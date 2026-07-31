from __future__ import annotations

import unittest
from itertools import pairwise

import numpy as np
import pandas as pd

from core.factor_research import (
    FACTOR_FORMULA_VERSION,
    FACTOR_RESEARCH_ENGINE_VERSION,
    InsufficientFactorData,
    ResearchConfig,
    _benjamini_hochberg,
    _correlation_p_value,
    _evaluate_factor,
    _factor_series,
    _newey_west_correlation_test,
    _safe_corr,
    _strategy_metrics,
    _walk_forward_windows,
    analyze_factors,
)


def _frame(close: np.ndarray) -> pd.DataFrame:
    rng = np.random.default_rng(29)
    return pd.DataFrame(
        {
            "datetime": pd.date_range("2023-01-01", periods=len(close), freq="D"),
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": rng.integers(10_000, 80_000, len(close)),
        }
    )


class FactorResearchTests(unittest.TestCase):
    def test_benjamini_hochberg_adjustment_is_monotonic_in_rank_order(self) -> None:
        adjusted = _benjamini_hochberg([0.01, 0.04, 0.03, 0.20])

        expected = [0.04, 0.05333333333333334, 0.05333333333333334, 0.2]
        for actual, target in zip(adjusted, expected, strict=True):
            self.assertAlmostEqual(actual, target)

    def test_rejects_short_history(self) -> None:
        frame = _frame(np.linspace(100, 110, 80))
        with self.assertRaisesRegex(InsufficientFactorData, "至少 100 条"):
            analyze_factors(frame)

    def test_newey_west_hac_corrects_serial_correlation(self) -> None:
        rng = np.random.default_rng(7)
        observations = 300
        factor = np.zeros(observations)
        residual = np.zeros(observations)
        for index in range(1, observations):
            factor[index] = 0.95 * factor[index - 1] + rng.normal()
            residual[index] = 0.9 * residual[index - 1] + rng.normal()
        forward = 0.2 * factor + residual
        factor_series = pd.Series(factor)
        forward_series = pd.Series(forward)
        correlation = _safe_corr(factor_series, forward_series, "spearman")

        hac_p_value, effective_observations, hac_lags = _newey_west_correlation_test(
            factor_series,
            forward_series,
            9,
        )

        self.assertGreater(hac_p_value, _correlation_p_value(correlation, observations))
        self.assertLess(effective_observations, observations)
        self.assertEqual(hac_lags, 9)

    def test_factor_formation_does_not_read_future_prices(self) -> None:
        close = 100 + np.sin(np.arange(180) / 7) * 4 + np.arange(180) * 0.03
        original = _frame(close)
        changed = original.copy()
        changed.loc[150:, "close"] *= 1.8
        changed.loc[150:, "open"] = changed.loc[150:, "close"]
        changed.loc[150:, "high"] = changed.loc[150:, "close"] * 1.01
        changed.loc[150:, "low"] = changed.loc[150:, "close"] * 0.99

        before = _factor_series(original)
        after = _factor_series(changed)
        for key in before:
            pd.testing.assert_series_equal(before[key].iloc[:150], after[key].iloc[:150])

    def test_returns_ranked_factors_methods_and_curve(self) -> None:
        index = np.arange(420)
        close = 100 + index * 0.04 + np.sin(index / 5) * 5
        result = analyze_factors(
            _frame(close),
            ResearchConfig(horizon=3, transaction_cost_bps=12),
        )

        self.assertEqual(14, len(result["factors"]))
        self.assertEqual(6, len(result["methods"]))
        self.assertEqual(42, len(result["curve"]))
        self.assertEqual(375, result["summary"]["train_rows"])
        self.assertEqual(3, result["summary"]["purged_rows"])
        self.assertEqual(42, result["summary"]["test_rows"])
        self.assertEqual(126, result["summary"]["walk_forward_test_rows"])
        self.assertEqual(3, result["summary"]["walk_forward_folds"])
        self.assertEqual("walk_forward_out_of_sample", result["summary"]["evaluation_scope"])
        self.assertEqual(FACTOR_RESEARCH_ENGINE_VERSION, result["summary"]["engine_version"])
        self.assertEqual(FACTOR_FORMULA_VERSION, result["summary"]["factor_formula_version"])
        self.assertEqual(64, len(result["summary"]["data_fingerprint"]))
        self.assertEqual(
            "EMA(close,20) / EMA(close,60) - 1",
            next(item["formula"] for item in result["factors"] if item["key"] == "trend_strength"),
        )
        self.assertTrue(all(item["formula_version"] == "1.0.0" for item in result["factors"]))
        self.assertIn(
            result["current_signal"]["level"], {"normal", "watch", "reduce", "risk_off", "recovery"}
        )
        self.assertTrue(
            all("icir" in item and len(item["decay"]) == 5 for item in result["factors"])
        )
        self.assertTrue(
            all(item["p_value_method"] == "newey_west_hac" for item in result["factors"])
        )
        self.assertTrue(all(item["window_count"] == 3 for item in result["factors"]))
        self.assertTrue(all(len(item["windows"]) == 3 for item in result["factors"]))
        self.assertTrue(
            all(
                item["adjusted_p_value"] <= result["summary"]["significance_level"]
                for item in result["factors"]
                if item["status"] == "usable"
            )
        )
        self.assertTrue(all("sortino" in item and "cvar_95" in item for item in result["methods"]))
        self.assertTrue(
            all(
                item["win_rate_basis"] == "closed_trades"
                and item["profit_factor_basis"] == "closed_trades"
                for item in result["methods"]
            )
        )
        cost_curve = result["cost_analysis"]["curve"]
        self.assertEqual(
            sorted(item["transaction_cost_bps"] for item in cost_curve),
            [item["transaction_cost_bps"] for item in cost_curve],
        )
        self.assertTrue(
            all(
                current["total_return"] <= previous["total_return"]
                for previous, current in pairwise(cost_curve)
            )
        )
        definitions = {item["key"]: item for item in result["methodology"]["metric_definitions"]}
        for key in (
            "total_return",
            "sharpe",
            "max_drawdown",
            "profit_factor",
            "win_rate",
            "turnover",
            "transaction_cost_bps",
        ):
            self.assertIn(key, definitions)
            self.assertTrue(definitions[key]["formula"])
            self.assertTrue(definitions[key]["unit"])
            self.assertTrue(definitions[key]["source"])
        self.assertEqual(8, len(result["indicators"]))
        self.assertAlmostEqual(
            1.0,
            sum(item["weight"] for item in result["factors"] if item["selected"]),
            places=3,
        )

    def test_closed_trade_metrics_use_compounded_trade_returns(self) -> None:
        returns = pd.Series([0.0, 0.10, -0.02, 0.0, -0.05, -0.05, 0.0])
        position = pd.Series([1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 0.0])

        metrics, _, _ = _strategy_metrics(
            "trend",
            returns,
            position,
            ResearchConfig(transaction_cost_bps=0),
        )

        self.assertEqual(2, metrics["trades"])
        self.assertEqual(2, metrics["closed_trades"])
        self.assertFalse(metrics["open_trade"])
        self.assertEqual("closed_trades", metrics["win_rate_basis"])
        self.assertEqual("closed_trades", metrics["profit_factor_basis"])
        self.assertAlmostEqual(metrics["win_rate"], 0.5)
        self.assertAlmostEqual(metrics["profit_factor"], 0.8)
        self.assertAlmostEqual(metrics["average_trade_return"], -0.0097)
        self.assertAlmostEqual(metrics["average_holding_period"], 2.0)

    def test_transaction_cost_changes_equity_and_closed_trade_metrics(self) -> None:
        returns = pd.Series([0.0, 0.10, -0.02, 0.0, -0.05, -0.05, 0.0])
        position = pd.Series([1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 0.0])

        free, free_equity, _ = _strategy_metrics(
            "trend", returns, position, ResearchConfig(transaction_cost_bps=0)
        )
        costly, costly_equity, _ = _strategy_metrics(
            "trend", returns, position, ResearchConfig(transaction_cost_bps=100)
        )

        self.assertLess(costly_equity.iloc[-1], free_equity.iloc[-1])
        self.assertLess(costly["total_return"], free["total_return"])
        self.assertLess(costly["average_trade_return"], free["average_trade_return"])
        self.assertLess(costly["profit_factor"], free["profit_factor"])

    def test_expanding_and_rolling_windows_have_exact_training_boundaries(self) -> None:
        data = _frame(np.linspace(100, 140, 420))
        expanding = _walk_forward_windows(
            data,
            ResearchConfig(horizon=3, walk_forward_mode="expanding", walk_forward_folds=3),
        )
        rolling = _walk_forward_windows(
            data,
            ResearchConfig(horizon=3, walk_forward_mode="rolling", walk_forward_folds=3),
        )

        self.assertEqual([42, 42, 42], [item["test"]["rows"] for item in expanding])
        self.assertEqual(0, expanding[-1]["train"]["start_index"])
        self.assertEqual(375, expanding[-1]["train"]["rows"])
        self.assertEqual(84, rolling[-1]["train"]["start_index"])
        self.assertEqual(291, rolling[-1]["train"]["rows"])
        self.assertEqual(expanding[-1]["test"], rolling[-1]["test"])

    def test_tracks_direction_flips_across_non_overlapping_windows(self) -> None:
        rng = np.random.default_rng(19)
        factor = pd.Series(rng.normal(size=360))
        forward = pd.Series(np.nan, index=factor.index, dtype=float)
        ranges = [
            (0, 80, 90, 110, 1),
            (120, 200, 210, 230, -1),
            (240, 320, 330, 350, 1),
        ]
        windows = []
        for fold, (train_start, train_end, test_start, test_end, direction) in enumerate(
            ranges,
            start=1,
        ):
            forward.iloc[train_start:train_end] = factor.iloc[train_start:train_end] * direction
            forward.iloc[test_start:test_end] = factor.iloc[test_start:test_end] * direction
            windows.append(
                {
                    "fold": fold,
                    "mode": "rolling",
                    "train": {
                        "start_index": train_start,
                        "end_index": train_end - 1,
                        "start": str(train_start),
                        "end": str(train_end - 1),
                        "rows": train_end - train_start,
                    },
                    "purge": {
                        "start_index": train_end,
                        "end_index": test_start - 1,
                        "start": str(train_end),
                        "end": str(test_start - 1),
                        "rows": test_start - train_end,
                    },
                    "test": {
                        "start_index": test_start,
                        "end_index": test_end - 1,
                        "start": str(test_start),
                        "end": str(test_end - 1),
                        "rows": test_end - test_start,
                    },
                }
            )

        evaluated = _evaluate_factor(
            "momentum_20",
            factor,
            forward,
            {value: forward for value in (1, 3, 5, 10, 20)},
            windows,
            horizon=5,
        )

        self.assertEqual(2, evaluated["direction_flips"])
        self.assertEqual(3, evaluated["passed_windows"])
        self.assertTrue(evaluated["multi_window_consistent"])

    def test_single_passing_window_does_not_become_usable(self) -> None:
        rng = np.random.default_rng(23)
        data = _frame(np.linspace(100, 130, 300))
        factor = pd.Series(rng.normal(size=300))
        forward = factor.copy()
        windows = _walk_forward_windows(
            data,
            ResearchConfig(horizon=5, walk_forward_mode="expanding", walk_forward_folds=3),
        )
        for window in windows[1:]:
            start = window["test"]["start_index"]
            end = window["test"]["end_index"] + 1
            forward.iloc[start:end] = factor.iloc[start:end].mul(-1)

        evaluated = _evaluate_factor(
            "momentum_20",
            factor,
            forward,
            {value: forward for value in (1, 3, 5, 10, 20)},
            windows,
            horizon=5,
        )

        self.assertEqual(
            ["pass", "reject", "reject"], [window["status"] for window in evaluated["windows"]]
        )
        self.assertEqual(1, evaluated["passed_windows"])
        self.assertFalse(evaluated["multi_window_consistent"])
        self.assertNotEqual("usable", evaluated["status"])

    def test_decay_uses_final_window_direction_and_each_exact_horizon(self) -> None:
        rng = np.random.default_rng(31)
        data = _frame(np.linspace(100, 130, 300))
        factor = pd.Series(rng.normal(size=300))
        forward = factor.copy()
        windows = _walk_forward_windows(data, ResearchConfig(horizon=5))
        decay_forwards = {
            1: factor,
            3: factor.mul(-1),
            5: factor,
            10: factor.mul(-1),
            20: factor,
        }

        evaluated = _evaluate_factor(
            "momentum_20",
            factor,
            forward,
            decay_forwards,
            windows,
            horizon=5,
        )

        self.assertEqual(
            [
                {"horizon": 1, "ic": 1.0},
                {"horizon": 3, "ic": -1.0},
                {"horizon": 5, "ic": 1.0},
                {"horizon": 10, "ic": -1.0},
                {"horizon": 20, "ic": 1.0},
            ],
            evaluated["decay"],
        )

    def test_deep_price_drawdown_emits_risk_off(self) -> None:
        rise = np.linspace(100, 160, 220)
        fall = np.linspace(160, 110, 120)
        result = analyze_factors(_frame(np.concatenate([rise, fall])))

        self.assertEqual("risk_off", result["current_signal"]["level"])
        self.assertLessEqual(result["current_signal"]["drawdown"], -0.15)
        self.assertTrue(any(item["level"] == "risk_off" for item in result["signal_events"]))


if __name__ == "__main__":
    unittest.main()
