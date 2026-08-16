"""Generate pre-live risk-gate evidence with isolated Runner databases."""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from apps.okx_runner.adapter import AccountSnapshot, ExternalOrder, InstrumentRules
from apps.okx_runner.database import connect
from apps.okx_runner.engine import RiskViolation, RunnerEngine
from apps.okx_runner.schemas import OrderRequest
from packages.strategy_package import (
    RiskLimits,
    StrategyReleasePayload,
    create_release_package,
)

OUTPUT = Path("docs/Plan/evidence/factor-cohort-v1-2026-08-12/prelive-fault-drills.json")
KEY = b"prelive-risk-drill-signing-key-01"


class DrillAdapter:
    def __init__(self) -> None:
        self.submit_calls = 0
        self.snapshot_error: Exception | None = None
        self.observed_at = datetime.now(UTC)
        self.balance = 1_000_000.0
        self.peak_equity = 1_000_000.0

    def instrument_rules(self, _symbol: str) -> InstrumentRules:
        return InstrumentRules(0.01, 0.01, 0.1, "USDT", 5)

    def submit_order(self, request: dict) -> ExternalOrder:
        self.submit_calls += 1
        return ExternalOrder("unexpected", request["client_order_id"], "submitted")

    def fetch_order_by_client_id(self, _client_order_id: str, _symbol: str | None = None):
        return None

    def account_snapshot(self, _account_id: str) -> AccountSnapshot:
        if self.snapshot_error is not None:
            raise self.snapshot_error
        return AccountSnapshot(
            orders=(),
            fills=(),
            balances={"USDT": {"total": self.balance, "available": self.balance}},
            positions={"BTC-USDT-SWAP": {"quantity": 0.0, "mark_price": 60_000.0}},
            observed_at=self.observed_at,
            peak_equity=self.peak_equity,
        )

    def mark_price(self, _symbol: str) -> float:
        return 60_000.0


def release_package():
    formula = '{"op":"pct_change","periods":24,"value":{"name":"close","op":"field"}}'
    payload = StrategyReleasePayload(
        strategy_id="prelive-risk-drill",
        version="1.0.0",
        target_market="okx",
        product_type="usdt_perpetual",
        runner_compatibility="1.0.0",
        formula=formula,
        formula_hash=sha256(formula.encode()).hexdigest(),
        parameters={"lookback": 2},
        universe={"quote": "USDT"},
        signal_frequency="1h",
        rebalance_frequency="4h",
        data_fields=("open", "high", "low", "close", "volume", "funding_rate"),
        data_delay_seconds=5,
        data_snapshot_id="prelive-risk-drill-v1",
        research_engine_version="2.2.0",
        out_of_sample_results={"rank_ic": 0.027},
        cost_assumptions={"fee_bps": 5, "funding_bps": 1, "spread_bps": 2},
        risk_limits=RiskLimits(
            max_leverage=2,
            max_symbol_exposure=0.1,
            max_total_exposure=0.5,
            max_loss=1_000,
            max_drawdown=0.15,
        ),
        simulation_results={"status": "passed"},
        allowed_environments=("demo",),
        approved_by="prelive-risk-drill",
        approved_at=datetime(2026, 8, 12, tzinfo=UTC),
        audit_record_ids=("prelive-risk-drill",),
    )
    return create_release_package(payload, KEY)


def request(scenario: str) -> OrderRequest:
    return OrderRequest(
        strategy_id="prelive-risk-drill",
        strategy_version="1.0.0",
        intent_id=f"prelive-{scenario}",
        account_id="demo-account",
        symbol="BTC-USDT-SWAP",
        side="buy",
        order_type="limit",
        quantity=0.1,
        price=60_000.0,
        leverage=2,
    )


def audit_counts(path: Path) -> dict:
    with connect(path) as connection:
        return {
            "risk_decisions": connection.execute(
                "SELECT COUNT(*) FROM risk_decisions WHERE outcome='rejected'"
            ).fetchone()[0],
            "risk_mode_changes": connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type='risk_mode_changed'"
            ).fetchone()[0],
            "open_reconciliation_differences": connection.execute(
                "SELECT COUNT(*) FROM reconciliation_diffs WHERE status='open'"
            ).fetchone()[0],
        }


def run_scenario(name: str) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"quanthub-{name}-") as directory:
        path = Path(directory) / "runner.db"
        adapter = DrillAdapter()
        engine = RunnerEngine(path, adapter, KEY, "demo")
        engine.import_package(release_package())
        setup: dict = {}
        if name == "network_down":
            adapter.snapshot_error = ConnectionError("injected network outage")
        elif name == "data_stale":
            adapter.observed_at = datetime.now(UTC) - timedelta(minutes=5)
        elif name == "drawdown_breach":
            adapter.balance = 800_000.0
        elif name == "kill_switch":
            setup["risk_mode"] = engine.set_risk_mode(
                "global", "halted", "pre-live kill switch drill", "risk-drill"
            )
        elif name == "reconciliation_anomaly":
            engine.reconcile("demo-account")
            adapter.balance = 900_000.0
            reconciliation = engine.reconcile("demo-account")
            setup["reconciliation"] = reconciliation
            setup["risk_mode"] = engine.set_risk_mode(
                "global", "cancel_only", "open reconciliation difference", "risk-drill"
            )
        else:
            raise ValueError(name)

        error = None
        try:
            engine.submit(request(name))
        except RiskViolation as exc:
            error = str(exc)
        counts = audit_counts(path)
        passed = (
            error is not None
            and adapter.submit_calls == 0
            and counts["risk_decisions"] >= 1
            and (name != "reconciliation_anomaly" or counts["open_reconciliation_differences"] >= 1)
            and (
                name not in {"kill_switch", "reconciliation_anomaly"}
                or counts["risk_mode_changes"] >= 1
            )
        )
        return {
            "scenario": name,
            "blocked_before_external_submit": adapter.submit_calls == 0,
            "risk_error": error,
            "audit_counts": counts,
            "setup": setup,
            "passed": passed,
        }


def main() -> None:
    scenarios = [
        run_scenario(name)
        for name in (
            "network_down",
            "data_stale",
            "reconciliation_anomaly",
            "drawdown_breach",
            "kill_switch",
        )
    ]
    payload = {
        "evidence_kind": "isolated_runner_prelive_fault_drill",
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": "throwaway_demo_runner_databases",
        "credentials_used": False,
        "external_orders_created": 0,
        "monitoring_cycles_to_block_new_risk": 1,
        "scenarios": scenarios,
        "all_passed": all(item["passed"] for item in scenarios),
        "live_trading_enabled": False,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
