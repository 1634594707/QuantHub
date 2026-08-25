from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid

from apps.api import store


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def principal_by_token(token: str) -> dict | None:
    now = time.time()
    digest = token_hash(token)
    with store._lock, store._conn() as connection:
        row = connection.execute(
            """SELECT u.* FROM api_tokens t JOIN users u ON u.id=t.user_id
               WHERE t.token_hash=? AND t.revoked_at IS NULL AND u.active=1
               AND (t.expires_at IS NULL OR t.expires_at>?)""",
            (digest, now),
        ).fetchone()
        if row is None:
            return None
        connection.execute(
            "UPDATE api_tokens SET last_used_at=? WHERE token_hash=?",
            (now, digest),
        )
    return get_user(row["id"])


def get_user(user_id: str) -> dict | None:
    with store._lock, store._conn() as connection:
        row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None:
            return None
        roles = [
            item["name"]
            for item in connection.execute(
                """SELECT r.name FROM roles r JOIN user_roles ur ON ur.role_id=r.id
               WHERE ur.user_id=? ORDER BY r.name""",
                (user_id,),
            ).fetchall()
        ]
        permissions = [
            item["name"]
            for item in connection.execute(
                """SELECT DISTINCT p.name FROM permissions p
               JOIN role_permissions rp ON rp.permission_id=p.id
               JOIN user_roles ur ON ur.role_id=rp.role_id
               WHERE ur.user_id=? ORDER BY p.name""",
                (user_id,),
            ).fetchall()
        ]
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "active": bool(row["active"]),
        "created_at": row["created_at"],
        "roles": roles,
        "permissions": permissions,
    }


def list_users() -> list[dict]:
    with store._lock, store._conn() as connection:
        ids = [
            row["id"]
            for row in connection.execute("SELECT id FROM users ORDER BY username").fetchall()
        ]
    return [user for user_id in ids if (user := get_user(user_id)) is not None]


def list_roles() -> list[dict]:
    with store._lock, store._conn() as connection:
        roles = connection.execute("SELECT id, name FROM roles ORDER BY name").fetchall()
        result = []
        for role in roles:
            permissions = [
                row["name"]
                for row in connection.execute(
                    """SELECT p.name FROM permissions p
                   JOIN role_permissions rp ON rp.permission_id=p.id
                   WHERE rp.role_id=? ORDER BY p.name""",
                    (role["id"],),
                ).fetchall()
            ]
            result.append({"id": role["id"], "name": role["name"], "permissions": permissions})
    return result


def create_user(username: str, display_name: str, roles: list[str]) -> dict:
    user_id = str(uuid.uuid4())
    with store._lock, store._conn() as connection:
        known = {row["name"] for row in connection.execute("SELECT name FROM roles").fetchall()}
        unknown = sorted(set(roles) - known)
        if unknown:
            raise ValueError(f"未知角色: {', '.join(unknown)}")
        connection.execute(
            """INSERT INTO users (id, username, display_name, active, created_at)
               VALUES (?, ?, ?, 1, ?)""",
            (user_id, username.strip(), display_name.strip(), time.time()),
        )
        for role in sorted(set(roles)):
            connection.execute(
                "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
                (user_id, role),
            )
    return get_user(user_id) or {}


def update_roles(user_id: str, roles: list[str]) -> dict | None:
    with store._lock, store._conn() as connection:
        if connection.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone() is None:
            return None
        known = {row["name"] for row in connection.execute("SELECT name FROM roles").fetchall()}
        unknown = sorted(set(roles) - known)
        if unknown:
            raise ValueError(f"未知角色: {', '.join(unknown)}")
        connection.execute("DELETE FROM user_roles WHERE user_id=?", (user_id,))
        for role in sorted(set(roles)):
            connection.execute(
                "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", (user_id, role)
            )
    return get_user(user_id)


def set_user_active(user_id: str, active: bool) -> dict | None:
    now = time.time()
    with store._lock, store._conn() as connection:
        row = connection.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None:
            return None
        connection.execute("UPDATE users SET active=? WHERE id=?", (int(active), user_id))
        if not active:
            connection.execute(
                "UPDATE api_tokens SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                (now, user_id),
            )
    return get_user(user_id)


