from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .okx_adapter import OkxCcxtAdapter
from .private_ws import OkxPrivateWs

try:
    import ccxt
except ImportError:  # pragma: no cover - crypto dependency group
    ccxt = None  # type: ignore[assignment]

from packages.credential_vault import load_okx_demo_credentials  # noqa: E402

DEFAULT_CHANNELS = ("orders", "account", "positions", "balance_and_position")


class WsManager:
    """Owns a long-running private WebSocket client in a background thread.

    Exposes start/stop/status so the runner API can drive M4-04 without blocking
    the request handler. The client writes a structured evidence file on every
    event; ``status()`` surfaces a redacted summary of the latest evidence.
    """

    def __init__(self, evidence_dir: str | Path | None = None) -> None:
        self._thread: threading.Thread | None = None
        self._client: OkxPrivateWs | None = None
        self._lock = threading.Lock()
        self._evidence_dir = Path(evidence_dir or "data/okx_ws_evidence")
        self._status: dict[str, Any] = {
            "running": False,
            "environment": None,
            "run_id": None,
            "evidence_path": None,
            "summary": None,
        }

    def start(
        self,
        *,
        environment: str = "demo",
        channels: tuple[str, ...] = DEFAULT_CHANNELS,
        heartbeat_interval: float = 15.0,
    ) -> dict[str, Any]:
        if ccxt is None:
            raise RuntimeError("WsManager requires the crypto dependency group (ccxt)")
        if environment != "demo":
            raise ValueError("the configured credential vault only supports the demo environment")
        if heartbeat_interval <= 0:
            raise ValueError("heartbeat_interval must be positive")
        if self._thread is not None and self._thread.is_alive():
            return self.status()
        creds = load_okx_demo_credentials()
        exchange = ccxt.okx(
            {
                "apiKey": creds.api_key,
                "secret": creds.secret_key,
                "password": creds.passphrase,
                "enableRateLimit": True,
            }
        )
        if environment == "demo":
            exchange.set_sandbox_mode(True)
        exchange.session.trust_env = True
        adapter = OkxCcxtAdapter(exchange)

        def compensator() -> Any:
            return adapter.account_snapshot("demo")

        client = OkxPrivateWs(
            api_key=creds.api_key,
            secret=creds.secret_key,
            passphrase=creds.passphrase,
            environment=environment,
            evidence_dir=self._evidence_dir,
            rest_compensator=compensator,
            channels=channels,
            heartbeat_interval=heartbeat_interval,
        )
        self._client = client

        def run_client() -> None:
            try:
                client.run()
            finally:
                with self._lock:
                    self._status["running"] = False

        self._thread = threading.Thread(target=run_client, name="okx-private-ws", daemon=True)
        with self._lock:
            self._status.update(
                {
                    "running": True,
                    "environment": environment,
                    "run_id": client._run_id,
                    "evidence_path": str(client.evidence_path()),
                    "summary": None,
                }
            )
            thread = self._thread
        thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        if self._client is not None:
            # The client's stop-watcher task (running in its own loop) observes
            # this flag and closes the socket, ending the run cleanly.
            self._client.request_stop()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=10.0)
        with self._lock:
            self._status["running"] = self.is_running()
        return self.status()

    def is_running(self) -> bool:
        return bool(
            self._thread
            and self._thread.is_alive()
            and self._client
            and not self._client._stop.is_set()
        )

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._status["running"] = self.is_running()
            summary = None
            if self._client is not None:
                path = self._client.evidence_path()
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    summary = {
                        "messages_received": data.get("messages_received"),
                        "private_messages": data.get("private_messages"),
                        "reconnects": data.get("reconnects"),
                        "rest_compensations": data.get("rest_compensations"),
                        "login_response": data.get("login_response"),
                        "subscribed": data.get("subscribed"),
                        "status": data.get("status"),
                        "last_error": data.get("last_error"),
                    }
                except (ValueError, OSError):
                    summary = None
            self._status["summary"] = summary
            return dict(self._status)


_MANAGER = WsManager()


def get_ws_manager() -> WsManager:
    return _MANAGER
