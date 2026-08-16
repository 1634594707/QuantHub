"""Point-in-time macro event ingestion and deterministic transmission rules."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime, time
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .akshare_provider import _akshare_client
from .contracts import (
    EventDirection,
    InstrumentRelationship,
    MacroEvent,
    MacroTransmission,
    PointInTimeProvenance,
)
from .normalization import canonical_content_hash

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _decimal(value: Any) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _date_end(value: Any) -> datetime:
    parsed = pd.Timestamp(value)
    result = datetime.combine(parsed.date(), time(23, 59, 59), tzinfo=_SHANGHAI)
    return result


def _direction(
    actual: Decimal | None, reference: Decimal | None, *, inverse: bool
) -> EventDirection:
    if actual is None or reference is None:
        return EventDirection.INSUFFICIENT
    if actual == reference:
        return EventDirection.NEUTRAL
    positive = actual < reference if inverse else actual > reference
    return EventDirection.POSITIVE if positive else EventDirection.NEGATIVE


class AkshareMacroProvider:
    name = "akshare-macro-calendar"

    def __init__(
        self, client: Any | None = None, *, clock: Callable[[], datetime] | None = None
    ) -> None:
        self._client = client
        self._clock = clock or (lambda: datetime.now(UTC))

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = _akshare_client()
        return self._client

    def fetch_events(self, *, as_of: datetime) -> tuple[MacroEvent, ...]:
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        client = self._get_client()
        fetched_at = self._clock()
        cutoff = as_of
        events: list[MacroEvent] = []
        central_banks = (
            ("macro_bank_usa_interest_rate", "US", "美联储利率决议"),
            ("macro_bank_euro_interest_rate", "EU", "欧洲央行利率决议"),
            ("macro_bank_china_interest_rate", "CN", "中国人民银行利率决议"),
        )
        for method_name, region, default_title in central_banks:
            if not hasattr(client, method_name):
                continue
            frame = getattr(client, method_name)()
            for row in frame.to_dict(orient="records"):
                event_at = _date_end(row.get("日期"))
                actual = _decimal(row.get("今值"))
                expected = _decimal(row.get("预测值"))
                previous = _decimal(row.get("前值"))
                if actual is None and event_at < cutoff:
                    continue
                if actual is None and fetched_at > cutoff:
                    # A current calendar fetch cannot prove that a future meeting was
                    # already visible at an earlier historical research cutoff.
                    continue
                if actual is not None and event_at > cutoff:
                    continue
                events.append(
                    self._event(
                        region=region,
                        category="central_bank",
                        title=str(row.get("商品") or default_title),
                        event_at=event_at,
                        published_at=event_at if actual is not None else cutoff,
                        state="released" if actual is not None else "scheduled",
                        previous=previous,
                        expected=expected,
                        actual=actual,
                        unit="%",
                        direction=_direction(actual, expected or previous, inverse=True),
                        fetched_at=fetched_at,
                    )
                )
        economic_indicators = (
            ("macro_usa_cpi_yoy", "cpi", "美国 CPI 同比", "%", True),
            ("macro_usa_ppi", "ppi", "美国 PPI", "%", True),
            ("macro_usa_non_farm", "employment", "美国非农就业", "万人", False),
            ("macro_usa_unemployment_rate", "employment", "美国失业率", "%", True),
            ("macro_usa_gdp_monthly", "gdp", "美国 GDP", "%", False),
            ("macro_usa_ism_pmi", "pmi", "美国 ISM 制造业 PMI", None, False),
            ("macro_usa_retail_sales", "retail", "美国零售销售", "%", False),
        )
        for method_name, category, title, unit, inverse in economic_indicators:
            if not hasattr(client, method_name):
                continue
            frame = getattr(client, method_name)()
            for row in frame.to_dict(orient="records"):
                event_at = _date_end(row.get("时间") or row.get("日期"))
                published_at = _date_end(row.get("发布日期") or row.get("日期") or row.get("时间"))
                actual = _decimal(row.get("现值") if "现值" in row else row.get("今值"))
                previous = _decimal(row.get("前值"))
                expected = _decimal(row.get("预测值"))
                if published_at > cutoff or actual is None:
                    continue
                events.append(
                    self._event(
                        region="US",
                        category=category,
                        title=title,
                        event_at=event_at,
                        published_at=published_at,
                        state="released",
                        previous=previous,
                        expected=expected,
                        actual=actual,
                        unit=unit,
                        direction=_direction(actual, expected or previous, inverse=inverse),
                        fetched_at=fetched_at,
                    )
                )
        return tuple(sorted(events, key=lambda item: item.provenance.published_at, reverse=True))

    def _event(
        self,
        *,
        region: str,
        category: str,
        title: str,
        event_at: datetime,
        published_at: datetime,
        state: str,
        previous: Decimal | None,
        expected: Decimal | None,
        actual: Decimal | None,
        unit: str | None,
        direction: EventDirection,
        fetched_at: datetime,
    ) -> MacroEvent:
        surprise = actual - expected if actual is not None and expected is not None else None
        payload = {
            "region": region,
            "category": category,
            "event_at": event_at.isoformat(),
            "published_at": published_at.isoformat(),
            "previous": previous,
            "expected": expected,
            "actual": actual,
        }
        content_hash = canonical_content_hash(payload)
        event_id = sha256(f"{category}|{event_at.isoformat()}|{content_hash}".encode()).hexdigest()
        return MacroEvent(
            event_id=event_id,
            region=region,
            category=category,
            title=title,
            state=state,
            previous_value=previous,
            expected_value=expected,
            actual_value=actual,
            unit=unit,
            surprise=surprise,
            direction=direction,
            provenance=PointInTimeProvenance(
                source=self.name,
                source_url="https://datacenter.jin10.com/",
                source_record_id=event_id,
                event_at=event_at,
                published_at=published_at,
                available_at=published_at,
                fetched_at=max(fetched_at, published_at),
                revision=published_at.date().isoformat(),
                content_hash=content_hash,
                quality_status="single_source",
                quality_reasons=("SINGLE_SOURCE",),
            ),
        )


def build_macro_transmissions(
    *,
    events: Iterable[MacroEvent],
    relationships: Iterable[InstrumentRelationship],
) -> tuple[MacroTransmission, ...]:
    transmissions: list[MacroTransmission] = []
    for event in events:
        for relationship in relationships:
            channel = _channel(event, relationship)
            if channel is None:
                continue
            direction = _compose_direction(event.direction, relationship.direction)
            identity = (
                f"{event.event_id}|{relationship.relationship_id}|{channel}|{direction.value}"
            )
            transmissions.append(
                MacroTransmission(
                    transmission_id=sha256(identity.encode()).hexdigest(),
                    event_id=event.event_id,
                    instrument_id=relationship.instrument_id,
                    relationship_id=relationship.relationship_id,
                    channel=channel,
                    order="direct"
                    if relationship.target_type in {"rate", "currency", "commodity"}
                    else "second_order",
                    direction=direction,
                    horizon="medium" if channel in {"rates", "inflation", "demand"} else "short",
                    strength=round(
                        relationship.strength
                        * (0.8 if direction != EventDirection.INSUFFICIENT else 0.3),
                        4,
                    ),
                    evidence_level="high"
                    if relationship.relation_source == "fact"
                    else "medium"
                    if relationship.relation_source == "user"
                    else "low",
                    counterexamples=("标的实际业务暴露或市场定价可能抵消该传导",),
                )
            )
    return tuple(transmissions)


def _channel(event: MacroEvent, relationship: InstrumentRelationship) -> str | None:
    if event.category in {"central_bank", "interest_rate"} and relationship.target_type == "rate":
        return "rates"
    if event.category in {"central_bank", "fx"} and relationship.target_type == "currency":
        return "fx"
    if event.category in {"cpi", "ppi"} and relationship.target_type in {"rate", "region"}:
        return "inflation"
    if event.category == "commodity" and relationship.target_type == "commodity":
        return "commodity"
    if event.category in {"gdp", "pmi", "retail", "employment"} and relationship.target_type in {
        "region",
        "industry",
    }:
        return "demand"
    if event.category in {"geopolitical", "trade"} and relationship.target_type in {
        "region",
        "regulation",
        "supply_chain",
    }:
        return "policy"
    return None


def _compose_direction(
    event_direction: EventDirection, relationship_direction: str
) -> EventDirection:
    if relationship_direction == "mixed" or event_direction in {
        EventDirection.MIXED,
        EventDirection.INSUFFICIENT,
    }:
        return EventDirection.INSUFFICIENT
    if relationship_direction == "positive":
        return event_direction
    if event_direction == EventDirection.POSITIVE:
        return EventDirection.NEGATIVE
    if event_direction == EventDirection.NEGATIVE:
        return EventDirection.POSITIVE
    return event_direction
