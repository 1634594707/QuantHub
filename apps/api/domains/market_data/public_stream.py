"""Lifecycle owner for explicitly started OKX public market streams."""

from __future__ import annotations

import asyncio
import json
import threading
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from packages.market_data.contracts import MarketEvent
from packages.market_data.okx_public_ws import OkxPublicMarketStream

StreamFactory = Callable[..., OkxPublicMarketStream]


class PublicMarketStreamManager:
    """Run public streams in daemon threads and expose redacted freshness evidence."""

    def __init__(
        self,
        *,
        evidence_dir: str | Path = "data/public_market_evidence",
        stream_factory: StreamFactory = OkxPublicMarketStream,
        delayed_after: timedelta = timedelta(seconds=5),
        stale_after: timedelta = timedelta(seconds=30),
    ) -> None:
        self._evidence_dir = Path(evidence_dir)
        self._stream_factory = stream_factory
        self._delayed_after = delayed_after
        self._stale_after = stale_after
        self._lock = threading.RLock()
        self._entries: dict[str, dict[str, Any]] = {}

    @staticmethod
    def stream_id(inst_id: str, candle_channel: str) -> str:
        return f"{inst_id.strip().upper()}:{candle_channel}"

    def start(self, *, inst_id: str, candle_channel: str = "candle1H") -> dict[str, Any]:
        key = self.stream_id(inst_id, candle_channel)
        with self._lock:
            existing = self._entries.get(key)
            if existing and existing["thread"].is_alive():
                return self._entry_status(key, existing)

            latest: dict[str, dict[str, Any]] = {}
            recent: deque[dict[str, Any]] = deque(maxlen=100)

            def on_event(event: MarketEvent) -> None:
                payload = event.model_dump(mode="json")
                with self._lock:
                    latest[event.kind.value] = payload
                    recent.append(payload)
                    entry = self._entries.get(key)
                    if entry:
                        entry["last_event_at"] = datetime.now(UTC).isoformat()
                        self._write_evidence(key, entry)

            stream = self._stream_factory(
                inst_id=inst_id,
                candle_channel=candle_channel,
                on_event=on_event,
            )
            entry: dict[str, Any] = {
                "stream": stream,
                "thread": None,
                "loop": None,
                "task": None,
                "latest": latest,
                "recent": recent,
                "started_at": datetime.now(UTC).isoformat(),
                "last_event_at": None,
            }

            def run() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                task = loop.create_task(stream.arun())
                with self._lock:
                    entry["loop"] = loop
                    entry["task"] = task
                try:
                    loop.run_until_complete(task)
                except asyncio.CancelledError:
                    pass
                finally:
                    with self._lock:
                        stream.evidence["status"] = "stopped"
                        self._write_evidence(key, entry)
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    loop.close()

            thread = threading.Thread(
                target=run,
                name=f"okx-public-{key}",
                daemon=True,
            )
            entry["thread"] = thread
            self._entries[key] = entry
            thread.start()
            self._write_evidence(key, entry)
            return self._entry_status(key, entry)

    def stop(self, stream_id: str) -> dict[str, Any]:
        with self._lock:
            entry = self._entries.get(stream_id)
            if entry is None:
                raise KeyError(stream_id)
            loop = entry.get("loop")
            task = entry.get("task")
            if loop and loop.is_running():
                loop.call_soon_threadsafe(entry["stream"].stop_event.set)
                if task and not task.done():
                    loop.call_soon_threadsafe(task.cancel)
            thread = entry["thread"]
        if thread is not threading.current_thread():
            thread.join(timeout=5)
        with self._lock:
            self._write_evidence(stream_id, entry)
            return self._entry_status(stream_id, entry)

    def stop_all(self) -> None:
        with self._lock:
            keys = list(self._entries)
        for key in keys:
            try:
                self.stop(key)
            except KeyError:
                continue

    def status(self, stream_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if stream_id is not None:
                entry = self._entries.get(stream_id)
                if entry is None:
                    raise KeyError(stream_id)
                return self._entry_status(stream_id, entry)
            return {
                "ok": True,
                "generated_at": datetime.now(UTC).isoformat(),
                "streams": [
                    self._entry_status(key, entry) for key, entry in sorted(self._entries.items())
                ],
            }

    def latest_valuation_event(self, stream_id: str) -> tuple[MarketEvent, dict[str, Any]]:
        """Return the freshest executable valuation event, preferring top-of-book."""
        with self._lock:
            entry = self._entries.get(stream_id)
            if entry is None:
                raise KeyError(stream_id)
            now = datetime.now(UTC)
            for kind in ("best_bid_ask", "ticker", "trade"):
                payload = entry["latest"].get(kind)
                if payload is None:
                    continue
                status = self._event_status(payload, now)
                if status["freshness"]["usable_for_valuation"] is True:
                    return MarketEvent.model_validate(payload), status["freshness"]
        raise ValueError("公共行情流没有新鲜的 ticker/BBO/trade 估值事件")

    def _entry_status(self, key: str, entry: dict[str, Any]) -> dict[str, Any]:
        stream = entry["stream"]
        thread = entry["thread"]
        now = datetime.now(UTC)
        latest_events = {
            kind: self._event_status(payload, now) for kind, payload in entry["latest"].items()
        }
        valuation = latest_events.get("best_bid_ask") or latest_events.get("ticker")
        research = latest_events.get("closed_bar_live")
        stale_kinds = [
            kind
            for kind, payload in latest_events.items()
            if payload.get("freshness", {}).get("action") == "block_new_risk"
        ]
        return {
            "stream_id": key,
            "running": bool(thread and thread.is_alive()),
            "started_at": entry["started_at"],
            "last_event_at": entry["last_event_at"],
            "evidence_path": str(self._evidence_path(key)).replace("\\", "/"),
            "evidence": dict(stream.evidence),
            "latest_events": latest_events,
            "recent_event_count": len(entry["recent"]),
            "freshness_gate": {
                "valuation_ready": bool(
                    valuation and valuation.get("freshness", {}).get("usable_for_valuation") is True
                ),
                "research_ready": bool(
                    research
                    and research.get("freshness", {}).get("usable_for_research_signal") is True
                ),
                "stale_event_kinds": stale_kinds,
                "action": "block_new_risk" if stale_kinds else "allow",
                "evaluated_at": now.isoformat(),
            },
        }

    def _event_status(self, payload: dict[str, Any], now: datetime) -> dict[str, Any]:
        event = MarketEvent.model_validate(payload)
        return {
            **payload,
            "freshness": event.freshness_at(
                now,
                delayed_after=self._delayed_after,
                stale_after=self._stale_after,
            ),
        }

    def _evidence_path(self, key: str) -> Path:
        safe = key.replace(":", "_").replace("/", "_")
        return self._evidence_dir / f"{safe}.json"

    def _write_evidence(self, key: str, entry: dict[str, Any]) -> None:
        path = self._evidence_path(key)
        payload = self._entry_status(key, entry)
        payload["recent_events"] = list(entry["recent"])
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(path)
        except OSError:
            return


_MANAGER = PublicMarketStreamManager()


def get_public_stream_manager() -> PublicMarketStreamManager:
    return _MANAGER
