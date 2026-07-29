from __future__ import annotations

import logging
from typing import Any

from apps.api import store
from apps.api.domains.instrument import service as instrument_service
from apps.api.domains.ledger import repository as ledger_repository
from apps.api.domains.ledger.domain import Trade
from apps.api.domains.portfolio import service as portfolio_service
from core.config import get_config

from .schemas import SimulationFillCreate, SimulationOrderCreate, SimulationOrderPreviewRequest

logger = logging.getLogger(__name__)


def _risk_check(
    key: str,
    label: str,
    actual: float,
    limit: float,
    *,
    unit: str = "ratio",
) -> dict[str, Any]:
    passed = actual <= limit
    return {
        "key": key,
        "label": label,
        "status": "passed" if passed else "failed",
        "actual": round(actual, 6),
        "limit": round(limit, 6),
        "unit": unit,
    }


def preview_order(req: SimulationOrderPreviewRequest) -> dict:
    """在创建模拟订单前计算账户影响，不写入订单或账本。"""
    signal = store.get_signal(req.signal_id)
    if signal is None:
        raise KeyError(req.signal_id)
    if signal["direction"] not in {"buy", "sell"}:
        raise ValueError("观望信号不能转为模拟订单")

    symbol = signal["symbol"]
    market = signal["market"]
    side = signal["direction"]
    account = account_snapshot()
    position = next(
        (
            item
            for item in account["positions"]
            if item["symbol"] == symbol and item["market"] == market
        ),
        None,
    )
    current_quantity = float(position["quantity"]) if position else 0.0
    signed_quantity = req.quantity if side == "buy" else -req.quantity
    projected_quantity = current_quantity + signed_quantity
    price = portfolio_service.latest_close(symbol, market)
    if price is not None and price <= 0:
        price = None

    risk = get_config(market).get("risk", {})
    max_symbol_weight = float(risk.get("max_position_per_symbol", 0.15))
    max_total_exposure = float(risk.get("max_total_exposure", 0.8))
    equity = float(account["equity"])
    cash = float(account["cash"])
    checks: list[dict[str, Any]] = []

    if price is None:
        checks.append(
            {
                "key": "price_available",
                "label": "行情价格",
                "status": "unavailable",
                "actual": None,
                "limit": None,
                "unit": "price",
            }
        )
        return {
            "symbol": symbol,
            "market": market,
            "side": side,
            "quantity": req.quantity,
            "price": None,
            "order_notional": None,
            "current_quantity": round(current_quantity, 8),
            "projected_quantity": round(projected_quantity, 8),
            "current_symbol_value": None,
            "projected_symbol_value": None,
            "gross_exposure_before": round(
                sum(abs(float(item["market_value"])) for item in account["positions"]), 2
            ),
            "gross_exposure_after": None,
            "cash_before": round(cash, 2),
            "cash_after": None,
            "equity": round(equity, 2),
            "risk_evaluated": False,
            "can_submit": True,
            "checks": checks,
        }

    order_notional = req.quantity * price
    current_symbol_value = current_quantity * price
    projected_symbol_value = projected_quantity * price
    existing_symbol_value = float(position["market_value"]) if position else 0.0
    recorded_gross = sum(abs(float(item["market_value"])) for item in account["positions"])
    gross_before = recorded_gross - abs(existing_symbol_value) + abs(current_symbol_value)
    gross_after = gross_before - abs(current_symbol_value) + abs(projected_symbol_value)
    cash_after = cash - order_notional if side == "buy" else cash + order_notional

    if equity <= 0:
        checks.append(
            {
                "key": "positive_equity",
                "label": "账户权益",
                "status": "failed",
                "actual": round(equity, 2),
                "limit": 0.0,
                "unit": "currency",
            }
        )
    else:
        checks.extend(
            [
                _risk_check(
                    "symbol_weight",
                    "单标的仓位",
                    abs(projected_symbol_value) / equity,
                    max_symbol_weight,
                ),
                _risk_check(
                    "gross_exposure",
                    "组合总敞口",
                    gross_after / equity,
                    max_total_exposure,
                ),
            ]
        )
    if side == "buy":
        checks.append(
            {
                "key": "available_cash",
                "label": "可用现金",
                "status": "passed" if cash_after >= 0 else "failed",
                "actual": round(cash, 2),
                "limit": round(order_notional, 2),
                "unit": "currency",
            }
        )

    return {
        "symbol": symbol,
        "market": market,
        "side": side,
        "quantity": req.quantity,
        "price": round(price, 8),
        "order_notional": round(order_notional, 2),
        "current_quantity": round(current_quantity, 8),
        "projected_quantity": round(projected_quantity, 8),
        "current_symbol_value": round(current_symbol_value, 2),
        "projected_symbol_value": round(projected_symbol_value, 2),
        "gross_exposure_before": round(gross_before, 2),
        "gross_exposure_after": round(gross_after, 2),
        "cash_before": round(cash, 2),
        "cash_after": round(cash_after, 2),
        "equity": round(equity, 2),
        "risk_evaluated": True,
        "can_submit": not any(item["status"] == "failed" for item in checks),
        "checks": checks,
    }


