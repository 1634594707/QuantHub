"""故障历史持久化。"""

from __future__ import annotations

import json
import time
import uuid

from apps.api import store


def observe_data_source_failure(
    source: str, operation: str, error: str, occurred_at: float
) -> dict:
    with store._lock, store._conn() as c:
        row = c.execute(
            """SELECT * FROM data_source_incidents
               WHERE source=? AND operation=? AND status='open'
               ORDER BY started_at DESC LIMIT 1""",
            (source, operation),
        ).fetchone()
        if row is None:
            incident_id = str(uuid.uuid4())
            c.execute(
                """INSERT INTO data_source_incidents
                   (id, source, operation, status, error, started_at, updated_at)
                   VALUES (?, ?, ?, 'open', ?, ?, ?)""",
                (incident_id, source, operation, error, occurred_at, occurred_at),
            )
        else:
            incident_id = row["id"]
            c.execute(
                """UPDATE data_source_incidents SET error=?, updated_at=? WHERE id=?""",
                (error, occurred_at, incident_id),
            )
    return get_data_source_incident(incident_id) or {}


def get_data_source_incident(incident_id: str) -> dict | None:
    with store._lock, store._conn() as c:
        row = c.execute("SELECT * FROM data_source_incidents WHERE id=?", (incident_id,)).fetchone()
    return _row(row) if row else None


def record_data_source_check(incident_id: str, result: dict) -> dict | None:
    now = time.time()
    with store._lock, store._conn() as c:
        row = c.execute("SELECT * FROM data_source_incidents WHERE id=?", (incident_id,)).fetchone()
        if row is None:
            return None
        status = "recovered" if result.get("ok") else "open"
        recovered_at = now if result.get("ok") else row["recovered_at"]
        error = row["error"] if result.get("ok") else str(result.get("error") or row["error"])
        c.execute(
            """UPDATE data_source_incidents
               SET status=?, error=?, recovered_at=?, last_check_json=?, updated_at=?
               WHERE id=?""",
            (status, error, recovered_at, json.dumps(result, ensure_ascii=False), now, incident_id),
        )
    return get_data_source_incident(incident_id)


def acknowledge_data_source_recovery(incident_id: str, resolution: str) -> dict | None:
    now = time.time()
    with store._lock, store._conn() as c:
        row = c.execute("SELECT * FROM data_source_incidents WHERE id=?", (incident_id,)).fetchone()
        if row is None or row["status"] != "recovered":
            return None
        c.execute(
            """UPDATE data_source_incidents
               SET status='acknowledged', acknowledged_at=?, resolution=?, updated_at=?
               WHERE id=?""",
            (now, resolution, now, incident_id),
        )
    return get_data_source_incident(incident_id)


def list_data_source_incidents(
    *, include_acknowledged: bool = True, limit: int = 200
) -> list[dict]:
    with store._lock, store._conn() as c:
        if include_acknowledged:
            rows = c.execute(
                "SELECT * FROM data_source_incidents ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = c.execute(
                """SELECT * FROM data_source_incidents WHERE status!='acknowledged'
                   ORDER BY updated_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
    return [_row(row) for row in rows]


def _row(row) -> dict:
    return {
        "id": row["id"],
        "source": row["source"],
        "operation": row["operation"],
        "status": row["status"],
        "error": row["error"],
        "started_at": row["started_at"],
        "recovered_at": row["recovered_at"],
        "acknowledged_at": row["acknowledged_at"],
        "resolution": row["resolution"],
        "last_check": json.loads(row["last_check_json"]) if row["last_check_json"] else None,
        "updated_at": row["updated_at"],
    }
