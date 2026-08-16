from __future__ import annotations

import unittest
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import ValidationError
from requests import ConnectionError as RequestsConnectionError

import packages.financial_data.akshare_valuation as valuation_module
from apps.api import store
from apps.api.domains.financials.service import evaluate_fundamentals, evaluate_valuation
from apps.api.domains.research.service import build_export_manifest, build_research_decision
from apps.api.domains.research_data.service import ensure_default_relationships
from core.research_decision import ModuleOpinion, decide_research
from packages.financial_data import (
    AccountingStandard,
    AkshareFinancialProvider,
    AkshareMacroProvider,
    AkshareValuationReferenceProvider,
    FinancialLineItem,
    FinancialPeriodType,
    FinancialStatementQuery,
    HoldingStatus,
    InstrumentRelationship,
    MacroEvent,
    NormalizedFinancialStatement,
    PointInTimeProvenance,
    SecCompanyFactsFinancialProvider,
    SecCompanyFactsValuationReferenceProvider,
    StatementType,
    build_action_guidance,
    build_company_events,
    build_fundamental_snapshot,
    build_macro_transmissions,
    build_ttm_line_items,
    build_valuation_snapshot,
    cumulative_to_single_quarter,
    resolve_statement_conflicts,
    select_available_statements,
)

NOW = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)


class FakeAkshareFinancialClient:
    def __init__(self) -> None:
        self.symbols: list[str] = []

    def _frame(self, **values: object) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "REPORT_DATE": "2026-03-31",
                    "NOTICE_DATE": pd.Timestamp("2026-04-30"),
                    "UPDATE_DATE": pd.Timestamp("2026-04-30"),
                    **values,
                }
            ]
        )

    def stock_profit_sheet_by_report_em(self, *, symbol: str) -> pd.DataFrame:
        self.symbols.append(symbol)
        return self._frame(TOTAL_OPERATE_INCOME=Decimal(100), PARENT_NETPROFIT=Decimal(15))

    def stock_balance_sheet_by_report_em(self, *, symbol: str) -> pd.DataFrame:
        self.symbols.append(symbol)
        return self._frame(
            TOTAL_ASSETS=Decimal(500),
            TOTAL_LIABILITIES=Decimal(200),
            TOTAL_PARENT_EQUITY=Decimal(300),
        )

    def stock_cash_flow_sheet_by_report_em(self, *, symbol: str) -> pd.DataFrame:
        self.symbols.append(symbol)
        return self._frame(NETCASH_OPERATE=Decimal(20), CONSTRUCT_LONG_ASSET=Decimal(5))

    def stock_individual_info_em(self, *, symbol: str) -> pd.DataFrame:
        self.symbols.append(symbol)
        return pd.DataFrame(
            [
                {"item": "总股本", "value": Decimal(1000)},
                {"item": "行业", "value": "饮料制造"},
            ]
        )

    def stock_a_indicator_lg(self, *, symbol: str) -> pd.DataFrame:
        self.symbols.append(symbol)
        return pd.DataFrame(
            [
                {"trade_date": "2026-01-01", "pe_ttm": 10, "pb": 1, "ps_ttm": 2, "dv_ttm": 2},
                {"trade_date": "2026-04-01", "pe_ttm": 15, "pb": 2, "ps_ttm": 3, "dv_ttm": 3},
                {"trade_date": "2026-08-01", "pe_ttm": 20, "pb": 3, "ps_ttm": 4, "dv_ttm": 4},
            ]
        )

    def stock_board_industry_cons_em(self, *, symbol: str) -> pd.DataFrame:
        self.symbols.append(symbol)
        return pd.DataFrame(
            [
                {"代码": "600519", "市净率": 3, "市销率": 4},
                {"代码": "000858", "市净率": 4, "市销率": 5},
            ]
        )


class FlakyAkshareValuationClient(FakeAkshareFinancialClient):
    def __init__(self) -> None:
        super().__init__()
        self.info_attempts = 0

    def stock_individual_info_em(self, *, symbol: str) -> pd.DataFrame:
        self.info_attempts += 1
        if self.info_attempts == 1:
            raise RequestsConnectionError("temporary disconnect")
        return super().stock_individual_info_em(symbol=symbol)


