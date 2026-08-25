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

因子公式必须由调用方显式提供，或由模块目录中的
``best_mt5_strategy.json`` 训练产物提供；产物缺失、无效或词表不匹配时 fail-closed，
不使用内置启发式公式替代。
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

from core.data_feed.quality import ohlcv_rejection_reason
from core.signals import Signal
from strategies.base import StrategyBase, StrategyInfo, register_strategy

logger = logging.getLogger(__name__)

# AlphaMaster 最小运行时随策略内置，避免依赖庞大的 vendored 归档。
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ALPHAMASTER_ROOT = Path(__file__).resolve().parent / "_upstream"
_TRAINED_ARTIFACT_PATH = Path(__file__).resolve().parent / "best_mt5_strategy.json"

# 连续仓位阈值：|tanh(factor)| 小于该值的信号被视为空仓（与 AlphaMaster 一致）
MIN_TRADE_EXPOSURE: float = 0.05


class FormulaValidationError(ValueError):
    """AlphaMaster 公式 token 与当前引擎不兼容。"""


class FormulaEvaluationError(RuntimeError):
    """AlphaMaster 公式执行或结果校验失败，禁止用剩余公式替代。"""


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
    """按受控源码词表和 StackVM 栈规则校验公式，无需导入 torch。"""
    from strategies.mt5.alphamaster.formula_adapter import validate_formulas as validate

    try:
        return validate(formulas)
    except (TypeError, ValueError) as exc:
        raise FormulaValidationError(str(exc)) from exc


def describe_formulas(formulas: Any) -> list[dict[str, Any]]:
    """返回公式 token、可读名称和版本信息，无需导入 torch。"""
    from strategies.mt5.alphamaster.formula_adapter import describe_formulas as describe

    return [{**item, "warnings": []} for item in describe(formulas)]


