from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.market_data import Provenance

CONTRACT_VERSION = "1.0.0"


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
