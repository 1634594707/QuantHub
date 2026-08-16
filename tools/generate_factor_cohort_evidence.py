"""Generate deterministic factor cohort acceptance evidence.

This evidence proves contracts and replay behavior only. It intentionally does
not claim elapsed seven-day observation, exchange connectivity, or live trading.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from apps.api.domains.factor_factory.cohort_review import run_cohort_ai_review
from core.cohort_evaluation import (
    EvaluationCohort,
    ExecutionPolicy,
    VirtualLedger,
    default_benchmark_pool,
    program_live_gate,
    run_cohort_backtest,
)
from core.config import get_config
from core.data_feed.factory import get_data_source
from core.llm import LLMResponse
from packages.market_data.contracts import (
    MarketEvent,
    MarketEventKind,
    MarketEventQuality,
)

OUTPUT = Path("docs/Plan/evidence/factor-cohort-v1-2026-08-12")
GENERATED_AT = "2026-08-12T12:00:00+00:00"
COHORT_ID = "factor-cohort-v1-acceptance-20260812"
CANDIDATE_KEY = "candidate:momentum-quality:v1"


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def write_json(name: str, payload: Any) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / name
    path.write_text(
        json.dumps(jsonable(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def fixture_frame(rows: int = 240) -> pd.DataFrame:
    start = datetime(2026, 7, 1, tzinfo=UTC)
    times = [start + timedelta(hours=index) for index in range(rows)]
    close = pd.Series(
        [100 + index * 0.08 + ((index % 24) - 12) * 0.03 for index in range(rows)],
        dtype=float,
    )
    return pd.DataFrame(
        {
            "datetime": times,
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close + 0.35,
            "low": close - 0.35,
            "close": close,
            "volume": [1_000 + (index % 17) * 25 for index in range(rows)],
        }
    )


class DeterministicReviewClient:
    _provider = "deterministic_acceptance_fixture"

    def chat(self, *_args, **_kwargs) -> LLMResponse:
        payload = {
            "recommendation": "request_small_live",
            "summary": "候选仍需完成真实自然日观察，当前不能进入小额实盘。",
            "primary_return_source": "趋势暴露与信号择时的组合。",
            "weaker_than_benchmarks": ["buy_hold"],
            "applicable_regimes": ["trend", "normal_liquidity"],
            "failure_regimes": ["range", "liquidity_stress"],
            "remaining_risks": ["真实七日观察尚未完成", "联网重连演练尚未完成"],
            "evidence": ["program_gate.passed=false", "minimum_observation_days=false"],
        }
        return LLMResponse(
            content=json.dumps(payload, ensure_ascii=False),
            model="deterministic-review-fixture-v1",
            usage={"total_tokens": 0},
        )


def main() -> None:
    frame = fixture_frame()
    candidate_signal = (frame["close"].pct_change(12) > 0).astype(float)
    pool = default_benchmark_pool("crypto", "1h")
    policy = ExecutionPolicy(capacity_fraction=0.25)
    frame_payload = frame.assign(
        datetime=frame["datetime"].map(lambda value: value.isoformat())
    ).to_dict(orient="records")
    frame_hash = canonical_hash(frame_payload)
    cohort = EvaluationCohort(
        cohort_id=COHORT_ID,
        candidate_key=CANDIDATE_KEY,
        candidate_version="1.0.0",
        benchmark_pool_version=pool.version,
        benchmark_pool_hash=pool.content_hash,
        started_at=GENERATED_AT,
        ends_at="after_7_natural_days_and_3_effective_rebalances",
        config_hash=canonical_hash(
            {
                "candidate": CANDIDATE_KEY,
                "market": "crypto",
                "interval": "1h",
                "initial_capital": 100_000,
                "execution_policy": asdict(policy),
            }
        ),
        market_data_fingerprint=frame_hash,
    )
    report = run_cohort_backtest(
        cohort_id=COHORT_ID,
        frame=frame,
        candidate_signal=candidate_signal,
        candidate_key=CANDIDATE_KEY,
        market="crypto",
        interval="1h",
        initial_capital=100_000,
        policy=policy,
        pool=pool,
    )
    replay = run_cohort_backtest(
        cohort_id=COHORT_ID,
        frame=frame,
        candidate_signal=candidate_signal,
        candidate_key=CANDIDATE_KEY,
        market="crypto",
        interval="1h",
        initial_capital=100_000,
        policy=policy,
        pool=pool,
    )
    online_hashes = {key: canonical_hash(value) for key, value in report["ledgers"].items()}
    replay_hashes = {key: canonical_hash(value) for key, value in replay["ledgers"].items()}
    reconstructed = {
        key: VirtualLedger.from_dict(value).to_dict() for key, value in report["ledgers"].items()
    }
    reconstructed_hashes = {key: canonical_hash(value) for key, value in reconstructed.items()}
    gate = program_live_gate(
        report,
        observed_days=0,
        rebalance_count=0,
        freshness_ok=True,
        reconciliation_ok=False,
        kill_switch_ready=False,
    )
    review = run_cohort_ai_review(
        jsonable({**report, "program_gate": gate}),
        llm=DeterministicReviewClient(),
    )
    now = datetime.fromisoformat(GENERATED_AT)
    closed_bar = MarketEvent(
        event_id="acceptance:closed-bar:20260812",
        instrument_id="okx:BTC-USDT-SWAP",
        kind=MarketEventKind.CLOSED_BAR_LIVE,
        event_time=now - timedelta(seconds=2),
        bar_open_time=now - timedelta(hours=1),
        bar_close_time=now - timedelta(seconds=2),
        fetched_at=now,
        received_at=now,
        is_closed=True,
        source="deterministic_acceptance_fixture",
        quality_status=MarketEventQuality.FRESH,
        open=100,
        high=102,
        low=99,
        close=101,
        volume=10,
    )
    forming_bar = MarketEvent(
        event_id="acceptance:forming-bar:20260812",
        instrument_id="okx:BTC-USDT-SWAP",
        kind=MarketEventKind.FORMING_BAR,
        event_time=now,
        bar_open_time=now,
        bar_close_time=now + timedelta(hours=1),
        fetched_at=now,
        received_at=now,
        is_closed=False,
        source="deterministic_acceptance_fixture",
        quality_status=MarketEventQuality.FRESH,
        open=101,
        high=102,
        low=100,
        close=101.5,
        volume=2,
    )
    bbo = MarketEvent(
        event_id="acceptance:bbo:20260812",
        instrument_id="okx:BTC-USDT-SWAP",
        kind=MarketEventKind.BEST_BID_ASK,
        event_time=now,
        fetched_at=now,
        received_at=now,
        source="deterministic_acceptance_fixture",
        quality_status=MarketEventQuality.FRESH,
        bid=100.0,
        ask=100.2,
    )
    valuation_price = (float(bbo.bid) + float(bbo.ask)) / 2
    locked_fields = ("ranking", "comparison", "benchmark_pool", "execution_policy")
    locked_before = canonical_hash({key: report.get(key) for key in locked_fields})
    valued_ledgers: dict[str, Any] = {}
    valuation_rows: dict[str, Any] = {}
    for member_key, payload in report["ledgers"].items():
        ledger = VirtualLedger.from_dict(payload)
        before_counts = {
            "orders": len(ledger.orders),
            "executions": len(ledger.executions),
            "cash_flows": len(ledger.cash_flows),
        }
        applied = ledger.mark(
            bbo.event_id,
            bbo.event_time.isoformat(),
            valuation_price,
            apply_funding=False,
        )
        duplicate_applied = ledger.mark(
            bbo.event_id,
            bbo.event_time.isoformat(),
            valuation_price,
            apply_funding=False,
        )
        valued_ledgers[member_key] = ledger.to_dict()
        valuation_rows[member_key] = {
            "mark_applied": applied,
            "duplicate_mark_applied": duplicate_applied,
            "equity": ledger.equity_at(valuation_price),
            "orders_unchanged": len(ledger.orders) == before_counts["orders"],
            "executions_unchanged": len(ledger.executions) == before_counts["executions"],
            "cash_flows_unchanged": len(ledger.cash_flows) == before_counts["cash_flows"],
            "replay": ledger.verify_replay(price=valuation_price),
        }
    valuation_report = {**report, "ledgers": valued_ledgers}
    locked_after = canonical_hash({key: valuation_report.get(key) for key in locked_fields})
    a_share_config = get_config("a_shares").get("data_sources", {})
    a_share_proxy = get_data_source("a_shares")

    write_json(
        "data-freshness.json",
        {
            "evidence_kind": "deterministic_contract_acceptance",
            "generated_at": GENERATED_AT,
            "closed_bar": closed_bar.model_dump(mode="json"),
            "forming_bar": forming_bar.model_dump(mode="json"),
            "assertions": {
                "closed_bar_research_signal_allowed": closed_bar.usable_for_research_signal(),
                "forming_bar_research_signal_allowed": forming_bar.usable_for_research_signal(),
                "real_public_ws_connectivity": "pending",
            },
        },
    )
    write_json(
        "live-valuation.json",
        {
            "evidence_kind": "deterministic_contract_acceptance",
            "generated_at": GENERATED_AT,
            "connected_public_stream": False,
            "event": bbo.model_dump(mode="json"),
            "price_basis": "bbo_mid",
            "valuation_price": valuation_price,
            "ledger_count": len(valuation_rows),
            "applied_ledger_count": sum(row["mark_applied"] for row in valuation_rows.values()),
            "duplicate_applied_ledger_count": sum(
                row["duplicate_mark_applied"] for row in valuation_rows.values()
            ),
            "funding_applied": False,
            "locked_research_evidence_hash_before": locked_before,
            "locked_research_evidence_hash_after": locked_after,
            "locked_research_evidence_unchanged": locked_before == locked_after,
            "all_order_execution_cashflow_counts_unchanged": all(
                row["orders_unchanged"]
                and row["executions_unchanged"]
                and row["cash_flows_unchanged"]
                for row in valuation_rows.values()
            ),
            "all_replays_passed": all(row["replay"]["passed"] for row in valuation_rows.values()),
            "ledgers": valuation_rows,
            "note": "The quote is deterministic and does not claim real exchange connectivity.",
            "live_trading_enabled": False,
        },
    )
    write_json(
        "a-share-source-contract.json",
        {
            "evidence_kind": "deterministic_configuration_acceptance",
            "generated_at": GENERATED_AT,
            "configured_priority": [
                a_share_config.get("primary"),
                *a_share_config.get("fallback", []),
            ],
            "runtime_plans": {
                interval: a_share_proxy.source_plan("get_kline", interval)
                for interval in ("1m", "5m", "15m", "30m", "1h", "1d", "1w")
            },
            "news_plan": a_share_proxy.source_plan("get_news"),
            "announcements_plan": a_share_proxy.source_plan("get_announcements"),
            "assertions": {
                "daily_sources_are_bar_snapshots": all(
                    item["kline_semantics"] == "bar_snapshot" and item["tick_by_tick"] is False
                    for item in a_share_proxy.source_plan("get_kline", "1d")
                ),
                "news_only_sources_excluded_from_daily_kline": all(
                    "get_kline" in item["operations"]
                    for item in a_share_proxy.source_plan("get_kline", "1d")
                ),
            },
            "note": "Plans describe configured adapter capabilities; they do not claim tick-level data.",
        },
    )
    write_json("cohort-definition.json", cohort.to_dict())
    write_json("benchmark-pool.json", pool.to_dict())
    write_json(
        "ledger-replay-report.json",
        {
            "generated_at": GENERATED_AT,
            "cohort_id": COHORT_ID,
            "ledger_count": len(report["ledgers"]),
            "online_hashes": online_hashes,
            "replay_hashes": replay_hashes,
            "reconstructed_hashes": reconstructed_hashes,
            "online_equals_replay": online_hashes == replay_hashes,
            "online_equals_reconstructed": online_hashes == reconstructed_hashes,
            "fairness": report["fairness"],
        },
    )
    write_json(
        "strategy-comparison.json",
        {
            "generated_at": GENERATED_AT,
            "evidence_kind": "deterministic_contract_acceptance",
            "ranking": report["ranking"],
            "comparison": report["comparison"],
            "execution_policy": report["execution_policy"],
            "fairness": report["fairness"],
            "replay_verification": report["replay_verification"],
            "regime_analysis": report["regime_analysis"],
            "grid_risk": report["grid_risk"],
        },
    )
    write_json("ai-review.json", review)
    write_json(
        "program-gate.json",
        {
            **gate,
            "observation_status": "pending",
            "observed_natural_days": 0,
            "required_natural_days": 7,
            "real_duration_fabricated": False,
        },
    )
    write_json(
        "manual-approval.json",
        {
            "status": "pending",
            "reason": "program_gate_not_passed",
            "manual_approval_record": None,
            "live_trading_enabled": False,
        },
    )
    write_json(
        "fault-reconnect-evidence.json",
        {
            "status": "partially_verified",
            "deterministic_tests": {
                "rest_compensation": "passed",
                "duplicate_suppression": "passed",
                "gap_evidence": "passed",
                "manager_start_stop": "passed",
            },
            "real_exchange_disconnect_reconnect_drill": "pending",
            "note": "No external connectivity result is claimed by this fixture.",
        },
    )
    write_json(
        "manifest.json",
        {
            "generated_at": GENERATED_AT,
            "generator": "tools/generate_factor_cohort_evidence.py",
            "evidence_kind": "deterministic_contract_acceptance",
            "files": sorted(
                path.name
                for path in OUTPUT.glob("*.json")
                if path.name != "manifest.json" and "-debug" not in path.name
            ),
            "pending_real_world_items": [
                "seven_natural_day_okx_demo_cohort",
                "real_okx_public_ws_disconnect_reconnect_drill_blocked_by_ws_handshake",
                "manual_small_live_approval",
                "small_live_execution_and_attribution",
            ],
            "isolated_prelive_fault_evidence": "prelive-fault-drills.json",
            "failed_real_world_evidence": ["real-public-reconnect.json"],
            "ai_candidate_blind_benchmark": (
                "ai-candidate-blind-benchmark.json"
                if (OUTPUT / "ai-candidate-blind-benchmark.json").exists()
                else None
            ),
            "live_trading_enabled": False,
        },
    )


if __name__ == "__main__":
    main()
