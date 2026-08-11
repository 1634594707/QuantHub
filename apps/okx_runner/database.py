from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 2

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS strategy_versions (
    strategy_id TEXT NOT NULL,
    version TEXT NOT NULL,
    package_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    PRIMARY KEY(strategy_id, version)
);
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    client_order_id TEXT NOT NULL UNIQUE,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    account_id TEXT NOT NULL,
    environment TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL,
    leverage REAL NOT NULL,
    request_json TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    external_order_id TEXT,
    status TEXT NOT NULL,
    filled_quantity REAL NOT NULL DEFAULT 0,
    average_price REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL REFERENCES orders(order_id),
    from_status TEXT,
    to_status TEXT NOT NULL,
    external_order_id TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fills (
    external_fill_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(order_id),
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    fee REAL NOT NULL,
    fee_currency TEXT NOT NULL,
    filled_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS balance_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    environment TEXT NOT NULL,
    currency TEXT NOT NULL,
    total REAL NOT NULL,
    available REAL NOT NULL,
    observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS position_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    environment TEXT NOT NULL,
    symbol TEXT NOT NULL,
    quantity REAL NOT NULL,
    mark_price REAL NOT NULL,
    entry_price REAL,
    unrealized_pnl REAL NOT NULL DEFAULT 0,
    leverage REAL,
    position_side TEXT,
    observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS account_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    environment TEXT NOT NULL,
    equity REAL NOT NULL,
    realized_pnl REAL NOT NULL DEFAULT 0,
    unrealized_pnl REAL NOT NULL DEFAULT 0,
    peak_equity REAL,
    observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reconciliation_diffs (
    diff_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    local_json TEXT NOT NULL,
    external_json TEXT NOT NULL,
    status TEXT NOT NULL,
    owner TEXT,
    resolution TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS risk_states (
    scope TEXT PRIMARY KEY,
    mode TEXT NOT NULL CHECK(mode IN ('normal', 'halted', 'cancel_only')),
    reason TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime_results (
    run_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    environment TEXT NOT NULL,
    result_json TEXT NOT NULL,
    result_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS risk_decisions (
    decision_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    intent_id TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    snapshot_reference TEXT,
    limits_json TEXT NOT NULL,
    calculation_json TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK(outcome IN ('approved', 'rejected')),
    reason TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runner_risk_decisions ON risk_decisions(account_id, created_at);
CREATE INDEX IF NOT EXISTS idx_runner_open_orders ON orders(status, account_id);
"""


def initialize(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        row = connection.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
        if row is None:
            connection.execute("INSERT INTO schema_meta VALUES (?)", (SCHEMA_VERSION,))
        elif row[0] < SCHEMA_VERSION:
            existing_columns = {
                item[1] for item in connection.execute("PRAGMA table_info(position_snapshots)")
            }
            migrations = {
                "entry_price": "ALTER TABLE position_snapshots ADD COLUMN entry_price REAL",
                "unrealized_pnl": "ALTER TABLE position_snapshots ADD COLUMN unrealized_pnl REAL NOT NULL DEFAULT 0",
                "leverage": "ALTER TABLE position_snapshots ADD COLUMN leverage REAL",
                "position_side": "ALTER TABLE position_snapshots ADD COLUMN position_side TEXT",
            }
            for column, statement in migrations.items():
                if column not in existing_columns:
                    connection.execute(statement)
            connection.execute("UPDATE schema_meta SET version=?", (SCHEMA_VERSION,))
        elif row[0] != SCHEMA_VERSION:
            raise RuntimeError(f"unsupported Runner schema version {row[0]}")
        connection.execute(
            "INSERT OR IGNORE INTO risk_states VALUES ('global', 'normal', 'initial', datetime('now'))"
        )
        connection.commit()
    finally:
        connection.close()


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    initialize(path)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
