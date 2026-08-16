from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.market_data import Provenance

CONTRACT_VERSION = "1.0.0"
STOCK_RESEARCH_CONTRACT_VERSION = "2.0.0"


class StatementType(StrEnum):
    INCOME = "income"
    BALANCE_SHEET = "balance_sheet"
    CASH_FLOW = "cash_flow"


class AccountingStandard(StrEnum):
    CAS = "CAS"
    IFRS = "IFRS"
    US_GAAP = "US_GAAP"
    OTHER = "OTHER"


class FinancialStatement(BaseModel):
    model_config = ConfigDict(frozen=True)

    protocol_version: str = CONTRACT_VERSION
    instrument_id: str
    statement_type: StatementType
    period_start: date
    period_end: date
    announced_at: datetime
    currency: str = Field(min_length=3, max_length=3)
    unit: str = "1"
    consolidated: bool
    accounting_standard: AccountingStandard
    values: dict[str, Decimal]
    provenance: Provenance

    @model_validator(mode="after")
    def validate_period(self) -> FinancialStatement:
        if self.period_start > self.period_end:
            raise ValueError("period_start cannot follow period_end")
        if self.announced_at.tzinfo is None:
            raise ValueError("announced_at must be timezone-aware")
        if self.provenance.available_at < self.announced_at:
            raise ValueError("financial data cannot be available before announcement")
        return self


_UNIT_MULTIPLIERS = {
    "1": Decimal(1),
    "thousand": Decimal(1000),
    "million": Decimal(1000000),
    "billion": Decimal(1000000000),
    "万": Decimal(10000),
    "亿": Decimal(100000000),
}


def normalize_amount(value: Decimal | float | str, unit: str) -> Decimal:
    try:
        multiplier = _UNIT_MULTIPLIERS[unit]
    except KeyError as exc:
        raise ValueError(f"unsupported financial unit: {unit}") from exc
    return Decimal(str(value)) * multiplier


def reconcile_statements(
    statements: list[FinancialStatement],
) -> dict[tuple[str, StatementType, date], tuple[FinancialStatement, ...]]:
    """Keep source revisions side by side instead of silently overwriting them."""
    grouped: dict[tuple[str, StatementType, date], list[FinancialStatement]] = {}
    for statement in statements:
        key = (statement.instrument_id, statement.statement_type, statement.period_end)
        grouped.setdefault(key, []).append(statement)
    return {
        key: tuple(
            sorted(
                values,
                key=lambda item: (
                    item.provenance.source,
                    item.provenance.revision,
                    item.provenance.fetched_at,
                ),
            )
        )
        for key, values in grouped.items()
    }


class ResearchMode(StrEnum):
    QUICK = "quick"
    INVESTOR = "investor"
    PROFESSIONAL = "professional"
    QUANT = "quant"


class HoldingStatus(StrEnum):
    NOT_HELD = "not_held"
    HELD = "held"


class ResearchHorizon(StrEnum):
    SHORT = "short"
    SWING = "swing"
    MEDIUM = "medium"
    LONG = "long"


