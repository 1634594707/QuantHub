"""SuperTrend 指标 — TradingView Pine v4 移植（ATR 趋势跟踪）。

从 trading-master/05-A_Stock_Trend/src/indicators.py 提取，保持原 ATR / band
更新算法完全不变，仅适配 QuantHub 小写列名约定，并按规范输出:
    supertrend / final_upperband / final_lowerband / trend
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def supertrend(
    df: pd.DataFrame,
    period: int = 10,
    multiplier: float = 3.0,
    use_wilder_atr: bool = True,
) -> pd.DataFrame:
    """计算 SuperTrend 指标。

    Parameters
    ----------
    df             : OHLCV DataFrame（high / low / close 必需，volume 可选）；
                     兼容首字母大写（High/Low/Close）的原始命名。
    period         : ATR 周期（默认 10）
    multiplier     : ATR 带宽倍数（默认 3.0）
    use_wilder_atr : True → Wilder ATR（ewm, alpha=1/period）；False → SMA(TR)

    Returns
    -------
    DataFrame，新增列:
        atr, final_upperband, final_lowerband, supertrend, trend, buy_signal, sell_signal
    其中:
        trend             = 1（多头）/ -1（空头）
        final_upperband   = src + multiplier*atr（上轨，空头阻力，数值较高）
        final_lowerband   = src - multiplier*atr（下轨，多头支撑，数值较低）
        supertrend        = 当前生效的轨（多头取下轨，空头取上轨）
        buy_signal        = trend 由 -1 翻 1 的 bar
        sell_signal       = trend 由 1 翻 -1 的 bar
    """
    df = df.copy()

    # 列名归一化：兼容 High/Low/Close 与 high/low/close
    _rename = {}
    for c in list(df.columns):
        cl = str(c).lower()
        if cl in ("open", "high", "low", "close", "volume") and c != cl:
            _rename[c] = cl
    if _rename:
        df = df.rename(columns=_rename)

    high = df["high"]
    low = df["low"]
    close = df["close"]
    src = (high + low) / 2

    # True Range
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(
        axis=1
    )

    # ATR（默认 Wilder：ewm alpha=1/period）
    if use_wilder_atr:
        atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    else:
        atr = tr.rolling(period).mean()

    df["atr"] = atr

    n = len(df)
    up_band = np.full(n, np.nan)  # 下轨候选（src - multiplier*atr）
    dn_band = np.full(n, np.nan)  # 上轨候选（src + multiplier*atr）
    trend = np.full(n, np.nan)

    src_arr = src.to_numpy()
    close_arr = close.to_numpy()
    atr_arr = atr.to_numpy()

    for i in range(n):
        if np.isnan(atr_arr[i]):
            trend[i] = 1
            continue

        raw_up = src_arr[i] - multiplier * atr_arr[i]
        raw_dn = src_arr[i] + multiplier * atr_arr[i]

        prev_up = up_band[i - 1] if i > 0 and not np.isnan(up_band[i - 1]) else raw_up
        prev_dn = dn_band[i - 1] if i > 0 and not np.isnan(dn_band[i - 1]) else raw_dn
        prev_close_val = close_arr[i - 1] if i > 0 else close_arr[i]
        prev_trend = trend[i - 1] if i > 0 and not np.isnan(trend[i - 1]) else 1

        # 下轨：仅在能继续支撑多头时抬升，否则重置为当前 raw_up
        up_band[i] = max(raw_up, prev_up) if prev_close_val > prev_up else raw_up
        # 上轨：仅在能继续压制空头时压低，否则重置为当前 raw_dn
        dn_band[i] = min(raw_dn, prev_dn) if prev_close_val < prev_dn else raw_dn

        # 趋势翻转判定（与原版逐字一致，保留 Python 条件表达式优先级语义）
        if prev_trend == -1 and close_arr[i] > dn_band[i - 1] if i > 0 else False:
            trend[i] = 1
        elif prev_trend == 1 and close_arr[i] < up_band[i - 1] if i > 0 else False:
            trend[i] = -1
        else:
            trend[i] = prev_trend

    # 输出列（按规范命名）
    df["final_lowerband"] = up_band  # 下轨（数值较低）
    df["final_upperband"] = dn_band  # 上轨（数值较高）
    trend_series = pd.Series(trend, index=df.index)
    df["trend"] = trend_series
    # supertrend 线：多头取下轨，空头取上轨
    df["supertrend"] = np.where(trend_series == -1, dn_band, up_band)
    df["buy_signal"] = (df["trend"] == 1) & (df["trend"].shift(1) == -1)
    df["sell_signal"] = (df["trend"] == -1) & (df["trend"].shift(1) == 1)

    return df