def create_token(user_id: str, label: str, expires_at: float | None) -> dict:
    if get_user(user_id) is None:
        raise ValueError("用户不存在")
    token = secrets.token_urlsafe(32)
    token_id = str(uuid.uuid4())
    created_at = time.time()
    with store._lock, store._conn() as connection:
        connection.execute(
            """INSERT INTO api_tokens
               (id, user_id, token_hash, label, expires_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (token_id, user_id, token_hash(token), label.strip(), expires_at, created_at),
        )
    return {
        "id": token_id,
        "user_id": user_id,
        "label": label.strip(),
        "token": token,
        "expires_at": expires_at,
        "created_at": created_at,
    }


def list_tokens() -> list[dict]:
    with store._lock, store._conn() as connection:
        rows = connection.execute(
            """SELECT t.id, t.user_id, u.username, t.label, t.expires_at,
                      t.last_used_at, t.created_at, t.revoked_at
               FROM api_tokens t JOIN users u ON u.id=t.user_id
               ORDER BY t.created_at DESC"""
        ).fetchall()
    return [
        {
            "id": row["id"],
            "user_id": row["user_id"],
            "username": row["username"],
            "label": row["label"],
            "expires_at": row["expires_at"],
            "last_used_at": row["last_used_at"],
            "created_at": row["created_at"],
            "revoked_at": row["revoked_at"],
        }
        for row in rows
    ]


def revoke_token(token_id: str) -> dict | None:
    revoked_at = time.time()
    with store._lock, store._conn() as connection:
        row = connection.execute(
            "SELECT id FROM api_tokens WHERE id=?",
            (token_id,),
        ).fetchone()
        if row is None:
            return None
        connection.execute(
            "UPDATE api_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
            (revoked_at, token_id),
        )
    return next((item for item in list_tokens() if item["id"] == token_id), None)


def add_audit(
    *,
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    before: dict | None = None,
    after: dict | None = None,
    result: str = "succeeded",
    error: str | None = None,
) -> dict:
    audit_id = str(uuid.uuid4())
    created_at = time.time()
    with store._lock, store._conn() as connection:
        connection.execute(
            """INSERT INTO audit_logs
               (id, actor_id, action, entity_type, entity_id, before_json, after_json,
                result, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                audit_id,
                actor_id,
                action,
                entity_type,
                entity_id,
                json.dumps(before, ensure_ascii=False) if before is not None else None,
                json.dumps(after, ensure_ascii=False) if after is not None else None,
                result,
                error,
                created_at,
            ),
        )
    return {
        "id": audit_id,
        "actor_id": actor_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "before": before,
        "after": after,
        "result": result,
        "error": error,
        "created_at": created_at,
    }


def list_audit(limit: int = 200) -> list[dict]:
    with store._lock, store._conn() as connection:
        rows = connection.execute(
            "SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "actor_id": row["actor_id"],
            "action": row["action"],
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "before": json.loads(row["before_json"]) if row["before_json"] else None,
            "after": json.loads(row["after_json"]) if row["after_json"] else None,
            "result": row["result"],
            "error": row["error"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def list_audit_page(*, limit: int = 200, cursor: str | None = None) -> dict:
    params: list = []
    sql = "SELECT * FROM audit_logs"
    if cursor:
        cursor_value, cursor_id = store._decode_cursor(cursor)
        sql += " WHERE (created_at < ? OR (created_at = ? AND id < ?))"
        params.extend([cursor_value, cursor_value, cursor_id])
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit + 1)
    with store._lock, store._conn() as connection:
        total = int(
            connection.execute("SELECT COUNT(*) AS total FROM audit_logs").fetchone()["total"]
        )
        rows = connection.execute(sql, params).fetchall()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    items = [
        {
            "id": row["id"],
            "actor_id": row["actor_id"],
            "action": row["action"],
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "before": json.loads(row["before_json"]) if row["before_json"] else None,
            "after": json.loads(row["after_json"]) if row["after_json"] else None,
            "result": row["result"],
            "error": row["error"],
            "created_at": row["created_at"],
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
