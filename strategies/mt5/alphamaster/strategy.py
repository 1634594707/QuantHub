"""AlphaMaster MT5 因子引擎适配器 — QuantHub 迁移版。

从 ``AlphaMaster-main/model_core``（MT5FeatureEngineer + StackVM）下沉为
``strategies/mt5/alphamaster`` 插件模块，覆盖 MT5 外汇 · 贵金属 · 股指
这第三类资产。**实盘默认关闭**（live=false）。

设计要点（与 crypto/alphagpt 同源但互不污染）：
    - 通过 sys.path 注入策略内置的 AlphaMaster 最小运行时，复用其因子引擎
      （命名空间包 model_core.features / model_core.vm）。
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
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core.signals import Signal
from strategies.base import StrategyBase, StrategyInfo, register_strategy

logger = logging.getLogger(__name__)

# AlphaMaster 最小运行时随策略内置，避免依赖庞大的 vendored 归档。
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ALPHAMASTER_ROOT = Path(__file__).resolve().parent / "_upstream"

# 默认扫描品种（与 AlphaMaster TRAINABLE_SYMBOLS 对齐的子集，仅取已有本地数据的）
DEFAULT_SYMBOLS: list[str] = [
    "EURUSD",
    "USDJPY",
    "XAUUSD",
    "XAGUSD",
    "US30.cash",
    "US100.cash",
    "US500.cash",
    "US2000.cash",
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


class FormulaValidationError(ValueError):
    """AlphaMaster 公式 token 与当前引擎不兼容。"""


def _inject_alpha_master_root() -> None:
    """把内置 AlphaMaster 运行时注入 sys.path（仅追加，避免遮蔽同名模块）。

    其 ``model_core`` 命名空间包与 QuantHub 的 core/strategies/apps 不冲突，
    追加到末尾即可被唯一解析。
    """
    root = str(ALPHAMASTER_ROOT)
    if root not in sys.path:
        sys.path.append(root)


def compute_target_positions(
    factors,
    min_trade_exposure: float = MIN_TRADE_EXPOSURE,
) -> Any:
    """连续仓位 [-1, +1]（收益优先模式，等价重实现 AlphaMaster signal.py）。

    Args:
        factors: torch.Tensor，形状 [N, T] 或 [N]，单元素标量因子。
    Returns:
        经 tanh 压缩、并在 |pos| < MIN_TRADE_EXPOSURE 时置零的仓位张量。
    """
    import torch  # 懒加载

    pos = torch.tanh(factors)
    if min_trade_exposure > 0:
        pos = torch.where(
            pos.abs() >= min_trade_exposure,
            pos,
            torch.zeros_like(pos),
        )
    return pos


def _normalize_formulas(formulas: Any) -> list[list[int]]:
    """兼容单公式 ``[tokens]`` 与公式集合 ``[[tokens], ...]``。"""
    if not isinstance(formulas, list) or not formulas:
        raise FormulaValidationError("公式不能为空")
    candidates = [formulas] if all(isinstance(token, int) for token in formulas) else formulas
    normalized: list[list[int]] = []
    for index, formula in enumerate(candidates):
        if not isinstance(formula, list) or not formula:
            raise FormulaValidationError(f"第 {index + 1} 条公式为空或不是 token 列表")
        if any(isinstance(token, bool) or not isinstance(token, int) for token in formula):
            raise FormulaValidationError(f"第 {index + 1} 条公式包含非整数 token")
        normalized.append([int(token) for token in formula])
    return normalized


def validate_formulas(formulas: Any) -> list[list[int]]:
    """按上游动态词表和 StackVM 栈规则校验公式。"""
    normalized = _normalize_formulas(formulas)
    _inject_alpha_master_root()
    from model_core.ops import OPS_CONFIG
    from model_core.vocab import FORMULA_VOCAB

    operator_arity = {
        FORMULA_VOCAB.operator_offset + index: int(config[2])
        for index, config in enumerate(OPS_CONFIG)
    }
    for formula_index, formula in enumerate(normalized):
        depth = 0
        for token_index, token in enumerate(formula):
            if token < 0 or token >= FORMULA_VOCAB.size:
                raise FormulaValidationError(
                    f"第 {formula_index + 1} 条公式的 token[{token_index}]={token} "
                    f"超出当前词表范围 0..{FORMULA_VOCAB.size - 1}"
                )
            if token < FORMULA_VOCAB.operator_offset:
                depth += 1
                continue
            arity = operator_arity.get(token)
            if arity is None or depth < arity:
                name = FORMULA_VOCAB.token_names[token]
                raise FormulaValidationError(
                    f"第 {formula_index + 1} 条公式在 {name} 处缺少操作数"
                )
            depth = depth - arity + 1
        if depth != 1:
            raise FormulaValidationError(
                f"第 {formula_index + 1} 条公式执行后栈深度为 {depth}，应为 1"
            )
    return normalized


def describe_formulas(formulas: Any) -> list[dict[str, Any]]:
    """返回公式 token、可读名称和上游结构风险提示。"""
    normalized = validate_formulas(formulas)
    _inject_alpha_master_root()
    from model_core.vm import validate_formula_structure
    from model_core.vocab import FORMULA_VOCAB, VOCAB_VERSION

    return [
        {
            "tokens": formula,
            "expression": " -> ".join(FORMULA_VOCAB.token_names[token] for token in formula),
            "warnings": validate_formula_structure(formula, FORMULA_VOCAB.token_names),
            "vocab_version": VOCAB_VERSION,
        }
        for formula in normalized
    ]


def engine_info() -> dict[str, Any]:
    """AlphaMaster 引擎能力与当前 fallback 公式的可观测信息。"""
    try:
        import torch  # noqa: F401
    except ModuleNotFoundError:
        return {
            "available": False,
            "root": str(ALPHAMASTER_ROOT),
            "vocab_version": None,
            "vocab_schema": None,
            "feature_count": 0,
            "operator_count": 0,
            "fallback_formulas": [],
            "reason": "缺少可选依赖 torch",
            "install_command": "uv sync --extra heavy-torch",
        }

    _inject_alpha_master_root()
    from model_core.vocab import FORMULA_VOCAB, VOCAB_SCHEMA_TAG, VOCAB_VERSION

    return {
        "available": ALPHAMASTER_ROOT.exists(),
        "root": str(ALPHAMASTER_ROOT),
        "vocab_version": VOCAB_VERSION,
        "vocab_schema": VOCAB_SCHEMA_TAG,
        "feature_count": FORMULA_VOCAB.feature_count,
        "operator_count": len(FORMULA_VOCAB.operator_names),
        "fallback_formulas": describe_formulas(_FALLBACK_FORMULAS),
    }


@register_strategy(
    StrategyInfo(
        name="alphamaster",
        market="mt5",
        live_capable=True,
        description="AlphaMaster MT5因子引擎(外汇/贵金属/股指, 实盘默认关)",
    )
)
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
        else:
            formulas = validate_formulas(formulas)

        min_trade_exposure = float(
            kwargs.get(
                "min_trade_exposure",
                self.config.get("min_trade_exposure", MIN_TRADE_EXPOSURE),
            )
        )

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
            except Exception:
                logger.exception("alphamaster 特征构建失败: %s", symbol)
                continue

            # 评估每条公式，取最新时点标量，再取均值作为综合因子分
            scores: list[float] = []
            for formula in formulas:
                try:
                    res = vm.execute(formula, feat)
                except Exception:
                    continue
                if res is None:
                    continue
                try:
                    scores.append(float(res[0, -1].item()))
                except Exception:
                    continue
            if not scores:
                continue

            raw = sum(scores) / len(scores)
            # 连续仓位：tanh 压缩到 (-1, +1)，低于阈值置零
            pos = float(
                compute_target_positions(
                    torch.tensor([raw]), min_trade_exposure=min_trade_exposure
                )[0].item()
            )
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
                meta={
                    "raw_factor": raw,
                    "target_position": pos,
                    "formula_tokens": formulas,
                    "engine": "AlphaMaster-StackVM",
                },
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
        except Exception:
            logger.exception("alphamaster 无法构建 mt5 数据源")
            return {}
        out: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                df = src.get_kline(sym, timeframe, limit=5000)
            except Exception:
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
            arr = (
                df[col].astype(float).to_numpy()
                if col in df.columns
                else np.zeros(len(df), dtype=float)
            )
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
                _inject_alpha_master_root()
                from model_core.vocab import FORMULA_VOCAB

                artifact_version = data.get("vocab_version")
                if artifact_version:
                    FORMULA_VOCAB.verify(str(artifact_version))
                else:
                    logger.warning("alphamaster 策略产物缺少 vocab_version，按 legacy 校验")
                normalized = validate_formulas(formula)
                logger.info(
                    "alphamaster 加载训练公式 %d 条（来自 %s）",
                    len(normalized),
                    json_path.name,
                )
                return normalized
            except Exception as exc:
                logger.warning(
                    "alphamaster 读取 %s 失败，回退启发式公式: %s",
                    json_path.name,
                    exc,
                )
        return run_factor_search()

    # ---------- 回测 / 实盘 ----------

    def backtest(
        self,
        klines: pd.DataFrame,
        formulas: list[list[int]] | None = None,
        initial_capital: float = 10000.0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """按 AlphaMaster 原生连续仓位口径执行无前视偏差回测。"""
        if klines is None or klines.empty:
            from core.backtest.engine import BacktestResult

            return BacktestResult.empty(engine="event")

        _inject_alpha_master_root()
        from model_core.features import MT5FeatureEngineer
        from model_core.vm import StackVM

        sort_column = (
            "datetime"
            if "datetime" in klines and klines["datetime"].notna().any()
            else "bar_time"
            if "bar_time" in klines
            else None
        )
        df = (
            klines.sort_values(sort_column).reset_index(drop=True)
            if sort_column
            else klines.reset_index(drop=True)
        )
        formulas = validate_formulas(formulas or self._load_formulas())
        vm = StackVM()
        feat = MT5FeatureEngineer.compute_features(self._df_to_raw_dict(df))

        factor_tensors = [vm.execute(formula, feat) for formula in formulas]
        valid_factors = [factor for factor in factor_tensors if factor is not None]
        if not valid_factors:
            raise FormulaValidationError("没有公式能被 StackVM 执行")

        import torch

        factor = torch.stack(valid_factors).mean(dim=0)[0]
        min_trade_exposure = float(
            kwargs.get(
                "min_trade_exposure",
                self.config.get("min_trade_exposure", MIN_TRADE_EXPOSURE),
            )
        )
        position = (
            compute_target_positions(factor, min_trade_exposure=min_trade_exposure)
            .detach()
            .cpu()
            .numpy()
            .astype(float)
        )
        factor_values = factor.detach().cpu().numpy().astype(float)
        open_prices = df["open"].astype(float).to_numpy()
        target_return = np.zeros(len(df), dtype=float)
        if len(df) >= 3:
            target_return[:-2] = np.log(
                (open_prices[2:] + 1e-12) / (open_prices[1:-1] + 1e-12)
            )

        previous_position = np.zeros(len(df), dtype=float)
        previous_position[1:] = position[:-1]
        turnover = np.abs(position - previous_position)
        cost_rate = max(0.0, float(kwargs.get("cost_rate", 0.0001)))
        slippage_rate = max(0.0, float(kwargs.get("slippage_rate", 0.0001)))
        total_cost_rate = cost_rate + slippage_rate
        pnl = position * target_return - turnover * total_cost_rate
        cumulative_log_return = np.cumsum(pnl)
        equity_values = float(initial_capital) * np.exp(cumulative_log_return)

        timestamps = (
            df["datetime"].tolist()
            if "datetime" in df and df["datetime"].notna().any()
            else df["bar_time"].tolist()
            if "bar_time" in df
            else list(range(len(df)))
        )
        trades = self._extract_continuous_trades(
            position=position,
            open_prices=open_prices,
            timestamps=timestamps,
            pnl=pnl,
            initial_capital=float(initial_capital),
            min_trade_exposure=min_trade_exposure,
        )
        periods_per_year = max(1, int(kwargs.get("periods_per_year", 6240)))
        metrics = self._continuous_metrics(
            pnl=pnl,
            equity=equity_values,
            trades=trades,
            turnover=turnover,
            position=position,
            periods_per_year=periods_per_year,
        )
        formula_details = describe_formulas(formulas)
        equity_curve = pd.DataFrame(
            {
                "datetime": timestamps,
                "equity": equity_values,
                "factor": factor_values,
                "position": position,
            }
        )
        return {
            "engine": "alphamaster-continuous",
            "metrics": {
                **metrics,
                "formula_count": len(formulas),
                "vocab_version": formula_details[0]["vocab_version"],
                "formula_warnings": [
                    warning
                    for item in formula_details
                    for warning in item["warnings"]
                ],
            },
            "final_equity": float(equity_values[-1]),
            "total_return": float(equity_values[-1] / initial_capital - 1.0),
            "max_drawdown": metrics["max_drawdown"],
            "trades": trades,
            "equity_curve": equity_curve,
            "formulas": formula_details,
        }

    @staticmethod
    def _extract_continuous_trades(
        *,
        position: np.ndarray,
        open_prices: np.ndarray,
        timestamps: list[Any],
        pnl: np.ndarray,
        initial_capital: float,
        min_trade_exposure: float,
    ) -> list[dict[str, Any]]:
        """把连续仓位的方向切换整理为完整多空交易。"""
        trades: list[dict[str, Any]] = []
        current_direction = 0
        entry_bar = 0

        def direction(value: float) -> int:
            if value >= min_trade_exposure:
                return 1
            if value <= -min_trade_exposure:
                return -1
            return 0

        def execution_index(signal_bar: int) -> int:
            return min(signal_bar + 1, len(open_prices) - 1)

        def close_trade(exit_bar: int) -> None:
            execution_entry = execution_index(entry_bar)
            execution_exit = execution_index(exit_bar)
            log_return = float(pnl[entry_bar:exit_bar].sum())
            trades.append(
                {
                    "direction": "long" if current_direction > 0 else "short",
                    "entry_time": str(timestamps[execution_entry]),
                    "exit_time": str(timestamps[execution_exit]),
                    "entry_price": float(open_prices[execution_entry]),
                    "exit_price": float(open_prices[execution_exit]),
                    "pnl": float(initial_capital * math.expm1(log_return)),
                    "return_pct": float(math.expm1(log_return) * 100),
                    "hold_bars": max(0, exit_bar - entry_bar),
                    "avg_exposure": float(np.abs(position[entry_bar:exit_bar]).mean())
                    if exit_bar > entry_bar
                    else 0.0,
                }
            )

        for bar, value in enumerate(position):
            new_direction = direction(float(value))
            if new_direction == current_direction:
                continue
            if current_direction != 0:
                close_trade(bar)
            current_direction = new_direction
            entry_bar = bar

        if current_direction != 0:
            close_trade(len(position))
        return trades

    @staticmethod
    def _continuous_metrics(
        *,
        pnl: np.ndarray,
        equity: np.ndarray,
        trades: list[dict[str, Any]],
        turnover: np.ndarray,
        position: np.ndarray,
        periods_per_year: int,
    ) -> dict[str, float | int | None]:
        mean_return = float(np.mean(pnl)) if len(pnl) else 0.0
        std_return = float(np.std(pnl)) if len(pnl) else 0.0
        downside = pnl[pnl < 0]
        downside_std = float(np.std(downside)) if len(downside) else 0.0
        sharpe = (
            mean_return / std_return * math.sqrt(periods_per_year)
            if std_return > 1e-12
            else 0.0
        )
        sortino = (
            mean_return / downside_std * math.sqrt(periods_per_year)
            if downside_std > 1e-12
            else 0.0
        )
        peaks = np.maximum.accumulate(equity)
        drawdown = equity / np.maximum(peaks, 1e-12) - 1.0
        max_drawdown = abs(float(drawdown.min())) if len(drawdown) else 0.0
        wins = [float(trade["pnl"]) for trade in trades if float(trade["pnl"]) > 0]
        losses = [abs(float(trade["pnl"])) for trade in trades if float(trade["pnl"]) < 0]
        return {
            "annualized_log_return": mean_return * periods_per_year,
            "sharpe": float(np.clip(sharpe, -20.0, 20.0)),
            "sortino": float(np.clip(sortino, -20.0, 20.0)),
            "max_drawdown": max_drawdown,
            "win_rate": len(wins) / len(trades) if trades else 0.0,
            "profit_factor": sum(wins) / sum(losses) if losses else None,
            "average_hold_bars": float(
                np.mean([trade["hold_bars"] for trade in trades])
            )
            if trades
            else 0.0,
            "average_exposure": float(np.mean(np.abs(position))) if len(position) else 0.0,
            "turnover": float(np.sum(turnover)),
            "n_trades": len(trades),
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
    return validate_formulas([list(f) for f in _FALLBACK_FORMULAS])