def create_order(req: SimulationOrderCreate) -> dict:
    symbol = req.symbol
    market = req.market
    side = req.side
    if req.signal_id:
        signal = store.get_signal(req.signal_id)
        if signal is None:
            raise KeyError(req.signal_id)
        symbol = signal["symbol"]
        market = signal["market"]
        if signal["direction"] not in {"buy", "sell"}:
            raise ValueError("观望信号不能转为模拟订单")
        side = signal["direction"]
    assert symbol is not None and side is not None
    instrument = instrument_service.resolve_strict(symbol, market)
    return store.create_simulation_order(
        signal_id=req.signal_id,
        symbol=instrument.code,
        market=instrument.market,
        side=side,
        order_type=req.order_type,
        quantity=req.quantity,
        limit_price=req.limit_price,
        account_id=req.account_id,
        instrument_id=instrument.instrument_id,
    )


def _find_execution(order: dict, execution_id: str) -> dict:
    for execution in order["executions"]:
        if execution["id"] == execution_id:
            return execution
    raise KeyError(execution_id)


def sync_execution_to_ledger(order_id: str, execution_id: str) -> dict:
    """将单笔模拟成交幂等写入账本，并返回刷新后的模拟订单。"""
    order = store.get_simulation_order(order_id)
    if order is None:
        raise KeyError(order_id)
    execution = _find_execution(order, execution_id)
    ledger_trade_id = f"simulation:{execution_id}"

    try:
        instrument = instrument_service.register(
            code=order["symbol"],
            market=order["market"],
        )
        trade = Trade(
            id=ledger_trade_id,
            instrument_id=instrument.instrument_id,
            code=instrument.code,
            market=instrument.market,
            direction=order["side"],
            quantity=execution["quantity"],
            price=execution["price"],
            fee=execution["fee"],
            ts=execution["executed_at"],
            source="simulation",
            note=(f"模拟账户 {order['account_id']} / 订单 {order_id} / 成交 {execution_id}"),
        )
        saved_trade = ledger_repository.save_trade_if_absent(trade)
        comparable_fields = (
            "instrument_id",
            "code",
            "market",
            "direction",
            "quantity",
            "price",
            "fee",
        )
        if any(getattr(saved_trade, field) != getattr(trade, field) for field in comparable_fields):
            raise ValueError(f"账本成交编号冲突: {ledger_trade_id}")
        store.update_simulation_execution_ledger_sync(
            execution_id,
            status="synced",
            ledger_trade_id=ledger_trade_id,
            error=None,
        )
    except Exception as exc:
        logger.exception("模拟成交同步账本失败 order=%s execution=%s", order_id, execution_id)
        store.update_simulation_execution_ledger_sync(
            execution_id,
            status="failed",
            ledger_trade_id=None,
            error=str(exc),
        )
    refreshed = store.get_simulation_order(order_id)
    if refreshed is None:
        raise KeyError(order_id)
    return refreshed


def fill_order(order_id: str, req: SimulationFillCreate) -> dict:
    current = store.get_simulation_order(order_id)
    if current is None:
        raise KeyError(order_id)
    quantity = req.quantity or (current["quantity"] - current["filled_quantity"])
    order = store.fill_simulation_order(
        order_id,
        quantity=quantity,
        price=req.price,
        fee_rate=req.fee_rate,
    )
    if order is None:
        raise KeyError(order_id)
    execution = order["executions"][-1]
    return sync_execution_to_ledger(order_id, execution["id"])


