from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


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
    invalid_mask = missing_mask.any(axis=1) | nonpositive | inconsistent
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
