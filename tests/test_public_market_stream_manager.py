from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from apps.api.domains.market_data.public_stream import PublicMarketStreamManager
from packages.market_data.contracts import MarketEvent, MarketEventKind, MarketEventQuality


class _FakeStream:
    def __init__(self, *, inst_id, candle_channel, on_event):
        self.inst_id = inst_id
        self.candle_channel = candle_channel
        self.on_event = on_event
        self.stop_event = asyncio.Event()
        self.evidence = {
            "status": "idle",
            "inst_id": inst_id,
            "channels": ["tickers", "books5", candle_channel],
            "rest_compensations": 0,
            "gaps": [],
        }

    async def arun(self):
        self.evidence["status"] = "running"
        now = datetime.now(UTC)
        self.on_event(
            MarketEvent(
                event_id="ticker:test",
                instrument_id="okx:BTC-USDT-SWAP",
                kind=MarketEventKind.TICKER,
                event_time=now,
                fetched_at=now,
                received_at=now,
                source="test",
                quality_status=MarketEventQuality.FRESH,
                price=100.0,
            )
        )
        self.on_event(
            MarketEvent(
                event_id="bbo:test",
                instrument_id="okx:BTC-USDT-SWAP",
                kind=MarketEventKind.BEST_BID_ASK,
                event_time=now,
                fetched_at=now,
                received_at=now,
                source="test",
                quality_status=MarketEventQuality.FRESH,
                bid=99.0,
                ask=101.0,
            )
        )
        await self.stop_event.wait()
        self.evidence["status"] = "stopped"


def test_manager_owns_explicit_stream_lifecycle_and_evidence(tmp_path) -> None:
    manager = PublicMarketStreamManager(
        evidence_dir=tmp_path,
        stream_factory=_FakeStream,
    )
    started = manager.start(inst_id="BTC-USDT-SWAP", candle_channel="candle1H")
    stream_id = started["stream_id"]

    for _ in range(100):
        status = manager.status(stream_id)
        if status["latest_events"]:
            break
        __import__("time").sleep(0.01)

    assert status["running"] is True
    assert status["latest_events"]["ticker"]["price"] == 100.0
    valuation_event, freshness = manager.latest_valuation_event(stream_id)
    assert valuation_event.kind == MarketEventKind.BEST_BID_ASK
    assert freshness["usable_for_valuation"] is True
    assert (tmp_path / "BTC-USDT-SWAP_candle1H.json").exists()

    stopped = manager.stop(stream_id)

    assert stopped["running"] is False
    assert stopped["evidence"]["status"] == "stopped"


class _OldEventStream(_FakeStream):
    async def arun(self):
        self.evidence["status"] = "running"
        now = datetime.now(UTC)
        self.on_event(
            MarketEvent(
                event_id="ticker:old",
                instrument_id="okx:BTC-USDT-SWAP",
                kind=MarketEventKind.TICKER,
                event_time=now - timedelta(minutes=5),
                fetched_at=now,
                received_at=now,
                source="test",
                quality_status=MarketEventQuality.FRESH,
                price=100.0,
            )
        )
        await self.stop_event.wait()


def test_manager_reclassifies_old_events_and_blocks_new_risk(tmp_path) -> None:
    manager = PublicMarketStreamManager(
        evidence_dir=tmp_path,
        stream_factory=_OldEventStream,
        delayed_after=timedelta(seconds=1),
        stale_after=timedelta(seconds=2),
    )
    stream_id = manager.start(inst_id="BTC-USDT-SWAP")["stream_id"]
    for _ in range(100):
        status = manager.status(stream_id)
        if status["latest_events"]:
            break
        __import__("time").sleep(0.01)

    ticker = status["latest_events"]["ticker"]
    assert ticker["freshness"]["quality_status"] == "stale"
    assert ticker["freshness"]["action"] == "block_new_risk"
    assert status["freshness_gate"]["valuation_ready"] is False
    assert status["freshness_gate"]["action"] == "block_new_risk"
    try:
        manager.latest_valuation_event(stream_id)
    except ValueError as exc:
        assert "没有新鲜" in str(exc)
    else:
        raise AssertionError("stale ticker must not be returned for valuation")
    manager.stop(stream_id)
