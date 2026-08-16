"""组合账本领域模型与持仓计算。"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class Trade:
    """成交流水。direction: buy/sell。"""

    id: str
    instrument_id: str
    code: str
    market: str
    direction: str  # "buy" | "sell"
    quantity: float
    price: float
    fee: float = 0.0
    ts: float = 0.0
    source: str = "manual"
    note: str = ""
    strategy_id: str | None = None
    strategy_version: str | None = None
    factor_key: str | None = None
    factor_version: str | None = None
    research_run_id: str | None = None
    signal_id: str | None = None
    simulation_order_id: str | None = None
    execution_id: str | None = None
    market_regime_id: str | None = None
    attribution_status: str = "unknown_attribution"

    def signed_quantity(self) -> float:
        """带符号数量：buy 正、sell 负。"""
        return self.quantity if self.direction == "buy" else -self.quantity

    def cash_flow(self) -> float:
        """对现金的影响：buy 减少（负）、sell 增加（正），扣除费用。"""
        if self.direction == "buy":
            return -(self.quantity * self.price + self.fee)
        return self.quantity * self.price - self.fee

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CashEntry:
    """现金流水：direction in/out。"""

    id: str
    direction: str  # "in" | "out"
    amount: float
    currency: str = "CNY"
    ts: float = 0.0
    source: str = "manual"
    note: str = ""

    def signed_amount(self) -> float:
        return self.amount if self.direction == "in" else -self.amount

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Position:
    """由成交计算的持仓。"""

    instrument_id: str
    code: str
    market: str
    quantity: float = 0.0
    average_cost: float = 0.0
    realized_pnl: float = 0.0
    last_price: float = 0.0
    ts: float = 0.0

    @property
    def unrealized_pnl(self) -> float:
        if abs(self.quantity) <= 1e-9 or self.average_cost <= 0:
            return 0.0
        return (self.last_price - self.average_cost) * self.quantity

    @property
    def market_value(self) -> float:
        return self.quantity * self.last_price

    @property
    def cost_basis(self) -> float:
        return abs(self.quantity) * self.average_cost

    def to_dict(self) -> dict:
        d = asdict(self)
        d["unrealized_pnl"] = round(self.unrealized_pnl, 2)
        d["market_value"] = round(self.market_value, 2)
        d["cost_basis"] = round(self.cost_basis, 2)
        return d


@dataclass
class Benchmark:
    """基准曲线与指标。"""

    id: str
    name: str
    code: str
    market: str
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    ts: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def apply_trade(position: Position, trade: Trade) -> Position:
    """把一笔成交应用到持仓，返回更新后的持仓（不修改原对象）。

    正数量表示多头，负数量表示空头；反向成交先平仓，超出部分建立反向持仓。
    """
    old_quantity = position.quantity
    average_cost = position.average_cost
    realized = position.realized_pnl

    if trade.direction == "buy":
        new_quantity = old_quantity + trade.quantity
        if old_quantity >= 0:
            new_average = (
                old_quantity * average_cost + trade.quantity * trade.price
            ) / new_quantity
        else:
            closed_quantity = min(trade.quantity, -old_quantity)
            realized += (average_cost - trade.price) * closed_quantity
            if new_quantity > 1e-9:
                new_average = trade.price
            elif new_quantity < -1e-9:
                new_average = average_cost
            else:
                new_average = 0.0
    else:
        new_quantity = old_quantity - trade.quantity
        if old_quantity <= 0:
            new_average = ((-old_quantity) * average_cost + trade.quantity * trade.price) / (
                -new_quantity
            )
        else:
            closed_quantity = min(trade.quantity, old_quantity)
            realized += (trade.price - average_cost) * closed_quantity
            if new_quantity < -1e-9:
                new_average = trade.price
            elif new_quantity > 1e-9:
                new_average = average_cost
            else:
                new_average = 0.0

    return Position(
        instrument_id=position.instrument_id,
        code=position.code,
        market=position.market,
        quantity=new_quantity,
        average_cost=new_average,
        realized_pnl=realized,
        last_price=trade.price,
        ts=trade.ts,
    )


def compute_positions(trades: list[Trade]) -> dict[str, Position]:
    """从成交流水计算各标的持仓。返回 instrument_id → Position。"""
    positions: dict[str, Position] = {}
    for trade in sorted(trades, key=lambda t: t.ts):
        pos = positions.get(trade.instrument_id)
        if pos is None:
            pos = Position(
                instrument_id=trade.instrument_id,
                code=trade.code,
                market=trade.market,
            )
        positions[trade.instrument_id] = apply_trade(pos, trade)
    return positions


def match_closed_trades(trades: list[Trade]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Match executions into FIFO closed trades without inventing broker fields."""
    lots: dict[str, list[dict[str, Any]]] = {}
    closed: list[dict[str, Any]] = []
    for trade in sorted(trades, key=lambda item: (item.ts, item.id)):
        sign = 1 if trade.direction == "buy" else -1
        remaining = float(trade.quantity)
        fee_per_unit = float(trade.fee) / remaining if remaining > 0 else 0.0
        instrument_lots = lots.setdefault(trade.instrument_id, [])

        while remaining > 1e-9 and instrument_lots and instrument_lots[0]["sign"] != sign:
            lot = instrument_lots[0]
            quantity = min(remaining, lot["quantity"])
            entry_fee = lot["fee_per_unit"] * quantity
            exit_fee = fee_per_unit * quantity
            gross_pnl = (float(trade.price) - lot["price"]) * quantity * lot["sign"]
            pnl = gross_pnl - entry_fee - exit_fee
            entry_notional = lot["price"] * quantity
            closed.append(
                {
                    "instrument_id": trade.instrument_id,
                    "code": trade.code,
                    "market": trade.market,
                    "direction": "long" if lot["sign"] > 0 else "short",
                    "quantity": round(quantity, 8),
                    "entry_price": round(lot["price"], 8),
                    "exit_price": round(float(trade.price), 8),
                    "entry_at": lot["ts"],
                    "exit_at": trade.ts,
                    "holding_seconds": max(0.0, trade.ts - lot["ts"]),
                    "gross_pnl": round(gross_pnl, 2),
                    "fees": round(entry_fee + exit_fee, 2),
                    "pnl": round(pnl, 2),
                    "return_pct": round(pnl / entry_notional * 100, 4)
                    if entry_notional > 0
                    else 0.0,
                    "source": lot["source"],
                    "strategy_id": lot["strategy_id"],
                    "strategy_version": lot["strategy_version"],
                    "factor_key": lot["factor_key"],
                    "factor_version": lot["factor_version"],
                    "research_run_id": lot["research_run_id"],
                    "signal_id": lot["signal_id"],
                    "simulation_order_id": lot["simulation_order_id"],
                    "execution_id": lot["execution_id"],
                    "market_regime_id": lot["market_regime_id"],
                    "attribution_status": lot["attribution_status"],
                    "entry_trade_id": lot["trade_id"],
                    "exit_trade_id": trade.id,
                    "entry_notional": round(entry_notional, 2),
                    "exit_notional": round(float(trade.price) * quantity, 2),
                }
            )
            remaining -= quantity
            lot["quantity"] -= quantity
            if lot["quantity"] <= 1e-9:
                instrument_lots.pop(0)

        if remaining > 1e-9:
            instrument_lots.append(
                {
                    "sign": sign,
                    "quantity": remaining,
                    "price": float(trade.price),
                    "fee_per_unit": fee_per_unit,
                    "ts": trade.ts,
                    "source": trade.source or "manual",
                    "trade_id": trade.id,
                    "strategy_id": trade.strategy_id,
                    "strategy_version": trade.strategy_version,
                    "factor_key": trade.factor_key,
                    "factor_version": trade.factor_version,
                    "research_run_id": trade.research_run_id,
                    "signal_id": trade.signal_id,
                    "simulation_order_id": trade.simulation_order_id,
                    "execution_id": trade.execution_id,
                    "market_regime_id": trade.market_regime_id,
                    "attribution_status": trade.attribution_status,
                }
            )

    open_quantity = sum(
        abs(float(lot["quantity"])) for instrument_lots in lots.values() for lot in instrument_lots
    )
    return closed, {
        "open_lot_count": sum(len(instrument_lots) for instrument_lots in lots.values()),
        "open_quantity": round(open_quantity, 8),
    }


