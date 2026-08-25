from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apps.api import store
from apps.api.domains.research.service import add_evidence, complete_module
from core.data_feed.factory import get_data_source
from packages.financial_data import (
    AkshareMacroProvider,
    CompanyEvent,
    InstrumentRelationship,
    MacroEvent,
    MacroTransmission,
    PointInTimeProvenance,
    build_company_events,
    build_macro_transmissions,
)

_DEFAULT_RELATIONSHIPS_PATH = (
    Path(__file__).resolve().parents[4] / "configs" / "research" / "default_relationships.json"
)


def ingest_company_events(events: tuple[CompanyEvent, ...]) -> int:
    return sum(store.save_company_event(item.model_dump(mode="json")) for item in events)


def ingest_macro_events(events: tuple[MacroEvent, ...]) -> int:
    return sum(store.save_macro_event(item.model_dump(mode="json")) for item in events)


def evaluate_company_events(
    *,
    instrument_id: str,
    symbol: str,
    market: str,
    run_id: str,
    limit: int = 30,
    fetched_at: datetime | None = None,
) -> dict[str, Any]:
    run = store.get_research_run(run_id) or {}
    news_evidence = next(
        (item for item in reversed(run.get("evidence") or []) if item.get("kind") == "news"),
        None,
    )
    news_items = ((news_evidence or {}).get("payload") or {}).get("items") or []
    source = get_data_source(market)
    announcements = [
        {
            "title": item.title,
            "content": item.content,
            "ts": item.ts,
            "source": source.name,
            "url": item.url,
            "ann_type": item.ann_type,
        }
        for item in source.get_announcements(symbol, limit=max(1, limit))
    ]
    events = build_company_events(
        instrument_id=instrument_id,
        news_items=news_items,
        announcements=announcements,
        fetched_at=fetched_at,
    )
    inserted = ingest_company_events(events)
    canonical = [item for item in events if item.repost_of is None]
    trusted = [
        item for item in canonical if item.verification_status in {"verified", "corroborated"}
    ]
    directions = {
        item.direction.value for item in trusted if item.direction.value != "insufficient"
    }
    direction = (
        "conflicted"
        if {"positive", "negative"}.issubset(directions)
        else "long"
        if directions == {"positive"}
        else "short"
        if directions == {"negative"}
        else "neutral"
        if directions == {"neutral"}
        else "insufficient"
    )
    summary = {
        "ok": True,
        "total": len(events),
        "canonical_count": len(canonical),
        "verified_count": len(trusted),
        "inserted_count": inserted,
        "direction": direction,
        "execution_eligible": bool(trusted) and direction not in {"conflicted", "insufficient"},
        "reason": "公司公告与可信事件方向汇总" if trusted else "没有已核实的公司事件",
        "events": [item.model_dump(mode="json") for item in canonical[:20]],
    }
    add_evidence(
        run_id,
        kind="company_event_snapshot",
        source="company-event-normalization-v1",
        title=f"{symbol} 公司事件快照",
        payload=summary,
    )
    complete_module(run_id, "announcements", summary)
    return summary


