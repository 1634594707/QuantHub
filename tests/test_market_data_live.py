from __future__ import annotations

import json
from datetime import UTC, datetime

from apps.api.domains.factor_factory import service as factor_factory_service
from apps.api.domains.factor_factory.schemas import FactorFactoryStartRequest
from core.backtest import market_data


class FakeExchange:
    rateLimit = 0

    def __init__(self, rows: list[list[float]]) -> None:
        self.rows = rows
        self.calls: list[int | None] = []

    def fetch_ohlcv(
        self,
        _symbol: str,
        _interval: str,
        since: int | None,
        limit: int,
    ) -> list[list[float]]:
        self.calls.append(since)
        eligible = self.rows if since is None else [row for row in self.rows if row[0] >= since]
        return eligible[: min(limit, 3)]


def _rows(count: int) -> list[list[float]]:
    hour_ms = 60 * 60 * 1000
    latest = int(datetime.now(UTC).timestamp() * 1000) - 60_000
    return [
        [
            latest - (count - index - 1) * hour_ms,
            100 + index,
            101 + index,
            99 + index,
            100.5 + index,
            1_000 + index,
        ]
        for index in range(count)
    ]


def test_live_ohlcv_pages_forward_and_returns_latest_requested_window(
    tmp_path, monkeypatch
) -> None:
    rows = _rows(20)
    exchange = FakeExchange(rows)
    monkeypatch.setattr(market_data, "MARKET_CACHE_DIR", tmp_path)
    monkeypatch.setattr(market_data, "_build_public_exchange", lambda: exchange)

    snapshot = market_data.fetch_live_ohlcv(
        "BTC-USDT-SWAP",
        "1h",
        n_bars=8,
        use_cache=False,
    )

    assert len(snapshot.df) == 8
    assert snapshot.df["datetime"].iloc[-1].timestamp() * 1000 == rows[-1][0]
    assert snapshot.provenance["requested_bars"] == 8
    assert snapshot.provenance["bars"] == 8
    assert len(exchange.calls) > 1
    assert all(value is not None for value in exchange.calls)
    assert exchange.calls == sorted(exchange.calls)


def test_live_ohlcv_refetches_incomplete_unbounded_cache(tmp_path, monkeypatch) -> None:
    rows = _rows(20)
    exchange = FakeExchange(rows)
    monkeypatch.setattr(market_data, "MARKET_CACHE_DIR", tmp_path)
    monkeypatch.setattr(market_data, "_build_public_exchange", lambda: exchange)
    key = market_data._cache_key("BTC-USDT-SWAP", "1h", 8, None, None)
    path = market_data._cache_path("BTC-USDT-SWAP", "1h", key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rows": rows[-3:]}), encoding="utf-8")

    snapshot = market_data.fetch_live_ohlcv(
        "BTC-USDT-SWAP",
        "1h",
        n_bars=8,
        use_cache=True,
    )

    assert len(snapshot.df) == 8
    assert snapshot.provenance["cache_hit"] is False
    assert exchange.calls


def test_current_bar_boundary_floors_to_interval_in_utc() -> None:
    now = datetime(2026, 8, 11, 7, 59, 59, tzinfo=UTC)

    assert market_data.current_bar_boundary("1h", now=now) == datetime(
        2026, 8, 11, 7, 0, tzinfo=UTC
    )
    assert market_data.current_bar_boundary("4h", now=now) == datetime(
        2026, 8, 11, 4, 0, tzinfo=UTC
    )


def test_live_ohlcv_refetches_incomplete_bar_scoped_cache(tmp_path, monkeypatch) -> None:
    rows = _rows(20)
    exchange = FakeExchange(rows)
    end = market_data.current_bar_boundary("1h").isoformat()
    monkeypatch.setattr(market_data, "MARKET_CACHE_DIR", tmp_path)
    monkeypatch.setattr(market_data, "_build_public_exchange", lambda: exchange)
    key = market_data._cache_key("BTC-USDT-SWAP", "1h", 8, None, end)
    path = market_data._cache_path("BTC-USDT-SWAP", "1h", key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rows": rows[-3:]}), encoding="utf-8")

    snapshot = market_data.fetch_live_ohlcv(
        "BTC-USDT-SWAP",
        "1h",
        n_bars=8,
        end=end,
        use_cache=True,
    )

    assert len(snapshot.df) == 8
    assert snapshot.provenance["cache_hit"] is False
    assert snapshot.provenance["requested_end"] == end
    assert exchange.calls


def test_factor_factory_live_snapshot_cache_key_tracks_current_bar(monkeypatch) -> None:
    rows = _rows(240)
    frame = market_data._frame_from_rows(rows)
    boundary = datetime(2026, 8, 11, 4, 0, tzinfo=UTC)
    captured: dict[str, object] = {}

    def fake_load_market_data(source: str, **kwargs):
        captured.update({"source": source, **kwargs})
        return market_data.MarketSnapshot(
            df=frame,
            source="okx_live",
            symbol="BTC-USDT-SWAP",
            interval="4h",
            fingerprint=market_data.fingerprint_frame(frame),
            provenance={"requested_end": kwargs["end"]},
        )

    monkeypatch.setattr(
        factor_factory_service.market_data_module,
        "current_bar_boundary",
        lambda _interval: boundary,
    )
    monkeypatch.setattr(
        factor_factory_service.market_data_module,
        "load_market_data",
        fake_load_market_data,
    )

    _frame, provenance = factor_factory_service._load_frame(
        FactorFactoryStartRequest(
            candidate_mode="library",
            use_ai=False,
            source="okx_live",
            symbol="BTC-USDT-SWAP",
            interval="4h",
            n_bars=240,
        )
    )

    assert captured["end"] == boundary.isoformat()
    assert captured["use_cache"] is True
    assert provenance["requested_end"] == boundary.isoformat()
