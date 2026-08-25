from __future__ import annotations

import base64
import io
import itertools
import zipfile
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from apps.api import store
from apps.api.domains.factor_research.universe_import import parse_universe_file
from apps.api.domains.instrument import service as instrument_service
from apps.api.domains.simulation import service as simulation_service
from apps.api.domains.simulation.risk import PaperOrderIntent, evaluate_risk
from apps.api.domains.simulation.schemas import SimulationOrderCreate
from core.cost_profiles import select_reference_profile
from core.research_decision import ModuleOpinion, decide_research, normalize_direction


def _opinion(module: str, direction: str) -> ModuleOpinion:
    if direction == "insufficient":
        return ModuleOpinion(
            module=module,
            direction="insufficient",
            status="missing",
            reason="fixture missing",
        )
    return ModuleOpinion(module=module, direction=direction)


@pytest.mark.parametrize(
    ("left", "right"), itertools.product(("long", "short", "neutral", "insufficient"), repeat=2)
)
def test_research_decision_matrix_is_symmetric_and_fail_closed(left: str, right: str) -> None:
    decision = decide_research([_opinion("price", left), _opinion("model", right)])
    reverse = decide_research([_opinion("price", right), _opinion("model", left)])

    assert decision.direction == reverse.direction
    if {left, right} == {"long", "short"} or (
        "neutral" in {left, right} and ({left, right} & {"long", "short"})
    ):
        assert decision.direction == "conflicted"
    elif "insufficient" in {left, right}:
        assert decision.direction == "insufficient"
    elif left == right == "long":
        assert decision.direction == "long"
    elif left == right == "short":
        assert decision.direction == "short"
    else:
        assert decision.direction == "neutral"
    assert decision.execution_eligible is (left == right and left in {"long", "short"})


def test_direction_normalization_does_not_guess_unknown_text() -> None:
    assert normalize_direction("偏强") == "long"
    assert normalize_direction("bearish") == "short"
    assert normalize_direction("maybe") == "insufficient"


@pytest.mark.parametrize("market", ["a_shares", "us_stocks", "crypto"])
def test_reference_cost_profiles_are_complete_and_immutable(market: str) -> None:
    profile = select_reference_profile(market)
    first = profile.immutable_snapshot()
    second = select_reference_profile(
        market, profile_id=profile.profile_id, version=profile.version
    ).immutable_snapshot()
    assert first["complete"] is True
    assert first["content_hash"] == second["content_hash"]
    assert first["gaps"] == {"components": [], "constraints": []}


def _risk_fixture(*, now: datetime) -> dict:
    return {
        "market_snapshot": {
            "price": 100.0,
            "source": "tencent",
            "primary_source": "tencent",
            "source_role": "primary",
            "cache_status": "miss",
            "transport": "online",
            "data_semantics": "bar_snapshot",
            "bar_at": now.isoformat(),
            "observed_at": now.isoformat(),
            "quality_status": "verified",
        },
        "account_snapshot": {
            "observed_at": now.isoformat(),
            "reconciled": True,
            "equity": 1_000.0,
            "cash": 1_000.0,
            "positions": [],
        },
        "open_orders": [],
        "cost_profile": {
            "profile_id": "us-stocks-reference",
            "version": "1.0.0",
            "market": "us_stocks",
            "complete": True,
            "gaps": [],
            "total_transaction_cost_bps": 10.0,
            "execution_constraints": [
                {"key": "quantity_step", "value": 0.1},
                {"key": "price_tick", "value": 0.01},
            ],
        },
        "now": now,
    }


