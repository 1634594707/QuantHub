# -*- coding: utf-8 -*-
"""AlphaMaster MT5 因子引擎适配器 — QuantHub 迁移版。

从 ``AlphaMaster-main/model_core``（MT5FeatureEngineer + StackVM）下沉为
``strategies/mt5/alphamaster`` 插件模块，覆盖 MT5 外汇 · 贵金属 · 股指
这第三类资产。**实盘默认关闭**（live=false）。

设计要点（与 crypto/alphagpt 同源但互不污染）：
    - 通过 sys.path 注入 AlphaMaster-main 根目录，直接复用其因子引擎
      （命名空间包 model_core.features / model_core.vm），**不复制 152 个文件**。
    - 重依赖（torch / model_core）全部懒加载：``import strategies.mt5.alphamaster``
      本身不触发 torch import，仅在 produce / backtest / live 路径内 import。
    - 不 import AlphaMaster 的 ``config``（其无条件 ``from dotenv import load_dotenv``
      在离线环境会失败）。``compute_target_positions`` 在本模块内等价重实现
      （tanh 连续仓位 + MIN_TRADE_EXPOSURE 阈值），无需 AlphaMaster 配置。

K 线数据：经 core.data_feed 的 LocalParquetSource 零拷贝读取
``data/MT5_K线数据/{SYMBOL}_{TF}.parquet``（与 AlphaMaster 同源）。

因子公式来源（优先级）：
    1. 模块目录下的 ``best_mt5_strategy.json``（由 AlphaMaster 训练产出，
       token 列表，vocab 版本需匹配 model_core.vocab.FORMULA_VOCAB）。
    2. 缺省/无效时回退为内置启发式 MT5 公式（纯特征 token，见 run_factor_search）。
"""
from __future__ import annotations

import json
import logging
import math
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core.signals import Signal
from strategies.base import StrategyBase, StrategyInfo, register_strategy

logger = logging.getLogger(__name__)

# AlphaMaster-main 仓库根（vendored 归档，相对本文件上溯 4 级 + vendored/）
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ALPHAMASTER_ROOT = REPO_ROOT / "vendored" / "AlphaMaster-main"

# 默认扫描品种（与 AlphaMaster TRAINABLE_SYMBOLS 对齐的子集，仅取已有本地数据的）
DEFAULT_SYMBOLS: list[str] = [
    "EURUSD", "USDJPY",
    "XAUUSD", "XAGUSD",
    "US30.cash", "US100.cash", "US500.cash", "US2000.cash",
    "JP225.cash",
]

# 连续仓位阈值：|tanh(factor)| 小于该值的信号被视为空仓（与 AlphaMaster 一致）
MIN_TRADE_EXPOSURE: float = 0.05

# 内置启发式 fallback 公式（纯特征 token，无需算子）：
#   RET20       (idx 2)  : 20 周期收益 — 趋势动量
#   DEV         (idx 9)  : 偏离/反转 — 均值回复
#   MACD_HIST  (idx 23) : MACD 柱 — 动量加速
# 三者取均值作为综合因子分，方向由 tanh 决定。
_FALLBACK_FORMULAS: list[list[int]] = [[2], [9], [23]]


def _inject_alpha_master_root() -> None:
    """把 AlphaMaster-main 根目录注入 sys.path（仅追加，避免遮蔽 QuantHub 同名模块）。

    其 ``model_core`` 命名空间包与 QuantHub 的 core/strategies/apps 不冲突，
    追加到末尾即可被唯一解析。
    """
    root = str(ALPHAMASTER_ROOT)
    if root not in sys.path:
        sys.path.append(root)


def compute_target_positions(factors) -> Any:
    """连续仓位 [-1, +1]（收益优先模式，等价重实现 AlphaMaster signal.py）。

    Args:
        factors: torch.Tensor，形状 [N, T] 或 [N]，单元素标量因子。
    Returns:
        经 tanh 压缩、并在 |pos| < MIN_TRADE_EXPOSURE 时置零的仓位张量。
    """
    import torch  # 懒加载
    pos = torch.tanh(factors)
    if MIN_TRADE_EXPOSURE > 0:
        pos = torch.where(
            pos.abs() >= MIN_TRADE_EXPOSURE,
            pos,
            torch.zeros_like(pos),
        )
    return pos


