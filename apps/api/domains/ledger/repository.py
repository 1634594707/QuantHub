"""组合账本持久化层。"""

from __future__ import annotations

import json
import time
import uuid

from apps.api import store

from .domain import Benchmark, CashEntry, Trade


def _trade_row(row) -> Trade:
    return Trade(
        id=row["id"],
        instrument_id=row["instrument_id"],
        code=row["code"],
        market=row["market"],
        direction=row["direction"],
        quantity=row["quantity"],
        price=row["price"],
        fee=row["fee"],
        ts=row["ts"],
        source=row["source"],
        note=row["note"],
        strategy_id=row["strategy_id"],
        strategy_version=row["strategy_version"],
        factor_key=row["factor_key"],
        factor_version=row["factor_version"],
        research_run_id=row["research_run_id"],
        signal_id=row["signal_id"],
        simulation_order_id=row["simulation_order_id"],
        execution_id=row["execution_id"],
        market_regime_id=row["market_regime_id"],
        attribution_status=row["attribution_status"] or "unknown_attribution",
    )


def _cash_row(row) -> CashEntry:
    return CashEntry(
        id=row["id"],
        direction=row["direction"],
        amount=row["amount"],
        currency=row["currency"],
        ts=row["ts"],
        source=row["source"],
        note=row["note"],
    )


def _bench_row(row) -> Benchmark:
    return Benchmark(
        id=row["id"],
        name=row["name"],
        code=row["code"],
        market=row["market"],
        equity_curve=json.loads(row["equity_curve"]) if row["equity_curve"] else [],
        metrics=json.loads(row["metrics"]) if row["metrics"] else {},
        ts=row["ts"],
    )


# ---- Trade ----
def save_trade(trade: Trade) -> Trade:
    with store._lock, store._conn() as c:
        c.execute(
            """INSERT INTO ledger_trades
               (id, instrument_id, code, market, direction, quantity, price, fee, ts,
                source, note, strategy_id, strategy_version, factor_key, factor_version,
                research_run_id, signal_id, simulation_order_id, execution_id,
                market_regime_id, attribution_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trade.id,
                trade.instrument_id,
                trade.code,
                trade.market,
                trade.direction,
                trade.quantity,
                trade.price,
                trade.fee,
                trade.ts,
                trade.source,
                trade.note,
                trade.strategy_id,
                trade.strategy_version,
                trade.factor_key,
                trade.factor_version,
                trade.research_run_id,
                trade.signal_id,
                trade.simulation_order_id,
                trade.execution_id,
                trade.market_regime_id,
                trade.attribution_status,
            ),
        )
        c.commit()
    return trade


def save_trade_if_absent(trade: Trade) -> Trade:
    """按成交编号幂等写入，供跨域同步和重试使用。"""
    with store._lock, store._conn() as c:
        c.execute(
            """INSERT OR IGNORE INTO ledger_trades
               (id, instrument_id, code, market, direction, quantity, price, fee, ts,
                source, note, strategy_id, strategy_version, factor_key, factor_version,
                research_run_id, signal_id, simulation_order_id, execution_id,
                market_regime_id, attribution_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trade.id,
                trade.instrument_id,
                trade.code,
                trade.market,
                trade.direction,
                trade.quantity,
                trade.price,
                trade.fee,
                trade.ts,
                trade.source,
                trade.note,
                trade.strategy_id,
                trade.strategy_version,
                trade.factor_key,
                trade.factor_version,
                trade.research_run_id,
                trade.signal_id,
                trade.simulation_order_id,
                trade.execution_id,
                trade.market_regime_id,
                trade.attribution_status,
            ),
        )
        row = c.execute("SELECT * FROM ledger_trades WHERE id=?", (trade.id,)).fetchone()
        c.commit()
    return _trade_row(row)


def get_trade(trade_id: str) -> Trade | None:
    with store._lock, store._conn() as c:
        row = c.execute(
            "SELECT * FROM ledger_trades WHERE id=?",
            (trade_id,),
        ).fetchone()
    return _trade_row(row) if row else None


