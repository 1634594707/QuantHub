from __future__ import annotations

import unittest

from apps.api.domains.evaluation.service import evaluate_market
from core.data_feed.okx_source import to_ccxt_symbol


def candles(closes: list[float], *, volume: float = 1000.0) -> list[dict]:
    return [
        {
            "t": f"bar-{index}",
            "o": close - 0.5,
            "h": close + 1,
            "l": close - 1,
            "c": close,
            "v": volume + index * 10,
        }
        for index, close in enumerate(closes)
    ]


class MarketEvaluationTests(unittest.TestCase):
    def test_rising_market_exposes_metrics_dimensions_and_strategy_views(self) -> None:
        result = evaluate_market(candles([100 + index * 0.8 for index in range(80)]))

        self.assertEqual(result["version"], "market-evaluation-v1")
        self.assertEqual(result["bar_count"], 80)
        self.assertEqual(result["confidence"], "高")
        self.assertEqual(result["dimensions"]["trend"]["signal"], "上升")
        self.assertEqual(result["dimensions"]["momentum"]["signal"], "增强")
        self.assertGreater(result["metrics"]["return_20_pct"], 0)
        views = {item["key"]: item for item in result["strategies"]}
        self.assertEqual(views["trend_following"]["stance"], "顺势关注")
        self.assertIn(views["risk_first"]["stance"], {"风险可控", "控制仓位"})

    def test_requested_methods_and_lenses_limit_the_result(self) -> None:
        result = evaluate_market(
            candles([100 + index * 0.2 for index in range(30)]),
            methods=["trend", "drawdown", "unknown"],
            strategy_lenses=["risk_first", "unknown"],
        )

        self.assertEqual(result["methods"], ["trend", "drawdown"])
        self.assertEqual(set(result["dimensions"]), {"trend", "drawdown"})
        self.assertEqual([item["key"] for item in result["strategies"]], ["risk_first"])

    def test_flat_market_has_neutral_rsi_instead_of_false_overbought_signal(self) -> None:
        result = evaluate_market(candles([100.0] * 30))

        self.assertEqual(result["metrics"]["rsi_14"], 50.0)
        self.assertEqual(result["dimensions"]["mean_reversion"]["signal"], "常态")

    def test_requires_two_valid_closes(self) -> None:
        with self.assertRaisesRegex(ValueError, "至少需要 2 根"):
            evaluate_market(candles([100.0]))

    def test_okx_symbol_normalization_accepts_ui_pair_formats(self) -> None:
        self.assertEqual(to_ccxt_symbol("BTC-USDT"), "BTC/USDT:USDT")
        self.assertEqual(to_ccxt_symbol("eth"), "ETH/USDT:USDT")
        self.assertEqual(to_ccxt_symbol("SOL/USDT"), "SOL/USDT:USDT")


if __name__ == "__main__":
    unittest.main()
