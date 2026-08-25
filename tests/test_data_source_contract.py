from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import pandas as pd
import pytest

from core.config import get_config
from core.data_feed.base import DataSource, Interval, News
from core.data_feed.cache import CacheStore
from core.data_feed.factory import DataSourceProxy, get_configured_source, get_data_source


class _KlineSource(DataSource):
    market = "a_shares"

    def __init__(self, name: str, *, rows: int = 1, error: Exception | None = None) -> None:
        self.name = name
        self.rows = rows
        self.error = error
        self.calls = 0

    def supported_intervals(self):
        return (Interval.DAILY,)

    def get_kline(self, symbol, interval, start=None, end=None, limit=500):
        self.calls += 1
        if self.error:
            raise self.error
        if not self.rows:
            return pd.DataFrame()
        return pd.DataFrame({"datetime": [datetime(2026, 8, 12, tzinfo=UTC)], "close": [100.0]})


class _NewsSource(DataSource):
    name = "news_only"
    market = "a_shares"

    def __init__(self) -> None:
        self.calls = 0

    def supported_intervals(self):
        return ()

    def get_kline(self, symbol, interval, start=None, end=None, limit=500):
        raise AssertionError("news-only source must not receive kline requests")

    def get_news(self, symbol=None, limit=50):
        self.calls += 1
        return [News(title="n", content="n", ts=datetime.now(UTC), source=self.name)]


def test_primary_empty_result_never_accesses_secondary() -> None:
    primary = _KlineSource("tencent", rows=0)
    secondary = _KlineSource("eastmoney")
    proxy = DataSourceProxy(primary, cache=Mock())

    frame = proxy.get_kline(
        "600519", Interval.DAILY, start=datetime(2026, 8, 1, tzinfo=UTC), limit=10
    )

    assert frame.empty
    assert primary.calls == 1
    assert secondary.calls == 0
    assert [item["name"] for item in proxy.source_plan("get_kline", Interval.DAILY)] == ["tencent"]


def test_primary_failure_never_accesses_secondary() -> None:
    primary = _KlineSource("tencent", error=RuntimeError("primary unavailable"))
    secondary = _KlineSource("eastmoney")
    proxy = DataSourceProxy(primary, cache=Mock())

    with pytest.raises(RuntimeError, match="primary unavailable"):
        proxy.get_kline("600519", Interval.DAILY, start=datetime(2026, 8, 1, tzinfo=UTC), limit=10)

    assert primary.calls == 1
    assert secondary.calls == 0


def test_proxy_does_not_accept_fallback_sources() -> None:
    with pytest.raises(TypeError):
        DataSourceProxy(_KlineSource("tencent"), [_KlineSource("eastmoney")], cache=Mock())


def test_source_plan_only_exposes_primary_capability() -> None:
    primary = _KlineSource("tencent")
    proxy = DataSourceProxy(primary, cache=Mock())

    assert [item["name"] for item in proxy.source_plan("get_kline", "1d")] == ["tencent"]
    assert proxy.source_plan("get_news") == []


def test_primary_construction_failure_does_not_promote_another_source(monkeypatch) -> None:
    cfg = {
        "data_sources": {
            "primary": "broken_primary",
        }
    }
    build_calls: list[str] = []

    monkeypatch.setattr("core.data_feed.factory.get_config", lambda market: cfg)

    def build(name, **kwargs):
        build_calls.append(name)
        if name == "broken_primary":
            raise ImportError("missing primary dependency")
        return _KlineSource(name)

    monkeypatch.setattr("core.data_feed.factory._build_source", build)

    with pytest.raises(RuntimeError, match="primary 数据源不可用: broken_primary"):
        get_data_source("a_shares")

    assert build_calls == ["broken_primary"]


def test_explicit_configured_source_remains_available_for_diagnostics(monkeypatch) -> None:
    cfg = {
        "data_sources": {
            "primary": "tencent",
            "local_parquet": {"root": "data"},
        }
    }
    secondary = _KlineSource("local_parquet")
    monkeypatch.setattr("core.data_feed.factory.get_config", lambda market: cfg)
    monkeypatch.setattr("core.data_feed.factory._build_source", lambda name, **kwargs: secondary)

    assert get_configured_source("a_shares", "local_parquet") is secondary


def test_legacy_fallback_config_is_rejected_before_any_source_is_built(monkeypatch) -> None:
    cfg = {"data_sources": {"primary": "tencent", "fallback": ["eastmoney"]}}
    build = Mock()
    monkeypatch.setattr("core.data_feed.factory.get_config", lambda market: cfg)
    monkeypatch.setattr("core.data_feed.factory._build_source", build)

    with pytest.raises(ValueError, match=r"已移除的 data_sources\.fallback"):
        get_data_source("a_shares")
    with pytest.raises(ValueError, match=r"已移除的 data_sources\.fallback"):
        get_configured_source("a_shares", "eastmoney")

    build.assert_not_called()


def test_cache_entries_are_scoped_to_market_and_primary_source(tmp_path) -> None:
    """A cache written by an old provider must not survive as a new primary result."""
    previous_instance = CacheStore._instance
    CacheStore._instance = None
    try:
        cache = CacheStore(tmp_path / "cache.db")
        frame = pd.DataFrame({"datetime": [datetime(2026, 8, 12, tzinfo=UTC)], "close": [100.0]})
        cache.set_kline(
            "AAPL",
            "us_stocks",
            "1d",
            "2026-08-12",
            frame,
            source="tencent",
            limit=10,
        )
        cache.set_docs(
            "get_news",
            "AAPL",
            [{"title": "old primary"}],
            market="us_stocks",
            source="tencent",
            limit=10,
        )

        assert (
            cache.get_kline(
                "AAPL",
                "us_stocks",
                "1d",
                "2026-08-12",
                source="yahoo",
                limit=10,
            )
            is None
        )
        assert (
            cache.get_docs(
                "get_news",
                "AAPL",
                market="us_stocks",
                source="yahoo",
                limit=10,
            )
            is None
        )
        assert (
            cache.get_kline(
                "AAPL",
                "us_stocks",
                "1d",
                "2026-08-12",
                source="tencent",
                limit=10,
            )
            is not None
        )
    finally:
        connection = getattr(getattr(locals().get("cache", None), "_local", None), "conn", None)
        if connection is not None:
            connection.close()
        CacheStore._instance = previous_instance


@pytest.mark.parametrize("market", ["a_shares", "us_stocks", "crypto", "mt5"])
def test_production_market_configs_only_declare_a_primary_source(market: str) -> None:
    sources = get_config(market)["data_sources"]

    assert isinstance(sources.get("primary"), str)
    assert "fallback" not in sources
