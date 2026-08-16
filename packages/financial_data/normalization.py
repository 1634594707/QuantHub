"""Deterministic point-in-time and financial-period normalization helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from .contracts import FinancialLineItem, NormalizedFinancialStatement

FreshnessStatus = Literal["fresh", "stale", "expired", "future"]


def canonical_content_hash(payload: object) -> str:
    serialized = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def classify_freshness(
    *, available_at: datetime, as_of: datetime, stale_after: timedelta, expire_after: timedelta
) -> FreshnessStatus:
    if available_at.tzinfo is None or as_of.tzinfo is None:
        raise ValueError("freshness timestamps must be timezone-aware")
    if stale_after < timedelta(0) or expire_after < stale_after:
        raise ValueError("freshness thresholds must be ordered and non-negative")
    age = as_of - available_at
    if age < timedelta(0):
        return "future"
    if age > expire_after:
        return "expired"
    if age > stale_after:
        return "stale"
    return "fresh"


def select_available_statements(
    statements: Iterable[NormalizedFinancialStatement], *, as_of: datetime
) -> tuple[NormalizedFinancialStatement, ...]:
    """Select the latest visible revision per statement identity without future leakage."""
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    selected: dict[tuple[str, object, object, str], NormalizedFinancialStatement] = {}
    ordered = sorted(
        statements,
        key=lambda item: (
            item.provenance.available_at,
            item.provenance.fetched_at,
            item.provenance.revision,
        ),
    )
    for statement in ordered:
        if statement.provenance.available_at > as_of:
            continue
        key = (
            statement.instrument_id,
            statement.statement_type,
            statement.period_end,
            statement.provenance.source,
        )
        selected[key] = statement
    return tuple(sorted(selected.values(), key=lambda item: (item.period_end, item.statement_type)))


def resolve_statement_conflicts(
    statements: Iterable[NormalizedFinancialStatement],
    *,
    source_priority: tuple[str, ...],
) -> tuple[NormalizedFinancialStatement, ...]:
    """Adopt one source per period using an explicit, stable priority list."""
    priority = {source: index for index, source in enumerate(source_priority)}
    grouped: dict[tuple[str, object, object], list[NormalizedFinancialStatement]] = {}
    for statement in statements:
        key = (statement.instrument_id, statement.statement_type, statement.period_end)
        grouped.setdefault(key, []).append(statement)
    adopted = []
    for candidates in grouped.values():
        adopted.append(
            min(
                candidates,
                key=lambda item: (
                    priority.get(item.provenance.source, len(priority)),
                    -item.provenance.available_at.timestamp(),
                    item.provenance.source,
                    item.statement_id,
                ),
            )
        )
    return tuple(sorted(adopted, key=lambda item: (item.period_end, item.statement_type)))


def build_ttm_line_items(
    quarters: tuple[tuple[FinancialLineItem, ...], ...],
) -> tuple[FinancialLineItem, ...]:
    """Sum exactly four normalized single-quarter flows without filling gaps."""
    if len(quarters) != 4:
        raise ValueError("TTM requires exactly four single-quarter periods")
    names = sorted({item.canonical_name for quarter in quarters for item in quarter})
    result: list[FinancialLineItem] = []
    for name in names:
        items = [
            next((item for item in quarter if item.canonical_name == name), None)
            for quarter in quarters
        ]
        first = next((item for item in items if item is not None), None)
        if first is None:
            continue
        compatible = bool(
            all(
                item is not None
                and item.value is not None
                and not item.cumulative
                and item.currency == first.currency
                and item.unit == first.unit
                for item in items
            )
        )
        result.append(
            first.model_copy(
                update={
                    "value": sum(
                        (item.value for item in items if item and item.value is not None),
                        start=Decimal(0),
                    )
                    if compatible
                    else None,
                    "cumulative": False,
                    "conversion_status": "converted" if compatible else "not_convertible",
                }
            )
        )
    return tuple(result)


def cumulative_to_single_quarter(
    current: NormalizedFinancialStatement,
    previous: NormalizedFinancialStatement | None,
) -> tuple[FinancialLineItem, ...]:
    """Convert cumulative flow items to one quarter; mark gaps instead of guessing."""
    if current.statement_type.value == "balance_sheet":
        return current.items
    previous_items = {item.canonical_name: item for item in previous.items} if previous else {}
    converted: list[FinancialLineItem] = []
    for item in current.items:
        if not item.cumulative:
            converted.append(item)
            continue
        prior = previous_items.get(item.canonical_name)
        compatible = bool(
            prior
            and prior.value is not None
            and item.value is not None
            and prior.currency == item.currency
            and prior.unit == item.unit
            and prior.cumulative
        )
        converted.append(
            item.model_copy(
                update={
                    "value": item.value - prior.value if compatible and prior else None,
                    "cumulative": False,
                    "conversion_status": "converted" if compatible else "not_convertible",
                }
            )
        )
    return tuple(converted)