def test_simulation_risk_rejects_missing_stale_and_changed_inputs() -> None:
    now = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
    intent = PaperOrderIntent(
        intent_id="risk-1",
        account_id="paper",
        symbol="AAPL",
        market="us_stocks",
        side="buy",
        order_type="limit",
        quantity=1,
        limit_price=101,
    )
    approved = evaluate_risk(intent, **_risk_fixture(now=now))
    assert approved["can_submit"] is True

    missing = _risk_fixture(now=now)
    missing["market_snapshot"]["price"] = None
    rejected = evaluate_risk(intent, **missing)
    assert rejected["can_submit"] is False
    assert "MARKET_PRICE_MISSING" in rejected["reason_codes"]

    stale = _risk_fixture(now=now)
    stale["account_snapshot"]["observed_at"] = (now - timedelta(minutes=5)).isoformat()
    rejected = evaluate_risk(intent, **stale)
    assert "ACCOUNT_SNAPSHOT_STALE" in rejected["reason_codes"]

    changed = _risk_fixture(now=now)
    changed["account_snapshot"]["cash"] = 50.0
    rejected = evaluate_risk(intent, **changed)
    assert "INSUFFICIENT_CASH" in rejected["reason_codes"]
    assert rejected["input_fingerprint"] != approved["input_fingerprint"]


def test_simulation_risk_rejects_degraded_or_historical_market_snapshot() -> None:
    now = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
    intent = PaperOrderIntent(
        intent_id="risk-source",
        account_id="paper",
        symbol="AAPL",
        market="us_stocks",
        side="buy",
        order_type="limit",
        quantity=1,
        limit_price=101,
    )

    local = _risk_fixture(now=now)
    local["market_snapshot"].update({"source": "local_parquet", "quality_status": "closed_bar"})
    rejected = evaluate_risk(intent, **local)
    assert rejected["can_submit"] is False
    assert "MARKET_PRICE_SOURCE" in rejected["reason_codes"]

    degraded = _risk_fixture(now=now)
    degraded["market_snapshot"]["quality_status"] = "available"
    rejected = evaluate_risk(intent, **degraded)
    assert rejected["can_submit"] is False
    assert "MARKET_PRICE_QUALITY" in rejected["reason_codes"]

    stale_bar = _risk_fixture(now=now)
    stale_bar["market_snapshot"].update(
        {
            "bar_at": (now - timedelta(minutes=6)).isoformat(),
            "observed_at": now.isoformat(),
        }
    )
    rejected = evaluate_risk(intent, **stale_bar)
    assert rejected["can_submit"] is False
    assert "MARKET_PRICE_STALE" in rejected["reason_codes"]


def test_simulation_risk_rejects_cache_synthetic_and_forged_primary_provenance() -> None:
    now = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
    intent = PaperOrderIntent(
        intent_id="risk-provenance",
        account_id="paper",
        symbol="AAPL",
        market="us_stocks",
        side="buy",
        order_type="limit",
        quantity=1,
        limit_price=101,
    )

    cached = _risk_fixture(now=now)
    cached["market_snapshot"].update(
        {
            "source_role": "primary_cache",
            "cache_status": "hit",
            "transport": "cache",
            "quality_status": "cached_primary",
        }
    )
    rejected = evaluate_risk(intent, **cached)
    assert rejected["can_submit"] is False
    assert {"MARKET_PRICE_SOURCE", "MARKET_PRICE_CACHE", "MARKET_PRICE_QUALITY"} <= set(
        rejected["reason_codes"]
    )

    synthetic = _risk_fixture(now=now)
    synthetic["market_snapshot"].update(
        {
            "source": "synthetic",
            "primary_source": "synthetic",
            "source_role": "primary",
            "cache_status": "miss",
            "transport": "online",
            "quality_status": "verified",
        }
    )
    rejected = evaluate_risk(intent, **synthetic)
    assert rejected["can_submit"] is False
    assert "MARKET_PRICE_SOURCE" in rejected["reason_codes"]

    forged = _risk_fixture(now=now)
    forged["market_snapshot"].update(
        {
            "source": "yahoo",
            "primary_source": "yahoo",
            "source_role": "primary",
            "cache_status": "miss",
            "transport": "online",
            "quality_status": "verified",
        }
    )
    rejected = evaluate_risk(intent, **forged)
    assert rejected["can_submit"] is False
    assert "MARKET_PRICE_SOURCE" in rejected["reason_codes"]


