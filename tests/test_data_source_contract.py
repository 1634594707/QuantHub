from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import pandas as pd

from core.data_feed.base import DataSource, Interval, News
from core.data_feed.factory import DataSourceProxy


class _KlineSource(DataSource):
    market = "a_shares"

    def __init__(self, name: str, *, rows: int) -> None:
        self.name = name
        self.rows = rows
        self.calls = 0

    def supported_intervals(self):
        return (Interval.DAILY,)

    def get_kline(self, symbol, interval, start=None, end=None, limit=500):
        self.calls += 1
        if not self.rows:
            return pd.DataFrame()
        return pd.DataFrame({"datetime": [datetime(2026, 8, 12, tzinfo=UTC)], "close": [100.0]})


class _NewsSource(DataSource):
    name = "news_only"
    market = "a_shares"

    def supported_intervals(self):
        return ()

    def get_kline(self, symbol, interval, start=None, end=None, limit=500):
        raise AssertionError("news-only source must not receive kline requests")

    def get_news(self, symbol=None, limit=50):
        return [News(title="n", content="n", ts=datetime.now(UTC), source=self.name)]


def test_kline_fallback_filters_capabilities_and_preserves_priority() -> None:
    primary = _KlineSource("tencent", rows=0)
    news = _NewsSource()
    fallback = _KlineSource("eastmoney", rows=1)
    proxy = DataSourceProxy(primary, [news, fallback], cache=Mock())

    plan = proxy.source_plan("get_kline", Interval.DAILY)
    frame = proxy.get_kline(
        "600519",
        Interval.DAILY,
        start=datetime(2026, 8, 1, tzinfo=UTC),
        limit=10,
    )

    assert [item["name"] for item in plan] == ["tencent", "eastmoney"]
    assert [item["priority"] for item in plan] == [1, 3]
    assert all(item["kline_semantics"] == "bar_snapshot" for item in plan)
    assert all(item["tick_by_tick"] is False for item in plan)
    assert primary.calls == 1
    assert fallback.calls == 1
    assert frame.attrs["_source"] == "eastmoney"
    assert frame.attrs["_source_plan"] == plan
    assert frame.attrs["_data_contract"]["tick_by_tick"] is False


def test_news_plan_keeps_news_capable_source_out_of_kline_plan() -> None:
    primary = _KlineSource("tencent", rows=1)
    news = _NewsSource()
    proxy = DataSourceProxy(primary, [news], cache=Mock())

    assert [item["name"] for item in proxy.source_plan("get_news")] == ["news_only"]
    assert [item["name"] for item in proxy.source_plan("get_kline", "1d")] == ["tencent"]


def test_source_plan_preserves_configured_priority_after_adapter_construction_failure() -> None:
    primary = _KlineSource("tencent", rows=1)
    fallback = _KlineSource("local_parquet", rows=1)
    primary._configured_priority = 1
    fallback._configured_priority = 5
    proxy = DataSourceProxy(primary, [fallback], cache=Mock())

    assert [item["priority"] for item in proxy.source_plan("get_kline", "1d")] == [1, 5]
