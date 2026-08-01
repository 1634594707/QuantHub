import unittest

import numpy as np
import pandas as pd

from core.factor_experiment_suite import (
    build_preregistered_experiments,
    cross_sectional_candidate_report,
)


class FactorExperimentSuiteTests(unittest.TestCase):
    def test_candidate_report_detects_cross_sectional_signal(self) -> None:
        sessions = pd.RangeIndex(150)
        symbols = [f"S{index}" for index in range(40)]
        factor = pd.DataFrame(
            np.tile(np.arange(len(symbols), dtype=float), (len(sessions), 1)),
            index=sessions,
            columns=symbols,
        )
        future = factor * 0.001
        report = cross_sectional_candidate_report(factor, future, horizon=5)
        self.assertTrue(report["passed"])
        self.assertGreater(report["rank_ic_mean"], 0.9)

    def test_six_preregistered_experiments_preserve_failures(self) -> None:
        rng = np.random.default_rng(7)
        sessions = pd.RangeIndex(180)
        symbols = [f"S{index}" for index in range(35)]
        returns = pd.DataFrame(
            rng.normal(0, 0.01, (len(sessions), len(symbols))),
            index=sessions,
            columns=symbols,
        )
        close = (1 + returns).cumprod() * 100
        open_price = close.shift(1).fillna(close.iloc[0]) * (1 + returns * 0.2)
        high = pd.DataFrame(
            np.maximum(open_price, close) * 1.01,
            index=sessions,
            columns=symbols,
        )
        low = pd.DataFrame(
            np.minimum(open_price, close) * 0.99,
            index=sessions,
            columns=symbols,
        )
        volume = pd.DataFrame(
            rng.integers(1_000, 10_000, (len(sessions), len(symbols))),
            index=sessions,
            columns=symbols,
        )
        experiments = build_preregistered_experiments(
            open_price=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )
        self.assertEqual(len(experiments), 6)
        self.assertEqual(
            [item["experiment_id"] for item in experiments],
            [
                "exp-01-adx-direction",
                "exp-02-volatility-adjusted-residual-momentum",
                "exp-03-breakout-volume-shock",
                "exp-04-short-term-reversal",
                "exp-05-overnight-intraday-decomposition",
                "exp-07-limit-up-state",
            ],
        )
        self.assertTrue(all(item["candidates"] for item in experiments))
        self.assertTrue(
            all("adjusted_p_value" in row for item in experiments for row in item["candidates"])
        )


if __name__ == "__main__":
    unittest.main()
