"""Provider boundary for point-in-time financial statement ingestion."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import (
    ComparableGroup,
    NormalizedFinancialStatement,
    PointInTimeProvenance,
    StatementType,
)


class FinancialProviderCapability(StrEnum):
    INCOME_STATEMENT = "income_statement"
    BALANCE_SHEET = "balance_sheet"
    CASH_FLOW = "cash_flow"
    EARNINGS_FORECAST = "earnings_forecast"
    EARNINGS_FLASH = "earnings_flash"
    DIVIDEND_ACTION = "dividend_action"
    REVISION_HISTORY = "revision_history"


class FinancialProviderStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(min_length=1, max_length=120)
    market: str = Field(min_length=1, max_length=40)
    capabilities: frozenset[FinancialProviderCapability]
    available: bool
    degraded_reasons: tuple[str, ...] = ()
    checked_at: datetime

    @model_validator(mode="after")
    def validate_checked_at(self) -> FinancialProviderStatus:
        if self.checked_at.tzinfo is None:
            raise ValueError("checked_at must be timezone-aware")
        return self


class FinancialStatementQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument_id: str = Field(min_length=1, max_length=160)
    statement_types: tuple[StatementType, ...] = tuple(StatementType)
    available_as_of: datetime
    announced_after: datetime | None = None
    limit_per_type: int = Field(default=20, ge=1, le=200)

    @model_validator(mode="after")
    def validate_times(self) -> FinancialStatementQuery:
        timestamps = [self.available_as_of]
        if self.announced_after is not None:
            timestamps.append(self.announced_after)
        if any(value.tzinfo is None for value in timestamps):
            raise ValueError("query timestamps must be timezone-aware")
        if self.announced_after is not None and self.announced_after > self.available_as_of:
            raise ValueError("announced_after cannot follow available_as_of")
        return self


@runtime_checkable
class FinancialStatementProvider(Protocol):
    @property
    def name(self) -> str: ...

    def probe(self) -> FinancialProviderStatus: ...

    def fetch_statements(
        self, query: FinancialStatementQuery
    ) -> tuple[NormalizedFinancialStatement, ...]: ...


class ValuationReferenceData(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument_id: str = Field(min_length=1, max_length=160)
    shares_outstanding: Decimal = Field(gt=0)
    shares_at: datetime
    historical_values: dict[str, tuple[Decimal, ...]]
    industry_values: dict[str, tuple[Decimal, ...]]
    comparable_values: dict[str, tuple[Decimal, ...]]
    comparable_group: ComparableGroup | None = None
    provenance: PointInTimeProvenance

    @model_validator(mode="after")
    def validate_times(self) -> ValuationReferenceData:
        if self.shares_at.tzinfo is None:
            raise ValueError("shares_at must be timezone-aware")
        return self


@runtime_checkable
class ValuationReferenceProvider(Protocol):
    def fetch_references(
        self, *, instrument_id: str, as_of: datetime
    ) -> ValuationReferenceData: ...