class FallbackAkshareValuationClient:
    def stock_profile_cninfo(self, *, symbol: str) -> pd.DataFrame:
        return pd.DataFrame([{"A股代码": symbol, "所属行业": "饮料制造"}])

    def stock_share_change_cninfo(
        self, *, symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"证券代码": symbol, "公告日期": "2026-04-30", "总股本": Decimal("0.1")},
                {"证券代码": symbol, "公告日期": "2026-08-17", "总股本": Decimal("0.2")},
            ]
        )

    def stock_zh_valuation_baidu(self, *, symbol: str, indicator: str, period: str) -> pd.DataFrame:
        values = [10, 15, 20] if indicator == "市盈率(TTM)" else [1, 2, 3]
        return pd.DataFrame(
            [
                {"date": "2026-01-01", "value": values[0]},
                {"date": "2026-04-01", "value": values[1]},
                {"date": "2026-08-17", "value": values[2]},
            ]
        )


class CircuitFallbackAkshareValuationClient(FallbackAkshareValuationClient):
    def __init__(self) -> None:
        self.info_attempts = 0

    def stock_individual_info_em(self, *, symbol: str) -> pd.DataFrame:
        self.info_attempts += 1
        raise RequestsConnectionError("eastmoney blocked")


class FakeAkshareMacroClient:
    @staticmethod
    def _indicator(value: str, previous: str, *, expected: str | None = None) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "时间": "2026-06-01",
                    "发布日期": "2026-07-15",
                    "现值": value,
                    "前值": previous,
                    "预测值": expected,
                }
            ]
        )

    def macro_bank_usa_interest_rate(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "商品": "美联储利率决议",
                    "日期": "2026-06-30",
                    "今值": "5.00",
                    "预测值": "5.25",
                    "前值": "5.25",
                },
                {
                    "商品": "美联储利率决议",
                    "日期": "2026-09-01",
                    "今值": None,
                    "预测值": "4.75",
                    "前值": "5.00",
                },
            ]
        )

    def macro_bank_euro_interest_rate(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "商品": "欧洲央行利率决议",
                    "日期": "2026-07-24",
                    "今值": "2.00",
                    "预测值": "2.00",
                    "前值": "2.25",
                }
            ]
        )

    def macro_bank_china_interest_rate(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "商品": "中国人民银行利率决议",
                    "日期": "2026-07-20",
                    "今值": "3.00",
                    "预测值": "3.10",
                    "前值": "3.10",
                }
            ]
        )

    def macro_usa_cpi_yoy(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "时间": "2026-06-01",
                    "发布日期": "2026-07-15",
                    "现值": "2.8",
                    "前值": "3.0",
                },
                {
                    "时间": "2026-07-01",
                    "发布日期": "2026-08-20",
                    "现值": "2.7",
                    "前值": "2.8",
                },
            ]
        )

    def macro_usa_ppi(self) -> pd.DataFrame:
        return self._indicator("2.5", "2.7", expected="2.6")

    def macro_usa_non_farm(self) -> pd.DataFrame:
        return self._indicator("18", "15", expected="16")

    def macro_usa_unemployment_rate(self) -> pd.DataFrame:
        return self._indicator("4.1", "4.2", expected="4.2")

    def macro_usa_gdp_monthly(self) -> pd.DataFrame:
        return self._indicator("2.9", "2.7", expected="2.8")

    def macro_usa_ism_pmi(self) -> pd.DataFrame:
        return self._indicator("51", "49", expected="50")

    def macro_usa_retail_sales(self) -> pd.DataFrame:
        return self._indicator("0.8", "0.4", expected="0.5")