def engine_info() -> dict[str, Any]:
    """AlphaMaster 引擎能力与训练产物要求的可观测信息。"""
    from strategies.mt5.alphamaster.formula_adapter import vocab_manifest

    manifest = vocab_manifest()
    try:
        import torch  # noqa: F401
    except ModuleNotFoundError:
        return {
            "available": False,
            "root": str(ALPHAMASTER_ROOT),
            "vocab_version": manifest["version"],
            "vocab_schema": manifest["schema"],
            "feature_count": len(manifest["feature_names"]),
            "operator_count": len(manifest["operators"]),
            "requires_trained_artifact": True,
            "artifact_path": str(_TRAINED_ARTIFACT_PATH),
            "artifact_present": _TRAINED_ARTIFACT_PATH.exists(),
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
        "requires_trained_artifact": True,
        "artifact_path": str(_TRAINED_ARTIFACT_PATH),
        "artifact_present": _TRAINED_ARTIFACT_PATH.exists(),
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

    _REQUIRED_OHLCV = ("open", "high", "low", "close", "volume")

    @classmethod
    def _ohlcv_rejection_reason(cls, df: pd.DataFrame) -> str | None:
        """Reject malformed bars before feature construction or execution."""
        return ohlcv_rejection_reason(df, require_volume=True)

    def _reject_incomplete_market_data(
        self,
        *,
        source: str,
        symbols: list[str],
        failed_symbols: list[str],
        timeframe: str,
        reason: str,
    ) -> list[Signal]:
        """记录 MT5 primary 行情缺口并阻断整批因子信号。"""
        failed = list(dict.fromkeys(str(symbol) for symbol in failed_symbols))
        details = {
            "source": source,
            "market": "mt5",
            "symbols": [str(symbol) for symbol in symbols],
            "failed_symbols": failed,
            "timeframe": timeframe,
            "reason": reason,
        }
        self.last_report = {
            "kind": "alphamaster",
            "status": "unavailable",
            "degraded": True,
            "display_only": True,
            "execution_eligible": False,
            **details,
        }
        self.last_signal_rejection = {
            "code": "market_data_incomplete",
            "message": "MT5 primary 行情不完整，未发布 AlphaMaster 信号。",
            "details": details,
        }
        logger.warning(
            "alphamaster 因 primary 行情不完整而终止: source=%s failed_symbols=%s reason=%s",
            source,
            failed,
            reason,
        )
        return []

    def _reject_missing_symbols(self) -> list[Signal]:
        self.last_report = {
            "kind": "alphamaster",
            "status": "unavailable",
            "degraded": True,
            "display_only": True,
            "execution_eligible": False,
            "market": "mt5",
            "reason": "未提供显式 symbols 配置",
        }
        self.last_signal_rejection = {
            "code": "symbols_required",
            "message": "AlphaMaster 需要调用方显式提供 symbols，未使用示例标的回退。",
            "details": {"source": "alphamaster"},
        }
        return []

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
            symbols:     候选品种列表；必须由调用方或显式策略配置提供
            timeframe:   K 线周期（对齐 LocalParquetSource 的 tf_map，默认 1h）
            formulas:    因子公式 token 列表；缺省时加载 best_mt5_strategy.json，
                        产物缺失或无效时拒绝运行
            klines_map:  各品种 K 线数据 ``{symbol: DataFrame}``；缺省时通过
                        ``get_data_source('mt5')`` 从本地 parquet 读取
        """
        if symbols is None:
            symbols = self.config.get("symbols")
        if not symbols:
            logger.warning("alphamaster.produce 未提供显式 symbols，拒绝使用示例标的")
            return self._reject_missing_symbols()
        symbols = list(symbols)
        timeframe = self.config.get("timeframe", timeframe)
        self.last_report = None
        self.last_signal_rejection = None
        if formulas is None:
            formulas = self._load_formulas()
        else:
            formulas = validate_formulas(formulas)
        data_source = "provided"
        if not klines_map:
            data_source = getattr(self, "_last_data_source_name", "mt5_primary")
            klines_map = self._load_klines(symbols, timeframe)
            data_source = getattr(self, "_last_data_source_name", data_source)
            if not klines_map:
                logger.warning("alphamaster.produce 未能加载任何 K 线，无信号产出")
                failure = getattr(self, "_last_data_failure", None) or {
                    "failed_symbols": symbols,
                    "reason": "primary K 线为空",
                }
                return self._reject_incomplete_market_data(
                    source=data_source,
                    symbols=symbols,
                    failed_symbols=failure["failed_symbols"],
                    timeframe=timeframe,
                    reason=failure["reason"],
                )

        missing = [
            symbol
            for symbol in symbols
            if not isinstance(klines_map.get(symbol), pd.DataFrame)
            or klines_map[symbol].empty
            or len(klines_map[symbol]) < 50
        ]
        if missing:
            return self._reject_incomplete_market_data(
                source=data_source,
                symbols=symbols,
                failed_symbols=missing,
                timeframe=timeframe,
                reason="K 线为空或不足 50 根",
            )
        for symbol in symbols:
            quality_reason = self._ohlcv_rejection_reason(klines_map[symbol])
            if quality_reason is not None:
                return self._reject_incomplete_market_data(
                    source=data_source,
                    symbols=symbols,
                    failed_symbols=[symbol],
                    timeframe=timeframe,
                    reason=quality_reason,
                )

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
            try:
                raw_dict = self._df_to_raw_dict(df)
                feat = MT5FeatureEngineer.compute_features(raw_dict)  # [1, 65, T]
            except Exception as exc:
                logger.exception("alphamaster 特征构建失败: %s", symbol)
                return self._reject_incomplete_market_data(
                    source=data_source,
                    symbols=symbols,
                    failed_symbols=[symbol],
                    timeframe=timeframe,
                    reason=f"特征构建失败: {exc}",
                )

            # 评估每条公式，取最新时点标量，再取均值作为综合因子分
            scores: list[float] = []
            for formula in formulas:
                try:
                    res = vm.execute(formula, feat)
                except Exception as exc:  # noqa: BLE001 - preserve the primary formula failure
                    return self._reject_incomplete_market_data(
                        source=data_source,
                        symbols=symbols,
                        failed_symbols=[symbol],
                        timeframe=timeframe,
                        reason=f"公式执行失败: {exc}",
                    )
                if res is None:
                    return self._reject_incomplete_market_data(
                        source=data_source,
                        symbols=symbols,
                        failed_symbols=[symbol],
                        timeframe=timeframe,
                        reason="公式未返回评分",
                    )
                try:
                    score_value = float(res[0, -1].item())
                except Exception as exc:  # noqa: BLE001 - preserve malformed formula output
                    return self._reject_incomplete_market_data(
                        source=data_source,
                        symbols=symbols,
                        failed_symbols=[symbol],
                        timeframe=timeframe,
                        reason=f"公式结果无效: {exc}",
                    )
                if not math.isfinite(score_value):
                    return self._reject_incomplete_market_data(
                        source=data_source,
                        symbols=symbols,
                        failed_symbols=[symbol],
                        timeframe=timeframe,
                        reason="公式返回非有限评分",
                    )
                scores.append(score_value)
            if not scores:
                return self._reject_incomplete_market_data(
                    source=data_source,
                    symbols=symbols,
                    failed_symbols=[symbol],
                    timeframe=timeframe,
                    reason="没有可用公式评分",
                )

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

            try:
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
            except Exception as exc:
                logger.exception("alphamaster 信号构造失败: %s", symbol)
                return self._reject_incomplete_market_data(
                    source=data_source,
                    symbols=symbols,
                    failed_symbols=[symbol],
                    timeframe=timeframe,
                    reason=f"信号构造失败: {exc}",
                )
            signals.append(sig)
        for sig in signals:
            self.publish(sig)
        return signals

    # ---------- 数据加载 ----------

    def _load_klines(self, symbols: list[str], timeframe: str) -> dict[str, pd.DataFrame]:
        """经 core.data_feed 的 LocalParquetSource 读取本地 MT5 K 线。"""
        from core.data_feed.factory import get_data_source

        self._last_data_failure: dict[str, Any] | None = None
        self._last_data_source_name = "mt5_primary"
        try:
            src = get_data_source("mt5")
        except Exception as exc:
            logger.exception("alphamaster 无法构建 mt5 数据源")
            self._last_data_failure = {
                "failed_symbols": list(symbols),
                "reason": f"primary 数据源初始化失败: {exc}",
            }
            return {}
        self._last_data_source_name = str(getattr(src, "name", "mt5_primary"))
        out: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                df = src.get_kline(sym, timeframe, limit=5000)
            except Exception as exc:  # noqa: BLE001 - preserve primary failure details
                logger.warning("alphamaster 读取 %s %s 失败", sym, timeframe, exc_info=True)
                self._last_data_failure = {
                    "failed_symbols": [sym],
                    "reason": f"primary K 线请求失败: {exc}",
                }
                return {}
            if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                self._last_data_failure = {
                    "failed_symbols": [sym],
                    "reason": "primary K 线为空",
                }
                return {}
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
            if col not in df.columns:
                raise ValueError(f"K线缺少必需列: {col}")
            arr = df[col].astype(float).to_numpy()
            if not np.isfinite(arr).all():
                raise ValueError(f"K线列 {col} 含非有限值")
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
        """加载并校验训练产物中的公式，缺失或无效时拒绝运行。"""
        if not _TRAINED_ARTIFACT_PATH.exists():
            raise FormulaValidationError(f"训练产物不存在: {_TRAINED_ARTIFACT_PATH}")

        try:
            with _TRAINED_ARTIFACT_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise FormulaValidationError(
                f"无法读取训练产物 {_TRAINED_ARTIFACT_PATH.name}: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise FormulaValidationError("训练产物必须是 JSON 对象")
        formula = data.get("formula")
        if formula is None:
            formula = data.get("formula_tokens")
        artifact_version = data.get("vocab_version")
        if not isinstance(artifact_version, str) or not artifact_version:
            raise FormulaValidationError("训练产物缺少 vocab_version")

        from strategies.mt5.alphamaster.formula_adapter import vocab_manifest

        manifest = vocab_manifest()
        if artifact_version != manifest["version"]:
            raise FormulaValidationError(
                "词表版本不匹配："
                f"产物版本 {artifact_version!r} != 当前派生版本 {manifest['version']!r}"
            )
        artifact_schema = data.get("vocab_schema")
        if artifact_schema is not None and artifact_schema != manifest["schema"]:
            raise FormulaValidationError(
                "词表 schema 不匹配："
                f"产物 schema {artifact_schema!r} != 当前 schema {manifest['schema']!r}"
            )

        try:
            normalized = validate_formulas(formula)
        except FormulaValidationError as exc:
            raise FormulaValidationError(f"训练产物公式无效: {exc}") from exc
        logger.info(
            "alphamaster 加载训练公式 %d 条（来自 %s）",
            len(normalized),
            _TRAINED_ARTIFACT_PATH.name,
        )
        return normalized

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

        quality_reason = self._ohlcv_rejection_reason(klines)
        if quality_reason is not None:
            raise ValueError(f"K线质量不合格: {quality_reason}")

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
        formulas = self._load_formulas() if formulas is None else validate_formulas(formulas)
        vm = StackVM()
        feat = MT5FeatureEngineer.compute_features(self._df_to_raw_dict(df))

        factor_tensors = []
        for formula in formulas:
            try:
                factor = vm.execute(formula, feat)
            except Exception as exc:
                raise FormulaEvaluationError(f"公式执行失败: {exc}") from exc
            if factor is None:
                raise FormulaEvaluationError("公式未返回结果")
            factor_tensors.append(factor)
        if not factor_tensors:
            raise FormulaEvaluationError("没有可用公式评分")

        import torch

        try:
            factor = torch.stack(factor_tensors).mean(dim=0)[0]
        except Exception as exc:
            raise FormulaEvaluationError(f"公式结果无法聚合: {exc}") from exc
        if not bool(torch.isfinite(factor).all()):
            raise FormulaEvaluationError("公式聚合结果含非有限值")
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
            target_return[:-2] = np.log((open_prices[2:] + 1e-12) / (open_prices[1:-1] + 1e-12))

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
                    warning for item in formula_details for warning in item["warnings"]
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
            mean_return / std_return * math.sqrt(periods_per_year) if std_return > 1e-12 else 0.0
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
            "average_hold_bars": float(np.mean([trade["hold_bars"] for trade in trades]))
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
    """返回已验证训练产物中的公式，不在运行时生成启发式公式。"""
    return AlphaMasterStrategy(config={})._load_formulas()
