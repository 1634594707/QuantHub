"""M4-04 end-to-end verification against a protocol-accurate mock OKX server.

The mock validates the client's login HMAC with the exact OKX formula, so a
successful handshake proves the signature construction is correct. It also
simulates a mid-session disconnect to exercise reconnect + REST compensation.

Run:  .venv/Scripts/python.exe tests/test_private_ws_mock.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps.okx_runner.private_ws import OkxPrivateWs  # noqa: E402
from tools.okx_ws_mock_server import MockOkxWs  # noqa: E402


def start_mock(creds, port: int, drop_after: int) -> MockOkxWs:
    mock = MockOkxWs(creds.api_key, creds.secret_key, creds.passphrase, drop_after=drop_after)

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(mock.start("127.0.0.1", port))
        loop.run_forever()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    for _ in range(100):
        if mock.url:
            break
        time.sleep(0.05)
    return mock


compensations = []


def rest_compensator():
    compensations.append(time.time())


async def main() -> int:
    class Creds:
        api_key = "test-api-key"
        secret_key = "test-secret-key"
        passphrase = "test-passphrase"

    creds = Creds()
    mock = start_mock(creds, 0, drop_after=3)
    assert mock.url, "mock server failed to start"

    client = OkxPrivateWs(
        api_key=creds.api_key,
        secret=creds.secret_key,
        passphrase=creds.passphrase,
        ws_url=mock.url,
        evidence_dir=ROOT / "data" / "okx_ws_evidence",
        rest_compensator=rest_compensator,
        channels=("account", "orders"),
        heartbeat_interval=0.5,
        reconnect_base=0.3,
        reconnect_max=1.0,
        max_reconnect=5,
        run_id="test-mock",
    )

    async def _stopper() -> None:
        await asyncio.sleep(8)
        await client.stop()

    await asyncio.gather(client.arun(), _stopper())

    ev = json.loads(client.evidence_path().read_text(encoding="utf-8"))
    login_code = (ev.get("login_response") or {}).get("code")
    print("\n=== M4-04 Mock Evidence ===")
    print("login_response     :", ev.get("login_response"))
    print("subscribed         :", ev.get("subscribed"))
    print("messages_received  :", ev.get("messages_received"))
    print("private_messages   :", ev.get("private_messages"))
    print("reconnects         :", ev.get("reconnects"))
    print("rest_compensations :", ev.get("rest_compensations"))

    ok = (
        login_code in (0, "0")
        and bool(ev.get("subscribed"))
        and ev.get("private_messages", 0) > 0
        and ev.get("reconnects", 0) >= 1
        and ev.get("rest_compensations", 0) >= 1
    )
    print("\nRESULT:", "PASS" if ok else "FAIL")
    if not ok:
        print("events:", json.dumps(ev.get("events", []), ensure_ascii=False)[:800])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
