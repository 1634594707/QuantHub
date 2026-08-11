"""M4-05 verification: four-category reconcile scheduler runs, persists, and
captures errors without stopping the loop.

Run:  .venv/Scripts/python.exe tests/test_reconcile_scheduler.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps.okx_runner.reconcile_scheduler import ReconcileScheduler  # noqa: E402


class FakeReconcile:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> dict:
        self.calls += 1
        if self.calls == 3:
            raise RuntimeError("simulated upstream timeout")
        return {
            "account_id": "ACC-1",
            "difference_ids": [] if self.calls % 2 else ["diff-x"],
            "passed": bool(self.calls % 2),
        }


def main() -> int:
    fake = FakeReconcile()
    sched = ReconcileScheduler(runs_dir=str(ROOT / "data" / "reconcile_runs_test"))
    sched.configure(fake, "ACC-1", interval_seconds=0.3)
    sched.start()
    time.sleep(3.0)
    sched.stop()
    time.sleep(0.3)

    status = sched.status()
    runs = sched.list_runs(limit=50)
    print("status         :", {k: status[k] for k in ("running", "runs_total", "last_passed")})
    print("runs returned  :", len(runs))
    errors = [r for r in runs if r["error"]]
    passed = [r for r in runs if r["passed"] is True]
    print("passed runs    :", len(passed))
    print("error runs     :", len(errors))
    if errors:
        print("sample error   :", errors[0]["error"])

    ok = (
        status["runs_total"] >= 3
        and len(passed) >= 1
        and len(errors) >= 1
        and not sched.is_running()
    )
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
