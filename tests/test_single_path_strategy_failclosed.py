from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from apps.api.domains.automation import service as automation_service
from apps.api.domains.strategies import service as strategies_service
from apps.scheduler import jobs as scheduler_jobs
from strategies.ai_analysis.pa_agent import strategy as pa_strategy
from strategies.crypto.alphagpt import strategy as alphagpt_strategy
from strategies.mt5.alphamaster import strategy as alphamaster_strategy
from strategies.mt5.alphamaster.formula_adapter import vocab_manifest


class PaScheduledConfigurationTests(unittest.TestCase):
    def test_unreadable_configuration_skips_scheduled_analysis(self) -> None:
        with (
            patch.object(
                pa_strategy, "get_config", side_effect=RuntimeError("configuration unavailable")
            ),
            patch.object(pa_strategy, "run_analysis") as run_analysis,
        ):
            pa_strategy.run_scheduled()

        run_analysis.assert_not_called()

    def test_missing_symbols_skips_scheduled_analysis(self) -> None:
        with (
            patch.object(pa_strategy, "get_config", return_value={"modules": {}}),
            patch.object(pa_strategy, "run_analysis") as run_analysis,
        ):
            pa_strategy.run_scheduled()

        run_analysis.assert_not_called()

    def test_empty_symbols_skips_scheduled_analysis(self) -> None:
        with (
            patch.object(
                pa_strategy,
                "get_config",
                return_value={"modules": {"pa_agent": {"symbols": []}}},
            ),
            patch.object(pa_strategy, "run_analysis") as run_analysis,
        ):
            pa_strategy.run_scheduled()

        run_analysis.assert_not_called()


class AlphaMasterFormulaArtifactTests(unittest.TestCase):
    def test_missing_artifact_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "best_mt5_strategy.json"
            strategy = alphamaster_strategy.AlphaMasterStrategy(config={})
            with patch.object(alphamaster_strategy, "_TRAINED_ARTIFACT_PATH", artifact):
                with self.assertRaisesRegex(
                    alphamaster_strategy.FormulaValidationError, "训练产物不存在"
                ):
                    strategy._load_formulas()

    def test_incompatible_artifact_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "best_mt5_strategy.json"
            artifact.write_text(
                json.dumps({"formula": [[0]], "vocab_version": "v-incompatible"}),
                encoding="utf-8",
            )
            strategy = alphamaster_strategy.AlphaMasterStrategy(config={})
            with patch.object(alphamaster_strategy, "_TRAINED_ARTIFACT_PATH", artifact):
                with self.assertRaisesRegex(
                    alphamaster_strategy.FormulaValidationError, "词表版本不匹配"
                ):
                    strategy._load_formulas()

    def test_valid_artifact_is_the_only_formula_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "best_mt5_strategy.json"
            manifest = vocab_manifest()
            artifact.write_text(
                json.dumps(
                    {
                        "formula": [[0]],
                        "vocab_version": manifest["version"],
                        "vocab_schema": manifest["schema"],
                    }
                ),
                encoding="utf-8",
            )
            strategy = alphamaster_strategy.AlphaMasterStrategy(config={})
            with patch.object(alphamaster_strategy, "_TRAINED_ARTIFACT_PATH", artifact):
                self.assertEqual(strategy._load_formulas(), [[0]])

    def test_legacy_search_entry_rejects_when_artifact_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "best_mt5_strategy.json"
            with patch.object(alphamaster_strategy, "_TRAINED_ARTIFACT_PATH", artifact):
                with self.assertRaisesRegex(
                    alphamaster_strategy.FormulaValidationError, "训练产物不存在"
                ):
                    alphamaster_strategy.run_factor_search()


class AlphaGptFormulaTests(unittest.TestCase):
    def test_produce_with_formulas_but_without_symbols_does_not_scan_examples(self) -> None:
        strategy = alphagpt_strategy.AlphaGptStrategy(config={})

        signals = strategy.produce(formulas=[[0]], klines_map={})

        self.assertEqual(signals, [])
        self.assertEqual(strategy.last_signal_rejection["code"], "symbols_required")

    def test_produce_without_formulas_does_not_search_or_emit(self) -> None:
        strategy = alphagpt_strategy.AlphaGptStrategy(config={})
        with patch.object(
            alphagpt_strategy,
            "run_factor_search",
            side_effect=AssertionError("produce must not invoke factor search"),
        ):
            signals = strategy.produce(klines_map={"SOL/USDT": pd.DataFrame({"close": [1.0]})})

        self.assertEqual(signals, [])
        self.assertEqual(strategy.last_signal_rejection["code"], "formulas_required")

    def test_backtest_without_formulas_does_not_search(self) -> None:
        frame = pd.DataFrame(
            {
                "datetime": pd.date_range("2026-01-01", periods=2, freq="h"),
                "open": [1.0, 1.0],
                "high": [1.0, 1.0],
                "low": [1.0, 1.0],
                "close": [1.0, 1.0],
                "volume": [1.0, 1.0],
            }
        )
        with patch.object(
            alphagpt_strategy,
            "run_factor_search",
            side_effect=AssertionError("backtest must not invoke factor search"),
        ):
            with self.assertRaises(alphagpt_strategy.FormulaRequiredError):
                alphagpt_strategy.AlphaGptStrategy(config={}).backtest(frame)

    def test_factor_search_entry_is_explicitly_rejected(self) -> None:
        with self.assertRaises(alphagpt_strategy.FormulaRequiredError):
            alphagpt_strategy.run_factor_search({})


class AlphaMasterSymbolConfigurationTests(unittest.TestCase):
    def test_produce_without_symbols_does_not_scan_example_universe(self) -> None:
        strategy = alphamaster_strategy.AlphaMasterStrategy(config={})

        signals = strategy.produce(formulas=[[0]], klines_map={})

        self.assertEqual(signals, [])
        self.assertEqual(strategy.last_signal_rejection["code"], "symbols_required")


class _InternalTypeErrorStrategy:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def produce(self, **kwargs):
        self.calls.append(dict(kwargs))
        raise TypeError("strategy-internal failure")


class TypeErrorCompatibilityTests(unittest.TestCase):
    def test_api_call_produce_does_not_retry_internal_type_error(self) -> None:
        strategy = _InternalTypeErrorStrategy()

        with self.assertRaisesRegex(TypeError, "strategy-internal failure"):
            strategies_service.call_produce(strategy, {"symbol": "BTC-USDT"})

        self.assertEqual(strategy.calls, [{"symbol": "BTC-USDT"}])

    def test_automation_strategy_job_does_not_retry_internal_type_error(self) -> None:
        strategy = _InternalTypeErrorStrategy()
        with patch("strategies.get_strategy", return_value=strategy):
            with self.assertRaisesRegex(TypeError, "strategy-internal failure"):
                automation_service._execute_job("__run_strategy__:test")

        self.assertEqual(strategy.calls, [{}])

    def test_scheduler_strategy_job_does_not_retry_internal_type_error(self) -> None:
        strategy = _InternalTypeErrorStrategy()
        with patch.object(scheduler_jobs, "get_strategy", return_value=strategy):
            scheduler_jobs._run_strategy("test")

        self.assertEqual(strategy.calls, [{}])


if __name__ == "__main__":
    unittest.main()
