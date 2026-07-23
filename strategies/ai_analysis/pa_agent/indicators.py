"""价格行为指标计算（ATR / EMA）。

从原 ``PA_Agent/pa_agent/indicators/atr.py`` 与 ``ema.py`` 提取，
**算法严格保持原样**（True Range 定义、Wilder 平滑、EMA 种子与 α=2/(period+1)），
仅合并到单一模块并补充 DataFrame 适配入口，供本策略模块使用。

原始算法说明:
    - ATR: 前 period-1 个值为 nan 暖机；第 period 个为前 period 个 TR 的简单平均；
      之后采用 Wilder 平滑  ATR_t = (ATR_{t-1}*(period-1) + TR_t) / period
    - EMA: 前 period-1 个值为 nan 暖机；第 period 个为前 period 个值的简单平均；
      之后采用标准 EMA  prev = x*α + prev*(1-α), α = 2/(period+1)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

# ── ATR (Average True Range, Wilder smoothing) ───────────────────────────────


@dataclass(frozen=True)
class AtrState:
    """增量 ATR 计算的最小状态。"""

    last: float  # 最近一次 ATR 值（暖机期为 nan）
    period: int
    count: int  # 已处理的 bar 数
    prev_close: float  # 上一根 bar 的收盘价（未设置时为 nan）
    _sum_tr: float  # 暖机期 TR 的累计和


def _true_range(high: float, low: float, prev_close: float) -> float:
    """计算单根 bar 的 True Range。"""
    hl = abs(high - low)
    if math.isnan(prev_close):
        return hl
    return max(hl, abs(high - prev_close), abs(low - prev_close))


def atr_full(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float]:
    """对并行 OHLC 列表计算 ATR（旧 → 新）。

    返回与输入等长的列表：
        - 索引 0 .. period-2: nan（暖机）
        - 索引 period-1: 前 period 个 True Range 的简单平均
        - 索引 period .. end: Wilder 平滑  ATR_t = (ATR_{t-1}*(period-1) + TR_t) / period
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    n = len(highs)
    if n != len(lows) or n != len(closes):
        raise ValueError("highs, lows, closes must have the same length")
    result = [math.nan] * n
    if n < period:
        return result

    # 计算每根 bar 的 TR
    trs: list[float] = []
    for i in range(n):
        prev_c = closes[i - 1] if i > 0 else math.nan
        trs.append(_true_range(highs[i], lows[i], prev_c))

    # 以前 period 个 TR 的简单平均作为种子
    seed = sum(trs[:period]) / period
    result[period - 1] = seed
    prev_atr = seed
    for i in range(period, n):
        prev_atr = (prev_atr * (period - 1) + trs[i]) / period
        result[i] = prev_atr
    return result


def atr_incremental(state: AtrState, high: float, low: float, close: float) -> AtrState:
    """用一根新 bar (high, low, close) 更新 ATR 状态。

    暖机期 (count < period) 累计 TR 和；count == period 时播种 ATR；
    暖机结束后应用 Wilder 平滑。
    """
    period = state.period
    count = state.count + 1
    tr = _true_range(high, low, state.prev_close)

    if count < period:
        return AtrState(
            last=math.nan,
            period=period,
            count=count,
            prev_close=close,
            _sum_tr=state._sum_tr + tr,
        )
    elif count == period:
        seed = (state._sum_tr + tr) / period
        return AtrState(
            last=seed,
            period=period,
            count=count,
            prev_close=close,
            _sum_tr=0.0,
        )
    else:
        new_last = (state.last * (period - 1) + tr) / period
        return AtrState(
            last=new_last,
            period=period,
            count=count,
            prev_close=close,
            _sum_tr=0.0,
        )


def make_atr_state(period: int = 14) -> AtrState:
    """为指定周期创建一个全新的 AtrState。"""
    return AtrState(last=math.nan, period=period, count=0, prev_close=math.nan, _sum_tr=0.0)