class FakeSecCompanyFactsClient:
    def company_tickers(self) -> dict[str, dict[str, object]]:
        return {"0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."}}

    def company_facts(self, cik: str) -> dict[str, object]:
        assert cik == "0000320193"

        def entries(values: tuple[tuple[str, str, str, int], ...], *, unit: str = "USD") -> dict:
            return {
                "label": "Fixture fact",
                "units": {
                    unit: [
                        {
                            "start": start,
                            "end": end,
                            "filed": filed,
                            "form": "10-Q",
                            "accn": f"fixture-{end}",
                            "val": value,
                        }
                        for start, end, filed, value in values
                    ]
                },
            }

        periods = (
            ("2026-01-01", "2026-03-31", "2026-04-30", 100),
            ("2026-01-01", "2026-06-30", "2026-07-31", 230),
        )
        balance_periods = (
            ("2026-03-31", "2026-03-31", "2026-04-30", 500),
            ("2026-06-30", "2026-06-30", "2026-07-31", 540),
        )
        return {
            "facts": {
                "us-gaap": {
                    "Revenues": entries(periods),
                    "NetIncomeLoss": entries(tuple((*row[:3], row[3] // 10) for row in periods)),
                    "Assets": entries(balance_periods),
                    "Liabilities": entries(tuple((*row[:3], 200) for row in balance_periods)),
                    "StockholdersEquity": entries(
                        tuple((*row[:3], 300) for row in balance_periods)
                    ),
                    "NetCashProvidedByUsedInOperatingActivities": entries(
                        tuple((*row[:3], row[3] // 8) for row in periods)
                    ),
                    "PaymentsToAcquirePropertyPlantAndEquipment": entries(
                        tuple((*row[:3], row[3] // 20) for row in periods)
                    ),
                },
                "dei": {
                    "EntityCommonStockSharesOutstanding": {
                        "units": {
                            "shares": [
                                {
                                    "end": "2026-06-30",
                                    "filed": "2026-07-31",
                                    "form": "10-Q",
                                    "accn": "fixture-2026-06-30",
                                    "val": 15000000000,
                                }
                            ]
                        }
                    }
                },
            }
        }


def provenance(*, available_at: datetime = NOW, revision: str = "1") -> PointInTimeProvenance:
    return PointInTimeProvenance(
        source="fixture",
        source_url="https://example.test/statement",
        published_at=available_at - timedelta(minutes=1),
        available_at=available_at,
        fetched_at=available_at + timedelta(minutes=1),
        revision=revision,
        content_hash="a" * 64,
    )


def statement(
    statement_id: str,
    *,
    period_end: date,
    available_at: datetime = NOW,
    values: dict[str, Decimal],
    cumulative: bool = False,
    statement_type: StatementType = StatementType.INCOME,
) -> NormalizedFinancialStatement:
    return NormalizedFinancialStatement(
        statement_id=statement_id,
        instrument_id="a_shares:600519",
        market="a_shares",
        statement_type=statement_type,
        period_type=FinancialPeriodType.QUARTER,
        period_start=date(period_end.year, 1, 1),
        period_end=period_end,
        currency="CNY",
        accounting_standard=AccountingStandard.CAS,
        items=tuple(
            FinancialLineItem(
                canonical_name=key,
                raw_name=key,
                value=value,
                currency="CNY",
                cumulative=cumulative,
            )
            for key, value in values.items()
        ),
        provenance=provenance(available_at=available_at),
    )


class StockResearchContractTests(unittest.TestCase):
    def test_export_manifest_records_cutoff_methods_sources_and_disclaimer(self) -> None:
        manifest = build_export_manifest(
            {
                "updated_at": NOW.timestamp(),
                "evidence": [
                    {
                        "id": "evidence-1",
                        "kind": "fundamental_snapshot",
                        "title": "财务快照",
                        "source": "sec-companyfacts-financials",
                        "uri": "https://example.test/evidence",
                        "captured_at": NOW.timestamp(),
                        "payload": {
                            "method_version": "fundamental-analysis-v1",
                            "provenance": {
                                "available_at": "2026-08-15T23:59:59-04:00",
                                "revision": "fixture-accession",
                                "content_hash": "b" * 64,
                            },
                        },
                    }
                ],
            }
        )
        self.assertEqual(manifest["data_cutoff"], "2026-08-15T23:59:59-04:00")
        self.assertIn("fundamental-analysis-v1", manifest["method_versions"])
        self.assertEqual(manifest["evidence_manifest"][0]["revision"], "fixture-accession")
        self.assertIn("不构成投资建议", manifest["disclaimer"])

    def test_sec_companyfacts_maps_us_gaap_and_filters_by_filing_date(self) -> None:
        provider = SecCompanyFactsFinancialProvider(FakeSecCompanyFactsClient(), clock=lambda: NOW)
        self.assertTrue(provider.probe().available)
        before_q2 = provider.fetch_statements(
            FinancialStatementQuery(
                instrument_id="us_stocks:AAPL",
                available_as_of=datetime(2026, 7, 1, tzinfo=UTC),
            )
        )
        after_q2 = provider.fetch_statements(
            FinancialStatementQuery(
                instrument_id="us_stocks:AAPL",
                available_as_of=NOW,
            )
        )
        self.assertEqual({item.period_end for item in before_q2}, {date(2026, 3, 31)})
        self.assertEqual(
            {item.statement_type for item in after_q2},
            {StatementType.INCOME, StatementType.BALANCE_SHEET, StatementType.CASH_FLOW},
        )
        self.assertTrue(
            all(item.accounting_standard == AccountingStandard.US_GAAP for item in after_q2)
        )
        revenue = next(
            line
            for item in after_q2
            if item.statement_type == StatementType.INCOME and item.period_end == date(2026, 6, 30)
            for line in item.items
            if line.canonical_name == "revenue"
        )
        self.assertEqual(revenue.raw_name, "Revenues")
        self.assertEqual(revenue.value, Decimal(230))
        self.assertEqual(
            next(
                item for item in after_q2 if item.period_end == date(2026, 6, 30)
            ).provenance.available_at.hour,
            23,
        )

    def test_us_stock_fundamentals_and_valuation_use_sec_without_fake_percentiles(self) -> None:
        client = FakeSecCompanyFactsClient()
        fundamentals = evaluate_fundamentals(
            instrument_id="us_stocks:AAPL",
            market="us_stocks",
            as_of=NOW,
            provider=SecCompanyFactsFinancialProvider(client, clock=lambda: NOW),
        )
        self.assertEqual(fundamentals["instrument_id"], "us_stocks:AAPL")
        valuation = evaluate_valuation(
            instrument_id="us_stocks:AAPL",
            market="us_stocks",
            price=Decimal(200),
            price_at=NOW,
            as_of=NOW,
            provider=SecCompanyFactsValuationReferenceProvider(client, clock=lambda: NOW),
        )
        pb = next(item for item in valuation["metrics"] if item["key"] == "pb")
        self.assertTrue(pb["applicable"])
        self.assertIsNone(pb["historical_percentile"])
        self.assertEqual(valuation["valuation_range"], "insufficient")
        self.assertFalse(valuation["execution_eligible"])
        self.assertIn(
            "HISTORICAL_VALUATION_UNAVAILABLE",
            valuation["provenance"]["quality_reasons"],
        )

    def test_company_events_classify_deduplicate_and_use_conservative_dates(self) -> None:
        events = build_company_events(
            instrument_id="a_shares:600519",
            news_items=(
                {
                    "title": "贵州茅台净利润增长",
                    "summary": "聚合转载",
                    "source": "news-aggregator",
                    "ts": "2026-08-15",
                    "entities": [{"text": "贵州茅台", "type": "org"}],
                },
            ),
            announcements=(
                {
                    "title": "贵州茅台净利润增长",
                    "content": "交易所正式公告",
                    "source": "exchange",
                    "ts": "2026-08-15",
                    "ann_type": "业绩公告",
                    "products": ["飞天茅台"],
                    "supply_chain": ["高粱采购"],
                },
            ),
            fetched_at=NOW,
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].category, "earnings")
        self.assertEqual(events[0].direction.value, "positive")
        self.assertEqual(events[0].provenance.published_at.hour, 23)
        self.assertEqual(events[0].provenance.published_at.tzinfo, ZoneInfo("Asia/Shanghai"))
        self.assertEqual(events[0].verification_status, "verified")
        self.assertEqual(events[1].verification_status, "pending")
        self.assertIsNone(events[0].repost_of)
        self.assertEqual(events[1].repost_of, events[0].event_id)
        self.assertEqual({item.verification_status for item in events}, {"pending", "verified"})
        self.assertTrue(
            {("product", "飞天茅台"), ("supply_chain", "高粱采购")}.issubset(
                {(item.entity_type, item.name) for item in events[0].related_entities}
            )
        )

    def test_macro_provider_separates_released_scheduled_and_point_in_time_data(self) -> None:
        provider = AkshareMacroProvider(FakeAkshareMacroClient(), clock=lambda: NOW)
        events = provider.fetch_events(as_of=NOW)
        released = [item for item in events if item.state == "released"]
        scheduled = [item for item in events if item.state == "scheduled"]
        self.assertEqual(
            {item.category for item in released},
            {"central_bank", "cpi", "ppi", "employment", "gdp", "pmi", "retail"},
        )
        self.assertEqual(
            {item.region for item in released if item.category == "central_bank"},
            {"US", "EU", "CN"},
        )
        self.assertEqual(len(scheduled), 1)
        self.assertIsNone(scheduled[0].actual_value)
        self.assertGreater(scheduled[0].provenance.event_at, NOW)
        self.assertLessEqual(scheduled[0].provenance.available_at, NOW)
        self.assertEqual(
            next(
                item for item in released if item.category == "central_bank" and item.region == "US"
            ).direction.value,
            "positive",
        )

        historical_cutoff = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
        historical = provider.fetch_events(as_of=historical_cutoff)
        self.assertEqual({item.category for item in historical}, {"central_bank"})
        self.assertTrue(
            all(item.provenance.available_at <= historical_cutoff for item in historical)
        )

    def test_macro_revisions_are_immutable_and_filtered_by_available_time(self) -> None:
        first_available = datetime(2026, 7, 15, 15, 59, 59, tzinfo=UTC)
        revised_available = datetime(2026, 8, 15, 15, 59, 59, tzinfo=UTC)

        def macro_event(
            event_id: str, state: str, actual: str, available_at: datetime
        ) -> MacroEvent:
            return MacroEvent(
                event_id=event_id,
                region="US",
                category="cpi",
                title="美国 CPI 同比",
                state=state,
                previous_value=Decimal("3.0"),
                actual_value=Decimal(actual),
                revised_value=Decimal(actual) if state == "revised" else None,
                unit="%",
                provenance=provenance(available_at=available_at, revision=state),
            )

        first = macro_event("macro-cpi-initial", "released", "2.8", first_available)
        revised = macro_event("macro-cpi-revised", "revised", "2.7", revised_available)
        self.assertTrue(store.save_macro_event(first.model_dump(mode="json")))
        self.assertTrue(store.save_macro_event(revised.model_dump(mode="json")))
        initial_view = store.list_macro_events(
            available_as_of=datetime(2026, 8, 1, tzinfo=UTC), region="US"
        )
        revised_view = store.list_macro_events(available_as_of=NOW, region="US")
        self.assertEqual([item["event_id"] for item in initial_view], [first.event_id])
        self.assertEqual(
            {item["event_id"] for item in revised_view}, {first.event_id, revised.event_id}
        )

    def test_macro_transmission_requires_relationship_and_is_owner_scoped(self) -> None:
        event = MacroEvent(
            event_id="macro-rate-cut",
            region="US",
            category="central_bank",
            title="美联储降息",
            state="released",
            previous_value=Decimal("5.25"),
            expected_value=Decimal("5.00"),
            actual_value=Decimal("4.75"),
            unit="%",
            direction="positive",
            provenance=provenance(),
        )
        relationship = InstrumentRelationship(
            relationship_id="relationship-rate-sensitive",
            instrument_id="a_shares:600519",
            target_type="rate",
            target_key="USD policy rate",
            relation_source="fact",
            direction="negative",
            strength=0.8,
            valid_from=NOW - timedelta(days=365),
            provenance=provenance(),
        )
        self.assertEqual(build_macro_transmissions(events=(event,), relationships=()), ())
        transmissions = build_macro_transmissions(events=(event,), relationships=(relationship,))
        self.assertEqual(len(transmissions), 1)
        self.assertEqual(transmissions[0].channel, "rates")
        self.assertEqual(transmissions[0].direction.value, "negative")
        payload = transmissions[0].model_dump(mode="json")
        self.assertTrue(store.save_macro_transmission(payload, owner_id="macro-alice"))
        self.assertTrue(store.save_macro_transmission(payload, owner_id="macro-bob"))
        self.assertEqual(
            len(store.list_macro_transmissions("a_shares:600519", owner_id="macro-alice")),
            1,
        )
        self.assertEqual(
            store.list_macro_transmissions("a_shares:600519", owner_id="macro-charlie"),
            [],
        )

    def test_default_market_relationships_are_versioned_and_idempotent(self) -> None:
        instrument_id = "us_stocks:DEFAULT-SEED-FIXTURE"
        owner_id = "default-seed-owner"
        inserted = ensure_default_relationships(
            instrument_id=instrument_id,
            market="us_stocks",
            owner_id=owner_id,
            as_of=NOW,
        )
        repeated = ensure_default_relationships(
            instrument_id=instrument_id,
            market="us_stocks",
            owner_id=owner_id,
            as_of=NOW,
        )
        relationships = store.list_instrument_relationships(
            instrument_id,
            as_of=NOW,
            owner_id=owner_id,
        )
        self.assertEqual(inserted, 4)
        self.assertEqual(repeated, 0)
        self.assertEqual(len(relationships), 4)
        self.assertTrue(
            all(item["method_version"] == "default-relationships-1.0.0" for item in relationships)
        )
        self.assertTrue(all(item["relation_source"] == "model" for item in relationships))

    def test_akshare_provider_maps_three_statements_and_conservative_notice_time(self) -> None:
        client = FakeAkshareFinancialClient()
        provider = AkshareFinancialProvider(client, clock=lambda: NOW)
        self.assertTrue(provider.probe().available)
        statements = provider.fetch_statements(
            FinancialStatementQuery(
                instrument_id="a_shares:600519",
                available_as_of=NOW,
            )
        )
        self.assertEqual(len(statements), 3)
        self.assertEqual(client.symbols, ["SH600519", "SH600519", "SH600519"])
        self.assertEqual(
            {item.statement_type for item in statements},
            {StatementType.INCOME, StatementType.BALANCE_SHEET, StatementType.CASH_FLOW},
        )
        self.assertTrue(all(item.provenance.available_at.hour == 23 for item in statements))

    def test_financial_store_is_immutable_and_filters_by_available_time(self) -> None:
        statement_row = AkshareFinancialProvider(
            FakeAkshareFinancialClient(), clock=lambda: NOW
        ).fetch_statements(
            FinancialStatementQuery(
                instrument_id="a_shares:600519",
                statement_types=(StatementType.INCOME,),
                available_as_of=NOW,
            )
        )[0]
        payload = statement_row.model_dump(mode="json")
        self.assertTrue(store.save_financial_statement(payload))
        self.assertFalse(store.save_financial_statement(payload))
        before = store.list_financial_statements(
            "a_shares:600519",
            available_as_of=datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
        )
        after = store.list_financial_statements("a_shares:600519", available_as_of=NOW)
        self.assertEqual(before, [])
        self.assertEqual([item["statement_id"] for item in after], [statement_row.statement_id])

    def test_financial_and_valuation_services_form_a_persisted_point_in_time_loop(self) -> None:
        client = FakeAkshareFinancialClient()
        fundamentals = evaluate_fundamentals(
            instrument_id="a_shares:000333",
            market="a_shares",
            as_of=NOW,
            provider=AkshareFinancialProvider(client, clock=lambda: NOW),
        )
        self.assertEqual(fundamentals["instrument_id"], "a_shares:000333")
        valuation = evaluate_valuation(
            instrument_id="a_shares:000333",
            market="a_shares",
            price=Decimal(20),
            price_at=NOW,
            as_of=NOW,
            provider=AkshareValuationReferenceProvider(client, clock=lambda: NOW),
        )
        pb = next(item for item in valuation["metrics"] if item["key"] == "pb")
        pe = next(item for item in valuation["metrics"] if item["key"] == "pe_ttm")
        self.assertEqual(Decimal(pb["value"]), Decimal(200) / Decimal(3))
        self.assertFalse(pe["applicable"])
        self.assertEqual(valuation["direction"], "short")
        persisted = store.list_valuation_snapshots("a_shares:000333", as_of=NOW)
        self.assertEqual(persisted[0]["snapshot_id"], valuation["snapshot_id"])

    def test_valuation_provider_retries_transient_network_disconnects(self) -> None:
        client = FlakyAkshareValuationClient()
        references = AkshareValuationReferenceProvider(client, clock=lambda: NOW).fetch_references(
            instrument_id="a_shares:600519",
            as_of=NOW,
        )
        self.assertEqual(client.info_attempts, 2)
        self.assertEqual(references.shares_outstanding, Decimal(1000))

    def test_valuation_provider_falls_back_to_point_in_time_cninfo_and_baidu(self) -> None:
        references = AkshareValuationReferenceProvider(
            FallbackAkshareValuationClient(), clock=lambda: NOW
        ).fetch_references(instrument_id="a_shares:600519", as_of=NOW)
        self.assertEqual(references.shares_outstanding, Decimal(1000))
        self.assertEqual(references.historical_values["pe_ttm"], (Decimal(10), Decimal(15)))
        self.assertEqual(references.historical_values["pb"], (Decimal(1), Decimal(2)))
        self.assertEqual(references.comparable_group.industry, "饮料制造")
        self.assertEqual(references.comparable_group.members, ())
        self.assertEqual(references.provenance.quality_status, "degraded")

    def test_valuation_provider_opens_circuit_after_repeated_eastmoney_failures(self) -> None:
        valuation_module._circuit_failures.clear()
        client = CircuitFallbackAkshareValuationClient()
        provider = AkshareValuationReferenceProvider(client, clock=lambda: NOW)
        provider.fetch_references(instrument_id="a_shares:600519", as_of=NOW)
        provider.fetch_references(instrument_id="a_shares:600519", as_of=NOW)
        self.assertEqual(client.info_attempts, 6)
        third = provider.fetch_references(instrument_id="a_shares:600519", as_of=NOW)
        self.assertEqual(client.info_attempts, 6)
        self.assertIn("FALLBACK_CNINFO_SHARE_PROFILE", third.provenance.quality_reasons)

    def test_point_in_time_selection_excludes_future_and_keeps_visible_revision(self) -> None:
        old = statement("old", period_end=date(2026, 3, 31), values={"revenue": Decimal(10)})
        future = statement(
            "future",
            period_end=date(2026, 6, 30),
            available_at=NOW + timedelta(days=1),
            values={"revenue": Decimal(20)},
        )
        self.assertEqual(select_available_statements((future, old), as_of=NOW), (old,))

    def test_cumulative_quarter_conversion_is_deterministic_and_fails_closed(self) -> None:
        q1 = statement(
            "q1", period_end=date(2026, 3, 31), values={"revenue": Decimal(10)}, cumulative=True
        )
        q2 = statement(
            "q2", period_end=date(2026, 6, 30), values={"revenue": Decimal(26)}, cumulative=True
        )
        converted = cumulative_to_single_quarter(q2, q1)
        self.assertEqual(converted[0].value, Decimal(16))
        self.assertEqual(converted[0].conversion_status, "converted")
        missing = cumulative_to_single_quarter(q2, None)
        self.assertIsNone(missing[0].value)
        self.assertEqual(missing[0].conversion_status, "not_convertible")

    def test_ttm_requires_four_complete_single_quarters(self) -> None:
        quarters = tuple(
            (
                FinancialLineItem(
                    canonical_name="revenue",
                    raw_name="revenue",
                    value=Decimal(value),
                    currency="CNY",
                ),
            )
            for value in (10, 20, 30, 40)
        )
        ttm = build_ttm_line_items(quarters)
        self.assertEqual(ttm[0].value, Decimal(100))
        with self.assertRaisesRegex(ValueError, "exactly four"):
            build_ttm_line_items(quarters[:3])

    def test_source_conflicts_are_preserved_until_priority_is_explicit(self) -> None:
        primary = statement(
            "primary", period_end=date(2026, 3, 31), values={"revenue": Decimal(10)}
        )
        secondary = primary.model_copy(
            update={
                "statement_id": "secondary",
                "provenance": primary.provenance.model_copy(update={"source": "secondary"}),
            }
        )
        visible = select_available_statements((secondary, primary), as_of=NOW)
        self.assertEqual({item.statement_id for item in visible}, {"primary", "secondary"})
        adopted = resolve_statement_conflicts(visible, source_priority=("secondary", "fixture"))
        self.assertEqual([item.statement_id for item in adopted], ["secondary"])

    def test_fundamental_snapshot_detects_profit_cash_divergence(self) -> None:
        q1 = statement(
            "q1",
            period_end=date(2026, 3, 31),
            values={
                "revenue": Decimal(100),
                "net_profit": Decimal(10),
                "operating_cash_flow": Decimal(8),
            },
        )
        q2 = statement(
            "q2",
            period_end=date(2026, 6, 30),
            values={
                "revenue": Decimal(120),
                "net_profit": Decimal(15),
                "operating_cash_flow": Decimal(-2),
            },
        )
        snapshot = build_fundamental_snapshot(
            snapshot_id="fund-1", instrument_id="a_shares:600519", statements=(q1, q2), as_of=NOW
        )
        self.assertEqual(snapshot.earnings_trend, "improving")
        self.assertIn("PROFIT_CASH_FLOW_DIVERGENCE", snapshot.anomalies)
        self.assertEqual(snapshot.cash_flow_quality, "weak")

    def test_valuation_rejects_negative_earnings_pe(self) -> None:
        snapshot = build_valuation_snapshot(
            snapshot_id="val-1",
            instrument_id="a_shares:688256",
            as_of=NOW,
            price=Decimal(20),
            price_at=NOW,
            shares_outstanding=Decimal(100),
            shares_at=NOW,
            currency="CNY",
            denominators={"net_profit_ttm": (Decimal(-5), date(2026, 6, 30))},
            historical_values={},
            industry_values={},
            comparable_values={},
            comparable_group=None,
            provenance=provenance(),
        )
        pe = next(item for item in snapshot.metrics if item.key == "pe_ttm")
        self.assertFalse(pe.applicable)
        self.assertIsNone(pe.value)

    def test_required_financial_modules_fail_closed(self) -> None:
        decision = decide_research(
            [ModuleOpinion(module="price_structure", direction="long")],
            required_modules=["fundamentals", "valuation"],
        )
        self.assertEqual(decision.direction, "insufficient")
        self.assertFalse(decision.execution_eligible)
        self.assertEqual(
            {item.module for item in decision.module_opinions},
            {"price_structure", "fundamentals", "valuation"},
        )

    def test_research_run_cannot_pass_when_configured_financial_evidence_is_missing(self) -> None:
        result = build_research_decision(
            {
                "modules": ["fundamentals", "valuation"],
                "summary": {
                    "market": {
                        "quantitative": {
                            "dimensions": {
                                "trend": {"signal": "上涨", "score": 80, "evidence": "趋势向上"}
                            }
                        }
                    },
                    "ensemble": {
                        "ok": True,
                        "consensus": {"direction": "buy", "confidence": 0.8},
                    },
                },
                "evidence": [],
            }
        )
        self.assertEqual(result["direction"], "insufficient")
        self.assertFalse(result["execution_eligible"])
        missing = {
            item["module"] for item in result["module_opinions"] if item["status"] == "missing"
        }
        self.assertEqual(missing, {"fundamentals", "valuation"})

    def test_research_run_fails_closed_when_configured_event_evidence_is_missing(self) -> None:
        result = build_research_decision(
            {
                "modules": ["announcements", "macro"],
                "summary": {
                    "market": {
                        "quantitative": {
                            "dimensions": {
                                "trend": {
                                    "signal": "上涨",
                                    "score": 80,
                                    "evidence": "趋势向上",
                                }
                            }
                        }
                    },
                    "ensemble": {
                        "ok": True,
                        "consensus": {"direction": "buy", "confidence": 0.8},
                    },
                },
                "evidence": [],
            }
        )
        self.assertEqual(result["direction"], "insufficient")
        self.assertFalse(result["execution_eligible"])
        missing = {
            item["module"] for item in result["module_opinions"] if item["status"] == "missing"
        }
        self.assertTrue({"company_events", "macro"}.issubset(missing))

    def test_guidance_changes_action_for_holding_without_changing_decision(self) -> None:
        decision = decide_research(
            [
                ModuleOpinion(module="fundamentals", direction="short", reason="盈利恶化"),
                ModuleOpinion(module="valuation", direction="short", reason="估值仍高"),
            ],
            reevaluate_triggers=["下一期财报发布"],
        )
        coverage = {"fundamentals": "covered", "valuation": "covered"}
        held = build_action_guidance(
            decision,
            holding_status=HoldingStatus.HELD,
            evidence_coverage=coverage,
            review_at=NOW + timedelta(days=30),
        )
        not_held = build_action_guidance(
            decision,
            holding_status=HoldingStatus.NOT_HELD,
            evidence_coverage=coverage,
            review_at=NOW + timedelta(days=30),
        )
        self.assertEqual(held.status, "reduce_risk")
        self.assertEqual(not_held.status, "exit_watch")
        self.assertTrue(held.execution_eligible)

    def test_point_in_time_contract_rejects_naive_timestamps(self) -> None:
        with self.assertRaises(ValidationError):
            provenance(available_at=NOW.replace(tzinfo=None))


if __name__ == "__main__":
    unittest.main()
