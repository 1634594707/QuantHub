from __future__ import annotations

import json
import math
import sqlite3
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from packages.market_data import canonical_instrument_id
from packages.model_client import redact_secrets
from packages.research_protocol import canonical_json, content_hash
from packages.strategy_package import (
    StrategyReleasePackage,
    StrategyReleasePayload,
    verify_release_package,
)

from .adapter import AccountSnapshot, ExternalOrder, TradingAdapter
from .database import connect
from .schemas import AmendOrderRequest, ClosePositionRequest, OrderRequest

FINAL_STATUSES = {"FILLED", "CANCELLED", "REJECTED"}
OPEN_STATUSES = {"PENDING_SUBMIT", "SUBMITTED", "PARTIALLY_FILLED", "UNKNOWN"}
EXTERNAL_STATUS = {
    "live": "SUBMITTED",
    "open": "SUBMITTED",
    "submitted": "SUBMITTED",
    "partially_filled": "PARTIALLY_FILLED",
    "filled": "FILLED",
    "canceled": "CANCELLED",
    "cancelled": "CANCELLED",
    "rejected": "REJECTED",
    "unknown": "UNKNOWN",
}
TRANSITIONS = {
    "PENDING_SUBMIT": {"SUBMITTED", "PARTIALLY_FILLED", "FILLED", "REJECTED", "UNKNOWN"},
    "SUBMITTED": {"PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED", "UNKNOWN"},
    "PARTIALLY_FILLED": {"PARTIALLY_FILLED", "FILLED", "CANCELLED", "UNKNOWN"},
    "UNKNOWN": {"SUBMITTED", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED", "UNKNOWN"},
}


class RiskViolation(ValueError):
    pass


def _redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if any(
                    token in key.lower()
                    for token in ("api_key", "secret", "token", "passphrase", "private_key")
                )
                else _redact_payload(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_payload(item) for item in value]
    if isinstance(value, str):
        return redact_secrets(value)
    return value


class RunnerEngine:
    def __init__(
        self,
        database_path: Path,
        adapter: TradingAdapter,
        signing_key: bytes,
        environment: str,
        runner_version: str = "1.0.0",
    ) -> None:
        self.database_path = database_path
        self.adapter = adapter
        self.signing_key = signing_key
        self.environment = environment
        self.runner_version = runner_version

    def preflight(self, symbols: list[str]) -> dict[str, Any]:
        if self.environment != "demo":
            raise ValueError("OKX preflight requires the demo environment")
        return self.adapter.preflight(symbols)

    def funding_rate(self, symbol: str) -> dict[str, Any]:
        if self.environment != "demo":
            raise ValueError("OKX funding-rate evidence requires the demo environment")
        return self.adapter.funding_rate(symbol)

    def import_package(self, package: StrategyReleasePackage) -> dict[str, Any]:
        payload = verify_release_package(
            package,
            self.signing_key,
            runner_version=self.runner_version,
            environment=self.environment,
        )
        with connect(self.database_path) as connection:
            existing = connection.execute(
                "SELECT content_hash FROM strategy_versions WHERE strategy_id=? AND version=?",
                (payload.strategy_id, payload.version),
            ).fetchone()
            if existing:
                if existing["content_hash"] != package.content_sha256:
                    raise ValueError("an imported strategy version cannot be modified")
                return {
                    "strategy_id": payload.strategy_id,
                    "version": payload.version,
                    "content_hash": package.content_sha256,
                    "already_imported": True,
                }
            connection.execute(
                "INSERT INTO strategy_versions VALUES (?, ?, ?, ?, ?)",
                (
                    payload.strategy_id,
                    payload.version,
                    package.model_dump_json(),
                    package.content_sha256,
                    datetime.now(UTC).isoformat(),
                ),
            )
            self._audit(
                connection,
                "strategy_imported",
                {"strategy_id": payload.strategy_id, "version": payload.version},
            )
        return {
            "strategy_id": payload.strategy_id,
            "version": payload.version,
            "content_hash": package.content_sha256,
            "already_imported": False,
        }

    def _package(self, strategy_id: str, version: str) -> StrategyReleasePayload:
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT package_json FROM strategy_versions WHERE strategy_id=? AND version=?",
                (strategy_id, version),
            ).fetchone()
        if row is None:
            raise LookupError("strategy version is not imported")
        package = StrategyReleasePackage.model_validate_json(row["package_json"])
        return verify_release_package(
            package,
            self.signing_key,
            runner_version=self.runner_version,
            environment=self.environment,
        )

    @staticmethod
    def client_order_id(request: OrderRequest) -> str:
        identity = {
            "strategy_id": request.strategy_id,
            "strategy_version": request.strategy_version,
            "intent_id": request.intent_id,
            "account_id": request.account_id,
            "symbol": request.symbol,
            "side": request.side,
        }
        return "qh" + sha256(canonical_json(identity).encode("utf-8")).hexdigest()[:30]

    def _risk_mode(self, account_id: str) -> str:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT scope, mode FROM risk_states WHERE scope IN ('global', ?)",
                (f"account:{account_id}",),
            ).fetchall()
        modes = {row["mode"] for row in rows}
        if "halted" in modes:
            return "halted"
        if "cancel_only" in modes:
            return "cancel_only"
        return "normal"

    @staticmethod
    def _snapshot_equity(snapshot: AccountSnapshot) -> float:
        return sum(float(values.get("total", 0)) for values in snapshot.balances.values())

    def _risk_snapshot(
        self, request: OrderRequest, *, exclude_order_id: str | None = None
    ) -> tuple[AccountSnapshot, dict[str, Any]]:
        snapshot = self.adapter.account_snapshot(request.account_id)
        now = datetime.now(UTC)
        observed_at = snapshot.observed_at.astimezone(UTC)
        if observed_at < now - timedelta(seconds=90) or observed_at > now + timedelta(seconds=5):
            raise RiskViolation("account snapshot is stale or has an invalid timestamp")
        equity = self._snapshot_equity(snapshot)
        if equity <= 0:
            raise RiskViolation("account snapshot has no positive equity")
        # Risk is marked against the adapter's trusted market price.  The
        # limit price is an execution instruction and must never lower the
        # server-side exposure calculation.
        mark_price = self.adapter.mark_price(request.symbol)
        if mark_price <= 0:
            raise RiskViolation("no usable mark price for requested instrument")
        current_position = snapshot.positions.get(request.symbol, {})
        current_quantity = float(current_position.get("quantity", 0))
        if request.reduce_only:
            valid_reduce = (
                current_quantity > 0
                and request.side == "sell"
                and request.quantity <= current_quantity
            ) or (
                current_quantity < 0
                and request.side == "buy"
                and request.quantity <= abs(current_quantity)
            )
            if not valid_reduce:
                raise RiskViolation("reduce-only order would increase or reverse the position")
        symbol_exposure = sum(
            abs(float(position.get("quantity", 0)) * float(position.get("mark_price", 0)))
            for symbol, position in snapshot.positions.items()
            if symbol == request.symbol
        )
        total_exposure = sum(
            abs(float(position.get("quantity", 0)) * float(position.get("mark_price", 0)))
            for position in snapshot.positions.values()
        )
        current_position_exposure = abs(
            current_quantity * float(current_position.get("mark_price", mark_price))
        )
        open_symbol_exposure = 0.0
        with connect(self.database_path) as connection:
            open_orders = connection.execute(
                """SELECT order_id, symbol, quantity, price FROM orders
                   WHERE account_id=? AND status IN ('PENDING_SUBMIT', 'SUBMITTED', 'PARTIALLY_FILLED', 'UNKNOWN')""",
                (request.account_id,),
            ).fetchall()
            previous_equities = connection.execute(
                "SELECT total FROM balance_snapshots WHERE account_id=? ORDER BY observed_at DESC LIMIT 500",
                (request.account_id,),
            ).fetchall()
        for order in open_orders:
            if order["order_id"] == exclude_order_id:
                continue
            try:
                price = float(self.adapter.mark_price(order["symbol"]))
            except Exception:  # noqa: BLE001 - adapters expose provider-specific failures
                price = float(
                    order["price"] or (mark_price if order["symbol"] == request.symbol else 0)
                )
            if price <= 0:
                raise RiskViolation(f"no usable mark price for open order {order['symbol']}")
            exposure = abs(float(order["quantity"]) * price)
            total_exposure += exposure
            if order["symbol"] == request.symbol:
                symbol_exposure += exposure
                open_symbol_exposure += exposure
        peak_equity = max(
            [
                equity,
                float(snapshot.peak_equity or 0),
                *(float(row["total"]) for row in previous_equities),
            ]
        )
        requested_notional = abs(request.quantity * mark_price)
        if request.reduce_only:
            signed = request.quantity if request.side == "buy" else -request.quantity
            projected_position_exposure = abs((current_quantity + signed) * mark_price)
            projected_symbol_exposure = open_symbol_exposure + projected_position_exposure
            projected_total_exposure = (
                total_exposure - current_position_exposure + projected_position_exposure
            )
        else:
            projected_symbol_exposure = symbol_exposure + requested_notional
            projected_total_exposure = total_exposure + requested_notional
        calculation = {
            "observed_at": observed_at.isoformat(),
            "equity": equity,
            "mark_price": mark_price,
            "requested_order_price": request.price,
            "existing_symbol_exposure": symbol_exposure,
            "existing_total_exposure": total_exposure,
            "requested_notional": requested_notional,
            "reduce_only": request.reduce_only,
            "current_quantity": current_quantity,
            "projected_symbol_exposure": projected_symbol_exposure / equity,
            "projected_total_exposure": projected_total_exposure / equity,
            "realized_loss": max(0.0, -float(snapshot.realized_pnl)),
            "drawdown": max(0.0, (peak_equity - equity) / peak_equity),
            "peak_equity": peak_equity,
        }
        return snapshot, calculation

    def _record_risk_decision(
        self,
        request: OrderRequest,
        package: StrategyReleasePayload,
        calculation: dict[str, Any],
        outcome: str,
        reason: str | None = None,
    ) -> None:
        snapshot_reference = content_hash(
            {
                "account_id": request.account_id,
                "observed_at": calculation["observed_at"],
                "calculation": calculation,
            }
        )
        with connect(self.database_path) as connection:
            connection.execute(
                """INSERT INTO risk_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"risk-{uuid.uuid4().hex}",
                    request.account_id,
                    request.intent_id,
                    request.strategy_id,
                    request.strategy_version,
                    snapshot_reference,
                    canonical_json(package.risk_limits.model_dump(mode="json")),
                    canonical_json(calculation),
                    outcome,
                    reason,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def _validate_risk(
        self,
        request: OrderRequest,
        package: StrategyReleasePayload,
        *,
        exclude_order_id: str | None = None,
    ) -> dict[str, Any]:
        mode = self._risk_mode(request.account_id)
        if mode != "normal":
            reason = f"new orders are blocked while risk mode is {mode}"
            self._record_risk_decision(
                request,
                package,
                {"risk_mode": mode, "observed_at": datetime.now(UTC).isoformat()},
                "rejected",
                reason,
            )
            raise RiskViolation(reason)
        rules = self.adapter.instrument_rules(request.symbol)
        limits = package.risk_limits
        decision_recorded = False
        try:
            _, calculation = self._risk_snapshot(request, exclude_order_id=exclude_order_id)
            mark_price = calculation["mark_price"]
            checks = (
                (
                    request.order_type == "limit" and request.price is None,
                    "limit order requires a price",
                ),
                (request.quantity < rules.minimum_quantity, "quantity is below instrument minimum"),
                (
                    not math.isclose(
                        request.quantity / rules.quantity_step,
                        round(request.quantity / rules.quantity_step),
                        abs_tol=1e-8,
                    ),
                    "quantity does not match instrument precision",
                ),
                (
                    request.price is not None
                    and not math.isclose(
                        request.price / rules.price_tick,
                        round(request.price / rules.price_tick),
                        abs_tol=1e-8,
                    ),
                    "price does not match instrument precision",
                ),
                (
                    request.stop_loss is not None
                    and (
                        request.stop_loss.trigger_price >= mark_price
                        if request.side == "buy"
                        else request.stop_loss.trigger_price <= mark_price
                    ),
                    "stop loss trigger is on the wrong side of the market",
                ),
                (
                    request.take_profit is not None
                    and (
                        request.take_profit.trigger_price <= mark_price
                        if request.side == "buy"
                        else request.take_profit.trigger_price >= mark_price
                    ),
                    "take profit trigger is on the wrong side of the market",
                ),
                (
                    request.leverage > min(limits.max_leverage, rules.maximum_leverage),
                    "leverage exceeds a hard limit",
                ),
                (
                    not request.reduce_only
                    and calculation["projected_symbol_exposure"] > limits.max_symbol_exposure,
                    "symbol exposure exceeds package hard limit",
                ),
                (
                    not request.reduce_only
                    and calculation["projected_total_exposure"] > limits.max_total_exposure,
                    "total exposure exceeds package hard limit",
                ),
                (calculation["realized_loss"] >= limits.max_loss, "loss hard limit reached"),
                (calculation["drawdown"] >= limits.max_drawdown, "drawdown hard limit reached"),
            )
            for failed, reason in checks:
                if failed:
                    self._record_risk_decision(request, package, calculation, "rejected", reason)
                    decision_recorded = True
                    raise RiskViolation(reason)
            self._record_risk_decision(request, package, calculation, "approved")
            return calculation
        except RiskViolation as exc:
            if not decision_recorded:
                self._record_risk_decision(
                    request,
                    package,
                    {
                        "observed_at": datetime.now(UTC).isoformat(),
                        "risk_snapshot_error": str(exc),
                    },
                    "rejected",
                    str(exc),
                )
            raise
        except Exception as exc:  # noqa: BLE001
            reason = redact_secrets(f"risk snapshot unavailable: {type(exc).__name__}: {exc}")
            self._record_risk_decision(
                request, package, {"observed_at": datetime.now(UTC).isoformat()}, "rejected", reason
            )
            raise RiskViolation(reason) from exc

    def submit(self, request: OrderRequest) -> dict[str, Any]:
        client_id = self.client_order_id(request)
        with connect(self.database_path) as connection:
            existing = connection.execute(
                "SELECT * FROM orders WHERE client_order_id=?", (client_id,)
            ).fetchone()
        if existing is not None:
            return dict(existing) | {"idempotent_replay": True}

        package = self._package(request.strategy_id, request.strategy_version)
        risk_calculation = self._validate_risk(request, package)
        now = datetime.now(UTC).isoformat()
        order_id = f"order-{uuid.uuid4().hex}"
        raw_request = request.model_dump(mode="json") | {
            "client_order_id": client_id,
            "instrument_id": canonical_instrument_id("okx", request.symbol),
        }
        raw_request["risk_snapshot"] = risk_calculation
        safe_json = redact_secrets(canonical_json(raw_request))
        with connect(self.database_path) as connection:
            try:
                connection.execute(
                    """INSERT INTO orders(
                        order_id, client_order_id, strategy_id, strategy_version, account_id,
                        environment, symbol, side, order_type, quantity, price, leverage,
                        request_json, request_hash, external_order_id, status, filled_quantity,
                        average_price, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL,
                              'PENDING_SUBMIT', 0, NULL, ?, ?)""",
                    (
                        order_id,
                        client_id,
                        request.strategy_id,
                        request.strategy_version,
                        request.account_id,
                        self.environment,
                        request.symbol,
                        request.side,
                        request.order_type,
                        request.quantity,
                        request.price,
                        request.leverage,
                        safe_json,
                        content_hash(raw_request),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT * FROM orders WHERE client_order_id=?", (client_id,)
                ).fetchone()
                if row is None:
                    raise
                return dict(row) | {"idempotent_replay": True}
            self._event(
                connection,
                order_id,
                None,
                "PENDING_SUBMIT",
                None,
                {"request_hash": content_hash(raw_request)},
            )

        try:
            external = self.adapter.submit_order(json.loads(safe_json))
        except (TimeoutError, ConnectionError):
            external = self.adapter.fetch_order_by_client_id(client_id, request.symbol)
            if external is None:
                self._transition(order_id, "UNKNOWN", payload={"reason": "submit outcome unknown"})
                return self.order(order_id) | {"idempotent_replay": False}
        # Adapter libraries expose provider-specific exception hierarchies. Any
        # non-network submission failure must still become an auditable rejection.
        except Exception as exc:  # noqa: BLE001
            self._transition(
                order_id,
                "REJECTED",
                payload={"error": redact_secrets(f"{type(exc).__name__}: {exc}")},
            )
            return self.order(order_id) | {"idempotent_replay": False}
        self._apply_external(order_id, external)
        return self.order(order_id) | {"idempotent_replay": False}

    def _apply_external(self, order_id: str, external: ExternalOrder) -> None:
        status = EXTERNAL_STATUS.get(external.status.lower(), "UNKNOWN")
        self._transition(
            order_id,
            status,
            external_order_id=external.external_order_id,
            filled_quantity=external.filled_quantity,
            average_price=external.average_price,
            payload=external.raw or {},
        )

    def _transition(
        self,
        order_id: str,
        status: str,
        *,
        external_order_id: str | None = None,
        filled_quantity: float | None = None,
        average_price: float | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM orders WHERE order_id=?", (order_id,)
            ).fetchone()
            if row is None:
                raise LookupError("order not found")
            current = row["status"]
            if current == status:
                connection.execute(
                    """UPDATE orders SET external_order_id=COALESCE(?, external_order_id),
                        filled_quantity=COALESCE(?, filled_quantity),
                        average_price=COALESCE(?, average_price), updated_at=? WHERE order_id=?""",
                    (
                        external_order_id,
                        filled_quantity,
                        average_price,
                        datetime.now(UTC).isoformat(),
                        order_id,
                    ),
                )
                return
            if current in FINAL_STATUSES:
                if current == status:
                    return
                raise ValueError(f"cannot transition final order from {current} to {status}")
            if status not in TRANSITIONS.get(current, set()):
                raise ValueError(f"invalid order transition {current} -> {status}")
            safe_payload = _redact_payload(payload or {})
            connection.execute(
                """UPDATE orders SET status=?, external_order_id=COALESCE(?, external_order_id),
                    filled_quantity=COALESCE(?, filled_quantity),
                    average_price=COALESCE(?, average_price), updated_at=? WHERE order_id=?""",
                (
                    status,
                    external_order_id,
                    filled_quantity,
                    average_price,
                    datetime.now(UTC).isoformat(),
                    order_id,
                ),
            )
            self._event(connection, order_id, current, status, external_order_id, safe_payload)

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        order_id: str,
        from_status: str | None,
        to_status: str,
        external_order_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        connection.execute(
            """INSERT INTO order_events(
                order_id, from_status, to_status, external_order_id, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                order_id,
                from_status,
                to_status,
                external_order_id,
                canonical_json(payload),
                datetime.now(UTC).isoformat(),
            ),
        )

    @staticmethod
    def _audit(connection: sqlite3.Connection, event_type: str, payload: dict[str, Any]) -> None:
        connection.execute(
            "INSERT INTO audit_events(event_type, payload_json, created_at) VALUES (?, ?, ?)",
            (event_type, canonical_json(payload), datetime.now(UTC).isoformat()),
        )

    def order(self, order_id: str) -> dict[str, Any]:
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM orders WHERE order_id=?", (order_id,)
            ).fetchone()
            if row is None:
                raise LookupError("order not found")
            events = connection.execute(
                "SELECT * FROM order_events WHERE order_id=? ORDER BY sequence", (order_id,)
            ).fetchall()
            fills = connection.execute(
                "SELECT * FROM fills WHERE order_id=? ORDER BY filled_at", (order_id,)
            ).fetchall()
            intent_id = json.loads(row["request_json"])["intent_id"]
            decisions = connection.execute(
                """SELECT decision_id, snapshot_reference, limits_json, calculation_json,
                          outcome, reason, created_at FROM risk_decisions
                   WHERE intent_id=? AND account_id=? ORDER BY created_at""",
                (intent_id, row["account_id"]),
            ).fetchall()
        return dict(row) | {
            "external_source": "okx" if row["external_order_id"] or fills else None,
            "events": [
                dict(event) | {"payload": json.loads(event["payload_json"])} for event in events
            ],
            "fills": [dict(fill) | {"external_source": "okx"} for fill in fills],
            "risk_decisions": [
                dict(decision)
                | {
                    "limits": json.loads(decision["limits_json"]),
                    "calculation": json.loads(decision["calculation_json"]),
                }
                for decision in decisions
            ],
        }

    def strategy(self, strategy_id: str, version: str) -> dict[str, Any]:
        payload = self._package(strategy_id, version)
        with connect(self.database_path) as connection:
            metadata = connection.execute(
                """SELECT content_hash, imported_at FROM strategy_versions
                   WHERE strategy_id=? AND version=?""",
                (strategy_id, version),
            ).fetchone()
            orders = connection.execute(
                """SELECT order_id, account_id, symbol, side, status, external_order_id, updated_at
                   FROM orders WHERE strategy_id=? AND strategy_version=? ORDER BY updated_at DESC LIMIT 100""",
                (strategy_id, version),
            ).fetchall()
            runtime_results = connection.execute(
                """SELECT run_id, environment, result_hash, created_at FROM runtime_results
                   WHERE strategy_id=? AND strategy_version=? ORDER BY created_at DESC LIMIT 100""",
                (strategy_id, version),
            ).fetchall()
        if metadata is None:
            raise LookupError("strategy version is not imported")
        return {
            "strategy_id": strategy_id,
            "version": version,
            "content_hash": metadata["content_hash"],
            "imported_at": metadata["imported_at"],
            "package": payload.model_dump(mode="json"),
            "orders": [dict(row) for row in orders],
            "runtime_results": [dict(row) for row in runtime_results],
        }

    def account(self, account_id: str) -> dict[str, Any]:
        with connect(self.database_path) as connection:
            balances = connection.execute(
                """SELECT currency, total, available, observed_at FROM balance_snapshots
                   WHERE account_id=? ORDER BY observed_at DESC LIMIT 20""",
                (account_id,),
            ).fetchall()
            positions = connection.execute(
                """SELECT symbol, quantity, mark_price, observed_at FROM position_snapshots
                   WHERE account_id=? ORDER BY observed_at DESC LIMIT 50""",
                (account_id,),
            ).fetchall()
            orders = connection.execute(
                """SELECT order_id, symbol, side, status, updated_at FROM orders
                   WHERE account_id=? ORDER BY updated_at DESC LIMIT 50""",
                (account_id,),
            ).fetchall()
            reconciliation = connection.execute(
                """SELECT created_at, payload_json FROM audit_events
                   WHERE event_type='reconciliation_completed' ORDER BY sequence DESC LIMIT 100"""
            ).fetchall()
        last_reconciliation_at = next(
            (
                row["created_at"]
                for row in reconciliation
                if json.loads(row["payload_json"]).get("account_id") == account_id
            ),
            None,
        )
        latest = max([row["observed_at"] for row in [*balances, *positions]], default=None)
        if not balances and not positions and not orders:
            raise LookupError("account has no Runner-owned records")
        return {
            "account_id": account_id,
            "environment": self.environment,
            "external_source": "okx",
            "permissions": "trade" if self.environment in {"demo", "live"} else "read_only",
            "latest_snapshot_at": latest,
            "last_reconciliation_at": last_reconciliation_at,
            "balances": [dict(row) for row in balances],
            "positions": [dict(row) for row in positions],
            "orders": [dict(row) for row in orders],
        }

    def reconciliation_diff(self, diff_id: str) -> dict[str, Any]:
        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM reconciliation_diffs WHERE diff_id=?", (diff_id,)
            ).fetchone()
        if row is None:
            raise LookupError("reconciliation difference not found")
        return dict(row) | {
            "local": json.loads(row["local_json"]),
            "external": json.loads(row["external_json"]),
        }

    def dashboard(self) -> dict[str, Any]:
        with connect(self.database_path) as connection:
            strategies = connection.execute(
                """SELECT strategy_id, version, package_json, content_hash, imported_at
                   FROM strategy_versions ORDER BY imported_at DESC"""
            ).fetchall()
            orders = connection.execute(
                """SELECT order_id, client_order_id, strategy_id, strategy_version, account_id,
                          environment, symbol, side, order_type, quantity, price, leverage,
                          external_order_id, status, filled_quantity, average_price,
                          created_at, updated_at
                   FROM orders ORDER BY updated_at DESC LIMIT 200"""
            ).fetchall()
            fills = connection.execute(
                """SELECT f.*, o.symbol, o.side FROM fills f JOIN orders o USING(order_id)
                   ORDER BY f.filled_at DESC LIMIT 200"""
            ).fetchall()
            balances = connection.execute(
                """SELECT * FROM balance_snapshots ORDER BY observed_at DESC LIMIT 100"""
            ).fetchall()
            positions = connection.execute(
                """SELECT * FROM position_snapshots ORDER BY observed_at DESC LIMIT 100"""
            ).fetchall()
            account_snapshots = connection.execute(
                """SELECT account_id, environment, equity, realized_pnl,
                          unrealized_pnl, peak_equity, observed_at
                   FROM account_snapshots ORDER BY observed_at DESC LIMIT 500"""
            ).fetchall()
            diffs = connection.execute(
                """SELECT diff_id, account_id, kind, key, status, owner, resolution,
                          created_at, resolved_at
                   FROM reconciliation_diffs ORDER BY created_at DESC LIMIT 200"""
            ).fetchall()
            risk_states = connection.execute("SELECT * FROM risk_states ORDER BY scope").fetchall()
            incidents = connection.execute(
                """SELECT sequence, event_type, payload_json, created_at
                   FROM audit_events ORDER BY sequence DESC LIMIT 100"""
            ).fetchall()
            runtime_results = connection.execute(
                """SELECT run_id, strategy_id, strategy_version, environment, result_hash, created_at
                   FROM runtime_results ORDER BY created_at DESC LIMIT 100"""
            ).fetchall()
            risk_decisions = connection.execute(
                """SELECT decision_id, account_id, intent_id, strategy_id, strategy_version,
                          snapshot_reference, calculation_json, outcome, reason, created_at
                   FROM risk_decisions ORDER BY created_at DESC LIMIT 100"""
            ).fetchall()
            reconciliation_events = connection.execute(
                """SELECT payload_json, created_at FROM audit_events
                   WHERE event_type='reconciliation_completed' ORDER BY sequence DESC LIMIT 1"""
            ).fetchone()
        now = datetime.now(UTC)
        latest_times = [
            datetime.fromisoformat(row["observed_at"])
            for row in [*balances, *positions, *account_snapshots]
            if row["observed_at"]
        ]
        latest_snapshot_at = max(latest_times) if latest_times else None
        snapshot_stale = latest_snapshot_at is None or latest_snapshot_at < now - timedelta(
            seconds=90
        )
        histories: dict[str, list[dict[str, Any]]] = {}
        for row in reversed(account_snapshots):
            histories.setdefault(row["account_id"], []).append(dict(row))
        account_summary: list[dict[str, Any]] = []
        for account_id, history in histories.items():
            latest = history[-1]
            equities = [float(item["equity"]) for item in history]
            initial_equity = equities[0]
            peak = 0.0
            max_drawdown = 0.0
            for value in equities:
                peak = max(peak, value)
                if peak > 0:
                    max_drawdown = min(max_drawdown, (value - peak) / peak)
            equity_change = float(latest["equity"]) - initial_equity
            reported_pnl = float(latest["realized_pnl"]) + float(latest["unrealized_pnl"])
            account_summary.append(
                {
                    "account_id": account_id,
                    "environment": latest["environment"],
                    "equity_currency": "USD",
                    "equity": float(latest["equity"]),
                    "initial_equity": initial_equity,
                    "equity_change": equity_change,
                    "realized_pnl": float(latest["realized_pnl"]),
                    "unrealized_pnl": float(latest["unrealized_pnl"]),
                    "total_pnl": reported_pnl if reported_pnl else equity_change,
                    "peak_equity": peak,
                    "max_drawdown": max_drawdown,
                    "observed_at": latest["observed_at"],
                }
            )
        return {
            "strategies": [
                dict(row)
                | {
                    "package": json.loads(row["package_json"])["payload"],
                }
                for row in strategies
            ],
            "orders": [dict(row) for row in orders],
            "fills": [dict(row) for row in fills],
            "balances": [dict(row) for row in balances],
            "positions": [dict(row) for row in positions],
            "account_summary": {"accounts": account_summary},
            "reconciliation_diffs": [dict(row) for row in diffs],
            "risk_states": [dict(row) for row in risk_states],
            "incidents": [
                dict(row) | {"payload": json.loads(row["payload_json"])} for row in incidents
            ],
            "runtime_results": [dict(row) for row in runtime_results],
            "risk_decisions": [
                dict(row) | {"calculation": json.loads(row["calculation_json"])}
                for row in risk_decisions
            ],
            "account_status": {
                "environment": self.environment,
                "connected": latest_snapshot_at is not None,
                "permissions": "trade" if self.environment in {"demo", "live"} else "read_only",
                "latest_snapshot_at": latest_snapshot_at.isoformat()
                if latest_snapshot_at
                else None,
                "stale": snapshot_stale,
                "last_reconciliation_at": reconciliation_events["created_at"]
                if reconciliation_events
                else None,
                "server_time": now.isoformat(),
            },
        }

    def cancel(self, order_id: str) -> dict[str, Any]:
        order = self.order(order_id)
        if order["status"] in FINAL_STATUSES:
            return order
        if not order["external_order_id"]:
            self._transition(
                order_id, "UNKNOWN", payload={"reason": "cannot cancel without external id"}
            )
            return self.order(order_id)
        external = self.adapter.cancel_order(order["external_order_id"])
        self._apply_external(order_id, external)
        return self.order(order_id)

    def amend(self, order_id: str, amendment: AmendOrderRequest) -> dict[str, Any]:
        order = self.order(order_id)
        if order["status"] not in OPEN_STATUSES:
            raise ValueError("only open orders can be amended")
        if not order["external_order_id"]:
            raise ValueError("cannot amend an order without an external order id")
        original = json.loads(order["request_json"])
        merged = {
            key: original.get(key)
            for key in (
                "strategy_id",
                "strategy_version",
                "intent_id",
                "account_id",
                "symbol",
                "side",
                "order_type",
                "leverage",
                "reduce_only",
            )
        }
        merged.update(amendment.model_dump(mode="json"))
        request = OrderRequest.model_validate(merged)
        risk_calculation = self._validate_risk(
            request,
            self._package(request.strategy_id, request.strategy_version),
            exclude_order_id=order_id,
        )
        external_request = request.model_dump(mode="json") | {
            "client_order_id": order["client_order_id"],
            "risk_snapshot": risk_calculation,
        }
        external = self.adapter.amend_order(
            order["external_order_id"], order["symbol"], external_request
        )
        now = datetime.now(UTC).isoformat()
        safe_json = redact_secrets(canonical_json(external_request))
        with connect(self.database_path) as connection:
            connection.execute(
                """UPDATE orders SET quantity=?, price=?, request_json=?, request_hash=?,
                   updated_at=? WHERE order_id=?""",
                (
                    request.quantity,
                    request.price,
                    safe_json,
                    content_hash(external_request),
                    now,
                    order_id,
                ),
            )
            self._event(
                connection,
                order_id,
                order["status"],
                order["status"],
                order["external_order_id"],
                {"amended": True, "risk_snapshot": risk_calculation},
            )
        self._apply_external(order_id, external)
        return self.order(order_id)

    def close_position(
        self, account_id: str, symbol: str, request: ClosePositionRequest
    ) -> dict[str, Any]:
        snapshot = self.adapter.account_snapshot(account_id)
        position = snapshot.positions.get(symbol)
        current_quantity = float((position or {}).get("quantity", 0))
        if abs(current_quantity) <= 1e-12:
            raise ValueError("position is already flat")
        quantity = request.quantity or abs(current_quantity)
        if quantity > abs(current_quantity):
            raise RiskViolation("close quantity exceeds the current position")
        intent = OrderRequest(
            strategy_id=request.strategy_id,
            strategy_version=request.strategy_version,
            intent_id=request.intent_id,
            account_id=account_id,
            symbol=symbol,
            side="sell" if current_quantity > 0 else "buy",
            order_type=request.order_type,
            quantity=quantity,
            price=request.price,
            reduce_only=True,
        )
        return self.submit(intent)

    def recover_open_orders(self) -> list[dict[str, Any]]:
        with connect(self.database_path) as connection:
            rows = connection.execute(
                f"SELECT order_id, client_order_id, symbol FROM orders WHERE status IN ({','.join('?' for _ in OPEN_STATUSES)})",
                tuple(sorted(OPEN_STATUSES)),
            ).fetchall()
        recovered: list[dict[str, Any]] = []
        for row in rows:
            external = self.adapter.fetch_order_by_client_id(row["client_order_id"], row["symbol"])
            if external is not None:
                self._apply_external(row["order_id"], external)
            elif self.order(row["order_id"])["status"] != "UNKNOWN":
                self._transition(
                    row["order_id"], "UNKNOWN", payload={"reason": "not found during recovery"}
                )
            recovered.append(self.order(row["order_id"]))
        return recovered

    def set_risk_mode(
        self, scope: str, mode: str, reason: str, operator: str = "system"
    ) -> dict[str, str]:
        if scope != "global" and not scope.startswith("account:"):
            raise ValueError("risk scope must be global or account:<id>")
        if mode not in {"normal", "halted", "cancel_only"}:
            raise ValueError("invalid risk mode")
        with connect(self.database_path) as connection:
            if mode == "normal":
                unresolved = connection.execute(
                    "SELECT COUNT(*) FROM reconciliation_diffs WHERE status='open'"
                ).fetchone()[0]
                if unresolved:
                    raise ValueError(
                        "normal mode requires zero unresolved reconciliation differences"
                    )
            connection.execute(
                """INSERT INTO risk_states VALUES (?, ?, ?, ?)
                ON CONFLICT(scope) DO UPDATE SET mode=excluded.mode, reason=excluded.reason,
                    updated_at=excluded.updated_at""",
                (scope, mode, reason, datetime.now(UTC).isoformat()),
            )
            self._audit(
                connection,
                "risk_mode_changed",
                {"scope": scope, "mode": mode, "reason": reason, "operator": operator},
            )
        return {"scope": scope, "mode": mode, "reason": reason, "operator": operator}

    def reconcile(self, account_id: str) -> dict[str, Any]:
        snapshot = self.adapter.account_snapshot(account_id)
        observed_at = snapshot.observed_at
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)
        observed_at_text = observed_at.astimezone(UTC).isoformat()
        with connect(self.database_path) as connection:
            local_orders = {
                row["client_order_id"]: dict(row)
                for row in connection.execute(
                    "SELECT * FROM orders WHERE account_id=?", (account_id,)
                ).fetchall()
            }
            local_fills = {
                row["external_fill_id"]: dict(row)
                for row in connection.execute(
                    """SELECT f.* FROM fills f JOIN orders o USING(order_id)
                    WHERE o.account_id=?""",
                    (account_id,),
                ).fetchall()
            }
            # OKX account history can contain manual or third-party orders. Reconciliation
            # owns only orders whose client id is already present in the Runner ledger.
            external_orders = {
                order.client_order_id: order
                for order in snapshot.orders
                if order.client_order_id and order.client_order_id in local_orders
            }
            for client_order_id, local_order in local_orders.items():
                if client_order_id in external_orders:
                    continue
                recovered = self.adapter.fetch_order_by_client_id(
                    client_order_id, local_order["symbol"]
                )
                if recovered is not None:
                    external_orders[client_order_id] = recovered
            diffs: list[str] = []
            for key in sorted(set(local_orders) | set(external_orders)):
                local = local_orders.get(key)
                external = external_orders.get(key)
                local_status = local["status"] if local else None
                external_status = (
                    EXTERNAL_STATUS.get(external.status.lower(), "UNKNOWN") if external else None
                )
                if local_status != external_status:
                    diffs.append(
                        self._record_diff(
                            connection,
                            account_id,
                            "order",
                            key,
                            local or {},
                            external.__dict__ if external else {},
                        )
                    )
            orders_by_external_id = {
                row["external_order_id"]: row["order_id"]
                for row in local_orders.values()
                if row.get("external_order_id")
            }
            external_fills = {
                fill.external_fill_id: fill
                for fill in snapshot.fills
                if fill.external_order_id in orders_by_external_id
            }
            imported_fill_ids: list[str] = []
            for key in sorted(set(local_fills) | set(external_fills)):
                external_fill = external_fills.get(key)
                if key not in local_fills and external_fill is not None:
                    order_id = orders_by_external_id.get(external_fill.external_order_id)
                    if order_id:
                        connection.execute(
                            """INSERT OR IGNORE INTO fills(
                                external_fill_id, order_id, quantity, price, fee,
                                fee_currency, filled_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (
                                external_fill.external_fill_id,
                                order_id,
                                external_fill.quantity,
                                external_fill.price,
                                external_fill.fee,
                                external_fill.fee_currency,
                                external_fill.filled_at.isoformat(),
                            ),
                        )
                        imported_fill_ids.append(external_fill.external_fill_id)
                        continue
                if key not in local_fills or key not in external_fills:
                    diffs.append(
                        self._record_diff(
                            connection,
                            account_id,
                            "fill",
                            key,
                            local_fills.get(key, {}),
                            external_fills[key].__dict__ if key in external_fills else {},
                        )
                    )
            for currency, values in snapshot.balances.items():
                local = connection.execute(
                    """SELECT total, available FROM balance_snapshots
                    WHERE account_id=? AND currency=? ORDER BY id DESC LIMIT 1""",
                    (account_id, currency),
                ).fetchone()
                if local and (
                    not math.isclose(local["total"], values["total"], abs_tol=1e-8)
                    or not math.isclose(local["available"], values["available"], abs_tol=1e-8)
                ):
                    diffs.append(
                        self._record_diff(
                            connection, account_id, "balance", currency, dict(local), values
                        )
                    )
                connection.execute(
                    """INSERT INTO balance_snapshots(
                        account_id, environment, currency, total, available, observed_at
                    ) SELECT ?, ?, ?, ?, ?, ?
                    WHERE NOT EXISTS (
                        SELECT 1 FROM balance_snapshots
                        WHERE account_id=? AND environment=? AND currency=?
                          AND total=? AND available=? AND observed_at=?
                    )""",
                    (
                        account_id,
                        self.environment,
                        currency,
                        values["total"],
                        values["available"],
                        observed_at_text,
                        account_id,
                        self.environment,
                        currency,
                        values["total"],
                        values["available"],
                        observed_at_text,
                    ),
                )
            for symbol, values in snapshot.positions.items():
                local = connection.execute(
                    """SELECT quantity, mark_price FROM position_snapshots
                    WHERE account_id=? AND symbol=? ORDER BY id DESC LIMIT 1""",
                    (account_id, symbol),
                ).fetchone()
                if local and (
                    not math.isclose(local["quantity"], values["quantity"], abs_tol=1e-8)
                    or not math.isclose(local["mark_price"], values["mark_price"], abs_tol=1e-8)
                ):
                    diffs.append(
                        self._record_diff(
                            connection, account_id, "position", symbol, dict(local), values
                        )
                    )
                connection.execute(
                    """INSERT INTO position_snapshots(
                        account_id, environment, symbol, quantity, mark_price,
                        entry_price, unrealized_pnl, leverage, position_side, observed_at
                    ) SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    WHERE NOT EXISTS (
                        SELECT 1 FROM position_snapshots
                        WHERE account_id=? AND environment=? AND symbol=?
                          AND quantity=? AND mark_price=? AND observed_at=?
                    )""",
                    (
                        account_id,
                        self.environment,
                        symbol,
                        values["quantity"],
                        values["mark_price"],
                        values.get("entry_price"),
                        values.get("unrealized_pnl", 0),
                        values.get("leverage"),
                        values.get("position_side"),
                        observed_at_text,
                        account_id,
                        self.environment,
                        symbol,
                        values["quantity"],
                        values["mark_price"],
                        observed_at_text,
                    ),
                )
            equity = float(snapshot.equity or self._snapshot_equity(snapshot))
            connection.execute(
                """INSERT INTO account_snapshots(
                    account_id, environment, equity, realized_pnl,
                    unrealized_pnl, peak_equity, observed_at
                ) SELECT ?, ?, ?, ?, ?, ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM account_snapshots
                    WHERE account_id=? AND environment=? AND equity=?
                      AND realized_pnl=? AND unrealized_pnl=? AND observed_at=?
                )""",
                (
                    account_id,
                    self.environment,
                    equity,
                    float(snapshot.realized_pnl or 0),
                    float(snapshot.unrealized_pnl or 0),
                    float(snapshot.peak_equity or equity),
                    observed_at_text,
                    account_id,
                    self.environment,
                    equity,
                    float(snapshot.realized_pnl or 0),
                    float(snapshot.unrealized_pnl or 0),
                    observed_at_text,
                ),
            )
            self._audit(
                connection,
                "reconciliation_completed",
                {
                    "account_id": account_id,
                    "source": "okx",
                    "observed_at": observed_at_text,
                    "imported_fill_ids": imported_fill_ids,
                    "diffs": diffs,
                },
            )
        return {"account_id": account_id, "difference_ids": diffs, "passed": not diffs}

    def _record_diff(
        self,
        connection: sqlite3.Connection,
        account_id: str,
        kind: str,
        key: str,
        local: dict[str, Any],
        external: dict[str, Any],
    ) -> str:
        diff_id = f"diff-{uuid.uuid4().hex}"
        connection.execute(
            "INSERT INTO reconciliation_diffs VALUES (?, ?, ?, ?, ?, ?, 'open', NULL, NULL, ?, NULL)",
            (
                diff_id,
                account_id,
                kind,
                key,
                redact_secrets(canonical_json(local)),
                redact_secrets(canonical_json(external)),
                datetime.now(UTC).isoformat(),
            ),
        )
        return diff_id

    def resolve_diff(self, diff_id: str, owner: str, resolution: str) -> dict[str, str]:
        with connect(self.database_path) as connection:
            cursor = connection.execute(
                """UPDATE reconciliation_diffs SET status='resolved', owner=?, resolution=?, resolved_at=?
                WHERE diff_id=? AND status='open'""",
                (owner, resolution, datetime.now(UTC).isoformat(), diff_id),
            )
            if cursor.rowcount != 1:
                raise LookupError("open reconciliation difference not found")
            self._audit(
                connection,
                "reconciliation_difference_resolved",
                {"diff_id": diff_id, "owner": owner, "resolution": resolution},
            )
        return {"diff_id": diff_id, "status": "resolved", "owner": owner}

    def deterministic_replay(
        self, strategy_id: str, version: str, bars: list[dict[str, Any]]
    ) -> dict[str, Any]:
        package = self._package(strategy_id, version)
        ordered = sorted(bars, key=lambda item: item["event_time"])
        if ordered != bars:
            raise ValueError("replay bars must be ordered")
        signals = []
        lookback = int(package.parameters.get("lookback", 1))
        closes = [float(bar["close"]) for bar in bars]
        for index in range(lookback, len(closes)):
            change = closes[index] / closes[index - lookback] - 1
            signals.append(
                {"event_time": bars[index]["event_time"], "target": 1 if change > 0 else -1}
            )
        return {
            "strategy_id": strategy_id,
            "version": version,
            "bar_hash": content_hash(bars),
            "signal_hash": content_hash(signals),
            "signals": signals,
        }

    def run_shadow_session(
        self,
        strategy_id: str,
        version: str,
        bars: Iterable[dict[str, Any]],
        *,
        feed_mode: str,
    ) -> dict[str, Any]:
        if self.environment != "shadow":
            raise ValueError("shadow sessions require the shadow environment")
        package = self._package(strategy_id, version)
        started_at = datetime.now(UTC)
        parsed = []
        raw_bars = []
        previous_observed_at: datetime | None = None
        for bar in bars:
            raw_bars.append(bar)
            event_time = datetime.fromisoformat(str(bar["event_time"]))
            observed_at = datetime.fromisoformat(str(bar["observed_at"]))
            if event_time.tzinfo is None or observed_at.tzinfo is None:
                raise ValueError("shadow timestamps must be timezone-aware")
            if observed_at < event_time:
                raise ValueError("shadow observation cannot precede event time")
            if previous_observed_at is not None and observed_at < previous_observed_at:
                raise ValueError("shadow bars must be ordered by observed_at")
            parsed.append((event_time, observed_at, float(bar["close"])))
            previous_observed_at = observed_at

        if not parsed:
            raise ValueError("shadow session requires at least one bar")

        lookback = int(package.parameters.get("lookback", 1))
        if lookback < 1 or len(parsed) <= lookback:
            raise ValueError("shadow session does not cover the strategy lookback")
        cost_bps = sum(float(value) for value in package.cost_assumptions.values())
        target_limit = package.risk_limits.max_symbol_exposure
        observations = []
        previous_target = 0.0
        for index in range(lookback, len(parsed)):
            event_time, observed_at, close = parsed[index]
            change = close / parsed[index - lookback][2] - 1
            direction = 1 if change > 0 else -1 if change < 0 else 0
            target = direction * target_limit
            delta = target - previous_target
            side = "buy" if delta > 0 else "sell" if delta < 0 else "hold"
            impact = cost_bps / 10_000
            estimated_price = close * (
                1 + impact if side == "buy" else 1 - impact if side == "sell" else 1
            )
            observations.append(
                {
                    "event_time": event_time.isoformat(),
                    "observed_at": observed_at.isoformat(),
                    "latency_seconds": (observed_at - event_time).total_seconds(),
                    "signal": direction,
                    "target_position": target,
                    "theoretical_fill": {
                        "side": side,
                        "position_delta": delta,
                        "reference_price": close,
                        "estimated_price": estimated_price,
                        "cost_bps": cost_bps,
                    },
                }
            )
            previous_target = target

        completed_at = datetime.now(UTC)
        result = {
            "session_type": "shadow",
            "feed_mode": feed_mode,
            "strategy_id": strategy_id,
            "version": version,
            "bar_hash": content_hash(raw_bars),
            "observations": observations,
            "risk_limit": target_limit,
            "external_orders_created": 0,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "elapsed_seconds": (completed_at - started_at).total_seconds(),
        }
        return self.record_runtime_result(strategy_id, version, result)

    def record_runtime_result(
        self, strategy_id: str, version: str, result: dict[str, Any]
    ) -> dict[str, Any]:
        run_id = f"runner-result-{uuid.uuid4().hex}"
        digest = content_hash(result)
        with connect(self.database_path) as connection:
            connection.execute(
                "INSERT INTO runtime_results VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    strategy_id,
                    version,
                    self.environment,
                    canonical_json(result),
                    digest,
                    datetime.now(UTC).isoformat(),
                ),
            )
        return {
            "run_id": run_id,
            "strategy_id": strategy_id,
            "strategy_version": version,
            "environment": self.environment,
            "result": result,
            "result_hash": digest,
        }
