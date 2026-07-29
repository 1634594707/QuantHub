"""Run backup restore and persistent-run recovery drills in an isolated database."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from apps.api import database, store
from apps.api.domains.automation import repository as automation_repository
from apps.api.domains.automation import service as automation_service
from apps.api.domains.backups import service as backup_service


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def submit(self, *args):
        self.calls.append(args)
        return None


def run_drill() -> dict:
    original_db = store._DB
    original_backup_dir = backup_service.BACKUP_DIR
    original_executor = automation_service._EXECUTOR
    with tempfile.TemporaryDirectory(prefix="quanthub-recovery-") as temporary:
        root = Path(temporary)
        store._DB = root / "store.db"
        backup_service.BACKUP_DIR = root / "backups"
        recorder = RecordingExecutor()
        automation_service._EXECUTOR = recorder
        database.dispose_engines()
        try:
            store._init()
            with store._lock, store._conn() as connection:
                connection.execute(
                    "INSERT INTO app_meta (key, value) VALUES (?, ?)",
                    ("recovery_drill", "before"),
                )
            backup = backup_service.create_backup(actor="recovery-drill")
            with store._lock, store._conn() as connection:
                connection.execute(
                    "UPDATE app_meta SET value=? WHERE key=?",
                    ("after", "recovery_drill"),
                )
            restored = backup_service.restore_backup(
                backup["backup"]["name"],
                confirm_name=backup["backup"]["name"],
                actor="recovery-drill",
            )
            with store._lock, store._conn() as connection:
                restored_value = connection.execute(
                    "SELECT value FROM app_meta WHERE key=?",
                    ("recovery_drill",),
                ).fetchone()["value"]

            run = automation_repository.create_run(
                "recovery-drill",
                trigger_type="scheduled",
            )
            automation_repository.update_run(run["id"], {"status": "running"})
            recovery = automation_service.recover_pending_runs()
            recovered_run = automation_repository.get_run(run["id"])
            ok = (
                restored_value == "before"
                and restored["result"]["integrity"] == "ok"
                and recovery["run_ids"] == [run["id"]]
                and recovered_run is not None
                and recovered_run["status"] == "queued"
                and len(recorder.calls) == 1
            )
            return {
                "ok": ok,
                "backup_integrity": restored["result"]["integrity"],
                "restored_value": restored_value,
                "recovered_run_id": run["id"],
                "recovered_status": recovered_run["status"] if recovered_run else None,
                "dispatch_count": len(recorder.calls),
            }
        finally:
            database.dispose_engines()
            store._DB = original_db
            backup_service.BACKUP_DIR = original_backup_dir
            automation_service._EXECUTOR = original_executor


def main() -> int:
    argparse.ArgumentParser(description="QuantHub isolated recovery drill").parse_args()
    result = run_drill()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
