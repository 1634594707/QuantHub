"""SEC Companyfacts adapters for point-in-time US-stock financial research."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

import requests

from .contracts import (
    AccountingStandard,
    FinancialLineItem,
    FinancialPeriodType,
    NormalizedFinancialStatement,
    PointInTimeProvenance,
    StatementType,
)
from .normalization import canonical_content_hash
from .provider import (
    FinancialProviderCapability,
    FinancialProviderStatus,
    FinancialStatementQuery,
    ValuationReferenceData,
)

_NEW_YORK = ZoneInfo("America/New_York")
_SEC_FORMS = {"10-K", "10-Q", "20-F", "40-F"}

_TAGS: dict[StatementType, tuple[tuple[str, tuple[str, ...]], ...]] = {
    StatementType.INCOME: (
        (
            "revenue",
            (
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues",
                "SalesRevenueNet",
            ),
        ),
        ("operating_profit", ("OperatingIncomeLoss",)),
        (
            "total_profit",
            (
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            ),
        ),
        ("net_profit", ("NetIncomeLoss", "ProfitLoss")),
        ("basic_eps", ("EarningsPerShareBasic",)),
    ),
    StatementType.BALANCE_SHEET: (
        (
            "cash",
            (
                "CashAndCashEquivalentsAtCarryingValue",
                "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
            ),
        ),
        ("accounts_receivable", ("AccountsReceivableNetCurrent",)),
        ("inventory", ("InventoryNet",)),
        ("total_assets", ("Assets",)),
        ("total_debt", ("Liabilities",)),
        (
            "total_equity",
            (
                "StockholdersEquity",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            ),
        ),
    ),
    StatementType.CASH_FLOW: (
        ("operating_cash_flow", ("NetCashProvidedByUsedInOperatingActivities",)),
        ("investing_cash_flow", ("NetCashProvidedByUsedInInvestingActivities",)),
        ("financing_cash_flow", ("NetCashProvidedByUsedInFinancingActivities",)),
        ("capital_expenditure", ("PaymentsToAcquirePropertyPlantAndEquipment",)),
    ),
}

_ticker_lock = Lock()
_ticker_cache: dict[str, str] = {}


def _date_end(value: str | date) -> datetime:
    parsed = date.fromisoformat(value) if isinstance(value, str) else value
    return datetime.combine(parsed, time(23, 59, 59), tzinfo=_NEW_YORK)


def _decimal(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _period_type(
    statement_type: StatementType, start: date, end: date, form: str
) -> FinancialPeriodType:
    if form in {"10-K", "20-F", "40-F"}:
        return FinancialPeriodType.ANNUAL
    if statement_type == StatementType.BALANCE_SHEET:
        return FinancialPeriodType.QUARTER
    days = (end - start).days + 1
    if days <= 120:
        return FinancialPeriodType.QUARTER
    if days <= 210:
        return FinancialPeriodType.HALF_YEAR
    if days <= 300:
        return FinancialPeriodType.NINE_MONTH
    return FinancialPeriodType.ANNUAL


class SecCompanyFactsHttpClient:
    def __init__(self, *, user_agent: str | None = None, timeout: float = 20.0) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": user_agent
                or os.environ.get("QUANTHUB_SEC_USER_AGENT")
                or "QuantHub/0.4 research-contact@localhost",
                "Accept-Encoding": "gzip, deflate",
            }
        )
        self._timeout = timeout

    def company_tickers(self) -> Mapping[str, Any]:
        response = self._session.get(
            "https://www.sec.gov/files/company_tickers.json", timeout=self._timeout
        )
        response.raise_for_status()
        return response.json()

    def company_facts(self, cik: str) -> Mapping[str, Any]:
        response = self._session.get(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()


def _resolve_cik(client: Any, symbol: str) -> str:
    normalized = symbol.upper()
    with _ticker_lock:
        cached = _ticker_cache.get(normalized)
    if cached:
        return cached
    rows = client.company_tickers()
    for row in rows.values():
        if str(row.get("ticker") or "").upper() != normalized:
            continue
        cik = str(row.get("cik_str") or "").zfill(10)
        if cik.strip("0"):
            with _ticker_lock:
                _ticker_cache[normalized] = cik
            return cik
    raise ValueError(f"SEC 未找到美股代码: {symbol}")


def _facts(client: Any, instrument_id: str) -> tuple[str, Mapping[str, Any]]:
    symbol = instrument_id.rsplit(":", 1)[-1].strip().upper()
    if not symbol or len(symbol) > 12:
        raise ValueError("美股财务数据要求有效证券代码")
    cik = _resolve_cik(client, symbol)
    return cik, client.company_facts(cik)


class SecCompanyFactsFinancialProvider:
    name = "sec-companyfacts-financials"

    def __init__(
        self,
        client: Any | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client or SecCompanyFactsHttpClient()
        self._clock = clock or (lambda: datetime.now(UTC))

    def probe(self) -> FinancialProviderStatus:
        return FinancialProviderStatus(
            provider=self.name,
            market="us_stocks",
            capabilities=frozenset(
                {
                    FinancialProviderCapability.INCOME_STATEMENT,
                    FinancialProviderCapability.BALANCE_SHEET,
                    FinancialProviderCapability.CASH_FLOW,
                    FinancialProviderCapability.REVISION_HISTORY,
                }
            ),
            available=True,
            checked_at=self._clock(),
        )

    def fetch_statements(
        self, query: FinancialStatementQuery
    ) -> tuple[NormalizedFinancialStatement, ...]:
        cik, payload = _facts(self._client, query.instrument_id)
        fetched_at = self._clock()
        us_gaap = (payload.get("facts") or {}).get("us-gaap") or {}
        results: list[NormalizedFinancialStatement] = []
        for statement_type in query.statement_types:
            grouped: dict[
                tuple[date, date, date, str, str], dict[str, tuple[str, Decimal, str]]
            ] = {}
            for canonical_name, aliases in _TAGS[statement_type]:
                matched = next(
                    ((tag, us_gaap.get(tag)) for tag in aliases if us_gaap.get(tag)),
                    None,
                )
                if matched is None:
                    continue
                raw_tag, fact = matched
                if not isinstance(fact, Mapping):
                    continue
                raw_name = raw_tag
                units = fact.get("units") if isinstance(fact.get("units"), Mapping) else {}
                unit_name = "USD/shares" if canonical_name == "basic_eps" else "USD"
                entries = units.get(unit_name) or units.get("USD") or []
                for entry in entries:
                    if not isinstance(entry, Mapping) or entry.get("form") not in _SEC_FORMS:
                        continue
                    filed_raw = entry.get("filed")
                    end_raw = entry.get("end")
                    if not filed_raw or not end_raw:
                        continue
                    filed = date.fromisoformat(str(filed_raw))
                    end = date.fromisoformat(str(end_raw))
                    start = date.fromisoformat(str(entry["start"])) if entry.get("start") else end
                    published_at = _date_end(filed)
                    if published_at > query.available_as_of or published_at > fetched_at:
                        continue
                    if query.announced_after and published_at < query.announced_after:
                        continue
                    value = _decimal(entry.get("val"))
                    if value is None:
                        continue
                    key = (
                        start,
                        end,
                        filed,
                        str(entry.get("form")),
                        str(entry.get("accn") or filed_raw),
                    )
                    grouped.setdefault(key, {}).setdefault(
                        canonical_name, (raw_name, value, unit_name)
                    )
            normalized = [
                self._statement(
                    instrument_id=query.instrument_id,
                    cik=cik,
                    statement_type=statement_type,
                    key=key,
                    values=values,
                    fetched_at=fetched_at,
                )
                for key, values in grouped.items()
                if values
            ]
            normalized.sort(
                key=lambda item: (item.period_end, item.provenance.published_at), reverse=True
            )
            results.extend(normalized[: query.limit_per_type])
        return tuple(sorted(results, key=lambda item: (item.period_end, item.statement_type)))

    def _statement(
        self,
        *,
        instrument_id: str,
        cik: str,
        statement_type: StatementType,
        key: tuple[date, date, date, str, str],
        values: Mapping[str, tuple[str, Decimal, str]],
        fetched_at: datetime,
    ) -> NormalizedFinancialStatement:
        start, end, filed, form, accession = key
        published_at = _date_end(filed)
        raw_payload = {
            "cik": cik,
            "statement_type": statement_type.value,
            "start": start,
            "end": end,
            "filed": filed,
            "form": form,
            "accession": accession,
            "values": {name: str(value[1]) for name, value in values.items()},
        }
        content_hash = canonical_content_hash(raw_payload)
        identity = f"{instrument_id}|{statement_type.value}|{end}|{accession}|{content_hash}"
        return NormalizedFinancialStatement(
            statement_id=sha256(identity.encode()).hexdigest(),
            instrument_id=instrument_id,
            market="us_stocks",
            statement_type=statement_type,
            period_type=_period_type(statement_type, start, end, form),
            period_start=start,
            period_end=end,
            fiscal_year_end=end if form in {"10-K", "20-F", "40-F"} else None,
            currency="USD",
            accounting_standard=AccountingStandard.US_GAAP,
            items=tuple(
                FinancialLineItem(
                    canonical_name=name,
                    raw_name=raw_name,
                    value=value,
                    currency="USD",
                    unit=unit,
                    cumulative=statement_type != StatementType.BALANCE_SHEET,
                )
                for name, (raw_name, value, unit) in sorted(values.items())
            ),
            provenance=PointInTimeProvenance(
                source=self.name,
                source_url=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                source_record_id=accession,
                event_at=_date_end(end),
                published_at=published_at,
                available_at=published_at,
                fetched_at=max(fetched_at, published_at),
                revision=accession,
                content_hash=content_hash,
                quality_status="verified",
            ),
        )


class SecCompanyFactsValuationReferenceProvider:
    name = "sec-companyfacts-valuation-references"

    def __init__(
        self,
        client: Any | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client or SecCompanyFactsHttpClient()
        self._clock = clock or (lambda: datetime.now(UTC))

    def fetch_references(self, *, instrument_id: str, as_of: datetime) -> ValuationReferenceData:
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        cik, payload = _facts(self._client, instrument_id)
        fact = ((payload.get("facts") or {}).get("dei") or {}).get(
            "EntityCommonStockSharesOutstanding"
        ) or {}
        units = fact.get("units") if isinstance(fact, Mapping) else {}
        candidates: list[tuple[datetime, date, Decimal, str]] = []
        for entry in units.get("shares", []):
            if not isinstance(entry, Mapping) or not entry.get("filed") or not entry.get("end"):
                continue
            available_at = _date_end(str(entry["filed"]))
            shares_at = date.fromisoformat(str(entry["end"]))
            value = _decimal(entry.get("val"))
            if available_at <= as_of and value is not None and value > 0:
                candidates.append(
                    (available_at, shares_at, value, str(entry.get("accn") or entry["filed"]))
                )
        if not candidates:
            raise RuntimeError("SEC Companyfacts 没有点时有效的流通股本")
        available_at, shares_date, shares, accession = max(
            candidates, key=lambda item: (item[0], item[1])
        )
        fetched_at = self._clock()
        content_hash = canonical_content_hash(
            {
                "instrument_id": instrument_id,
                "shares": shares,
                "shares_date": shares_date,
                "accession": accession,
            }
        )
        return ValuationReferenceData(
            instrument_id=instrument_id,
            shares_outstanding=shares,
            shares_at=_date_end(shares_date),
            historical_values={
                "pe_ttm": (),
                "pb": (),
                "ps": (),
                "dividend_yield": (),
            },
            industry_values={},
            comparable_values={},
            provenance=PointInTimeProvenance(
                source=self.name,
                source_url=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                source_record_id=accession,
                event_at=_date_end(shares_date),
                published_at=available_at,
                available_at=available_at,
                fetched_at=max(fetched_at, available_at),
                revision=accession,
                content_hash=content_hash,
                quality_status="degraded",
                quality_reasons=(
                    "HISTORICAL_VALUATION_UNAVAILABLE",
                    "INDUSTRY_CROSS_SECTION_UNAVAILABLE",
                ),
            ),
        )