def account_snapshot(starting_cash: float = 1_000_000.0) -> dict:
    orders = store.list_simulation_orders(limit=10_000)
    events = sorted(
        (
            {
                **execution,
                "symbol": order["symbol"],
                "market": order["market"],
                "side": order["side"],
            }
            for order in orders
            for execution in order["executions"]
        ),
        key=lambda item: (item["executed_at"], item["id"]),
    )
    cash = starting_cash
    total_fees = 0.0
    realized_pnl = 0.0
    positions: dict[tuple[str, str], dict] = {}

    for event in events:
        key = (event["symbol"], event["market"])
        position = positions.setdefault(
            key,
            {
                "symbol": event["symbol"],
                "market": event["market"],
                "quantity": 0.0,
                "average_cost": 0.0,
                "mark_price": 0.0,
                "realized_pnl": 0.0,
            },
        )
        quantity = float(event["quantity"])
        price = float(event["price"])
        fee = float(event["fee"])
        old_quantity = float(position["quantity"])
        average_cost = float(position["average_cost"])
        total_fees += fee
        position["mark_price"] = price

        if event["side"] == "buy":
            cash -= quantity * price + fee
            if old_quantity >= 0:
                new_quantity = old_quantity + quantity
                position["average_cost"] = (
                    old_quantity * average_cost + quantity * price
                ) / new_quantity
            else:
                closed = min(quantity, -old_quantity)
                pnl = (average_cost - price) * closed
                position["realized_pnl"] += pnl
                realized_pnl += pnl
                new_quantity = old_quantity + quantity
                if new_quantity >= 0:
                    position["average_cost"] = price if new_quantity > 0 else 0.0
            position["quantity"] = new_quantity
        else:
            cash += quantity * price - fee
            if old_quantity <= 0:
                new_quantity = old_quantity - quantity
                short_size = -old_quantity
                position["average_cost"] = (
                    short_size * average_cost + quantity * price
                ) / -new_quantity
            else:
                closed = min(quantity, old_quantity)
                pnl = (price - average_cost) * closed
                position["realized_pnl"] += pnl
                realized_pnl += pnl
                new_quantity = old_quantity - quantity
                if new_quantity <= 0:
                    position["average_cost"] = price if new_quantity < 0 else 0.0
            position["quantity"] = new_quantity

    position_rows = []
    market_value = 0.0
    unrealized_pnl = 0.0
    for position in positions.values():
        if abs(position["quantity"]) <= 1e-9:
            continue
        value = position["quantity"] * position["mark_price"]
        unrealized = position["quantity"] * (position["mark_price"] - position["average_cost"])
        market_value += value
        unrealized_pnl += unrealized
        position_rows.append(
            {
                **position,
                "quantity": round(position["quantity"], 8),
                "average_cost": round(position["average_cost"], 8),
                "market_value": round(value, 2),
                "unrealized_pnl": round(unrealized, 2),
                "realized_pnl": round(position["realized_pnl"], 2),
            }
        )

    issues = []
    for order in orders:
        executed = sum(item["quantity"] for item in order["executions"])
        weighted_value = sum(item["quantity"] * item["price"] for item in order["executions"])
        average = weighted_value / executed if executed else None
        if abs(executed - order["filled_quantity"]) > 1e-8:
            issues.append({"order_id": order["id"], "field": "filled_quantity"})
        if average is not None and (
            order["average_price"] is None or abs(average - order["average_price"]) > 1e-8
        ):
            issues.append({"order_id": order["id"], "field": "average_price"})
        if order["status"] == "filled" and abs(executed - order["quantity"]) > 1e-8:
            issues.append({"order_id": order["id"], "field": "filled_status"})

    return {
        "ok": True,
        "mode": "paper",
        "starting_cash": starting_cash,
        "cash": round(cash, 2),
        "market_value": round(market_value, 2),
        "equity": round(cash + market_value, 2),
        "total_fees": round(total_fees, 2),
        "realized_pnl": round(realized_pnl, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "positions": sorted(position_rows, key=lambda item: (item["market"], item["symbol"])),
        "order_count": len(orders),
        "execution_count": len(events),
        "reconciled": not issues,
        "reconciliation_issues": issues,
    }
