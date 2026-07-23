"""经典 Pivot 枢轴点计算。

从原 ``trading-master/03-daily_news/daily-news/scripts/pivot.py`` 下沉而来，
算法保持不变（经典 Pivot 公式），仅剥离 CLI/打印逻辑并补充从 K线
DataFrame 取前一交易日 OHLC 的便捷入口。

公式：
    P  = (H + L + C) / 3
    R1 = 2P - L
    R2 = P + (H - L)
    R3 = R1 + (H - L)
    S1 = 2P - H
    S2 = P - (H - L)
    S3 = S1 - (H - L)
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def calc_pivots(high: float, low: float, close: float) -> dict[str, float]:
    """经典 Pivot 公式（与原脚本完全一致）。

    Args:
        high: 前一交易日最高价
        low:  前一交易日最低价
        close: 前一交易日收盘价

    Returns:
        包含 P / R1 / R2 / R3 / S1 / S2 / S3 的字典
    """
    p = (high + low + close) / 3
    r = high - low
    return {
        "P": p,
        "R1": 2 * p - low,
        "R2": p + r,
        "R3": 2 * p - low + r,  # R1 + (H - L)
        "S1": 2 * p - high,
        "S2": p - r,
        "S3": 2 * p - high - r,  # S1 - (H - L)
    }


def pivots_from_klines(klines: pd.DataFrame) -> dict[str, float] | None:
    """从 K线 DataFrame 取最后一根（前一交易日）OHLC 计算枢轴点。

    Args:
        klines: ``core.data_feed`` 返回的 K线 DataFrame，需含
                high / low / close 列（按 datetime 升序）。

    Returns:
        枢轴点字典；数据不足或为空时返回 None
    """
    if klines is None or klines.empty:
        return None
    last: Any = klines.iloc[-1]
    try:
        high = float(last["high"])
        low = float(last["low"])
        close = float(last["close"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (high >= low):
        return None
    return calc_pivots(high, low, close)


def fmt_pivot(value: float) -> str:
    """统一格式化枢轴点数值（保留两位小数，千分位）。"""
    return f"{value:,.2f}"
