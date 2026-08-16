"""AkShare/Eastmoney adapter for point-in-time A-share financial statements."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

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
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")

_ENDPOINTS = {
    StatementType.INCOME: "stock_profit_sheet_by_report_em",
    StatementType.BALANCE_SHEET: "stock_balance_sheet_by_report_em",
    StatementType.CASH_FLOW: "stock_cash_flow_sheet_by_report_em",
}

_ALIASES: dict[StatementType, tuple[tuple[str, tuple[str, ...]], ...]] = {
    StatementType.INCOME: (
        ("revenue", ("TOTAL_OPERATE_INCOME", "OPERATE_INCOME", "营业总收入", "营业收入")),
        ("operating_profit", ("OPERATE_PROFIT", "营业利润")),
        ("total_profit", ("TOTAL_PROFIT", "利润总额")),
        ("ebitda", ("EBITDA", "息税折旧摊销前利润")),
        ("net_profit", ("PARENT_NETPROFIT", "NETPROFIT", "归属于母公司股东的净利润", "净利润")),
        ("basic_eps", ("BASIC_EPS", "基本每股收益")),
    ),
    StatementType.BALANCE_SHEET: (
        ("cash", ("MONETARYFUNDS", "货币资金")),
        ("accounts_receivable", ("ACCOUNTS_RECE", "应收账款")),
        ("inventory", ("INVENTORY", "存货")),
        ("total_assets", ("TOTAL_ASSETS", "资产总计")),
        ("total_debt", ("TOTAL_LIABILITIES", "负债合计")),
        ("total_equity", ("TOTAL_EQUITY", "TOTAL_PARENT_EQUITY", "所有者权益合计")),
    ),
    StatementType.CASH_FLOW: (
        ("operating_cash_flow", ("NETCASH_OPERATE", "经营活动产生的现金流量净额")),
        ("investing_cash_flow", ("NETCASH_INVEST", "投资活动产生的现金流量净额")),
        ("financing_cash_flow", ("NETCASH_FINANCE", "筹资活动产生的现金流量净额")),
        (
            "capital_expenditure",
            ("CONSTRUCT_LONG_ASSET", "购建固定资产、无形资产和其他长期资产支付的现金"),
        ),
    ),
}


def _akshare_client() -> Any:
    try:
        import akshare as ak
    except ImportError as exc:
        raise ImportError("akshare 未安装，请安装 a_shares 可选依赖") from exc
    return ak


def _eastmoney_symbol(instrument_id: str) -> str:
    symbol = instrument_id.rsplit(":", 1)[-1].strip().upper()
    if not symbol.isdigit() or len(symbol) != 6:
        raise ValueError("A 股财务数据要求 6 位证券代码")
    prefix = (
        "SH"
        if symbol.startswith(("5", "6", "9"))
        else "BJ"
        if symbol.startswith(("4", "8"))
        else "SZ"
    )
    return f"{prefix}{symbol}"


def _first(row: Mapping[str, Any], names: tuple[str, ...]) -> tuple[str, Any] | None:
    for name in names:
        if name in row and not pd.isna(row[name]):
            return name, row[name]
    return None


def _decimal(value: Any) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _timestamp(value: Any, *, conservative_date: bool) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    parsed = pd.Timestamp(value)
    if pd.isna(parsed):
        return None
    is_date_only = isinstance(value, date) and not isinstance(value, datetime)
    if isinstance(value, str):
        is_date_only = len(value.strip()) <= 10
    if conservative_date and parsed.time() == time.min:
        # AkShare commonly materializes date-only announcement fields as midnight Timestamps.
        is_date_only = True
    if is_date_only and conservative_date:
        parsed = pd.Timestamp(datetime.combine(parsed.date(), time(23, 59, 59)))
    value_datetime = parsed.to_pydatetime()
    return (
        value_datetime.replace(tzinfo=_SHANGHAI)
        if value_datetime.tzinfo is None
        else value_datetime.astimezone(_SHANGHAI)
    )


def _period_type(period_end: date) -> FinancialPeriodType:
    return {
        3: FinancialPeriodType.QUARTER,
        6: FinancialPeriodType.HALF_YEAR,
        9: FinancialPeriodType.NINE_MONTH,
        12: FinancialPeriodType.ANNUAL,
    }.get(period_end.month, FinancialPeriodType.QUARTER)


class AkshareFinancialProvider:
    name = "akshare-eastmoney-financials"

    def __init__(
        self,
        client: Any | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._clock = clock or (lambda: datetime.now(UTC))

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = _akshare_client()
        return self._client

    def probe(self) -> FinancialProviderStatus:
        try:
            client = self._get_client()
            capabilities = {
                capability
                for statement_type, capability in (
                    (StatementType.INCOME, FinancialProviderCapability.INCOME_STATEMENT),
                    (StatementType.BALANCE_SHEET, FinancialProviderCapability.BALANCE_SHEET),
                    (StatementType.CASH_FLOW, FinancialProviderCapability.CASH_FLOW),
                )
                if hasattr(client, _ENDPOINTS[statement_type])
            }
            missing = [
                item.value
                for item in (
                    FinancialProviderCapability.INCOME_STATEMENT,
                    FinancialProviderCapability.BALANCE_SHEET,
                    FinancialProviderCapability.CASH_FLOW,
                )
                if item not in capabilities
            ]
            return FinancialProviderStatus(
                provider=self.name,
                market="a_shares",
                capabilities=frozenset(capabilities),
                available=len(capabilities) == 3,
                degraded_reasons=tuple(f"MISSING_CAPABILITY:{item}" for item in missing),
                checked_at=self._clock(),
            )
        except ImportError as exc:
            return FinancialProviderStatus(
                provider=self.name,
                market="a_shares",
                capabilities=frozenset(),
                available=False,
                degraded_reasons=(f"DEPENDENCY_UNAVAILABLE:{exc}",),
                checked_at=self._clock(),
            )

    def fetch_statements(
        self, query: FinancialStatementQuery
    ) -> tuple[NormalizedFinancialStatement, ...]:
        client = self._get_client()
        symbol = _eastmoney_symbol(query.instrument_id)
        fetched_at = self._clock()
        results: list[NormalizedFinancialStatement] = []
        for statement_type in query.statement_types:
            endpoint_name = _ENDPOINTS[statement_type]
            endpoint = getattr(client, endpoint_name, None)
            if endpoint is None:
                continue
            frame = endpoint(symbol=symbol)
            if frame is None or frame.empty:
                continue
            normalized = [
                item
                for raw in frame.to_dict(orient="records")
                if (
                    item := self._normalize_row(
                        query.instrument_id, statement_type, raw, fetched_at
                    )
                )
                is not None
                and item.provenance.available_at <= query.available_as_of
                and (
                    query.announced_after is None
                    or item.provenance.published_at >= query.announced_after
                )
            ]
            results.extend(
                sorted(normalized, key=lambda item: item.period_end, reverse=True)[
                    : query.limit_per_type
                ]
            )
        return tuple(sorted(results, key=lambda item: (item.period_end, item.statement_type)))

    def _normalize_row(
        self,
        instrument_id: str,
        statement_type: StatementType,
        row: Mapping[str, Any],
        fetched_at: datetime,
    ) -> NormalizedFinancialStatement | None:
        period_raw = _first(row, ("REPORT_DATE", "REPORTDATE", "报告日", "报告期"))
        published_raw = _first(row, ("NOTICE_DATE", "UPDATE_DATE", "公告日期", "最新公告日期"))
        if period_raw is None or published_raw is None:
            return None
        period_at = _timestamp(period_raw[1], conservative_date=False)
        published_at = _timestamp(published_raw[1], conservative_date=True)
        if period_at is None or published_at is None:
            return None
        if published_at > fetched_at.astimezone(_SHANGHAI):
            return None
        period_end = period_at.date()
        items: list[FinancialLineItem] = []
        for canonical_name, aliases in _ALIASES[statement_type]:
            matched = _first(row, aliases)
            if matched is None:
                continue
            value = _decimal(matched[1])
            if value is None:
                continue
            items.append(
                FinancialLineItem(
                    canonical_name=canonical_name,
                    raw_name=matched[0],
                    value=value,
                    currency="CNY",
                    cumulative=statement_type != StatementType.BALANCE_SHEET,
                )
            )
        if not items:
            return None
        raw_payload = {
            key: None if pd.isna(value) else value
            for key, value in row.items()
            if isinstance(value, (str, int, float, date, datetime, Decimal)) or value is None
        }
        content_hash = canonical_content_hash(raw_payload)
        revision_value = _first(row, ("UPDATE_DATE", "NOTICE_DATE", "公告日期"))
        revision = str(revision_value[1]) if revision_value else "1"
        identity = f"{instrument_id}:{statement_type.value}:{period_end}:{revision}:{content_hash}"
        statement_id = sha256(identity.encode("utf-8")).hexdigest()
        period_start = (
            period_end
            if statement_type == StatementType.BALANCE_SHEET
            else date(period_end.year, 1, 1)
        )
        return NormalizedFinancialStatement(
            statement_id=statement_id,
            instrument_id=instrument_id,
            market="a_shares",
            statement_type=statement_type,
            period_type=_period_type(period_end),
            period_start=period_start,
            period_end=period_end,
            fiscal_year_end=date(period_end.year, 12, 31),
            currency="CNY",
            consolidated=True,
            accounting_standard=AccountingStandard.CAS,
            items=tuple(items),
            provenance=PointInTimeProvenance(
                source=self.name,
                source_url="https://data.eastmoney.com/bbsj/",
                source_record_id=identity,
                event_at=period_at,
                published_at=published_at,
                available_at=published_at,
                fetched_at=fetched_at,
                revision=revision,
                content_hash=content_hash,
                quality_status="single_source",
                quality_reasons=("SINGLE_SOURCE",),
            ),
        )