def evaluate_macro_events(
    *,
    instrument_id: str,
    run_id: str,
    owner_id: str,
    market: str | None = None,
    as_of: datetime | None = None,
    provider: AkshareMacroProvider | None = None,
) -> dict[str, Any]:
    cutoff = as_of or datetime.now(UTC)
    actual_provider = provider or AkshareMacroProvider()
    events = actual_provider.fetch_events(as_of=cutoff)
    ingest_macro_events(events)
    # ``market`` remains part of the request contract, but market-wide model
    # defaults must never be silently materialized into an executable run.
    # Relationships are instead supplied explicitly by their owner.
    _ = market
    relationships = tuple(
        InstrumentRelationship.model_validate(item)
        for item in store.list_instrument_relationships(
            instrument_id, as_of=cutoff, owner_id=owner_id
        )
    )
    transmissions = build_macro_transmissions(events=events, relationships=relationships)
    executable_relationship_ids = {
        relationship.relationship_id
        for relationship in relationships
        if relationship.relation_source in {"fact", "user"}
    }
    relationship_sources = {
        relationship.relationship_id: relationship.relation_source for relationship in relationships
    }
    executable_transmissions = [
        transmission
        for transmission in transmissions
        if transmission.relationship_id in executable_relationship_ids
    ]
    for transmission in executable_transmissions:
        store.save_macro_transmission(transmission.model_dump(mode="json"), owner_id=owner_id)
    reliable = [
        item
        for item in executable_transmissions
        if item.evidence_level in {"high", "medium"}
        and item.direction.value not in {"insufficient", "mixed"}
    ]
    directions = {item.direction.value for item in reliable}
    direction = (
        "conflicted"
        if {"positive", "negative"}.issubset(directions)
        else "long"
        if directions == {"positive"}
        else "short"
        if directions == {"negative"}
        else "neutral"
        if directions == {"neutral"}
        else "insufficient"
    )
    summary = {
        "ok": True,
        "event_count": len(events),
        "relationship_count": len(relationships),
        "transmission_count": len(transmissions),
        "execution_relationship_count": len(executable_relationship_ids),
        "display_only_relationship_count": len(relationships) - len(executable_relationship_ids),
        "execution_transmission_count": len(executable_transmissions),
        "reliable_transmission_count": len(reliable),
        "direction": direction,
        "execution_eligible": bool(reliable) and direction not in {"conflicted", "insufficient"},
        "reason": (
            "宏观事件与标的可靠暴露传导汇总"
            if reliable
            else "模型默认关系仅供展示，未纳入可执行宏观传导"
            if transmissions and not executable_transmissions
            else "无法建立可靠传导"
        ),
        "events": [item.model_dump(mode="json") for item in events[:20]],
        "transmissions": [
            {
                **item.model_dump(mode="json"),
                "relationship_source": relationship_sources[item.relationship_id],
                "execution_eligible": item.relationship_id in executable_relationship_ids,
            }
            for item in transmissions[:50]
        ],
    }
    add_evidence(
        run_id,
        kind="macro_event_snapshot",
        source=actual_provider.name,
        title="宏观事件与标的传导快照",
        payload=summary,
    )
    complete_module(run_id, "macro", summary)
    return summary


def ensure_default_relationships(
    *, instrument_id: str, market: str, owner_id: str, as_of: datetime
) -> int:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if store.list_instrument_relationships(instrument_id, as_of=as_of, owner_id=owner_id):
        return 0
    config = json.loads(_DEFAULT_RELATIONSHIPS_PATH.read_text(encoding="utf-8"))
    effective_from = datetime.fromisoformat(str(config["effective_from"]))
    if effective_from > as_of:
        return 0
    version = str(config["version"])
    inserted = 0
    for item in config.get("markets", {}).get(market, []):
        identity = "|".join(
            [instrument_id, version, str(item["target_type"]), str(item["target_key"])]
        )
        relationship_id = hashlib.sha256(identity.encode()).hexdigest()
        content_hash = hashlib.sha256(
            json.dumps(item, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        relationship = InstrumentRelationship(
            relationship_id=relationship_id,
            instrument_id=instrument_id,
            target_type=item["target_type"],
            target_key=item["target_key"],
            relation_source="model",
            direction=item["direction"],
            strength=item["strength"],
            valid_from=effective_from,
            method_version=version,
            provenance=PointInTimeProvenance(
                source="quanthub-default-relationships",
                source_url=None,
                source_record_id=relationship_id,
                published_at=effective_from,
                available_at=effective_from,
                fetched_at=max(datetime.now(UTC), effective_from),
                revision=version,
                content_hash=content_hash,
                quality_status="degraded",
                quality_reasons=("MODEL_INFERRED_MARKET_DEFAULT",),
            ),
        )
        inserted += int(save_relationship(relationship, owner_id=owner_id))
    return inserted


def save_relationship(relationship: InstrumentRelationship, *, owner_id: str) -> bool:
    return store.save_instrument_relationship(
        relationship.model_dump(mode="json"), owner_id=owner_id
    )


def save_macro_event(event: MacroEvent) -> bool:
    return store.save_macro_event(event.model_dump(mode="json"))


def save_company_event(event: CompanyEvent) -> bool:
    return store.save_company_event(event.model_dump(mode="json"))


def save_transmission(transmission: MacroTransmission, *, owner_id: str = "local-user") -> bool:
    return store.save_macro_transmission(transmission.model_dump(mode="json"), owner_id=owner_id)
