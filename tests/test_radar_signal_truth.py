from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from pydantic import ValidationError

from apps.api.domains.portfolio import service as portfolio_service
from apps.api.domains.signals import service as signal_service
from apps.api.domains.signals.schemas import PublishSignalRequest
from strategies.a_shares.realtime_analyzer.strategy import RealtimeAnalyzerStrategy
from strategies.ai_analysis.pa_agent.strategy import PaAgentStrategy
from strategies.ai_analysis.pa_agent.two_stage import TwoStageResult
from strategies.signal_contract import parse_report_signal
from strategies.us_stocks.realtime_analyzer.strategy import RealtimeAnalyzerUsStrategy


def signal(
    *,
    signal_id: str,
    symbol: str,
    market: str,
    confidence: float,
    status: str = "new",
    source: str = "truth_test",
    ts: str = "2026-08-11T10:00:00+00:00",
    expires_at: float | None = 4_000_000_000,
) -> dict:
    return {
        "id": signal_id,
        "symbol": symbol,
        "market": market,
        "timeframe": "1h",
        "direction": "buy",
        "score": 0.7,
        "confidence": confidence,
        "source": source,
        "tags": [],
        "meta": {},
        "ts": ts,
        "status": status,
        "expires_at": expires_at,
    }


def trusted_quote(symbol: str, market: str, source: str = "tencent") -> dict:
    return {
        "code": symbol,
        "name": symbol,
        "last": 100.0,
        "pct": 0.5,
        "prev_close": 99.5,
        "source": source,
        "market": market,
        "observed_at": datetime.now(UTC).isoformat(),
        "verified": True,
    }


class PublishSignalContractTests(unittest.TestCase):
    def test_confidence_is_required(self) -> None:
        with self.assertRaises(ValidationError):
            PublishSignalRequest(symbol="600519")

    def test_report_signal_requires_explicit_valid_json_footer(self) -> None:
        self.assertIsNone(parse_report_signal("置信度大概较高"))
        self.assertIsNone(
            parse_report_signal(
                'QUANTHUB_SIGNAL_JSON:{"direction":"buy","score":0.8,"confidence":1.2}'
            )
        )
        self.assertEqual(
            parse_report_signal(
                '分析正文\nQUANTHUB_SIGNAL_JSON:{"direction":"sell","score":0.71,"confidence":0.83}'
            ),
            {"direction": "sell", "score": 0.71, "confidence": 0.83},
        )


class NarrativeStrategyTruthTests(unittest.TestCase):
    def test_a_share_snapshot_is_saved_without_publishing_a_fallback_signal(self) -> None:
        strategy = RealtimeAnalyzerStrategy(config={"enabled": True})
        with (
            patch.object(strategy, "_build_report", return_value=None),
            patch(
                "strategies.a_shares.realtime_analyzer.strategy.fetch_quotes",
                return_value=[trusted_quote("600519", "a_shares")],
            ),
            patch(
                "strategies.a_shares.realtime_analyzer.strategy.fetch_index_baseline",
                return_value={},
            ),
        ):
            produced = strategy.produce(codes=["600519"], with_kline=False)

        self.assertEqual(produced, [])
        self.assertEqual(strategy.last_report["kind"], "market_snapshot")
        self.assertTrue(strategy.last_report["display_only"])
        self.assertFalse(strategy.last_report["execution_eligible"])
        self.assertFalse(strategy.last_report["market_data"]["execution_eligible"])
        self.assertEqual(strategy.last_signal_rejection["code"], "model_unavailable")

    def test_us_report_without_structured_values_is_not_published(self) -> None:
        strategy = RealtimeAnalyzerUsStrategy(config={"enabled": True})
        with (
            patch.object(strategy, "_build_report", return_value="只有叙事结论"),
            patch(
                "strategies.us_stocks.realtime_analyzer.strategy.fetch_quotes",
                return_value=[trusted_quote("NVDA", "us_stocks")],
            ),
        ):
            produced = strategy.produce(codes=["NVDA"], with_kline=False)

        self.assertEqual(produced, [])
        self.assertEqual(strategy.last_signal_rejection["code"], "structured_signal_missing")

    def test_structured_report_values_are_published_without_numeric_defaults(self) -> None:
        strategy = RealtimeAnalyzerStrategy(config={"enabled": True})
        report = '分析正文\nQUANTHUB_SIGNAL_JSON:{"direction":"buy","score":0.74,"confidence":0.81}'
        with (
            patch.object(strategy, "_build_report", return_value=report),
            patch.object(strategy, "publish") as publish,
            patch(
                "strategies.a_shares.realtime_analyzer.strategy.fetch_quotes",
                return_value=[trusted_quote("600519", "a_shares")],
            ),
            patch(
                "strategies.a_shares.realtime_analyzer.strategy.fetch_index_baseline",
                return_value={},
            ),
        ):
            produced = strategy.produce(codes=["600519"], with_kline=False)

        self.assertEqual(len(produced), 1)
        self.assertEqual(produced[0].score, 0.74)
        self.assertEqual(produced[0].confidence, 0.81)
        publish.assert_called_once_with(produced[0])

    def test_pa_missing_both_confidence_inputs_rejects_signal(self) -> None:
        result = TwoStageResult(
            stage1_json={},
            stage2_json={
                "decision": {"order_type": "不下单"},
                "terminal": {"outcome": "wait"},
            },
        )
        produced = PaAgentStrategy._signal_from_result(result, "BTC-USDT", "crypto", "1h")
        self.assertIsNone(produced)


