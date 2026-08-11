"""OKX public swap candle data source."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime

import pandas as pd
import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from core.config import get_config
from core.data_feed.base import DataSource, Interval
from core.data_feed.quality import normalize_ohlcv_rows

logger = logging.getLogger(__name__)

_INTERVAL_MAP = {
    Interval.M1: "1m",
    Interval.M5: "5m",
    Interval.M15: "15m",
    Interval.M30: "30m",
    Interval.H1: "1H",
    Interval.H4: "4H",
    Interval.DAILY: "1D",
    Interval.WEEKLY: "1W",
}

_CANDLES_URL = "https://www.okx.com/api/v5/market/candles"


def to_ccxt_symbol(symbol: str) -> str:
    """把常见币对代码统一为 CCXT 永续合约格式。"""
    normalized = symbol.strip().upper()
    if "/" in normalized:
        base_quote, _, settlement = normalized.partition(":")
        quote = base_quote.split("/", 1)[1]
        return f"{base_quote}:{settlement or quote}"
    parts = normalized.split("-")
    if len(parts) == 3 and parts[2] == "SWAP":
        base, quote = parts[:2]
        return f"{base}/{quote}:{quote}"
    if len(parts) == 2:
        base, quote = parts
        return f"{base}/{quote}:{quote}"
    return f"{normalized}/USDT:USDT"


def to_okx_inst_id(symbol: str) -> str:
    """Normalize common spot/CCXT inputs to an OKX USDT swap instrument id."""
    normalized = symbol.strip().upper().replace(" ", "")
    if ":" in normalized:
        normalized = normalized.split(":", 1)[0]
    normalized = normalized.replace("/", "-")
    if normalized.endswith("-USDT-SWAP"):
        return normalized
    if normalized.endswith("-USDT"):
        return f"{normalized}-SWAP"
    if normalized.endswith("USDT"):
        return f"{normalized[:-4]}-USDT-SWAP"
    return f"{normalized}-USDT-SWAP"


class OkxSource(DataSource):
    """OKX public USDT swap data source."""

    name = "okx"
    market = "crypto"

    def __init__(
        self, api_key: str | None = None, secret: str | None = None, passphrase: str | None = None
    ) -> None:
        del api_key, secret, passphrase
        self._session = requests.Session()
        self._session.trust_env = True
        retry_cfg = get_config().get("data_feed", {}).get("retry", {})
        self._max_attempts = retry_cfg.get("max_attempts", 4)
        self._backoff_base = retry_cfg.get("backoff_base", 1.5)
        self._backoff_cap = retry_cfg.get("backoff_cap", 30)

    def _retryer(self):
        return retry(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential(multiplier=self._backoff_base, max=self._backoff_cap),
            retry=retry_if_exception_type(
                (ConnectionError, TimeoutError, OSError, requests.RequestException)
            ),
            reraise=True,
        )

    def supported_intervals(self) -> Iterable[Interval]:
        return tuple(_INTERVAL_MAP.keys())

    def get_kline(
        self,
        symbol: str,
        interval: Interval | str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> pd.DataFrame:
        interval = Interval(interval) if isinstance(interval, str) else interval
        if interval not in _INTERVAL_MAP:
            raise ValueError(f"okx 不支持周期: {interval}")
        tf = _INTERVAL_MAP[interval]
        inst_id = to_okx_inst_id(symbol)

        @self._retryer()
        def _fetch():
            exchange = getattr(self, "_exchange", None)
            if exchange is not None:
                since = int(start.timestamp() * 1000) if start else None
                return exchange.fetch_ohlcv(
                    to_ccxt_symbol(symbol), timeframe=tf.lower(), since=since, limit=limit
                )

            rows_by_timestamp: dict[int, list] = {}
            after = int(end.timestamp() * 1000) if end else None
            since = int(start.timestamp() * 1000) if start else None
            while len(rows_by_timestamp) < limit:
                params: dict[str, str | int] = {
                    "instId": inst_id,
                    "bar": tf,
                    "limit": min(limit - len(rows_by_timestamp), 300),
                }
                if after is not None:
                    params["after"] = after
                response = self._session.get(_CANDLES_URL, params=params, timeout=(5, 15))
                response.raise_for_status()
                payload = response.json()
                if payload.get("code") != "0":
                    raise RuntimeError(payload.get("msg") or "OKX candle request failed")
                page = payload.get("data") or []
                if not page:
                    break
                oldest = min(int(row[0]) for row in page)
                for row in page:
                    timestamp = int(row[0])
                    if since is None or timestamp >= since:
                        rows_by_timestamp[timestamp] = row[:6]
                if (since is not None and oldest <= since) or oldest == after:
                    break
                after = oldest
            return [rows_by_timestamp[key] for key in sorted(rows_by_timestamp)][-limit:]

        try:
            raw = _fetch()
        except Exception:
            logger.exception("okx get_kline failed: %s", inst_id)
            return pd.DataFrame()

        if not raw:
            return pd.DataFrame()
        df = pd.DataFrame(raw, columns=["ts_ms", "open", "high", "low", "close", "volume"])
        df["ts_ms"] = pd.to_numeric(df["ts_ms"], errors="coerce")
        df["datetime"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True).dt.tz_convert(None)
        df = df.drop(columns=["ts_ms"])
        df["symbol"] = inst_id
        df["market"] = self.market
        df["interval"] = interval.value
        df["amount"] = None
        df["turnover"] = None
        result = normalize_ohlcv_rows(
            df[
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
            ]
        )
        result.attrs["corporate_action_adjustment"] = "not_applicable"
        return result
