from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps.okx_runner.adapter import (
    AccountSnapshot,
    ExternalFill,
    ExternalOrder,
    InstrumentRules,
)
from apps.okx_runner.config import RunnerSettings
from apps.okx_runner.database import connect
from apps.okx_runner.engine import RiskViolation, RunnerEngine
from apps.okx_runner.main import create_app
from apps.okx_runner.schemas import AmendOrderRequest, ClosePositionRequest, OrderRequest
from packages.strategy_package import (
    RiskLimits,
    StrategyReleasePayload,
    create_release_package,
)


class DemoAdapter:
    def __init__(self) -> None:
        self.behavior = "submitted"
        self.submit_calls = 0
        self.orders: dict[str, ExternalOrder] = {}
        self.fills: tuple[ExternalFill, ...] = ()
        self.balances = {"USDT": {"total": 1000000.0, "available": 900000.0}}
        self.positions = {"BTC-USDT-SWAP": {"quantity": 0.0, "mark_price": 60000.0}}
        self.observed_at = datetime.now(UTC)
        self.realized_pnl = 0.0
        self.peak_equity = 1000000.0
        self.include_orders_in_snapshot = True

    def preflight(self, symbols: list[str]) -> dict:
        return {
            "environment": "demo",
            "observed_at": datetime.now(UTC).isoformat(),
            "account": {
                "account_level": "2",
                "position_mode": "net_mode",
                "permissions": ["read_only", "trade"],
            },
            "ip_whitelist": {"field_exposed": False, "status": "manual_confirmation_required"},
            "clock": {
                "server_time_available": True,
                "absolute_drift_ms": 100,
                "within_tolerance": True,
                "tolerance_ms": 5000,
            },
            "instruments": [{"symbol": symbol, "active": True} for symbol in symbols],
        }

    def instrument_rules(self, symbol: str) -> InstrumentRules:
        return InstrumentRules(0.01, 0.01, 0.1, "USDT", 5)

    def submit_order(self, request: dict) -> ExternalOrder:
        self.submit_calls += 1
        client_id = request["client_order_id"]
        external = ExternalOrder(
            external_order_id=f"okx-{client_id}",
            client_order_id=client_id,
            status="partially_filled" if self.behavior == "partial" else "submitted",
            filled_quantity=0.01 if self.behavior == "partial" else 0,
            average_price=60000 if self.behavior == "partial" else None,
            raw={"request_id": "demo", "api_key": "must-not-leak"},
        )
        if self.behavior in {"timeout_stored", "partial", "submitted"}:
            self.orders[client_id] = external
        if self.behavior in {"timeout_stored", "timeout_missing"}:
            raise TimeoutError("demo timeout")
        if self.behavior == "rejected":
            raise RuntimeError("token=must-not-leak rejected")
        return external

    def fetch_order_by_client_id(
        self, client_order_id: str, symbol: str | None = None
    ) -> ExternalOrder | None:
        return self.orders.get(client_order_id)

    def cancel_order(self, external_order_id: str) -> ExternalOrder:
        current = next(
            order for order in self.orders.values() if order.external_order_id == external_order_id
        )
        cancelled = ExternalOrder(
            external_order_id=current.external_order_id,
            client_order_id=current.client_order_id,
            status="cancelled",
            filled_quantity=current.filled_quantity,
            average_price=current.average_price,
        )
        self.orders[current.client_order_id] = cancelled
        return cancelled

    def amend_order(self, external_order_id: str, symbol: str, request: dict) -> ExternalOrder:
        current = next(
            order for order in self.orders.values() if order.external_order_id == external_order_id
        )
        amended = ExternalOrder(
            external_order_id=current.external_order_id,
            client_order_id=current.client_order_id,
            status="submitted",
            filled_quantity=current.filled_quantity,
            average_price=current.average_price,
            raw={"amended_quantity": request["quantity"], "symbol": symbol},
        )
        self.orders[current.client_order_id] = amended
        return amended

    def account_snapshot(self, account_id: str) -> AccountSnapshot:
        return AccountSnapshot(
            orders=tuple(self.orders.values()) if self.include_orders_in_snapshot else (),
            fills=self.fills,
            balances=self.balances,
            positions=self.positions,
            observed_at=self.observed_at,
            realized_pnl=self.realized_pnl,
            peak_equity=self.peak_equity,
        )

    def mark_price(self, symbol: str) -> float:
        return float(self.positions.get(symbol, {}).get("mark_price", 60000.0))


