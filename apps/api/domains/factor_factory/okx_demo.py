from __future__ import annotations

import math
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from apps.api.domains.trading.schemas import OrderIntentRequest
from apps.api.domains.trading.service import TradingService, get_service
from packages.research_protocol import canonical_json
from packages.strategy_package import (
    RiskLimits,
    StrategyReleasePackage,
    StrategyReleasePayload,
    create_release_package,
    signing_key_from_env,
)

from .schemas import FactorFactoryStartRequest


def _data(response: dict[str, Any]) -> Any:
    if response.get("status") == "error":
        raise RuntimeError(str(response.get("detail") or response.get("message") or "Runner 错误"))
    return response.get("data")


def build_demo_release_package(
    *,
    run_id: str,
    research_plan_id: str,
    experiment_id: str,
    definition: dict[str, Any],
    confirmation_summary: dict[str, Any],
    data_fingerprint: str,
    req: FactorFactoryStartRequest,
) -> StrategyReleasePackage:
    formula = canonical_json(definition["ast"])
    metrics = dict(confirmation_summary.get("metrics") or {})
    payload = StrategyReleasePayload(
        strategy_id=f"factor-factory-{run_id[:20]}",
        version=str(definition["version"]),
        target_market="okx",
        product_type="usdt_perpetual",
        runner_compatibility="1.0.0",
        formula=formula,
        formula_hash=sha256(formula.encode("utf-8")).hexdigest(),
        parameters={
            "factor_key": definition["key"],
            "factor_version": definition["version"],
            "factor_ast": definition["ast"],
            "position_mapping": "long_only_tanh_capped",
            "maximum_demo_exposure": req.maximum_demo_exposure,
            "horizon": req.horizon,
        },
        universe={"symbols": [req.symbol]},
        signal_frequency=req.interval,
        rebalance_frequency=req.interval,
        data_fields=("open", "high", "low", "close", "volume"),
        data_delay_seconds=0,
        data_snapshot_id=data_fingerprint,
        research_engine_version="factor-factory-v1",
        out_of_sample_results={
            "total_return": float(confirmation_summary.get("total_return") or 0.0),
            "max_drawdown": float(confirmation_summary.get("max_drawdown") or 0.0),
            "sharpe": float(metrics.get("sharpe") or 0.0),
            "rank_ic": float(confirmation_summary.get("rank_ic") or 0.0),
        },
        cost_assumptions={
            "commission_bps": req.commission_bps,
            "marketable_limit_slippage_bps": 5.0,
        },
        risk_limits=RiskLimits(
            max_leverage=1.0,
            max_symbol_exposure=req.maximum_demo_exposure,
            max_total_exposure=req.maximum_demo_exposure,
            max_loss=req.maximum_demo_loss,
            max_drawdown=req.thresholds.maximum_paper_drawdown,
            kill_switch_required=True,
        ),
        simulation_results={
            "status": "pending_forward_demo",
            "factor_factory_run_id": run_id,
            "live_trading_enabled": False,
        },
        allowed_environments=("demo",),
        approved_by="factor-factory-locked-gate",
        approved_at=datetime.now(UTC),
        audit_record_ids=(research_plan_id, experiment_id),
    )
    return create_release_package(payload, signing_key_from_env())


def _readiness(
    preflight: dict[str, Any], dashboard: dict[str, Any], symbol: str
) -> tuple[dict[str, Any], dict[str, Any] | None, float | None]:
    instrument = next(
        (item for item in preflight.get("instruments", []) if item.get("symbol") == symbol),
        None,
    )
    permissions = set(preflight.get("account", {}).get("permissions", []))
    risk_states = dashboard.get("risk_states", [])
    blocking_risk = [
        item
        for item in risk_states
        if item.get("scope") in {"global", "account:demo"} and item.get("mode") != "normal"
    ]
    open_diffs = [
        item
        for item in dashboard.get("reconciliation_diffs", [])
        if item.get("account_id") == "demo" and item.get("status") == "open"
    ]
    account = next(
        (
            item
            for item in dashboard.get("account_summary", {}).get("accounts", [])
            if item.get("account_id") == "demo"
        ),
        None,
    )
    checks = {
        "demo_environment": dashboard.get("account_status", {}).get("environment") == "demo",
        "trade_permission": "trade" in permissions,
        "clock_within_tolerance": preflight.get("clock", {}).get("within_tolerance") is True,
        "instrument_active": bool(instrument and instrument.get("active")),
        "risk_mode_normal": not blocking_risk,
        "reconciliation_clear": not open_diffs,
        "fresh_account_snapshot": bool(
            account and not dashboard.get("account_status", {}).get("stale", True)
        ),
    }
    return (
        {
            "passed": all(checks.values()),
            "checks": checks,
            "blocking_risk_states": blocking_risk,
            "open_reconciliation_diffs": open_diffs,
        },
        instrument,
        float(account["equity"]) if account and account.get("equity") is not None else None,
    )


def _round_quantity(value: float, step: float) -> float:
    return math.floor((value + 1e-12) / step) * step


def _marketable_limit(price: float, tick: float, side: str) -> float:
    shifted = price * (1.0005 if side == "buy" else 0.9995)
    units = math.ceil(shifted / tick) if side == "buy" else math.floor(shifted / tick)
    return round(units * tick, 12)


