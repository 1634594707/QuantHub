"""SuperTrend 趋势跟踪策略 — QuantHub 迁移版。

从 trading-master/05-A_Stock_Trend 下沉为 strategies/a_shares/supertrend:
    - produce(): 用 core.data_feed 拉取 K 线 → 计算 SuperTrend → 产出 Signal
    - backtest(): 用 core.backtest.EventEngine 事件驱动回测
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd

from core.backtest.engine import BacktestResult, EventContext, EventEngine
from core.config import get_config
from core.data_feed import Interval, get_data_source
from core.signals import Signal
from strategies.a_shares.supertrend import indicators as st_ind
from strategies.base import StrategyBase, StrategyInfo, register_strategy

logger = logging.getLogger(__name__)

# timeframe 字符串 → Interval 枚举
_TIMEFRAME_TO_INTERVAL: dict[str, Interval] = {
    "daily": Interval.DAILY,
    "1d": Interval.DAILY,
    "weekly": Interval.WEEKLY,
    "1w": Interval.WEEKLY,
    "1h": Interval.H1,
    "60m": Interval.H1,
    "4h": Interval.H4,
    "30m": Interval.M30,
    "15m": Interval.M15,
    "5m": Interval.M5,
    "1m": Interval.M1,
}


def _resolve_interval(timeframe: str) -> Interval:
    """把对外 timeframe 字符串映射为 data_feed 的 Interval 枚举。"""
    tf = str(timeframe).lower()
    if tf not in _TIMEFRAME_TO_INTERVAL:
        raise ValueError(f"不支持的时间周期: {timeframe}（支持: {sorted(_TIMEFRAME_TO_INTERVAL)}）")
    return _TIMEFRAME_TO_INTERVAL[tf]


def _is_nan(x: Any) -> bool:
    """宽松判断标量是否为 NaN（兼容 None / 非数值）。"""
    if x is None:
        return True
    try:
        return bool(np.isnan(x))
    except (TypeError, ValueError):
        return False


@register_strategy(
    StrategyInfo(
        name="supertrend",
        market="a_shares",
        live_capable=False,
        description="SuperTrend 趋势跟踪策略",
    )
)
class SuperTrendStrategy(StrategyBase):
    """SuperTrend 趋势跟踪策略。"""

    def _resolve_symbols(self, symbols: list[str] | None) -> list[str] | None:
        """Resolve only caller-provided or explicitly configured symbols.

        The former built-in example universe is intentionally not used when
        a scheduler or API caller omits its target universe.
        """
        raw = symbols if symbols is not None else self.config.get("symbols")
        if not isinstance(raw, (list, tuple)):
            return None
        resolved = [str(item).strip() for item in raw if str(item).strip()]
        return resolved or None

    def _reject_configuration(self, *, reason: str, timeframe: str) -> list[Signal]:
        details = {
            "source": "configuration",
            "market": "a_shares",
            "symbols": [],
            "failed_symbols": [],
            "timeframe": timeframe,
            "reason": reason,
        }
        self.last_report = {
            "kind": "supertrend",
            "status": "unavailable",
            "degraded": True,
            "display_only": True,
            "execution_eligible": False,
            **details,
        }
        self.last_signal_rejection = {
            "code": "symbols_required",
            "message": "SuperTrend 未配置明确标的，未启动扫描。",
            "details": details,
        }
        logger.warning("SuperTrend 配置不完整，跳过扫描: %s", reason)
        return []

    def _reject_incomplete_market_data(
        self,
        *,
        source: Any,
        symbols: list[str],
        failed_symbols: list[str],
        timeframe: str,
        interval: Interval,
        reason: str,
    ) -> list[Signal]:
        """记录 primary 行情/指标缺口并阻断整批趋势信号。

        SuperTrend 信号是方向性结果；静默丢弃一个标的会使扫描结果
        变成不完整的候选池。因此任一标的不可用时不发布已计算的部分，
        并把失败原因留在统一的拒绝诊断中。
        """
        source_name = str(getattr(source, "name", "unknown"))
        failed = list(dict.fromkeys(str(symbol) for symbol in failed_symbols))
        details = {
            "source": source_name,
            "market": "a_shares",
            "symbols": [str(symbol) for symbol in symbols],
            "failed_symbols": failed,
            "timeframe": timeframe,
            "interval": interval.value,
            "reason": reason,
        }
        self.last_report = {
            "kind": "supertrend",
            "status": "unavailable",
            "degraded": True,
            "display_only": True,
            "execution_eligible": False,
            **details,
        }
        self.last_signal_rejection = {
            "code": "market_data_incomplete",
            "message": "A股 primary 行情不完整，未发布 SuperTrend 信号。",
            "details": details,
        }
        logger.warning(
            "SuperTrend 因 primary 行情不完整而终止: source=%s failed_symbols=%s reason=%s",
            source_name,
            failed,
            reason,
        )
        return []

    def produce(
        self,
        symbols: list[str] | None = None,
        timeframe: str = "daily",
        period: int = 10,
        multiplier: float = 3.0,
        limit: int = 500,
        **kwargs: Any,
    ) -> list[Signal]:
        """扫描标的，基于 SuperTrend 当前趋势方向产出信号。

        trend = 1  → buy
        trend = -1 → sell
        score / confidence 基于 ATR 与趋势强度。
        """
        self.last_report = None
        self.last_signal_rejection = None
        interval = _resolve_interval(timeframe)
        resolved_symbols = self._resolve_symbols(symbols)
        if resolved_symbols is None:
            return self._reject_configuration(
                reason="未提供明确标的（调用参数 symbols 或 modules.supertrend.symbols）",
                timeframe=timeframe,
            )
        symbols = resolved_symbols
        try:
            source = get_data_source("a_shares")
        except Exception as exc:
            logger.exception("A股 primary 数据源不可用")
            return self._reject_incomplete_market_data(
                source=None,
                symbols=symbols,
                failed_symbols=symbols,
                timeframe=timeframe,
                interval=interval,
                reason=f"primary 数据源初始化失败: {exc}",
            )

        signals: list[Signal] = []
        for symbol in symbols:
            try:
                klines = source.get_kline(symbol, interval, limit=limit)
            except Exception as exc:
                logger.exception("获取 K 线失败: %s %s", symbol, interval)
                return self._reject_incomplete_market_data(
                    source=source,
                    symbols=symbols,
                    failed_symbols=[symbol],
                    timeframe=timeframe,
                    interval=interval,
                    reason=f"primary K 线请求失败: {exc}",
                )
            if klines is None or not isinstance(klines, pd.DataFrame) or klines.empty:
                return self._reject_incomplete_market_data(
                    source=source,
                    symbols=symbols,
                    failed_symbols=[symbol],
                    timeframe=timeframe,
                    interval=interval,
                    reason="primary K 线为空",
                )

            try:
                df = st_ind.supertrend(klines, period=period, multiplier=multiplier)
            except Exception as exc:
                logger.exception("SuperTrend 计算失败: %s", symbol)
                return self._reject_incomplete_market_data(
                    source=source,
                    symbols=symbols,
                    failed_symbols=[symbol],
                    timeframe=timeframe,
                    interval=interval,
                    reason=f"SuperTrend 计算失败: {exc}",
                )

            try:
                sig = self._signal_from_df(df, symbol, timeframe, period, multiplier)
            except Exception as exc:
                logger.exception("SuperTrend 信号构造失败: %s", symbol)
                return self._reject_incomplete_market_data(
                    source=source,
                    symbols=symbols,
                    failed_symbols=[symbol],
                    timeframe=timeframe,
                    interval=interval,
                    reason=f"SuperTrend 信号构造失败: {exc}",
                )
            if sig is None:
                return self._reject_incomplete_market_data(
                    source=source,
                    symbols=symbols,
                    failed_symbols=[symbol],
                    timeframe=timeframe,
                    interval=interval,
                    reason="SuperTrend 未返回有效信号",
                )
            signals.append(sig)

        for sig in signals:
            self.publish(sig)
        return signals

    @staticmethod
    def _signal_from_df(
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        period: int,
        multiplier: float,
    ) -> Signal | None:
        """从最新一根 K 线的 SuperTrend 状态构造 Signal。"""
        if df.empty or "trend" not in df.columns:
            return None
        last = df.iloc[-1]
        trend = last["trend"]
        if _is_nan(trend):
            return None

        # A warm-up/malformed indicator row must not be turned into a neutral
        # score (or, worse, the implicit ``sell`` branch below).  The latest
        # bar needs a finite direction, close, ATR and active SuperTrend band
        # before it can become a directional signal.
        try:
            trend_value = int(trend)
        except (TypeError, ValueError, OverflowError):
            return None
        if trend_value not in {-1, 1}:
            return None

        direction = "buy" if trend_value == 1 else "sell"

        try:
            close = float(last["close"])
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(close) or close <= 0:
            return None
        atr_raw = last.get("atr")
        st_raw = last.get("supertrend")
        try:
            atr_val = float(atr_raw)
            st_val = float(st_raw)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(atr_val) or atr_val <= 0 or not math.isfinite(st_val) or st_val <= 0:
            return None

        # score: 价格距 supertrend 线的距离（以 ATR 归一化），越远强度越高
        strength = abs(close - st_val) / atr_val
        score = float(min(1.0, strength / 3.0))

        # confidence: 趋势持续 bar 数越长置信度越高
        trend_bars = 0
        for t in df["trend"].iloc[::-1]:
            if t == trend_value:
                trend_bars += 1
            else:
                break
        confidence = float(min(1.0, 0.4 + 0.6 * min(trend_bars, 10) / 10.0))

        return Signal(
            symbol=symbol,
            market="a_shares",
            timeframe=timeframe,
            direction=direction,
            score=score,
            confidence=confidence,
            source="supertrend",
            tags=[f"period={period}", f"multiplier={multiplier}"],
            meta={
                "trend": trend_value,
                "atr": atr_val,
                "supertrend": st_val,
                "trend_bars": trend_bars,
            },
        )

    def backtest(
        self,
        klines: pd.DataFrame,
        period: int = 10,
        multiplier: float = 3.0,
        initial_capital: float = 100000.0,
        **kwargs: Any,
    ) -> BacktestResult:
        """事件驱动回测：on_bar 内按 SuperTrend 翻转信号买卖。"""
        if klines is None or klines.empty:
            return BacktestResult.empty(engine="event")

        df = klines.sort_values("datetime").reset_index(drop=True)
        df = st_ind.supertrend(df, period=period, multiplier=multiplier)

        buy_flags = df["buy_signal"].tolist() if "buy_signal" in df.columns else [False] * len(df)
        sell_flags = (
            df["sell_signal"].tolist() if "sell_signal" in df.columns else [False] * len(df)
        )

        # 顺序游标：EventEngine 按 datetime 升序逐 bar 调用 on_bar
        state = {"i": 0}

        def on_bar(bar: pd.Series, ctx: EventContext) -> None:
            i = state["i"]
            price = float(bar["close"])
            ts = bar.get("datetime")
            if buy_flags[i] and ctx.position == 0.0:
                # 全仓买入（预留手续费）
                qty = ctx.cash / (price * (1 + ctx.commission))
                if qty > 0:
                    ctx.buy(price, qty, ts)
            elif sell_flags[i] and ctx.position > 0.0:
                ctx.sell(price, ctx.position, ts)
            state["i"] += 1

        engine = EventEngine(initial_capital=initial_capital)
        result = engine.run(df, on_bar)
        # 直接返回类型化 BacktestResult（含逐根 equity_curve），由 API 负责序列化。
        # 单一来源，避免 dict 化时丢字段导致前端权益曲线为空。
        return result


def run_scan(
    symbols: list[str] | None = None,
    timeframe: str = "daily",
    period: int = 10,
    multiplier: float = 3.0,
    **kwargs: Any,
) -> list[Signal]:
    """便捷扫描入口：实例化 SuperTrendStrategy 并产出信号。"""
    # Scheduler jobs must pass the configured universe explicitly; an omitted
    # config must not revive the historical built-in example symbols.
    cfg: dict[str, Any] = {}
    if symbols is None:
        try:
            raw_config = get_config("a_shares")
            module_cfg = raw_config.get("modules", {}).get("supertrend", {})
            if isinstance(module_cfg, dict):
                cfg = module_cfg
        except Exception as exc:  # noqa: BLE001 - preserve explicit unavailable result
            logger.warning("SuperTrend 无法读取模块配置，跳过扫描: %s", exc)
    strategy = SuperTrendStrategy(config={**cfg, "enabled": True})
    configured_symbols = symbols if symbols is not None else cfg.get("symbols")
    return strategy.produce(
        symbols=configured_symbols,
        timeframe=timeframe,
        period=period,
        multiplier=multiplier,
        **kwargs,
    )
