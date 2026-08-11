"""Delete only audited test signals, with a production guard and verification."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_DATABASE = (REPO_ROOT / "apps" / "api" / "store.db").resolve()


def table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    names = [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()
    ]
    return {
        name: int(connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
        for name in names
    }


def load_ids(manifest: Path) -> list[str]:
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    records = payload.get("contamination", {}).get("records", [])
    ids = [str(record.get("id") or "") for record in records]
    if not ids or any(not signal_id for signal_id in ids):
        raise ValueError("审计清单没有提供完整的 contamination.records[].id")
    if len(ids) != len(set(ids)):
        raise ValueError("审计清单包含重复 signal id")
    return ids


def purge(database: Path, manifest: Path, *, apply: bool, allow_production: bool) -> dict[str, Any]:
    database_path = database.resolve()
    if apply and database_path == PRODUCTION_DATABASE and not allow_production:
        raise RuntimeError("拒绝清理生产主库；负责人确认后必须显式传入 --allow-production")

    expected_ids = load_ids(manifest.resolve())
    placeholders = ",".join("?" for _ in expected_ids)
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        before = table_counts(connection)
        present_ids = {
            str(row[0])
            for row in connection.execute(
                f"SELECT id FROM signals WHERE id IN ({placeholders})", expected_ids
            ).fetchall()
        }
        missing_ids = sorted(set(expected_ids) - present_ids)
        if missing_ids:
            raise RuntimeError(f"数据库缺少审计清单中的 {len(missing_ids)} 条记录")

        if apply:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(f"DELETE FROM signals WHERE id IN ({placeholders})", expected_ids)
            connection.commit()

        remaining = int(
            connection.execute(
                f"SELECT COUNT(*) FROM signals WHERE id IN ({placeholders})", expected_ids
            ).fetchone()[0]
        )
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_key_violations = [
            list(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()
        ]
        after = table_counts(connection)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "database": str(database_path),
        "production_database": str(PRODUCTION_DATABASE),
        "manifest": str(manifest.resolve()),
        "dry_run": not apply,
        "expected_records": len(expected_ids),
        "matched_records": len(present_ids),
        "deleted_records": len(expected_ids) - remaining if apply else 0,
        "remaining_manifest_records": remaining,
        "integrity_check": integrity,
        "foreign_key_violations": foreign_key_violations,
        "table_counts_before": before,
        "table_counts_after": after,
        "ok": integrity == "ok" and not foreign_key_violations and (not apply or remaining == 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge audited test signals")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--json", dest="json_path", type=Path)
    args = parser.parse_args()

    result = purge(
        args.database,
        args.manifest,
        apply=args.apply,
        allow_production=args.allow_production,
    )
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