def test_factor_factory_historical_closed_bar_exception_is_explicit_and_narrow() -> None:
    now = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
    fixture = _risk_fixture(now=now)
    intent = PaperOrderIntent(
        intent_id="factor-history",
        account_id="factor-factory:run-001",
        symbol="AAPL",
        market="us_stocks",
        side="buy",
        order_type="market",
        quantity=1,
    )
    fixture["market_snapshot"] = {
        "price": 100.0,
        "source": "factor_factory.closed_bar",
        "quality_status": "closed_bar",
        "bar_at": (now - timedelta(days=30)).isoformat(),
        "observed_at": (now - timedelta(days=30)).isoformat(),
        "snapshot_kind": "historical_closed_bar",
        "execution_exception": {
            "kind": "factor_factory_isolated_closed_bar",
            "scope": "isolated",
            "authorized_by": "simulation_service",
            "realtime_executable": False,
        },
    }

    decision = evaluate_risk(intent, **fixture)

    assert decision["can_submit"] is True
    assert decision["market_execution_class"] == "historical_closed_bar_simulation"
    exception = next(
        check
        for check in decision["checks"]
        if check["code"] == "MARKET_HISTORICAL_SIMULATION_EXCEPTION"
    )
    assert exception["status"] == "excepted"
    assert exception["actual"]["realtime_executable"] is False

    normal_account = intent.model_copy(update={"account_id": "paper"})
    rejected = evaluate_risk(normal_account, **fixture)
    assert rejected["can_submit"] is False
    assert "MARKET_PRICE_SOURCE" in rejected["reason_codes"]


def test_trusted_market_snapshot_is_reserved_for_factor_factory_isolated_history() -> None:
    event_time = "2026-08-16T08:00:00"
    trusted = {
        "price": 100.0,
        "source": "factor_factory.closed_bar",
        "quality_status": "closed_bar",
        "event_time": event_time,
    }

    allowed = simulation_service._market_snapshot_for_evaluation(
        symbol="AAPL",
        market="us_stocks",
        account_id="factor-factory:run-001",
        trusted_market_snapshot=trusted,
    )
    rejected = simulation_service._market_snapshot_for_evaluation(
        symbol="AAPL",
        market="us_stocks",
        account_id="paper",
        trusted_market_snapshot=trusted,
    )

    assert allowed["snapshot_kind"] == "historical_closed_bar"
    assert allowed["execution_exception"]["realtime_executable"] is False
    assert allowed["bar_at"].endswith("+00:00")
    assert rejected["price"] is None
    assert rejected["source"] == "untrusted_server_snapshot"


def test_factor_factory_closed_bar_resolution_uses_canonical_internal_identity(monkeypatch) -> None:
    event_time = "2026-08-16T08:00:00+00:00"
    req = SimulationOrderCreate(
        symbol="BTCUSDT",
        market="crypto",
        side="buy",
        quantity=0.01,
        account_id="factor-factory:run-001",
    )
    strict = Mock(side_effect=AssertionError("live OKX resolver must not be used"))
    upsert = Mock()
    monkeypatch.setattr(instrument_service, "resolve_strict", strict)
    monkeypatch.setattr(instrument_service.repository, "upsert", upsert)
    context = simulation_service._resolve_order_context(
        req,
        trusted_market_snapshot={
            "price": 60_000.0,
            "event_time": event_time,
            "source": "factor_factory.closed_bar",
            "quality_status": "closed_bar",
        },
    )

    assert context["instrument"].code == "BTC-USDT-SWAP"
    strict.assert_not_called()
    upsert.assert_called_once()


def test_factor_factory_resolution_does_not_bypass_strict_crypto_for_untrusted_snapshot(
    monkeypatch,
) -> None:
    req = SimulationOrderCreate(
        symbol="BTCUSDT",
        market="crypto",
        side="buy",
        quantity=0.01,
        account_id="factor-factory:run-001",
    )
    strict = Mock(side_effect=instrument_service.InstrumentResolutionError("catalog unavailable"))
    monkeypatch.setattr(instrument_service, "resolve_strict", strict)

    with pytest.raises(instrument_service.InstrumentResolutionError, match="catalog unavailable"):
        simulation_service._resolve_order_context(
            req,
            trusted_market_snapshot={
                "price": 60_000.0,
                "event_time": "2026-08-16T08:00:00+00:00",
                "source": "okx",
                "quality_status": "closed_bar",
            },
        )
    strict.assert_called_once_with("BTCUSDT", "crypto")


