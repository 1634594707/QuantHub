from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.migrate_product_data import apply_migration, inspect_source, rollback


class ProductMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "legacy.db"
        connection = sqlite3.connect(self.source)
        connection.executescript(
            """
            CREATE TABLE signals(id TEXT PRIMARY KEY, symbol TEXT, market TEXT);
            INSERT INTO signals VALUES ('s1', 'BTC-USDT-SWAP', 'okx');
            """
        )
        connection.commit()
        connection.close()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_dry_run_apply_hash_verification_and_rollback_for_runner(self) -> None:
        target = self.root / "okx_runner.db"
        dry_run = inspect_source(self.source, "okx_runner")
        self.assertEqual(len(dry_run["source_hash"]), 64)
        manifest = apply_migration(self.source, target, "okx_runner")
        self.assertTrue(manifest["verified"])
        connection = sqlite3.connect(target)
        migrated = connection.execute(
            "SELECT COUNT(*) FROM legacy_migration_records WHERE run_id=?",
            (manifest["run_id"],),
        ).fetchone()[0]
        connection.close()
        self.assertEqual(migrated, sum(dry_run["counts"].values()))
        result = rollback(target, manifest["run_id"])
        self.assertTrue(result["rolled_back"])


if __name__ == "__main__":
    unittest.main()
