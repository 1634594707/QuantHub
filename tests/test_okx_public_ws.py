from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from packages.market_data.contracts import MarketEventKind, MarketEventQuality
from packages.market_data.okx_public_ws import (
    OkxPublicMarketStream,
    fetch_okx_public_rest_events,
    parse_okx_public_message,
)


def test_parser_distinguishes_ticker_bbo_forming_and_closed_bars() -> None:
    received = datetime(2026, 8, 12, 8, 0, 2, tzinfo=UTC)
    ticker = parse_okx_public_message(
        {
            "arg": {"channel": "tickers", "instId": "BTC-USDT-SWAP"},
            "data": [
                {
                    "ts": "1786521600000",
                    "last": "120000",
                    "bidPx": "119999",
                    "askPx": "120001",
                    "vol24h": "10",
                }
            ],
        },
        received_at=received,
    )[0]
    bbo = parse_okx_public_message(
        {
            "arg": {"channel": "books5", "instId": "BTC-USDT-SWAP"},
            "data": [
                {
                    "ts": "1786521600000",
                    "bids": [["119999", "1", "0", "1"]],
                    "asks": [["120001", "1", "0", "1"]],
                }
            ],
        },
        received_at=received,
    )[0]
    forming = parse_okx_public_message(
        {
            "arg": {"channel": "candle1H", "instId": "BTC-USDT-SWAP"},
            "data": [["1786521600000", "100", "102", "99", "101", "10", "0", "0", "0"]],
        },
        received_at=received,
    )[0]
    closed = parse_okx_public_message(
        {
            "arg": {"channel": "candle1H", "instId": "BTC-USDT-SWAP"},
            "data": [["1786518000000", "99", "101", "98", "100", "9", "0", "0", "1"]],
        },
        received_at=received,
    )[0]

    assert ticker.kind == MarketEventKind.TICKER
    assert bbo.kind == MarketEventKind.BEST_BID_ASK
    assert forming.kind == MarketEventKind.FORMING_BAR
    assert not forming.usable_for_research_signal()
    assert closed.kind == MarketEventKind.CLOSED_BAR_LIVE
    assert closed.usable_for_research_signal()


def test_parser_clamps_small_exchange_clock_skew_without_inverting_receipt_time() -> None:
    local_receipt = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    exchange_time = local_receipt + timedelta(milliseconds=750)
    event = parse_okx_public_message(
        {
            "arg": {"channel": "tickers", "instId": "BTC-USDT-SWAP"},
            "data": [
                {
                    "ts": str(int(exchange_time.timestamp() * 1000)),
                    "last": "100",
                    "bidPx": "99",
                    "askPx": "101",
                    "vol24h": "10",
                }
            ],
        },
        received_at=local_receipt,
    )[0]

    assert event.received_at == exchange_time
    assert event.recovery == {"clock_skew_ms": 750, "receipt_time_clamped": True}


def test_rest_compensation_deduplicates_and_records_gap_evidence() -> None:
    received = datetime.now(UTC)
    event = parse_okx_public_message(
        {
            "arg": {"channel": "tickers", "instId": "BTC-USDT-SWAP"},
            "data": [
                {
                    "ts": str(int((received - timedelta(seconds=1)).timestamp() * 1000)),
                    "last": "100",
                    "bidPx": "99",
                    "askPx": "101",
                    "vol24h": "10",
                }
            ],
        },
        received_at=received,
    )[0]
    emitted = []
    stream = OkxPublicMarketStream(
        inst_id="BTC-USDT-SWAP",
        on_event=emitted.append,
        rest_compensator=lambda: [event, event],
    )
    stream.evidence["gaps"].append({"detected_at": received.isoformat(), "cause": "test"})

    asyncio.run(stream._compensate())

    assert len(emitted) == 1
    assert emitted[0].quality_status == MarketEventQuality.GAP_RECOVERED
    assert stream.evidence["duplicates_suppressed"] == 1
    assert stream.evidence["rest_compensations"] == 1
    assert stream.evidence["gaps"][-1]["recovered"] is True


def test_default_rest_compensation_normalizes_all_public_event_kinds(monkeypatch) -> None:
    received = datetime(2026, 8, 12, 8, 0, 2, tzinfo=UTC)

    class _Response:
        def __init__(self, payload):
            self.payload = payload

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def raise_for_status(self):
            return None

        async def json(self):
            return self.payload

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def get(self, url, **_kwargs):
            if url.endswith("/ticker"):
                data = [{"ts": "1786521600000", "last": "100", "bidPx": "99", "askPx": "101"}]
            elif url.endswith("/books"):
                data = [{"ts": "1786521600000", "bids": [["99", "1"]], "asks": [["101", "1"]]}]
            else:
                data = [["1786518000000", "99", "101", "98", "100", "9", "0", "0", "1"]]
            return _Response({"code": "0", "data": data})

    monkeypatch.setattr(
        "packages.market_data.okx_public_ws.aiohttp.ClientSession",
        lambda **_kwargs: _Session(),
    )
    events = asyncio.run(
        fetch_okx_public_rest_events(
            inst_id="BTC-USDT-SWAP",
            received_at=received,
        )
    )

    assert {event.kind for event in events} == {
        MarketEventKind.TICKER,
        MarketEventKind.BEST_BID_ASK,
        MarketEventKind.CLOSED_BAR_LIVE,
    }
