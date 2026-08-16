"""OKX public market stream with reconnect, REST compensation, and deduplication."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from .contracts import (
    MarketEvent,
    MarketEventKind,
    MarketEventQuality,
    canonical_instrument_id,
    classify_market_event_quality,
)

logger = logging.getLogger(__name__)

try:
    import aiohttp
except ImportError:  # pragma: no cover - crypto dependency group
    aiohttp = None  # type: ignore[assignment]

OKX_PUBLIC_WS = "wss://ws.okx.com:8443/ws/v5/public"
OKX_BUSINESS_WS = "wss://ws.okx.com:8443/ws/v5/business"
OKX_REST_BASE = "https://www.okx.com"

RestCompensator = Callable[[], Any] | Callable[[], Awaitable[Any]]


async def fetch_okx_public_rest_events(
    *,
    inst_id: str,
    candle_channel: str = "candle1H",
    proxy: str | None = None,
    received_at: datetime | None = None,
) -> list[MarketEvent]:
    """Fetch ticker, top-of-book, and recent candles for reconnect compensation."""
    if aiohttp is None:
        raise RuntimeError("OKX public REST compensation requires aiohttp")
    normalized_inst_id = inst_id.strip().upper()
    bar = candle_channel.removeprefix("candle")
    requests = (
        ("tickers", "/api/v5/market/ticker", {"instId": normalized_inst_id}),
        ("books5", "/api/v5/market/books", {"instId": normalized_inst_id, "sz": "5"}),
        (
            candle_channel,
            "/api/v5/market/candles",
            {"instId": normalized_inst_id, "bar": bar, "limit": "3"},
        ),
    )
    fetched = received_at or datetime.now(UTC)
    events: list[MarketEvent] = []
    async with aiohttp.ClientSession(trust_env=True) as session:
        for channel, path, params in requests:
            async with session.get(
                f"{OKX_REST_BASE}{path}",
                params=params,
                proxy=proxy,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                response.raise_for_status()
                payload = await response.json()
            if str(payload.get("code", "0")) != "0":
                raise RuntimeError(
                    f"OKX REST compensation failed for {channel}: {payload.get('msg') or payload}"
                )
            events.extend(
                parse_okx_public_message(
                    {
                        "arg": {"channel": channel, "instId": normalized_inst_id},
                        "data": payload.get("data") or [],
                    },
                    received_at=fetched,
                    source="okx_public_rest_compensation",
                )
            )
    return events


def _utc_from_ms(value: str | int) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, UTC)


def _receipt_time(received_at: datetime, event_time: datetime) -> tuple[datetime, dict[str, Any]]:
    """Tolerate small exchange/local clock skew without inverting event chronology."""
    if received_at >= event_time:
        return received_at, {}
    skew_ms = int((event_time - received_at).total_seconds() * 1000)
    return event_time, {"clock_skew_ms": skew_ms, "receipt_time_clamped": True}


def _interval_delta(channel: str) -> timedelta:
    suffix = channel.removeprefix("candle")
    if suffix.endswith("H"):
        return timedelta(hours=int(suffix[:-1] or "1"))
    if suffix.endswith("D"):
        return timedelta(days=int(suffix[:-1] or "1"))
    if suffix.endswith("m"):
        return timedelta(minutes=int(suffix[:-1] or "1"))
    raise ValueError(f"unsupported OKX candle channel: {channel}")


def parse_okx_public_message(
    payload: dict[str, Any],
    *,
    received_at: datetime | None = None,
    source: str = "okx_public_ws",
) -> list[MarketEvent]:
    """Normalize one OKX public push into immutable market events."""
    arg = payload.get("arg") or {}
    channel = str(arg.get("channel") or "")
    inst_id = str(arg.get("instId") or "")
    if not channel or not inst_id or not isinstance(payload.get("data"), list):
        return []
    received = received_at or datetime.now(UTC)
    instrument_id = canonical_instrument_id("okx", inst_id)
    events: list[MarketEvent] = []
    for row in payload["data"]:
        if channel == "tickers" and isinstance(row, dict):
            event_time = _utc_from_ms(row["ts"])
            event_received, recovery = _receipt_time(received, event_time)
            events.append(
                MarketEvent(
                    event_id=f"ticker:{inst_id}:{row['ts']}",
                    instrument_id=instrument_id,
                    kind=MarketEventKind.TICKER,
                    event_time=event_time,
                    fetched_at=event_received,
                    received_at=event_received,
                    source=source,
                    quality_status=classify_market_event_quality(
                        event_time=event_time,
                        received_at=event_received,
                        delayed_after=timedelta(seconds=3),
                        stale_after=timedelta(seconds=15),
                    ),
                    price=float(row["last"]),
                    bid=float(row["bidPx"]) if row.get("bidPx") else None,
                    ask=float(row["askPx"]) if row.get("askPx") else None,
                    volume=float(row["vol24h"]) if row.get("vol24h") else None,
                    recovery=recovery,
                )
            )
        elif channel in {"bbo-tbt", "books5"} and isinstance(row, dict):
            event_time = _utc_from_ms(row["ts"])
            event_received, recovery = _receipt_time(received, event_time)
            bids = row.get("bids") or []
            asks = row.get("asks") or []
            if not bids or not asks:
                continue
            events.append(
                MarketEvent(
                    event_id=f"bbo:{inst_id}:{row['ts']}:{bids[0][0]}:{asks[0][0]}",
                    instrument_id=instrument_id,
                    kind=MarketEventKind.BEST_BID_ASK,
                    event_time=event_time,
                    fetched_at=event_received,
                    received_at=event_received,
                    source=source,
                    quality_status=classify_market_event_quality(
                        event_time=event_time,
                        received_at=event_received,
                        delayed_after=timedelta(seconds=2),
                        stale_after=timedelta(seconds=10),
                    ),
                    bid=float(bids[0][0]),
                    ask=float(asks[0][0]),
                    recovery=recovery,
                )
            )
        elif channel.startswith("candle") and isinstance(row, list) and len(row) >= 9:
            bar_open = _utc_from_ms(row[0])
            bar_close = bar_open + _interval_delta(channel)
            is_closed = str(row[8]) == "1"
            kind = MarketEventKind.CLOSED_BAR_LIVE if is_closed else MarketEventKind.FORMING_BAR
            event_time = bar_close if is_closed else received
            events.append(
                MarketEvent(
                    event_id=f"{channel}:{inst_id}:{row[0]}:{row[8]}",
                    instrument_id=instrument_id,
                    kind=kind,
                    event_time=event_time,
                    bar_open_time=bar_open,
                    bar_close_time=bar_close,
                    fetched_at=received,
                    received_at=received,
                    is_closed=is_closed,
                    source=source,
                    quality_status=(
                        classify_market_event_quality(
                            event_time=bar_close,
                            received_at=received,
                            delayed_after=timedelta(seconds=5),
                            stale_after=_interval_delta(channel) * 2,
                        )
                        if is_closed
                        else MarketEventQuality.FRESH
                    ),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
            )
    return events


class OkxPublicMarketStream:
    """Long-running public stream; research consumers receive only closed bars."""

    def __init__(
        self,
        *,
        inst_id: str,
        candle_channel: str = "candle1H",
        on_event: Callable[[MarketEvent], None] | None = None,
        rest_compensator: RestCompensator | None = None,
        proxy: str | None = None,
        reconnect_base: float = 1.0,
        reconnect_max: float = 30.0,
        max_reconnect: int = 20,
        fault_disconnect_after_messages: int | None = None,
        public_ws_url: str = OKX_PUBLIC_WS,
        business_ws_url: str = OKX_BUSINESS_WS,
    ) -> None:
        if aiohttp is None:
            raise RuntimeError("OKX public WebSocket requires aiohttp")
        self.inst_id = inst_id.strip().upper()
        self.candle_channel = candle_channel
        self.on_event = on_event
        self.rest_compensator = rest_compensator or self._default_rest_compensation
        self.proxy = proxy or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        self.reconnect_base = reconnect_base
        self.reconnect_max = reconnect_max
        self.max_reconnect = max_reconnect
        self.fault_disconnect_after_messages = fault_disconnect_after_messages
        self.public_ws_url = public_ws_url
        self.business_ws_url = business_ws_url
        self._fault_disconnect_injected = False
        self.stop_event = asyncio.Event()
        self.seen_event_ids: set[str] = set()
        self.evidence: dict[str, Any] = {
            "status": "idle",
            "inst_id": self.inst_id,
            "channels": ["tickers", "books5", candle_channel],
            "messages_received": 0,
            "connections_opened": 0,
            "events_emitted": 0,
            "events_after_reconnect": 0,
            "duplicates_suppressed": 0,
            "reconnects": 0,
            "rest_compensations": 0,
            "gaps": [],
            "fault_injections": [],
            "last_error": None,
        }

    async def arun(self) -> None:
        self.stop_event.clear()
        self.evidence["status"] = "running"
        attempt = 0
        while not self.stop_event.is_set() and attempt <= self.max_reconnect:
            attempt += 1
            disconnected = False
            try:
                await self._session()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - top-level reconnect guard
                disconnected = True
                self.evidence["last_error"] = f"{type(exc).__name__}: {exc}"
                self.evidence["gaps"].append(
                    {"detected_at": datetime.now(UTC).isoformat(), "cause": type(exc).__name__}
                )
            if disconnected and not self.stop_event.is_set():
                await self._compensate()
            if self.stop_event.is_set():
                break
            self.evidence["reconnects"] += 1
            await asyncio.sleep(min(self.reconnect_base * 2 ** (attempt - 1), self.reconnect_max))
        self.evidence["status"] = "stopped"

    async def stop(self) -> None:
        self.stop_event.set()

    async def _default_rest_compensation(self) -> list[MarketEvent]:
        return await fetch_okx_public_rest_events(
            inst_id=self.inst_id,
            candle_channel=self.candle_channel,
            proxy=self.proxy,
        )

    async def _session(self) -> None:
        public_args = [
            {"channel": "tickers", "instId": self.inst_id},
            {"channel": "books5", "instId": self.inst_id},
        ]
        business_args = [{"channel": self.candle_channel, "instId": self.inst_id}]
        tasks = [
            asyncio.create_task(self._consume(self.public_ws_url, public_args)),
            asyncio.create_task(self._consume(self.business_ws_url, business_args)),
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _consume(self, url: str, args: list[dict[str, str]]) -> None:
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.ws_connect(url, proxy=self.proxy, heartbeat=20, ssl=True) as ws:
                self.evidence["connections_opened"] += 1
                await ws.send_json({"op": "subscribe", "args": args})
                async for message in ws:
                    if self.stop_event.is_set():
                        await ws.close()
                        break
                    if message.type in {
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    }:
                        raise RuntimeError(f"OKX public stream closed: {message.type}")
                    if message.type != aiohttp.WSMsgType.TEXT or message.data == "pong":
                        continue
                    try:
                        payload = json.loads(message.data)
                    except ValueError:
                        continue
                    self.evidence["messages_received"] += 1
                    if (
                        self.fault_disconnect_after_messages is not None
                        and not self._fault_disconnect_injected
                        and self.evidence["messages_received"]
                        >= self.fault_disconnect_after_messages
                    ):
                        self._fault_disconnect_injected = True
                        self.evidence["fault_injections"].append(
                            {
                                "at": datetime.now(UTC).isoformat(),
                                "kind": "forced_public_ws_disconnect",
                                "url": url,
                            }
                        )
                        await ws.close()
                        raise ConnectionError("forced public WebSocket disconnect drill")
                    for event in parse_okx_public_message(payload):
                        self._emit(event)

    def _emit(self, event: MarketEvent) -> bool:
        if event.event_id in self.seen_event_ids:
            self.evidence["duplicates_suppressed"] += 1
            return False
        self.seen_event_ids.add(event.event_id)
        self.evidence["events_emitted"] += 1
        if self.evidence["reconnects"] > 0 and event.recovery.get("method") != "rest_compensation":
            self.evidence["events_after_reconnect"] += 1
        if self.on_event is not None:
            self.on_event(event)
        return True

    async def _compensate(self) -> None:
        if self.rest_compensator is None:
            return
        try:
            result = self.rest_compensator()
            if asyncio.iscoroutine(result):
                result = await result
            events = result if isinstance(result, list) else []
            emitted = 0
            for event in events:
                if isinstance(event, MarketEvent):
                    recovered = event.model_copy(
                        update={
                            "quality_status": MarketEventQuality.GAP_RECOVERED,
                            "recovery": {"method": "rest_compensation"},
                        }
                    )
                    emitted += self._emit(recovered)
            self.evidence["rest_compensations"] += 1
            if self.evidence["gaps"]:
                self.evidence["gaps"][-1].update(
                    {"recovered": True, "recovered_events": emitted, "method": "rest_compensation"}
                )
        except Exception as exc:  # noqa: BLE001 - evidence records recovery failure
            if self.evidence["gaps"]:
                self.evidence["gaps"][-1].update(
                    {"recovered": False, "recovery_error": f"{type(exc).__name__}: {exc}"}
                )
