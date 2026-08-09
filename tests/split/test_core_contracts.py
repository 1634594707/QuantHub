from __future__ import annotations

import unittest
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

from pydantic import ValidationError

from packages.data_quality import (
    check_conflicts,
    check_missing,
    check_staleness,
    check_temporal_order,
)
from packages.financial_data import (
    AccountingStandard,
    FinancialStatement,
    StatementType,
    normalize_amount,
    reconcile_statements,
)
from packages.market_data import (
    Candle,
    Instrument,
    Market,
    Provenance,
    canonical_instrument_id,
    normalize_candles,
)
from packages.model_client import (
    ModelRequest,
    ModelResponse,
    RetryingModelClient,
    redact_secrets,
)
from packages.research_protocol import Evidence, EvidenceKind, content_hash
from packages.strategy_package import (
    CompatibilityError,
    PackageValidationError,
    RiskLimits,
    StrategyReleasePackage,
    StrategyReleasePayload,
    create_release_package,
    verify_release_package,
)

NOW = datetime(2026, 8, 3, 8, tzinfo=UTC)


def provenance(source: str = "fixture", revision: str = "1") -> Provenance:
    return Provenance(
        source=source,
        fetched_at=NOW + timedelta(hours=2),
        available_at=NOW + timedelta(hours=1),
        revision=revision,
    )


class MarketDataContractTests(unittest.TestCase):
    def test_instrument_identifier_is_canonical(self) -> None:
        instrument_id = canonical_instrument_id(Market.OKX, "btc/usdt-swap")
        self.assertEqual(instrument_id, "okx:BTC-USDT-SWAP")
        instrument = Instrument(
            instrument_id=instrument_id,
            market=Market.OKX,
            symbol="BTC/USDT-SWAP",
            name="Bitcoin perpetual",
            currency="USD",
            timezone="UTC",
            trading_calendar="24x7",
        )
        self.assertEqual(instrument.protocol_version, "1.0.0")

    def test_candles_are_validated_deduplicated_and_ordered(self) -> None:
        def candle(hour: int, close: float) -> Candle:
            event = NOW + timedelta(hours=hour)
            return Candle(
                instrument_id="okx:BTC-USDT-SWAP",
                interval="1h",
                event_time=event,
                available_at=event + timedelta(seconds=1),
                fetched_at=event + timedelta(seconds=2),
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=10,
                provenance=provenance(),
            )

        rows = normalize_candles([candle(2, 2), candle(1, 1), candle(2, 3)])
        self.assertEqual([row.close for row in rows], [1, 3])
        with self.assertRaises(ValidationError):
            candle(3, 2).model_copy(update={"high": 0}).model_validate(
                candle(3, 2).model_dump() | {"high": 0}
            )


class FinancialAndQualityContractTests(unittest.TestCase):
    def _statement(self, source: str, value: str) -> FinancialStatement:
        return FinancialStatement(
            instrument_id="a_shares:600519",
            statement_type=StatementType.INCOME,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            announced_at=NOW,
            currency="CNY",
            unit="million",
            consolidated=True,
            accounting_standard=AccountingStandard.CAS,
            values={"revenue": Decimal(value)},
            provenance=provenance(source),
        )

    def test_normalization_and_source_conflict_preservation(self) -> None:
        self.assertEqual(normalize_amount("1.25", "million"), Decimal("1250000.00"))
        grouped = reconcile_statements([self._statement("a", "10"), self._statement("b", "11")])
        self.assertEqual(len(next(iter(grouped.values()))), 2)
        self.assertEqual(check_conflicts({"a": 10, "b": 11})[0].code, "source_conflict")

    def test_quality_gates_cover_missing_stale_and_temporal_order(self) -> None:
        self.assertEqual(check_missing({"revenue": None}, ["revenue"])[0].code, "missing_field")
        self.assertEqual(
            check_staleness(NOW, NOW + timedelta(days=400), timedelta(days=365))[0].code,
            "stale_data",
        )
        issues = check_temporal_order(NOW, NOW - timedelta(seconds=1), NOW)
        self.assertEqual(issues[0].code, "future_leakage")


