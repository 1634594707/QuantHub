from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.product_database import backup, restore, verify


class ProductBackupTests(unittest.TestCase):
    def test_backup_verify_restore_drill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.db"
            connection = sqlite3.connect(source)
            connection.execute("CREATE TABLE evidence(id TEXT PRIMARY KEY, value TEXT)")
            connection.execute("INSERT INTO evidence VALUES ('1', 'immutable')")
            connection.commit()
            connection.close()
            result = backup(source, root / "backups", "okx-runner")
            self.assertTrue(result["verified"])
            restored = root / "restored.db"
            restore(Path(result["path"]), restored, confirmed=True)
            self.assertEqual(verify(source)["logical_sha256"], verify(restored)["logical_sha256"])


if __name__ == "__main__":
    unittest.main()