@register_strategy(StrategyInfo(
    name="alphamaster",
    market="mt5",
    live_capable=True,
    description="AlphaMaster MT5因子引擎(外汇/贵金属/股指, 实盘默认关)",
))
class AlphaMasterStrategy(StrategyBase):
    """AlphaMaster MT5 因子引擎适配器（实盘默认关闭）。"""

    def produce(
        self,
        symbols: list[str] | None = None,
        timeframe: str = "1h",
        formulas: list[list[int]] | None = None,
        klines_map: dict[str, pd.DataFrame] | None = None,
        **kwargs: Any,
    ) -> list[Signal]:
        """用 StackVM 评估因子公式，对 MT5 品种产出 Signal。

        Args:
            symbols:     候选品种列表（缺省用 DEFAULT_SYMBOLS）
            timeframe:   K 线周期（对齐 LocalParquetSource 的 tf_map，默认 1h）
            formulas:    因子公式 token 列表；缺省时加载 best_mt5_strategy.json，
                        失败则回退到内置启发式公式
            klines_map:  各品种 K 线数据 ``{symbol: DataFrame}``；缺省时通过
                        ``get_data_source('mt5')`` 从本地 parquet 读取
        """
        symbols = symbols or self.config.get("symbols") or DEFAULT_SYMBOLS
        timeframe = self.config.get("timeframe", timeframe)
        if not klines_map:
            klines_map = self._load_klines(symbols, timeframe)
            if not klines_map:
                logger.warning("alphamaster.produce 未能加载任何 K 线，无信号产出")
                return []

        if formulas is None:
            formulas = self._load_formulas()

        import torch  # 懒加载重依赖
        _inject_alpha_master_root()
        from model_core.features import MT5FeatureEngineer
        from model_core.vm import StackVM

        vm = StackVM()
        signals: list[Signal] = []
        for symbol in symbols:
            df = klines_map.get(symbol)
            if df is None or df.empty or len(df) < 50:
                continue  # 数据不足，跳过（特征在短序列上会退化）
            try:
                raw_dict = self._df_to_raw_dict(df)
                feat = MT5FeatureEngineer.compute_features(raw_dict)  # [1, 65, T]
            except Exception:  # noqa: BLE001 - 单标的失败不影响其余
                logger.exception("alphamaster 特征构建失败: %s", symbol)
                continue

            # 评估每条公式，取最新时点标量，再取均值作为综合因子分
            scores: list[float] = []
            for formula in formulas:
                try:
                    res = vm.execute(formula, feat)
                except Exception:  # noqa: BLE001
                    continue
                if res is None:
                    continue
                try:
                    scores.append(float(res[0, -1].item()))
                except Exception:  # noqa: BLE001
                    continue
            if not scores:
                continue

            raw = sum(scores) / len(scores)
            # 连续仓位：tanh 压缩到 (-1, +1)，低于阈值置零
            pos = float(compute_target_positions(torch.tensor([raw]))[0].item())
            if pos > 0:
                direction = "buy"
            elif pos < 0:
                direction = "sell"
            else:
                direction = "hold"
            strength = abs(pos)  # 已在 [0,1]

            sig = Signal(
                symbol=symbol,
                market="mt5",
                timeframe=timeframe,
                direction=direction,
                score=strength,
                confidence=strength,
                source="alphamaster",
                tags=[f"formulas={len(formulas)}", f"bars={len(df)}"],
                meta={"raw_factor": raw, "engine": "AlphaMaster-MT5"},
            )
            signals.append(sig)
            self.publish(sig)
        return signals

    # ---------- 数据加载 ----------

    def _load_klines(self, symbols: list[str], timeframe: str) -> dict[str, pd.DataFrame]:
        """经 core.data_feed 的 LocalParquetSource 读取本地 MT5 K 线。"""
        from core.data_feed.factory import get_data_source
        try:
            src = get_data_source("mt5")
        except Exception:  # noqa: BLE001
            logger.exception("alphamaster 无法构建 mt5 数据源")
            return {}
        out: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                df = src.get_kline(sym, timeframe, limit=5000)
            except Exception:  # noqa: BLE001
                logger.warning("alphamaster 读取 %s %s 失败", sym, timeframe)
                continue
            if df is not None and not df.empty:
                out[sym] = df
        return out

    @staticmethod
    def _df_to_raw_dict(df: pd.DataFrame) -> dict:
        """把 K 线 DataFrame 转为 MT5FeatureEngineer 所需的 raw_dict。

        返回每个键为形状 [N=1, T] 的 float32 张量，键集仅含引擎实际读取的
        close / open / high / low / volume。
        """
        import torch  # 懒加载

        def _t1d(col: str) -> Any:
            arr = df[col].astype(float).to_numpy() if col in df.columns \
                else np.zeros(len(df), dtype=float)
            return torch.tensor(arr, dtype=torch.float32).unsqueeze(0)

        return {
            "close": _t1d("close"),
            "open": _t1d("open"),
            "high": _t1d("high"),
            "low": _t1d("low"),
            "volume": _t1d("volume"),
        }

    # ---------- 公式加载 ----------

    def _load_formulas(self) -> list[list[int]]:
        """加载因子公式；无效/缺失时回退到内置启发式。"""
        json_path = Path(__file__).resolve().parent / "best_mt5_strategy.json"
        if json_path.exists():
            try:
                with json_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                formula = data.get("formula") or data.get("formula_tokens")
                if isinstance(formula, list) and formula and all(
                    isinstance(t, int) for t in (formula[0] if isinstance(formula[0], list) else formula)
                ):
                    # 兼容 "formula": [tokens] 或 "formula": [[tokens], ...]
                    if isinstance(formula[0], list):
                        logger.info("alphamaster 加载训练公式 %d 条（来自 %s）", len(formula), json_path.name)
                        return [list(map(int, f)) for f in formula]
                    logger.info("alphamaster 加载训练公式 1 条（来自 %s）", json_path.name)
                    return [list(map(int, formula))]
            except Exception:  # noqa: BLE001
                logger.warning("alphamaster 读取 %s 失败，回退启发式公式", json_path.name)
        return run_factor_search()

    # ---------- 回测 / 实盘 ----------

    def backtest(
        self,
        klines: pd.DataFrame,
        formulas: list[list[int]] | None = None,
        initial_capital: float = 10000.0,
        **kwargs: Any,
    ) -> "BacktestResult":
        """事件驱动回测：on_bar 内按综合因子分方向交易。"""
        if klines is None or klines.empty:
            from core.backtest.engine import BacktestResult
            return BacktestResult.empty(engine="event")

        import torch  # 懒加载
        _inject_alpha_master_root()
        from core.backtest.engine import EventContext, EventEngine
        from model_core.features import MT5FeatureEngineer
        from model_core.vm import StackVM

        df = klines.sort_values("datetime").reset_index(drop=True)
        formulas = formulas or self._load_formulas()
        vm = StackVM()
        feat = MT5FeatureEngineer.compute_features(self._df_to_raw_dict(df))

        per_bar: list[float] = []
        for i in range(len(df)):
            bar_scores: list[float] = []
            for formula in formulas:
                try:
                    res = vm.execute(formula, feat)
                except Exception:  # noqa: BLE001
                    continue
                if res is None:
                    continue
                try:
                    bar_scores.append(float(res[0, i].item()))
                except Exception:  # noqa: BLE001
                    continue
            per_bar.append(sum(bar_scores) / len(bar_scores) if bar_scores else 0.0)

        state = {"i": 0}

        def on_bar(bar: pd.Series, ctx: EventContext) -> None:
            i = state["i"]
            raw = per_bar[i] if i < len(per_bar) else 0.0
            price = float(bar["close"])
            ts = bar.get("datetime")
            if raw > 0.2 and ctx.position == 0.0:
                qty = ctx.cash / (price * (1 + ctx.commission))
                if qty > 0:
                    ctx.buy(price, qty, ts)
            elif raw < -0.2 and ctx.position > 0.0:
                ctx.sell(price, ctx.position, ts)
            state["i"] += 1

        engine = EventEngine(initial_capital=initial_capital)
        result = engine.run(df, on_bar)
        return {
            "engine": result.engine,
            "metrics": result.metrics,
            "final_equity": result.final_equity,
            "total_return": result.total_return,
            "max_drawdown": result.max_drawdown,
            "trades": result.trades,
        }

    def live_tick(self, **kwargs: Any) -> dict | None:
        """实盘 tick：实盘关闭时 no-op，仅输出拟下单 JSON。

        实盘开启（``is_live()=True``）时输出下单意图（MT5 执行通道为后续扩展，
        本期不接入 broker）。
        """
        intent = {
            "symbol": kwargs.get("symbol"),
            "side": kwargs.get("side", "buy"),
            "notional": float(kwargs.get("notional", 0.0)),
            "market": "mt5",
            "live": self.is_live(),
        }
        if not self.is_live():
            logger.info("alphamaster dry-run 拟下单: %s", json.dumps(intent, ensure_ascii=False))
            return {"dry_run": True, "intent": intent}
        logger.info("alphamaster live 下单意图: %s", json.dumps(intent, ensure_ascii=False))
        return {"dry_run": False, "intent": intent, "status": "submitted"}


def run_factor_search(
    klines_map: dict[str, pd.DataFrame] | None = None,
    **kwargs: Any,
) -> list[list[int]]:
    """MT5 因子搜索便捷入口。

    AlphaMaster 用 Transformer（AlphaGPT）自动写因子（需 torch + 训练权重）。
    迁移版在无 ``best_mt5_strategy.json`` 时**回退为一组内置启发式公式**
    （纯特征 token，覆盖趋势 / 反转 / 动量），无需算子即可被 StackVM 评估。
    """
    return [list(f) for f in _FALLBACK_FORMULAS]