class RiskPreference(StrEnum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class UserResearchPreference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol_version: str = STOCK_RESEARCH_CONTRACT_VERSION
    user_id: str = Field(min_length=1, max_length=160)
    default_mode: ResearchMode = ResearchMode.INVESTOR
    default_market: str = Field(default="a_shares", min_length=1, max_length=40)
    holding_status: HoldingStatus = HoldingStatus.NOT_HELD
    research_horizon: ResearchHorizon = ResearchHorizon.SWING
    risk_preference: RiskPreference = RiskPreference.BALANCED
    terminology_level: Literal["plain", "standard", "technical"] = "standard"
    updated_at: datetime

    @model_validator(mode="after")
    def validate_updated_at(self) -> UserResearchPreference:
        if self.updated_at.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")
        return self


class PointInTimeProvenance(BaseModel):
    """Source and temporal metadata shared by every stock-research artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(min_length=1, max_length=120)
    source_url: str | None = Field(default=None, max_length=2000)
    source_record_id: str | None = Field(default=None, max_length=240)
    event_at: datetime | None = None
    published_at: datetime
    available_at: datetime
    fetched_at: datetime
    revision: str = Field(default="1", min_length=1, max_length=80)
    content_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    quality_status: Literal["verified", "single_source", "degraded", "invalid"] = "single_source"
    quality_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_temporal_order(self) -> PointInTimeProvenance:
        values = [self.published_at, self.available_at, self.fetched_at]
        if self.event_at is not None:
            values.append(self.event_at)
        if any(value.tzinfo is None for value in values):
            raise ValueError("point-in-time timestamps must be timezone-aware")
        if self.available_at < self.published_at:
            raise ValueError("available_at cannot precede published_at")
        if self.fetched_at < self.available_at:
            raise ValueError("fetched_at cannot precede available_at")
        return self


class FinancialPeriodType(StrEnum):
    QUARTER = "quarter"
    HALF_YEAR = "half_year"
    NINE_MONTH = "nine_month"
    ANNUAL = "annual"
    TTM = "ttm"


class FinancialLineItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    canonical_name: str = Field(min_length=1, max_length=120)
    raw_name: str = Field(min_length=1, max_length=240)
    value: Decimal | None
    currency: str = Field(min_length=3, max_length=3)
    unit: str = "1"
    cumulative: bool = False
    conversion_status: Literal["original", "converted", "not_convertible"] = "original"


class NormalizedFinancialStatement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol_version: str = STOCK_RESEARCH_CONTRACT_VERSION
    statement_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    market: Literal["a_shares", "us_stocks"]
    statement_type: StatementType
    period_type: FinancialPeriodType
    period_start: date
    period_end: date
    fiscal_year_end: date | None = None
    currency: str = Field(min_length=3, max_length=3)
    consolidated: bool = True
    accounting_standard: AccountingStandard
    items: tuple[FinancialLineItem, ...] = Field(min_length=1)
    provenance: PointInTimeProvenance

    @model_validator(mode="after")
    def validate_statement(self) -> NormalizedFinancialStatement:
        if self.period_start > self.period_end:
            raise ValueError("period_start cannot follow period_end")
        names = [item.canonical_name for item in self.items]
        if len(names) != len(set(names)):
            raise ValueError("canonical financial line items must be unique")
        return self


class FundamentalSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol_version: str = STOCK_RESEARCH_CONTRACT_VERSION
    snapshot_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    as_of: datetime
    statement_ids: tuple[str, ...] = Field(min_length=1)
    metrics: dict[str, Decimal | None]
    trends: dict[str, Literal["improving", "stable", "deteriorating", "insufficient"]]
    financial_quality: Literal["strong", "adequate", "weak", "insufficient"]
    earnings_trend: Literal["improving", "stable", "deteriorating", "insufficient"]
    cash_flow_quality: Literal["strong", "adequate", "weak", "insufficient"]
    confidence: float = Field(ge=0, le=1)
    anomalies: tuple[str, ...] = ()
    industry_template: str = "general"
    method_version: str = "fundamental-analysis-v1"
    provenance: PointInTimeProvenance

    @model_validator(mode="after")
    def validate_snapshot_time(self) -> FundamentalSnapshot:
        if self.as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        if self.provenance.available_at > self.as_of:
            raise ValueError("snapshot cannot include evidence unavailable at as_of")
        return self


class ValuationMetric(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: Literal["pe_ttm", "forward_pe", "pb", "ps", "ev_ebitda", "fcf_yield", "dividend_yield"]
    value: Decimal | None = None
    applicable: bool = True
    unavailable_reason: str | None = Field(default=None, max_length=500)
    denominator_period_end: date | None = None
    historical_percentile: float | None = Field(default=None, ge=0, le=1)
    industry_percentile: float | None = Field(default=None, ge=0, le=1)
    comparable_percentile: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_applicability(self) -> ValuationMetric:
        if not self.applicable and not self.unavailable_reason:
            raise ValueError("inapplicable valuation metrics require a reason")
        if not self.applicable and self.value is not None:
            raise ValueError("inapplicable valuation metrics cannot expose a value")
        return self


class ComparableGroup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    group_id: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=80)
    industry: str | None = Field(default=None, max_length=160)
    subindustry: str | None = Field(default=None, max_length=160)
    members: tuple[str, ...] = ()
    selection_method: str = Field(default="industry", max_length=160)


class ValuationSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol_version: str = STOCK_RESEARCH_CONTRACT_VERSION
    snapshot_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    as_of: datetime
    price: Decimal = Field(gt=0)
    price_at: datetime
    shares_outstanding: Decimal | None = Field(default=None, gt=0)
    shares_at: datetime | None = None
    currency: str = Field(min_length=3, max_length=3)
    metrics: tuple[ValuationMetric, ...]
    comparable_group: ComparableGroup | None = None
    valuation_range: Literal["very_low", "low", "fair", "high", "very_high", "insufficient"]
    valuation_percentile: float | None = Field(default=None, ge=0, le=1)
    sensitivity: dict[str, Decimal | None] = Field(default_factory=dict)
    invalidation_conditions: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=1)
    method_version: str = "valuation-analysis-v1"
    provenance: PointInTimeProvenance

    @model_validator(mode="after")
    def validate_valuation_times(self) -> ValuationSnapshot:
        timestamps = [self.as_of, self.price_at]
        if self.shares_at is not None:
            timestamps.append(self.shares_at)
        if any(value.tzinfo is None for value in timestamps):
            raise ValueError("valuation timestamps must be timezone-aware")
        if self.price_at > self.as_of or (self.shares_at and self.shares_at > self.as_of):
            raise ValueError("valuation inputs cannot be later than as_of")
        keys = [item.key for item in self.metrics]
        if len(keys) != len(set(keys)):
            raise ValueError("valuation metric keys must be unique")
        if self.provenance.available_at > self.as_of:
            raise ValueError("valuation cannot include evidence unavailable at as_of")
        return self


class EventDirection(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"
    INSUFFICIENT = "insufficient"


class CompanyEventEntity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_type: Literal[
        "company",
        "person",
        "region",
        "product",
        "supply_chain",
        "competitor",
        "industry",
        "other",
    ]
    name: str = Field(min_length=1, max_length=240)
    identifier: str | None = Field(default=None, max_length=240)
    confidence: float = Field(ge=0, le=1)
    verification_status: Literal["verified", "inferred", "pending"] = "pending"


class CompanyEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol_version: str = STOCK_RESEARCH_CONTRACT_VERSION
    event_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    category: Literal[
        "earnings",
        "guidance",
        "order",
        "merger",
        "buyback",
        "insider_sale",
        "regulatory",
        "litigation",
        "product",
        "management",
        "capital_action",
        "other",
    ]
    title: str = Field(min_length=1, max_length=1000)
    summary: str = Field(default="", max_length=8000)
    direction: EventDirection = EventDirection.INSUFFICIENT
    importance: Literal["low", "medium", "high", "critical"] = "medium"
    impact_horizon: Literal["short", "medium", "long", "mixed"] = "short"
    affected_metrics: tuple[str, ...] = ()
    related_entities: tuple[CompanyEventEntity, ...] = ()
    falsification_conditions: tuple[str, ...] = ()
    verification_status: Literal["verified", "corroborated", "pending"] = "pending"
    repost_of: str | None = Field(default=None, max_length=160)
    provenance: PointInTimeProvenance


class MacroEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol_version: str = STOCK_RESEARCH_CONTRACT_VERSION
    event_id: str = Field(min_length=1, max_length=160)
    region: str = Field(min_length=1, max_length=80)
    category: Literal[
        "central_bank",
        "cpi",
        "ppi",
        "employment",
        "gdp",
        "pmi",
        "retail",
        "interest_rate",
        "fx",
        "bond_yield",
        "liquidity",
        "geopolitical",
        "trade",
        "commodity",
        "other",
    ]
    title: str = Field(min_length=1, max_length=1000)
    state: Literal["scheduled", "released", "revised"]
    previous_value: Decimal | None = None
    expected_value: Decimal | None = None
    actual_value: Decimal | None = None
    revised_value: Decimal | None = None
    unit: str | None = Field(default=None, max_length=40)
    surprise: Decimal | None = None
    direction: EventDirection = EventDirection.INSUFFICIENT
    provenance: PointInTimeProvenance

    @model_validator(mode="after")
    def validate_release_state(self) -> MacroEvent:
        if self.state == "scheduled" and self.actual_value is not None:
            raise ValueError("scheduled macro events cannot expose an actual value")
        if self.state != "scheduled" and self.actual_value is None:
            raise ValueError("released macro events require an actual value")
        return self


class InstrumentRelationship(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    relationship_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    target_type: Literal[
        "industry",
        "index",
        "region",
        "currency",
        "rate",
        "commodity",
        "supply_chain",
        "revenue_region",
        "regulation",
    ]
    target_key: str = Field(min_length=1, max_length=240)
    relation_source: Literal["fact", "model", "user"]
    direction: Literal["positive", "negative", "mixed"] = "mixed"
    strength: float = Field(ge=0, le=1)
    valid_from: datetime
    valid_to: datetime | None = None
    method_version: str = Field(default="relationship-v1", max_length=80)
    provenance: PointInTimeProvenance

    @model_validator(mode="after")
    def validate_relationship_times(self) -> InstrumentRelationship:
        timestamps = [self.valid_from]
        if self.valid_to is not None:
            timestamps.append(self.valid_to)
        if any(value.tzinfo is None for value in timestamps):
            raise ValueError("relationship timestamps must be timezone-aware")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must follow valid_from")
        return self


class MacroTransmission(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    transmission_id: str = Field(min_length=1, max_length=160)
    event_id: str = Field(min_length=1, max_length=160)
    instrument_id: str = Field(min_length=1, max_length=160)
    relationship_id: str = Field(min_length=1, max_length=160)
    channel: Literal["rates", "fx", "inflation", "demand", "liquidity", "commodity", "policy"]
    order: Literal["direct", "second_order", "correlation"]
    direction: EventDirection
    horizon: Literal["short", "medium", "long"]
    strength: float = Field(ge=0, le=1)
    evidence_level: Literal["high", "medium", "low"]
    counterexamples: tuple[str, ...] = ()
    method_version: str = "macro-transmission-v1"


class ActionGuidance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal[
        "continue_observing",
        "research_further",
        "wait_for_confirmation",
        "review_holding",
        "reduce_risk",
        "exit_watch",
        "insufficient_data",
    ]
    holding_status: HoldingStatus
    primary_reasons: tuple[str, ...]
    primary_risks: tuple[str, ...]
    trigger_conditions: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    review_at: datetime
    evidence_coverage: dict[str, Literal["covered", "partial", "missing", "stale"]]
    execution_eligible: bool = False
    disclaimer: str = "研究参考，不是收益承诺。"
    method_version: str = "action-guidance-v1"

    @model_validator(mode="after")
    def validate_guidance(self) -> ActionGuidance:
        if self.review_at.tzinfo is None:
            raise ValueError("review_at must be timezone-aware")
        if (
            self.status in {"reduce_risk", "review_holding"}
            and self.holding_status != HoldingStatus.HELD
        ):
            raise ValueError("holding-only guidance cannot be shown to users without a position")
        if self.execution_eligible and not self.trigger_conditions:
            raise ValueError("executable guidance requires trigger conditions")
        if not self.primary_reasons or not self.primary_risks or not self.evidence_coverage:
            raise ValueError("guidance requires reasons, risks, and evidence coverage")
        if self.execution_eligible and any(
            status != "covered" for status in self.evidence_coverage.values()
        ):
            raise ValueError("executable guidance requires fully covered fresh evidence")
        return self
