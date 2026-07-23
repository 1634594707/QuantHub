"""SuperTrend 趋势跟踪策略 — QuantHub 迁移版。

从 trading-master/05-A_Stock_Trend 下沉为 strategies/a_shares/supertrend:
    - produce(): 用 core.data_feed 拉取 K 线 → 计算 SuperTrend → 产出 Signal
    - backtest(): 用 core.backtest.EventEngine 事件驱动回测
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from core.backtest.engine import BacktestResult, EventContext, EventEngine
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

# 默认扫描标的（沪深300ETF、中国银行）
DEFAULT_SYMBOLS: list[str] = ["510300", "601988"]


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
        symbols = symbols or DEFAULT_SYMBOLS
        interval = _resolve_interval(timeframe)
        source = get_data_source("a_shares")

        signals: list[Signal] = []
        for symbol in symbols:
            try:
                klines = source.get_kline(symbol, interval, limit=limit)
            except Exception:
                logger.exception("获取 K 线失败: %s %s", symbol, interval)
                continue
            if klines is None or klines.empty:
                logger.warning("K 线为空: %s %s", symbol, interval)
                continue

            try:
                df = st_ind.supertrend(klines, period=period, multiplier=multiplier)
            except Exception:
                logger.exception("SuperTrend 计算失败: %s", symbol)
                continue

            sig = self._signal_from_df(df, symbol, timeframe, period, multiplier)
            if sig is not None:
                signals.append(sig)
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

        direction = "buy" if trend == 1 else "sell"

        close = float(last["close"])
        atr_raw = last.get("atr")
        st_raw = last.get("supertrend")
        atr_val = 0.0 if _is_nan(atr_raw) else float(atr_raw)
        st_val = None if _is_nan(st_raw) else float(st_raw)

        # score: 价格距 supertrend 线的距离（以 ATR 归一化），越远强度越高
        if atr_val > 0 and st_val is not None:
            strength = abs(close - st_val) / atr_val
            score = float(min(1.0, strength / 3.0))
        else:
            score = 0.5

        # confidence: 趋势持续 bar 数越长置信度越高
        trend_bars = 0
        for t in df["trend"].iloc[::-1]:
            if t == trend:
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
                "trend": int(trend),
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

        return {
            "engine": result.engine,
            "metrics": result.metrics,
            "final_equity": result.final_equity,
            "total_return": result.total_return,
            "max_drawdown": result.max_drawdown,
            "trades": result.trades,
        }


def run_scan(
    symbols: list[str] | None = None,
    timeframe: str = "daily",
    period: int = 10,
    multiplier: float = 3.0,
    **kwargs: Any,
) -> list[Signal]:
    """便捷扫描入口：实例化 SuperTrendStrategy 并产出信号。"""
    strategy = SuperTrendStrategy(config={"enabled": True})
    return strategy.produce(
        symbols=symbols,
        timeframe=timeframe,
        period=period,
        multiplier=multiplier,
        **kwargs,
    )
