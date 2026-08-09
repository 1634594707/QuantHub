"""后端门禁隔离守卫用例。

对应复核问题「后端门禁会污染主数据库」的回归防线：只要有人绕开
``tests/__init__.py`` 的隔离（或把 ``QUANTHUB_STORE_PATH`` 指回主库），
这些用例会**先于业务用例失败**，而不是悄悄写脏 ``apps/api/store.db``。

第三条用例复现原始事故场景：走 ``apps.api.main:app`` 发一个写请求，
触发 ``governance_middleware`` 的统一审计，然后断言仓库主库字节级未变。
"""

from __future__ import annotations

import hashlib
import os
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from tests import PRODUCTION_STORE_PATH, STORE_PATH


def sha256_of(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class BackendGateIsolationTests(unittest.TestCase):
    def test_store_path_is_not_the_repository_database(self) -> None:
        from apps.api import store

        self.assertNotEqual(
            store._DB,
            PRODUCTION_STORE_PATH,
            "apps.api.store 仍指向仓库主库，测试会污染生产数据",
        )
        self.assertEqual(store._DB, STORE_PATH, "store 解析出的库路径与隔离路径不一致")

    def test_environment_points_at_disposable_location(self) -> None:
        configured = os.environ.get("QUANTHUB_STORE_PATH", "")
        self.assertTrue(configured, "QUANTHUB_STORE_PATH 未设置，隔离未生效")
        self.assertNotEqual(Path(configured).resolve(), PRODUCTION_STORE_PATH)
        # 备份域默认落在库同级目录，不得回落到 apps/api/backups
        backup_dir = Path(os.environ["QUANTHUB_BACKUP_DIR"]).resolve()
        self.assertNotEqual(backup_dir, (PRODUCTION_STORE_PATH.parent / "backups").resolve())

    def test_audited_write_request_does_not_touch_repository_database(self) -> None:
        """复现事故：写请求 → 统一审计 → 曾经写进主库。现在主库必须字节不变。"""
        if not PRODUCTION_STORE_PATH.is_file():
            self.skipTest("仓库主库不存在（全新克隆），无需校验")

        before = sha256_of(PRODUCTION_STORE_PATH)
        size_before = PRODUCTION_STORE_PATH.stat().st_size

        from apps.api.main import app

        client = TestClient(app)
        # 该请求必然被拒（交易服务未装配），但中间件仍会写审计——这正是要隔离的写入。
        response = client.post("/trading/orders", json={"symbol": "BTC-USDT-SWAP"})
        self.assertIn(response.status_code, range(400, 600))

        after = sha256_of(PRODUCTION_STORE_PATH)
        self.assertEqual(
            before,
            after,
            "写请求改变了仓库主库 apps/api/store.db，门禁仍有副作用",
        )
        self.assertEqual(size_before, PRODUCTION_STORE_PATH.stat().st_size)


if __name__ == "__main__":
    unittest.main()
