from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


def normalize_ohlcv_rows(df: pd.DataFrame, *, time_column: str = "datetime") -> pd.DataFrame:
    """按适配器统一契约清理缺失 OHLC、重复时间和逆序数据。"""
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.copy()
    result = df.copy()
    required = ["open", "high", "low", "close"]
    if (
        any(column not in result.columns for column in required)
        or time_column not in result.columns
    ):
        return result
    for column in [*required, "volume"]:
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    if time_column == "datetime":
        result[time_column] = pd.to_datetime(result[time_column], errors="coerce")
    result = result.dropna(subset=[time_column, *required])
    result = result.sort_values(time_column).drop_duplicates(time_column, keep="last")
    return result.reset_index(drop=True)


def ohlcv_rejection_reason(
    df: pd.DataFrame | None,
    *,
    require_volume: bool = True,
) -> str | None:
    """Return a deterministic quality error for an execution-grade OHLCV frame.

    Normalization intentionally does not silently repair malformed prices.  A
    strategy that can publish a signal should call this helper before feature
    construction so zero/negative prices, impossible high/low relationships,
    and non-finite values cannot turn into a neutral or partial signal.
    ``volume`` is required by the factor engines; callers that only need price
    bars (for example SuperTrend) may opt out explicitly.
    """

    if not isinstance(df, pd.DataFrame) or df.empty:
        return "K 线为空或不是 DataFrame"

    required = ["open", "high", "low", "close"]
    if require_volume:
        required.append("volume")
    missing = [column for column in required if column not in df.columns]
    if missing:
        return f"缺少 OHLCV 列: {', '.join(missing)}"

    values = df.loc[:, required].apply(pd.to_numeric, errors="coerce")
    if values.isna().any().any():
        return "OHLCV 含缺失或非数值字段"
    array = values.to_numpy(dtype=float)
    if not np.isfinite(array).all():
        return "OHLCV 含非有限值"

    prices = values.loc[:, ["open", "high", "low", "close"]]
    if prices.le(0).any().any():
        return "OHLCV 含非正价格"
    if require_volume and values["volume"].lt(0).any():
        return "OHLCV 含负成交量"

    high = prices["high"]
    low = prices["low"]
    if (
        high.lt(prices[["open", "low", "close"]].max(axis=1)).any()
        or low.gt(prices[["open", "high", "close"]].min(axis=1)).any()
    ):
        return "OHLCV 高低价关系无效"
    return None


@dataclass(frozen=True)
class DataQualityReport:
    status: str
    usable: bool
    row_count: int
    missing_rate: float
    invalid_rows: int
    latest_time: str | None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_ohlcv(df: pd.DataFrame | None) -> DataQualityReport:
    if df is None or df.empty:
        return DataQualityReport(
            status="empty",
            usable=False,
            row_count=0,
            missing_rate=1.0,
            invalid_rows=0,
            latest_time=None,
            reason="K线为空",
        )

    required = ["open", "high", "low", "close"]
    missing_columns = [column for column in required if column not in df.columns]
    if missing_columns:
        return DataQualityReport(
            status="invalid",
            usable=False,
            row_count=len(df),
            missing_rate=1.0,
            invalid_rows=len(df),
            latest_time=_latest_time(df),
            reason=f"缺少字段: {', '.join(missing_columns)}",
        )

    numeric = df[required].apply(pd.to_numeric, errors="coerce")
    missing_mask = numeric.isna()
    missing_rate = float(missing_mask.sum().sum() / numeric.size) if numeric.size else 1.0
    nonpositive = numeric.le(0).any(axis=1)
    inconsistent = numeric["high"].lt(numeric[["open", "low", "close"]].max(axis=1)) | numeric[
        "low"
    ].gt(numeric[["open", "high", "close"]].min(axis=1))
    finite_mask = ~np.isfinite(numeric.to_numpy(dtype=float)).all(axis=1)
    invalid_mask = missing_mask.any(axis=1) | finite_mask | nonpositive | inconsistent
    invalid_rows = int(invalid_mask.sum())
    usable = invalid_rows == 0 and missing_rate <= 0.02
    reason = None
    if invalid_rows:
        reason = f"发现 {invalid_rows} 行非法 OHLC"
    elif missing_rate > 0.02:
        reason = f"关键字段缺失率 {missing_rate:.2%}"
    return DataQualityReport(
        status="ok" if usable else "invalid",
        usable=usable,
        row_count=len(df),
        missing_rate=round(missing_rate, 6),
        invalid_rows=invalid_rows,
        latest_time=_latest_time(df),
        reason=reason,
    )


def _latest_time(df: pd.DataFrame) -> str | None:
    if "datetime" in df.columns:
        values = pd.to_datetime(df["datetime"], errors="coerce").dropna()
        if not values.empty:
            return values.iloc[-1].isoformat()
    if "bar_time" in df.columns and not df["bar_time"].empty:
        value = df["bar_time"].iloc[-1]
        if pd.notna(value):
            return str(value)
    return None
