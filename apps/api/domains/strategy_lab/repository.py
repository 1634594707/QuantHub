"""策略实验室持久化层。"""

from __future__ import annotations

import json
import time
import uuid

from apps.api import store

from .domain import BacktestRun, Experiment, StrategyDefinition, StrategyVersion


def _def_row(row) -> StrategyDefinition:
    return StrategyDefinition(
        id=row["id"],
        name=row["name"],
        strategy_key=row["strategy_key"],
        market=row["market"],
        description=row["description"],
        tags=json.loads(row["tags"]) if row["tags"] else [],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        archived_at=row["archived_at"],
    )


def _ver_row(row) -> StrategyVersion:
    return StrategyVersion(
        id=row["id"],
        definition_id=row["definition_id"],
        version=row["version"],
        params=json.loads(row["params"]) if row["params"] else {},
        code_hash=row["code_hash"],
        changelog=row["changelog"],
        created_at=row["created_at"],
        archived_at=row["archived_at"],
    )


def _exp_row(row) -> Experiment:
    return Experiment(
        id=row["id"],
        definition_id=row["definition_id"],
        version_id=row["version_id"],
        instrument_id=row["instrument_id"],
        symbol=row["symbol"],
        market=row["market"],
        timeframe=row["timeframe"],
        research_run_id=row["research_run_id"],
        status=row["status"],
        params=json.loads(row["params"]) if row["params"] else {},
        note=row["note"],
        created_at=row["created_at"],
        updated_at=row["updated_at"] or row["created_at"],
        archived_at=row["archived_at"],
    )


