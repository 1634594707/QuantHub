# -*- coding: utf-8 -*-
"""数据层统一入口。

对外暴露:
    get_data_source(market) -> DataSourceProxy (带缓存+fallback)
    Kline / News / Announcement / DataSource / Interval / Market
"""
from __future__ import annotations

from core.data_feed.base import (
    Announcement,
    DataSource,
    Interval,
    Kline,
    Market,
    News,
    klines_to_df,
)
from core.data_feed.cache import CacheStore, cache_key_date
from core.data_feed.factory import (
    DataSourceProxy,
    get_data_source,
    register_source,
)

__all__ = [
    "Announcement",
    "DataSource",
    "DataSourceProxy",
    "Interval",
    "Kline",
    "Market",
    "News",
    "CacheStore",
    "cache_key_date",
    "get_data_source",
    "klines_to_df",
    "register_source",
]
