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
from core.backtest import dataset as dataset_module
from core.backtest import factors as factor_module
from core.backtest import market_data as market_data_module
from core.backtest import strategies_demo as demo_strategy_module
from core.config import get_config

from .schemas import (
    DemoRunRequest,
    SimulationFillCreate,
    SimulationOrderCreate,
    SimulationOrderPreviewRequest,
)

logger = logging.getLogger(__name__)

# 回测 demo 运行记录落地目录（与既有 data/ 体系一致，JSON 可复现、可审查）
DEMO_RUNS_DIR = Path("data/demo_runs")


def _periods_per_year(interval: str, source: str = "synthetic") -> int:
    """年化周期数。加密市场 7×24 连续交易按 365 天折算，合成数据沿用 A 股 252 日惯例。"""
    minutes = dataset_module.INTERVAL_MINUTES.get(interval, 1440)
    trading_days = 365 if source in {"okx_local", "okx_live"} else 252
    if minutes >= 1440:
        return trading_days
    return max(1, int(trading_days * (1440 / minutes)))


def demo_catalog() -> dict:
    """返回 demo 可用选项：数据源 / 标的 / 数据集 / 因子 / 策略 / 周期，供前端下拉与一键启动。"""
    return {
        "sources": market_data_module.list_sources(),
        "datasets": dataset_module.list_presets(),
        "factors": factor_module.list_factors(),
        "strategies": demo_strategy_module.list_strategies(),
        "intervals": list(dataset_module.INTERVAL_MINUTES.keys()),
        "defaults": {
            "source": "okx_local",
            "symbol": "BTCUSDT",
            "dataset": "uptrend",
            "seed": 12,
            "n_bars": 250,
            "interval": "1d",
            "start": None,
            "end": None,
            "use_cache": True,
            "initial_capital": 1_000_000.0,
            "commission": 0.0003,
            "position_fraction": 1.0,
            "strategy": "factor_follow",
            "factor": "momentum",
        },
    }


def _load_demo_frame(req: DemoRunRequest) -> tuple[Any, dict[str, Any], str]:
    """按数据源取数，返回 (DataFrame, 数据溯源信息, 一行摘要)。"""
    if req.source == "synthetic":
        start = req.start or "2024-01-01"
        df = dataset_module.generate_dataset(
            preset=req.dataset,
            seed=req.seed,
            n_bars=req.n_bars,
            interval=req.interval,
            start=start,
        )
        provenance = {
            "source": "synthetic",
            "channel": "确定性合成行情（无真实市场数据）",
            "dataset": req.dataset,
            "seed": req.seed,
            "interval": req.interval,
            "start": start,
            "bars": int(len(df)),
            "fingerprint": market_data_module.fingerprint_frame(df),
            "offline": True,
            "reproducible": "相同 (数据集, seed, 周期, 起点, 根数) 必得相同结果",
        }
        summary = (
            f"合成数据集 {req.dataset}（seed={req.seed}, {req.interval}, "
            f"start={start}）→ {len(df)} 根 K 线"
        )
        return df, provenance, summary

    snapshot = market_data_module.load_market_data(
        req.source,
        symbol=req.symbol,
        interval=req.interval,
        n_bars=req.n_bars,
        start=req.start,
        end=req.end,
        use_cache=req.use_cache,
    )
    provenance = {
        "source": snapshot.source,
        "symbol": snapshot.symbol,
        "interval": snapshot.interval,
        "fingerprint": snapshot.fingerprint,
        **snapshot.provenance,
    }
    summary = (
        f"真实 OKX 行情 {snapshot.symbol} {snapshot.interval} → {len(snapshot.df)} 根 K 线"
        f"（{snapshot.provenance.get('selected_first')} ~ {snapshot.provenance.get('selected_last')}）"
    )
    return snapshot.df, provenance, summary


