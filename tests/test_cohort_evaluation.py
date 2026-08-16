from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from apps.api.domains.factor_factory.cohort_review import run_cohort_ai_review
from core.cohort_evaluation import (
    ExecutionPolicy,
    VirtualLedger,
    default_benchmark_pool,
    program_live_gate,
    run_cohort_backtest,
)
from packages.market_data.contracts import (
    MarketEvent,
    MarketEventKind,
    MarketEventQuality,
)


class _ReviewLlm:
    _provider = "test"

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def chat(self, *_args, **_kwargs):
        from core.llm import LLMResponse

        return LLMResponse(
            content=__import__("json").dumps(self.payload),
            model="test-review",
            usage={"total_tokens": 100},
        )


def _frame(rows: int = 120) -> pd.DataFrame:
    times = pd.date_range("2026-01-01", periods=rows, freq="h", tz="UTC")
    close = pd.Series([100 + index * 0.2 + (index % 7 - 3) * 0.1 for index in range(rows)])
    return pd.DataFrame(
        {
            "datetime": times,
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1000.0,
        }
    )


def test_forming_bar_is_not_usable_for_research_signal() -> None:
    now = datetime.now(UTC)
    event = MarketEvent(
        event_id="forming-1",
        instrument_id="okx:BTC-USDT-SWAP",
        kind=MarketEventKind.FORMING_BAR,
        event_time=now - timedelta(minutes=30),
        bar_open_time=now - timedelta(minutes=30),
        bar_close_time=now + timedelta(minutes=30),
        fetched_at=now,
        received_at=now,
        is_closed=False,
        source="okx_public_ws",
        quality_status=MarketEventQuality.FRESH,
        close=100.0,
    )

    assert event.age_ms >= 0
    assert not event.usable_for_research_signal()


def test_virtual_ledger_is_idempotent_and_isolated() -> None:
    policy = ExecutionPolicy(capacity_fraction=1.0)
    left = VirtualLedger.create("left", "candidate", 100_000)
    right = VirtualLedger.create("right", "candidate", 100_000)
    kwargs = {
        "event_key": "bar-1",
        "decision_time": "2026-01-01T00:00:00+00:00",
        "tradable_time": "2026-01-01T01:00:00+00:00",
        "quote_time": "2026-01-01T01:00:00+00:00",
        "execution_time": "2026-01-01T01:00:00+00:00",
        "reference_price": 100.0,
        "target_weight": 0.5,
        "policy": policy,
    }

    left.rebalance(**kwargs)
    left.rebalance(**kwargs)

    assert len(left.orders) == 1
    assert len(left.executions) == 1
    assert right.cash == 100_000
    assert right.position.quantity == 0


def test_cohort_members_share_events_but_have_independent_ledgers() -> None:
    frame = _frame()
    signal = (frame["close"].pct_change(8) > 0).astype(float)
    result = run_cohort_backtest(
        cohort_id="cohort-test",
        frame=frame,
        candidate_signal=signal,
        candidate_key="candidate:v1",
        market="crypto",
        interval="1h",
        initial_capital=100_000,
        policy=ExecutionPolicy(capacity_fraction=1.0),
        pool=default_benchmark_pool("crypto", "1h"),
    )

    assert result["fairness"]["identical_event_order"]
    assert result["fairness"]["independent_ledgers"]
    assert len([key for key in result["ledgers"] if key.startswith("random_")]) == 20
    assert 0 <= result["comparison"]["random_percentile"] <= 1
    event_counts = {len(ledger["equity_curve"]) for ledger in result["ledgers"].values()}
    assert event_counts == {len(frame)}


def test_every_cohort_ledger_has_an_exact_serialization_round_trip() -> None:
    frame = _frame()
    report = run_cohort_backtest(
        cohort_id="cohort-round-trip",
        frame=frame,
        candidate_signal=(frame["close"].pct_change(8) > 0).astype(float),
        candidate_key="candidate:v1",
        market="crypto",
        interval="1h",
        initial_capital=100_000,
        policy=ExecutionPolicy(capacity_fraction=1.0),
    )

    for payload in report["ledgers"].values():
        assert VirtualLedger.from_dict(payload).to_dict() == payload


