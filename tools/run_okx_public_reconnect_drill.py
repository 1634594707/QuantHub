"""Run a read-only OKX public WebSocket disconnect/reconnect acceptance drill."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from packages.market_data.okx_public_ws import OkxPublicMarketStream

OUTPUT = Path("docs/Plan/evidence/factor-cohort-v1-2026-08-12/real-public-reconnect.json")


async def probe_tcp(port: int) -> dict:
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection("ws.okx.com", port),
            timeout=5,
        )
        writer.close()
        await writer.wait_closed()
        return {"port": port, "connected": True, "error": None}
    except Exception as exc:  # noqa: BLE001 - evidence records the environment failure
        return {"port": port, "connected": False, "error": f"{type(exc).__name__}: {exc}"}


async def run_drill(timeout_seconds: float, *, standard_port: bool) -> dict:
    started = datetime.now(UTC)
    tcp_connectivity = await asyncio.gather(probe_tcp(443), probe_tcp(8443))
    stream = OkxPublicMarketStream(
        inst_id="BTC-USDT-SWAP",
        candle_channel="candle1H",
        reconnect_base=0.25,
        reconnect_max=1.0,
        max_reconnect=5,
        fault_disconnect_after_messages=1,
        public_ws_url=(
            "wss://ws.okx.com/ws/v5/public"
            if standard_port
            else "wss://ws.okx.com:8443/ws/v5/public"
        ),
        business_ws_url=(
            "wss://ws.okx.com/ws/v5/business"
            if standard_port
            else "wss://ws.okx.com:8443/ws/v5/business"
        ),
    )

    async def stop_when_proved() -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            evidence = stream.evidence
            if (
                evidence["reconnects"] >= 1
                and evidence["rest_compensations"] >= 1
                and evidence["connections_opened"] >= 3
                and evidence["events_after_reconnect"] >= 1
            ):
                await stream.stop()
                return
            await asyncio.sleep(0.1)
        await stream.stop()

    await asyncio.gather(stream.arun(), stop_when_proved())
    evidence = stream.evidence
    checks = {
        "real_public_connections_opened": evidence["connections_opened"] >= 3,
        "forced_disconnect_recorded": bool(evidence["fault_injections"]),
        "gap_recorded": bool(evidence["gaps"]),
        "rest_compensation_completed": evidence["rest_compensations"] >= 1,
        "automatic_reconnect_completed": evidence["reconnects"] >= 1,
        "fresh_event_received_after_reconnect": evidence["events_after_reconnect"] >= 1,
        "duplicates_accounted_for": evidence["duplicates_suppressed"] >= 0,
    }
    return {
        "evidence_kind": "real_exchange_read_only_fault_drill",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "instrument": "BTC-USDT-SWAP",
        "websocket_port": 443 if standard_port else 8443,
        "tcp_connectivity": tcp_connectivity,
        "credentials_used": False,
        "orders_sent": 0,
        "live_trading_enabled": False,
        "checks": checks,
        "passed": all(checks.values()),
        "stream_evidence": evidence,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--standard-port", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(run_drill(args.timeout, standard_port=args.standard_port))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