def test_historical_closed_bar_order_cannot_use_shared_ledger_path(monkeypatch) -> None:
    order = {
        "audit": {"market_execution_class": "historical_closed_bar_simulation"},
        "quantity": 1,
        "filled_quantity": 0,
    }
    monkeypatch.setattr(simulation_service.store, "get_simulation_order", lambda _order_id: order)

    with pytest.raises(ValueError, match="隔离成交路径"):
        simulation_service.fill_order("history-order", object())
    with pytest.raises(ValueError, match="不得同步共享账本"):
        simulation_service.sync_execution_to_ledger("history-order", "execution-1")


def test_reduce_only_can_lower_an_existing_over_limit_position() -> None:
    now = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
    fixture = _risk_fixture(now=now)
    fixture["account_snapshot"].update(
        {
            "equity": 100.0,
            "cash": 0.0,
            "positions": [
                {
                    "symbol": "AAPL",
                    "market": "us_stocks",
                    "quantity": -2.0,
                    "market_value": -200.0,
                }
            ],
        }
    )
    intent = PaperOrderIntent(
        intent_id="reduce-short",
        account_id="paper",
        symbol="AAPL",
        market="us_stocks",
        side="buy",
        order_type="market",
        quantity=1,
        reduce_only=True,
    )
    decision = evaluate_risk(intent, **fixture)
    assert decision["can_submit"] is True
    assert decision["calculation"]["projected_quantity"] == -1.0


def test_direct_simulation_api_cannot_accept_client_risk_conclusions() -> None:
    with pytest.raises(ValidationError):
        SimulationOrderCreate.model_validate(
            {
                "symbol": "AAPL",
                "side": "buy",
                "quantity": 1,
                "can_submit": True,
                "risk_evaluated": True,
            }
        )


def _xlsx_payload() -> str:
    worksheet = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="inlineStr"><is><t>symbol</t></is></c><c r="B1" t="inlineStr"><is><t>effective_from</t></is></c></row>
    <row r="2"><c r="A2" t="inlineStr"><is><t>AAPL</t></is></c><c r="B2" t="inlineStr"><is><t>2026-01-01</t></is></c></row>
  </sheetData>
</worksheet>"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_universe_import_parses_csv_and_xlsx_without_duplicate_rows() -> None:
    csv_payload = base64.b64encode(
        b"symbol,effective_from,status\nAAPL,2026-01-01,active\n"
    ).decode("ascii")
    csv_rows = parse_universe_file("universe.csv", csv_payload)
    xlsx_rows = parse_universe_file("universe.xlsx", _xlsx_payload())
    assert csv_rows == [{"symbol": "AAPL", "effective_from": "2026-01-01", "status": "active"}]
    assert xlsx_rows == [{"symbol": "AAPL", "effective_from": "2026-01-01"}]


def test_universe_rollback_pointer_controls_dated_member_queries(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(store, "_DB", tmp_path / "universe-version.db")
    store._init()
    universe = store.create_factor_universe("US tech", "us_stocks", "fixture")
    v1_members = [
        {
            "symbol": "AAPL",
            "effective_from": "2026-01-01",
            "effective_to": None,
        }
    ]
    v1 = store.create_factor_universe_version(
        universe["id"], members=v1_members, source="fixture-v1"
    )
    v2_members = [
        *v1_members,
        {
            "symbol": "MSFT",
            "effective_from": "2026-02-01",
            "effective_to": None,
        },
    ]
    store.create_factor_universe_version(
        universe["id"], members=v2_members, source="fixture-v2", parent_version_id=v1["id"]
    )
    assert {
        item["symbol"]
        for item in store.list_factor_universe_members(
            universe["id"], start_date="2026-03-01", end_date="2026-03-31"
        )
    } == {"AAPL", "MSFT"}

    store.set_factor_universe_current_version(universe["id"], v1["id"])
    assert {
        item["symbol"]
        for item in store.list_factor_universe_members(
            universe["id"], start_date="2026-03-01", end_date="2026-03-31"
        )
    } == {"AAPL"}
