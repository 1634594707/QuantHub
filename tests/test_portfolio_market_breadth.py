from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd

from apps.api.domains.portfolio import service


def test_market_breadth_uses_configured_primary_realtime_quote(monkeypatch) -> None:
    monkeypatch.setattr(service, "CONFIG", {"breadth_basket": [("600519", "消费")]})
    monkeypatch.setattr(service, "_market_fetch_disabled", lambda: False)
    monkeypatch.setattr(service, "_configured_primary_source", lambda _market: "tencent")

    class _Primary:
        name = "tencent"

        @staticmethod
        def source_plan(operation: str, interval: str | None = None) -> list[dict]:
            del interval
            return [{"name": "tencent", "priority": 1}] if operation == "get_realtime_quote" else []

        @staticmethod
        def get_realtime_quote(_symbol: str):
            return SimpleNamespace(
                source="tencent",
                market="a_shares",
                price=110.0,
                prev_close=100.0,
            )

    monkeypatch.setattr(service, "get_data_source", lambda _market: _Primary())
    monkeypatch.setattr(
        service,
        "tencent_quote_detail",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("legacy endpoint used")),
    )

    result = service.market_breadth()

    assert result["up"] == 1
    assert result["flat"] == 0
    assert result["down"] == 0
    assert result["sectors"] == [{"name": "消费", "chgPct": 10.0}]


def test_market_breadth_does_not_switch_to_tencent_when_primary_lacks_quotes(monkeypatch) -> None:
    monkeypatch.setattr(service, "CONFIG", {"breadth_basket": [("600519", "消费")]})
    monkeypatch.setattr(service, "_market_fetch_disabled", lambda: False)
    monkeypatch.setattr(service, "_configured_primary_source", lambda _market: "akshare")

    class _Primary:
        name = "akshare"

        @staticmethod
        def source_plan(operation: str, interval: str | None = None) -> list[dict]:
            del interval
            return [{"name": "akshare", "priority": 1}] if operation == "get_kline" else []

    monkeypatch.setattr(service, "get_data_source", lambda _market: _Primary())
    monkeypatch.setattr(
        service,
        "tencent_quote_detail",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("secondary endpoint used")),
    )

    result = service.market_breadth()

    assert result["sectors"] == []
    assert "未声明实时行情能力" in result["note"]


def test_latest_close_snapshot_preserves_primary_source_and_bar_time(monkeypatch) -> None:
    bar_at = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
    frame = pd.DataFrame({"datetime": [bar_at], "close": [100.0]})
    frame.attrs["_source"] = "okx"
    frame.attrs["_data_contract"] = {"kline_semantics": "bar_snapshot"}
    frame.attrs["_data_contract"]["name"] = "okx"
    frame.attrs["_source_plan"] = [{"name": "okx", "priority": 1}]

    class _Source:
        name = "okx"

        def get_kline(self, *_args, **_kwargs):
            return frame

    monkeypatch.setattr(service, "_market_fetch_disabled", lambda: False)
    monkeypatch.setattr(service, "get_data_source", lambda _market: _Source())

    snapshot = service.latest_close_snapshot("BTC-USDT", "crypto", "1h")

    assert snapshot == {
        "price": 100.0,
        "source": "okx",
        "primary_source": "okx",
        "source_role": "primary",
        "cache_status": "miss",
        "transport": "online",
        "data_semantics": "bar_snapshot",
        "bar_at": bar_at.isoformat(),
        "observed_at": bar_at.isoformat(),
        "quality_status": "closed_bar",
        "error": None,
    }


def test_latest_close_snapshot_never_marks_local_data_executable(monkeypatch) -> None:
    bar_at = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
    frame = pd.DataFrame({"datetime": [bar_at], "close": [100.0]})
    frame.attrs["_source"] = "local_parquet"
    frame.attrs["_data_contract"] = {"kline_semantics": "bar_snapshot"}

    class _Source:
        name = "okx"

        def get_kline(self, *_args, **_kwargs):
            return frame

    monkeypatch.setattr(service, "_market_fetch_disabled", lambda: False)
    monkeypatch.setattr(service, "get_data_source", lambda _market: _Source())

    snapshot = service.latest_close_snapshot("BTC-USDT", "crypto", "1h")

    assert snapshot["source"] == "local_parquet"
    assert snapshot["bar_at"] == bar_at.isoformat()
    assert snapshot["source_role"] == "unverified"
    assert snapshot["quality_status"] == "unavailable"
    assert snapshot["error"]


