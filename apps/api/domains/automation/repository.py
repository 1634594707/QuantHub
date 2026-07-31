from __future__ import annotations

import json
import time
import uuid

from apps.api import store


def list_overrides() -> dict[str, dict]:
    with store._lock, store._conn() as connection:
        rows = connection.execute("SELECT * FROM automation_job_overrides").fetchall()
    return {
        row["name"]: {
            "name": row["name"],
            "enabled": bool(row["enabled"]),
            "cron": row["cron"],
            "updated_at": float(row["updated_at"]),
            "updated_by": row["updated_by"],
        }
        for row in rows
    }


def save_override(name: str, *, enabled: bool, cron: str, actor: str) -> dict:
    now = time.time()
    with store._lock, store._conn() as connection:
        connection.execute(
            """INSERT INTO automation_job_overrides
               (name, enabled, cron, updated_at, updated_by)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                 enabled=excluded.enabled,
                 cron=excluded.cron,
                 updated_at=excluded.updated_at,
                 updated_by=excluded.updated_by""",
            (name, int(enabled), cron, now, actor),
        )
    return {
        "name": name,
        "enabled": enabled,
        "cron": cron,
        "updated_at": now,
        "updated_by": actor,
    }


def _factor_job_dict(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "universe_id": row["universe_id"],
        "cron": row["cron"],
        "enabled": bool(row["enabled"]),
        "request": json.loads(row["request_json"]),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "updated_by": row["updated_by"],
    }


def create_factor_research_job(
    *, name: str, universe_id: str, cron: str, enabled: bool, request: dict, actor: str
) -> dict:
    job_id = f"FACTOR-{uuid.uuid4().hex[:12].upper()}"
    now = time.time()
    with store._lock, store._conn() as connection:
        connection.execute(
            """INSERT INTO factor_research_jobs
               (id, name, universe_id, cron, enabled, request_json, created_at, updated_at,
                updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                name,
                universe_id,
                cron,
                int(enabled),
                json.dumps(request, ensure_ascii=False),
                now,
                now,
                actor,
            ),
        )
        row = connection.execute(
            "SELECT * FROM factor_research_jobs WHERE id=?", (job_id,)
        ).fetchone()
    return _factor_job_dict(row)


def list_factor_research_jobs() -> list[dict]:
    with store._lock, store._conn() as connection:
        rows = connection.execute(
            "SELECT * FROM factor_research_jobs ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [_factor_job_dict(row) for row in rows]


def get_factor_research_job(job_id: str) -> dict | None:
    with store._lock, store._conn() as connection:
        row = connection.execute(
            "SELECT * FROM factor_research_jobs WHERE id=?", (job_id,)
        ).fetchone()
    return _factor_job_dict(row) if row else None


def update_factor_research_job(job_id: str, patch: dict, actor: str) -> dict | None:
    allowed = {"name", "cron", "enabled", "request", "universe_id"}
    values = {key: value for key, value in patch.items() if key in allowed}
    if not values:
        return get_factor_research_job(job_id)
    assignments: list[str] = []
    params: list = []
    for key, value in values.items():
        column = "request_json" if key == "request" else key
        if key == "request":
            value = json.dumps(value, ensure_ascii=False)
        if key == "enabled":
            value = int(value)
        assignments.append(f"{column}=?")
        params.append(value)
    assignments.extend(["updated_at=?", "updated_by=?"])
    params.extend([time.time(), actor, job_id])
    with store._lock, store._conn() as connection:
        result = connection.execute(
            f"UPDATE factor_research_jobs SET {', '.join(assignments)} WHERE id=?", params
        )
    return get_factor_research_job(job_id) if result.rowcount else None


def create_run(
    job_name: str,
    *,
    trigger_type: str,
    attempt: int = 1,
    parent_run_id: str | None = None,
) -> dict:
    run_id = f"AUTO-{uuid.uuid4().hex[:12].upper()}"
    now = time.time()
    with store._lock, store._conn() as connection:
        connection.execute(
            """INSERT INTO automation_runs
               (id, job_name, status, trigger_type, attempt, parent_run_id, created_at)
               VALUES (?, ?, 'queued', ?, ?, ?, ?)""",
            (run_id, job_name, trigger_type, attempt, parent_run_id, now),
        )
    return get_run(run_id)


def _run_dict(row) -> dict:
    return {
        "id": row["id"],
        "job_name": row["job_name"],
        "status": row["status"],
        "trigger_type": row["trigger_type"],
        "attempt": int(row["attempt"]),
        "parent_run_id": row["parent_run_id"],
        "log": row["log"],
        "error": row["error"],
        "created_at": float(row["created_at"]),
        "started_at": float(row["started_at"]) if row["started_at"] is not None else None,
        "finished_at": float(row["finished_at"]) if row["finished_at"] is not None else None,
        "duration_ms": row["duration_ms"],
        "result_type": row["result_type"],
        "result_id": row["result_id"],
        "acknowledged_at": (
            float(row["acknowledged_at"]) if row["acknowledged_at"] is not None else None
        ),
        "acknowledged_by": row["acknowledged_by"],
    }


def get_run(run_id: str) -> dict | None:
    with store._lock, store._conn() as connection:
        row = connection.execute(
            "SELECT * FROM automation_runs WHERE id=?",
            (run_id,),
        ).fetchone()
    return _run_dict(row) if row else None


def list_runs(
    *,
    job_name: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict]:
    sql = "SELECT * FROM automation_runs"
    clauses: list[str] = []
    params: list = []
    if job_name:
        clauses.append("job_name=?")
        params.append(job_name)
    if status:
        clauses.append("status=?")
        params.append(status)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with store._lock, store._conn() as connection:
        rows = connection.execute(sql, params).fetchall()
    return [_run_dict(row) for row in rows]


def list_runs_page(
    *,
    job_name: str | None = None,
    status: str | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> dict:
    clauses: list[str] = []
    params: list = []
    if job_name:
        clauses.append("job_name=?")
        params.append(job_name)
    if status:
        clauses.append("status=?")
        params.append(status)
    count_sql = "SELECT COUNT(*) AS total FROM automation_runs"
    if clauses:
        count_sql += " WHERE " + " AND ".join(clauses)
    page_clauses = list(clauses)
    page_params = list(params)
    if cursor:
        cursor_value, cursor_id = store._decode_cursor(cursor)
        page_clauses.append("(created_at < ? OR (created_at = ? AND id < ?))")
        page_params.extend([cursor_value, cursor_value, cursor_id])
    sql = "SELECT * FROM automation_runs"
    if page_clauses:
        sql += " WHERE " + " AND ".join(page_clauses)
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    page_params.append(limit + 1)
    with store._lock, store._conn() as connection:
        total = int(connection.execute(count_sql, params).fetchone()["total"])
        rows = connection.execute(sql, page_params).fetchall()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    return {
        "items": [_run_dict(row) for row in page_rows],
        "total": total,
        "next_cursor": (
            store._encode_cursor(float(page_rows[-1]["created_at"]), str(page_rows[-1]["id"]))
            if has_more and page_rows
            else None
        ),
    }


def find_active_run(job_name: str, trigger_type: str) -> dict | None:
    with store._lock, store._conn() as connection:
        row = connection.execute(
            """SELECT * FROM automation_runs
               WHERE job_name=? AND trigger_type=? AND status IN ('queued', 'running')
               ORDER BY created_at DESC LIMIT 1""",
            (job_name, trigger_type),
        ).fetchone()
    return _run_dict(row) if row else None


def update_run(run_id: str, patch: dict) -> dict | None:
    allowed = {
        "status",
        "log",
        "error",
        "started_at",
        "finished_at",
        "duration_ms",
        "result_type",
        "result_id",
        "acknowledged_at",
        "acknowledged_by",
    }
    values = {key: value for key, value in patch.items() if key in allowed}
    if not values:
        return get_run(run_id)
    assignments = ", ".join(f"{key}=?" for key in values)
    with store._lock, store._conn() as connection:
        connection.execute(
            f"UPDATE automation_runs SET {assignments} WHERE id=?",
            (*values.values(), run_id),
        )
    return get_run(run_id)


def add_audit(
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    actor: str,
    before: dict | None,
    after: dict | None,
    result: str,
    error: str | None = None,
) -> dict:
    audit_id = f"AUD-{uuid.uuid4().hex[:12].upper()}"
    now = time.time()
    with store._lock, store._conn() as connection:
        connection.execute(
            """INSERT INTO automation_audit_logs
               (id, action, entity_type, entity_id, actor, before_json, after_json,
                result, error, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                audit_id,
                action,
                entity_type,
                entity_id,
                actor,
                json.dumps(before, ensure_ascii=False) if before is not None else None,
                json.dumps(after, ensure_ascii=False) if after is not None else None,
                result,
                error,
                now,
            ),
        )
    return {
        "id": audit_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "actor": actor,
        "before": before,
        "after": after,
        "result": result,
        "error": error,
        "created_at": now,
    }


