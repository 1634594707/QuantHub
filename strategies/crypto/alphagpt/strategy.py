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
from core.data_feed.quality import ohlcv_rejection_reason
from core.signals import Signal
from strategies.base import StrategyBase, StrategyInfo, register_strategy

logger = logging.getLogger(__name__)


class FormulaRequiredError(ValueError):
    """AlphaGPT 执行需要调用方提供经过审计的公式。"""


class FormulaEvaluationError(RuntimeError):
    """AlphaGPT 公式执行或结果校验失败，禁止用剩余公式替代。"""


def _require_formulas(formulas: list[list[int]] | None) -> list[list[int]]:
    """拒绝缺省或空公式，避免在执行路径生成未授权的启发式候选。"""
    if not formulas:
        raise FormulaRequiredError("AlphaGPT 需要显式提供经过审计的 formulas")
    return formulas


@register_strategy(
    StrategyInfo(
        name="alphagpt",
        market="crypto",
        live_capable=True,
        description="AlphaGPT因子DSL+链上执行(实盘默认关)",
    )
)
class AlphaGptStrategy(StrategyBase):
    """AlphaGPT 因子 DSL + 链上执行策略（实盘默认关闭）。"""

    _REQUIRED_OHLCV = ("open", "high", "low", "close", "volume")

    @classmethod
    def _ohlcv_rejection_reason(cls, df: pd.DataFrame) -> str | None:
        """Reject malformed bars before feature construction or execution."""
        return ohlcv_rejection_reason(df, require_volume=True)

    def _reject_incomplete_market_data(
        self,
        *,
        symbols: list[str],
        failed_symbols: list[str],
        timeframe: str,
        reason: str,
    ) -> list[Signal]:
        """记录行情/因子证据缺口并阻断整批 AlphaGPT 信号。"""
        failed = list(dict.fromkeys(str(symbol) for symbol in failed_symbols))
        details = {
            "source": "provided",
            "market": "crypto",
            "symbols": [str(symbol) for symbol in symbols],
            "failed_symbols": failed,
            "timeframe": timeframe,
            "reason": reason,
        }
        self.last_report = {
            "kind": "alphagpt",
            "status": "unavailable",
            "degraded": True,
            "display_only": True,
            "execution_eligible": False,
            **details,
        }
        self.last_signal_rejection = {
            "code": "market_data_incomplete",
            "message": "AlphaGPT 输入行情或因子评分不完整，未发布信号。",
            "details": details,
        }
        logger.warning(
            "alphagpt 因输入证据不完整而终止: failed_symbols=%s reason=%s", failed, reason
        )
        return []

    def _reject_missing_symbols(self) -> list[Signal]:
        self.last_report = {
            "kind": "alphagpt",
            "status": "unavailable",
            "degraded": True,
            "display_only": True,
            "execution_eligible": False,
            "market": "crypto",
            "reason": "未提供显式 symbols 配置",
        }
        self.last_signal_rejection = {
            "code": "symbols_required",
            "message": "AlphaGPT 需要调用方显式提供 symbols，未使用示例标的回退。",
            "details": {"source": "alphagpt"},
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
        """用 StackVM 评估因子公式，对候选代币产出 Signal。

        Args:
            symbols: 候选代币列表；必须由调用方或显式策略配置提供
            timeframe: K 线周期
            formulas: 因子公式 token 列表（每条为一组 StackVM 后缀 token）；
                      必须由调用方显式提供
            klines_map: 各代币 K 线数据 ``{symbol: DataFrame}``；缺省返回空
        """
        self.last_report = None
        self.last_signal_rejection = None
        try:
            formulas = _require_formulas(formulas)
        except FormulaRequiredError as exc:
            logger.warning("alphagpt.produce 拒绝执行: %s", exc)
            self.last_signal_rejection = {
                "code": "formulas_required",
                "message": str(exc),
                "details": {"source": "alphagpt"},
            }
            return []

        if symbols is None:
            symbols = self.config.get("symbols")
        if not symbols:
            logger.warning("alphagpt.produce 未提供显式 symbols，拒绝使用示例标的")
            return self._reject_missing_symbols()
        symbols = list(symbols)
        if not klines_map:
            logger.warning("alphagpt.produce 未提供 klines_map，无信号产出")
            return self._reject_incomplete_market_data(
                symbols=symbols,
                failed_symbols=symbols,
                timeframe=timeframe,
                reason="未提供 K 线数据",
            )

        for symbol in symbols:
            frame = klines_map.get(symbol)
            if not isinstance(frame, pd.DataFrame) or frame.empty:
                return self._reject_incomplete_market_data(
                    symbols=symbols,
                    failed_symbols=[symbol],
                    timeframe=timeframe,
                    reason="K 线为空或缺失",
                )
            quality_reason = self._ohlcv_rejection_reason(frame)
            if quality_reason is not None:
                return self._reject_incomplete_market_data(
                    symbols=symbols,
                    failed_symbols=[symbol],
                    timeframe=timeframe,
                    reason=quality_reason,
                )

        # 懒加载重依赖（torch）
        import torch

        from strategies.crypto.alphagpt.factors import FeatureEngineer
        from strategies.crypto.alphagpt.stack_vm import StackVM

        vm = StackVM()
        signals: list[Signal] = []
        for symbol in symbols:
            df = klines_map.get(symbol)
            try:
                feat = self._build_feat_tensor(torch, FeatureEngineer, df)
            except Exception as exc:
                logger.exception("alphagpt 特征构建失败: %s", symbol)
                return self._reject_incomplete_market_data(
                    symbols=symbols,
                    failed_symbols=[symbol],
                    timeframe=timeframe,
                    reason=f"特征构建失败: {exc}",
                )

            # 评估每条公式，取均值作为综合因子分
            scores: list[float] = []
            for formula in formulas:
                try:
                    res = vm.execute(formula, feat)
                except Exception as exc:
                    logger.exception("alphagpt 公式执行失败: %s", symbol)
                    return self._reject_incomplete_market_data(
                        symbols=symbols,
                        failed_symbols=[symbol],
                        timeframe=timeframe,
                        reason=f"公式执行失败: {exc}",
                    )
                if res is None:
                    return self._reject_incomplete_market_data(
                        symbols=symbols,
                        failed_symbols=[symbol],
                        timeframe=timeframe,
                        reason="公式未返回评分",
                    )
                try:
                    # res: [B, T]，取最新时点标量
                    score_value = float(res[0, -1].item())
                except Exception as exc:
                    logger.exception("alphagpt 公式结果无效: %s", symbol)
                    return self._reject_incomplete_market_data(
                        symbols=symbols,
                        failed_symbols=[symbol],
                        timeframe=timeframe,
                        reason=f"公式结果无效: {exc}",
                    )
                if not math.isfinite(score_value):
                    return self._reject_incomplete_market_data(
                        symbols=symbols,
                        failed_symbols=[symbol],
                        timeframe=timeframe,
                        reason="公式返回非有限评分",
                    )
                scores.append(score_value)
            if not scores:
                return self._reject_incomplete_market_data(
                    symbols=symbols,
                    failed_symbols=[symbol],
                    timeframe=timeframe,
                    reason="没有可用公式评分",
                )

            raw = sum(scores) / len(scores)
            score = self._normalize_score(raw)
            if raw > 0:
                direction = "buy"
            elif raw < 0:
                direction = "sell"
            else:
                direction = "hold"
            confidence = float(min(1.0, abs(raw) + 0.3))

            try:
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
            except Exception as exc:
                logger.exception("alphagpt 信号构造失败: %s", symbol)
                return self._reject_incomplete_market_data(
                    symbols=symbols,
                    failed_symbols=[symbol],
                    timeframe=timeframe,
                    reason=f"信号构造失败: {exc}",
                )
            signals.append(sig)
        for sig in signals:
            self.publish(sig)
        return signals

    def backtest(
        self,
        klines: pd.DataFrame,
        formulas: list[list[int]] | None = None,
        initial_capital: float = 10000.0,
        **kwargs: Any,
    ) -> BacktestResult:
        """事件驱动回测：on_bar 内按综合因子分方向买卖。"""
        if klines is None or klines.empty:
            from core.backtest.engine import BacktestResult

            return BacktestResult.empty(engine="event")

        quality_reason = self._ohlcv_rejection_reason(klines)
        if quality_reason is not None:
            raise ValueError(f"K线质量不合格: {quality_reason}")

        formulas = _require_formulas(formulas)

        # 懒加载重依赖
        import torch

        from strategies.crypto.alphagpt.factors import FeatureEngineer
        from strategies.crypto.alphagpt.stack_vm import StackVM

        df = klines.sort_values("datetime").reset_index(drop=True)
        vm = StackVM()
        feat = self._build_feat_tensor(torch, FeatureEngineer, df)

        # 预计算每根 bar 的综合因子分
        per_bar: list[float] = []
        for i in range(len(df)):
            bar_scores: list[float] = []
            for formula in formulas:
                try:
                    res = vm.execute(formula, feat)
                except Exception as exc:
                    raise FormulaEvaluationError(f"公式执行失败（bar={i}）: {exc}") from exc
                if res is None:
                    raise FormulaEvaluationError(f"公式未返回结果（bar={i}）")
                try:
                    value = float(res[0, i].item())
                except Exception as exc:
                    raise FormulaEvaluationError(f"公式结果无效（bar={i}）: {exc}") from exc
                if not math.isfinite(value):
                    raise FormulaEvaluationError(f"公式返回非有限值（bar={i}）")
                bar_scores.append(value)
            if not bar_scores:
                raise FormulaEvaluationError(f"没有可用公式评分（bar={i}）")
            per_bar.append(sum(bar_scores) / len(bar_scores))

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
        result = engine.run(df, on_bar, periods_per_year=365)
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
        except Exception:
            logger.exception("alphagpt live_tick 执行失败")
            return {"dry_run": False, "intent": intent, "status": "error"}
        return {"dry_run": False, "intent": intent, "status": "submitted"}

    # ---------- 内部工具 ----------

    @staticmethod
    def _build_feat_tensor(torch, feature_engineer_cls, df: pd.DataFrame):
        """把 K 线 DataFrame 转成因子引擎所需的 ``raw_dict``。

        返回 ``FeatureEngineer.compute_features`` 的输出：[B=1, F=6, T]。

        OHLCV 是行情真源字段，不能以常数列替代；缺失、非数值或非有限值
        一律拒绝。``liquidity`` / ``fdv`` 是可选的链上增强字段，缺失时使用
        明确记录在此处的中性模型先验，不会改变 OHLCV 的执行资格。
        """

        quality_reason = AlphaGptStrategy._ohlcv_rejection_reason(df)
        if quality_reason is not None:
            raise ValueError(f"OHLCV 质量不合格: {quality_reason}")

        def _col(name: str, default: float | None = None) -> np.ndarray:
            if name in df.columns:
                try:
                    values = df[name].astype(float).to_numpy()
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"列 {name} 不是数值") from exc
                if not np.isfinite(values).all():
                    raise ValueError(f"列 {name} 含非有限值")
                return values
            if default is None:
                raise ValueError(f"K线缺少必需列: {name}")
            return np.full(len(df), float(default))

        def _t1d(name: str, default: float | None = None):
            return torch.tensor(_col(name, default), dtype=torch.float32).unsqueeze(0)

        raw_dict = {
            # OHLCV 是执行所需的真源字段，故不提供常数默认值。
            "close": _t1d("close"),
            "open": _t1d("open"),
            "high": _t1d("high"),
            "low": _t1d("low"),
            "volume": _t1d("volume"),
            # 链上增强字段是可选模型输入，使用显式记录的中性先验。
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
    klines_map: dict[str, pd.DataFrame] | None = None,
    max_depth: int = 5,
    population: int = 50,
    **kwargs: Any,
) -> list[list[int]]:
    """明确拒绝运行时启发式搜索，公式须由上游审计流程提供。"""
    raise FormulaRequiredError("AlphaGPT 运行时不生成公式；请显式提供经过审计的 formulas")
