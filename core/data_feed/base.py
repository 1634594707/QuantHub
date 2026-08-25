"""数据层统一抽象。

定义:
    - Kline / News / Announcement 数据类
    - DataSource 抽象接口 (get_kline / get_news / get_announcements)
    - Market / Interval 枚举

具体实现见 akshare_source / eastmoney_source / okx_source。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import pandas as pd


class Market(str, Enum):
    """市场标识。"""

    A_SHARES = "a_shares"
    CRYPTO = "crypto"
    MT5 = "mt5"


class Interval(str, Enum):
    """K线周期（统一枚举，各 source 负责映射到具体 API 参数）。"""

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    DAILY = "1d"
    WEEKLY = "1w"


@dataclass
class Kline:
    """统一 K线结构（可批量组装为 DataFrame）。"""

    symbol: str
    market: str
    interval: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    ts: datetime
    amount: float | None = None  # 成交额（A股常用）
    turnover: float | None = None  # 换手率（加密无）

    def to_row(self) -> dict:
        return {
            "symbol": self.symbol,
            "market": self.market,
            "interval": self.interval,
            "datetime": self.ts,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "amount": self.amount,
            "turnover": self.turnover,
        }


@dataclass(frozen=True)
class RealtimeQuote:
    """A provider-verified point-in-time quote.

    Quotes deliberately stay outside the bar cache contract: an analyzer must
    be able to distinguish a live provider response from a historical bar.
    """

    symbol: str
    market: str
    price: float
    observed_at: datetime
    source: str
    name: str | None = None
    prev_close: float | None = None
    change_pct: float | None = None


@dataclass
class News:
    """新闻条目。"""

    title: str
    content: str
    ts: datetime
    source: str  # 来源（东财/新浪/...）
    url: str | None = None
    symbols: list[str] = field(default_factory=list)  # 关联标的


@dataclass
class Announcement:
    """上市公司公告。"""

    symbol: str
    title: str
    ts: datetime
    content: str | None = None
    url: str | None = None
    ann_type: str | None = None  # 公告类型（如"股东回馈"）


class DataSource(ABC):
    """数据源抽象接口。

    所有具体数据源必须实现 get_kline；news/announcement 视能力实现，
    不支持的返回空列表；调用方必须依据数据契约显式处理能力不足，不能据此切换其他供应商。
    """

    name: str = "abstract"
    market: str = "abstract"

    @abstractmethod
    def get_kline(
        self,
        symbol: str,
        interval: Interval | str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> pd.DataFrame:
        """获取 K 线，返回 DataFrame，列见 Kline.to_row()。"""
        raise NotImplementedError

    def get_realtime_quote(self, symbol: str) -> RealtimeQuote | None:
        """Fetch one provider-verified live quote when the adapter supports it.

        Returning ``None`` means this primary has no quote for the symbol; it
        never authorizes a caller to try another source.
        """
        return None

    def get_news(self, symbol: str | None = None, limit: int = 50) -> list[News]:
        """获取新闻列表，默认返回空（不支持的数据源）。"""
        return []

    def get_announcements(self, symbol: str, limit: int = 50) -> list[Announcement]:
        """获取公告列表，默认返回空。"""
        return []

    def supported_intervals(self) -> Iterable[Interval]:
        """返回该数据源支持的周期。"""
        return tuple(Interval)

    def data_contract(self) -> dict:
        """Return capabilities without implying that bar snapshots are tick data."""
        operations = ["get_kline"] if tuple(self.supported_intervals()) else []
        has_realtime_quote = type(self).get_realtime_quote is not DataSource.get_realtime_quote
        if has_realtime_quote:
            operations.append("get_realtime_quote")
        if type(self).get_news is not DataSource.get_news:
            operations.append("get_news")
        if type(self).get_announcements is not DataSource.get_announcements:
            operations.append("get_announcements")
        return {
            "name": self.name,
            "market": self.market,
            "operations": operations,
            "intervals": [item.value for item in self.supported_intervals()],
            "kline_semantics": "bar_snapshot" if "get_kline" in operations else None,
            "realtime_quote_semantics": "provider_snapshot" if has_realtime_quote else None,
            "tick_by_tick": False,
        }


def klines_to_df(klines: list[Kline]) -> pd.DataFrame:
    """把 Kline 列表转为 DataFrame，按 ts 升序。"""
    if not klines:
        return pd.DataFrame(
            columns=[
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
        )
    df = pd.DataFrame([k.to_row() for k in klines])
    df = df.sort_values("datetime").reset_index(drop=True)
    return df
