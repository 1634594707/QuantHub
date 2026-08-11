from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .runner_errors import RunnerError, _scrub

logger = logging.getLogger(__name__)

try:
    import aiohttp
except ImportError:  # pragma: no cover - aiohttp is a runner dependency
    aiohttp = None  # type: ignore[assignment]


# OKX private WebSocket endpoints. The demo/sandbox cluster requires the
# brokerId=9999 query parameter, otherwise subscriptions are silently rejected.
DEMO_PRIVATE_WS = "wss://wspap.okx.com:8443/ws/v5/private?brokerId=9999"
LIVE_PRIVATE_WS = "wss://ws.okx.com:8443/ws/v5/private"
DEMO_PUBLIC_WS = "wss://wspap.okx.com:8443/ws/v5/public?brokerId=9999"

# Channel subscriptions that constitute the "private push" surface. Each maps to
# one of the four reconciliation categories (orders / fills / positions / balance).
PRIVATE_CHANNELS = ("account", "orders", "fills", "positions", "balance_and_position")

RestCompensator = Callable[[], Any] | Callable[[], Awaitable[Any]]


def make_login_args(api_key: str, secret: str, passphrase: str) -> dict[str, str]:
    """Build the OKX private-login args (signature over `/users/self/verify`).

    The passphrase is the *plain* passphrase set on the API key, not the
    base64 form used by REST headers. The timestamp is **epoch seconds** as a
    string — OKX's private WS login rejects ISO-8601 here (returns
    ``60011 Please log in``), unlike the REST header which uses ISO-8601.
    """
    timestamp = str(int(time.time()))
    prehash = timestamp + "GET" + "/users/self/verify"
    signature = base64.b64encode(
        hmac.new(secret.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")
    return {
        "apiKey": api_key,
        "passphrase": passphrase,
        "timestamp": timestamp,
        "sign": signature,
    }


class OkxPrivateWs:
    """Private WebSocket push client with login, heartbeat, reconnect, and a
    REST compensation fallback when the stream drops.

    The client is transport-agnostic about the rest of the runner: it only needs
    a ``rest_compensator`` callable that returns the latest account/order view
    (typically ``engine.adapter.account_snapshot`` wrapped to refresh state). It
    writes a structured evidence file so M4-08 can attest the stream actually
    connected, authenticated, and recovered.
    """

    def __init__(
        self,
        *,
        api_key: str,
        secret: str,
        passphrase: str,
        environment: str = "demo",
        ws_url: str | None = None,
        proxy: str | None = None,
        evidence_dir: str | Path | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        channels: tuple[str, ...] = PRIVATE_CHANNELS,
        subscribe_args: dict[str, Any] | None = None,
        rest_compensator: RestCompensator | None = None,
        heartbeat_interval: float = 15.0,
        reconnect_base: float = 1.0,
        reconnect_max: float = 30.0,
        max_reconnect: int = 20,
        run_id: str | None = None,
    ) -> None:
        if aiohttp is None:
            raise RuntimeError("M4-04 requires the aiohttp dependency for private WebSocket")
        if environment not in {"demo", "live"}:
            raise ValueError("environment must be demo or live")
        if heartbeat_interval <= 0:
            raise ValueError("heartbeat_interval must be positive")
        self._api_key = api_key
        self._secret = secret
        self._passphrase = passphrase
        self._environment = environment
        self._ws_url = ws_url or (DEMO_PRIVATE_WS if environment == "demo" else LIVE_PRIVATE_WS)
        self._proxy = proxy or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        self._evidence_dir = Path(evidence_dir or "data/okx_ws_evidence")
        self._on_event = on_event
        self._channels = tuple(channels)
        self._subscribe_args = subscribe_args or {}
        self._rest_compensator = rest_compensator
        self._heartbeat_interval = heartbeat_interval
        self._reconnect_base = reconnect_base
        self._reconnect_max = reconnect_max
        self._max_reconnect = max_reconnect
        self._run_id = run_id or f"ws-{uuid.uuid4().hex[:12]}"

        self._stop = asyncio.Event()
        self._evidence: dict[str, Any] = {
            "run_id": self._run_id,
            "environment": environment,
            "ws_url": self._ws_url,
            "channels": list(self._channels),
            "proxy": self._proxy,
            "started_at": _now_iso(),
            "login_response": None,
            "subscribed": [],
            "messages_received": 0,
            "private_messages": 0,
            "reconnects": 0,
            "rest_compensations": 0,
            "last_error": None,
            "events": [],
            "finished_at": None,
            "status": "running",
        }

    # -- public control ----------------------------------------------------
    def run(self) -> None:
        """Blocking entry used by CLI/tools; spawns the asyncio loop."""
        asyncio.run(self.arun())

    async def arun(self) -> None:
        self._stop.clear()
        self._evidence_dir.mkdir(parents=True, exist_ok=True)
        attempt = 0
        while not self._stop.is_set() and attempt <= self._max_reconnect:
            attempt += 1
            self._evidence["attempt"] = attempt
            disconnected = False
            try:
                await self._session()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - top-level guard, record + retry
                disconnected = True
                err = RunnerError("WS_DISCONNECTED", str(exc), {"cause": type(exc).__name__})
                self._log("error", {"message": _scrub(err.to_dict())})
                self._evidence["last_error"] = _scrub(err.to_dict())
            else:
                # Session ended without exception: a clean stream close or an
                # in-loop stop. Only treat it as a disconnect if we were not asked
                # to stop.
                disconnected = not self._stop.is_set()
            if disconnected and not self._stop.is_set():
                await self._compensate()
            if self._stop.is_set():
                break
            backoff = min(self._reconnect_base * (2 ** (attempt - 1)), self._reconnect_max)
            self._evidence["reconnects"] += 1
            self._log("reconnect", {"after_seconds": backoff, "attempt": attempt})
            await asyncio.sleep(backoff)
        self._evidence["status"] = "stopped"
        self._evidence["finished_at"] = _now_iso()
        self._flush_evidence()

    async def stop(self) -> None:
        self._stop.set()

    def request_stop(self) -> None:
        """Request shutdown from a manager thread."""
        self._stop.set()

    # -- session -----------------------------------------------------------
    async def _session(self) -> None:
        url = self._evidence["ws_url"]
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.ws_connect(url, proxy=self._proxy, heartbeat=20, ssl=True) as ws:
                self._log("connect", {"url": url})
                await ws.send_json(
                    {
                        "op": "login",
                        "args": [make_login_args(self._api_key, self._secret, self._passphrase)],
                    }
                )
                hb = asyncio.create_task(self._heartbeat(ws))

                async def _watch_stop() -> None:
                    # `async for msg in ws` only wakes on a new frame, so a quiet
                    # stream would never observe the stop flag. Close the socket
                    # from this watcher to unblock the listen loop promptly.
                    while not self._stop.is_set():
                        await asyncio.sleep(0.2)
                    try:
                        await ws.close()
                    except Exception as exc:  # noqa: BLE001 - best effort
                        logger.debug("private websocket close failed: %s", type(exc).__name__)

                stop_watch = asyncio.create_task(_watch_stop())
                login_ok = False
                subscribed_sent = False
                try:
                    async for msg in ws:
                        if self._stop.is_set():
                            break
                        if msg.type in (
                            aiohttp.WSMsgType.CLOSE,
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            self._log("stream_closed", {"type": str(msg.type)})
                            break
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                        payload = _safe_json(msg.data)
                        if payload is None:
                            continue
                        self._evidence["messages_received"] += 1
                        event = payload.get("event")
                        if event == "login":
                            self._evidence["login_response"] = _scrub(payload)
                            ok = payload.get("code") in (0, "0")
                            login_ok = ok
                            self._log("login", {"code": payload.get("code"), "ok": ok})
                            if not ok:
                                raise RuntimeError(
                                    f"OKX login rejected (code={payload.get('code')})"
                                )
                            if self._channels and not subscribed_sent:
                                await ws.send_json(
                                    {
                                        "op": "subscribe",
                                        "args": [
                                            {"channel": ch, **self._subscribe_args}
                                            for ch in self._channels
                                        ],
                                    }
                                )
                                subscribed_sent = True
                        elif event == "subscribe":
                            self._evidence["subscribed"] = _scrub(payload.get("arg", payload))
                            self._log("subscribe", {"arg": payload.get("arg")})
                        elif event == "error":
                            self._log(
                                "error_event",
                                {
                                    "code": payload.get("code"),
                                    "connId": payload.get("connId"),
                                },
                            )
                        elif event == "pong":
                            pass
                        elif "data" in payload or "arg" in payload:
                            self._evidence["private_messages"] += 1
                            self._log(
                                "push",
                                _scrub({"channel": (payload.get("arg") or {}).get("channel")}),
                            )
                            if self._on_event is not None:
                                self._on_event(payload)
                        else:
                            self._log("event", _scrub(payload))
                            if self._on_event is not None:
                                self._on_event(payload)
                    if not login_ok:
                        raise RuntimeError("login acknowledgement never received")
                finally:
                    hb.cancel()
                    stop_watch.cancel()

    async def _heartbeat(self, ws: Any) -> None:
        while not self._stop.is_set():
            try:
                await ws.send_str("ping")
            except Exception:  # noqa: BLE001 - heartbeat failure => caller reconnects
                return
            await asyncio.sleep(self._heartbeat_interval)

    async def _compensate(self) -> None:
        """Run the REST compensation fallback after a disconnect.

        Falls back to the latest REST snapshot to re-anchor local order/fill
        state, then records the compensation in the evidence file.
        """
        if self._rest_compensator is None:
            return
        try:
            result = self._rest_compensator()
            if asyncio.iscoroutine(result):
                result = await result
            self._evidence["rest_compensations"] += 1
            summary = _scrub(_summarize_snapshot(result))
            self._log("rest_compensation", {"snapshot": summary})
        except Exception as exc:  # noqa: BLE001 - compensation failure is logged, not fatal
            err = RunnerError("WS_DISCONNECTED", str(exc), {"cause": type(exc).__name__})
            self._log("rest_compensation_failed", _scrub(err.to_dict()))

    # -- helpers -----------------------------------------------------------
    def _log(self, kind: str, payload: Any) -> None:
        self._evidence.setdefault("events", []).append(
            {"at": _now_iso(), "kind": kind, "payload": payload}
        )
        # Keep evidence file fresh for in-flight inspection / M4-08 collection.
        self._flush_evidence()

    def _flush_evidence(self) -> None:
        self._evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self._evidence_dir / f"{self._run_id}.json"
        with path.open("w", encoding="utf-8") as handle:
            json.dump(self._evidence, handle, ensure_ascii=False, indent=2)

    def evidence_path(self) -> Path:
        return self._evidence_dir / f"{self._run_id}.json"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_json(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _summarize_snapshot(snapshot: Any) -> dict[str, Any]:
    """Reduce an AccountSnapshot to a desensitized summary for evidence."""
    if snapshot is None:
        return {"available": False}
    try:
        return {
            "orders": len(getattr(snapshot, "orders", []) or []),
            "fills": len(getattr(snapshot, "fills", []) or []),
            "balances": list((getattr(snapshot, "balances", {}) or {}).keys()),
            "positions": list((getattr(snapshot, "positions", {}) or {}).keys()),
            "observed_at": str(getattr(snapshot, "observed_at", "")),
        }
    except Exception:  # noqa: BLE001 - never let summarizer break the loop
        return {"available": True}
