"""Instrument 持久化层：SQLite instruments 表（code+market 唯一）。"""

from __future__ import annotations

import json
import time

from apps.api import store

from .domain import Instrument


def _row_to_instrument(row) -> Instrument:
    return Instrument(
        code=row["code"],
        market=row["market"],
        exchange=row["exchange"] or "",
        name=row["name"] or "",
        currency=row["currency"] or "",
        asset_class=row["asset_class"] or "stock",
    )


def upsert(instrument: Instrument) -> Instrument:
    """插入或更新 Instrument（按 code+market 唯一）。"""
    with store._lock, store._conn() as c:
        c.execute(
            """INSERT INTO instruments (code, market, exchange, name, currency, asset_class, meta, ts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(code, market) DO UPDATE SET
                 exchange=excluded.exchange,
                 name=excluded.name,
                 currency=excluded.currency,
                 asset_class=excluded.asset_class,
                 meta=excluded.meta,
                 ts=excluded.ts""",
            (
                instrument.code,
                instrument.market,
                instrument.exchange,
                instrument.name,
                instrument.currency,
                instrument.asset_class,
                json.dumps({}),
                time.time(),
            ),
        )
        c.commit()
    return instrument


def get(code: str, market: str) -> Instrument | None:
    with store._lock, store._conn() as c:
        row = c.execute(
            "SELECT * FROM instruments WHERE code=? AND market=?",
            (code.upper(), market),
        ).fetchone()
    return _row_to_instrument(row) if row else None


def search(query: str, limit: int = 20, market: str | None = None) -> list[Instrument]:
    """按代码或名称模糊搜索（大小写不敏感）。"""
    pattern = f"%{query.upper()}%"
    with store._lock, store._conn() as c:
        if market:
            rows = c.execute(
                """SELECT * FROM instruments
                   WHERE market=? AND (UPPER(code) LIKE ? OR UPPER(name) LIKE ?)
                   ORDER BY ts DESC LIMIT ?""",
                (market, pattern, pattern, limit),
            ).fetchall()
        else:
            rows = c.execute(
                """SELECT * FROM instruments
                   WHERE UPPER(code) LIKE ? OR UPPER(name) LIKE ?
                   ORDER BY ts DESC LIMIT ?""",
                (pattern, pattern, limit),
            ).fetchall()
    return [_row_to_instrument(row) for row in rows]


def list_all(limit: int = 200, market: str | None = None) -> list[Instrument]:
    with store._lock, store._conn() as c:
        if market:
            rows = c.execute(
                "SELECT * FROM instruments WHERE market=? ORDER BY ts DESC LIMIT ?",
                (market, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM instruments ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
    return [_row_to_instrument(row) for row in rows]
