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
                    "selected": True,
                    "status": "usable",
                }
            ],
        )

    def test_context_mismatch_rejects_experiment_creation(self) -> None:
        response = self._create_linked_experiment(timeframe="4h")

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"], "策略实验与因子研究的标的、市场、周期必须完全一致")
        self.assertEqual(repository.list_experiments(), [])

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


if __name__ == "__main__":
    unittest.main()
