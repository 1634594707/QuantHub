"""Lossless, verifiable migration of legacy execution data into OKX Runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from packages.research_protocol import canonical_json

PRODUCT_TABLES = {
    "okx_runner": (
        "signals",
        "simulation_orders",
        "simulation_executions",
        "ledger_trades",
        "ledger_cash",
        "ledger_positions",
        "ledger_benchmarks",
        "ledger_corrections",
    ),
}

MIGRATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS legacy_migration_runs (
    run_id TEXT PRIMARY KEY,
    product TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    counts_json TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    rolled_back_at TEXT
);
CREATE TABLE IF NOT EXISTS legacy_migration_records (
    run_id TEXT NOT NULL REFERENCES legacy_migration_runs(run_id),
    source_table TEXT NOT NULL,
    source_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    PRIMARY KEY(run_id, source_table, source_key)
);
"""


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def _records(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    if not _table_exists(connection, table):
        return []
    connection.row_factory = sqlite3.Row
    return [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"').fetchall()]


def _record_key(table: str, row: dict[str, Any]) -> str:
    for columns in (("id",), ("code", "market"), ("key",), ("name",)):
        if all(row.get(column) is not None for column in columns):
            return "|".join(str(row[column]) for column in columns)
    return hashlib.sha256(canonical_json(row).encode("utf-8")).hexdigest()


def inspect_source(source: Path, product: str) -> dict[str, Any]:
    if product not in PRODUCT_TABLES:
        raise ValueError(f"unsupported product {product}")
    if not source.is_file():
        raise FileNotFoundError(source)
    connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    try:
        tables: dict[str, list[dict[str, Any]]] = {
            table: _records(connection, table) for table in PRODUCT_TABLES[product]
        }
    finally:
        connection.close()
    hashes = {
        table: hashlib.sha256(canonical_json(rows).encode("utf-8")).hexdigest()
        for table, rows in tables.items()
    }
    source_hash = hashlib.sha256(canonical_json(hashes).encode("utf-8")).hexdigest()
    return {
        "product": product,
        "source": str(source.resolve()),
        "counts": {table: len(rows) for table, rows in tables.items()},
        "hashes": hashes,
        "source_hash": source_hash,
        "tables": tables,
    }


def apply_migration(source: Path, target: Path, product: str) -> dict[str, Any]:
    inspection = inspect_source(source, product)
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.with_suffix(target.suffix + ".pre-migration.bak")
    if target.exists():
        shutil.copy2(target, backup)
    run_id = f"legacy-{product}-{uuid.uuid4().hex}"
    connection = sqlite3.connect(target)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(MIGRATION_SCHEMA)
        connection.execute("BEGIN")
        connection.execute(
            "INSERT INTO legacy_migration_runs VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (
                run_id,
                product,
                inspection["source"],
                inspection["source_hash"],
                canonical_json(inspection["counts"]),
                datetime.now(UTC).isoformat(),
            ),
        )
        for table, rows in inspection["tables"].items():
            for row in rows:
                payload = canonical_json(row)
                connection.execute(
                    "INSERT INTO legacy_migration_records VALUES (?, ?, ?, ?, ?)",
                    (
                        run_id,
                        table,
                        _record_key(table, row),
                        payload,
                        hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                    ),
                )
        connection.commit()
        verification = verify_migration(connection, run_id, inspection)
        if not verification["verified"]:
            raise RuntimeError(f"migration verification failed: {verification}")
    except Exception:
        connection.rollback()
        connection.close()
        if backup.exists():
            shutil.copy2(backup, target)
        raise
    finally:
        if connection:
            connection.close()
    manifest = target.with_suffix(target.suffix + f".{run_id}.json")
    manifest.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "product": product,
                "source": str(source.resolve()),
                "target": str(target.resolve()),
                "backup": str(backup.resolve()) if backup.exists() else None,
                "counts": inspection["counts"],
                "source_hash": inspection["source_hash"],
                "verified": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return json.loads(manifest.read_text(encoding="utf-8")) | {"manifest": str(manifest)}


def verify_migration(
    connection: sqlite3.Connection, run_id: str, inspection: dict[str, Any]
) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT source_table, payload_json FROM legacy_migration_records WHERE run_id=? ORDER BY source_table, source_key",
        (run_id,),
    ).fetchall()
    by_table: dict[str, list[dict[str, Any]]] = {table: [] for table in inspection["tables"]}
    for table, payload in rows:
        by_table[table].append(json.loads(payload))
    target_hashes = {
        table: hashlib.sha256(canonical_json(values).encode("utf-8")).hexdigest()
        for table, values in by_table.items()
    }
    target_counts = {table: len(values) for table, values in by_table.items()}
    return {
        "verified": target_counts == inspection["counts"] and target_hashes == inspection["hashes"],
        "counts": target_counts,
        "hashes": target_hashes,
    }


def rollback(target: Path, run_id: str) -> dict[str, Any]:
    connection = sqlite3.connect(target)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        row = connection.execute(
            "SELECT rolled_back_at FROM legacy_migration_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise LookupError("migration run not found")
        if row[0]:
            return {"run_id": run_id, "rolled_back": True, "already_rolled_back": True}
        connection.execute("DELETE FROM legacy_migration_records WHERE run_id=?", (run_id,))
        connection.execute(
            "UPDATE legacy_migration_runs SET rolled_back_at=? WHERE run_id=?",
            (datetime.now(UTC).isoformat(), run_id),
        )
        connection.commit()
    finally:
        connection.close()
    return {"run_id": run_id, "rolled_back": True, "already_rolled_back": False}


def main(argv: list[str] | None = None, *, fixed_product: str | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product", choices=sorted(PRODUCT_TABLES), required=fixed_product is None)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", metavar="RUN_ID")
    args = parser.parse_args(argv)
    product = fixed_product or args.product
    if args.rollback:
        result = rollback(args.target.resolve(), args.rollback)
    elif args.apply:
        result = apply_migration(args.source.resolve(), args.target.resolve(), product)
    else:
        inspection = inspect_source(args.source.resolve(), product)
        result = {key: value for key, value in inspection.items() if key != "tables"} | {
            "dry_run": True
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
