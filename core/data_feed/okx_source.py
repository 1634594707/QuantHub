"""OKX 数据源（加密，基于 ccxt）。

依赖 ccxt，按需安装: pip install ccxt
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime

import pandas as pd
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
    Interval.H1: "1h",
    Interval.H4: "4h",
    Interval.DAILY: "1d",
    Interval.WEEKLY: "1w",
}


def to_ccxt_symbol(symbol: str) -> str:
    """把常见币对代码统一为 CCXT 永续合约格式。"""
    normalized = symbol.strip().upper()
    if "/" in normalized:
        base_quote, _, settlement = normalized.partition(":")
        quote = base_quote.split("/", 1)[1]
        return f"{base_quote}:{settlement or quote}"
    if "-" in normalized:
        base, quote = normalized.split("-", 1)
        return f"{base}/{quote}:{quote}"
    return f"{normalized}/USDT:USDT"


class OkxSource(DataSource):
    """OKX 加密数据源（ccxt 实现）。"""

    name = "okx"
    market = "crypto"

    def __init__(
        self, api_key: str | None = None, secret: str | None = None, passphrase: str | None = None
    ) -> None:
        try:
            import ccxt
        except ImportError as e:
            raise ImportError("ccxt 未安装，请运行: pip install ccxt") from e
        self._ccxt = ccxt
        self._exchange = ccxt.okx(
            {
                "apiKey": api_key or "",
                "secret": secret or "",
                "password": passphrase or "",
                "enableRateLimit": True,
                "options": {"defaultType": "swap"},
            }
        )
        retry_cfg = get_config().get("data_feed", {}).get("retry", {})
        self._max_attempts = retry_cfg.get("max_attempts", 4)
        self._backoff_base = retry_cfg.get("backoff_base", 1.5)
        self._backoff_cap = retry_cfg.get("backoff_cap", 30)

    def _retryer(self):
        return retry(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential(multiplier=self._backoff_base, max=self._backoff_cap),
            retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
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
        # ccxt symbol 格式: BTC/USDT:USDT (永续)
        symbol = to_ccxt_symbol(symbol)

        @self._retryer()
        def _fetch():
            since = None
            if start:
                since = int(start.timestamp() * 1000)
            return self._exchange.fetch_ohlcv(
                symbol,
                timeframe=tf,
                since=since,
                limit=limit,
            )

        try:
            raw = _fetch()
        except Exception:
            logger.exception("okx get_kline 失败: %s", symbol)
            return pd.DataFrame()

        if not raw:
            return pd.DataFrame()
        df = pd.DataFrame(raw, columns=["ts_ms", "open", "high", "low", "close", "volume"])
        df["datetime"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True).dt.tz_convert(None)
        df = df.drop(columns=["ts_ms"])
        df["symbol"] = symbol
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