def trade_analytics(trades: list[Trade]) -> dict[str, Any]:
    closed, matching = match_closed_trades(trades)
    wins = [item for item in closed if item["pnl"] > 0]
    losses = [item for item in closed if item["pnl"] < 0]
    total_pnl = sum(item["pnl"] for item in closed)
    gross_profit = sum(item["pnl"] for item in wins)
    gross_loss = abs(sum(item["pnl"] for item in losses))
    entry_notional = sum(item["entry_notional"] for item in closed)
    total_fees = sum(item["fees"] for item in closed)

    consecutive_losses = 0
    max_consecutive_losses = 0
    cumulative = 0.0
    peak = 0.0
    peak_at: float | None = None
    drawdown_started_at: float | None = None
    max_stagnation_seconds = 0.0
    cumulative_curve: list[dict[str, Any]] = []
    for item in closed:
        consecutive_losses = consecutive_losses + 1 if item["pnl"] < 0 else 0
        max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
        cumulative += item["pnl"]
        if cumulative >= peak:
            if drawdown_started_at is not None:
                max_stagnation_seconds = max(
                    max_stagnation_seconds, item["exit_at"] - drawdown_started_at
                )
            peak = cumulative
            peak_at = item["exit_at"]
            drawdown_started_at = None
        elif drawdown_started_at is None:
            drawdown_started_at = peak_at or item["exit_at"]
        cumulative_curve.append(
            {
                "t": item["exit_at"],
                "pnl": round(cumulative, 2),
                "drawdown": round(cumulative - peak, 2),
            }
        )
    if drawdown_started_at is not None and closed:
        max_stagnation_seconds = max(
            max_stagnation_seconds, closed[-1]["exit_at"] - drawdown_started_at
        )

    def grouped(key_of) -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for item in closed:
            key = key_of(item)
            group = groups.setdefault(key, {"key": key, "count": 0, "wins": 0, "pnl": 0.0})
            group["count"] += 1
            group["wins"] += item["pnl"] > 0
            group["pnl"] += item["pnl"]
        return [
            {
                **group,
                "pnl": round(group["pnl"], 2),
                "win_rate_pct": round(group["wins"] / group["count"] * 100, 2),
            }
            for group in sorted(groups.values(), key=lambda value: value["key"])
        ]

    monthly = grouped(lambda item: datetime.fromtimestamp(item["exit_at"], UTC).strftime("%Y-%m"))
    daily = grouped(lambda item: datetime.fromtimestamp(item["exit_at"], UTC).strftime("%Y-%m-%d"))
    directions = grouped(lambda item: item["direction"])

    holding_ranges = (
        ("≤15分钟", -1, 15 * 60),
        ("15–60分钟", 15 * 60, 60 * 60),
        ("1–2小时", 60 * 60, 2 * 60 * 60),
        ("2–4小时", 2 * 60 * 60, 4 * 60 * 60),
        (">4小时", 4 * 60 * 60, math.inf),
    )
    holding_buckets = []
    for label, lower, upper in holding_ranges:
        items = [item for item in closed if lower < item["holding_seconds"] <= upper]
        holding_buckets.append(
            {
                "key": label,
                "count": len(items),
                "share_pct": round(len(items) / len(closed) * 100, 2) if closed else 0.0,
                "pnl": round(sum(item["pnl"] for item in items), 2),
            }
        )

    return {
        "ok": True,
        "summary": {
            "closed_trades": len(closed),
            "total_pnl": round(total_pnl, 2),
            "return_pct": round(total_pnl / entry_notional * 100, 4) if entry_notional > 0 else 0.0,
            "win_rate_pct": round(len(wins) / len(closed) * 100, 2) if closed else 0.0,
            "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss > 0 else None,
            "average_profit_loss_ratio": round(
                (gross_profit / len(wins)) / (gross_loss / len(losses)), 3
            )
            if wins and losses
            else None,
            "max_consecutive_losses": max_consecutive_losses,
            "average_holding_seconds": round(
                sum(item["holding_seconds"] for item in closed) / len(closed), 2
            )
            if closed
            else 0.0,
            "max_stagnation_days": round(max_stagnation_seconds / 86_400, 2),
        },
        "execution_quality": {
            "total_fees": round(total_fees, 2),
            "average_fee": round(total_fees / len(closed), 2) if closed else 0.0,
            "fee_drag_pct": round(total_fees / max(1e-9, gross_profit + gross_loss) * 100, 2),
            "slippage_available": False,
            "slippage_note": "账本未记录预期成交价，无法可靠计算滑点",
        },
        "matching": matching,
        "cumulative_curve": cumulative_curve,
        "monthly": monthly,
        "daily": daily,
        "directions": directions,
        "holding_buckets": holding_buckets,
        "closed_trade_rows": list(reversed(closed[-200:])),
    }