def _run_row(row) -> BacktestRun:
    return BacktestRun(
        id=row["id"],
        experiment_id=row["experiment_id"],
        symbol=row["symbol"],
        market=row["market"],
        timeframe=row["timeframe"],
        params=json.loads(row["params"]) if row["params"] else {},
        data_snapshot=json.loads(row["data_snapshot"]) if row["data_snapshot"] else {},
        initial_capital=row["initial_capital"],
        equity_curve=json.loads(row["equity_curve"]) if row["equity_curve"] else [],
        trades=json.loads(row["trades"]) if row["trades"] else [],
        metrics=json.loads(row["metrics"]) if row["metrics"] else {},
        seed=row["seed"],
        status=row["status"],
        error=row["error"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


# ---- StrategyDefinition ----
def create_definition(
    name: str, strategy_key: str, market: str, description: str, tags: list[str]
) -> StrategyDefinition:
    now = time.time()
    definition = StrategyDefinition(
        id=str(uuid.uuid4()),
        name=name,
        strategy_key=strategy_key,
        market=market,
        description=description,
        tags=tags,
        created_at=now,
        updated_at=now,
    )
    with store._lock, store._conn() as c:
        c.execute(
            """INSERT INTO strategy_definitions (id, name, strategy_key, market, description, tags, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                definition.id,
                definition.name,
                definition.strategy_key,
                definition.market,
                definition.description,
                json.dumps(tags),
                now,
                now,
            ),
        )
        c.commit()
    return definition


def get_definition(definition_id: str) -> StrategyDefinition | None:
    with store._lock, store._conn() as c:
        row = c.execute(
            "SELECT * FROM strategy_definitions WHERE id=?", (definition_id,)
        ).fetchone()
    return _def_row(row) if row else None


def list_definitions(limit: int = 100, include_archived: bool = False) -> list[StrategyDefinition]:
    with store._lock, store._conn() as c:
        if include_archived:
            rows = c.execute(
                "SELECT * FROM strategy_definitions ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = c.execute(
                """SELECT * FROM strategy_definitions WHERE archived_at IS NULL
                   ORDER BY updated_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
    return [_def_row(r) for r in rows]


def update_definition(
    definition_id: str,
    *,
    name: str,
    strategy_key: str,
    market: str,
    description: str,
    tags: list[str],
) -> StrategyDefinition | None:
    now = time.time()
    with store._lock, store._conn() as c:
        c.execute(
            """UPDATE strategy_definitions SET name=?, strategy_key=?, market=?,
               description=?, tags=?, updated_at=? WHERE id=?""",
            (name, strategy_key, market, description, json.dumps(tags), now, definition_id),
        )
        row = c.execute(
            "SELECT * FROM strategy_definitions WHERE id=?", (definition_id,)
        ).fetchone()
    return _def_row(row) if row else None


def archive_definition(definition_id: str) -> StrategyDefinition | None:
    now = time.time()
    with store._lock, store._conn() as c:
        c.execute(
            "UPDATE strategy_definitions SET archived_at=?, updated_at=? WHERE id=?",
            (now, now, definition_id),
        )
        row = c.execute(
            "SELECT * FROM strategy_definitions WHERE id=?", (definition_id,)
        ).fetchone()
    return _def_row(row) if row else None


# ---- StrategyVersion ----
def create_version(
    definition_id: str, version: str, params: dict, code_hash: str, changelog: str
) -> StrategyVersion:
    now = time.time()
    vid = str(uuid.uuid4())
    with store._lock, store._conn() as c:
        c.execute(
            """INSERT INTO strategy_versions (id, definition_id, version, params, code_hash, changelog, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (vid, definition_id, version, json.dumps(params), code_hash, changelog, now),
        )
        c.execute("UPDATE strategy_definitions SET updated_at=? WHERE id=?", (now, definition_id))
        c.commit()
    return StrategyVersion(
        id=vid,
        definition_id=definition_id,
        version=version,
        params=params,
        code_hash=code_hash,
        changelog=changelog,
        created_at=now,
    )


def get_version(version_id: str) -> StrategyVersion | None:
    with store._lock, store._conn() as c:
        row = c.execute("SELECT * FROM strategy_versions WHERE id=?", (version_id,)).fetchone()
    return _ver_row(row) if row else None


def list_versions(definition_id: str, include_archived: bool = False) -> list[StrategyVersion]:
    with store._lock, store._conn() as c:
        if include_archived:
            rows = c.execute(
                "SELECT * FROM strategy_versions WHERE definition_id=? ORDER BY created_at DESC",
                (definition_id,),
            ).fetchall()
        else:
            rows = c.execute(
                """SELECT * FROM strategy_versions
                   WHERE definition_id=? AND archived_at IS NULL ORDER BY created_at DESC""",
                (definition_id,),
            ).fetchall()
    return [_ver_row(r) for r in rows]


def update_version(
    version_id: str, *, version: str, params: dict, code_hash: str, changelog: str
) -> StrategyVersion | None:
    with store._lock, store._conn() as c:
        c.execute(
            """UPDATE strategy_versions SET version=?, params=?, code_hash=?, changelog=?
               WHERE id=?""",
            (version, json.dumps(params), code_hash, changelog, version_id),
        )
        row = c.execute("SELECT * FROM strategy_versions WHERE id=?", (version_id,)).fetchone()
        if row:
            c.execute(
                "UPDATE strategy_definitions SET updated_at=? WHERE id=?",
                (time.time(), row["definition_id"]),
            )
    return _ver_row(row) if row else None


def archive_version(version_id: str) -> StrategyVersion | None:
    with store._lock, store._conn() as c:
        c.execute(
            "UPDATE strategy_versions SET archived_at=? WHERE id=?", (time.time(), version_id)
        )
        row = c.execute("SELECT * FROM strategy_versions WHERE id=?", (version_id,)).fetchone()
    return _ver_row(row) if row else None


# ---- Experiment ----
def create_experiment(
    definition_id: str,
    instrument_id: str,
    symbol: str,
    market: str,
    timeframe: str,
    version_id: str | None,
    research_run_id: str | None,
    params: dict,
    note: str,
) -> Experiment:
    now = time.time()
    eid = str(uuid.uuid4())
    with store._lock, store._conn() as c:
        c.execute(
            """INSERT INTO experiments (id, definition_id, version_id, research_run_id, instrument_id, symbol, market, timeframe, status, params, note, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)""",
            (
                eid,
                definition_id,
                version_id,
                research_run_id,
                instrument_id,
                symbol,
                market,
                timeframe,
                json.dumps(params),
                note,
                now,
                now,
            ),
        )
        c.commit()
    return Experiment(
        id=eid,
        definition_id=definition_id,
        version_id=version_id,
        instrument_id=instrument_id,
        symbol=symbol,
        market=market,
        timeframe=timeframe,
        research_run_id=research_run_id,
        params=params,
        note=note,
        created_at=now,
        updated_at=now,
    )


def get_experiment(experiment_id: str) -> Experiment | None:
    with store._lock, store._conn() as c:
        row = c.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone()
    return _exp_row(row) if row else None


def list_experiments(
    definition_id: str | None = None, limit: int = 100, include_archived: bool = False
) -> list[Experiment]:
    with store._lock, store._conn() as c:
        if definition_id:
            where = "definition_id=?" + ("" if include_archived else " AND archived_at IS NULL")
            rows = c.execute(
                f"SELECT * FROM experiments WHERE {where} ORDER BY created_at DESC LIMIT ?",
                (definition_id, limit),
            ).fetchall()
        else:
            where = "" if include_archived else " WHERE archived_at IS NULL"
            rows = c.execute(
                f"SELECT * FROM experiments{where} ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return [_exp_row(r) for r in rows]


def update_experiment(
    experiment_id: str,
    *,
    symbol: str,
    market: str,
    timeframe: str,
    instrument_id: str,
    version_id: str | None,
    research_run_id: str | None,
    params: dict,
    note: str,
) -> Experiment | None:
    now = time.time()
    with store._lock, store._conn() as c:
        c.execute(
            """UPDATE experiments SET instrument_id=?, symbol=?, market=?, timeframe=?, version_id=?,
               research_run_id=?, params=?, note=?, updated_at=? WHERE id=?""",
            (
                instrument_id,
                symbol,
                market,
                timeframe,
                version_id,
                research_run_id,
                json.dumps(params),
                note,
                now,
                experiment_id,
            ),
        )
        row = c.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone()
    return _exp_row(row) if row else None


def archive_experiment(experiment_id: str) -> Experiment | None:
    now = time.time()
    with store._lock, store._conn() as c:
        c.execute(
            "UPDATE experiments SET archived_at=?, updated_at=? WHERE id=?",
            (now, now, experiment_id),
        )
        row = c.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone()
    return _exp_row(row) if row else None


def update_experiment_status(experiment_id: str, status: str) -> None:
    with store._lock, store._conn() as c:
        c.execute(
            "UPDATE experiments SET status=?, updated_at=? WHERE id=?",
            (status, time.time(), experiment_id),
        )
        c.commit()


# ---- BacktestRun ----
def save_run(run: BacktestRun) -> BacktestRun:
    with store._lock, store._conn() as c:
        c.execute(
            """INSERT INTO backtest_runs
               (id, experiment_id, symbol, market, timeframe, params, data_snapshot,
                initial_capital, equity_curve, trades, metrics, seed, status, error,
                started_at, finished_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run.id,
                run.experiment_id,
                run.symbol,
                run.market,
                run.timeframe,
                json.dumps(run.params),
                json.dumps(run.data_snapshot),
                run.initial_capital,
                json.dumps(run.equity_curve),
                json.dumps(run.trades),
                json.dumps(run.metrics),
                run.seed,
                run.status,
                run.error,
                run.started_at,
                run.finished_at,
            ),
        )
        c.commit()
    return run


def get_run(run_id: str) -> BacktestRun | None:
    with store._lock, store._conn() as c:
        row = c.execute("SELECT * FROM backtest_runs WHERE id=?", (run_id,)).fetchone()
    return _run_row(row) if row else None


def list_runs(experiment_id: str) -> list[BacktestRun]:
    with store._lock, store._conn() as c:
        rows = c.execute(
            "SELECT * FROM backtest_runs WHERE experiment_id=? ORDER BY started_at DESC",
            (experiment_id,),
        ).fetchall()
    return [_run_row(r) for r in rows]
