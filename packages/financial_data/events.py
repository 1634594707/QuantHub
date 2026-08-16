"""Deterministic normalization of company news and announcements."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, time
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .contracts import CompanyEvent, CompanyEventEntity, EventDirection, PointInTimeProvenance
from .normalization import canonical_content_hash

_SHANGHAI = ZoneInfo("Asia/Shanghai")

_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("earnings", ("财报", "业绩", "营收", "净利润", "earnings", "results")),
    ("guidance", ("预告", "指引", "forecast", "guidance")),
    ("order", ("订单", "中标", "合同", "order", "contract")),
    ("merger", ("并购", "收购", "重组", "merger", "acquisition")),
    ("buyback", ("回购", "buyback")),
    ("insider_sale", ("减持", "insider sale")),
    ("regulatory", ("监管", "处罚", "调查", "regulatory", "probe")),
    ("litigation", ("诉讼", "仲裁", "litigation", "lawsuit")),
    ("product", ("产品", "发布", "获批", "product", "approval")),
    ("management", ("董事", "高管", "辞职", "management", "ceo")),
    ("capital_action", ("分红", "送转", "增发", "配股", "dividend", "offering")),
)

_POSITIVE = ("增长", "上调", "中标", "回购", "获批", "扭亏", "increase", "beat", "win")
_NEGATIVE = ("下降", "下调", "亏损", "减持", "处罚", "诉讼", "调查", "decline", "miss")


def _timestamp(value: Any, *, conservative: bool = True) -> datetime:
    parsed = pd.Timestamp(value)
    if pd.isna(parsed):
        return datetime.now(UTC)
    if conservative and parsed.time() == time.min:
        parsed = pd.Timestamp(datetime.combine(parsed.date(), time(23, 59, 59)))
    result = parsed.to_pydatetime()
    return (
        result.replace(tzinfo=_SHANGHAI) if result.tzinfo is None else result.astimezone(_SHANGHAI)
    )


def _normalized_title(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.lower())


def _category(title: str, explicit: str | None = None) -> str:
    normalized = f"{explicit or ''} {title}".lower()
    return next(
        (key for key, phrases in _CATEGORY_RULES if any(item in normalized for item in phrases)),
        "other",
    )


def _direction(title: str, payload: Mapping[str, Any]) -> EventDirection:
    research = payload.get("research_event")
    explicit = research.get("direction") if isinstance(research, Mapping) else None
    mapping = {
        "positive": EventDirection.POSITIVE,
        "negative": EventDirection.NEGATIVE,
        "neutral": EventDirection.NEUTRAL,
        "mixed": EventDirection.MIXED,
    }
    if explicit in mapping:
        return mapping[str(explicit)]
    positive = any(item in title.lower() for item in _POSITIVE)
    negative = any(item in title.lower() for item in _NEGATIVE)
    if positive and negative:
        return EventDirection.MIXED
    if positive:
        return EventDirection.POSITIVE
    if negative:
        return EventDirection.NEGATIVE
    return EventDirection.INSUFFICIENT


def _affected_metrics(category: str) -> tuple[str, ...]:
    return {
        "earnings": ("revenue", "net_profit", "operating_cash_flow"),
        "guidance": ("revenue", "net_profit"),
        "order": ("revenue", "operating_cash_flow"),
        "merger": ("revenue", "total_debt", "total_equity"),
        "buyback": ("shares_outstanding", "eps"),
        "insider_sale": ("risk_premium",),
        "regulatory": ("risk_premium", "operating_cash_flow"),
        "litigation": ("risk_premium", "operating_cash_flow"),
        "capital_action": ("shares_outstanding", "dividends"),
    }.get(category, ())


def _related_entities(
    instrument_id: str, row: Mapping[str, Any], *, verified_source: bool
) -> tuple[CompanyEventEntity, ...]:
    entities: list[CompanyEventEntity] = [
        CompanyEventEntity(
            entity_type="company",
            name=instrument_id.rsplit(":", 1)[-1],
            identifier=instrument_id,
            confidence=1,
            verification_status="verified",
        )
    ]
    ner_mapping = {"org": "company", "person": "person", "location": "region"}
    for item in row.get("entities") or []:
        if not isinstance(item, Mapping) or not str(item.get("text") or "").strip():
            continue
        entities.append(
            CompanyEventEntity(
                entity_type=ner_mapping.get(str(item.get("type")), "other"),
                name=str(item["text"]).strip(),
                confidence=0.75 if verified_source else 0.55,
                verification_status="inferred",
            )
        )
    explicit_fields = {
        "products": "product",
        "product": "product",
        "supply_chain": "supply_chain",
        "competitors": "competitor",
        "industry": "industry",
    }
    for field, entity_type in explicit_fields.items():
        raw = row.get(field)
        values = raw if isinstance(raw, (list, tuple, set)) else [raw] if raw else []
        for value in values:
            name = str(value).strip()
            if name:
                entities.append(
                    CompanyEventEntity(
                        entity_type=entity_type,
                        name=name,
                        confidence=0.9 if verified_source else 0.7,
                        verification_status="verified" if verified_source else "pending",
                    )
                )
    deduplicated: dict[tuple[str, str], CompanyEventEntity] = {}
    for entity in entities:
        key = (entity.entity_type, entity.name.casefold())
        current = deduplicated.get(key)
        if current is None or entity.confidence > current.confidence:
            deduplicated[key] = entity
    return tuple(deduplicated.values())


def build_company_events(
    *,
    instrument_id: str,
    news_items: Iterable[Mapping[str, Any]] = (),
    announcements: Iterable[Mapping[str, Any]] = (),
    fetched_at: datetime | None = None,
) -> tuple[CompanyEvent, ...]:
    captured_at = fetched_at or datetime.now(UTC)
    rows: list[tuple[str, Mapping[str, Any], bool]] = [
        (str(item.get("title") or ""), item, False) for item in news_items
    ] + [(str(item.get("title") or ""), item, True) for item in announcements]
    rows.sort(
        key=lambda item: (
            _timestamp(item[1].get("ts") or captured_at),
            0 if item[2] else 1,
        )
    )
    canonical_by_title: dict[str, str] = {}
    events: list[CompanyEvent] = []
    for title, row, is_announcement in rows:
        if not title.strip():
            continue
        published_at = _timestamp(row.get("ts") or captured_at)
        if published_at > captured_at.astimezone(published_at.tzinfo):
            continue
        source = str(row.get("source") or ("exchange_announcement" if is_announcement else "news"))
        url = row.get("url")
        category = _category(title, str(row.get("ann_type") or ""))
        related_entities = _related_entities(instrument_id, row, verified_source=is_announcement)
        raw_payload = {
            "title": title,
            "summary": row.get("summary") or row.get("content") or "",
            "source": source,
            "url": url,
            "published_at": published_at.isoformat(),
            "category": category,
            "related_entities": [item.model_dump(mode="json") for item in related_entities],
        }
        content_hash = canonical_content_hash(raw_payload)
        identity = f"{instrument_id}|{source}|{published_at.isoformat()}|{content_hash}"
        event_id = sha256(identity.encode("utf-8")).hexdigest()
        title_key = _normalized_title(title)
        repost_of = canonical_by_title.get(title_key)
        if repost_of is None:
            canonical_by_title[title_key] = event_id
        events.append(
            CompanyEvent(
                event_id=event_id,
                instrument_id=instrument_id,
                category=category,
                title=title.strip(),
                summary=str(row.get("summary") or row.get("content") or "").strip(),
                direction=_direction(title, row),
                importance="high" if category in {"earnings", "merger", "regulatory"} else "medium",
                impact_horizon="medium"
                if category in {"earnings", "guidance", "order"}
                else "short",
                affected_metrics=_affected_metrics(category),
                related_entities=related_entities,
                falsification_conditions=("后续正式公告或财报与当前事件结论不一致",),
                verification_status="verified" if is_announcement else "pending",
                repost_of=repost_of,
                provenance=PointInTimeProvenance(
                    source=source[:120],
                    source_url=str(url) if url else None,
                    source_record_id=event_id,
                    event_at=published_at,
                    published_at=published_at,
                    available_at=published_at,
                    fetched_at=captured_at,
                    revision="1",
                    content_hash=content_hash,
                    quality_status="verified" if is_announcement else "single_source",
                    quality_reasons=() if is_announcement else ("SINGLE_SOURCE",),
                ),
            )
        )
    return tuple(events)