def portfolio_metrics(positions: dict[str, Position], cash_balance: float) -> dict[str, Any]:
    """计算组合级指标。"""
    total_realized = sum(p.realized_pnl for p in positions.values())
    total_unrealized = sum(p.unrealized_pnl for p in positions.values())
    total_market_value = sum(p.market_value for p in positions.values())
    total_cost = sum(p.cost_basis for p in positions.values())
    nav = total_market_value + cash_balance
    return {
        "nav": round(nav, 2),
        "cash": round(cash_balance, 2),
        "market_value": round(total_market_value, 2),
        "cost_basis": round(total_cost, 2),
        "realized_pnl": round(total_realized, 2),
        "unrealized_pnl": round(total_unrealized, 2),
        "total_pnl": round(total_realized + total_unrealized, 2),
        "return_pct": round((total_realized + total_unrealized) / total_cost * 100, 2)
        if total_cost > 0
        else 0.0,
        "n_positions": sum(1 for p in positions.values() if abs(p.quantity) > 1e-9),
    }


def max_drawdown(equity_curve: list[dict[str, Any]]) -> dict[str, Any]:
    """从权益曲线计算最大回撤。

    equity_curve 形如 [{"t": "...", "equity": 12345.0}, ...]，按时间升序。
    返回 ``{"max_drawdown_pct": ..., "peak_at": ..., "trough_at": ...}``。
    """
    if not equity_curve:
        return {"max_drawdown_pct": 0.0, "peak_at": None, "trough_at": None}
    peak = float(equity_curve[0].get("equity", 0))
    peak_t = equity_curve[0].get("t")
    trough_t = equity_curve[0].get("t")
    best_peak = peak
    best_peak_t = peak_t
    best_trough_t = trough_t
    best_dd = 0.0
    for point in equity_curve:
        eq = float(point.get("equity", 0))
        t = point.get("t")
        if eq > peak:
            peak = eq
            peak_t = t
        if peak > 0:
            dd = (peak - eq) / peak
            if dd > best_dd:
                best_dd = dd
                best_peak = peak
                best_peak_t = peak_t
                best_trough_t = t
    return {
        "max_drawdown_pct": round(best_dd * 100, 2),
        "peak_equity": round(best_peak, 2),
        "peak_at": best_peak_t,
        "trough_at": best_trough_t,
    }


