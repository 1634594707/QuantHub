"""清理由「未隔离的后端门禁」写入主库的审计残留（复核问题 P1 的善后）。

背景
----
在 ``tests/__init__.py`` 引入数据库隔离之前，``tests/test_trading_proxy.py``
直接使用 ``apps.api.main:app``，其写请求会被 ``governance_middleware`` 记入
``apps/api/store.db`` 的 ``audit_logs``。实测残留 66 行（3 次门禁 × 22 行）。

安全设计（默认不删任何东西）
----------------------------
- 默认 **dry-run**：只列出将被删除的行，退出码 0。
- ``--apply`` 才真正删除，且**先自动备份**整库到 ``backups/``，备份失败即中止。
- 只匹配「可证明由测试产生」的行：``entity_type='trading'`` 且
  ``action`` 属于交易代理写接口。判定依据：交易域是纯代理，当前环境为 shadow，
  从未接入真实 Runner，因此不存在合法的 ``/trading/*`` 写入流量。
- ``--before`` / ``--actor`` 可进一步收窄范围。

用法::

    python tools/purge_test_audit.py                     # 只看，不删
    python tools/purge_test_audit.py --json report.json  # 导出清单
    python tools/purge_test_audit.py --apply             # 备份后删除
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STORE = REPO_ROOT / "apps" / "api" / "store.db"
BACKUP_DIR = REPO_ROOT / "backups"

#: 仅这些写接口会被视为测试残留。读接口本就不写审计。
TEST_ARTIFACT_ACTIONS = (
    "POST /trading/orders",
    "POST /trading/risk/mode",
    "POST /trading/recovery/orders",
)


def sha256_of(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_rows(connection: sqlite3.Connection, actor: str | None, before: float | None):
    clauses = [
        "entity_type = 'trading'",
        f"action IN ({','.join('?' * len(TEST_ARTIFACT_ACTIONS))})",
    ]
    params: list[object] = list(TEST_ARTIFACT_ACTIONS)
    if actor:
        clauses.append("actor_id = ?")
        params.append(actor)
    if before is not None:
        clauses.append("created_at < ?")
        params.append(before)
    where = " AND ".join(clauses)
    return (
        connection.execute(
            f"SELECT id, actor_id, action, result, error, created_at FROM audit_logs WHERE {where} ORDER BY created_at",
            params,
        ).fetchall(),
        where,
        params,
    )


def backup_store() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    destination = BACKUP_DIR / f"store.db.pre-purge-{stamp}.bak"
    shutil.copy2(STORE, destination)
    if sha256_of(destination) != sha256_of(STORE):
        raise RuntimeError(f"备份校验失败，已中止：{destination}")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="清理测试写入主库的审计残留")
    parser.add_argument("--apply", action="store_true", help="真正删除（默认只列出）")
    parser.add_argument("--actor", help="只清理指定 actor_id")
    parser.add_argument("--before", help="只清理该 ISO 时间之前的行，例如 2026-08-09T16:00:00")
    parser.add_argument("--json", dest="json_path", type=Path, help="导出清单到 JSON")
    args = parser.parse_args()

    if not STORE.is_file():
        print(f"主库不存在：{STORE}")
        return 0

    before_ts = datetime.fromisoformat(args.before).timestamp() if args.before else None
    digest_before = sha256_of(STORE)

    connection = sqlite3.connect(str(STORE))
    try:
        rows, where, _ = select_rows(connection, args.actor, before_ts)
        total = connection.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]

        print(f"主库          : {STORE}")
        print(f"当前校验和    : {digest_before}")
        print(f"audit_logs 总数: {total}")
        print(f"匹配条件      : {where}")
        print(f"命中残留      : {len(rows)} 行")
        if rows:
            by_action = Counter(row[2] for row in rows)
            for action, count in by_action.most_common():
                print(f"  {count:4d}  {action}")
            first = (
                datetime.fromtimestamp(rows[0][5], UTC).astimezone().isoformat(timespec="seconds")
            )
            last = (
                datetime.fromtimestamp(rows[-1][5], UTC).astimezone().isoformat(timespec="seconds")
            )
            print(f"  时间窗: {first} -> {last}")

        report = {
            "task": "P1-audit-cleanup",
            "store_path": str(STORE),
            "sha256_before": digest_before,
            "audit_logs_total_before": total,
            "matched_rows": len(rows),
            "matched_by_action": dict(Counter(row[2] for row in rows)),
            "applied": bool(args.apply),
            "row_ids": [row[0] for row in rows],
        }

        if not args.apply:
            print("\n当前为 dry-run，未删除任何数据。确认无误后加 --apply 执行（会先自动备份）。")
        elif rows:
            backup = backup_store()
            print(f"\n已备份主库到: {backup}")
            connection.executemany(
                "DELETE FROM audit_logs WHERE id = ?", [(row[0],) for row in rows]
            )
            connection.commit()
            remaining = connection.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
            connection.close()
            digest_after = sha256_of(STORE)
            report |= {
                "backup_path": str(backup),
                "audit_logs_total_after": remaining,
                "sha256_after": digest_after,
            }
            print(f"已删除 {len(rows)} 行，audit_logs 剩余 {remaining}")
            print(f"清理后校验和: {digest_after}")
        else:
            print("\n无可清理的残留。")
    finally:
        try:
            connection.close()
        except sqlite3.ProgrammingError:
            pass

    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"清单已写入: {args.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
