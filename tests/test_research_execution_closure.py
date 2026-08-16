from __future__ import annotations

import base64
import io
import itertools
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from apps.api import store
from apps.api.domains.factor_research.universe_import import parse_universe_file
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