def list_audit(limit: int = 100) -> list[dict]:
    with store._lock, store._conn() as connection:
        rows = connection.execute(
            "SELECT * FROM automation_audit_logs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "action": row["action"],
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "actor": row["actor"],
            "before": json.loads(row["before_json"]) if row["before_json"] else None,
            "after": json.loads(row["after_json"]) if row["after_json"] else None,
            "result": row["result"],
            "error": row["error"],
            "created_at": float(row["created_at"]),
        }
        for row in rows
    ]


def list_audit_page(*, limit: int = 100, cursor: str | None = None) -> dict:
    params: list = []
    sql = "SELECT * FROM automation_audit_logs"
    if cursor:
        cursor_value, cursor_id = store._decode_cursor(cursor)
        sql += " WHERE (created_at < ? OR (created_at = ? AND id < ?))"
        params.extend([cursor_value, cursor_value, cursor_id])
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit + 1)
    with store._lock, store._conn() as connection:
        total = int(
            connection.execute("SELECT COUNT(*) AS total FROM automation_audit_logs").fetchone()[
                "total"
            ]
        )
        rows = connection.execute(sql, params).fetchall()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    items = [
        {
            "id": row["id"],
            "action": row["action"],
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "actor": row["actor"],
            "before": json.loads(row["before_json"]) if row["before_json"] else None,
            "after": json.loads(row["after_json"]) if row["after_json"] else None,
            "result": row["result"],
            "error": row["error"],
            "created_at": float(row["created_at"]),
        }
        for row in page_rows
    ]
    return {
        "items": items,
        "total": total,
        "next_cursor": (
            store._encode_cursor(float(page_rows[-1]["created_at"]), str(page_rows[-1]["id"]))
            if has_more and page_rows
            else None
        ),
    }