class RadarSelectionTests(unittest.TestCase):
    def test_latest_current_signal_wins_across_pages_and_markets_do_not_collide(self) -> None:
        first_page = [
            signal(
                signal_id="latest-a",
                symbol="SAME",
                market="a_shares",
                confidence=0.82,
                ts="2026-08-11T12:00:00+00:00",
            ),
            signal(
                signal_id="latest-us",
                symbol="SAME",
                market="us_stocks",
                confidence=0.73,
                ts="2026-08-11T11:00:00+00:00",
            ),
            signal(
                signal_id="ignored",
                symbol="DROP",
                market="crypto",
                confidence=0.9,
                status="converted",
            ),
        ]
        second_page = [
            signal(
                signal_id="old-a",
                symbol="SAME",
                market="a_shares",
                confidence=0.3,
                ts="2026-08-10T12:00:00+00:00",
            )
        ]
        pages = [
            {"items": first_page, "next_cursor": "older", "total": 4},
            {"items": second_page, "next_cursor": None, "total": 4},
        ]
        with patch.object(signal_service.repository, "list_signals_page", side_effect=pages):
            snapshot = signal_service.radar_snapshot()

        by_id = {item["id"]: item for item in snapshot["signals"]}
        self.assertEqual(set(by_id), {"latest-a", "latest-us"})
        self.assertEqual(by_id["latest-a"]["confidence"], 0.82)
        self.assertEqual(snapshot["scanned"], 4)

    def test_expired_is_only_used_when_no_current_signal_exists(self) -> None:
        items = [
            signal(
                signal_id="expired-newer",
                symbol="BTC-USDT",
                market="crypto",
                confidence=0.9,
                status="expired",
                ts="2026-08-11T12:00:00+00:00",
                expires_at=1,
            ),
            signal(
                signal_id="current-older",
                symbol="BTC-USDT",
                market="crypto",
                confidence=0.66,
                status="accepted",
                ts="2026-08-11T11:00:00+00:00",
            ),
            signal(
                signal_id="expired-only",
                symbol="ETH-USDT",
                market="crypto",
                confidence=0.7,
                status="expired",
                expires_at=1,
            ),
        ]
        page = {"items": items, "next_cursor": None, "total": len(items)}
        with patch.object(signal_service.repository, "list_signals_page", return_value=page):
            snapshot = signal_service.radar_snapshot()

        by_symbol = {item["symbol"]: item for item in snapshot["signals"]}
        self.assertEqual(by_symbol["BTC-USDT"]["id"], "current-older")
        self.assertEqual(by_symbol["BTC-USDT"]["radar_state"], "current")
        self.assertEqual(by_symbol["ETH-USDT"]["radar_state"], "expired")


class QuoteTruthContractTests(unittest.TestCase):
    def test_unavailable_quote_contains_source_time_and_reason(self) -> None:
        with patch.object(portfolio_service, "_market_fetch_disabled", return_value=True):
            quote = portfolio_service.quote_item("600519", "a_shares")

        self.assertFalse(quote["available"])
        self.assertEqual(quote["source"], "disabled")
        self.assertEqual(quote["freshness"], "unavailable")
        self.assertTrue(quote["observed_at"])
        self.assertIn("QUANTHUB_DISABLE_MARKET_FETCH", quote["error"])


if __name__ == "__main__":
    unittest.main()
