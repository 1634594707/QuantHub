"""Deterministic fundamental and valuation calculations."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from statistics import median

from .contracts import (
    ComparableGroup,
    FundamentalSnapshot,
    NormalizedFinancialStatement,
    PointInTimeProvenance,
    StatementType,
    ValuationMetric,
    ValuationSnapshot,
)
from .normalization import resolve_statement_conflicts, select_available_statements


def _latest_values(
    statements: tuple[NormalizedFinancialStatement, ...],
) -> tuple[dict[str, Decimal | None], dict[str, list[Decimal]]]:
    latest: dict[str, Decimal | None] = {}
    history: dict[str, list[Decimal]] = {}
    for statement in sorted(statements, key=lambda item: item.period_end):
        for item in statement.items:
            latest[item.canonical_name] = item.value
            if item.value is not None:
                history.setdefault(item.canonical_name, []).append(item.value)
    return latest, history


def _trend(values: list[Decimal]) -> str:
    if len(values) < 2:
        return "insufficient"
    previous, current = values[-2:]
    tolerance = max(abs(previous), Decimal(1)) * Decimal("0.02")
    if current > previous + tolerance:
        return "improving"
    if current < previous - tolerance:
        return "deteriorating"
    return "stable"


def build_fundamental_snapshot(
    *,
    snapshot_id: str,
    instrument_id: str,
    statements: tuple[NormalizedFinancialStatement, ...],
    as_of: datetime,
    industry_template: str = "general",
    source_priority: tuple[str, ...] = (),
) -> FundamentalSnapshot:
    candidates = select_available_statements(statements, as_of=as_of)
    visible = resolve_statement_conflicts(candidates, source_priority=source_priority)
    if not visible:
        raise ValueError("no financial statements were available at as_of")
    latest, history = _latest_values(visible)
    tracked = (
        "revenue",
        "gross_profit",
        "operating_profit",
        "net_profit",
        "operating_cash_flow",
        "free_cash_flow",
    )
    trends = {key: _trend(history.get(key, [])) for key in tracked}
    profit = latest.get("net_profit")
    cash = latest.get("operating_cash_flow")
    anomalies: list[str] = []
    if profit is not None and profit > 0 and (cash is None or cash <= 0):
        anomalies.append("PROFIT_CASH_FLOW_DIVERGENCE")
    debt = latest.get("total_debt")
    equity = latest.get("total_equity")
    if debt is not None and equity is not None and equity > 0 and debt / equity > Decimal(2):
        anomalies.append("HIGH_DEBT_TO_EQUITY")
    available_trends = [value for value in trends.values() if value != "insufficient"]
    worsening = sum(value == "deteriorating" for value in available_trends)
    improving = sum(value == "improving" for value in available_trends)
    quality = (
        "insufficient"
        if len(available_trends) < 2
        else "weak"
        if anomalies or worsening > improving
        else "strong"
        if improving >= 3
        else "adequate"
    )
    earnings = trends["net_profit"]
    cash_quality = (
        "insufficient"
        if cash is None
        else "weak"
        if cash <= 0 or "PROFIT_CASH_FLOW_DIVERGENCE" in anomalies
        else "strong"
        if profit is not None and profit > 0 and cash >= profit
        else "adequate"
    )
    confidence = min(1.0, (len(visible) / 6) * 0.6 + (len(available_trends) / len(tracked)) * 0.4)
    provenance = max(visible, key=lambda item: item.provenance.available_at).provenance
    return FundamentalSnapshot(
        snapshot_id=snapshot_id,
        instrument_id=instrument_id,
        as_of=as_of,
        statement_ids=tuple(item.statement_id for item in visible),
        metrics={key: latest.get(key) for key in (*tracked, "total_debt", "total_equity")},
        trends=trends,
        financial_quality=quality,
        earnings_trend=earnings,
        cash_flow_quality=cash_quality,
        confidence=round(confidence, 4),
        anomalies=tuple(anomalies),
        industry_template=industry_template,
        provenance=provenance,
    )


def percentile_rank(value: Decimal, population: tuple[Decimal, ...]) -> float | None:
    valid = sorted(item for item in population if item.is_finite())
    if not valid:
        return None
    below = sum(item < value for item in valid)
    equal = sum(item == value for item in valid)
    return (below + equal * 0.5) / len(valid)


def derive_valuation_denominators(
    statements: tuple[NormalizedFinancialStatement, ...],
    *,
    as_of: datetime,
    source_priority: tuple[str, ...] = (),
) -> dict[str, tuple[Decimal | None, date | None]]:
    visible = resolve_statement_conflicts(
        select_available_statements(statements, as_of=as_of),
        source_priority=source_priority,
    )
    by_type: dict[StatementType, dict[date, NormalizedFinancialStatement]] = {}
    for statement in visible:
        by_type.setdefault(statement.statement_type, {})[statement.period_end] = statement

    def item_value(statement: NormalizedFinancialStatement | None, key: str) -> Decimal | None:
        if statement is None:
            return None
        return next((item.value for item in statement.items if item.canonical_name == key), None)

    def ttm(statement_type: StatementType, key: str) -> tuple[Decimal | None, date | None]:
        periods = by_type.get(statement_type, {})
        if not periods:
            return None, None
        latest_date = max(periods)
        latest = periods[latest_date]
        current = item_value(latest, key)
        if current is None:
            return None, latest_date
        if latest_date.month == 12:
            return current, latest_date
        prior_annual_date = date(latest_date.year - 1, 12, 31)
        prior_same_date = date(latest_date.year - 1, latest_date.month, latest_date.day)
        prior_annual = item_value(periods.get(prior_annual_date), key)
        prior_same = item_value(periods.get(prior_same_date), key)
        if prior_annual is None or prior_same is None:
            return None, latest_date
        return current + prior_annual - prior_same, latest_date

    balance_periods = by_type.get(StatementType.BALANCE_SHEET, {})
    latest_balance_date = max(balance_periods) if balance_periods else None
    latest_balance = balance_periods.get(latest_balance_date) if latest_balance_date else None
    operating_cash, cash_period = ttm(StatementType.CASH_FLOW, "operating_cash_flow")
    capital_expenditure, _ = ttm(StatementType.CASH_FLOW, "capital_expenditure")
    free_cash = (
        operating_cash - capital_expenditure
        if operating_cash is not None and capital_expenditure is not None
        else None
    )
    total_debt = item_value(latest_balance, "total_debt")
    cash = item_value(latest_balance, "cash")
    net_debt = total_debt - cash if total_debt is not None and cash is not None else None
    return {
        "net_profit_ttm": ttm(StatementType.INCOME, "net_profit"),
        "forward_net_profit": (None, None),
        "book_value": (item_value(latest_balance, "total_equity"), latest_balance_date),
        "revenue_ttm": ttm(StatementType.INCOME, "revenue"),
        "ebitda_ttm": ttm(StatementType.INCOME, "ebitda"),
        "free_cash_flow_ttm": (free_cash, cash_period),
        "dividends_ttm": (None, None),
        "net_debt": (net_debt, latest_balance_date),
    }


def build_valuation_snapshot(
    *,
    snapshot_id: str,
    instrument_id: str,
    as_of: datetime,
    price: Decimal,
    price_at: datetime,
    shares_outstanding: Decimal | None,
    shares_at: datetime | None,
    currency: str,
    denominators: dict[str, tuple[Decimal | None, object]],
    historical_values: dict[str, tuple[Decimal, ...]],
    industry_values: dict[str, tuple[Decimal, ...]],
    comparable_values: dict[str, tuple[Decimal, ...]],
    comparable_group: ComparableGroup | None,
    provenance: PointInTimeProvenance,
) -> ValuationSnapshot:
    market_cap = price * shares_outstanding if shares_outstanding is not None else None
    net_debt = denominators.get("net_debt", (Decimal(0), None))[0] or Decimal(0)
    enterprise_value = market_cap + net_debt if market_cap is not None else None
    definitions = {
        "pe_ttm": (market_cap, "net_profit_ttm", False),
        "forward_pe": (market_cap, "forward_net_profit", False),
        "pb": (market_cap, "book_value", False),
        "ps": (market_cap, "revenue_ttm", False),
        "ev_ebitda": (enterprise_value, "ebitda_ttm", False),
        "fcf_yield": (market_cap, "free_cash_flow_ttm", True),
        "dividend_yield": (market_cap, "dividends_ttm", True),
    }
    metrics: list[ValuationMetric] = []
    for key, (numerator, denominator_key, is_yield) in definitions.items():
        denominator, period_end = denominators.get(denominator_key, (None, None))
        applicable = numerator is not None and denominator is not None and denominator > 0
        value = None
        if applicable and numerator is not None and denominator is not None:
            value = denominator / numerator if is_yield else numerator / denominator
        reason = None if applicable else "MISSING_OR_NON_POSITIVE_DENOMINATOR"
        metrics.append(
            ValuationMetric(
                key=key,
                value=value,
                applicable=applicable,
                unavailable_reason=reason,
                denominator_period_end=period_end,
                historical_percentile=percentile_rank(value, historical_values.get(key, ()))
                if value is not None
                else None,
                industry_percentile=percentile_rank(value, industry_values.get(key, ()))
                if value is not None
                else None,
                comparable_percentile=percentile_rank(value, comparable_values.get(key, ()))
                if value is not None
                else None,
            )
        )
    ranks = [
        item.historical_percentile
        for item in metrics
        if item.historical_percentile is not None and not item.key.endswith("yield")
    ]
    central = float(median(ranks)) if ranks else None
    valuation_range = (
        "insufficient"
        if central is None
        else "very_low"
        if central <= 0.1
        else "low"
        if central <= 0.35
        else "fair"
        if central <= 0.65
        else "high"
        if central <= 0.9
        else "very_high"
    )
    return ValuationSnapshot(
        snapshot_id=snapshot_id,
        instrument_id=instrument_id,
        as_of=as_of,
        price=price,
        price_at=price_at,
        shares_outstanding=shares_outstanding,
        shares_at=shares_at,
        currency=currency,
        metrics=tuple(metrics),
        comparable_group=comparable_group,
        valuation_range=valuation_range,
        valuation_percentile=central,
        sensitivity={},
        invalidation_conditions=("财务分母修订后需重新估值", "股本或价格时点过期后需重新估值"),
        confidence=round(len([item for item in metrics if item.applicable]) / len(metrics), 4),
        provenance=provenance,
    )
