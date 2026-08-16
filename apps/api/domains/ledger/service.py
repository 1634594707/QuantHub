"""组合账本服务：记录成交/现金流水，计算持仓与组合指标。"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from apps.api import store
from apps.api.domains.instrument import service as instrument_service
from apps.api.domains.portfolio.service import latest_close

from . import repository
from .domain import (
    Benchmark,
    CashEntry,
    Position,
    Trade,
    apply_trade,
    benchmark_excess,
    compute_positions,
    match_closed_trades,
    max_drawdown,
    portfolio_metrics,
    time_weighted_return,
    trade_analytics,
)
from .schemas import (
    BenchmarkCorrection,
    BenchmarkCreate,
    CashEntryCorrection,
    CashEntryCreate,
    TradeCorrection,
    TradeCreate,
)

logger = logging.getLogger(__name__)


def _attribution_fields(req) -> dict[str, Any]:
    values = {
        "strategy_id": req.strategy_id,
        "strategy_version": req.strategy_version,
        "factor_key": req.factor_key,
        "factor_version": req.factor_version,
        "research_run_id": req.research_run_id,
        "signal_id": req.signal_id,
        "simulation_order_id": req.simulation_order_id,
        "execution_id": req.execution_id,
        "market_regime_id": req.market_regime_id,
    }
    return {
        **values,
        "attribution_status": "attributed" if any(values.values()) else "unknown_attribution",
    }


def _ledger_latest_close(code: str, market: str) -> float | None:
    if os.environ.get("QUANTHUB_DISABLE_MARKET_FETCH") == "1":
        return None
    return latest_close(code, market)


def record_trade(req: TradeCreate) -> dict:
    """记录一笔成交，返回带现金影响的成交记录。"""
    instrument = instrument_service.resolve_strict(req.code, req.market)
    if instrument.instrument_id != req.instrument_id:
        raise ValueError("instrument_id 与 code/market 不一致")
    trade = Trade(
        id=str(uuid.uuid4()),
        instrument_id=req.instrument_id,
        code=req.code,
        market=req.market,
        direction=req.direction,
        quantity=req.quantity,
        price=req.price,
        fee=req.fee,
        ts=time.time(),
        source=req.source,
        note=req.note,
        **_attribution_fields(req),
    )
    repository.save_trade(trade)
    result = trade.to_dict()
    result["cash_flow"] = round(trade.cash_flow(), 2)
    return {"ok": True, "trade": result}


def list_trades(
    instrument_id: str | None = None, limit: int = 200, cursor: str | None = None
) -> dict:
    page = repository.list_trades_page(instrument_id=instrument_id, limit=limit, cursor=cursor)
    return {
        "count": len(page["items"]),
        "total": page["total"],
        "next_cursor": page["next_cursor"],
        "trades": [trade.to_dict() for trade in page["items"]],
    }


def correct_trade(trade_id: str, req: TradeCorrection) -> dict:
    current = repository.get_trade(trade_id)
    if current is None:
        return {"ok": False, "error": "成交记录不存在"}
    instrument = instrument_service.resolve_strict(req.code, req.market)
    if instrument.instrument_id != req.instrument_id:
        return {"ok": False, "error": "instrument_id 与 code/market 不一致"}
    trade = Trade(
        id=trade_id,
        instrument_id=req.instrument_id,
        code=req.code,
        market=req.market,
        direction=req.direction,
        quantity=req.quantity,
        price=req.price,
        fee=req.fee,
        ts=current.ts,
        source=req.source,
        note=req.note,
        **_attribution_fields(req),
    )
    correction = repository.correct_trade(trade, req.reason.strip())
    return {"ok": True, "trade": trade.to_dict(), "correction": correction}


def record_cash(req: CashEntryCreate) -> dict:
    entry = CashEntry(
        id=str(uuid.uuid4()),
        direction=req.direction,
        amount=req.amount,
        currency=req.currency,
        ts=time.time(),
        source=req.source,
        note=req.note,
    )
    repository.save_cash(entry)
    return {"ok": True, "entry": entry.to_dict()}


def list_cash(limit: int = 200, cursor: str | None = None) -> dict:
    page = repository.list_cash_page(limit=limit, cursor=cursor)
    return {
        "count": len(page["items"]),
        "total": page["total"],
        "next_cursor": page["next_cursor"],
        "entries": [entry.to_dict() for entry in page["items"]],
    }


def correct_cash(entry_id: str, req: CashEntryCorrection) -> dict:
    current = repository.get_cash(entry_id)
    if current is None:
        return {"ok": False, "error": "现金流水不存在"}
    entry = CashEntry(
        id=entry_id,
        direction=req.direction,
        amount=req.amount,
        currency=req.currency,
        ts=current.ts,
        source=req.source,
        note=req.note,
    )
    correction = repository.correct_cash(entry, req.reason.strip())
    return {"ok": True, "entry": entry.to_dict(), "correction": correction}


def compute_cash_balance() -> float:
    """从现金流水 + 成交现金流计算当前现金余额。"""
    cash_entries = repository.list_cash(limit=10_000)
    trades = repository.list_trades(limit=10_000)
    balance = sum(e.signed_amount() for e in cash_entries)
    balance += sum(t.cash_flow() for t in trades)
    return round(balance, 2)


def get_positions(*, refresh_prices: bool = True) -> dict:
    """从成交流水计算当前持仓；按需回填最新价。"""
    trades = repository.list_trades(limit=10_000)
    positions = compute_positions(trades)
    if refresh_prices:
        for pos in positions.values():
            if abs(pos.quantity) > 1e-9:
                try:
                    price = _ledger_latest_close(pos.code, pos.market)
                    if price:
                        pos.last_price = price
                except Exception:  # noqa: BLE001 - market adapters must not block ledger reads
                    logger.debug("回填最新价失败 %s", pos.code)
    items = [p.to_dict() for p in positions.values()]
    return {"count": len(items), "positions": items}


def get_position(instrument_id: str) -> dict:
    trades = repository.list_trades(instrument_id=instrument_id, limit=10_000)
    if not trades:
        return {"ok": False, "error": "该标的无成交记录"}
    positions = compute_positions(trades)
    pos = positions.get(instrument_id)
    if not pos:
        return {"ok": False, "error": "持仓计算失败"}
    if abs(pos.quantity) > 1e-9:
        try:
            price = _ledger_latest_close(pos.code, pos.market)
            if price:
                pos.last_price = price
        except Exception:  # noqa: BLE001 - market adapters must not block ledger reads
            logger.debug("回填最新价失败 %s", pos.code, exc_info=True)
    return {"ok": True, "position": pos.to_dict()}


def portfolio_summary() -> dict:
    """组合级指标：NAV、已实现/未实现盈亏、现金、持仓数。"""
    trades = repository.list_trades(limit=10_000)
    positions = compute_positions(trades)
    for pos in positions.values():
        if abs(pos.quantity) > 1e-9:
            try:
                price = _ledger_latest_close(pos.code, pos.market)
                if price:
                    pos.last_price = price
            except Exception:  # noqa: BLE001 - market adapters must not block ledger reads
                logger.debug("回填最新价失败 %s", pos.code, exc_info=True)
    cash = compute_cash_balance()
    metrics = portfolio_metrics(positions, cash)
    return {"ok": True, "summary": metrics}


def _build_equity_curve(
    trades: list[Trade], cash_entries: list[CashEntry], final_market_value: float
) -> list[dict[str, Any]]:
    """从成交 + 现金流水按时间顺序重建组合权益曲线。

    每个时点 NAV = 累计现金 + 累计已实现盈亏 + 持仓成本 + 累计未实现涨跌估算
    简化处理：以成交价作为该时点的 last_price 估算未实现盈亏。
    """
    # 合并时间轴
    events: list[tuple[float, str, Any]] = []
    for t in trades:
        events.append((t.ts, "trade", t))
    for e in cash_entries:
        events.append((e.ts, "cash", e))
    events.sort(key=lambda x: x[0])
    if not events:
        return []

    equity_curve: list[dict[str, Any]] = []
    cash_balance = 0.0
    positions: dict[str, Position] = {}
    # 按事件时点推进
    for ts, kind, item in events:
        if kind == "cash":
            cash_balance += item.signed_amount()
        else:
            cash_balance += item.cash_flow()
            pos = positions.get(item.instrument_id)
            if pos is None:
                pos = Position(
                    instrument_id=item.instrument_id,
                    code=item.code,
                    market=item.market,
                )
            positions[item.instrument_id] = apply_trade(pos, item)
        # 估算当前市值：用成交价作为 last_price
        market_value = sum(
            p.quantity * p.last_price for p in positions.values() if abs(p.quantity) > 1e-9
        )
        nav = cash_balance + market_value
        equity_curve.append({"t": ts, "equity": round(nav, 2)})
    # 最后一点用真实最新市值替换
    if equity_curve:
        last_ts = equity_curve[-1]["t"]
        equity_curve[-1] = {"t": last_ts, "equity": round(cash_balance + final_market_value, 2)}
    return equity_curve


def performance() -> dict:
    """组合绩效：TWR、最大回撤、基准超额。

    权益曲线由成交 + 现金流水按时间顺序重建；基准对比需先用 ``register_benchmark`` 落库。
    """
    trades = repository.list_trades(limit=10_000)
    cash_entries = repository.list_cash(limit=10_000)
    positions = compute_positions(trades)
    # 回填最新价用于末点市值
    for pos in positions.values():
        if abs(pos.quantity) > 1e-9:
            try:
                price = _ledger_latest_close(pos.code, pos.market)
                if price:
                    pos.last_price = price
            except Exception:  # noqa: BLE001 - market adapters must not block ledger reads
                logger.debug("回填最新价失败 %s", pos.code, exc_info=True)
    final_market_value = sum(p.market_value for p in positions.values())

    equity_curve = _build_equity_curve(trades, cash_entries, final_market_value)
    cash_flows = [{"ts": e.ts, "amount": e.signed_amount()} for e in cash_entries]
    twr = time_weighted_return(equity_curve, cash_flows)
    mdd = max_drawdown(equity_curve)

    # 基准对比：取最近一条基准曲线
    benchmarks = repository.list_benchmarks()
    bench_info: dict[str, Any] | None = None
    if benchmarks:
        latest_bench = benchmarks[0]
        bench_info = benchmark_excess(equity_curve, latest_bench.equity_curve)
        bench_info["benchmark_name"] = latest_bench.name
        bench_info["benchmark_code"] = latest_bench.code

    return {
        "ok": True,
        "equity_curve": equity_curve,
        "twr_pct": twr,
        "max_drawdown": mdd,
        "benchmark_excess": bench_info,
    }


def get_trade_analytics() -> dict:
    """Closed-trade quality report derived from immutable ledger executions."""
    return trade_analytics(repository.list_trades(limit=10_000))


def register_benchmark(req: BenchmarkCreate) -> dict:
    bench = Benchmark(
        id=str(uuid.uuid4()),
        name=req.name,
        code=req.code,
        market=req.market,
        equity_curve=req.equity_curve,
        metrics=req.metrics,
        ts=time.time(),
    )
    repository.save_benchmark(bench)
    return {"ok": True, "benchmark": bench.to_dict()}


def list_benchmarks() -> dict:
    items = repository.list_benchmarks()
    return {"count": len(items), "benchmarks": [b.to_dict() for b in items]}


def correct_benchmark(benchmark_id: str, req: BenchmarkCorrection) -> dict:
    current = repository.get_benchmark(benchmark_id)
    if current is None:
        return {"ok": False, "error": "基准记录不存在"}
    benchmark = Benchmark(
        id=benchmark_id,
        name=req.name,
        code=req.code.strip().upper(),
        market=req.market,
        equity_curve=req.equity_curve,
        metrics=req.metrics,
        ts=current.ts,
    )
    correction = repository.correct_benchmark(benchmark, req.reason.strip())
    return {"ok": True, "benchmark": benchmark.to_dict(), "correction": correction}


def list_corrections(
    entity_type: str | None = None, entity_id: str | None = None, limit: int = 200
) -> dict:
    corrections = repository.list_corrections(
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
    )
    return {"ok": True, "count": len(corrections), "corrections": corrections}


def exposures() -> dict:
    """风险敞口：按市场、方向、个股聚合。"""
    trades = repository.list_trades(limit=10_000)
    positions = compute_positions(trades)
    for pos in positions.values():
        if abs(pos.quantity) > 1e-9:
            try:
                price = _ledger_latest_close(pos.code, pos.market)
                if price:
                    pos.last_price = price
            except Exception:  # noqa: BLE001 - market adapters must not block ledger reads
                logger.debug("回填最新价失败 %s", pos.code, exc_info=True)
    active = [p for p in positions.values() if abs(p.quantity) > 1e-9]
    by_market: dict[str, float] = {}
    by_direction = {"long": 0, "short": 0}
    by_symbol: list[dict] = []
    for pos in active:
        mv = pos.market_value
        by_market[pos.market] = by_market.get(pos.market, 0) + mv
        if pos.quantity > 0:
            by_direction["long"] += 1
        else:
            by_direction["short"] += 1
        by_symbol.append(
            {
                "code": pos.code,
                "market": pos.market,
                "market_value": round(mv, 2),
                "weight_pct": 0.0,
            }
        )
    total_mv = sum(p.market_value for p in active)
    gross_mv = sum(abs(p.market_value) for p in active)
    for item in by_symbol:
        item["weight_pct"] = (
            round(abs(item["market_value"]) / gross_mv * 100, 2) if gross_mv > 0 else 0.0
        )
    by_symbol.sort(key=lambda x: abs(x["market_value"]), reverse=True)
    return {
        "ok": True,
        "by_market": {k: round(v, 2) for k, v in by_market.items()},
        "by_direction": by_direction,
        "by_symbol": by_symbol,
        "total_market_value": round(total_mv, 2),
        "gross_market_value": round(gross_mv, 2),
    }


def attribution(
    *, start_at: float | None = None, end_at: float | None = None, period: str = "month"
) -> dict:
    if period not in {"day", "week", "month"}:
        return {"ok": False, "error": "period 必须是 day、week 或 month"}
    trades = [
        trade
        for trade in repository.list_trades(limit=10_000)
        if (start_at is None or trade.ts >= start_at) and (end_at is None or trade.ts <= end_at)
    ]
    positions = compute_positions(trades)
    by_instrument = [
        {
            "instrument_id": position.instrument_id,
            "code": position.code,
            "market": position.market,
            "realized_pnl": round(position.realized_pnl, 2),
            "unrealized_pnl": round(position.unrealized_pnl, 2),
            "total_pnl": round(position.realized_pnl + position.unrealized_pnl, 2),
            "trade_count": sum(
                1 for trade in trades if trade.instrument_id == position.instrument_id
            ),
        }
        for position in positions.values()
    ]

    def aggregate(key_of) -> list[dict]:
        groups: dict[str, dict[str, Any]] = {}
        for trade in trades:
            key = key_of(trade)
            item = groups.setdefault(
                key, {"key": key, "trade_count": 0, "notional": 0.0, "fees": 0.0, "cash_flow": 0.0}
            )
            item["trade_count"] += 1
            item["notional"] += trade.quantity * trade.price
            item["fees"] += trade.fee
            item["cash_flow"] += trade.cash_flow()
        return [
            {
                **item,
                "notional": round(item["notional"], 2),
                "fees": round(item["fees"], 2),
                "cash_flow": round(item["cash_flow"], 2),
            }
            for item in sorted(groups.values(), key=lambda value: value["key"])
        ]

    closed_rows, matching = match_closed_trades(sorted(trades, key=lambda item: (item.ts, item.id)))

    def performance_aggregate(key_of) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in closed_rows:
            key = str(key_of(row) or "unknown")
            groups.setdefault(key, []).append(row)
        result: list[dict[str, Any]] = []
        for key, rows in sorted(groups.items()):
            cumulative = 0.0
            peak = 0.0
            max_drawdown_value = 0.0
            for row in rows:
                cumulative += float(row["pnl"])
                peak = max(peak, cumulative)
                max_drawdown_value = min(max_drawdown_value, cumulative - peak)
            gross_pnl = sum(float(row["gross_pnl"]) for row in rows)
            fees = sum(float(row["fees"]) for row in rows)
            net_pnl = sum(float(row["pnl"]) for row in rows)
            result.append(
                {
                    "key": key,
                    "trade_count": len(rows),
                    "wins": sum(float(row["pnl"]) > 0 for row in rows),
                    "win_rate_pct": round(
                        sum(float(row["pnl"]) > 0 for row in rows) / len(rows) * 100, 2
                    ),
                    "gross_pnl": round(gross_pnl, 2),
                    "fees": round(fees, 2),
                    "net_pnl": round(net_pnl, 2),
                    "fee_drag_pct": round(fees / abs(gross_pnl) * 100, 2) if gross_pnl else 0.0,
                    "average_holding_seconds": round(
                        sum(float(row["holding_seconds"]) for row in rows) / len(rows), 2
                    ),
                    "max_drawdown": round(max_drawdown_value, 2),
                    "links": [
                        {
                            "research_run_id": row.get("research_run_id"),
                            "signal_id": row.get("signal_id"),
                            "simulation_order_id": row.get("simulation_order_id"),
                            "execution_id": row.get("execution_id"),
                            "ledger_trade_id": row.get("exit_trade_id"),
                        }
                        for row in rows[-20:]
                    ],
                }
            )
        return result

    def period_key(trade: Trade) -> str:
        moment = datetime.fromtimestamp(trade.ts, UTC)
        if period == "day":
            return moment.strftime("%Y-%m-%d")
        if period == "week":
            year, week, _ = moment.isocalendar()
            return f"{year}-W{week:02d}"
        return moment.strftime("%Y-%m")

    return {
        "ok": True,
        "start_at": start_at,
        "end_at": end_at,
        "period": period,
        "by_instrument": sorted(by_instrument, key=lambda item: item["instrument_id"]),
        "by_strategy": aggregate(lambda trade: trade.strategy_id or "unknown"),
        "by_direction": aggregate(lambda trade: trade.direction),
        "by_period": aggregate(period_key),
        "by_factor": performance_aggregate(lambda row: row.get("factor_key")),
        "by_factor_version": performance_aggregate(
            lambda row: (
                f"{row.get('factor_key')}@{row.get('factor_version')}"
                if row.get("factor_key") and row.get("factor_version")
                else "unknown"
            )
        ),
        "by_research_run": performance_aggregate(lambda row: row.get("research_run_id")),
        "by_strategy_performance": performance_aggregate(lambda row: row.get("strategy_id")),
        "by_signal": performance_aggregate(lambda row: row.get("signal_id")),
        "by_market_regime": performance_aggregate(lambda row: row.get("market_regime_id")),
        "unknown_attribution": performance_aggregate(
            lambda row: (
                "unknown" if row.get("attribution_status") == "unknown_attribution" else "known"
            )
        ),
        "conservation": {
            "closed_trade_net_pnl": round(sum(float(row["pnl"]) for row in closed_rows), 2),
            "factor_group_net_pnl": round(
                sum(
                    item["net_pnl"]
                    for item in performance_aggregate(lambda row: row.get("factor_key"))
                ),
                2,
            ),
            "balanced": round(sum(float(row["pnl"]) for row in closed_rows), 2)
            == round(
                sum(
                    item["net_pnl"]
                    for item in performance_aggregate(lambda row: row.get("factor_key"))
                ),
                2,
            ),
            "matching": matching,
        },
    }


def decision_timeline(instrument_id: str) -> dict:
    events: list[dict[str, Any]] = []
    with store._lock, store._conn() as connection:
        research_rows = connection.execute(
            "SELECT * FROM research_runs WHERE instrument_id=?",
            (instrument_id,),
        ).fetchall()
        signal_rows = connection.execute(
            "SELECT * FROM signals WHERE instrument_id=?",
            (instrument_id,),
        ).fetchall()
        order_rows = connection.execute(
            "SELECT * FROM simulation_orders WHERE instrument_id=?",
            (instrument_id,),
        ).fetchall()
        order_ids = [row["id"] for row in order_rows]
        execution_rows = []
        if order_ids:
            placeholders = ",".join("?" for _ in order_ids)
            execution_rows = connection.execute(
                f"SELECT * FROM simulation_executions WHERE order_id IN ({placeholders})",
                order_ids,
            ).fetchall()
        trade_rows = connection.execute(
            "SELECT * FROM ledger_trades WHERE instrument_id=?",
            (instrument_id,),
        ).fetchall()
    for row in research_rows:
        events.append(
            {
                "kind": "research_run",
                "id": row["id"],
                "ts": row["updated_at"],
                "status": row["status"],
                "label": "研究运行",
                "links": {"research_run_id": row["id"]},
            }
        )
    for row in signal_rows:
        meta = json.loads(row["meta_json"] or "{}")
        events.append(
            {
                "kind": "signal",
                "id": row["id"],
                "ts": row["ts_epoch"],
                "status": row["status"],
                "label": f"信号 {row['direction']}",
                "note": row["decision_note"],
                "links": {
                    "research_run_id": meta.get("research_run_id"),
                    "signal_id": row["id"],
                    "order_id": row["order_id"],
                },
            }
        )
    for row in order_rows:
        events.append(
            {
                "kind": "simulation_order",
                "id": row["id"],
                "ts": row["created_at"],
                "status": row["status"],
                "label": f"模拟订单 {row['side']}",
                "links": {"signal_id": row["signal_id"], "order_id": row["id"]},
            }
        )
    for row in execution_rows:
        events.append(
            {
                "kind": "simulation_execution",
                "id": row["id"],
                "ts": row["executed_at"],
                "status": row["ledger_sync_status"],
                "label": "模拟成交",
                "links": {"order_id": row["order_id"], "ledger_trade_id": row["ledger_trade_id"]},
            }
        )
    for row in trade_rows:
        execution_id = row["id"].split(":", 1)[1] if row["id"].startswith("simulation:") else None
        events.append(
            {
                "kind": "ledger_trade",
                "id": row["id"],
                "ts": row["ts"],
                "status": "recorded",
                "label": f"账本成交 {row['direction']}",
                "note": row["note"],
                "links": {"ledger_trade_id": row["id"], "simulation_execution_id": execution_id},
            }
        )
    events.sort(key=lambda event: (event["ts"], event["kind"], event["id"]))
    return {"ok": True, "instrument_id": instrument_id, "count": len(events), "events": events}


def position_decision_context(instrument_id: str) -> dict:
    position = get_position(instrument_id)
    if not position.get("ok"):
        return position
    timeline = decision_timeline(instrument_id)
    return {"ok": True, "position": position["position"], "timeline": timeline}
