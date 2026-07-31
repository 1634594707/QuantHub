import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api import database, store
from apps.api.main import app


class ResearchRunMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_db = store._DB
        self.temp_dir = Path(tempfile.mkdtemp(prefix="quanthub-research-meta-"))
        database.dispose_engines()
        store._DB = self.temp_dir / "store.db"
        store._init()

    def tearDown(self) -> None:
        database.dispose_engines()
        store._DB = self.original_db
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_run(self) -> dict:
        return store.create_research_run(
            symbol="AAPL",
            market="us_stocks",
            timeframe="1d",
            modules=["factor_research"],
            input_data={},
        )

    def test_tags_and_archive_filter_are_persisted(self) -> None:
        first = self._create_run()
        second = self._create_run()
        updated = store.update_research_run(
            first["id"], {"tags": ["待复验", "趋势", "待复验"], "archived": True}
        )

        self.assertEqual(updated["tags"], ["待复验", "趋势"])
        self.assertIsNotNone(updated["archived_at"])
        self.assertEqual(
            [run["id"] for run in store.list_research_runs_page()["items"]], [second["id"]]
        )
        self.assertEqual(
            [run["id"] for run in store.list_research_runs_page(archived=True)["items"]],
            [first["id"]],
        )
        self.assertEqual(
            [
                run["id"]
                for run in store.list_research_runs_page(tag="待复验", archived=True)["items"]
            ],
            [first["id"]],
        )

    def test_batch_api_updates_all_runs_and_rejects_missing_ids_without_partial_update(
        self,
    ) -> None:
        first = self._create_run()
        second = self._create_run()
        client = TestClient(app)

        response = client.patch(
            "/research/runs/batch",
            json={"run_ids": [first["id"], second["id"]], "tags": ["批量复验"], "archived": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)
        self.assertTrue(all(run["archived_at"] for run in response.json()["runs"]))

        missing = client.patch(
            "/research/runs/batch",
            json={"run_ids": [first["id"], "missing-run"], "tags": ["不应写入"]},
        )
        self.assertEqual(missing.status_code, 404)
        self.assertNotIn("不应写入", store.get_research_run(first["id"])["tags"])

        restored = client.patch(
            "/research/runs/batch",
            json={"run_ids": [first["id"], second["id"]], "archived": False},
        )
        self.assertEqual(restored.status_code, 200)
        self.assertTrue(all(run["archived_at"] is None for run in restored.json()["runs"]))