def test_latest_close_snapshot_labels_same_primary_cache_non_executable(monkeypatch) -> None:
    bar_at = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
    frame = pd.DataFrame({"datetime": [bar_at], "close": [100.0]})
    # This matches CacheStore's restored provenance: source survives, while the
    # direct request contract and source plan deliberately do not.
    frame.attrs["_source"] = "tencent"

    class _Source:
        name = "tencent"

        def get_kline(self, *_args, **_kwargs):
            return frame

    monkeypatch.setattr(service, "_market_fetch_disabled", lambda: False)
    monkeypatch.setattr(service, "get_data_source", lambda _market: _Source())

    snapshot = service.latest_close_snapshot("AAPL", "us_stocks", "1d")

    assert snapshot["price"] == 100.0
    assert snapshot["source"] == "tencent"
    assert snapshot["source_role"] == "primary_cache"
    assert snapshot["cache_status"] == "hit"
    assert snapshot["transport"] == "cache"
    assert snapshot["quality_status"] == "cached_primary"
    assert snapshot["error"]


def test_portfolio_snapshot_never_uses_cost_as_a_missing_market_price(monkeypatch) -> None:
    holding = {
        "id": "holding-1",
        "code": "AAPL",
        "name": "Apple",
        "shares": 2.0,
        "cost": 100.0,
        "market": "us_stocks",
    }
    monkeypatch.setattr(service.repository, "list_holdings", lambda: [holding])
    monkeypatch.setattr(
        service,
        "latest_close_snapshot",
        lambda *_args, **_kwargs: {
            "price": None,
            "source": "unknown",
            "primary_source": "tencent",
            "source_role": "unavailable",
            "cache_status": "not_attempted",
            "transport": "none",
            "quality_status": "unavailable",
            "error": "primary unavailable",
        },
    )

    result = service.portfolio_snapshot()

    row = result["holdings"][0]
    assert row["price"] is None
    assert row["marketValue"] is None
    assert row["pnl"] is None
    assert row["costValue"] == 200.0
    assert row["available"] is False
    assert result["summary"]["nav"] is None
    assert result["summary"]["chgBasedScore"] is None
    assert result["summary"]["costBasis"] == 200.0
    assert result["summary"]["valuationStatus"] == "unavailable"


def test_portfolio_snapshot_does_not_promote_unverified_positive_price(monkeypatch) -> None:
    holding = {
        "id": "holding-unverified",
        "code": "AAPL",
        "name": "Apple",
        "shares": 1.0,
        "cost": 100.0,
        "market": "us_stocks",
    }
    monkeypatch.setattr(service.repository, "list_holdings", lambda: [holding])
    monkeypatch.setattr(
        service,
        "latest_close_snapshot",
        lambda *_args, **_kwargs: {
            "price": 150.0,
            "source": "local_parquet",
            "primary_source": "tencent",
            "source_role": "unverified",
            "cache_status": "unknown",
            "transport": "local",
            "quality_status": "unavailable",
            "error": "未验证行情来源",
        },
    )

    result = service.portfolio_snapshot()

    row = result["holdings"][0]
    assert row["price"] is None
    assert row["available"] is False
    assert result["summary"]["nav"] is None
    assert result["summary"]["unpricedPositions"] == 1


class _QuotePrimary:
    name = "tencent"
    market = "a_shares"

    def __init__(self, quote=None, error: Exception | None = None) -> None:
        self.quote = quote
        self.error = error
        self.kline_calls = 0

    def source_plan(self, operation: str, interval: str | None = None) -> list[dict]:
        del interval
        if operation == "get_realtime_quote":
            return [{"name": self.name, "priority": 1}]
        return []

    def get_realtime_quote(self, _symbol: str):
        if self.error:
            raise self.error
        return self.quote

    def get_kline(self, *_args, **_kwargs):
        self.kline_calls += 1
        raise AssertionError("realtime primary failure must not switch to K-line")


