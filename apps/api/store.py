"""轻量应用态持久化层。

职责：策略参数预设、策略运行历史、组合配置。
- 单文件 SQLite（WAL），线程安全，复用 core 既有的 SQLite 模式。
- 与行情缓存（core/data_feed/cache.py）隔离，专供应用业务态。
- 所有写操作幂等、带唯一 id，便于前端乐观更新与回查。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

_DB = Path(__file__).resolve().parent / "store.db"
_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    _DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init() -> None:
    with _lock, _conn() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS strategy_presets (
                id TEXT PRIMARY KEY,
                strategy TEXT NOT NULL,
                name TEXT NOT NULL,
                params TEXT NOT NULL,
                ts REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS strategy_runs (
                id TEXT PRIMARY KEY,
                strategy TEXT NOT NULL,
                params TEXT NOT NULL,
                result TEXT NOT NULL,
                ts REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS portfolio_allocs (
                id TEXT PRIMARY KEY,
                strategy TEXT NOT NULL,
                weight REAL NOT NULL,
                symbol TEXT,
                live INTEGER NOT NULL DEFAULT 0,
                note TEXT,
                ts REAL NOT NULL
            )"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_presets_strategy ON strategy_presets(strategy)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_runs_strategy ON strategy_runs(strategy)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_allocs_strategy ON portfolio_allocs(strategy)")


_init()


def _now() -> float:
    return time.time()


# ---------------------------------------------------------------------------
# 预设 presets
# ---------------------------------------------------------------------------
def list_presets() -> dict[str, list[dict]]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT id, strategy, name, params, ts FROM strategy_presets ORDER BY ts DESC"
        ).fetchall()
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["strategy"], []).append(
            {"id": r["id"], "name": r["name"], "params": json.loads(r["params"])}
        )
    return out


def save_preset(strategy: str, name: str, params: dict) -> dict:
    pid = uuid.uuid4().hex[:12]
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO strategy_presets (id, strategy, name, params, ts) VALUES (?,?,?,?,?)",
            (pid, strategy, name, json.dumps(params, ensure_ascii=False), _now()),
        )
    return {"id": pid, "name": name, "params": params}


def delete_preset(strategy: str, pid: str) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM strategy_presets WHERE id=? AND strategy=?", (pid, strategy))


# ---------------------------------------------------------------------------
# 运行历史 runs
# ---------------------------------------------------------------------------
def list_runs(limit: int = 500) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT id, strategy, params, result, ts FROM strategy_runs ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "name": r["strategy"],
            "params": json.loads(r["params"]),
            "result": json.loads(r["result"]),
            "ts": r["ts"],
        }
        for r in rows
    ]


def add_run(strategy: str, params: dict, result: dict) -> dict:
    rid = uuid.uuid4().hex[:12]
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO strategy_runs (id, strategy, params, result, ts) VALUES (?,?,?,?,?)",
            (
                rid,
                strategy,
                json.dumps(params, ensure_ascii=False),
                json.dumps(result, ensure_ascii=False, default=str),
                _now(),
            ),
        )
    return {"id": rid, "name": strategy, "params": params, "result": result, "ts": _now()}


def clear_runs() -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM strategy_runs")


# ---------------------------------------------------------------------------
# 组合配置 portfolio
# ---------------------------------------------------------------------------
def list_allocs() -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT id, strategy, weight, symbol, live, note, ts FROM portfolio_allocs ORDER BY ts DESC"
        ).fetchall()
    return [
        {
            "id": r["id"],
            "strategy": r["strategy"],
            "weight": r["weight"],
            "symbol": r["symbol"],
            "live": bool(r["live"]),
            "note": r["note"],
        }
        for r in rows
    ]


def save_alloc(
    strategy: str, weight: float, symbol: str | None, live: bool, note: str | None
) -> dict:
    aid = uuid.uuid4().hex[:12]
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO portfolio_allocs (id, strategy, weight, symbol, live, note, ts) VALUES (?,?,?,?,?,?,?)",
            (aid, strategy, float(weight), symbol, int(bool(live)), note, _now()),
        )
    return {
        "id": aid,
        "strategy": strategy,
        "weight": float(weight),
        "symbol": symbol,
        "live": bool(live),
        "note": note,
    }


def delete_alloc(aid: str) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM portfolio_allocs WHERE id=?", (aid,))


def update_alloc_live(aid: str, live: bool) -> None:
    with _lock, _conn() as c:
        c.execute("UPDATE portfolio_allocs SET live=? WHERE id=?", (int(bool(live)), aid))
