from __future__ import annotations

import shutil
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from apps.api import database, store
from apps.api.domains.instrument.domain import Instrument
from apps.api.domains.research.service import dataframe_snapshot
from apps.api.domains.strategy_lab import repository, service
from apps.api.domains.strategy_lab.schemas import (
    BacktestRunCreate,
    ExperimentCreate,
    ExperimentUpdate,
)


class StrategyLabResearchContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_db = store._DB
        self.temp_dir = Path(tempfile.mkdtemp(prefix="quanthub-strategy-contract-"))
        database.dispose_engines()
        store._DB = self.temp_dir / "store.db"
        store._init()
        self.definition = repository.create_definition(
            name="锁定因子实验",
            strategy_key="test_strategy",
            market="us_stocks",
            description="",
            tags=[],
        )
        self.frame = self._market_frame()
        self.snapshot = dataframe_snapshot(self.frame)
        self.snapshot["data_fingerprint"] = "f" * 64
        self.research_run_id = self._save_factor_run()
        self.lifecycle_event = self._approve_research_lifecycle()
        self.instrument = Instrument(
            code="AAPL",
            market="us_stocks",
            exchange="nasdaq",
            currency="USD",
        )

    def tearDown(self) -> None:
        database.dispose_engines()
        store._DB = self.original_db
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @staticmethod
    def _market_frame() -> pd.DataFrame:
        close = np.linspace(100.0, 130.0, 80)
        frame = pd.DataFrame(
            {
                "datetime": pd.date_range("2025-01-01", periods=len(close), freq="D"),
                "open": close - 0.2,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": np.full(len(close), 10_000.0),
            }
        )
        frame.attrs["_source"] = "contract_test_feed"
        return frame

    def _save_factor_run(self) -> str:
        run = store.create_research_run(
            symbol="AAPL",
            market="us_stocks",
            timeframe="1d",
            modules=["factor_research"],
            input_data={
                "factor_research": {
                    "horizon": 5,
                    "transaction_cost_bps": 10.0,
                    "walk_forward_mode": "expanding",
                    "walk_forward_folds": 3,
                }
            },
        )
        result = {
            "ok": True,
            "symbol": "AAPL",
            "market": "us_stocks",
            "interval": "1d",
            "summary": {
                "horizon": 5,
                "transaction_cost_bps": 10.0,
                "walk_forward_mode": "expanding",
                "walk_forward_folds": 3,
                "engine_version": "2.0.0",
                "factor_formula_version": "1.0.0",
                "data_fingerprint": "f" * 64,
                "thresholds": {"minimum_rank_ic": 0.03},
            },
            "factors": [
                {
                    "key": "trend_strength",
                    "label": "趋势强度",
                    "formula": "EMA(close,20) / EMA(close,60) - 1",
                    "formula_version": "1.0.0",
                    "direction": "positive",
                    "weight": 1.0,
                    "exploratory_candidate": True,
                    "selected": True,
                    "status": "usable",
                }
            ],
        }
        store.add_research_evidence(
            run_id=run["id"],
            kind="market_snapshot",
            source="contract_test_feed",
            title="因子研究锁定行情快照",
            uri=None,
            payload=self.snapshot,
        )
        store.add_research_evidence(
            run_id=run["id"],
            kind="factor_research_result",
            source="contract_test_feed",
            title="因子样本外验证",
            uri=None,
            payload=result,
        )
        store.update_research_run(run["id"], {"status": "succeeded"})
        return str(run["id"])

    def _approve_research_lifecycle(self) -> dict:
        from apps.api.domains.factor_research.service import seed_builtin_factor_definitions

        seed_builtin_factor_definitions()
        definition = store.get_factor_definition("trend_strength", "1.0.0")
        self.assertIsNotNone(definition)
        store.ensure_factor_lifecycle_draft(definition["id"], "us_stocks")
        evidence = {
            "formula_definition_hash": definition["definition_hash"],
            "formula_hash": definition["formula_hash"],
            "formula_version": definition["version"],
            "data_snapshot_hash": self.snapshot["sha256"],
            "cumulative_attempts": 1,
            "validation_window": {"start": "2025-01-01", "end": "2025-03-21"},
            "cost_profile_version": "test-cost-v1",
            "gate_version": "test-gate-v1",
        }
        store.append_factor_lifecycle_event(
            definition["id"],
            expected_state="draft",
            state="exploratory",
            target_market="us_stocks",
            actor_type="researcher",
            actor="test-researcher",
            rule="candidate_approved",
            evidence=evidence,
        )
        return store.append_factor_lifecycle_event(
            definition["id"],
            expected_state="exploratory",
            state="research_passed",
            target_market="us_stocks",
            actor_type="system",
            actor="test-statistical-gate",
            rule="locked_out_of_sample_statistical_gate",
            evidence=evidence,
        )

    def _create_linked_experiment(self, timeframe: str = "1d") -> dict:
        with patch.object(
            service.instrument_service, "resolve_strict", return_value=self.instrument
        ):
            return service.create_experiment(
                self.definition.id,
                ExperimentCreate(
                    symbol="AAPL",
                    market="us_stocks",
                    timeframe=timeframe,
                    research_run_id=self.research_run_id,
                    params={
                        "lookback": 20,
                        "research_contract": {"market_snapshot_sha256": "front-end-value"},
                    },
                ),
            )

    def test_create_experiment_builds_complete_server_contract(self) -> None:
        response = self._create_linked_experiment()

        self.assertTrue(response["ok"])
        experiment = response["experiment"]
        contract = experiment["params"]["research_contract"]
        self.assertEqual(experiment["research_run_id"], self.research_run_id)
        self.assertEqual(contract["research_run_id"], self.research_run_id)
        self.assertEqual(contract["data_fingerprint"], "f" * 64)
        self.assertEqual(contract["market_snapshot_sha256"], self.snapshot["sha256"])
        self.assertEqual(contract["engine_version"], "2.0.0")
        self.assertEqual(contract["factor_formula_version"], "1.0.0")
        self.assertEqual(contract["horizon"], 5)
        self.assertEqual(contract["transaction_cost_bps"], 10.0)
        self.assertEqual(contract["walk_forward_mode"], "expanding")
        self.assertEqual(contract["walk_forward_folds"], 3)
        self.assertEqual(contract["thresholds"], {"minimum_rank_ic": 0.03})
        self.assertEqual(
            contract["factors"],
            [
                {
                    "key": "trend_strength",
                    "label": "趋势强度",
                    "formula": "EMA(close,20) / EMA(close,60) - 1",
                    "formula_version": "1.0.0",
                    "direction": "positive",
                    "weight": 1.0,
                    "exploratory_candidate": True,
                    "selected": True,
                    "status": "usable",
                    "lifecycle_state": "research_passed",
                    "lifecycle_event_id": self.lifecycle_event["id"],
                    "lifecycle_evidence": self.lifecycle_event["evidence"],
                }
            ],
        )

    def test_context_mismatch_rejects_experiment_creation(self) -> None:
        response = self._create_linked_experiment(timeframe="4h")

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"], "策略实验与因子研究的标的、市场、周期必须完全一致")
        self.assertEqual(repository.list_experiments(), [])

    def test_research_without_selected_usable_factor_cannot_create_experiment(self) -> None:
        run = store.create_research_run(
            symbol="AAPL",
            market="us_stocks",
            timeframe="1d",
            modules=["factor_research"],
            input_data={"factor_research": {"horizon": 5}},
        )
        store.add_research_evidence(
            run_id=run["id"],
            kind="market_snapshot",
            source="contract_test_feed",
            title="因子研究锁定行情快照",
            uri=None,
            payload=self.snapshot,
        )
        store.add_research_evidence(
            run_id=run["id"],
            kind="factor_research_result",
            source="contract_test_feed",
            title="因子样本外验证",
            uri=None,
            payload={
                "summary": {
                    "data_fingerprint": "f" * 64,
                    "multifactor_constructed": False,
                },
                "factors": [
                    {
                        "key": "trend_strength",
                        "selected": False,
                        "status": "watch",
                    }
                ],
            },
        )
        store.update_research_run(run["id"], {"status": "succeeded"})

        with self.assertRaisesRegex(ValueError, "没有通过统计门禁的组合"):
            service._build_research_contract(
                str(run["id"]),
                symbol="AAPL",
                market="us_stocks",
                timeframe="1d",
            )

    def test_exploratory_candidate_without_research_passed_is_blocked(self) -> None:
        run = store.create_research_run(
            symbol="AAPL",
            market="us_stocks",
            timeframe="1d",
            modules=["factor_research"],
            input_data={"factor_research": {"horizon": 5}},
        )
        store.add_research_evidence(
            run_id=run["id"],
            kind="market_snapshot",
            source="contract_test_feed",
            title="因子研究锁定行情快照",
            uri=None,
            payload=self.snapshot,
        )
        store.add_research_evidence(
            run_id=run["id"],
            kind="factor_research_result",
            source="contract_test_feed",
            title="因子样本外验证",
            uri=None,
            payload={
                "summary": {
                    "data_fingerprint": "f" * 64,
                    "multifactor_constructed": True,
                },
                "factors": [
                    {
                        "key": "momentum_20",
                        "label": "20 日动量",
                        "formula": "close / close.shift(20) - 1",
                        "formula_version": "1.0.0",
                        "direction": "positive",
                        "weight": 1.0,
                        "exploratory_candidate": True,
                        "selected": True,
                        "status": "usable",
                    }
                ],
            },
        )
        store.update_research_run(run["id"], {"status": "succeeded"})

        with self.assertRaisesRegex(ValueError, "尚未达到 research_passed"):
            service._build_research_contract(
                str(run["id"]),
                symbol="AAPL",
                market="us_stocks",
                timeframe="1d",
            )

    def test_linked_backtest_uses_only_locked_snapshot_and_keeps_hash(self) -> None:
        experiment_id = self._create_linked_experiment()["experiment"]["id"]
        backtest_result = {
            "ok": True,
            "summary": {"engine": "test", "final_equity": 110_000.0, "metrics": {}},
            "equity": [],
            "trades": [],
        }
        with (
            patch.object(service, "get_data_source") as market_source,
            patch.object(
                service.strategies_service,
                "backtest",
                return_value=backtest_result,
            ) as backtest,
        ):
            response = service.run_backtest(
                experiment_id,
                BacktestRunCreate(initial_capital=100_000, limit=20, seed="fixed-seed"),
            )

        self.assertTrue(response["ok"])
        market_source.assert_not_called()
        loaded_frame = backtest.call_args.kwargs["klines"]
        self.assertEqual(len(loaded_frame), len(self.frame))
        self.assertEqual(backtest.call_args.args[1].params, {"lookback": 20})
        self.assertEqual(response["run"]["data_snapshot"]["sha256"], self.snapshot["sha256"])
        self.assertEqual(response["run"]["data_snapshot"]["bars"], self.snapshot["bars"])

    def test_research_state_change_does_not_rewrite_existing_contract(self) -> None:
        experiment_id = self._create_linked_experiment()["experiment"]["id"]
        before = deepcopy(repository.get_experiment(experiment_id).params["research_contract"])

        store.update_research_run(
            self.research_run_id,
            {"status": "failed", "summary": {"factor_research": {"usable_factors": 0}}},
        )
        with patch.object(
            service.instrument_service, "resolve_strict", return_value=self.instrument
        ):
            response = service.update_experiment(
                experiment_id,
                ExperimentUpdate(
                    symbol="AAPL",
                    market="us_stocks",
                    timeframe="1d",
                    research_run_id=self.research_run_id,
                    params={"lookback": 30, "research_contract": {"tampered": True}},
                    note="状态变化后复核",
                ),
            )

        after = repository.get_experiment(experiment_id).params["research_contract"]
        self.assertTrue(response["ok"])
        self.assertEqual(after, before)
        self.assertEqual(response["experiment"]["params"]["lookback"], 30)
        self.assertEqual(response["experiment"]["note"], "状态变化后复核")

    def test_degraded_factor_blocks_new_experiments_but_preserves_existing_contract(self) -> None:
        existing_id = self._create_linked_experiment()["experiment"]["id"]
        definition = store.get_factor_definition("trend_strength", "1.0.0")
        store.append_factor_lifecycle_event(
            definition["id"],
            expected_state="research_passed",
            state="degraded",
            target_market="us_stocks",
            actor_type="system",
            actor="drift-monitor",
            rule="ic_decay",
            evidence=self.lifecycle_event["evidence"],
        )

        blocked = self._create_linked_experiment()

        self.assertFalse(blocked["ok"])
        self.assertIn("尚未达到 research_passed", blocked["error"])
        self.assertIsNotNone(repository.get_experiment(existing_id))


if __name__ == "__main__":
    unittest.main()
