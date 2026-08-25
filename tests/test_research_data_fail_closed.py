from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

from apps.api.domains.research_data import service
from packages.financial_data import (
    InstrumentRelationship,
    MacroEvent,
    PointInTimeProvenance,
)

NOW = datetime(2026, 8, 20, 8, 0, tzinfo=UTC)


def _provenance(*, source: str, quality_status: str = "verified") -> PointInTimeProvenance:
    return PointInTimeProvenance(
        source=source,
        source_record_id=source,
        published_at=NOW - timedelta(hours=1),
        available_at=NOW - timedelta(hours=1),
        fetched_at=NOW,
        content_hash="a" * 64,
        quality_status=quality_status,
    )


def _relationship(relationship_id: str, relation_source: str) -> InstrumentRelationship:
    return InstrumentRelationship(
        relationship_id=relationship_id,
        instrument_id="a_shares:600519",
        target_type="rate",
        target_key="PBOC_POLICY_RATE",
        relation_source=relation_source,
        direction="positive",
        strength=0.8,
        valid_from=NOW - timedelta(days=1),
        provenance=_provenance(
            source=f"relationship-{relation_source}",
            quality_status="degraded" if relation_source == "model" else "verified",
        ),
    )


def test_macro_evaluation_does_not_seed_defaults_and_marks_model_relations_display_only(
    monkeypatch,
) -> None:
    event = MacroEvent(
        event_id="rate-decision",
        region="CN",
        category="central_bank",
        title="央行利率决定",
        state="released",
        actual_value=Decimal("2.0"),
        direction="positive",
        provenance=_provenance(source="macro-provider"),
    )
    fact = _relationship("fact-rate", "fact")
    model = _relationship("model-default-rate", "model")
    provider = Mock(name="macro-provider")
    provider.name = "fixture-macro"
    provider.fetch_events.return_value = (event,)
    default_seeder = Mock()
    save_transmission = Mock()

    monkeypatch.setattr(service, "ingest_macro_events", lambda events: len(events))
    monkeypatch.setattr(service, "ensure_default_relationships", default_seeder)
    monkeypatch.setattr(
        service.store,
        "list_instrument_relationships",
        lambda *args, **kwargs: [fact.model_dump(mode="json"), model.model_dump(mode="json")],
    )
    monkeypatch.setattr(service.store, "save_macro_transmission", save_transmission)
    monkeypatch.setattr(service, "add_evidence", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "complete_module", lambda *args, **kwargs: None)

    result = service.evaluate_macro_events(
        instrument_id="a_shares:600519",
        run_id="run-1",
        owner_id="owner-1",
        market="a_shares",
        as_of=NOW,
        provider=provider,
    )

    default_seeder.assert_not_called()
    assert result["execution_eligible"] is True
    assert result["execution_relationship_count"] == 1
    assert result["display_only_relationship_count"] == 1
    assert result["execution_transmission_count"] == 1
    assert save_transmission.call_count == 1
    model_transmission = next(
        item for item in result["transmissions"] if item["relationship_id"] == "model-default-rate"
    )
    assert model_transmission["relationship_source"] == "model"
    assert model_transmission["execution_eligible"] is False
