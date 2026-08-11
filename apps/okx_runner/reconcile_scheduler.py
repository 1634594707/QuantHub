from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .runner_errors import map_exception

# The four reconciliation categories performed by RunnerEngine.reconcile.
RECONCILE_CATEGORIES = ("order", "fill", "balance", "position")

ReconcileCallable = Callable[[], dict[str, Any]]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ReconcileScheduler:
    """Periodically runs the four-category reconciliation and persists run records.

    The scheduler is engine-agnostic: it is handed a ``reconcile_callable`` that
    performs one reconciliation pass and returns the engine result. In production
    this is ``lambda: engine.reconcile(account_id)``; in tests it is a fake. All
    runs are written to ``data/reconcile_runs/<run_id>.json`` so M4-08 can audit
    the cadence and outcomes.
    """

    def __init__(self, runs_dir: str | Path | None = None) -> None:
        self._reconcile: ReconcileCallable | None = None
        self._account_id: str | None = None
        self._interval: float = 30.0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._runs_dir = Path(runs_dir or "data/reconcile_runs")
        self._status: dict[str, Any] = {
            "running": False,
            "account_id": None,
            "interval_seconds": None,
            "runs_total": 0,
            "last_run_at": None,
            "last_passed": None,
            "last_error": None,
            "categories": list(RECONCILE_CATEGORIES),
        }

    # -- configuration -----------------------------------------------------
    def configure(
        self,
        reconcile_callable: ReconcileCallable,
        account_id: str,
        interval_seconds: float = 30.0,
    ) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("cannot reconfigure a running scheduler")
            self._reconcile = reconcile_callable
            self._account_id = account_id
            self._interval = max(1.0, float(interval_seconds))

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> dict[str, Any]:
        if self._reconcile is None:
            raise RuntimeError("scheduler must be configured before start")
        if self._thread is not None and self._thread.is_alive():
            return self.status()
        with self._lock:
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop, name="reconcile-scheduler", daemon=True
            )
            self._status["running"] = True
            self._status["account_id"] = self._account_id
            self._status["interval_seconds"] = self._interval
            thread = self._thread
        thread.start()
        return self.status()

    def stop(self, timeout_seconds: float = 10.0) -> dict[str, Any]:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout_seconds))
        with self._lock:
            self._status["running"] = bool(thread and thread.is_alive())
        return self.status()

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    # -- querying ----------------------------------------------------------
    def status(self) -> dict[str, Any]:
        with self._lock:
            self._status["running"] = self.is_running()
            return dict(self._status)

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(self._runs_dir.glob("*.json"), reverse=True)
        records: list[dict[str, Any]] = []
        for path in files[: limit * 4]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            records.append(
                {
                    "run_id": data.get("run_id"),
                    "account_id": data.get("account_id"),
                    "ran_at": data.get("ran_at"),
                    "passed": data.get("passed"),
                    "difference_count": data.get("difference_count"),
                    "error": data.get("error"),
                }
            )
            if len(records) >= limit:
                break
        return records

    # -- internals ---------------------------------------------------------
    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                self._run_once()
                self._stop.wait(self._interval)
        finally:
            with self._lock:
                self._status["running"] = False

    def _run_once(self) -> dict[str, Any]:
        run_id = f"rec-{uuid.uuid4().hex[:12]}"
        ran_at = _now_iso()
        record: dict[str, Any] = {
            "run_id": run_id,
            "account_id": self._account_id,
            "ran_at": ran_at,
            "categories": list(RECONCILE_CATEGORIES),
            "passed": None,
            "difference_count": None,
            "error": None,
        }
        try:
            assert self._reconcile is not None
            result = self._reconcile()
            record["passed"] = bool(result.get("passed"))
            record["difference_count"] = len(result.get("difference_ids") or [])
            record["engine_result"] = result
        except Exception as exc:  # noqa: BLE001 - capture, desensitize, continue
            err = map_exception(exc)
            record["error"] = err.to_dict()
        self._persist(record)
        with self._lock:
            self._status["runs_total"] += 1
            self._status["last_run_at"] = ran_at
            self._status["last_passed"] = record["passed"]
            self._status["last_error"] = record["error"]
        return record

    def _persist(self, record: dict[str, Any]) -> None:
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        path = self._runs_dir / f"{record['run_id']}.json"
        # Avoid persisting the full engine result (may contain sensitive context)
        # in the on-disk record; keep a safe summary only.
        safe = {k: v for k, v in record.items() if k != "engine_result"}
        with path.open("w", encoding="utf-8") as handle:
            json.dump(safe, handle, ensure_ascii=False, indent=2)


# Module-level singleton used by the FastAPI app and tooling.
_SCHEDULER = ReconcileScheduler()


def get_scheduler() -> ReconcileScheduler:
    return _SCHEDULER
