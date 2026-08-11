"""M4-07 fault-injection drills for the OKX runner trade-verification loop.

Builds a RunnerEngine over a throwaway SQLite DB with a FaultyAdapter that
injects four fault classes, then asserts every fault degrades into a stable,
desensitized RunnerError code (never leaking secrets or raw stack text). Writes
an evidence file to data/fault_drill_evidence.json.

Run:  .venv/Scripts/python.exe tools/run_fault_drills.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ccxt  # noqa: E402

from apps.okx_runner.adapter import AccountSnapshot, TradingAdapter  # noqa: E402
from apps.okx_runner.database import initialize  # noqa: E402
from apps.okx_runner.engine import RunnerEngine  # noqa: E402
from apps.okx_runner.runner_errors import map_exception  # noqa: E402

# A fake secret that must never appear in any error output.
FAKE_SECRET = "sk_live_TOPSECRET_do_not_leak_123456"


class FaultyAdapter(TradingAdapter):
    def __init__(self, mode: str) -> None:
        self.mode = mode

    def preflight(self, symbols):  # noqa: D401 - protocol stub
        return {}

    def instrument_rules(self, symbol):
        raise NotImplementedError

    def submit_order(self, request):
        raise NotImplementedError

    def fetch_order_by_client_id(self, client_order_id, symbol=None):
        return None

    def cancel_order(self, external_order_id):
        raise NotImplementedError

    def mark_price(self, symbol):
        return 1.0

    def account_snapshot(self, account_id):
        if self.mode == "network":
            raise ConnectionError(f"connection reset by peer (secret={FAKE_SECRET})")
        if self.mode == "ratelimit":
            raise ccxt.RateLimitExceeded("too many requests")
        if self.mode == "badcreds":
            raise ccxt.AuthenticationError("invalid api key or signature")
        if self.mode == "clockdrift":
            raise ValueError("account snapshot is stale or has an invalid timestamp")
        # baseline: a valid empty snapshot
        return AccountSnapshot(
            orders=(),
            fills=(),
            balances={"USDT": {"total": 1000.0, "available": 1000.0}},
            positions={},
            observed_at=datetime.now(UTC),
        )


SCENARIOS = [
    ("network_down", "network", "NETWORK_UNREACHABLE", True),
    ("rate_limited", "ratelimit", "OKX_RATE_LIMITED", True),
    ("bad_credentials", "badcreds", "OKX_AUTH_FAILED", False),
    ("clock_drift", "clockdrift", "STALE_SNAPSHOT", False),
    ("baseline_ok", "ok", None, True),
]


def build_engine(mode: str) -> RunnerEngine:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db:
        db_path = Path(db.name)
    initialize(db_path)
    engine = RunnerEngine(db_path, FaultyAdapter(mode), b"test-signing-key", "demo", "1.0.0")
    return engine


def main() -> int:
    results = []
    all_ok = True
    for name, mode, expected_code, recoverable in SCENARIOS:
        engine = build_engine(mode)
        try:
            engine.reconcile("ACC-1")
            mapped = None
        except Exception as exc:  # noqa: BLE001 - we want the mapped representation
            mapped = map_exception(exc)
        record = {"scenario": name, "expected_code": expected_code}
        if mapped is None:
            record["result"] = "no_error"
            record["passed"] = expected_code is None
        else:
            serialized = mapped.redacted_json()
            leaked = FAKE_SECRET in serialized
            record["result"] = mapped.to_dict()
            record["leaked_secret"] = leaked
            record["passed"] = (mapped.code == expected_code) and (not leaked)
        record["passed"] = bool(record.get("passed"))
        if not record["passed"]:
            all_ok = False
        results.append(record)
        print(
            f"[{name}] expected={expected_code} -> "
            f"{record.get('result') if isinstance(record.get('result'), str) else record['result'].get('code') if record.get('result') else record['result']}"
        )

    evidence = {
        "generated_at": datetime.now(UTC).isoformat(),
        "milestone": "M4-07",
        "scenarios": results,
        "all_passed": all_ok,
    }
    out = ROOT / "data" / "fault_drill_evidence.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nevidence -> {out}")
    print("RESULT:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
