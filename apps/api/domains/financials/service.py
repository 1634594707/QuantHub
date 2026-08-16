from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from apps.api import store
from packages.financial_data import (
    AkshareFinancialProvider,
    AkshareValuationReferenceProvider,
    FinancialStatementProvider,
    FinancialStatementQuery,
    NormalizedFinancialStatement,
    SecCompanyFactsFinancialProvider,
    SecCompanyFactsValuationReferenceProvider,
    ValuationReferenceProvider,
    build_fundamental_snapshot,
    build_valuation_snapshot,
    derive_valuation_denominators,
)


def _snapshot_id(instrument_id: str, as_of: datetime, statement_ids: tuple[str, ...]) -> str:
    payload = f"{instrument_id}|{as_of.isoformat()}|{'|'.join(sorted(statement_ids))}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _direction(snapshot: dict[str, Any]) -> tuple[str, str, bool]:
    quality = snapshot["financial_quality"]
    earnings = snapshot["earnings_trend"]
    if quality == "insufficient" or earnings == "insufficient":
        return "insufficient", "财务期间或关键指标不足", False
    if quality == "weak" or earnings == "deteriorating":
        return "short", "财务质量偏弱或盈利趋势恶化", True
    if quality == "strong" and earnings == "improving":
        return "long", "财务质量与盈利趋势共同改善", True
    return "neutral", "财务质量与盈利趋势尚未形成明确方向", True


def evaluate_fundamentals(
    *,
    instrument_id: str,
    market: str,
    as_of: datetime | None = None,
    provider: FinancialStatementProvider | None = None,
    source_priority: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    if market not in {"a_shares", "us_stocks"}:
        raise ValueError("当前财报模块仅支持 A 股和美股")
    evaluation_time = as_of or datetime.now(UTC)
    if evaluation_time.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    actual_provider = provider or (
        AkshareFinancialProvider() if market == "a_shares" else SecCompanyFactsFinancialProvider()
    )
    actual_source_priority = source_priority or (actual_provider.name,)
    status = actual_provider.probe()
    if not status.available:
        raise RuntimeError("；".join(status.degraded_reasons) or "财务数据提供方不可用")
    fetched = actual_provider.fetch_statements(
        FinancialStatementQuery(
            instrument_id=instrument_id,
            available_as_of=evaluation_time,
        )
    )
    if not fetched:
        raise RuntimeError("没有获取到公告时点有效的三表数据")
    inserted = sum(
        store.save_financial_statement(statement.model_dump(mode="json")) for statement in fetched
    )
    persisted = tuple(
        NormalizedFinancialStatement.model_validate(payload)
        for payload in store.list_financial_statements(
            instrument_id,
            available_as_of=evaluation_time,
            limit=500,
        )
    )
    snapshot = build_fundamental_snapshot(
        snapshot_id=_snapshot_id(
            instrument_id,
            evaluation_time,
            tuple(item.statement_id for item in persisted),
        ),
        instrument_id=instrument_id,
        statements=persisted,
        as_of=evaluation_time,
        source_priority=actual_source_priority,
    )
    payload = snapshot.model_dump(mode="json")
    direction, reason, eligible = _direction(payload)
    return {
        **payload,
        "direction": direction,
        "reason": reason,
        "execution_eligible": eligible,
        "provider": status.model_dump(mode="json"),
        "fetched_statement_count": len(fetched),
        "inserted_statement_count": inserted,
    }


def evaluate_valuation(
    *,
    instrument_id: str,
    market: str,
    price: Decimal,
    price_at: datetime,
    as_of: datetime | None = None,
    provider: ValuationReferenceProvider | None = None,
    source_priority: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    if market not in {"a_shares", "us_stocks"}:
        raise ValueError("当前估值模块仅支持 A 股和美股")
    cutoff = as_of or datetime.now(UTC)
    if cutoff.tzinfo is None or price_at.tzinfo is None:
        raise ValueError("valuation timestamps must be timezone-aware")
    persisted = tuple(
        NormalizedFinancialStatement.model_validate(payload)
        for payload in store.list_financial_statements(
            instrument_id,
            available_as_of=cutoff,
            limit=500,
        )
    )
    if not persisted:
        raise RuntimeError("估值前缺少点时财务报表")
    actual_provider = provider or (
        AkshareValuationReferenceProvider()
        if market == "a_shares"
        else SecCompanyFactsValuationReferenceProvider()
    )
    actual_source_priority = source_priority or (
        "akshare-eastmoney-financials" if market == "a_shares" else "sec-companyfacts-financials",
    )
    denominators = derive_valuation_denominators(
        persisted,
        as_of=cutoff,
        source_priority=actual_source_priority,
    )
    references = actual_provider.fetch_references(instrument_id=instrument_id, as_of=cutoff)
    snapshot_as_of = max(cutoff, price_at, references.shares_at, references.provenance.available_at)
    identity = (
        f"{instrument_id}|{snapshot_as_of.isoformat()}|{price}|"
        f"{references.provenance.content_hash}|{denominators}"
    )
    snapshot = build_valuation_snapshot(
        snapshot_id=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        instrument_id=instrument_id,
        as_of=snapshot_as_of,
        price=price,
        price_at=price_at,
        shares_outstanding=references.shares_outstanding,
        shares_at=references.shares_at,
        currency="CNY" if market == "a_shares" else "USD",
        denominators=denominators,
        historical_values=references.historical_values,
        industry_values=references.industry_values,
        comparable_values=references.comparable_values,
        comparable_group=references.comparable_group,
        provenance=references.provenance,
    )
    payload = snapshot.model_dump(mode="json")
    valuation_range = payload["valuation_range"]
    if valuation_range in {"very_low", "low"}:
        direction, reason = "long", "估值处于自身历史偏低区间"
    elif valuation_range in {"very_high", "high"}:
        direction, reason = "short", "估值处于自身历史偏高区间"
    elif valuation_range == "fair":
        direction, reason = "neutral", "估值处于自身历史中性区间"
    else:
        direction, reason = "insufficient", "估值参照或财务分母不足"
    result = {
        **payload,
        "direction": direction,
        "reason": reason,
        "execution_eligible": direction != "insufficient" and snapshot.confidence >= 0.4,
        "denominators": {
            key: {"value": value, "period_end": period_end}
            for key, (value, period_end) in denominators.items()
        },
    }
    store.save_valuation_snapshot(result)
    return result
