"""Sina Finance news source for A-share symbols.

This source intentionally does not depend on AkShare or Eastmoney.  It is a
news-only fallback backed by Sina's public per-stock news page.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import datetime
from html.parser import HTMLParser

import pandas as pd
import requests

from core.data_feed.base import DataSource, Interval, News

logger = logging.getLogger(__name__)

_ARTICLE_URL = re.compile(
    r"^https?://finance\.sina\.com\.cn/.+/(?P<date>\d{4}-\d{2}-\d{2})/.+\.shtml(?:\?.*)?$"
)


class _ArticleLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href and _ARTICLE_URL.match(href):
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href:
            return
        title = " ".join("".join(self._text).split())
        if title:
            self.links.append((title, self._href))
        self._href = None
        self._text = []


def _to_sina_symbol(symbol: str) -> str:
    value = symbol.strip().lower()
    if value.startswith(("sh", "sz", "bj")):
        return value
    if value.startswith(("60", "68", "69", "50", "51")):
        return f"sh{value}"
    if value.startswith(("4", "8", "92")):
        return f"bj{value}"
    return f"sz{value}"


class SinaNewsSource(DataSource):
    """Independent Sina Finance news fallback (news only)."""

    name = "sina_news"
    market = "a_shares"

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://finance.sina.com.cn/stock/",
            }
        )

    def supported_intervals(self) -> Iterable[Interval]:
        return ()

    def get_kline(
        self,
        symbol: str,
        interval: Interval | str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> pd.DataFrame:
        return pd.DataFrame()

    def get_news(self, symbol: str | None = None, limit: int = 50) -> list[News]:
        if not symbol:
            return []

        normalized = symbol.strip().upper()
        url = "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllNewsStock.php"
        try:
            response = self._session.get(
                url,
                params={"symbol": _to_sina_symbol(normalized), "Page": 1},
                timeout=15,
            )
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "gb18030"
            parser = _ArticleLinkParser()
            parser.feed(response.text)
        except Exception:
            logger.exception("sina get_news failed: %s", normalized)
            return []

        result: list[News] = []
        seen: set[str] = set()
        for title, article_url in parser.links:
            if article_url in seen:
                continue
            seen.add(article_url)
            matched = _ARTICLE_URL.match(article_url)
            try:
                published = (
                    datetime.strptime(matched.group("date"), "%Y-%m-%d")
                    if matched
                    else datetime.now()
                )
            except ValueError:
                published = datetime.now()
            result.append(
                News(
                    title=title,
                    content=title,
                    ts=published,
                    source="新浪财经",
                    url=article_url.replace("http://", "https://", 1),
                    symbols=[normalized],
                )
            )
            if len(result) >= max(1, int(limit)):
                break
        return result
