from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apps.api import store
from apps.api.domains.instrument import service as instrument_service
from apps.api.domains.ledger import repository as ledger_repository
from apps.api.domains.ledger.domain import Trade
from apps.api.domains.portfolio import service as portfolio_service
from core.config import get_config
from core.cost_profiles import select_reference_profile
from core.research_decision import decision_from_mapping
from core.trading_costs import TradingCostProfile

from .risk import PaperOrderIntent, evaluate_risk
from .schemas import SimulationFillCreate, SimulationOrderCreate, SimulationOrderPreviewRequest

logger = logging.getLogger(__name__)

_FACTOR_FACTORY_ACCOUNT_PREFIX = "factor-factory:"
_HISTORICAL_CLOSED_BAR_EXCEPTION = {
    "kind": "factor_factory_isolated_closed_bar",
    "scope": "isolated",
    "authorized_by": "simulation_service",
    "realtime_executable": False,
}


class SimulationRiskRejected(ValueError):
    def __init__(self, decision: dict[str, Any]) -> None:
        super().__init__("模拟订单未通过服务端风控")
        self.decision = decision


# 历史 Demo 记录目录。新运行禁止写入此目录。
DEMO_RUNS_DIR = Path("data/demo_runs")


def list_demo_runs(limit: int = 20) -> list[dict[str, Any]]:
    """列出最近的 demo 运行记录摘要（按创建时间倒序）。"""
    if not DEMO_RUNS_DIR.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(
        DEMO_RUNS_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True
    )[:limit]:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("跳过损坏的 demo 运行记录 %s: %s", path.name, exc)
            continue
        config = record.get("config", {})
        summary = record.get("summary", {})
        provenance = record.get("data_provenance", {})
        rows.append(
            {
                "run_id": record.get("run_id", path.stem),
                "created_at": record.get("created_at"),
                "source": config.get("source", "synthetic"),
                "symbol": config.get("symbol"),
                "interval": config.get("interval"),
                "strategy": config.get("strategy"),
                "factor": config.get("factor"),
                "total_return": summary.get("total_return"),
                "max_drawdown": summary.get("max_drawdown"),
                "sharpe": (summary.get("metrics") or {}).get("sharpe"),
                "n_trades": summary.get("n_trades"),
                "fingerprint": provenance.get("fingerprint"),
            }
        )
    return rows


def get_demo_run(run_id: str) -> dict[str, Any] | None:
    """按 run_id 回读完整运行记录，供复现与审查。"""
    if not run_id.isalnum():
        return None
    path = DEMO_RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取 demo 运行记录失败 %s: %s", run_id, exc)
        return None


def _resolve_order_context(
    req: SimulationOrderCreate | SimulationOrderPreviewRequest,
    *,
    trusted_market_snapshot: dict[str, Any] | None = None,
) -> dict:
    signal = store.get_signal(req.signal_id) if req.signal_id else None
    if req.signal_id and signal is None:
        raise KeyError(req.signal_id)
    if signal and signal["direction"] not in {"buy", "sell"}:
        raise ValueError("观望信号不能转为模拟订单")
    symbol = signal["symbol"] if signal else req.symbol
    market = signal["market"] if signal else req.market
    side = signal["direction"] if signal else req.side
    assert symbol is not None and side is not None
    research_run_id = req.research_run_id
    if not research_run_id and signal:
        research_run_id = (signal.get("meta") or {}).get("research_run_id")
    # The factor-factory paper account replays a historical, already-closed bar.
    # Its trusted snapshot is an explicit internal contract, so it may resolve a
    # canonical crypto identity without consulting the live OKX catalogue.  This
    # exception is deliberately checked before the normal resolver and is kept
    # narrower than the ordinary order path: account prefix + snapshot provenance
    # + closed-bar quality + canonical USDT swap symbol are all required.
    historical_snapshot = (
        _historical_factor_factory_snapshot(req.account_id, trusted_market_snapshot)
        if trusted_market_snapshot is not None
        else None
    )
    instrument = None
    if historical_snapshot is not None and market == "crypto":
        canonical = instrument_service.normalize_crypto_swap_code(symbol)
        if canonical:
            instrument = instrument_service.build_instrument(canonical, "crypto")
            instrument_service.repository.upsert(instrument)
    if instrument is None:
        instrument = instrument_service.resolve_strict(symbol, market)
    return {
        "signal": signal,
        "instrument": instrument,
        "side": side,
        "research_run_id": research_run_id,
    }


