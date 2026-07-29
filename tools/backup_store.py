"""Create and verify consistent backups of the QuantHub application database."""

from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path


def verify_database(path: Path) -> dict[str, int | str | bool]:
    """Run SQLite integrity checks and return basic backup metadata."""
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"数据库不存在: {resolved}")
    with closing(sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)) as conn:
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        table_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchone()[0]
        )
    return {
        "ok": integrity == "ok",
        "integrity": integrity,
        "table_count": table_count,
        "bytes": resolved.stat().st_size,
    }


def backup_database(source: Path, destination: Path, *, overwrite: bool = False) -> dict:
    """Create an atomic, transaction-consistent SQLite backup."""
    source_path = source.resolve()
    destination_path = destination.resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"源数据库不存在: {source_path}")
    if source_path == destination_path:
        raise ValueError("备份目标不能与源数据库相同")
    if destination_path.exists() and not overwrite:
        raise FileExistsError(f"备份已存在: {destination_path}")

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination_path.with_name(f".{destination_path.name}.tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        with closing(sqlite3.connect(str(source_path))) as source_conn:
            with closing(sqlite3.connect(str(temporary))) as backup_conn:
                source_conn.backup(backup_conn)
        verification = verify_database(temporary)
        if not verification["ok"]:
            raise RuntimeError(f"备份完整性校验失败: {verification['integrity']}")
        temporary.replace(destination_path)
    finally:
        if temporary.exists():
            temporary.unlink()

    return {"source": str(source_path), "destination": str(destination_path), **verification}


def restore_database(
    backup: Path,
    target: Path,
    *,
    replace: bool = False,
    safety_backup: Path | None = None,
) -> dict:
    """Verify and atomically restore a backup, preserving the current target first."""
    backup_path = backup.resolve()
    target_path = target.resolve()
    if backup_path == target_path:
        raise ValueError("恢复源不能与目标数据库相同")
    verification = verify_database(backup_path)
    if not verification["ok"]:
        raise RuntimeError(f"恢复源完整性校验失败: {verification['integrity']}")
    if target_path.exists() and not replace:
        raise FileExistsError("目标数据库已存在；恢复覆盖必须显式启用 replace")

    preserved: Path | None = None
    if target_path.exists():
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        preserved = (
            safety_backup.resolve()
            if safety_backup is not None
            else target_path.with_name(
                f"{target_path.stem}.pre-restore-{timestamp}{target_path.suffix}"
            )
        )
        backup_database(target_path, preserved)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = target_path.with_name(f".{target_path.name}.restore.tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        backup_database(backup_path, temporary, overwrite=True)
        temporary.replace(target_path)
    finally:
        if temporary.exists():
            temporary.unlink()

    restored = verify_database(target_path)
    return {
        "source": str(backup_path),
        "target": str(target_path),
        "safety_backup": str(preserved) if preserved else None,
        **restored,
    }


def prune_backups(
    directory: Path,
    *,
    keep: int,
    pattern: str = "store-*.db",
    apply: bool = False,
) -> dict:
    """Keep the newest matching backups; default to a non-destructive preview."""
    if keep < 1:
        raise ValueError("keep 必须大于等于 1")
    root = directory.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"备份目录不存在: {root}")
    matches = sorted(
        (path for path in root.glob(pattern) if path.is_file()),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    candidates = matches[keep:]
    for path in candidates:
        resolved = path.resolve()
        if resolved.parent != root:
            raise ValueError(f"拒绝删除备份目录之外的文件: {resolved}")
        if apply:
            resolved.unlink()
    return {
        "ok": True,
        "directory": str(root),
        "keep": keep,
        "matched": len(matches),
        "deleted": len(candidates) if apply else 0,
        "candidates": [str(path.resolve()) for path in candidates],
        "dry_run": not apply,
    }


def _default_source() -> Path:
    from apps.api.store import _DB

    return _DB


def main() -> int:
    parser = argparse.ArgumentParser(description="QuantHub SQLite backup utility")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup", help="create a consistent backup")
    backup_parser.add_argument("--source", type=Path, default=None)
    backup_parser.add_argument("--output", type=Path, required=True)
    backup_parser.add_argument("--overwrite", action="store_true")

    verify_parser = subparsers.add_parser("verify", help="verify a database backup")
    verify_parser.add_argument("path", type=Path)

    restore_parser = subparsers.add_parser("restore", help="restore a verified backup")
    restore_parser.add_argument("backup", type=Path)
    restore_parser.add_argument("--target", type=Path, default=None)
    restore_parser.add_argument("--safety-backup", type=Path, default=None)
    restore_parser.add_argument("--yes", action="store_true", help="confirm replacing target")

    prune_parser = subparsers.add_parser("prune", help="preview or apply backup retention")
    prune_parser.add_argument("directory", type=Path)
    prune_parser.add_argument("--keep", type=int, required=True)
    prune_parser.add_argument("--pattern", default="store-*.db")
    prune_parser.add_argument("--apply", action="store_true")

    args = parser.parse_args()
    if args.command == "backup":
        result = backup_database(
            args.source or _default_source(), args.output, overwrite=args.overwrite
        )
    elif args.command == "verify":
        result = verify_database(args.path)
    elif args.command == "restore":
        result = restore_database(
            args.backup,
            args.target or _default_source(),
            replace=args.yes,
            safety_backup=args.safety_backup,
        )
    else:
        result = prune_backups(
            args.directory,
            keep=args.keep,
            pattern=args.pattern,
            apply=args.apply,
        )
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
