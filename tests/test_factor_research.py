from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from core.factor_research import (
    InsufficientFactorData,
    ResearchConfig,
    _factor_series,
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
    def test_rejects_short_history(self) -> None:
        frame = _frame(np.linspace(100, 110, 80))
        with self.assertRaisesRegex(InsufficientFactorData, "至少 100 条"):
            analyze_factors(frame)

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
        self.assertGreater(len(result["curve"]), 100)
        self.assertEqual(291, result["summary"]["train_rows"])
        self.assertEqual(3, result["summary"]["purged_rows"])
        self.assertEqual(126, result["summary"]["test_rows"])
        self.assertEqual("out_of_sample", result["summary"]["evaluation_scope"])
        self.assertIn(
            result["current_signal"]["level"], {"normal", "watch", "reduce", "risk_off", "recovery"}
        )
        self.assertTrue(
            all("icir" in item and len(item["decay"]) == 5 for item in result["factors"])
        )
        self.assertTrue(all("sortino" in item and "cvar_95" in item for item in result["methods"]))
        self.assertEqual(8, len(result["indicators"]))
        self.assertAlmostEqual(
            1.0,
            sum(item["weight"] for item in result["factors"] if item["selected"]),
            places=3,
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