def _market_snapshot(symbol: str, market: str) -> dict[str, Any]:
    """Fetch a provenance-preserving market snapshot for fail-closed risk checks."""
    snapshot = portfolio_service.latest_close_snapshot(symbol, market)
    return dict(snapshot)


def _is_factor_factory_account(account_id: str) -> bool:
    suffix = account_id.removeprefix(_FACTOR_FACTORY_ACCOUNT_PREFIX)
    return (
        account_id.startswith(_FACTOR_FACTORY_ACCOUNT_PREFIX)
        and bool(suffix)
        and all(char.isalnum() or char in {"-", "_", "."} for char in suffix)
    )


def _utc_iso(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _historical_factor_factory_snapshot(
    account_id: str, snapshot: dict[str, Any]
) -> dict[str, Any] | None:
    """Validate the sole trusted historical-price path before risk evaluation.

    ``trusted_market_snapshot`` is intentionally absent from HTTP schemas. Even
    internal callers cannot use it as a general price override: only the
    factor-factory isolated closed-bar replay has a narrow, audited exception.
    """
    source = str(snapshot.get("source") or "").strip().lower()
    quality = str(snapshot.get("quality_status") or "").strip().lower()
    event_at = _utc_iso(snapshot.get("event_time"))
    if not (
        _is_factor_factory_account(account_id)
        and source == "factor_factory.closed_bar"
        and quality == "closed_bar"
        and event_at is not None
    ):
        return None
    return {
        "price": snapshot.get("price"),
        "source": "factor_factory.closed_bar",
        "primary_source": None,
        "source_role": "historical_simulation",
        "cache_status": "not_applicable",
        "transport": "historical",
        "data_semantics": "bar_snapshot",
        "bar_at": event_at,
        "observed_at": event_at,
        "quality_status": "closed_bar",
        "snapshot_kind": "historical_closed_bar",
        "execution_exception": dict(_HISTORICAL_CLOSED_BAR_EXCEPTION),
        "error": None,
    }


def _market_snapshot_for_evaluation(
    *,
    symbol: str,
    market: str,
    account_id: str,
    trusted_market_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    if trusted_market_snapshot is None:
        return _market_snapshot(symbol, market)
    historical = _historical_factor_factory_snapshot(account_id, trusted_market_snapshot)
    if historical is not None:
        return historical
    return {
        "price": None,
        "source": "untrusted_server_snapshot",
        "primary_source": None,
        "source_role": "untrusted",
        "cache_status": "unknown",
        "transport": "unknown",
        "data_semantics": None,
        "bar_at": None,
        "observed_at": None,
        "quality_status": "unavailable",
        "error": "仅 factor-factory 隔离历史闭合 bar 可使用 trusted_market_snapshot",
    }


def _cost_snapshot(
    market: str,
    *,
    account_id: str,
    profile_id: str | None,
    version: str | None,
) -> dict[str, Any]:
    stored = store.get_trading_cost_profile(profile_id, version) if profile_id else None
    if stored:
        profile = TradingCostProfile.model_validate(stored)
    else:
        profile = select_reference_profile(
            market,
            profile_id=profile_id,
            version=version,
            account_scope=account_id,
        )
    snapshot = profile.immutable_snapshot()
    store.save_trading_cost_profile(snapshot)
    return snapshot


def _research_decision(run_id: str | None) -> dict[str, Any] | None:
    if not run_id:
        return None
    run = store.get_research_run(run_id)
    if run is None:
        return None
    decision = decision_from_mapping((run.get("summary") or {}).get("research_decision"))
    return decision.model_dump(mode="json") if decision else None


def _evaluate_order(
    req: SimulationOrderCreate | SimulationOrderPreviewRequest,
    *,
    intent_id: str,
    trusted_market_snapshot: dict[str, Any] | None = None,
    trusted_research_decision: dict[str, Any] | None = None,
    trusted_limits: dict[str, float] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], PaperOrderIntent]:
    context = _resolve_order_context(req, trusted_market_snapshot=trusted_market_snapshot)
    instrument = context["instrument"]
    intent = PaperOrderIntent(
        intent_id=intent_id,
        account_id=req.account_id,
        symbol=instrument.code,
        market=instrument.market,
        side=context["side"],
        order_type=req.order_type,
        quantity=req.quantity,
        limit_price=req.limit_price,
        signal_id=req.signal_id,
        research_run_id=context["research_run_id"],
        reduce_only=req.reduce_only,
    )
    account = account_snapshot(account_id=req.account_id)
    open_orders = [
        item
        for item in store.list_simulation_orders(account_id=req.account_id, limit=10_000)
        if item["status"] in {"pending", "partially_filled"}
    ]
    risk_config = get_config(instrument.market).get("risk", {})
    decision = evaluate_risk(
        intent,
        market_snapshot=_market_snapshot_for_evaluation(
            symbol=instrument.code,
            market=instrument.market,
            account_id=intent.account_id,
            trusted_market_snapshot=trusted_market_snapshot,
        ),
        account_snapshot=account,
        open_orders=open_orders,
        cost_profile=_cost_snapshot(
            instrument.market,
            account_id=req.account_id,
            profile_id=req.cost_profile_id,
            version=req.cost_profile_version,
        ),
        research_decision=(
            trusted_research_decision
            if trusted_research_decision is not None
            else _research_decision(context["research_run_id"])
        ),
        limits=(
            trusted_limits
            if trusted_limits is not None
            else {
                "max_position_per_symbol": float(risk_config.get("max_position_per_symbol", 0.15)),
                "max_total_exposure": float(risk_config.get("max_total_exposure", 0.8)),
            }
        ),
    )
    return context, decision, intent


def preview_order(req: SimulationOrderPreviewRequest) -> dict:
    """Evaluate the same server-side risk path as create, without writing an order."""
    context, decision, intent = _evaluate_order(req, intent_id=f"preview:{uuid.uuid4().hex}")
    calculation = decision["calculation"]
    return {
        "symbol": intent.symbol,
        "market": intent.market,
        "side": intent.side,
        "quantity": intent.quantity,
        "research_run_id": context["research_run_id"],
        "price": calculation["execution_price"],
        "order_notional": calculation["order_notional"],
        "current_quantity": calculation["current_quantity"],
        "projected_quantity": calculation["projected_quantity"],
        "gross_exposure_before": calculation["gross_exposure_before"],
        "gross_exposure_after": calculation["gross_exposure_after"],
        "cash_before": calculation["cash_before"],
        "cash_after": calculation["cash_after"],
        "equity": decision["snapshot"]["account"].get("equity"),
        **decision,
    }


def create_order(
    req: SimulationOrderCreate,
    *,
    trusted_market_snapshot: dict[str, Any] | None = None,
    trusted_research_decision: dict[str, Any] | None = None,
    trusted_limits: dict[str, float] | None = None,
) -> dict:
    intent_id = req.intent_id or (f"signal:{req.signal_id}" if req.signal_id else uuid.uuid4().hex)
    existing = store.get_simulation_order_by_intent(intent_id)
    if existing is not None:
        return {**existing, "idempotent_replay": True}
    context, decision, intent = _evaluate_order(
        req,
        intent_id=intent_id,
        trusted_market_snapshot=trusted_market_snapshot,
        trusted_research_decision=trusted_research_decision,
        trusted_limits=trusted_limits,
    )
    risk_record = store.add_simulation_risk_decision(
        intent_id=intent_id,
        order_id=None,
        account_id=intent.account_id,
        symbol=intent.symbol,
        market=intent.market,
        outcome=decision["outcome"],
        reason_codes=decision["reason_codes"],
        snapshot=decision["snapshot"],
        decision=decision,
        input_fingerprint=decision["input_fingerprint"],
        rule_version=decision["rule_version"],
    )
    if not decision["can_submit"]:
        raise SimulationRiskRejected({**decision, "risk_decision_id": risk_record["id"]})
    instrument = context["instrument"]
    now_iso = datetime.now(UTC).isoformat()
    theoretical_price = req.theoretical_price
    if theoretical_price is None:
        theoretical_price = decision["calculation"]["execution_price"]
    signal_time = req.signal_time.isoformat() if req.signal_time else None
    signal = context["signal"]
    if signal_time is None and signal is not None:
        signal_time = signal.get("ts")
    order = store.create_simulation_order(
        intent_id=intent_id,
        signal_id=req.signal_id,
        symbol=instrument.code,
        market=instrument.market,
        side=intent.side,
        order_type=req.order_type,
        quantity=req.quantity,
        limit_price=req.limit_price,
        account_id=req.account_id,
        instrument_id=instrument.instrument_id,
        audit={
            "factor_key": req.factor_key,
            "factor_version": req.factor_version,
            "strategy_id": req.strategy_id,
            "strategy_version": req.strategy_version,
            "research_run_id": context["research_run_id"],
            "market_regime_id": req.market_regime_id,
            "rebalance_cycle_id": req.rebalance_cycle_id,
            "signal_time": signal_time or now_iso,
            "tradable_time": req.tradable_time.isoformat() if req.tradable_time else now_iso,
            "theoretical_price": theoretical_price,
            "capacity_used": req.capacity_used,
            "rejection_reason": None,
            "risk_decision_id": risk_record["id"],
            "risk_decision": decision,
            "market_execution_class": decision["market_execution_class"],
            "historical_simulation_exception": decision["snapshot"]["market"].get(
                "execution_exception"
            ),
            "cost_profile": decision["snapshot"]["cost_profile"],
            "reduce_only": req.reduce_only,
        },
    )
    store.update_simulation_risk_order(risk_record["id"], order["id"])
    return {**order, "idempotent_replay": False}


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
    if order["audit"].get("market_execution_class") == "historical_closed_bar_simulation":
        raise ValueError("历史闭合 bar 模拟订单不得同步共享账本")
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
            strategy_id=order["audit"].get("strategy_id"),
            strategy_version=order["audit"].get("strategy_version"),
            factor_key=order["audit"].get("factor_key"),
            factor_version=order["audit"].get("factor_version"),
            research_run_id=order["audit"].get("research_run_id"),
            signal_id=order.get("signal_id"),
            simulation_order_id=order_id,
            execution_id=execution_id,
            market_regime_id=order["audit"].get("market_regime_id"),
            attribution_status=(
                "attributed"
                if any(
                    (
                        order["audit"].get("strategy_id"),
                        order["audit"].get("factor_key"),
                        order["audit"].get("research_run_id"),
                        order.get("signal_id"),
                    )
                )
                else "unknown_attribution"
            ),
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
    if current["audit"].get("market_execution_class") == "historical_closed_bar_simulation":
        raise ValueError("历史闭合 bar 模拟订单只能通过隔离成交路径处理")
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


def fill_isolated_order(order_id: str, req: SimulationFillCreate) -> dict:
    """成交独立模拟账户订单，不写入共享手工模拟账本。"""
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
    store.update_simulation_execution_ledger_sync(
        execution["id"],
        status="isolated",
        ledger_trade_id=None,
        error=None,
    )
    refreshed = store.get_simulation_order(order_id)
    if refreshed is None:
        raise KeyError(order_id)
    return refreshed


def account_snapshot(
    starting_cash: float = 1_000_000.0,
    *,
    account_id: str | None = None,
) -> dict:
    orders = store.list_simulation_orders(account_id=account_id, limit=10_000)
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
        "observed_at": datetime.now(UTC).isoformat(),
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