def list_trades(instrument_id: str | None = None, limit: int = 200) -> list[Trade]:
    with store._lock, store._conn() as c:
        if instrument_id:
            rows = c.execute(
                "SELECT * FROM ledger_trades WHERE instrument_id=? ORDER BY ts DESC LIMIT ?",
                (instrument_id, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM ledger_trades ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
    return [_trade_row(r) for r in rows]


def list_trades_page(
    *, instrument_id: str | None = None, limit: int = 200, cursor: str | None = None
) -> dict:
    clauses: list[str] = []
    params: list = []
    if instrument_id:
        clauses.append("instrument_id=?")
        params.append(instrument_id)
    count_sql = "SELECT COUNT(*) AS total FROM ledger_trades"
    if clauses:
        count_sql += " WHERE " + " AND ".join(clauses)
    page_clauses = list(clauses)
    page_params = list(params)
    if cursor:
        cursor_value, cursor_id = store._decode_cursor(cursor)
        page_clauses.append("(ts < ? OR (ts = ? AND id < ?))")
        page_params.extend([cursor_value, cursor_value, cursor_id])
    sql = "SELECT * FROM ledger_trades"
    if page_clauses:
        sql += " WHERE " + " AND ".join(page_clauses)
    sql += " ORDER BY ts DESC, id DESC LIMIT ?"
    page_params.append(limit + 1)
    with store._lock, store._conn() as c:
        total = int(c.execute(count_sql, params).fetchone()["total"])
        rows = c.execute(sql, page_params).fetchall()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    return {
        "items": [_trade_row(row) for row in page_rows],
        "total": total,
        "next_cursor": (
            store._encode_cursor(float(page_rows[-1]["ts"]), str(page_rows[-1]["id"]))
            if has_more and page_rows
            else None
        ),
    }


def correct_trade(trade: Trade, reason: str) -> dict | None:
    with store._lock, store._conn() as c:
        row = c.execute("SELECT * FROM ledger_trades WHERE id=?", (trade.id,)).fetchone()
        if row is None:
            return None
        before = _trade_row(row).to_dict()
        c.execute(
            """UPDATE ledger_trades SET instrument_id=?, code=?, market=?, direction=?,
               quantity=?, price=?, fee=?, source=?, note=?, strategy_id=?,
               strategy_version=?, factor_key=?, factor_version=?, research_run_id=?,
               signal_id=?, simulation_order_id=?, execution_id=?, market_regime_id=?,
               attribution_status=? WHERE id=?""",
            (
                trade.instrument_id,
                trade.code,
                trade.market,
                trade.direction,
                trade.quantity,
                trade.price,
                trade.fee,
                trade.source,
                trade.note,
                trade.strategy_id,
                trade.strategy_version,
                trade.factor_key,
                trade.factor_version,
                trade.research_run_id,
                trade.signal_id,
                trade.simulation_order_id,
                trade.execution_id,
                trade.market_regime_id,
                trade.attribution_status,
                trade.id,
            ),
        )
        after = trade.to_dict()
        correction_id = str(uuid.uuid4())
        created_at = time.time()
        c.execute(
            """INSERT INTO ledger_corrections
               (id, entity_type, entity_id, reason, before_json, after_json, created_at)
               VALUES (?, 'trade', ?, ?, ?, ?, ?)""",
            (
                correction_id,
                trade.id,
                reason,
                json.dumps(before, ensure_ascii=False),
                json.dumps(after, ensure_ascii=False),
                created_at,
            ),
        )
    return {
        "id": correction_id,
        "entity_type": "trade",
        "entity_id": trade.id,
        "reason": reason,
        "before": before,
        "after": after,
        "created_at": created_at,
    }


# ---- CashEntry ----
def save_cash(entry: CashEntry) -> CashEntry:
    with store._lock, store._conn() as c:
        c.execute(
            """INSERT INTO ledger_cash
               (id, direction, amount, currency, ts, source, note)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.id,
                entry.direction,
                entry.amount,
                entry.currency,
                entry.ts,
                entry.source,
                entry.note,
            ),
        )
        c.commit()
    return entry


def list_cash(limit: int = 200) -> list[CashEntry]:
    with store._lock, store._conn() as c:
        rows = c.execute("SELECT * FROM ledger_cash ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    return [_cash_row(r) for r in rows]


def list_cash_page(*, limit: int = 200, cursor: str | None = None) -> dict:
    params: list = []
    sql = "SELECT * FROM ledger_cash"
    if cursor:
        cursor_value, cursor_id = store._decode_cursor(cursor)
        sql += " WHERE (ts < ? OR (ts = ? AND id < ?))"
        params.extend([cursor_value, cursor_value, cursor_id])
    sql += " ORDER BY ts DESC, id DESC LIMIT ?"
    params.append(limit + 1)
    with store._lock, store._conn() as c:
        total = int(c.execute("SELECT COUNT(*) AS total FROM ledger_cash").fetchone()["total"])
        rows = c.execute(sql, params).fetchall()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    return {
        "items": [_cash_row(row) for row in page_rows],
        "total": total,
        "next_cursor": (
            store._encode_cursor(float(page_rows[-1]["ts"]), str(page_rows[-1]["id"]))
            if has_more and page_rows
            else None
        ),
    }


def get_cash(entry_id: str) -> CashEntry | None:
    with store._lock, store._conn() as c:
        row = c.execute("SELECT * FROM ledger_cash WHERE id=?", (entry_id,)).fetchone()
    return _cash_row(row) if row else None


def correct_cash(entry: CashEntry, reason: str) -> dict | None:
    with store._lock, store._conn() as c:
        row = c.execute("SELECT * FROM ledger_cash WHERE id=?", (entry.id,)).fetchone()
        if row is None:
            return None
        before = _cash_row(row).to_dict()
        c.execute(
            """UPDATE ledger_cash SET direction=?, amount=?, currency=?, source=?, note=?
               WHERE id=?""",
            (entry.direction, entry.amount, entry.currency, entry.source, entry.note, entry.id),
        )
        after = entry.to_dict()
        correction_id = str(uuid.uuid4())
        created_at = time.time()
        c.execute(
            """INSERT INTO ledger_corrections
               (id, entity_type, entity_id, reason, before_json, after_json, created_at)
               VALUES (?, 'cash', ?, ?, ?, ?, ?)""",
            (
                correction_id,
                entry.id,
                reason,
                json.dumps(before, ensure_ascii=False),
                json.dumps(after, ensure_ascii=False),
                created_at,
            ),
        )
    return {
        "id": correction_id,
        "entity_type": "cash",
        "entity_id": entry.id,
        "reason": reason,
        "before": before,
        "after": after,
        "created_at": created_at,
    }


# ---- Benchmark ----
def save_benchmark(benchmark: Benchmark) -> Benchmark:
    with store._lock, store._conn() as c:
        c.execute(
            """INSERT INTO ledger_benchmarks
               (id, name, code, market, equity_curve, metrics, ts)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, code=excluded.code,
               market=excluded.market, equity_curve=excluded.equity_curve,
               metrics=excluded.metrics, ts=excluded.ts""",
            (
                benchmark.id,
                benchmark.name,
                benchmark.code,
                benchmark.market,
                json.dumps(benchmark.equity_curve),
                json.dumps(benchmark.metrics),
                benchmark.ts,
            ),
        )
        c.commit()
    return benchmark


def list_benchmarks() -> list[Benchmark]:
    with store._lock, store._conn() as c:
        rows = c.execute("SELECT * FROM ledger_benchmarks ORDER BY ts DESC").fetchall()
    return [_bench_row(r) for r in rows]


def get_benchmark(benchmark_id: str) -> Benchmark | None:
    with store._lock, store._conn() as c:
        row = c.execute("SELECT * FROM ledger_benchmarks WHERE id=?", (benchmark_id,)).fetchone()
    return _bench_row(row) if row else None


def correct_benchmark(benchmark: Benchmark, reason: str) -> dict | None:
    with store._lock, store._conn() as c:
        row = c.execute("SELECT * FROM ledger_benchmarks WHERE id=?", (benchmark.id,)).fetchone()
        if row is None:
            return None
        before = _bench_row(row).to_dict()
        c.execute(
            """UPDATE ledger_benchmarks SET name=?, code=?, market=?, equity_curve=?,
               metrics=? WHERE id=?""",
            (
                benchmark.name,
                benchmark.code,
                benchmark.market,
                json.dumps(benchmark.equity_curve, ensure_ascii=False),
                json.dumps(benchmark.metrics, ensure_ascii=False),
                benchmark.id,
            ),
        )
        after = benchmark.to_dict()
        correction_id = str(uuid.uuid4())
        created_at = time.time()
        c.execute(
            """INSERT INTO ledger_corrections
               (id, entity_type, entity_id, reason, before_json, after_json, created_at)
               VALUES (?, 'benchmark', ?, ?, ?, ?, ?)""",
            (
                correction_id,
                benchmark.id,
                reason,
                json.dumps(before, ensure_ascii=False),
                json.dumps(after, ensure_ascii=False),
                created_at,
            ),
        )
    return {
        "id": correction_id,
        "entity_type": "benchmark",
        "entity_id": benchmark.id,
        "reason": reason,
        "before": before,
        "after": after,
        "created_at": created_at,
    }


def list_corrections(
    entity_type: str | None = None, entity_id: str | None = None, limit: int = 200
) -> list[dict]:
    clauses: list[str] = []
    params: list[object] = []
    if entity_type:
        clauses.append("entity_type=?")
        params.append(entity_type)
    if entity_id:
        clauses.append("entity_id=?")
        params.append(entity_id)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with store._lock, store._conn() as c:
        rows = c.execute(
            f"SELECT * FROM ledger_corrections{where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [
        {
            "id": row["id"],
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "reason": row["reason"],
            "before": json.loads(row["before_json"]),
            "after": json.loads(row["after_json"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]
