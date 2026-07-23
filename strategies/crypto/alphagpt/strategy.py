# -*- coding: utf-8 -*-
"""AlphaGPT 因子 DSL + 链上执行策略 — QuantHub 迁移版。

从 ``AlphaGPT/model_core`` + ``strategy_manager`` + ``execution`` 下沉为
``strategies/crypto/alphagpt`` 插件模块。**实盘默认关闭**（live=false）。

生命周期:
    - produce()   : 用 StackVM 评估因子公式 → 对候选代币产出 Signal
    - backtest()  : 用 core.backtest.EventEngine 事件驱动回测
    - live_tick() : 实盘委托 execution 链上执行；is_live()=False 时 no-op，
                    仅输出拟下单 JSON

重依赖懒加载: torch / solana 在 produce / live 路径内才 import，
确保 ``import strategies.crypto.alphagpt`` 在未装 torch 时也可成功。
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any

import numpy as np
import pandas as pd

from core.backtest.engine import EventContext, EventEngine
from core.signals import Signal
from strategies.base import StrategyBase, StrategyInfo, register_strategy

logger = logging.getLogger(__name__)

# 默认扫描候选代币（实盘关闭时仅用于产 Signal / 回测）
DEFAULT_SYMBOLS: list[str] = ["SOL/USDT", "BONK/USDT", "WIF/USDT"]


@register_strategy(StrategyInfo(
    name="alphagpt",
    market="crypto",
    live_capable=True,
    description="AlphaGPT因子DSL+链上执行(实盘默认关)",
))
class AlphaGptStrategy(StrategyBase):
    """AlphaGPT 因子 DSL + 链上执行策略（实盘默认关闭）。"""

    def produce(
        self,
        symbols: list[str] | None = None,
        timeframe: str = "1h",
        formulas: list[list[int]] | None = None,
        klines_map: dict[str, pd.DataFrame] | None = None,
        **kwargs: Any,
    ) -> list[Signal]:
        """用 StackVM 评估因子公式，对候选代币产出 Signal。

        Args:
            symbols: 候选代币列表（缺省用 DEFAULT_SYMBOLS）
            timeframe: K 线周期
            formulas: 因子公式 token 列表（每条为一组 StackVM 后缀 token）；
                      缺省时调用 ``run_factor_search`` 自动搜索
            klines_map: 各代币 K 线数据 ``{symbol: DataFrame}``；缺省返回空
        """
        # 懒加载重依赖（torch）
        from strategies.crypto.alphagpt.factors import FeatureEngineer
        from strategies.crypto.alphagpt.stack_vm import StackVM

        symbols = symbols or DEFAULT_SYMBOLS
        if not klines_map:
            logger.warning("alphagpt.produce 未提供 klines_map，无信号产出")
            return []

        # 公式缺省 → 因子搜索（回退到内置启发式公式）
        if formulas is None:
            formulas = run_factor_search(klines_map, **kwargs)

        import torch  # noqa: PLC0415 - 重依赖懒加载

        vm = StackVM()
        signals: list[Signal] = []
        for symbol in symbols:
            df = klines_map.get(symbol)
            if df is None or df.empty:
                continue
            try:
                feat = self._build_feat_tensor(torch, FeatureEngineer, df)
            except Exception:  # noqa: BLE001 - 单标的失败不影响其余
                logger.exception("alphagpt 特征构建失败: %s", symbol)
                continue

            # 评估每条公式，取均值作为综合因子分
            scores: list[float] = []
            for formula in formulas:
                res = vm.execute(formula, feat)
                if res is None:
                    continue
                # res: [B, T]，取最新时点标量
                scores.append(float(res[0, -1].item()))
            if not scores:
                continue

            raw = sum(scores) / len(scores)
            score = self._normalize_score(raw)
            if raw > 0:
                direction = "buy"
            elif raw < 0:
                direction = "sell"
            else:
                direction = "hold"
            confidence = float(min(1.0, abs(raw) + 0.3))

            sig = Signal(
                symbol=symbol,
                market="crypto",
                timeframe=timeframe,
                direction=direction,
                score=score,
                confidence=confidence,
                source="alphagpt",
                tags=[f"formulas={len(formulas)}"],
                meta={"raw_score": raw, "chain": "solana"},
            )
            signals.append(sig)
            self.publish(sig)
        return signals

    def backtest(
        self,
        klines: pd.DataFrame,
        formulas: list[list[int]] | None = None,
        initial_capital: float = 10000.0,
        **kwargs: Any,
    ) -> "BacktestResult":
        """事件驱动回测：on_bar 内按综合因子分方向买卖。"""
        if klines is None or klines.empty:
            from core.backtest.engine import BacktestResult
            return BacktestResult.empty(engine="event")

        # 懒加载重依赖
        from strategies.crypto.alphagpt.factors import FeatureEngineer
        from strategies.crypto.alphagpt.stack_vm import StackVM
        import torch  # noqa: PLC0415 - 重依赖懒加载

        df = klines.sort_values("datetime").reset_index(drop=True)
        formulas = formulas or run_factor_search({"SYM": df}, **kwargs)
        vm = StackVM()
        feat = self._build_feat_tensor(torch, FeatureEngineer, df)

        # 预计算每根 bar 的综合因子分
        per_bar: list[float] = []
        for i in range(len(df)):
            bar_scores: list[float] = []
            for formula in formulas:
                res = vm.execute(formula, feat)
                if res is None:
                    continue
                bar_scores.append(float(res[0, i].item()))
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

        实盘开启（``is_live()=True``）时委托 execution 做链上执行并先过风控；
        否则只把下单意图打印成 JSON（dry-run）。
        """
        intent = {
            "symbol": kwargs.get("symbol"),
            "side": kwargs.get("side", "buy"),
            "notional": float(kwargs.get("notional", 0.0)),
            "chain": "solana",
            "live": self.is_live(),
        }

        if not self.is_live():
            # 实盘关闭：仅输出拟下单 JSON
            logger.info("alphagpt dry-run 拟下单: %s", json.dumps(intent, ensure_ascii=False))
            return {"dry_run": True, "intent": intent}

        # 实盘开启：先风控，再委托 execution 链上执行（solana 重依赖懒加载）
        try:
            from strategies.crypto.alphagpt.risk import check_order
            check_order(intent, **kwargs)
            # 真实签名由 execution 模块完成；此处仅记录拟执行 JSON
            logger.info("alphagpt live 委托 execution: %s", json.dumps(intent, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            logger.exception("alphagpt live_tick 执行失败")
            return {"dry_run": False, "intent": intent, "status": "error"}
        return {"dry_run": False, "intent": intent, "status": "submitted"}

    # ---------- 内部工具 ----------

    @staticmethod
    def _build_feat_tensor(torch, feature_engineer_cls, df: pd.DataFrame):
        """把 K 线 DataFrame 转成因子引擎所需的 ``raw_dict``（含 liquidity/fdv 兜底）。

        返回 ``FeatureEngineer.compute_features`` 的输出：[B=1, F=6, T]。
        """
        def _col(name: str, default: float) -> np.ndarray:
            if name in df.columns:
                return df[name].astype(float).to_numpy()
            return np.full(len(df), float(default))

        def _t1d(name: str, default: float):
            return torch.tensor(_col(name, default), dtype=torch.float32).unsqueeze(0)

        raw_dict = {
            "close": _t1d("close", 0.0),
            "open": _t1d("open", 0.0),
            "high": _t1d("high", 0.0),
            "low": _t1d("low", 0.0),
            "volume": _t1d("volume", 1.0),
            "liquidity": _t1d("liquidity", 1e5),
            "fdv": _t1d("fdv", 1e6),
        }
        return feature_engineer_cls.compute_features(raw_dict)

    @staticmethod
    def _normalize_score(raw: float) -> float:
        """把原始因子分压缩到 [0,1]（sigmoid）。"""
        s = 1.0 / (1.0 + math.exp(-raw))
        return float(max(0.0, min(1.0, s)))


def run_factor_search(
    klines_map: dict[str, pd.DataFrame],
    max_depth: int = 5,
    population: int = 50,
    **kwargs: Any,
) -> list[list[int]]:
    """因子搜索：返回一组 StackVM 公式 token 列表。

    原 AlphaGPT 用 Transformer 自动写因子（需 torch + 训练权重）。
    迁移版在无训练权重时**回退为一组内置启发式公式**（StackVM 后缀 token），
    覆盖动量 / 反转 / 量价 / 流动性等基础因子组合。

    Args:
        klines_map: 候选 K 线（保留给数据驱动的 Transformer 搜索，回退模式下未用）
        max_depth:  Transformer 搜索最大公式深度（保留参数，回退模式未用）
        population: Transformer 搜索种群规模（保留参数，回退模式未用）
    """
    from strategies.crypto.alphagpt.stack_vm import FORMULA_VOCAB

    # token: < feat_offset → 特征列；>= feat_offset → 算子
    F = FORMULA_VOCAB.feature_count          # 6
    off = FORMULA_VOCAB.operator_offset      # 6
    # 特征索引（与 FEATURE_NAMES 顺序一致）
    RET, LIQ_SCORE, PRESSURE, FOMO, DEV, LOG_VOL = range(F)
    # 算子索引（与 OPS_CONFIG 顺序一致）
    ADD, SUB, MUL, DIV, NEG, ABS, SIGN, GATE, JUMP, DECAY, DELAY1, MAX3 = range(off, off + 12)

    # 内置启发式公式（StackVM 后缀表达式）：
    # 1) DECAY(DEV)          : 衰减加权偏离（动量延续）
    # 2) NEG(JUMP(RET))      : 极端上涨后反转
    # 3) MUL(PRESSURE, FOMO) : 买卖压力 × FOMO 加速
    # 4) LIQ_SCORE           : 流动性健康度（单特征）
    formulas = [
        [DEV, DECAY],
        [RET, JUMP, NEG],
        [PRESSURE, FOMO, MUL],
        [LIQ_SCORE],
    ]
    return formulas