class ResearchAndModelContractTests(unittest.TestCase):
    def test_evidence_separates_fact_computation_and_ai(self) -> None:
        fact = Evidence(
            evidence_id="e1",
            kind=EvidenceKind.FACT,
            title="Revenue",
            value=10,
            source="annual-report",
            observed_at=NOW,
            available_at=NOW,
        )
        self.assertEqual(len(content_hash(fact)), 64)
        with self.assertRaises(ValidationError):
            Evidence(
                evidence_id="e2",
                kind=EvidenceKind.AI_INTERPRETATION,
                title="Summary",
                value="text",
                source="model",
                observed_at=NOW,
                available_at=NOW,
            )

    def test_model_client_redacts_and_retries_transient_errors(self) -> None:
        calls: list[ModelRequest] = []

        def transport(request: ModelRequest) -> ModelResponse:
            calls.append(request)
            if len(calls) == 1:
                raise TimeoutError("retry")
            return ModelResponse(model=request.model, content="ok")

        client = RetryingModelClient(transport, backoff_seconds=0)
        response = client.complete(
            ModelRequest(model="fixture", system="token: abc", prompt="api_key=secret")
        )
        self.assertEqual(response.content, "ok")
        self.assertNotIn("secret", calls[-1].prompt)
        self.assertEqual(redact_secrets("Bearer abc.def"), "Bearer=[REDACTED]")


class StrategyPackageContractTests(unittest.TestCase):
    def _payload(self) -> StrategyReleasePayload:
        formula = "rank(close / delay(close, 24) - 1)"
        return StrategyReleasePayload(
            strategy_id="okx-momentum-1h",
            version="1.0.0",
            target_market="okx",
            product_type="usdt_perpetual",
            runner_compatibility="1.0.0",
            formula=formula,
            formula_hash=sha256(formula.encode()).hexdigest(),
            parameters={"lookback": 24},
            universe={"quote": "USDT", "minimum_listing_days": 180},
            signal_frequency="1h",
            rebalance_frequency="4h",
            data_fields=("open", "high", "low", "close", "volume", "funding_rate"),
            data_delay_seconds=5,
            data_snapshot_id="okx-fixture-20260803",
            research_engine_version="1.0.0",
            out_of_sample_results={"rank_ic": 0.04, "max_drawdown": 0.12},
            cost_assumptions={"fee_bps": 5, "funding_bps": 1, "spread_bps": 2, "slippage_bps": 3},
            risk_limits=RiskLimits(
                max_leverage=2,
                max_symbol_exposure=0.1,
                max_total_exposure=0.5,
                max_loss=1000,
                max_drawdown=0.15,
            ),
            simulation_results={"status": "passed", "orders": 120},
            allowed_environments=("shadow", "demo"),
            approved_by="research-review",
            approved_at=NOW,
            audit_record_ids=("audit-1",),
        )

    def test_signed_package_rejects_tampering_and_incompatible_environment(self) -> None:
        key = b"k" * 32
        package = create_release_package(self._payload(), key)
        restored = verify_release_package(package, key, runner_version="1.2.0", environment="demo")
        self.assertEqual(restored.strategy_id, "okx-momentum-1h")
        tampered = StrategyReleasePackage(
            payload=package.payload.model_copy(update={"parameters": {"lookback": 12}}),
            content_sha256=package.content_sha256,
            signature=package.signature,
        )
        with self.assertRaises(PackageValidationError):
            verify_release_package(tampered, key, runner_version="1.0.0", environment="demo")
        with self.assertRaises(CompatibilityError):
            verify_release_package(package, key, runner_version="2.0.0", environment="demo")
        with self.assertRaises(CompatibilityError):
            verify_release_package(package, key, runner_version="1.0.0", environment="live")


if __name__ == "__main__":
    unittest.main()
