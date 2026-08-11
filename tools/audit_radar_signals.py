"""Read-only audit for the signal ledger used by the QuantHub radar."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONTAMINATION_SQL = """
source='api_test' OR symbol LIKE 'E2E-%' OR source='playwright_mobile'
""".strip()


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rows(connection: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(sql).fetchall()]


def file_metadata(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": sha256_of(resolved),
    }


def audit(database: Path, backup: Path | None = None) -> dict[str, Any]:
    database_path = database.resolve()
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    with sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        result: dict[str, Any] = {
            "generated_at": datetime.now(UTC).isoformat(),
            "read_only": True,
            "database": file_metadata(database_path),
            "integrity_check": integrity,
            "distributions": {
                "total": int(connection.execute("SELECT COUNT(*) FROM signals").fetchone()[0]),
                "source": rows(
                    connection,
                    "SELECT source, COUNT(*) AS count FROM signals "
                    "GROUP BY source ORDER BY count DESC, source",
                ),
                "status": rows(
                    connection,
                    "SELECT status, COUNT(*) AS count FROM signals GROUP BY status ORDER BY status",
                ),
                "market": rows(
                    connection,
                    "SELECT market, COUNT(*) AS count FROM signals GROUP BY market ORDER BY market",
                ),
                "confidence": rows(
                    connection,
                    "SELECT confidence, COUNT(*) AS count FROM signals "
                    "GROUP BY confidence ORDER BY confidence",
                ),
                "source_confidence": rows(
                    connection,
                    "SELECT source, confidence, COUNT(*) AS count FROM signals "
                    "GROUP BY source, confidence ORDER BY source, confidence",
                ),
            },
            "contamination": {
                "selection_rule": CONTAMINATION_SQL,
                "summary": rows(
                    connection,
                    f"SELECT source, COUNT(*) AS count FROM signals WHERE {CONTAMINATION_SQL} "
                    "GROUP BY source ORDER BY source",
                ),
                "records": rows(
                    connection,
                    "SELECT id, instrument_id, symbol, market, timeframe, direction, score, "
                    "confidence, source, tags_json, meta_json, ts_iso, ts_epoch, status, "
                    "expires_at, reviewed_at, decision_note, order_id, fingerprint "
                    f"FROM signals WHERE {CONTAMINATION_SQL} ORDER BY ts_epoch, id",
                ),
            },
        }
    if backup is not None:
        backup_path = backup.resolve()
        result["backup"] = file_metadata(backup_path)
        with sqlite3.connect(
            f"file:{backup_path.as_posix()}?mode=ro", uri=True
        ) as backup_connection:
            result["backup"]["integrity_check"] = str(
                backup_connection.execute("PRAGMA integrity_check").fetchone()[0]
            )
    result["ok"] = result["integrity_check"] == "ok" and (
        backup is None or result["backup"]["integrity_check"] == "ok"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit radar signal truth and contamination")
    parser.add_argument("--database", type=Path, default=Path("apps/api/store.db"))
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--json", dest="json_path", type=Path)
    args = parser.parse_args()

    result = audit(args.database, args.backup)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
