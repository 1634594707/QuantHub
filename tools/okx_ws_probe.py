"""M4-04 evidence probe: connect to OKX private WebSocket (demo), login, subscribe,
capture pushes, then stop and print the evidence summary.

Run:  .venv/Scripts/python.exe tools/okx_ws_probe.py [--seconds 25]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Allow running from the repository root without an editable install.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ccxt  # noqa: E402

from apps.okx_runner.okx_adapter import OkxCcxtAdapter  # noqa: E402
from apps.okx_runner.private_ws import OkxPrivateWs  # noqa: E402
from packages.credential_vault import load_okx_demo_credentials  # noqa: E402


def build_adapter() -> OkxCcxtAdapter:
    creds = load_okx_demo_credentials()
    exchange = ccxt.okx(
        {
            "apiKey": creds.api_key,
            "secret": creds.secret_key,
            "password": creds.passphrase,
            "enableRateLimit": True,
        }
    )
    exchange.set_sandbox_mode(True)
    exchange.session.trust_env = True
    return OkxCcxtAdapter(exchange)


async def main(seconds: float) -> None:
    creds = load_okx_demo_credentials()
    adapter = build_adapter()

    def compensator():
        return adapter.account_snapshot("demo")

    client = OkxPrivateWs(
        api_key=creds.api_key,
        secret=creds.secret_key,
        passphrase=creds.passphrase,
        environment="demo",
        evidence_dir=ROOT / "data" / "okx_ws_evidence",
        rest_compensator=compensator,
        channels=("orders", "account", "positions", "balance_and_position"),
    )

    async def _stopper() -> None:
        await asyncio.sleep(seconds)
        await client.stop()

    print(f"[probe] connecting to {client._evidence['ws_url']} ...", flush=True)
    await asyncio.gather(client.arun(), _stopper())
    print("[probe] stopped.", flush=True)

    evidence = json.loads(client.evidence_path().read_text(encoding="utf-8"))
    print("\n=== M4-04 Evidence Summary ===")
    print(f"run_id            : {evidence['run_id']}")
    print(f"environment       : {evidence['environment']}")
    print(f"messages_received : {evidence['messages_received']}")
    print(f"private_messages  : {evidence['private_messages']}")
    print(f"reconnects        : {evidence['reconnects']}")
    print(f"rest_compensations: {evidence['rest_compensations']}")
    print(f"login_response    : {json.dumps(evidence['login_response'], ensure_ascii=False)}")
    print(f"subscribed        : {json.dumps(evidence['subscribed'], ensure_ascii=False)}")
    print(f"status            : {evidence['status']}")
    print(f"evidence_file     : {client.evidence_path()}")
    print("\nfirst events:")
    for ev in evidence.get("events", [])[:12]:
        print(
            f"  {ev['at']}  {ev['kind']:20s} {json.dumps(ev['payload'], ensure_ascii=False)[:120]}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=25.0)
    args = parser.parse_args()
    asyncio.run(main(args.seconds))