def time_weighted_return(
    equity_curve: list[dict[str, Any]],
    cash_flows: list[dict[str, Any]] | None = None,
) -> float:
    """简化 TWR：基于权益曲线与外部现金流估算时间加权收益率。

    若未提供 cash_flows，退化为简单收益率 (末值/首值 - 1)。
    cash_flows 形如 [{"ts": 1.0, "amount": 1000}, ...]，amount 正数=入金，负数=出金。
    """
    if not equity_curve:
        return 0.0
    points = sorted(equity_curve, key=lambda p: str(p.get("t", "")))
    start_eq = float(points[0].get("equity", 0))
    end_eq = float(points[-1].get("equity", 0))
    if start_eq <= 0:
        return 0.0
    if not cash_flows:
        return round((end_eq / start_eq - 1) * 100, 2)
    # 简化 TWR：按相邻时点切分，扣除中间现金流影响
    sorted_flows = sorted(cash_flows, key=lambda c: float(c.get("ts", 0)))
    twr = 1.0
    prev_eq = start_eq
    flow_idx = 0
    for point in points[1:]:
        eq = float(point.get("equity", 0))
        ts = float(point.get("ts", 0) or 0)
        # 累计本区间内的净现金流
        net_flow = 0.0
        while flow_idx < len(sorted_flows) and float(sorted_flows[flow_idx].get("ts", 0)) <= ts:
            net_flow += float(sorted_flows[flow_idx].get("amount", 0))
            flow_idx += 1
        # 期初调整：扣除期间净流入后的期初净值
        adjusted_start = prev_eq + net_flow / 2  # 简化假设：现金流均匀发生
        if adjusted_start > 0:
            twr *= eq / adjusted_start
        prev_eq = eq
    return round((twr - 1) * 100, 2)


def benchmark_excess(
    portfolio_curve: list[dict[str, Any]],
    benchmark_curve: list[dict[str, Any]],
) -> dict[str, Any]:
    """计算组合相对基准的超额收益。

    两条曲线均按 ``t`` 升序对齐，使用首末点估算累计收益率后做差。
    """
    p_ret = _curve_return_pct(portfolio_curve)
    b_ret = _curve_return_pct(benchmark_curve)
    return {
        "portfolio_return_pct": p_ret,
        "benchmark_return_pct": b_ret,
        "excess_return_pct": round(p_ret - b_ret, 2),
    }


def _curve_return_pct(curve: list[dict[str, Any]]) -> float:
    if not curve:
        return 0.0
    points = sorted(curve, key=lambda p: str(p.get("t", "")))
    start = float(points[0].get("equity", 0))
    end = float(points[-1].get("equity", 0))
    if start <= 0:
        return 0.0
    return round((end / start - 1) * 100, 2)
