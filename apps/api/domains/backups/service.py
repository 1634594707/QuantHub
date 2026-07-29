"""受控 SQLite 备份目录的应用服务。"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from apps.api import database, store
from tools.backup_store import (
    backup_database,
    prune_backups,
    restore_database,
    verify_database,
)

BACKUP_DIR = (
    Path(os.environ.get("QUANTHUB_BACKUP_DIR", store._DB.parent / "backups")).expanduser().resolve()
)


def _require_sqlite() -> None:
    if database.is_postgresql(store._DB):
        raise ValueError("PostgreSQL 模式不支持 SQLite 文件备份接口")


def _backup_path(name: str) -> Path:
    if not name or Path(name).name != name or not name.endswith(".db"):
        raise ValueError("备份名称必须是备份目录内的 .db 文件名")
    path = (BACKUP_DIR / name).resolve()
    if path.parent != BACKUP_DIR:
        raise ValueError("备份文件必须位于受控备份目录")
    return path


def _metadata(path: Path) -> dict:
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "modified_at": stat.st_mtime,
    }


def list_backups() -> dict:
    if database.is_postgresql(store._DB):
        return {"ok": True, "supported": False, "count": 0, "backups": []}
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    items = sorted(
        (_metadata(path) for path in BACKUP_DIR.glob("*.db") if path.is_file()),
        key=lambda item: (item["modified_at"], item["name"]),
        reverse=True,
    )
    return {"ok": True, "count": len(items), "backups": items}


def status() -> dict:
    if database.is_postgresql(store._DB):
        return {
            "ok": True,
            "supported": False,
            "source_path": "postgresql",
            "source_exists": True,
            "backup_directory": "",
            "backup_count": 0,
            "latest_backup": None,
        }
    listed = list_backups()
    return {
        "ok": True,
        "supported": True,
        "source_path": str(store._DB.resolve()),
        "source_exists": store._DB.is_file(),
        "backup_directory": str(BACKUP_DIR),
        "backup_count": listed["count"],
        "latest_backup": listed["backups"][0] if listed["backups"] else None,
    }


def create_backup(*, actor: str) -> dict:
    _require_sqlite()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    destination = _backup_path(f"store-{timestamp}.db")
    with store._lock:
        result = backup_database(store._DB, destination)
    return {"ok": True, "actor": actor, "backup": _metadata(destination), "verification": result}


def verify_backup(name: str, *, actor: str) -> dict:
    _require_sqlite()
    path = _backup_path(name)
    result = verify_database(path)
    return {"ok": result["ok"], "actor": actor, "backup": _metadata(path), "verification": result}


def restore_backup(name: str, *, confirm_name: str, actor: str) -> dict:
    _require_sqlite()
    if confirm_name != name:
        raise ValueError("confirm_name 必须与目标备份名称完全一致")
    path = _backup_path(name)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    safety_backup = _backup_path(f"store-pre-restore-{timestamp}.db")
    with store._lock:
        # Windows does not allow replacing a SQLite file while a pooled
        # SQLAlchemy connection still owns a file handle.
        database.dispose_engines()
        result = restore_database(
            path,
            store._DB,
            replace=True,
            safety_backup=safety_backup,
        )
    return {
        "ok": result["ok"],
        "actor": actor,
        "restored_from": _metadata(path),
        "safety_backup": _metadata(safety_backup),
        "result": result,
    }


def retention_preview(*, keep: int, actor: str) -> dict:
    _require_sqlite()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    result = prune_backups(BACKUP_DIR, keep=keep, pattern="*.db", apply=False)
    return {**result, "actor": actor}


def retention_apply(*, keep: int, confirm_files: list[str], actor: str) -> dict:
    _require_sqlite()
    preview = retention_preview(keep=keep, actor=actor)
    if confirm_files != preview["candidates"]:
        raise ValueError("confirm_files 必须与当前保留策略预览结果完全一致")
    result = prune_backups(BACKUP_DIR, keep=keep, pattern="*.db", apply=True)
    return {**result, "actor": actor}