def test_program_gate_cannot_be_overridden_by_ai() -> None:
    frame = _frame()
    report = run_cohort_backtest(
        cohort_id="cohort-gate",
        frame=frame,
        candidate_signal=pd.Series(1.0, index=frame.index),
        candidate_key="candidate:v1",
        market="crypto",
        interval="1h",
        initial_capital=100_000,
        policy=ExecutionPolicy(capacity_fraction=1.0),
    )
    gate = program_live_gate(
        report,
        observed_days=1,
        rebalance_count=1,
        freshness_ok=True,
        reconciliation_ok=True,
        kill_switch_ready=True,
    )

    assert not gate["passed"]
    assert "minimum_observation_days" in gate["violations"]
    assert gate["ai_can_override"] is False
    assert gate["live_trading_enabled"] is False


def test_ai_small_live_recommendation_is_downgraded_when_program_gate_fails() -> None:
    evidence = {
        "comparison": {
            "candidate_key": "candidate:v1",
            "random_percentile": 0.4,
            "market_tailwind": True,
        },
        "ranking": [],
        "program_gate": {"passed": False, "violations": ["random_distribution"]},
    }
    review = run_cohort_ai_review(
        evidence,
        llm=_ReviewLlm(
            {
                "recommendation": "request_small_live",
                "summary": "Request a small live allocation.",
                "primary_return_source": "Market beta.",
                "weaker_than_benchmarks": ["buy_hold"],
                "applicable_regimes": ["trend"],
                "failure_regimes": ["range"],
                "remaining_risks": ["Low random percentile."],
                "evidence": ["random_percentile=0.4"],
            }
        ),
    )

    assert review["ok"]
    assert review["effective_recommendation"] == "continue_observation"
    assert review["conflict_reasons"] == ["program_gate_not_passed"]
    assert review["application_draft"]["submission_allowed"] is False
    assert review["audit"]["ledger_write_access"] is False


def test_executable_quote_policy_rejects_missing_quote_and_uses_bbo() -> None:
    policy = ExecutionPolicy(
        commission_bps=0,
        spread_bps=0,
        slippage_bps=10,
        capacity_fraction=1,
    )
    ledger = VirtualLedger.create("quote", "candidate", 100_000, policy)
    rejected = ledger.rebalance(
        event_key="missing",
        decision_time="2026-01-01T00:00:00+00:00",
        tradable_time="2026-01-01T01:00:00+00:00",
        quote_time="2026-01-01T01:00:00+00:00",
        execution_time="2026-01-01T01:00:00+00:00",
        reference_price=100,
        target_weight=0.5,
        policy=policy,
        quote_available=False,
    )
    filled = ledger.rebalance(
        event_key="bbo",
        decision_time="2026-01-01T01:00:00+00:00",
        tradable_time="2026-01-01T02:00:00+00:00",
        quote_time="2026-01-01T02:00:00+00:00",
        execution_time="2026-01-01T02:00:00+00:00",
        reference_price=100,
        target_weight=0.5,
        policy=policy,
        bid=99,
        ask=101,
    )

    assert rejected is not None
    assert rejected.rejection_reason == "missing_executable_quote"
    assert filled is not None and filled.status == "filled"
    assert ledger.executions[-1].price == 101 * 1.001
    assert ledger.executions[-1].spread_cost > 0
    assert ledger.executions[-1].slippage_cost > 0


