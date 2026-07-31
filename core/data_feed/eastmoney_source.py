"""东方财富数据源（A股）。

直接调用东方财富 push2 接口，作为 akshare 的 fallback。
复用 trading-master/04-stock-selector/data/eastmoney_api.py 的接口约定。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

import pandas as pd
import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from core.config import get_config
from core.data_feed.base import (
    Announcement,
    DataSource,
    Interval,
    News,
)
from core.data_feed.quality import normalize_ohlcv_rows

logger = logging.getLogger(__name__)

_INTERVAL_MAP = {
    Interval.DAILY: "101",
    Interval.WEEKLY: "102",
    Interval.M1: "1",
    Interval.M5: "5",
    Interval.M15: "15",
    Interval.M30: "30",
    Interval.H1: "60",
}


class EastmoneySource(DataSource):
    """东方财富 push2 数据源。"""

    name = "eastmoney"
    market = "a_shares"

    PUSH2_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

    def __init__(self) -> None:
        cfg = get_config("a_shares").get("data_sources", {}).get("eastmoney", {})
        self._host = cfg.get("push2_host", "push2his.eastmoney.com")
        retry_cfg = get_config().get("data_feed", {}).get("retry", {})
        self._max_attempts = retry_cfg.get("max_attempts", 4)
        self._backoff_base = retry_cfg.get("backoff_base", 1.5)
        self._backoff_cap = retry_cfg.get("backoff_cap", 30)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "QuantHub/0.1"})

    def _retryer(self):
        return retry(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential(multiplier=self._backoff_base, max=self._backoff_cap),
            retry=retry_if_exception_type((requests.RequestException, OSError)),
            reraise=True,
        )

    @staticmethod
    def _symbol_to_secid(symbol: str) -> str:
        """A股票代码转东财 secid（沪市 1.前缀，深市 0.前缀）。"""
        if symbol.startswith("6"):
            return f"1.{symbol}"
        return f"0.{symbol}"

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
            raise ValueError(f"eastmoney 不支持周期: {interval}")
        secid = self._symbol_to_secid(symbol)
        end = end or datetime.now(UTC)
        start = start or (end - timedelta(days=limit))

        params = {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": _INTERVAL_MAP[interval],
            "fqt": "1",  # 前复权
            "beg": start.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
            "lmt": str(limit),
        }

        @self._retryer()
        def _fetch():
            r = self._session.get(self.PUSH2_URL, params=params, timeout=15)
            r.raise_for_status()
            return r.json()

        try:
            data = _fetch()
        except Exception:
            logger.exception("eastmoney get_kline 失败: %s", symbol)
            return pd.DataFrame()

        klines = data.get("data", {}).get("klines", [])
        if not klines:
            return pd.DataFrame()

        rows = []
        for line in klines:
            parts = line.split(",")
            if len(parts) < 7:
                continue
            try:
                rows.append(
                    {
                        "symbol": symbol,
                        "market": self.market,
                        "interval": interval.value,
                        "datetime": pd.to_datetime(parts[0]),
                        "open": float(parts[1]),
                        "close": float(parts[2]),
                        "high": float(parts[3]),
                        "low": float(parts[4]),
                        "volume": float(parts[5]),
                        "amount": float(parts[6]) if len(parts) > 6 else None,
                        "turnover": float(parts[10]) if len(parts) > 10 else None,
                    }
                )
            except (ValueError, IndexError):
                continue
        if not rows:
            return pd.DataFrame()
        result = normalize_ohlcv_rows(pd.DataFrame(rows))
        result.attrs["corporate_action_adjustment"] = "qfq"
        return result

    def get_announcements(self, symbol: str, limit: int = 50) -> list[Announcement]:
        """东财公告接口（简化实现，如需更完整复用羊毛监控爬虫）。"""
        url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
        params = {
            "sr": "-1",
            "page_size": str(limit),
            "page_index": "1",
            "ann_type": "A",
            "stock_list": symbol,
            "f_node": "0",
            "s_node": "0",
        }

        @self._retryer()
        def _fetch():
            r = self._session.get(url, params=params, timeout=15)
            r.raise_for_status()
            return r.json()

        try:
            data = _fetch()
        except Exception:
            logger.exception("eastmoney get_announcements 失败: %s", symbol)
            return []
        anns: list[Announcement] = []
        for item in data.get("data", {}).get("list", [])[:limit]:
            ts = item.get("notice_date")
            ts_dt = pd.to_datetime(ts) if ts else datetime.now(UTC)
            anns.append(
                Announcement(
                    symbol=symbol,
                    title=item.get("title", ""),
                    ts=ts_dt.to_pydatetime() if hasattr(ts_dt, "to_pydatetime") else ts_dt,
                    url=item.get("art_code"),
                    ann_type=item.get("columns_name"),
                )
            )
        return anns

    def get_news(self, symbol: str | None = None, limit: int = 50) -> list[News]:
        """Fetch stock-related articles directly from Eastmoney search."""
        if not symbol:
            return []

        url = "https://search-api-web.eastmoney.com/search/jsonp"
        callback = "jQuery35101792940631092459_1764599530165"
        inner_param = {
            "uid": "",
            "keyword": symbol,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "param": {
                "cmsArticleWebOld": {
                    "searchScope": "default",
                    "sort": "default",
                    "pageIndex": 1,
                    "pageSize": min(max(1, int(limit)), 100),
                    "preTag": "<em>",
                    "postTag": "</em>",
                }
            },
        }
        params = {
            "cb": callback,
            "param": json.dumps(inner_param, ensure_ascii=False),
            "_": "1764599530176",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": f"https://so.eastmoney.com/news/s?keyword={symbol}",
        }

        @self._retryer()
        def _fetch() -> str:
            response = self._session.get(url, params=params, headers=headers, timeout=15)
            response.raise_for_status()
            return response.text

        try:
            data_text = _fetch()
            prefix = callback + "("
            payload_text = (
                data_text[len(prefix) : -1] if data_text.startswith(prefix) else data_text
            )
            payload = json.loads(payload_text)
        except Exception:
            logger.exception("eastmoney get_news 失败: %s", symbol)
            return []

        def _clean(value: object) -> str:
            return (
                str(value or "")
                .replace("<em>", "")
                .replace("</em>", "")
                .replace("\u3000", "")
                .replace("\r", " ")
                .replace("\n", " ")
                .strip()
            )

        items = payload.get("result", {}).get("cmsArticleWebOld", [])
        news: list[News] = []
        for item in items[:limit]:
            try:
                published = pd.to_datetime(item.get("date")).to_pydatetime()
            except (TypeError, ValueError, OverflowError):
                published = datetime.now(UTC)
            article_code = str(item.get("code", "") or "")
            news.append(
                News(
                    title=_clean(item.get("title")),
                    content=_clean(item.get("content")),
                    ts=published,
                    source=str(item.get("mediaName") or "东方财富"),
                    url=(
                        f"https://finance.eastmoney.com/a/{article_code}.html"
                        if article_code
                        else None
                    ),
                    symbols=[symbol],
                )
            )
        return news
