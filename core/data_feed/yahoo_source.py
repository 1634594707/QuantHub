"""Yahoo Finance chart data source for US stock history."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pandas as pd
import requests

from core.data_feed.base import DataSource, Interval
from core.data_feed.quality import normalize_ohlcv_rows

logger = logging.getLogger(__name__)

_CHART_HOSTS = (
    "https://query1.finance.yahoo.com",
    "https://query2.finance.yahoo.com",
)
_INTERVALS = {
    Interval.DAILY: "1d",
    Interval.WEEKLY: "1wk",
}
_CORPORATE_ACTION_RATIO_CHANGE_THRESHOLD = 0.05
_ADJUSTED_RETURN_DISCONTINUITY_THRESHOLD = 0.35


class YahooSource(DataSource):
    """Public Yahoo chart endpoint, used as a US-market history fallback."""

    name = "yahoo"
    market = "us_stocks"

    def __init__(self, market: str = "us_stocks") -> None:
        if market != "us_stocks":
            raise ValueError("Yahoo 数据源当前仅支持美股")
        self.market = market

    def supported_intervals(self) -> Iterable[Interval]:
        return tuple(_INTERVALS)

    def get_kline(
        self,
        symbol: str,
        interval: Interval | str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> pd.DataFrame:
        interval = Interval(interval) if isinstance(interval, str) else interval
        if interval not in _INTERVALS:
            raise ValueError(f"Yahoo 数据源仅支持日线/周线: {interval}")

        end = end or datetime.now(UTC)
        start = start or (end - timedelta(days=max(limit, 1) * 2 + 14))
        period1 = _as_utc_timestamp(start)
        # Yahoo 的 period2 是开区间，多加一天以包含调用当天。
        period2 = _as_utc_timestamp(end + timedelta(days=1))
        params = {
            "period1": period1,
            "period2": period2,
            "interval": _INTERVALS[interval],
            "events": "history",
            "includeAdjustedClose": "true",
        }
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        payload: dict | None = None
        for host in _CHART_HOSTS:
            url = f"{host}/v8/finance/chart/{quote(symbol.strip().upper(), safe='-.^=')}"
            try:
                response = requests.get(url, params=params, headers=headers, timeout=20)
                response.raise_for_status()
                candidate = response.json()
                if candidate.get("chart", {}).get("error"):
                    raise ValueError(str(candidate["chart"]["error"]))
                payload = candidate
                break
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                logger.warning("Yahoo K线请求失败 %s via %s: %s", symbol, host, exc)

        if payload is None:
            return pd.DataFrame()
        return _chart_to_frame(payload, symbol, interval, limit)


def _as_utc_timestamp(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.timestamp())


def _chart_to_frame(payload: dict, symbol: str, interval: Interval, limit: int) -> pd.DataFrame:
    results = payload.get("chart", {}).get("result") or []
    if not results:
        return pd.DataFrame()
    result = results[0]
    timestamps = result.get("timestamp") or []
    quotes = result.get("indicators", {}).get("quote") or []
    if not timestamps or not quotes:
        return pd.DataFrame()

    quote_data = quotes[0]
    row_count = min(
        len(timestamps),
        *(len(quote_data.get(column) or []) for column in ("open", "high", "low", "close")),
    )
    if row_count == 0:
        return pd.DataFrame()

    volume = quote_data.get("volume") or []
    adjusted_sets = result.get("indicators", {}).get("adjclose") or []
    adjusted_close = adjusted_sets[0].get("adjclose") or [] if adjusted_sets else []
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(timestamps[:row_count], unit="s", utc=True).tz_convert(None),
            "open": quote_data["open"][:row_count],
            "high": quote_data["high"][:row_count],
            "low": quote_data["low"][:row_count],
            "close": quote_data["close"][:row_count],
            "adjusted_close": [
                adjusted_close[index] if index < len(adjusted_close) else pd.NA
                for index in range(row_count)
            ],
            "volume": [
                volume[index] if index < len(volume) else pd.NA for index in range(row_count)
            ],
        }
    )
    numeric_columns = ["open", "high", "low", "close", "adjusted_close", "volume"]
    frame[numeric_columns] = frame[numeric_columns].apply(pd.to_numeric, errors="coerce")
    frame = frame.dropna(subset=["datetime", "open", "high", "low", "close"])
    frame = frame[(frame[["open", "high", "low", "close"]] > 0).all(axis=1)]
    frame = normalize_ohlcv_rows(frame)
    adjustment_ratio = frame["adjusted_close"].div(frame["close"])
    adjustment_ratio = adjustment_ratio.where(
        frame["adjusted_close"].gt(0) & adjustment_ratio.gt(0),
        1.0,
    )
    _validate_adjustment_continuity(frame, adjustment_ratio, symbol)
    frame[["open", "high", "low", "close"]] = frame[["open", "high", "low", "close"]].mul(
        adjustment_ratio, axis=0
    )
    frame = frame.drop(columns=["adjusted_close"])
    if limit > 0:
        frame = frame.tail(limit)
    frame["symbol"] = symbol.strip().upper()
    frame["market"] = "us_stocks"
    frame["interval"] = interval.value
    frame["amount"] = pd.NA
    frame["turnover"] = pd.NA
    result = frame[
        [
            "symbol",
            "market",
            "interval",
            "datetime",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "turnover",
        ]
    ].reset_index(drop=True)
    result.attrs["corporate_action_adjustment"] = "adjclose_ratio"
    return result


def _validate_adjustment_continuity(
    frame: pd.DataFrame,
    adjustment_ratio: pd.Series,
    symbol: str,
) -> None:
    ratio_change = adjustment_ratio.pct_change().abs()
    adjusted_return = frame["adjusted_close"].pct_change().abs()
    discontinuity = ratio_change.ge(_CORPORATE_ACTION_RATIO_CHANGE_THRESHOLD) & adjusted_return.ge(
        _ADJUSTED_RETURN_DISCONTINUITY_THRESHOLD
    )
    if not discontinuity.any():
        return
    index = discontinuity[discontinuity].index[0]
    timestamp = frame.loc[index, "datetime"]
    raise ValueError(
        f"Yahoo 复权连续性检查失败: {symbol.strip().upper()} {timestamp.isoformat()} "
        f"复权比例变化 {ratio_change.loc[index]:.2%}，复权收盘变化 {adjusted_return.loc[index]:.2%}"
    )
