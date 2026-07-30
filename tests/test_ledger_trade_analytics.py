from __future__ import annotations

import unittest

from apps.api.domains.ledger.domain import Trade, match_closed_trades, trade_analytics


def trade(
    trade_id: str,
    direction: str,
    quantity: float,
    price: float,
    ts: float,
    *,
    fee: float = 1.0,
) -> Trade:
    return Trade(
        id=trade_id,
        instrument_id="us_stocks:AAPL",
        code="AAPL",
        market="us_stocks",
        direction=direction,
        quantity=quantity,
        price=price,
        fee=fee,
        ts=ts,
        source="pa_agent",
    )


class LedgerTradeAnalyticsTests(unittest.TestCase):
    def test_fifo_matching_supports_partial_close_and_open_remainder(self) -> None:
        closed, matching = match_closed_trades(
            [
                trade("buy-1", "buy", 10, 100, 0),
                trade("sell-1", "sell", 6, 110, 900),
            ]
        )

        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["quantity"], 6)
        self.assertEqual(closed[0]["direction"], "long")
        self.assertAlmostEqual(closed[0]["pnl"], 58.4)
        self.assertEqual(matching["open_lot_count"], 1)
        self.assertEqual(matching["open_quantity"], 4)

    def test_summary_uses_closed_round_trips_and_real_fees(self) -> None:
        report = trade_analytics(
            [
                trade("long-in", "buy", 10, 100, 0),
                trade("long-out", "sell", 10, 110, 3600),
                trade("short-in", "sell", 5, 200, 7200),
                trade("short-out", "buy", 5, 210, 10800),
            ]
        )

        summary = report["summary"]
        self.assertEqual(summary["closed_trades"], 2)
        self.assertEqual(summary["total_pnl"], 46.0)
        self.assertEqual(summary["win_rate_pct"], 50.0)
        self.assertAlmostEqual(summary["profit_factor"], 98 / 52, places=3)
        self.assertEqual(summary["max_consecutive_losses"], 1)
        self.assertEqual(report["execution_quality"]["total_fees"], 4.0)
        self.assertFalse(report["execution_quality"]["slippage_available"])
        self.assertEqual({item["key"] for item in report["directions"]}, {"long", "short"})

    def test_empty_ledger_returns_zero_metrics_without_fake_slippage(self) -> None:
        report = trade_analytics([])

        self.assertEqual(report["summary"]["closed_trades"], 0)
        self.assertEqual(report["summary"]["win_rate_pct"], 0.0)
        self.assertEqual(report["cumulative_curve"], [])
        self.assertIn("无法可靠计算滑点", report["execution_quality"]["slippage_note"])


if __name__ == "__main__":
    unittest.main()