def activate_demo_strategy(
    *,
    package: StrategyReleasePackage,
    run_id: str,
    market_time: str,
    signal: float,
    price: float,
    previous_target_quantity: float = 0.0,
    trading: TradingService | None = None,
) -> dict[str, Any]:
    service = trading or get_service()
    strategy = package.payload
    imported = _data(service.import_demo_strategy(package.model_dump(mode="json")))
    symbol = strategy.universe["symbols"][0]
    preflight = _data(service.preflight([symbol]))
    _data(service.reconcile("demo"))
    dashboard = _data(service.dashboard())
    readiness, instrument, equity = _readiness(preflight, dashboard, symbol)
    base = {
        "status": "ready" if readiness["passed"] else "blocked",
        "environment": "demo",
        "strategy_id": strategy.strategy_id,
        "strategy_version": strategy.version,
        "content_hash": package.content_sha256,
        "package_import": imported,
        "readiness": readiness,
        "baseline_account_equity": equity,
        "live_trading_enabled": False,
    }
    if not readiness["passed"] or instrument is None or equity is None:
        return base

    target_ratio = min(max(float(signal), 0.0), strategy.risk_limits.max_symbol_exposure)
    step = float(instrument["quantity_step"])
    minimum = float(instrument["minimum_quantity"])
    contract_size = float(instrument.get("contract_size") or 1.0)
    unit_notional = max(price * contract_size, 1e-12)
    target_quantity = _round_quantity(equity * target_ratio / unit_notional, step)
    if 0 < target_quantity < minimum:
        target_quantity = (
            minimum
            if minimum * unit_notional <= equity * strategy.risk_limits.max_symbol_exposure
            else 0.0
        )
    delta = target_quantity - previous_target_quantity
    if abs(delta) < step / 2:
        return {
            **base,
            "status": "ready_no_order",
            "target_exposure": target_ratio,
            "target_quantity": target_quantity,
            "quantity_delta": 0.0,
            "order": None,
        }

    side = "buy" if delta > 0 else "sell"
    intent_hash = sha256(f"{run_id}:{market_time}:{side}".encode()).hexdigest()[:16]
    limit_price = _marketable_limit(price, float(instrument["price_tick"]), side)
    order = _data(
        service.submit_order(
            OrderIntentRequest(
                strategy_id=strategy.strategy_id,
                strategy_version=strategy.version,
                intent_id=f"ff-{run_id[:20]}-{intent_hash}",
                account_id="demo",
                symbol=symbol,
                side=side,
                order_type="limit",
                quantity=abs(delta),
                price=limit_price,
                leverage=1.0,
            )
        )
    )
    return {
        **base,
        "status": "submitted",
        "target_exposure": target_ratio,
        "target_quantity": target_quantity,
        "quantity_delta": delta,
        "reference_price": price,
        "limit_price": limit_price,
        "order": order,
    }


def refresh_demo_evidence(
    *,
    strategy_id: str,
    strategy_version: str,
    symbol: str,
    trading: TradingService | None = None,
) -> dict[str, Any]:
    service = trading or get_service()
    _data(service.recover_orders())
    reconciliation = _data(service.reconcile("demo"))
    dashboard = _data(service.dashboard())
    try:
        funding_rate = _data(service.funding_rate(symbol))
    except Exception as exc:  # noqa: BLE001 - 缺失本身必须成为门禁证据
        funding_rate = {
            "status": "unavailable",
            "error_type": type(exc).__name__,
        }
    orders = [
        item
        for item in dashboard.get("orders", [])
        if item.get("strategy_id") == strategy_id
        and item.get("strategy_version") == strategy_version
        and item.get("account_id") == "demo"
    ]
    order_ids = {str(item.get("order_id")) for item in orders}
    fills = [item for item in dashboard.get("fills", []) if str(item.get("order_id")) in order_ids]
    requested_quantity = sum(float(item.get("quantity") or 0.0) for item in orders)
    filled_quantity = sum(float(item.get("filled_quantity") or 0.0) for item in orders)
    account = next(
        (
            item
            for item in dashboard.get("account_summary", {}).get("accounts", [])
            if item.get("account_id") == "demo"
        ),
        None,
    )
    open_diffs = [
        item
        for item in dashboard.get("reconciliation_diffs", [])
        if item.get("account_id") == "demo" and item.get("status") == "open"
    ]
    blocking_risk = [
        item
        for item in dashboard.get("risk_states", [])
        if item.get("scope") in {"global", "account:demo"} and item.get("mode") != "normal"
    ]
    return {
        "environment": "demo",
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "symbol": symbol,
        "orders": orders,
        "fills": fills,
        "order_count": len(orders),
        "fill_count": len(fills),
        "fill_rate": filled_quantity / requested_quantity if requested_quantity else 0.0,
        "reconciliation": reconciliation,
        "reconciliation_clear": not open_diffs,
        "open_reconciliation_diffs": open_diffs,
        "risk_mode_normal": not blocking_risk,
        "blocking_risk_states": blocking_risk,
        "account": account,
        "funding_rate": funding_rate,
        "live_trading_enabled": False,
    }
