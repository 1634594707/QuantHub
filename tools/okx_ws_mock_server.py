"""Protocol-accurate mock of the OKX private WebSocket endpoint.

Used by the M4-04 test harness to validate the real ``OkxPrivateWs`` client
without depending on a live OKX private-login entitlement (demo API keys
commonly lack WS private-login permission, see M4-04 notes). The mock verifies
the client's login signature with the *same* HMAC-SHA256 formula OKX uses, so a
successful handshake proves the signature construction is correct.

Run as a server:
    .venv/Scripts/python.exe tools/okx_ws_mock_server.py
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import threading
from typing import Any

from aiohttp import web


def make_sign(secret: str, timestamp: str) -> str:
    prehash = timestamp + "GET" + "/users/self/verify"
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")


class MockOkxWs:
    def __init__(
        self,
        api_key: str,
        secret: str,
        passphrase: str,
        *,
        drop_after: int = 0,
        push_every: float = 0.4,
    ) -> None:
        self.api_key = api_key
        self.secret = secret
        self.passphrase = passphrase
        self.drop_after = drop_after
        self.push_every = push_every
        self._push_counts: list[int] = []
        self.app = web.Application()
        self.app.router.add_get("/ws/v5/private", self._handler)
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self.url = ""

    async def _handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        conn_id = id(ws)
        logged_in = False
        subscribed: list[dict[str, Any]] = []
        pushes = 0
        push_task: asyncio.Task[None] | None = None

        async def push_loop() -> None:
            nonlocal pushes
            while not ws.closed:
                await asyncio.sleep(self.push_every)
                pushes += 1
                for arg in subscribed:
                    await ws.send_json(
                        {
                            "arg": arg,
                            "data": [
                                {
                                    "channel": arg.get("channel"),
                                    "uTime": str(1_700_000_000_000 + pushes),
                                    "availBal": "1000.0",
                                    "sample": f"mock-push-{pushes}",
                                }
                            ],
                        }
                    )
                if self.drop_after and pushes >= self.drop_after:
                    await ws.close()
                    return

        try:
            async for msg in ws:
                if msg.type != web.WSMsgType.TEXT:
                    continue
                if msg.data == "ping":
                    await ws.send_str("pong")
                    continue
                data = json.loads(msg.data)
                op = data.get("op")
                if op == "login":
                    args = data.get("args", [])
                    login = args[0] if len(args) == 1 and isinstance(args[0], dict) else {}
                    expected = make_sign(self.secret, login.get("timestamp", ""))
                    ok = (
                        login.get("apiKey") == self.api_key
                        and login.get("passphrase") == self.passphrase
                        and login.get("sign") == expected
                    )
                    if ok:
                        logged_in = True
                        await ws.send_json({"event": "login", "code": 0, "connId": str(conn_id)})
                    else:
                        await ws.send_json({"event": "error", "code": 60013, "msg": "Invalid sign"})
                elif op == "subscribe":
                    if not logged_in:
                        await ws.send_json(
                            {"event": "error", "code": 60011, "msg": "Please log in"}
                        )
                        continue
                    for arg in data.get("args", []):
                        subscribed.append(arg)
                        await ws.send_json({"event": "subscribe", "arg": arg})
                    if push_task is None or push_task.done():
                        push_task = asyncio.create_task(push_loop())
        finally:
            if push_task is not None:
                push_task.cancel()
                await asyncio.gather(push_task, return_exceptions=True)
        return ws

    async def start(self, host: str = "127.0.0.1", port: int = 8765) -> str:
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host, port)
        await self._site.start()
        bound_port = self._site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        self.url = f"ws://{host}:{bound_port}/ws/v5/private"
        return self.url

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()


def _serve_forever(server: MockOkxWs, host: str, port: int) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(server.start(host, port))
    loop.run_forever()


if __name__ == "__main__":
    from packages.credential_vault import load_okx_demo_credentials

    creds = load_okx_demo_credentials()
    mock = MockOkxWs(creds.api_key, creds.secret_key, creds.passphrase)
    t = threading.Thread(target=_serve_forever, args=(mock, "127.0.0.1", 8765), daemon=True)
    t.start()
    print(f"mock OKX private WS listening on {mock.url}")
    try:
        while True:
            asyncio.new_event_loop()  # keep main thread alive
            import time

            time.sleep(3600)
    except KeyboardInterrupt:
        print("stopped")
