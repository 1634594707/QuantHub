"""M4-08 daily observation probe for the OKX trade-verification loop.

Collects one dated evidence file per UTC day under data/observation/ covering:
  - REST account reachability + desensitized balance/position summary
  - public WebSocket reachability (live ticker)
  - private WebSocket login handshake status (evidence of M4-04)
  - one-shot four-category reconciliation (evidence of M4-05)

Run it once per day for 7 consecutive days (e.g. via cron / Task Scheduler) and
fill in docs/m4_observation_template.md. It is idempotent per day unless --force.

Run:  .venv/Scripts/python.exe tools/observe_daily.py [--account-id demo] [--force]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps.okx_runner.database import initialize  # noqa: E402
from apps.okx_runner.engine import RunnerEngine  # noqa: E402
from apps.okx_runner.okx_adapter import OkxCcxtAdapter  # noqa: E402
from apps.okx_runner.private_ws import OkxPrivateWs  # noqa: E402
from apps.okx_runner.runner_errors import map_exception  # noqa: E402
from packages.credential_vault import load_okx_demo_credentials  # noqa: E402

OBS_DIR = ROOT / "data" / "observation"
DEMO_DB = ROOT / "data" / "okx_runner" / "runner-demo.db"
PUBLIC_WS = "wss://wspap.okx.com:8443/ws/v5/public?brokerId=9999"
logger = logging.getLogger(__name__)


def section(name: str, fn):
    try:
        result = fn()
        if isinstance(result, dict) and "ok" in result:
            ok = bool(result["ok"])
            detail = {key: value for key, value in result.items() if key != "ok"}
            return {"ok": ok, "detail": detail}
        return {"ok": True, "detail": result}
    except Exception as exc:  # noqa: BLE001 - record, never crash the whole probe
        return {"ok": False, "error": map_exception(exc).to_dict()}


def rest_probe(account_id: str) -> dict:
    import ccxt

    creds = load_okx_demo_credentials()
    ex = ccxt.okx(
        {
            "apiKey": creds.api_key,
            "secret": creds.secret_key,
            "password": creds.passphrase,
            "enableRateLimit": True,
        }
    )
    ex.set_sandbox_mode(True)
    ex.session.trust_env = True
    adapter = OkxCcxtAdapter(ex)
    snap = adapter.account_snapshot(account_id)
    return {
        "balances": list((snap.balances or {}).keys()),
        "positions": list((snap.positions or {}).keys()),
        "observed_at": snap.observed_at.astimezone(UTC).isoformat()
        if snap.observed_at.tzinfo
        else str(snap.observed_at),
    }


def public_ws_probe() -> dict:
    import os

    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    captured: dict = {}

    async def _run() -> None:
        import aiohttp

        async with aiohttp.ClientSession(trust_env=True) as s:
            async with s.ws_connect(
                PUBLIC_WS, proxy=proxy, heartbeat=20, ssl=True, timeout=15
            ) as ws:
                await ws.send_json(
                    {"op": "subscribe", "args": [{"channel": "tickers", "instId": "BTC-USDT"}]}
                )
                for _ in range(4):
                    msg = await asyncio.wait_for(ws.receive(), timeout=8)
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        p = json.loads(msg.data)
                        if p.get("data"):
                            captured["last"] = p["data"][0].get("last")
                            captured["inst_id"] = p["arg"].get("instId")
                            return

    asyncio.run(_run())
    return {"ok": bool(captured.get("last") and captured.get("inst_id")), **captured}


def private_ws_probe(account_id: str, seconds: int) -> dict:
    import ccxt

    creds = load_okx_demo_credentials()
    ex = ccxt.okx(
        {
            "apiKey": creds.api_key,
            "secret": creds.secret_key,
            "password": creds.passphrase,
            "enableRateLimit": True,
        }
    )
    ex.set_sandbox_mode(True)
    ex.session.trust_env = True
    adapter = OkxCcxtAdapter(ex)

    def compensator():
        return adapter.account_snapshot(account_id)

    client = OkxPrivateWs(
        api_key=creds.api_key,
        secret=creds.secret_key,
        passphrase=creds.passphrase,
        environment="demo",
        evidence_dir=OBS_DIR / "ws_evidence",
        rest_compensator=compensator,
        channels=("orders", "account"),
        run_id=f"obs-{datetime.now(UTC).strftime('%Y%m%d')}",
    )

    def _runner() -> None:
        try:
            client.run()
        except Exception as exc:  # noqa: BLE001 - report the safe mapped category below
            mapped = map_exception(exc)
            logger.warning("private websocket probe stopped: %s", mapped.code)

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    time.sleep(seconds)
    client.request_stop()
    t.join(timeout=5)
    data = json.loads(client.evidence_path().read_text(encoding="utf-8"))
    return {
        "ok": (data.get("login_response") or {}).get("code") in (0, "0"),
        "login_response": data.get("login_response"),
        "private_messages": data.get("private_messages"),
        "reconnects": data.get("reconnects"),
        "rest_compensations": data.get("rest_compensations"),
        "status": data.get("status"),
        "last_error": data.get("last_error"),
    }


def reconcile_probe(account_id: str) -> dict:
    import ccxt

    initialize(DEMO_DB)
    creds = load_okx_demo_credentials()
    ex = ccxt.okx(
        {
            "apiKey": creds.api_key,
            "secret": creds.secret_key,
            "password": creds.passphrase,
            "enableRateLimit": True,
        }
    )
    ex.set_sandbox_mode(True)
    ex.session.trust_env = True
    engine = RunnerEngine(DEMO_DB, OkxCcxtAdapter(ex), b"dev-key", "demo", "1.0.0")
    result = engine.reconcile(account_id)
    passed = bool(result.get("passed"))
    difference_count = len(result.get("difference_ids") or [])
    return {
        "ok": passed and difference_count == 0,
        "passed": bool(result.get("passed")),
        "difference_count": difference_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-id", default="demo")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--ws-seconds", type=int, default=8)
    args = parser.parse_args()

    OBS_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    out = OBS_DIR / f"{day}.json"
    if out.exists() and not args.force:
        print(f"[observe] {day} already collected ({out}); use --force to re-run.")
        return 0

    print(f"[observe] collecting {day} ...", flush=True)
    record = {
        "date": day,
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": "demo",
        "account_id": args.account_id,
        "rest": section("rest", lambda: rest_probe(args.account_id)),
        "public_ws": section("public_ws", public_ws_probe),
        "private_ws": section(
            "private_ws", lambda: private_ws_probe(args.account_id, args.ws_seconds)
        ),
        "reconcile": section("reconcile", lambda: reconcile_probe(args.account_id)),
    }
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[observe] wrote {out}")
    print(json.dumps({k: v.get("ok") for k, v in record.items() if isinstance(v, dict)}, indent=2))
    return 0 if all(v.get("ok") is True for v in record.values() if isinstance(v, dict)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