def test_perpetual_ledger_funding_risk_halt_and_replay_identity() -> None:
    policy = ExecutionPolicy(
        instrument_type="perpetual",
        contract_multiplier=0.01,
        leverage=3,
        funding_rate_per_period=0.001,
        commission_bps=2,
        spread_bps=0,
        slippage_bps=0,
        capacity_fraction=1,
        maximum_daily_loss=0.01,
        maximum_drawdown=0.02,
        maximum_price_gap_bps=0,
    )
    ledger = VirtualLedger.create("swap", "candidate", 10_000, policy)
    ledger.rebalance(
        event_key="open",
        decision_time="2026-01-01T00:00:00+00:00",
        tradable_time="2026-01-01T01:00:00+00:00",
        quote_time="2026-01-01T01:00:00+00:00",
        execution_time="2026-01-01T01:00:00+00:00",
        reference_price=100,
        target_weight=1,
        policy=policy,
        bid=100,
        ask=100,
    )
    ledger.mark("mark-1", "2026-01-01T01:00:00+00:00", 100)
    ledger.mark("mark-2", "2026-01-01T02:00:00+00:00", 96)

    assert any(flow.kind == "funding" for flow in ledger.cash_flows)
    assert ledger.halted
    assert {event.kind for event in ledger.risk_events} & {
        "maximum_daily_loss",
        "maximum_drawdown",
    }
    replay = ledger.verify_replay(price=96)
    assert replay["passed"]


def test_cohort_report_contains_risk_normalization_regimes_and_grid_inventory() -> None:
    frame = _frame(240)
    frame["volume"] = [500 + (index % 40) * 50 for index in range(len(frame))]
    report = run_cohort_backtest(
        cohort_id="cohort-full-evidence",
        frame=frame,
        candidate_signal=(frame["close"].pct_change(8) > 0).astype(float),
        candidate_key="candidate:v1",
        market="crypto",
        interval="1h",
        initial_capital=100_000,
        policy=ExecutionPolicy(capacity_fraction=1.0),
    )

    assert report["replay_verification"]["passed"]
    assert report["fairness"]["same_quote_and_gap_policy"]
    assert report["fairness"]["same_funding_model"]
    assert report["fairness"]["missing_results_preserved"]
    assert set(report["regime_analysis"]) == {
        "direction",
        "trend",
        "volatility",
        "liquidity",
    }
    normalizations = report["comparison"]["normalizations"]
    assert normalizations["equal_capital"]
    assert normalizations["equal_maximum_exposure"] == 1.0
    assert normalizations["equal_volatility"]["target_volatility"] > 0
    assert set(report["comparison"]["paired_signal_controls"]) == {
        "candidate_raw",
        "candidate_fixed_exposure",
        "candidate_volatility_target",
    }
    for evidence in report["grid_risk"].values():
        assert evidence["preregistered"]
        assert evidence["levels"] == 8
        assert evidence["range"]["lower"] < evidence["range"]["upper"]
        assert "inventory_risk" in evidence
        assert "outside_range_loss" in evidence


def test_cohort_stress_scenarios_preserve_ledgers_and_risk_limits() -> None:
    scenarios = {
        "up": [100 + index * 0.5 for index in range(160)],
        "down": [180 - index * 0.5 for index in range(160)],
        "gap": [100 + index * 0.1 if index < 80 else 145 + index * 0.1 for index in range(160)],
        "range": [100 + (index % 12 - 6) * 0.4 for index in range(160)],
        "low_liquidity": [100 + index * 0.05 for index in range(160)],
    }
    for name, closes in scenarios.items():
        times = pd.date_range("2026-01-01", periods=len(closes), freq="h", tz="UTC")
        close = pd.Series(closes, dtype=float)
        frame = pd.DataFrame(
            {
                "datetime": times,
                "open": close.shift(1).fillna(close.iloc[0]),
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 1.0 if name == "low_liquidity" else 1000.0,
            }
        )
        report = run_cohort_backtest(
            cohort_id=f"stress-{name}",
            frame=frame,
            candidate_signal=(close.pct_change(5) > 0).astype(float),
            candidate_key="candidate:v1",
            market="crypto",
            interval="1h",
            initial_capital=100_000,
            policy=ExecutionPolicy(
                capacity_fraction=0.1 if name == "low_liquidity" else 1.0,
                maximum_exposure=0.8,
                maximum_price_gap_bps=300,
            ),
        )
        assert report["replay_verification"]["passed"]
        assert report["fairness"]["independent_ledgers"]
        assert report["fairness"]["missing_results_preserved"]
        assert len(report["ledgers"]) == len(report["ranking"])
        if name == "gap":
            assert any(
                event["kind"] == "price_gap_exceeded"
                for ledger in report["ledgers"].values()
                for event in ledger["risk_events"]
            )