def test_quote_item_uses_only_declared_realtime_primary(monkeypatch) -> None:
    source = _QuotePrimary(
        quote=SimpleNamespace(
            source="tencent",
            market="a_shares",
            price=101.0,
            observed_at=datetime(2026, 8, 16, 8, tzinfo=UTC),
            name="贵州茅台",
            prev_close=100.0,
            change_pct=None,
        )
    )
    monkeypatch.setattr(service, "_configured_primary_source", lambda _market: "tencent")
    monkeypatch.setattr(service, "get_data_source", lambda _market: source)
    monkeypatch.setattr(
        service,
        "tencent_quote_detail",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("legacy endpoint used")),
    )

    result = service.quote_item("600519", "a_shares")

    assert result["available"] is True
    assert result["source"] == "tencent"
    assert result["price"] == 101.0
    assert result["chgPct"] == 1.0
    assert source.kline_calls == 0


def test_quote_item_realtime_failure_is_terminal(monkeypatch) -> None:
    source = _QuotePrimary(error=ConnectionError("primary down"))
    monkeypatch.setattr(service, "_configured_primary_source", lambda _market: "tencent")
    monkeypatch.setattr(service, "get_data_source", lambda _market: source)

    result = service.quote_item("600519", "a_shares")

    assert result["available"] is False
    assert result["source"] == "tencent"
    assert "primary down" in result["error"]
    assert source.kline_calls == 0


def test_quote_item_primary_without_realtime_uses_its_own_daily_bars(monkeypatch) -> None:
    frame = pd.DataFrame(
        {
            "datetime": [
                datetime(2026, 8, 15, tzinfo=UTC),
                datetime(2026, 8, 16, tzinfo=UTC),
            ],
            "close": [100.0, 105.0],
        }
    )
    frame.attrs["_source"] = "okx"
    frame.attrs["_data_contract"] = {"name": "okx", "kline_semantics": "bar_snapshot"}
    frame.attrs["_source_plan"] = [{"name": "okx", "priority": 1}]

    class _BarPrimary:
        name = "okx"
        market = "crypto"

        def source_plan(self, operation: str, interval: str | None = None) -> list[dict]:
            if operation == "get_kline" and interval == "1d":
                return [{"name": "okx", "priority": 1}]
            return []

        def get_kline(self, *_args, **_kwargs):
            return frame

    source = _BarPrimary()
    monkeypatch.setattr(service, "_configured_primary_source", lambda _market: "okx")
    monkeypatch.setattr(service, "get_data_source", lambda _market: source)

    result = service.quote_item("BTC-USDT", "crypto")

    assert result["available"] is True
    assert result["source"] == "okx"
    assert result["price"] == 105.0
    assert result["chgPct"] == 5.0
    assert result["freshness"] == "daily_close"


def test_quote_item_single_bar_does_not_query_another_endpoint(monkeypatch) -> None:
    frame = pd.DataFrame({"datetime": [datetime(2026, 8, 16, tzinfo=UTC)], "close": [105.0]})
    frame.attrs["_source"] = "okx"

    class _BarPrimary:
        name = "okx"
        market = "crypto"

        def source_plan(self, operation: str, interval: str | None = None) -> list[dict]:
            return [{"name": "okx", "priority": 1}] if operation == "get_kline" else []

        def get_kline(self, *_args, **_kwargs):
            return frame

    monkeypatch.setattr(service, "_configured_primary_source", lambda _market: "okx")
    monkeypatch.setattr(service, "get_data_source", lambda _market: _BarPrimary())
    monkeypatch.setattr(
        service,
        "tencent_quote_detail",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cross-endpoint lookup")),
    )

    result = service.quote_item("BTC-USDT", "crypto")

    assert result["available"] is True
    assert result["chgPct"] is None


def test_quote_item_rejects_non_primary_bar(monkeypatch) -> None:
    frame = pd.DataFrame({"datetime": [datetime(2026, 8, 16, tzinfo=UTC)], "close": [105.0]})
    frame.attrs["_source"] = "local_parquet"

    class _BarPrimary:
        name = "okx"
        market = "crypto"

        def source_plan(self, operation: str, interval: str | None = None) -> list[dict]:
            return [{"name": "okx", "priority": 1}] if operation == "get_kline" else []

        def get_kline(self, *_args, **_kwargs):
            return frame

    monkeypatch.setattr(service, "_configured_primary_source", lambda _market: "okx")
    monkeypatch.setattr(service, "get_data_source", lambda _market: _BarPrimary())

    result = service.quote_item("BTC-USDT", "crypto")

    assert result["available"] is False
    assert result["source"] == "local_parquet"