def run_demo(req: DemoRunRequest) -> dict:
    """编排一次可复现回测：数据 → (因子) → 策略 → 指标 + 运行日志，并持久化运行记录。"""
    run_log: list[dict[str, Any]] = []
    t0 = datetime.now(UTC)

    def log(step: str, message: str) -> None:
        run_log.append({"step": step, "message": message, "at": datetime.now(UTC).isoformat()})

    # 1) 数据（真实 OKX 归档 / 真实 OKX 实时 / 确定性合成）
    df, provenance, data_summary = _load_demo_frame(req)
    log("data", data_summary)
    log("data", f"数据指纹 sha256:{provenance['fingerprint'][:16]}… | {provenance['channel']}")
    if provenance.get("cache_file"):
        hit = "命中快照" if provenance.get("cache_hit") else "已写入快照"
        log("data", f"{hit}: {provenance['cache_file']}")

    # 2) 因子（仅因子策略需要）
    strategy_meta = next(
        (s for s in demo_strategy_module.list_strategies() if s["key"] == req.strategy), None
    )
    factor_used = req.factor
    if strategy_meta and strategy_meta["uses_factor"] and not factor_used:
        factor_used = "momentum"
        log("factor", "因子策略未指定因子，回退到 momentum")
    if req.factor_ast:
        log(
            "factor",
            f"安全 DSL 因子 {req.factor_label or factor_used or '未命名'}"
            f"@{req.factor_version or '未登记版本'} 已编译为信号序列",
        )
    elif factor_used:
        log("factor", f"因子 {factor_used} 已编译为信号序列")
    else:
        log("factor", "策略使用自带信号（忽略因子选择）")

    # 3) 回测
    periods_per_year = _periods_per_year(req.interval, req.source)
    result = demo_strategy_module.run_strategy(
        name=req.strategy,
        df=df,
        factor_name=factor_used,
        factor_params=req.factor_params,
        factor_ast=req.factor_ast,
        initial_capital=req.initial_capital,
        commission=req.commission,
        position_fraction=req.position_fraction,
        periods_per_year=periods_per_year,
    )
    m = result["metrics"]
    log(
        "backtest",
        f"策略 {req.strategy} 回测完成：{result['n_trades']} 笔成交，期末权益 {result['final_equity']:,.0f}",
    )
    log(
        "kpi",
        f"收益 {result['total_return'] * 100:+.2f}% | 回撤 {result['max_drawdown'] * 100:+.2f}% | "
        f"夏普 {m.get('sharpe', 0):.2f} | 交易胜率 {m.get('trade_win_rate', 0) * 100:.1f}%",
    )

    run_id = uuid.uuid4().hex[:12]
    config = {
        "source": req.source,
        "symbol": req.symbol,
        "dataset": req.dataset,
        "seed": req.seed,
        "n_bars": req.n_bars,
        "interval": req.interval,
        "start": req.start,
        "end": req.end,
        "use_cache": req.use_cache,
        "initial_capital": req.initial_capital,
        "commission": req.commission,
        "position_fraction": req.position_fraction,
        "strategy": req.strategy,
        "factor": factor_used,
        "factor_params": req.factor_params,
        "factor_ast": req.factor_ast,
        "factor_label": req.factor_label,
        "factor_version": req.factor_version,
        "periods_per_year": periods_per_year,
    }
    record = {
        "run_id": run_id,
        "created_at": t0.isoformat(),
        "config": config,
        "data_provenance": provenance,
        "summary": {
            "final_equity": result["final_equity"],
            "total_return": result["total_return"],
            "max_drawdown": result["max_drawdown"],
            "engine": result["engine"],
            "n_trades": result["n_trades"],
            "metrics": m,
        },
        "equity_curve": result["equity_curve"],
        "trades": result["trades"],
        "run_log": run_log,
    }
    try:
        DEMO_RUNS_DIR.mkdir(parents=True, exist_ok=True)
        (DEMO_RUNS_DIR / f"{run_id}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        persisted = True
        log("persist", f"运行记录已保存: data/demo_runs/{run_id}.json")
    except Exception as exc:  # noqa: BLE001 - 持久化失败不应阻断回测结果返回
        persisted = False
        logger.warning("demo 运行记录持久化失败: %s", exc)
        log("persist", f"运行记录保存失败（不影响结果）: {exc}")

    return {
        "ok": True,
        "run_id": run_id,
        "config": config,
        "data_provenance": provenance,
        "summary": record["summary"],
        "equity_curve": result["equity_curve"],
        "trades": result["trades"],
        "run_log": run_log,
        "persisted": persisted,
    }


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
    now_iso = datetime.now(UTC).isoformat()
    theoretical_price = req.theoretical_price
    if theoretical_price is None:
        try:
            latest = portfolio_service.latest_close(instrument.code, instrument.market)
            theoretical_price = float(latest) if latest and latest > 0 else None
        except (LookupError, ValueError, TypeError):
            theoretical_price = None
    signal_time = req.signal_time.isoformat() if req.signal_time else None
    if signal_time is None and req.signal_id and signal is not None:
        signal_time = signal.get("ts")
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
        audit={
            "factor_key": req.factor_key,
            "factor_version": req.factor_version,
            "research_run_id": req.research_run_id,
            "rebalance_cycle_id": req.rebalance_cycle_id,
            "signal_time": signal_time or now_iso,
            "tradable_time": req.tradable_time.isoformat() if req.tradable_time else now_iso,
            "theoretical_price": theoretical_price,
            "capacity_used": req.capacity_used,
            "rejection_reason": None,
        },
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
