from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apps.api import database, store
from apps.api.domains.factor_research import service
from apps.api.domains.factor_research.schemas import FactorAiReviewRequest, FactorResearchRequest


def factor_result() -> dict:
    return {
        "ok": True,
        "symbol": "AAPL",
        "market": "us_stocks",
        "interval": "1d",
        "source": "test_feed",
        "quality": {"status": "ok", "usable": True, "row_count": 500},
        "summary": {
            "rows": 500,
            "test_rows": 150,
            "usable_factors": 2,
            "selected_factors": ["trend_strength"],
            "best_factor": "trend_strength",
            "best_method": "multifactor",
        },
        "current_signal": {"level": "watch", "drawdown": -0.05},
        "factors": [{"key": "trend_strength", "status": "usable"}],
        "methods": [{"key": "multifactor"}],
        "curve": [],
        "method_curves": {},
    }


def ai_result() -> dict:
    return {
        "ok": True,
        "review": {"verdict": "谨慎复核", "confidence": 82},
        "meta": {
            "provider": "custom",
            "model": "gpt-5.6-sol",
            "input_fingerprint": "factor-test",
            "attempts": 1,
            "usage": {"total_tokens": 100},
            "statistical_conclusions_locked": True,
        },
    }


class FactorResearchPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_db = store._DB
        self.temp_dir = Path(tempfile.mkdtemp(prefix="quanthub-factor-test-"))
        database.dispose_engines()
        store._DB = self.temp_dir / "store.db"
        store._init()

    def tearDown(self) -> None:
        database.dispose_engines()
        store._DB = self.original_db
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_statistical_result_is_saved_and_history_is_module_scoped(self) -> None:
        store.create_research_run(
            symbol="AAPL",
            market="us_stocks",
            timeframe="1d",
            modules=["evaluation"],
            input_data={},
        )
        request = FactorResearchRequest(symbol="AAPL", market="us_stocks")
        with patch.object(service, "run_factor_research", return_value=factor_result()):
            response = service.run_and_save_factor_research(request)

        self.assertTrue(response["saved"])
        detail = service.get_factor_research_run(response["run_id"])
        self.assertIsNotNone(detail)
        self.assertEqual(detail["result"]["source"], "test_feed")
        self.assertEqual(detail["run"]["status"], "succeeded")
        self.assertEqual(detail["run"]["evidence_count"], 1)

        history = service.list_factor_research_runs(symbol="aapl")
        self.assertEqual(history["total"], 1)
        self.assertEqual(history["runs"][0]["id"], response["run_id"])

    def test_ai_review_is_appended_to_the_saved_statistical_snapshot(self) -> None:
        request = FactorResearchRequest(symbol="AAPL", market="us_stocks")
        with patch.object(service, "run_factor_research", return_value=factor_result()):
            statistical = service.run_and_save_factor_research(request)
        with patch.object(service, "run_ai_review", return_value=ai_result()):
            response = service.review_factor_research(
                FactorAiReviewRequest(
                    symbol="AAPL",
                    market="us_stocks",
                    run_id=statistical["run_id"],
                )
            )

        self.assertTrue(response["saved"])
        detail = service.get_factor_research_run(statistical["run_id"])
        self.assertTrue(detail["ai_review"]["saved"])
        self.assertEqual(detail["ai_review"]["review"]["verdict"], "谨慎复核")
        self.assertEqual(detail["run"]["evidence_count"], 2)
        self.assertEqual(detail["run"]["status"], "succeeded")

    def test_ai_timeout_keeps_statistics_and_marks_run_partial(self) -> None:
        request = FactorResearchRequest(symbol="AAPL", market="us_stocks")
        with patch.object(service, "run_factor_research", return_value=factor_result()):
            statistical = service.run_and_save_factor_research(request)
        with patch.object(service, "run_ai_review", side_effect=TimeoutError("timed out")):
            response = service.review_factor_research(
                FactorAiReviewRequest(
                    symbol="AAPL",
                    market="us_stocks",
                    run_id=statistical["run_id"],
                )
            )

        self.assertFalse(response["ok"])
        detail = service.get_factor_research_run(statistical["run_id"])
        self.assertIsNotNone(detail["result"])
        self.assertIsNone(detail["ai_review"])
        self.assertEqual(detail["run"]["status"], "partial")
        self.assertIn("统计结论未受影响", detail["run"]["error"])


if __name__ == "__main__":
    unittest.main()