# ── EMA (Exponential Moving Average) ─────────────────────────────────────────


@dataclass(frozen=True)
class EmaState:
    """增量 EMA 计算的最小状态。"""

    last: float  # 最近一次 EMA 值（暖机期为 nan）
    period: int
    count: int  # 已处理的值数
    _sum: float  # 暖机期的累计和


def ema_full(values: list[float], period: int) -> list[float]:
    """对 *values*（旧 → 新）计算 EMA。

    返回与输入等长的列表：
        - 索引 0 .. period-2: nan（暖机）
        - 索引 period-1: 前 period 个值的简单平均
        - 索引 period .. end: EMA, α = 2/(period+1)
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    n = len(values)
    result = [math.nan] * n
    if n < period:
        return result

    alpha = 2.0 / (period + 1)
    # 以前 period 个值的简单平均作为种子
    seed = sum(values[:period]) / period
    result[period - 1] = seed
    prev = seed
    for i in range(period, n):
        prev = values[i] * alpha + prev * (1.0 - alpha)
        result[i] = prev
    return result


def ema_incremental(state: EmaState, x: float) -> EmaState:
    """用新值 *x* 更新 EMA 状态。

    暖机期 (count < period) 累计和；count == period 时播种；
    暖机结束后应用标准 EMA 公式。
    """
    period = state.period
    count = state.count + 1
    alpha = 2.0 / (period + 1)

    if count < period:
        return EmaState(last=math.nan, period=period, count=count, _sum=state._sum + x)
    elif count == period:
        seed = (state._sum + x) / period
        return EmaState(last=seed, period=period, count=count, _sum=0.0)
    else:
        new_last = x * alpha + state.last * (1.0 - alpha)
        return EmaState(last=new_last, period=period, count=count, _sum=0.0)


def make_ema_state(period: int) -> EmaState:
    """为指定周期创建一个全新的 EmaState。"""
    return EmaState(last=math.nan, period=period, count=0, _sum=0.0)


# ── DataFrame 适配入口 ─────────────────────────────────────────────────────────


def _is_nan(x: Any) -> bool:
    """宽松判断标量是否为 NaN（兼容 None / 非数值）。"""
    if x is None:
        return True
    try:
        return bool(math.isnan(x))
    except (TypeError, ValueError):
        return False


def compute_indicators(
    klines: pd.DataFrame,
    *,
    atr_period: int = 14,
    ema_period: int = 20,
) -> pd.DataFrame:
    """在 K 线 DataFrame 上计算 ATR 与 EMA，返回追加列后的新 DataFrame。

    要求 klines 至少包含 high / low / close 列（按时间升序）。
    返回列:
        - atr:   Wilder 平滑 ATR（暖机期为 NaN）
        - ema:   指数移动平均（暖机期为 NaN）
    """
    if klines is None or klines.empty:
        return pd.DataFrame()
    df = klines.copy()
    highs = [float(v) for v in df["high"].tolist()]
    lows = [float(v) for v in df["low"].tolist()]
    closes = [float(v) for v in df["close"].tolist()]

    df["atr"] = atr_full(highs, lows, closes, period=atr_period)
    df["ema"] = ema_full(closes, period=ema_period)
    return df


def latest_atr(klines: pd.DataFrame, period: int = 14) -> float:
    """便捷取最新一根 bar 的 ATR 值（暖机未完成返回 nan）。"""
    highs = [float(v) for v in klines["high"].tolist()]
    lows = [float(v) for v in klines["low"].tolist()]
    closes = [float(v) for v in klines["close"].tolist()]
    series = atr_full(highs, lows, closes, period=period)
    return series[-1] if series else math.nan


def latest_ema(klines: pd.DataFrame, period: int = 20) -> float:
    """便捷取最新一根 bar 的 EMA 值（暖机未完成返回 nan）。"""
    closes = [float(v) for v in klines["close"].tolist()]
    series = ema_full(closes, period=period)
    return series[-1] if series else math.nan