def release_package(key: bytes):
    formula = '{"op":"pct_change","periods":24,"value":{"name":"close","op":"field"}}'
    payload = StrategyReleasePayload(
        strategy_id="okx-momentum-1h",
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
        data_snapshot_id="okx-demo-v1",
        research_engine_version="2.2.0",
        out_of_sample_results={"rank_ic": 0.027},
        cost_assumptions={"fee_bps": 5, "funding_bps": 1, "spread_bps": 2, "slippage_bps": 3},
        risk_limits=RiskLimits(
            max_leverage=2,
            max_symbol_exposure=0.1,
            max_total_exposure=0.5,
            max_loss=1000,
            max_drawdown=0.15,
        ),
        simulation_results={"status": "passed"},
        allowed_environments=("shadow", "demo"),
        approved_by="factor-review",
        approved_at=datetime(2026, 8, 3, tzinfo=UTC),
        audit_record_ids=("experiment-1", "simulation-1"),
    )
    return create_release_package(payload, key)


class RunnerProductTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "runner-demo.db"
        self.key = b"r" * 32
        self.adapter = DemoAdapter()
        self.engine = RunnerEngine(self.path, self.adapter, self.key, "demo")
        self.package = release_package(self.key)
        self.engine.import_package(self.package)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def request(intent_id: str = "intent-signal-1", **changes) -> OrderRequest:
        values = {
            "strategy_id": "okx-momentum-1h",
            "strategy_version": "1.0.0",
            "intent_id": intent_id,
            "account_id": "demo-account",
            "symbol": "BTC-USDT-SWAP",
            "side": "buy",
            "order_type": "limit",
            "quantity": 0.1,
            "price": 60000.0,
            "leverage": 2,
        }
        values.update(changes)
        return OrderRequest(**values)

    def test_stable_client_id_makes_repeated_request_idempotent(self) -> None:
        first = self.engine.submit(self.request())
        second = self.engine.submit(self.request())
        self.assertEqual(first["order_id"], second["order_id"])
        self.assertEqual(self.adapter.submit_calls, 1)
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(
            [event["to_status"] for event in first["events"]], ["PENDING_SUBMIT", "SUBMITTED"]
        )
        self.assertNotIn("must-not-leak", json.dumps(first["events"]))

    def test_dashboard_exposes_runner_owned_operational_state(self) -> None:
        order = self.engine.submit(self.request())
        dashboard = self.engine.dashboard()
        self.assertEqual(dashboard["strategies"][0]["strategy_id"], "okx-momentum-1h")
        self.assertEqual(dashboard["orders"][0]["order_id"], order["order_id"])
        self.assertEqual(dashboard["risk_states"][0]["mode"], "normal")
        self.assertTrue(dashboard["incidents"])
        detail = self.engine.order(order["order_id"])
        self.assertEqual(detail["request_hash"], order["request_hash"])
        self.assertEqual(detail["risk_decisions"][0]["outcome"], "approved")
        strategy = self.engine.strategy("okx-momentum-1h", "1.0.0")
        self.assertEqual(strategy["package"]["target_market"], "okx")

    def test_timeout_queries_before_recovery_and_never_blindly_resubmits(self) -> None:
        self.adapter.behavior = "timeout_stored"
        resolved = self.engine.submit(self.request("timeout-found"))
        self.assertEqual(resolved["status"], "SUBMITTED")
        self.assertEqual(self.adapter.submit_calls, 1)

        self.adapter.behavior = "timeout_missing"
        unknown = self.engine.submit(self.request("timeout-unknown"))
        self.assertEqual(unknown["status"], "UNKNOWN")
        self.assertEqual(self.adapter.submit_calls, 2)
        repeated = self.engine.submit(self.request("timeout-unknown"))
        self.assertEqual(repeated["status"], "UNKNOWN")
        self.assertEqual(self.adapter.submit_calls, 2)

        self.adapter.orders[unknown["client_order_id"]] = ExternalOrder(
            "okx-recovered", unknown["client_order_id"], "filled", 0.1, 60000
        )
        restarted = RunnerEngine(self.path, self.adapter, self.key, "demo")
        recovered = restarted.recover_open_orders()
        restored = next(row for row in recovered if row["order_id"] == unknown["order_id"])
        self.assertEqual(restored["status"], "FILLED")
        self.assertEqual(restored["external_order_id"], "okx-recovered")

    def test_partial_reject_cancel_and_hard_risk_controls(self) -> None:
        self.adapter.behavior = "partial"
        partial = self.engine.submit(self.request("partial"))
        self.assertEqual(partial["status"], "PARTIALLY_FILLED")
        cancelled = self.engine.cancel(partial["order_id"])
        self.assertEqual(cancelled["status"], "CANCELLED")

        self.adapter.behavior = "rejected"
        rejected = self.engine.submit(self.request("rejected"))
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertNotIn("must-not-leak", json.dumps(rejected["events"]))

        with self.assertRaisesRegex(RiskViolation, "leverage"):
            self.engine.submit(self.request("risk-leverage", leverage=3))
        with self.assertRaisesRegex(RiskViolation, "precision"):
            self.engine.submit(self.request("risk-precision", quantity=0.105))
        self.engine.set_risk_mode("account:demo-account", "cancel_only", "fault drill")
        with self.assertRaisesRegex(RiskViolation, "cancel_only"):
            self.engine.submit(self.request("risk-mode"))

    def test_market_reduce_only_amend_and_quick_close(self) -> None:
        market = self.engine.submit(self.request("market-order", order_type="market", price=None))
        self.assertEqual(market["status"], "SUBMITTED")

        amended = self.engine.amend(
            market["order_id"],
            AmendOrderRequest(
                quantity=0.05,
                price=None,
                stop_loss={"trigger_price": 59000},
                take_profit={"trigger_price": 62000},
            ),
        )
        self.assertEqual(amended["quantity"], 0.05)
        self.assertEqual(amended["status"], "SUBMITTED")

        self.adapter.positions["BTC-USDT-SWAP"] = {
            "quantity": 0.2,
            "mark_price": 60000.0,
        }
        closed = self.engine.close_position(
            "demo-account",
            "BTC-USDT-SWAP",
            ClosePositionRequest(
                strategy_id="okx-momentum-1h",
                strategy_version="1.0.0",
                intent_id="quick-close",
            ),
        )
        self.assertEqual(closed["side"], "sell")
        self.assertEqual(closed["order_type"], "market")
        self.assertTrue(json.loads(closed["request_json"])["reduce_only"])

    def test_protection_geometry_and_limit_price_fail_closed(self) -> None:
        with self.assertRaisesRegex(RiskViolation, "requires a price"):
            self.engine.submit(self.request("missing-limit-price", price=None))
        with self.assertRaisesRegex(RiskViolation, "stop loss"):
            self.engine.submit(self.request("invalid-stop", stop_loss={"trigger_price": 61000}))
        with self.assertRaisesRegex(RiskViolation, "take profit"):
            self.engine.submit(self.request("invalid-target", take_profit={"trigger_price": 59000}))

    def test_browser_cannot_override_server_risk_values(self) -> None:
        with self.assertRaises(ValidationError):
            OrderRequest(
                **self.request("malicious-fields").model_dump(),
                expected_total_exposure=0,
                expected_symbol_exposure=0,
                current_loss=0,
                current_drawdown=0,
            )

        self.adapter.positions["BTC-USDT-SWAP"] = {
            "quantity": 2.0,
            "mark_price": 60000.0,
        }
        with self.assertRaisesRegex(RiskViolation, "symbol exposure"):
            self.engine.submit(self.request("server-symbol-exposure"))

        self.adapter.positions["BTC-USDT-SWAP"] = {"quantity": 0, "mark_price": 60000.0}
        self.adapter.realized_pnl = -1000
        with self.assertRaisesRegex(RiskViolation, "loss hard limit"):
            self.engine.submit(self.request("server-loss"))

        self.adapter.realized_pnl = 0
        self.adapter.balances["USDT"]["total"] = 800000
        self.adapter.peak_equity = 1000000
        with self.assertRaisesRegex(RiskViolation, "drawdown hard limit"):
            self.engine.submit(self.request("server-drawdown"))

        with connect(self.path) as connection:
            rejected = connection.execute(
                "SELECT COUNT(*) FROM risk_decisions WHERE outcome='rejected'"
            ).fetchone()[0]
        self.assertEqual(rejected, 3)

    def test_stale_snapshot_blocks_submit_and_records_one_risk_decision(self) -> None:
        self.adapter.observed_at = datetime.now(UTC) - timedelta(minutes=5)

        with self.assertRaisesRegex(RiskViolation, "stale"):
            self.engine.submit(self.request("stale-snapshot"))

        self.assertEqual(self.adapter.submit_calls, 0)
        with connect(self.path) as connection:
            decisions = connection.execute(
                "SELECT outcome, reason FROM risk_decisions WHERE intent_id='stale-snapshot'"
            ).fetchall()
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["outcome"], "rejected")
        self.assertIn("stale", decisions[0]["reason"])

    def test_limit_price_cannot_reduce_server_marked_exposure(self) -> None:
        self.adapter.positions["BTC-USDT-SWAP"] = {"quantity": 1.7, "mark_price": 60000.0}
        with self.assertRaisesRegex(RiskViolation, "symbol exposure"):
            self.engine.submit(self.request("limit-price-bypass", price=1.0))

    def test_reconciliation_persists_owned_differences_and_runtime_results(self) -> None:
        order = self.engine.submit(self.request())
        with connect(self.path) as connection:
            connection.execute(
                "INSERT INTO balance_snapshots(account_id, environment, currency, total, available, observed_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("demo-account", "demo", "USDT", 9999, 8999, datetime.now(UTC).isoformat()),
            )
            connection.execute(
                "INSERT INTO position_snapshots(account_id, environment, symbol, quantity, mark_price, observed_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "demo-account",
                    "demo",
                    "BTC-USDT-SWAP",
                    0.1,
                    60000,
                    datetime.now(UTC).isoformat(),
                ),
            )
        reconciliation = self.engine.reconcile("demo-account")
        self.assertFalse(reconciliation["passed"])
        self.assertGreaterEqual(len(reconciliation["difference_ids"]), 2)
        resolved = self.engine.resolve_diff(
            reconciliation["difference_ids"][0], "operator", "accepted external snapshot"
        )
        self.assertEqual(resolved["status"], "resolved")
        diff_detail = self.engine.reconciliation_diff(reconciliation["difference_ids"][0])
        self.assertIn("local", diff_detail)
        self.assertIn("external", diff_detail)
        account = self.engine.account("demo-account")
        self.assertEqual(account["account_id"], "demo-account")
        self.assertEqual(account["environment"], "demo")
        dashboard = self.engine.dashboard()
        summary = dashboard["account_summary"]["accounts"][0]
        self.assertEqual(summary["account_id"], "demo-account")
        self.assertEqual(summary["equity"], 1000000.0)
        self.assertIn("unrealized_pnl", summary)

        self.engine.set_risk_mode("global", "cancel_only", "reconciliation drill", "operator-a")
        with self.assertRaisesRegex(ValueError, "zero unresolved"):
            self.engine.set_risk_mode("global", "normal", "attempted recovery", "operator-a")
        for diff_id in reconciliation["difference_ids"][1:]:
            self.engine.resolve_diff(diff_id, "operator-a", "reviewed")
        restored_mode = self.engine.set_risk_mode(
            "global", "normal", "all diffs closed", "operator-a"
        )
        self.assertEqual(restored_mode["operator"], "operator-a")

        bars = [
            {"event_time": "2026-08-03T00:00:00Z", "close": 100},
            {"event_time": "2026-08-03T01:00:00Z", "close": 101},
            {"event_time": "2026-08-03T02:00:00Z", "close": 103},
        ]
        replay = self.engine.deterministic_replay("okx-momentum-1h", "1.0.0", bars)
        self.assertEqual(replay["signals"][0]["target"], 1)
        runtime = self.engine.record_runtime_result(
            "okx-momentum-1h", "1.0.0", {"order_id": order["order_id"], "replay": replay}
        )
        self.assertTrue(runtime["run_id"].startswith("runner-result-"))

    def test_reconciliation_recovers_owned_final_order_missing_from_account_snapshot(self) -> None:
        order = self.engine.submit(self.request("reconcile-final-order"))
        cancelled = self.engine.cancel(order["order_id"])
        self.assertEqual(cancelled["status"], "CANCELLED")
        self.adapter.include_orders_in_snapshot = False

        reconciliation = self.engine.reconcile("demo-account")

        self.assertTrue(reconciliation["passed"])
        self.assertEqual(reconciliation["difference_ids"], [])

    def test_reconciliation_ignores_unowned_external_history(self) -> None:
        self.adapter.orders["manual-history"] = ExternalOrder(
            external_order_id="okx-manual-history",
            client_order_id="",
            status="closed",
            filled_quantity=1.0,
            average_price=60000.0,
        )
        self.adapter.fills = (
            ExternalFill(
                external_fill_id="manual-fill",
                external_order_id="okx-manual-history",
                quantity=1.0,
                price=60000.0,
                fee=1.0,
                fee_currency="USDT",
                filled_at=datetime.now(UTC),
            ),
        )

        reconciliation = self.engine.reconcile("account-without-runner-orders")

        self.assertTrue(reconciliation["passed"])
        self.assertEqual(reconciliation["difference_ids"], [])

    def test_external_account_state_is_traceable_and_refresh_is_idempotent(self) -> None:
        order = self.engine.submit(self.request("traceable-refresh"))
        observed_at = datetime(2026, 8, 9, 6, 30, tzinfo=UTC)
        self.adapter.observed_at = observed_at
        self.adapter.fills = (
            ExternalFill(
                external_fill_id="fill-okx-1",
                external_order_id=order["external_order_id"],
                quantity=0.1,
                price=60000.0,
                fee=0.5,
                fee_currency="USDT",
                filled_at=observed_at,
            ),
        )

        first = self.engine.reconcile("demo-account")
        second = self.engine.reconcile("demo-account")
        self.assertTrue(first["passed"])
        self.assertTrue(second["passed"])

        with connect(self.path) as connection:
            counts_before_read = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("orders", "fills", "balance_snapshots", "position_snapshots")
            }
            fill = connection.execute(
                "SELECT * FROM fills WHERE external_fill_id='fill-okx-1'"
            ).fetchone()
            audit = connection.execute(
                """SELECT payload_json FROM audit_events
                   WHERE event_type='reconciliation_completed'
                   ORDER BY sequence DESC LIMIT 1"""
            ).fetchone()

        self.assertEqual(
            counts_before_read,
            {
                "orders": 1,
                "fills": 1,
                "balance_snapshots": 1,
                "position_snapshots": 1,
            },
        )
        self.assertEqual(fill["order_id"], order["order_id"])
        audit_payload = json.loads(audit["payload_json"])
        self.assertEqual(audit_payload["source"], "okx")
        self.assertEqual(audit_payload["observed_at"], observed_at.isoformat())

        account_first = self.engine.account("demo-account")
        account_second = self.engine.account("demo-account")
        detail = self.engine.order(order["order_id"])
        self.assertEqual(account_first, account_second)
        self.assertEqual(account_first["external_source"], "okx")
        self.assertEqual(account_first["latest_snapshot_at"], observed_at.isoformat())
        self.assertEqual(detail["external_source"], "okx")
        self.assertEqual(detail["fills"][0]["external_source"], "okx")

        with connect(self.path) as connection:
            counts_after_read = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("orders", "fills", "balance_snapshots", "position_snapshots")
            }
        self.assertEqual(counts_after_read, counts_before_read)

    def test_shadow_session_records_signal_target_and_theoretical_fill(self) -> None:
        shadow = RunnerEngine(self.path, self.adapter, self.key, "shadow")
        shadow.import_package(self.package)
        bars = [
            {
                "event_time": "2026-08-03T00:00:00Z",
                "observed_at": "2026-08-03T00:00:01Z",
                "close": 100,
            },
            {
                "event_time": "2026-08-03T01:00:00Z",
                "observed_at": "2026-08-03T01:00:01Z",
                "close": 101,
            },
            {
                "event_time": "2026-08-03T02:00:00Z",
                "observed_at": "2026-08-03T02:00:02Z",
                "close": 103,
            },
        ]
        result = shadow.run_shadow_session(
            "okx-momentum-1h", "1.0.0", bars, feed_mode="programmable_test_feed"
        )
        observation = result["result"]["observations"][0]
        self.assertEqual(observation["signal"], 1)
        self.assertEqual(observation["target_position"], 0.1)
        self.assertEqual(observation["theoretical_fill"]["side"], "buy")
        self.assertGreater(observation["theoretical_fill"]["estimated_price"], 103)
        self.assertEqual(result["result"]["external_orders_created"], 0)

        demo = RunnerEngine(self.path, self.adapter, self.key, "demo")
        with self.assertRaisesRegex(ValueError, "shadow environment"):
            demo.run_shadow_session(
                "okx-momentum-1h", "1.0.0", bars, feed_mode="programmable_test_feed"
            )

    def test_runner_routes_forbid_formula_and_ai_mutation(self) -> None:
        settings = RunnerSettings(
            version="1.0.0",
            host="127.0.0.1",
            port=8103,
            database_path=self.path,
            environment="demo",
            signing_key=self.key,
        )
        app = create_app(settings, self.adapter)
        paths = {route.path for route in app.routes}
        self.assertFalse(any("formula" in path or "ai" in path for path in paths))
        with TestClient(app) as client:
            health = client.get("/health").json()
            self.assertFalse(health["formula_editing"])
            self.assertFalse(health["ai_parameter_updates"])
            self.assertEqual(client.get("/api/strategies/okx-momentum-1h/1.0.0").status_code, 200)
            preflight = client.get("/api/preflight?symbols=BTC-USDT-SWAP").json()
            self.assertEqual(preflight["environment"], "demo")
            self.assertEqual(preflight["instruments"][0]["symbol"], "BTC-USDT-SWAP")


if __name__ == "__main__":
    unittest.main()
