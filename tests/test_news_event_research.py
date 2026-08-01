from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from apps.api.domains.news.schemas import (
    NewsEventOutcome,
    NewsEventResearchRequest,
    NewsEventValidationRequest,
    NewsResearchEvent,
)
from apps.api.domains.news.service import research_events, validate_research_events
from core.news_event_research import EVENT_TAXONOMY, extract_event_semantics
from strategies.a_shares.news_analyzer.prompts import BATCH_ANALYSIS_SYSTEM_PROMPT


class NewsEventResearchTests(unittest.TestCase):
    def event(
        self,
        event_id: str,
        *,
        event_type: str = "major_contract",
        direction: str = "positive",
        confidence: float = 0.9,
        evidence: str = "公司签署重大合同 api_key=should-not-export",
        fingerprint: str = "a" * 64,
        minutes: int = 0,
        entity_matches_target: bool = True,
        publication_time_verified: bool = True,
        source_url: str | None = "https://example.com/a?id=1&token=secret",
        restricted_data: bool = False,
    ) -> NewsResearchEvent:
        published = datetime(2026, 1, 2, 9, 30, tzinfo=UTC) + timedelta(minutes=minutes)
        collected = published + timedelta(minutes=2)
        return NewsResearchEvent(
            event_id=event_id,
            entity_id="a-shares:600519",
            entity_name="贵州茅台",
            symbol="600519",
            market="a_shares",
            event_type=event_type,
            direction=direction,
            strength=0.8,
            confidence=confidence,
            evidence_excerpt=evidence,
            event_time=published - timedelta(hours=1),
            published_time=published,
            collected_time=collected,
            available_time=collected,
            source="exchange",
            source_document_id=f"document-{event_id}",
            source_url=source_url,
            content_fingerprint=fingerprint,
            entity_matches_target=entity_matches_target,
            publication_time_verified=publication_time_verified,
            restricted_data=restricted_data,
            extractor={"provider": "deepseek", "model": "fixed-taxonomy"},
        )

    @staticmethod
    def outcome(event_id: str, scale: float, *, price_state: str = "trend_up") -> NewsEventOutcome:
        return NewsEventOutcome(
            event_id=event_id,
            forward_returns={
                "1": 0.01 * scale,
                "3": 0.02 * scale,
                "5": 0.03 * scale,
                "10": 0.04 * scale,
                "20": 0.05 * scale,
            },
            market_returns={key: 0.001 for key in ("1", "3", "5", "10", "20")},
            industry_returns={key: 0.002 for key in ("1", "3", "5", "10", "20")},
            price_state=price_state,
            volume_state="expanding",
            liquidity_state="high",
        )

    def test_llm_contract_uses_fixed_taxonomy_and_forbids_price_prediction(self) -> None:
        extraction = extract_event_semantics(
            "公司签署重大合同",
            {
                "event_type": "major_contract",
                "event_direction": "positive",
                "event_strength": 0.8,
                "event_confidence": 0.95,
                "event_evidence": "签署重大合同",
            },
        )

        self.assertEqual(extraction["event_type"], "major_contract")
        self.assertEqual(extraction["extraction_method"], "llm_fixed_taxonomy")
        self.assertFalse(extraction["price_prediction_allowed"])
        self.assertIn("严禁输出股价涨跌预测", BATCH_ANALYSIS_SYSTEM_PROMPT)
        self.assertEqual(
            set(EVENT_TAXONOMY),
            {
                "earnings_guidance",
                "earnings_revision",
                "share_repurchase",
                "shareholder_change",
                "dividend",
                "regulatory_penalty",
                "major_contract",
                "trading_status",
            },
        )
        payload = self.event("event-extra").model_dump(mode="python")
        payload["price_prediction"] = "up"
        with self.assertRaisesRegex(ValidationError, "Extra inputs are not permitted"):
            NewsResearchEvent(**payload)

    def test_quality_gate_and_repost_clustering_are_auditable(self) -> None:
        events = [
            self.event("canonical", fingerprint="b" * 64),
            self.event("repost", fingerprint="b" * 64, minutes=10),
            self.event("low-confidence", confidence=0.4, fingerprint="c" * 64, minutes=20),
            self.event(
                "wrong-entity",
                fingerprint="d" * 64,
                minutes=30,
                entity_matches_target=False,
            ),
        ]
        response = validate_research_events(
            NewsEventValidationRequest(
                events=events,
                target_entity_id="a-shares:600519",
                minimum_confidence=0.75,
            )
        )

        self.assertTrue(response["ok"])
        report = response["report"]
        self.assertEqual(report["eligible_events_before_deduplication"], 2)
        self.assertEqual(report["canonical_event_count"], 1)
        self.assertEqual(report["duplicate_event_count"], 1)
        self.assertEqual(report["rejected_event_count"], 2)
        self.assertEqual(report["cluster_rule_version"], "entity-type-content-jaccard-1.0.0")
        reasons = {row["event_id"]: row["reasons"] for row in report["quality_gate"]}
        self.assertIn("low_confidence", reasons["low-confidence"])
        self.assertIn("entity_mismatch", reasons["wrong-entity"])
        self.assertFalse(response["prediction_generated"])

    def test_publication_delay_changes_the_research_snapshot(self) -> None:
        first = validate_research_events(
            NewsEventValidationRequest(
                events=[self.event("event-delay")],
                target_entity_id="a-shares:600519",
            )
        )["report"]
        delayed = validate_research_events(
            NewsEventValidationRequest(
                events=[self.event("event-delay", minutes=1)],
                target_entity_id="a-shares:600519",
            )
        )["report"]

        self.assertNotEqual(first["snapshot_fingerprint"], delayed["snapshot_fingerprint"])

    def test_event_research_reports_all_horizons_conditions_and_safe_evidence(self) -> None:
        events = [
            self.event("contract-1", fingerprint="1" * 64),
            self.event(
                "penalty-1",
                event_type="regulatory_penalty",
                direction="negative",
                evidence="公司收到监管处罚 token=private-value",
                fingerprint="2" * 64,
                minutes=200,
                source_url="https://example.com/penalty?authorization=private",
            ),
            self.event(
                "dividend-1",
                event_type="dividend",
                direction="positive",
                evidence="公司发布现金分红方案",
                fingerprint="3" * 64,
                minutes=400,
                restricted_data=True,
            ),
        ]
        outcomes = [
            self.outcome("contract-1", 1.0),
            self.outcome("penalty-1", -0.7, price_state="trend_down"),
            self.outcome("dividend-1", 0.5, price_state="range"),
        ]
        response = research_events(
            NewsEventResearchRequest(
                events=events,
                outcomes=outcomes,
                target_entity_id="a-shares:600519",
            )
        )

        self.assertTrue(response["ok"])
        report = response["report"]
        self.assertEqual({row["horizon"] for row in report["horizons"]}, {1, 3, 5, 10, 20})
        self.assertTrue(
            all(
                row["label"] == "market_industry_neutral_residual_return"
                for row in report["horizons"]
            )
        )
        self.assertEqual(report["matched_outcomes"], 3)
        self.assertTrue(report["conditional_effects"])
        self.assertFalse(report["prediction_generated"])
        evidence = {row["event_id"]: row for row in report["evidence_index"]}
        self.assertEqual(evidence["contract-1"]["source_url"], "https://example.com/a")
        self.assertNotIn("should-not-export", evidence["contract-1"]["evidence_excerpt"])
        self.assertNotIn("private-value", evidence["penalty-1"]["evidence_excerpt"])
        self.assertIsNone(evidence["dividend-1"]["source_url"])

    def test_unverified_publication_time_is_blocked(self) -> None:
        report = validate_research_events(
            NewsEventValidationRequest(
                events=[self.event("unverified", publication_time_verified=False)],
                target_entity_id="a-shares:600519",
            )
        )["report"]

        self.assertEqual(report["canonical_event_count"], 0)
        self.assertIn("publication_time_unverified", report["quality_gate"][0]["reasons"])


if __name__ == "__main__":
    unittest.main()
