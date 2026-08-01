from __future__ import annotations

import shutil
import tempfile
import unittest
from datetime import date, datetime, time
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
from pydantic import ValidationError

from apps.api import database, store
from apps.api.domains.factor_research import service
from apps.api.domains.factor_research.schemas import FactorAiReviewRequest, FactorResearchRequest
from apps.api.domains.research.service import snapshot_hash


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
            "significance_level": 0.05,
            "engine_version": "2.0.0",
            "factor_formula_version": "1.0.0",
            "data_fingerprint": "a" * 64,
            "thresholds": {"minimum_rank_ic": 0.03},
            "walk_forward_mode": "expanding",
            "walk_forward_folds": 3,
            "windows": [
                {
                    "fold": 1,
                    "mode": "expanding",
                    "train": {"start_index": 0, "end_index": 344, "rows": 345},
                    "purge": {"start_index": 345, "end_index": 349, "rows": 5},
                    "test": {"start_index": 350, "end_index": 399, "rows": 50},
                }
            ],
        },
        "current_signal": {"level": "watch", "drawdown": -0.05},
        "factors": [
            {
                "key": "trend_strength",
                "status": "usable",
                "adjusted_p_value": 0.03,
                "effective_observations": 30,
                "statistically_significant": True,
                "windows": [
                    {
                        "fold": 1,
                        "mode": "expanding",
                        "test_ic": 0.08,
                        "status": "pass",
                    }
                ],
            }
        ],
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
        self.assertEqual(detail["result"]["summary"]["significance_level"], 0.05)
        self.assertEqual(detail["result"]["factors"][0]["adjusted_p_value"], 0.03)
        self.assertTrue(detail["result"]["compatibility"]["legacy_engine_record"])
        self.assertEqual(detail["result"]["compatibility"]["record_engine_version"], "2.0.0")
        self.assertEqual(
            detail["result"]["compatibility"]["policy"],
            "historical_result_preserved_read_only",
        )
        self.assertEqual(detail["result"]["factors"][0]["effective_observations"], 30)
        self.assertEqual(
            detail["result"]["summary"]["windows"], factor_result()["summary"]["windows"]
        )
        self.assertEqual(
            detail["result"]["factors"][0]["windows"], factor_result()["factors"][0]["windows"]
        )
        self.assertEqual(detail["run"]["status"], "succeeded")
        self.assertEqual(detail["run"]["evidence_count"], 1)
        saved_summary = detail["run"]["summary"]["factor_research"]
        self.assertEqual(saved_summary["engine_version"], "2.0.0")
        self.assertEqual(saved_summary["factor_formula_version"], "1.0.0")
        self.assertEqual(saved_summary["data_fingerprint"], "a" * 64)
        self.assertEqual(saved_summary["thresholds"], {"minimum_rank_ic": 0.03})

        history = service.list_factor_research_runs(symbol="aapl")
        self.assertEqual(history["total"], 1)
        self.assertEqual(history["runs"][0]["id"], response["run_id"])

    def test_factor_research_saves_the_locked_market_snapshot(self) -> None:
        bars = [{"datetime": "2026-01-02T00:00:00", "close": 100.0}]
        snapshot = {
            "source": "test_feed",
            "count": 1,
            "columns": ["datetime", "close"],
            "sha256": snapshot_hash(bars),
            "bars": bars,
            "data_fingerprint": "a" * 64,
        }
        saved_result = {**factor_result(), "_market_snapshot": snapshot}
        with patch.object(service, "run_factor_research", return_value=saved_result):
            response = service.run_and_save_factor_research(
                FactorResearchRequest(symbol="AAPL", market="us_stocks")
            )

        run = store.get_research_run(response["run_id"])
        self.assertEqual(run["evidence_count"], 2)
        market_evidence = next(
            item for item in run["evidence"] if item["kind"] == "market_snapshot"
        )
        self.assertEqual(market_evidence["payload"], snapshot)
        self.assertEqual(
            market_evidence["payload"]["data_fingerprint"],
            run["summary"]["factor_research"]["data_fingerprint"],
        )

    def test_history_filters_use_saved_market_period_status_date_and_parameters(self) -> None:
        with patch.object(service, "run_factor_research", return_value=factor_result()):
            first = service.run_and_save_factor_research(
                FactorResearchRequest(symbol="AAPL", market="us_stocks")
            )
            second = service.run_and_save_factor_research(
                FactorResearchRequest(
                    symbol="BTCUSDT",
                    market="crypto",
                    interval="4h",
                    horizon=10,
                    transaction_cost_bps=20,
                    walk_forward_mode="rolling",
                    walk_forward_folds=4,
                )
            )
        store.update_research_run(second["run_id"], {"favorite": True, "note": "跨市场复验"})

        local_date = datetime.now().astimezone().date()
        history = service.list_factor_research_runs(
            market="crypto",
            interval="4h",
            status="succeeded",
            favorite=True,
            created_from=local_date,
            created_to=local_date,
            research_limit=500,
            horizon=10,
            transaction_cost_bps=20,
            walk_forward_mode="rolling",
            walk_forward_folds=4,
        )

        self.assertEqual(history["total"], 1)
        self.assertEqual(history["runs"][0]["id"], second["run_id"])
        self.assertTrue(history["runs"][0]["favorite"])
        self.assertEqual(history["runs"][0]["note"], "跨市场复验")
        self.assertNotEqual(history["runs"][0]["id"], first["run_id"])

        with self.assertRaisesRegex(ValueError, "created_from 不能晚于 created_to"):
            service.list_factor_research_runs(
                created_from=date(2026, 1, 2),
                created_to=date(2026, 1, 1),
            )

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

    def test_date_range_and_walk_forward_parameters_reach_data_source_exactly(self) -> None:
        rows = 300
        close = np.linspace(100, 130, rows)
        frame = pd.DataFrame(
            {
                "datetime": pd.date_range("2024-01-01", periods=rows, freq="D"),
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": np.full(rows, 10_000),
            }
        )
        source = Mock()
        source.name = "test_feed"
        source.get_kline.return_value = frame
        request = FactorResearchRequest(
            symbol="AAPL",
            market="us_stocks",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 10, 26),
            walk_forward_mode="rolling",
            walk_forward_folds=4,
        )

        with patch.object(service, "get_data_source", return_value=source):
            response = service.run_factor_research(request)

        self.assertTrue(response["ok"])
        source.get_kline.assert_called_once_with(
            "AAPL",
            "1d",
            start=datetime.combine(date(2024, 1, 1), time.min),
            end=datetime.combine(date(2024, 10, 26), time.max),
            limit=500,
        )
        self.assertEqual(response["requested_period"]["start_date"], "2024-01-01")
        self.assertEqual(response["requested_period"]["end_date"], "2024-10-26")
        self.assertEqual(response["summary"]["walk_forward_mode"], "rolling")
        self.assertEqual(response["summary"]["walk_forward_folds"], 4)

    def test_date_range_rejects_source_without_real_timestamps(self) -> None:
        rows = 300
        source = Mock()
        source.name = "ordinal_feed"
        source.get_kline.return_value = pd.DataFrame(
            {
                "datetime": pd.Series([pd.NaT] * rows),
                "open": np.full(rows, 100.0),
                "high": np.full(rows, 101.0),
                "low": np.full(rows, 99.0),
                "close": np.full(rows, 100.0),
                "volume": np.full(rows, 10_000),
            }
        )
        request = FactorResearchRequest(
            symbol="600519",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )

        with patch.object(service, "get_data_source", return_value=source):
            response = service.run_factor_research(request)

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"], "所选数据源没有可用 datetime，无法执行日期区间研究")

    def test_saved_request_uses_iso_dates_and_rejects_reversed_range(self) -> None:
        request = FactorResearchRequest(
            symbol="AAPL",
            market="us_stocks",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )
        with patch.object(service, "run_factor_research", return_value=factor_result()):
            response = service.run_and_save_factor_research(request)

        detail = service.get_factor_research_run(response["run_id"])
        saved_input = detail["run"]["input"]["factor_research"]
        self.assertEqual(saved_input["start_date"], "2024-01-01")
        self.assertEqual(saved_input["end_date"], "2024-12-31")

        with self.assertRaisesRegex(ValidationError, "start_date 不能晚于 end_date"):
            FactorResearchRequest(
                symbol="AAPL",
                start_date=date(2025, 1, 2),
                end_date=date(2025, 1, 1),
            )


if __name__ == "__main__":
    unittest.main()
