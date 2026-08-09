"""Backup, verify, restore, and retention tooling for one product database."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from packages.research_protocol import canonical_json


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(path: Path) -> dict:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        table_rows = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        logical: dict[str, dict] = {}
        for table in table_rows:
            name = table["name"]
            rows = [
                {
                    key: (value.hex() if isinstance(value, bytes) else value)
                    for key, value in dict(row).items()
                }
                for row in connection.execute(f'SELECT * FROM "{name}"').fetchall()
            ]
            logical[name] = {
                "schema": table["sql"],
                "rows": sorted(rows, key=canonical_json),
            }
    finally:
        connection.close()
    return {
        "path": str(path.resolve()),
        "sha256": file_hash(path),
        "logical_sha256": hashlib.sha256(canonical_json(logical).encode("utf-8")).hexdigest(),
        "integrity": integrity,
        "tables": len(table_rows),
        "verified": integrity == "ok",
    }


def backup(source: Path, directory: Path, product: str) -> dict:
    report = verify(source)
    if not report["verified"]:
        raise RuntimeError("source database integrity check failed")
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = directory / f"{product}-{stamp}.db"
    source_connection = sqlite3.connect(source)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()
    target_report = verify(target)
    manifest = target.with_suffix(".json")
    manifest.write_text(
        json.dumps(target_report | {"product": product}, indent=2), encoding="utf-8"
    )
    return target_report | {"manifest": str(manifest)}


def restore(backup_path: Path, target: Path, *, confirmed: bool) -> dict:
    if not confirmed:
        raise ValueError("restore requires --yes")
    report = verify(backup_path)
    if not report["verified"]:
        raise RuntimeError("backup integrity check failed")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        safety = target.with_suffix(target.suffix + ".before-restore")
        shutil.copy2(target, safety)
    shutil.copy2(backup_path, target)
    return verify(target) | {"restored_from": str(backup_path.resolve())}


def prune(directory: Path, days: int, *, apply: bool) -> dict:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    candidates = [
        path
        for path in directory.glob("*.db")
        if datetime.fromtimestamp(path.stat().st_mtime, UTC) < cutoff
    ]
    if apply:
        for path in candidates:
            path.unlink()
            manifest = path.with_suffix(".json")
            if manifest.exists():
                manifest.unlink()
    return {"candidates": [str(path) for path in candidates], "applied": apply}


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("source", type=Path)
    backup_parser.add_argument("directory", type=Path)
    backup_parser.add_argument("--product", required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("path", type=Path)
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("backup", type=Path)
    restore_parser.add_argument("target", type=Path)
    restore_parser.add_argument("--yes", action="store_true")
    prune_parser = subparsers.add_parser("prune")
    prune_parser.add_argument("directory", type=Path)
    prune_parser.add_argument("--days", type=int, default=30)
    prune_parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.command == "backup":
        result = backup(args.source, args.directory, args.product)
    elif args.command == "verify":
        result = verify(args.path)
    elif args.command == "restore":
        result = restore(args.backup, args.target, confirmed=args.yes)
    else:
        result = prune(args.directory, args.days, apply=args.apply)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
