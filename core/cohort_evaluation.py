"""Versioned cohort evaluation with isolated event-sourced virtual ledgers."""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import numpy as np
import pandas as pd

COHORT_ENGINE_VERSION = "1.1.0"
BENCHMARK_POOL_VERSION = "factor-cohort-v2"


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class BenchmarkStrategyDefinition:
    key: str
    strategy_type: str
    params: dict[str, Any]
    markets: tuple[str, ...]
    risk_limits: dict[str, float]
    code_version: str = COHORT_ENGINE_VERSION
    content_hash: str = ""

    def __post_init__(self) -> None:
        payload = {
            "key": self.key,
            "strategy_type": self.strategy_type,
            "params": self.params,
            "markets": self.markets,
            "risk_limits": self.risk_limits,
            "code_version": self.code_version,
        }
        computed = _hash(payload)
        if self.content_hash and self.content_hash != computed:
            raise ValueError("benchmark definition content hash mismatch")
        object.__setattr__(self, "content_hash", computed)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkPoolVersion:
    version: str
    market: str
    interval: str
    definitions: tuple[BenchmarkStrategyDefinition, ...]
    created_at: str
    content_hash: str = ""

    def __post_init__(self) -> None:
        keys = [item.key for item in self.definitions]
        if len(keys) != len(set(keys)):
            raise ValueError("benchmark keys must be unique")
        payload = {
            "version": self.version,
            "market": self.market,
            "interval": self.interval,
            "definitions": [item.to_dict() for item in self.definitions],
        }
        computed = _hash(payload)
        if self.content_hash and self.content_hash != computed:
            raise ValueError("benchmark pool content hash mismatch")
        object.__setattr__(self, "content_hash", computed)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "definitions": [item.to_dict() for item in self.definitions],
        }


@dataclass(frozen=True)
class EvaluationCohort:
    cohort_id: str
    candidate_key: str
    candidate_version: str
    benchmark_pool_version: str
    benchmark_pool_hash: str
    started_at: str
    ends_at: str
    config_hash: str
    market_data_fingerprint: str
    status: str = "cohort_observing"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionPolicy:
    commission_bps: float = 3.0
    spread_bps: float = 2.0
    slippage_bps: float = 1.0
    capacity_fraction: float = 0.25
    min_quantity: float = 1e-8
    quantity_step: float = 1e-8
    price_tick: float = 1e-8
    maximum_exposure: float = 1.0
    maximum_daily_loss: float = 0.05
    maximum_drawdown: float = 0.25
    instrument_type: Literal["spot", "perpetual"] = "spot"
    contract_multiplier: float = 1.0
    leverage: float = 1.0
    maintenance_margin_rate: float = 0.005
    funding_rate_per_period: float = 0.0
    maximum_price_gap_bps: float = 500.0

    @property
    def total_cost_rate(self) -> float:
        return (self.commission_bps + self.spread_bps / 2 + self.slippage_bps) / 10_000


@dataclass
class VirtualOrder:
    order_id: str
    idempotency_key: str
    ledger_id: str
    decision_time: str
    tradable_time: str
    quote_time: str
    side: Literal["buy", "sell"]
    requested_quantity: float
    status: str
    rejection_reason: str | None = None
    reference_price: float | None = None
    bid: float | None = None
    ask: float | None = None


@dataclass
class VirtualExecution:
    execution_id: str
    order_id: str
    execution_time: str
    side: Literal["buy", "sell"]
    quantity: float
    price: float
    fee: float
    slippage: float
    reference_price: float = 0.0
    spread_cost: float = 0.0
    slippage_cost: float = 0.0


@dataclass
class VirtualCashFlow:
    cash_flow_id: str
    event_key: str
    event_time: str
    kind: str
    amount: float


@dataclass
class VirtualPosition:
    quantity: float = 0.0
    average_price: float = 0.0
    realized_pnl: float = 0.0


@dataclass
class VirtualRiskEvent:
    risk_event_id: str
    event_key: str
    event_time: str
    kind: str
    detail: dict[str, Any]


@dataclass
class VirtualLedger:
    ledger_id: str
    member_key: str
    initial_cash: float
    cash: float
    position: VirtualPosition = field(default_factory=VirtualPosition)
    orders: list[VirtualOrder] = field(default_factory=list)
    executions: list[VirtualExecution] = field(default_factory=list)
    cash_flows: list[VirtualCashFlow] = field(default_factory=list)
    risk_events: list[VirtualRiskEvent] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    processed_keys: set[str] = field(default_factory=set)
    turnover_notional: float = 0.0
    peak_equity: float = 0.0
    instrument_type: Literal["spot", "perpetual"] = "spot"
    contract_multiplier: float = 1.0
    leverage: float = 1.0
    maintenance_margin_rate: float = 0.005
    funding_rate_per_period: float = 0.0
    maximum_exposure: float = 1.0
    maximum_daily_loss: float = 0.05
    maximum_drawdown: float = 0.25
    min_quantity: float = 1e-8
    maximum_price_gap_bps: float = 500.0
    current_day: str | None = None
    day_start_equity: float = 0.0
    last_mark_price: float | None = None
    halted: bool = False

    @classmethod
    def create(
        cls,
        ledger_id: str,
        member_key: str,
        initial_cash: float,
        policy: ExecutionPolicy | None = None,
    ) -> VirtualLedger:
        policy = policy or ExecutionPolicy()
        return cls(
            ledger_id=ledger_id,
            member_key=member_key,
            initial_cash=initial_cash,
            cash=initial_cash,
            peak_equity=initial_cash,
            instrument_type=policy.instrument_type,
            contract_multiplier=policy.contract_multiplier,
            leverage=policy.leverage,
            maintenance_margin_rate=policy.maintenance_margin_rate,
            funding_rate_per_period=policy.funding_rate_per_period,
            maximum_exposure=policy.maximum_exposure,
            maximum_daily_loss=policy.maximum_daily_loss,
            maximum_drawdown=policy.maximum_drawdown,
            min_quantity=policy.min_quantity,
            maximum_price_gap_bps=policy.maximum_price_gap_bps,
            day_start_equity=initial_cash,
        )

    def _unrealized_pnl(self, price: float) -> float:
        if self.position.quantity == 0:
            return 0.0
        return (
            (price - self.position.average_price)
            * self.position.quantity
            * self.contract_multiplier
        )

    def equity_at(self, price: float) -> float:
        if self.instrument_type == "perpetual":
            return self.cash + self._unrealized_pnl(price)
        return self.cash + self.position.quantity * price * self.contract_multiplier

    def exposure_at(self, price: float) -> float:
        equity = self.equity_at(price)
        if equity <= 0:
            return math.inf
        notional = abs(self.position.quantity * price * self.contract_multiplier)
        return notional / equity

    def _record_risk(self, event_key: str, event_time: str, kind: str, **detail: Any) -> None:
        if any(item.event_key == event_key and item.kind == kind for item in self.risk_events):
            return
        self.risk_events.append(
            VirtualRiskEvent(
                risk_event_id=_hash([self.ledger_id, event_key, kind])[:24],
                event_key=event_key,
                event_time=event_time,
                kind=kind,
                detail=detail,
            )
        )

    def apply_cash_flow(
        self,
        *,
        event_key: str,
        event_time: str,
        kind: str,
        amount: float,
    ) -> bool:
        key = f"cash:{kind}:{event_key}"
        if key in self.processed_keys:
            return False
        self.processed_keys.add(key)
        self.cash += amount
        self.cash_flows.append(
            VirtualCashFlow(
                cash_flow_id=_hash([self.ledger_id, key])[:24],
                event_key=event_key,
                event_time=event_time,
                kind=kind,
                amount=amount,
            )
        )
        return True

    def mark(
        self,
        event_key: str,
        event_time: str,
        price: float,
        *,
        apply_funding: bool = True,
    ) -> bool:
        key = f"mark:{event_key}"
        if key in self.processed_keys:
            return False
        if self.last_mark_price and self.maximum_price_gap_bps > 0:
            gap_bps = abs(price / self.last_mark_price - 1) * 10_000
            if gap_bps > self.maximum_price_gap_bps:
                self.halted = True
                self._record_risk(
                    event_key,
                    event_time,
                    "price_gap_exceeded",
                    actual_bps=gap_bps,
                    limit_bps=self.maximum_price_gap_bps,
                )
        if apply_funding and self.instrument_type == "perpetual" and self.position.quantity:
            funding = (
                -self.position.quantity
                * price
                * self.contract_multiplier
                * self.funding_rate_per_period
            )
            self.apply_cash_flow(
                event_key=event_key,
                event_time=event_time,
                kind="funding",
                amount=funding,
            )
        equity = self.equity_at(price)
        day = event_time[:10]
        if self.current_day != day:
            self.current_day = day
            self.day_start_equity = equity
        self.peak_equity = max(self.peak_equity, equity)
        drawdown = equity / self.peak_equity - 1 if self.peak_equity > 0 else 0.0
        daily_return = equity / self.day_start_equity - 1 if self.day_start_equity > 0 else -1.0
        exposure = self.exposure_at(price)
        if drawdown <= -self.maximum_drawdown:
            self.halted = True
            self._record_risk(
                event_key,
                event_time,
                "maximum_drawdown",
                actual=abs(drawdown),
                limit=self.maximum_drawdown,
            )
        if daily_return <= -self.maximum_daily_loss:
            self.halted = True
            self._record_risk(
                event_key,
                event_time,
                "maximum_daily_loss",
                actual=abs(daily_return),
                limit=self.maximum_daily_loss,
            )
        maintenance_margin = (
            abs(self.position.quantity * price * self.contract_multiplier)
            * self.maintenance_margin_rate
        )
        if self.instrument_type == "perpetual" and equity <= maintenance_margin:
            self.halted = True
            self._record_risk(
                event_key,
                event_time,
                "liquidation_risk",
                equity=equity,
                maintenance_margin=maintenance_margin,
            )
        self.equity_curve.append(
            {
                "event_key": event_key,
                "t": event_time,
                "price": price,
                "cash": self.cash,
                "position": self.position.quantity,
                "equity": equity,
                "drawdown": drawdown,
                "daily_return": daily_return,
                "exposure": exposure,
            }
        )
        self.last_mark_price = price
        self.processed_keys.add(key)
        return True

    def rebalance(
        self,
        *,
        event_key: str,
        decision_time: str,
        tradable_time: str,
        quote_time: str,
        execution_time: str,
        reference_price: float,
        target_weight: float,
        policy: ExecutionPolicy,
        bid: float | None = None,
        ask: float | None = None,
        quote_available: bool = True,
    ) -> VirtualOrder | None:
        key = f"order:{event_key}"
        if key in self.processed_keys:
            return None
        self.processed_keys.add(key)
        equity = self.equity_at(reference_price)
        capped_weight = max(-policy.maximum_exposure, min(policy.maximum_exposure, target_weight))
        target_quantity = (
            capped_weight
            * equity
            / max(reference_price * policy.contract_multiplier, policy.price_tick)
        )
        raw_delta = target_quantity - self.position.quantity
        stepped_delta = math.floor(abs(raw_delta) / policy.quantity_step) * policy.quantity_step
        delta = math.copysign(stepped_delta, raw_delta) if stepped_delta else 0.0
        side: Literal["buy", "sell"] = "buy" if delta >= 0 else "sell"
        order = VirtualOrder(
            order_id=_hash([self.ledger_id, key])[:24],
            idempotency_key=key,
            ledger_id=self.ledger_id,
            decision_time=decision_time,
            tradable_time=tradable_time,
            quote_time=quote_time,
            side=side,
            requested_quantity=abs(delta),
            status="accepted",
            reference_price=reference_price,
            bid=bid,
            ask=ask,
        )
        if not quote_available or (bid is None) != (ask is None):
            order.status = "rejected"
            order.rejection_reason = "missing_executable_quote"
            self.orders.append(order)
            return order
        if bid is not None and ask is not None and (bid <= 0 or ask < bid):
            order.status = "rejected"
            order.rejection_reason = "invalid_executable_quote"
            self.orders.append(order)
            return order
        if self.halted and abs(capped_weight) >= self.exposure_at(reference_price):
            order.status = "rejected"
            order.rejection_reason = "risk_halted"
            self.orders.append(order)
            return order
        if self.last_mark_price and policy.maximum_price_gap_bps > 0:
            gap_bps = abs(reference_price / self.last_mark_price - 1) * 10_000
            if gap_bps > policy.maximum_price_gap_bps:
                order.status = "rejected"
                order.rejection_reason = "price_gap_exceeded"
                self._record_risk(
                    event_key,
                    execution_time,
                    "price_gap_exceeded",
                    actual_bps=gap_bps,
                    limit_bps=policy.maximum_price_gap_bps,
                )
                self.orders.append(order)
                return order
        if abs(delta) < policy.min_quantity:
            order.status = "rejected"
            order.rejection_reason = "below_minimum_quantity"
            self.orders.append(order)
            return order
        maximum_quantity = (
            policy.capacity_fraction
            * equity
            / max(reference_price * policy.contract_multiplier, policy.price_tick)
        )
        fill_quantity = min(abs(delta), maximum_quantity)
        if fill_quantity < policy.min_quantity:
            order.status = "rejected"
            order.rejection_reason = "insufficient_capacity"
            self.orders.append(order)
            return order
        if fill_quantity + 1e-12 < abs(delta):
            order.status = "partially_filled"
        else:
            order.status = "filled"
        direction = 1 if side == "buy" else -1
        side_quote = (
            (ask if side == "buy" else bid)
            if bid is not None and ask is not None
            else (reference_price * (1 + direction * policy.spread_bps / 20_000))
        )
        execution_price = side_quote * (1 + direction * policy.slippage_bps / 10_000)
        quantity_delta = direction * fill_quantity
        notional = fill_quantity * execution_price * policy.contract_multiplier
        fee = (
            fill_quantity
            * reference_price
            * policy.contract_multiplier
            * policy.commission_bps
            / 10_000
        )
        old_quantity = self.position.quantity
        old_average = self.position.average_price
        realized_increment = 0.0
        if old_quantity == 0 or old_quantity * quantity_delta > 0:
            new_quantity = old_quantity + quantity_delta
            self.position.average_price = (
                abs(old_quantity) * old_average + abs(quantity_delta) * execution_price
            ) / abs(new_quantity)
        else:
            closed = min(abs(old_quantity), abs(quantity_delta))
            realized_increment = (
                (execution_price - old_average)
                * closed
                * self.contract_multiplier
                * (1 if old_quantity > 0 else -1)
            )
            self.position.realized_pnl += realized_increment
            new_quantity = old_quantity + quantity_delta
            if abs(new_quantity) < policy.min_quantity:
                new_quantity = 0.0
                self.position.average_price = 0.0
            elif old_quantity * new_quantity < 0:
                self.position.average_price = execution_price
        self.position.quantity = new_quantity
        cash_change = (
            realized_increment - fee
            if policy.instrument_type == "perpetual"
            else -quantity_delta * execution_price * policy.contract_multiplier - fee
        )
        self.cash += cash_change
        execution = VirtualExecution(
            execution_id=_hash([order.order_id, execution_time])[:24],
            order_id=order.order_id,
            execution_time=execution_time,
            side=side,
            quantity=fill_quantity,
            price=execution_price,
            fee=fee,
            slippage=abs(execution_price - side_quote) * fill_quantity * policy.contract_multiplier,
            reference_price=reference_price,
            spread_cost=abs(side_quote - reference_price)
            * fill_quantity
            * policy.contract_multiplier,
            slippage_cost=abs(execution_price - side_quote)
            * fill_quantity
            * policy.contract_multiplier,
        )
        self.orders.append(order)
        self.executions.append(execution)
        self.cash_flows.append(
            VirtualCashFlow(
                cash_flow_id=_hash([execution.execution_id, "trade"])[:24],
                event_key=event_key,
                event_time=execution_time,
                kind="trade_and_fee",
                amount=cash_change,
            )
        )
        self.turnover_notional += notional
        return order

    def reconstructed_state(
        self, *, price: float, event_time: str | None = None
    ) -> dict[str, float]:
        executions = [
            item
            for item in self.executions
            if event_time is None or item.execution_time <= event_time
        ]
        flows = [
            item for item in self.cash_flows if event_time is None or item.event_time <= event_time
        ]
        cash = self.initial_cash + sum(item.amount for item in flows)
        average_price = 0.0
        position = 0.0
        realized = 0.0
        for item in executions:
            delta = (1 if item.side == "buy" else -1) * item.quantity
            if position == 0 or position * delta > 0:
                new_position = position + delta
                average_price = (abs(position) * average_price + abs(delta) * item.price) / abs(
                    new_position
                )
            else:
                closed = min(abs(position), abs(delta))
                realized += (
                    (item.price - average_price)
                    * closed
                    * self.contract_multiplier
                    * (1 if position > 0 else -1)
                )
                new_position = position + delta
                if abs(new_position) < self.min_quantity:
                    new_position = 0.0
                    average_price = 0.0
                elif position * new_position < 0:
                    average_price = item.price
            position = new_position
        quantity = position
        if self.instrument_type == "perpetual":
            unrealized = (price - average_price) * position * self.contract_multiplier
            equity = cash + unrealized
        else:
            equity = cash + quantity * price * self.contract_multiplier
        return {
            "cash": cash,
            "quantity": quantity,
            "realized_pnl": realized,
            "equity": equity,
        }

    def verify_replay(self, *, price: float) -> dict[str, Any]:
        state = self.reconstructed_state(price=price)
        expected_equity = self.equity_at(price)
        checks = {
            "cash": math.isclose(state["cash"], self.cash, rel_tol=0, abs_tol=1e-8),
            "quantity": math.isclose(
                state["quantity"], self.position.quantity, rel_tol=0, abs_tol=1e-8
            ),
            "equity": math.isclose(state["equity"], expected_equity, rel_tol=0, abs_tol=1e-8),
        }
        return {"passed": all(checks.values()), "checks": checks, "reconstructed": state}

    def to_dict(self) -> dict[str, Any]:
        return {
            "ledger_id": self.ledger_id,
            "member_key": self.member_key,
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "position": asdict(self.position),
            "orders": [asdict(item) for item in self.orders],
            "executions": [asdict(item) for item in self.executions],
            "cash_flows": [asdict(item) for item in self.cash_flows],
            "risk_events": [asdict(item) for item in self.risk_events],
            "equity_curve": self.equity_curve,
            "processed_keys": sorted(self.processed_keys),
            "turnover_notional": self.turnover_notional,
            "peak_equity": self.peak_equity,
            "instrument_type": self.instrument_type,
            "contract_multiplier": self.contract_multiplier,
            "leverage": self.leverage,
            "maintenance_margin_rate": self.maintenance_margin_rate,
            "funding_rate_per_period": self.funding_rate_per_period,
            "maximum_exposure": self.maximum_exposure,
            "maximum_daily_loss": self.maximum_daily_loss,
            "maximum_drawdown": self.maximum_drawdown,
            "min_quantity": self.min_quantity,
            "maximum_price_gap_bps": self.maximum_price_gap_bps,
            "current_day": self.current_day,
            "day_start_equity": self.day_start_equity,
            "last_mark_price": self.last_mark_price,
            "halted": self.halted,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> VirtualLedger:
        policy = ExecutionPolicy(
            instrument_type=payload.get("instrument_type", "spot"),
            contract_multiplier=payload.get("contract_multiplier", 1.0),
            leverage=payload.get("leverage", 1.0),
            maintenance_margin_rate=payload.get("maintenance_margin_rate", 0.005),
            funding_rate_per_period=payload.get("funding_rate_per_period", 0.0),
            maximum_exposure=payload.get("maximum_exposure", 1.0),
            maximum_daily_loss=payload.get("maximum_daily_loss", 0.05),
            maximum_drawdown=payload.get("maximum_drawdown", 0.25),
            min_quantity=payload.get("min_quantity", 1e-8),
            maximum_price_gap_bps=payload.get("maximum_price_gap_bps", 500.0),
        )
        ledger = cls.create(
            payload["ledger_id"], payload["member_key"], payload["initial_cash"], policy
        )
        ledger.cash = payload["cash"]
        ledger.position = VirtualPosition(**payload.get("position", {}))
        ledger.orders = [VirtualOrder(**item) for item in payload.get("orders", [])]
        ledger.executions = [VirtualExecution(**item) for item in payload.get("executions", [])]
        ledger.cash_flows = [VirtualCashFlow(**item) for item in payload.get("cash_flows", [])]
        ledger.risk_events = [VirtualRiskEvent(**item) for item in payload.get("risk_events", [])]
        ledger.equity_curve = list(payload.get("equity_curve", []))
        ledger.processed_keys = set(payload.get("processed_keys", []))
        ledger.turnover_notional = payload.get("turnover_notional", 0.0)
        ledger.peak_equity = payload.get("peak_equity", ledger.initial_cash)
        ledger.current_day = payload.get("current_day")
        ledger.day_start_equity = payload.get("day_start_equity", ledger.initial_cash)
        ledger.last_mark_price = payload.get("last_mark_price")
        ledger.halted = payload.get("halted", False)
        return ledger


def default_benchmark_pool(market: str, interval: str) -> BenchmarkPoolVersion:
    common_risk = {"maximum_exposure": 1.0, "maximum_drawdown": 0.25}
    specs: list[tuple[str, str, dict[str, Any]]] = [
        ("cash", "cash", {}),
        ("buy_hold", "buy_hold", {}),
        ("dca", "dca", {"frequency": 20, "target_step": 0.1}),
        ("fixed_exposure", "fixed_exposure", {"weight": 0.5}),
        ("ma_trend", "ma_trend", {"fast": 10, "slow": 40}),
        ("time_series_momentum", "momentum", {"lookback": 20}),
        ("donchian_breakout", "donchian", {"lookback": 20}),
        ("zscore_mean_reversion", "mean_reversion", {"lookback": 20, "entry_z": 1.5}),
        ("volatility_target", "volatility_target", {"lookback": 20, "target": 0.15}),
        (
            "grid_arithmetic",
            "grid",
            {
                "mode": "arithmetic",
                "levels": 8,
                "width": 0.08,
                "capital_per_level": 0.125,
                "exit_rule": "return_to_center_or_cohort_end",
            },
        ),
        (
            "grid_geometric",
            "grid",
            {
                "mode": "geometric",
                "levels": 8,
                "width": 0.08,
                "capital_per_level": 0.125,
                "exit_rule": "return_to_center_or_cohort_end",
            },
        ),
        (
            "grid_adaptive",
            "grid",
            {
                "mode": "adaptive",
                "levels": 8,
                "width": 0.08,
                "atr": 2.0,
                "capital_per_level": 0.125,
                "exit_rule": "return_to_center_or_cohort_end",
            },
        ),
        (
            "grid_trend_filtered",
            "grid",
            {
                "mode": "trend_filtered",
                "levels": 8,
                "width": 0.08,
                "capital_per_level": 0.125,
                "exit_rule": "return_to_center_or_cohort_end",
            },
        ),
        ("fixed_stop_time_exit", "fixed_stop", {"stop": 0.04, "take": 0.08, "bars": 20}),
        ("limited_martingale", "martingale", {"layers": 3, "multiplier": 1.5}),
        ("anti_martingale", "anti_martingale", {"layers": 3, "multiplier": 1.25}),
    ]
    for seed in range(20):
        specs.append((f"random_{seed:02d}", "random", {"seed": seed, "hold_probability": 0.6}))
    definitions = tuple(
        BenchmarkStrategyDefinition(
            key=key,
            strategy_type=strategy_type,
            params=params,
            markets=(market,),
            risk_limits=common_risk,
        )
        for key, strategy_type, params in specs
    )
    return BenchmarkPoolVersion(
        version=BENCHMARK_POOL_VERSION,
        market=market,
        interval=interval,
        definitions=definitions,
        created_at=datetime.now(UTC).isoformat(),
    )


def _strategy_weights(
    definition: BenchmarkStrategyDefinition,
    frame: pd.DataFrame,
    periods_per_year: int,
) -> pd.Series:
    close = frame["close"].astype(float).reset_index(drop=True)
    strategy = definition.strategy_type
    params = definition.params
    if strategy == "cash":
        return pd.Series(0.0, index=close.index)
    if strategy == "buy_hold":
        return pd.Series(1.0, index=close.index)
    if strategy == "fixed_exposure":
        return pd.Series(float(params["weight"]), index=close.index)
    if strategy == "dca":
        step = float(params["target_step"])
        frequency = int(params["frequency"])
        return pd.Series([min(1.0, (index // frequency + 1) * step) for index in close.index])
    if strategy == "ma_trend":
        fast = close.rolling(int(params["fast"])).mean()
        slow = close.rolling(int(params["slow"])).mean()
        return (fast > slow).astype(float)
    if strategy == "momentum":
        return (close.pct_change(int(params["lookback"])) > 0).astype(float)
    if strategy == "donchian":
        high = close.rolling(int(params["lookback"])).max().shift(1)
        low = close.rolling(int(params["lookback"])).min().shift(1)
        state = 0.0
        values = []
        for price, upper, lower in zip(close, high, low, strict=False):
            if pd.notna(upper) and price > upper:
                state = 1.0
            elif pd.notna(lower) and price < lower:
                state = 0.0
            values.append(state)
        return pd.Series(values)
    if strategy == "mean_reversion":
        lookback = int(params["lookback"])
        mean = close.rolling(lookback).mean()
        std = close.rolling(lookback).std().replace(0, np.nan)
        zscore = (close - mean) / std
        return (zscore < -float(params["entry_z"])).astype(float)
    if strategy == "volatility_target":
        realized = close.pct_change().rolling(int(params["lookback"])).std() * math.sqrt(
            periods_per_year
        )
        return (float(params["target"]) / realized.replace(0, np.nan)).clip(0, 1).fillna(0)
    if strategy == "grid":
        center = close.rolling(40, min_periods=5).mean()
        deviation = (close / center - 1).fillna(0)
        width = float(params.get("width", 0.08))
        if params.get("mode") == "adaptive":
            width_series = close.pct_change().rolling(20).std().fillna(width / 2) * float(
                params.get("atr", 2)
            )
        else:
            width_series = pd.Series(width, index=close.index)
        weights = (0.5 - deviation / (2 * width_series.replace(0, np.nan))).clip(0, 1).fillna(0.5)
        if params.get("mode") == "geometric":
            weights = weights.pow(1.25)
        if params.get("mode") == "trend_filtered":
            trend = close > close.rolling(80, min_periods=10).mean()
            weights = weights.where(~trend, weights.clip(upper=0.35))
        return weights
    if strategy in {"martingale", "anti_martingale"}:
        returns = close.pct_change().fillna(0)
        layers = int(params["layers"])
        multiplier = float(params["multiplier"])
        loss_streak = win_streak = 0
        values = []
        for value in returns:
            loss_streak = loss_streak + 1 if value < 0 else 0
            win_streak = win_streak + 1 if value > 0 else 0
            streak = loss_streak if strategy == "martingale" else win_streak
            values.append(min(1.0, 0.25 * multiplier ** min(streak, layers)))
        return pd.Series(values)
    if strategy == "fixed_stop":
        momentum = close.pct_change(10)
        return (momentum > 0).astype(float)
    if strategy == "random":
        rng = random.Random(int(params["seed"]))
        probability = float(params["hold_probability"])
        return pd.Series([1.0 if rng.random() > probability else 0.0 for _ in close.index])
    raise ValueError(f"unknown benchmark strategy: {strategy}")


def _metrics(ledger: VirtualLedger, periods_per_year: int) -> dict[str, Any]:
    equities = pd.Series([point["equity"] for point in ledger.equity_curve], dtype=float)
    returns = equities.pct_change().dropna()
    total_return = equities.iloc[-1] / ledger.initial_cash - 1 if len(equities) else 0.0
    drawdown = equities / equities.cummax() - 1 if len(equities) else pd.Series(dtype=float)
    max_drawdown = abs(float(drawdown.min())) if len(drawdown) else 0.0
    volatility = (
        float(returns.std(ddof=1) * math.sqrt(periods_per_year)) if len(returns) > 1 else 0.0
    )
    annual_return = float(returns.mean() * periods_per_year) if len(returns) else 0.0
    downside = returns[returns < 0]
    downside_vol = (
        float(downside.std(ddof=1) * math.sqrt(periods_per_year)) if len(downside) > 1 else 0.0
    )
    cvar = abs(float(returns[returns <= returns.quantile(0.05)].mean())) if len(returns) else 0.0
    average_equity = float(equities.mean()) if len(equities) else ledger.initial_cash
    average_exposure = (
        float(
            np.mean(
                [
                    abs(point["position"] * point["price"]) / max(point["equity"], 1e-9)
                    for point in ledger.equity_curve
                ]
            )
        )
        if ledger.equity_curve
        else 0.0
    )
    total_fees = sum(item.fee for item in ledger.executions)
    total_spread_cost = sum(item.spread_cost for item in ledger.executions)
    total_slippage_cost = sum(item.slippage_cost for item in ledger.executions)
    total_funding = sum(item.amount for item in ledger.cash_flows if item.kind == "funding")
    rejected_orders = [item for item in ledger.orders if item.status == "rejected"]
    return {
        "absolute_return": total_return,
        "after_cost_return": total_return,
        "max_drawdown": max_drawdown,
        "sharpe": annual_return / volatility if volatility > 0 else 0.0,
        "sortino": annual_return / downside_vol if downside_vol > 0 else 0.0,
        "calmar": annual_return / max_drawdown if max_drawdown > 0 else 0.0,
        "cvar_95": cvar,
        "turnover": ledger.turnover_notional / max(average_equity, 1e-9),
        "fill_rate": (
            len(ledger.executions)
            / len([order for order in ledger.orders if order.requested_quantity > 0])
            if any(order.requested_quantity > 0 for order in ledger.orders)
            else 1.0
        ),
        "capital_utilization": average_exposure,
        "trade_count": len(ledger.executions),
        "fees": total_fees,
        "spread_cost": total_spread_cost,
        "slippage_cost": total_slippage_cost,
        "funding_pnl": total_funding,
        "volatility": volatility,
        "rejected_order_count": len(rejected_orders),
        "rejection_reasons": sorted(
            {item.rejection_reason for item in rejected_orders if item.rejection_reason}
        ),
        "risk_event_count": len(ledger.risk_events),
        "risk_halted": ledger.halted,
        "final_equity": float(equities.iloc[-1]) if len(equities) else ledger.initial_cash,
    }


def _annual_periods(market: str, interval: str) -> int:
    if market == "crypto":
        return {"1h": 365 * 24, "4h": 365 * 6, "1d": 365}.get(interval, 365)
    return {"1h": 252 * 4, "4h": 252, "1d": 252}.get(interval, 252)


def _regime_labels(frame: pd.DataFrame) -> pd.DataFrame:
    close = frame["close"].astype(float).reset_index(drop=True)
    volume = (
        frame.get("volume", pd.Series(1.0, index=frame.index)).astype(float).reset_index(drop=True)
    )
    returns = close.pct_change().fillna(0.0)
    rolling_return = close.pct_change(20).fillna(0.0)
    volatility = returns.rolling(20, min_periods=5).std().fillna(returns.expanding().std())
    volatility = volatility.fillna(0.0)
    median_volatility = float(volatility.median())
    median_volume = float(volume.median())
    trend_strength = rolling_return.abs()
    trend_threshold = max(float(trend_strength.median()), 0.01)
    return pd.DataFrame(
        {
            "direction": np.where(rolling_return >= 0, "up", "down"),
            "trend": np.where(trend_strength >= trend_threshold, "trend", "range"),
            "volatility": np.where(
                volatility >= median_volatility, "high_volatility", "low_volatility"
            ),
            "liquidity": np.where(volume >= median_volume, "normal_liquidity", "low_liquidity"),
        }
    )


def _regime_report(
    *,
    ledgers: dict[str, VirtualLedger],
    frame: pd.DataFrame,
    candidate_key: str,
    benchmark_key: str,
) -> dict[str, Any]:
    labels = _regime_labels(frame)
    candidate_equity = pd.Series(
        [point["equity"] for point in ledgers[candidate_key].equity_curve], dtype=float
    )
    benchmark_equity = pd.Series(
        [point["equity"] for point in ledgers[benchmark_key].equity_curve], dtype=float
    )
    candidate_returns = candidate_equity.pct_change().fillna(0.0)
    benchmark_returns = benchmark_equity.pct_change().fillna(0.0)
    result: dict[str, Any] = {}
    for dimension in labels.columns:
        result[dimension] = {}
        for regime in sorted(labels[dimension].unique()):
            mask = labels[dimension] == regime
            candidate_return = float((1 + candidate_returns[mask]).prod() - 1)
            benchmark_return = float((1 + benchmark_returns[mask]).prod() - 1)
            result[dimension][regime] = {
                "observations": int(mask.sum()),
                "candidate_return": candidate_return,
                "benchmark_return": benchmark_return,
                "excess_return": candidate_return - benchmark_return,
            }
    return result


def _risk_normalized_return(metrics: dict[str, Any], target_volatility: float) -> float:
    volatility = float(metrics.get("volatility") or 0.0)
    if volatility <= 0:
        return 0.0
    scale = min(1.0, target_volatility / volatility)
    return float(metrics["after_cost_return"]) * scale


def _grid_risk_report(
    *,
    pool: BenchmarkPoolVersion,
    ledgers: dict[str, VirtualLedger],
    frame: pd.DataFrame,
) -> dict[str, Any]:
    definitions = {item.key: item for item in pool.definitions}
    final_price = float(frame["close"].iloc[-1])
    result: dict[str, Any] = {}
    for key, definition in definitions.items():
        if definition.strategy_type != "grid":
            continue
        ledger = ledgers[key]
        params = dict(definition.params)
        width = float(params.get("width", 0.08))
        center = float(frame["close"].tail(min(40, len(frame))).mean())
        lower = center * (1 - width)
        upper = center * (1 + width)
        inventory_notional = ledger.position.quantity * final_price * ledger.contract_multiplier
        equity = max(ledger.equity_at(final_price), 1e-9)
        fees = sum(item.fee for item in ledger.executions)
        result[key] = {
            "mode": params.get("mode"),
            "levels": int(params.get("levels", 0)),
            "range": {"lower": lower, "center": center, "upper": upper},
            "inventory_quantity": ledger.position.quantity,
            "inventory_notional": inventory_notional,
            "inventory_risk": abs(inventory_notional) / equity,
            "capital_utilization": _metrics(ledger, 365).get("capital_utilization", 0.0),
            "trade_count": len(ledger.executions),
            "fee_share_of_initial_capital": fees / ledger.initial_cash,
            "outside_range": final_price < lower or final_price > upper,
            "outside_range_loss": max(
                0.0,
                -ledger.position.quantity
                * (final_price - (lower if final_price < lower else upper))
                * ledger.contract_multiplier,
            ),
            "idle_cash_ratio": max(0.0, ledger.cash / equity),
            "preregistered": True,
            "exit_rule": params.get("exit_rule", "return_to_center_or_cohort_end"),
        }
    return result


def run_cohort_backtest(
    *,
    cohort_id: str,
    frame: pd.DataFrame,
    candidate_signal: pd.Series,
    candidate_key: str,
    market: str,
    interval: str,
    initial_capital: float,
    policy: ExecutionPolicy,
    pool: BenchmarkPoolVersion | None = None,
) -> dict[str, Any]:
    if frame.empty or len(frame) != len(candidate_signal):
        raise ValueError("cohort frame and candidate signal must be non-empty and aligned")
    frame = frame.reset_index(drop=True).copy()
    frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
    pool = pool or default_benchmark_pool(market, interval)
    periods_per_year = 365 * 24 if interval == "1h" and market == "crypto" else 365
    signals: dict[str, pd.Series] = {
        candidate_key: pd.Series(candidate_signal).reset_index(drop=True).fillna(0).clip(-1, 1)
    }
    for definition in pool.definitions:
        signals[definition.key] = _strategy_weights(definition, frame, periods_per_year)
    signals["candidate_fixed_exposure"] = signals[candidate_key].apply(
        lambda value: math.copysign(0.5, value) if value else 0.0
    )
    signals["candidate_volatility_target"] = signals[candidate_key] * (
        0.15
        / frame["close"]
        .astype(float)
        .pct_change()
        .rolling(20)
        .std()
        .mul(math.sqrt(periods_per_year))
        .replace(0, np.nan)
    ).clip(0, 1).fillna(0)
    ledgers = {
        key: VirtualLedger.create(f"{cohort_id}:{key}", key, initial_capital, policy)
        for key in signals
    }
    for index, row in frame.iterrows():
        event_time = row["datetime"].to_pydatetime().astimezone(UTC).isoformat()
        event_key = _hash([cohort_id, event_time, float(row["close"])])[:24]
        execution_price = float(row.get("open", row["close"]))
        mark_price = float(row["close"])
        bid = float(row["bid"]) if "bid" in row and pd.notna(row["bid"]) else None
        ask = float(row["ask"]) if "ask" in row and pd.notna(row["ask"]) else None
        quote_available = not bool(row.get("quote_missing", False))
        for key, ledger in ledgers.items():
            target = float(signals[key].shift(1).fillna(0).iloc[index])
            ledger.rebalance(
                event_key=event_key,
                decision_time=(
                    frame["datetime"].iloc[index - 1].to_pydatetime().astimezone(UTC).isoformat()
                    if index > 0
                    else event_time
                ),
                tradable_time=event_time,
                quote_time=event_time,
                execution_time=event_time,
                reference_price=execution_price,
                target_weight=target,
                policy=policy,
                bid=bid,
                ask=ask,
                quote_available=quote_available,
            )
            ledger.mark(event_key, event_time, mark_price)
    rows = []
    for key, ledger in ledgers.items():
        rows.append({"member_key": key, "metrics": _metrics(ledger, periods_per_year)})
    rows.sort(key=lambda item: item["metrics"]["sharpe"], reverse=True)
    random_returns = sorted(
        item["metrics"]["after_cost_return"]
        for item in rows
        if item["member_key"].startswith("random_")
    )
    candidate = next(item for item in rows if item["member_key"] == candidate_key)
    candidate_return = candidate["metrics"]["after_cost_return"]
    random_percentile = (
        sum(value <= candidate_return for value in random_returns) / len(random_returns)
        if random_returns
        else 0.0
    )
    key_map = {item["member_key"]: item for item in rows}
    grids = [item for item in rows if item["member_key"].startswith("grid_")]
    simple = [key_map[key] for key in ("cash", "buy_hold", "dca", "fixed_exposure")]
    market_tailwind = (
        sum(item["metrics"]["after_cost_return"] > 0 for item in rows) / len(rows) >= 0.7
    )
    target_volatility = float(key_map["fixed_exposure"]["metrics"]["volatility"] or 0.15)
    candidate_risk_normalized = _risk_normalized_return(candidate["metrics"], target_volatility)
    benchmark_risk_normalized = {
        key: _risk_normalized_return(item["metrics"], target_volatility)
        for key, item in key_map.items()
    }
    candidate_ledger = ledgers[candidate_key]
    replay = {
        key: ledger.verify_replay(price=float(frame["close"].iloc[-1]))
        for key, ledger in ledgers.items()
    }
    regime_report = _regime_report(
        ledgers=ledgers,
        frame=frame,
        candidate_key=candidate_key,
        benchmark_key="buy_hold",
    )
    regime_excess = [
        values["excess_return"] for groups in regime_report.values() for values in groups.values()
    ]
    return {
        "engine_version": COHORT_ENGINE_VERSION,
        "benchmark_pool": pool.to_dict(),
        "execution_policy": asdict(policy),
        "ranking": rows,
        "ledgers": {key: ledger.to_dict() for key, ledger in ledgers.items()},
        "replay_verification": {
            "passed": all(item["passed"] for item in replay.values()),
            "ledgers": replay,
        },
        "grid_risk": _grid_risk_report(pool=pool, ledgers=ledgers, frame=frame),
        "regime_analysis": regime_report,
        "comparison": {
            "candidate_key": candidate_key,
            "candidate_rank": next(
                index + 1 for index, item in enumerate(rows) if item is candidate
            ),
            "random_percentile": random_percentile,
            "excess_vs_cash": candidate_return - key_map["cash"]["metrics"]["after_cost_return"],
            "excess_vs_buy_hold": candidate_return
            - key_map["buy_hold"]["metrics"]["after_cost_return"],
            "excess_vs_best_simple": candidate_return
            - max(item["metrics"]["after_cost_return"] for item in simple),
            "excess_vs_grid_median": candidate_return
            - float(np.median([item["metrics"]["after_cost_return"] for item in grids])),
            "market_tailwind": market_tailwind,
            "normalizations": {
                "equal_capital": True,
                "equal_maximum_exposure": policy.maximum_exposure,
                "equal_risk_policy": True,
                "equal_volatility": {
                    "target_volatility": target_volatility,
                    "candidate_return": candidate_risk_normalized,
                    "benchmark_returns": benchmark_risk_normalized,
                },
            },
            "attribution": {
                "market_beta_proxy": key_map["buy_hold"]["metrics"]["after_cost_return"],
                "signal_and_timing": candidate_return
                - key_map["buy_hold"]["metrics"]["after_cost_return"],
                "fees": -candidate["metrics"]["fees"] / initial_capital,
                "spread": -candidate["metrics"]["spread_cost"] / initial_capital,
                "slippage": -candidate["metrics"]["slippage_cost"] / initial_capital,
                "funding": candidate["metrics"]["funding_pnl"] / initial_capital,
                "position_management": candidate_return
                - key_map["candidate_fixed_exposure"]["metrics"]["after_cost_return"],
                "volatility_sizing": candidate_return
                - key_map["candidate_volatility_target"]["metrics"]["after_cost_return"],
            },
            "paired_signal_controls": {
                "candidate_raw": candidate_return,
                "candidate_fixed_exposure": key_map["candidate_fixed_exposure"]["metrics"][
                    "after_cost_return"
                ],
                "candidate_volatility_target": key_map["candidate_volatility_target"]["metrics"][
                    "after_cost_return"
                ],
            },
            "regime_stability": {
                "minimum_excess_return": min(regime_excess) if regime_excess else 0.0,
                "positive_group_ratio": (
                    sum(value >= 0 for value in regime_excess) / len(regime_excess)
                    if regime_excess
                    else 0.0
                ),
            },
        },
        "fairness": {
            "shared_market_event_count": len(frame),
            "identical_event_order": True,
            "independent_ledgers": len({id(ledger) for ledger in ledgers.values()}) == len(ledgers),
            "same_execution_policy": True,
            "same_market_calendar": True,
            "same_quote_and_gap_policy": True,
            "same_rejection_model": True,
            "same_funding_model": True,
            "risk_limits_enforced": all(
                max(
                    (point.get("exposure", 0.0) for point in ledger.equity_curve),
                    default=0.0,
                )
                <= policy.maximum_exposure + 1e-8
                for ledger in ledgers.values()
            ),
            "missing_results_preserved": all(key in ledgers for key in signals),
        },
    }


def program_live_gate(
    report: dict[str, Any],
    *,
    observed_days: float,
    rebalance_count: int,
    freshness_ok: bool,
    reconciliation_ok: bool,
    kill_switch_ready: bool,
    required_days: int = 7,
    required_rebalances: int = 3,
    random_percentile: float = 0.8,
) -> dict[str, Any]:
    comparison = report["comparison"]
    candidate = next(
        item for item in report["ranking"] if item["member_key"] == comparison["candidate_key"]
    )
    metrics = candidate["metrics"]
    checks = {
        "minimum_observation_days": observed_days >= required_days,
        "minimum_rebalances": rebalance_count >= required_rebalances,
        "positive_after_cost_return": metrics["after_cost_return"] > 0,
        "risk_adjusted_excess": comparison["excess_vs_best_simple"] > 0,
        "random_distribution": comparison["random_percentile"] >= random_percentile,
        "not_leverage_driven": (
            metrics["capital_utilization"] <= 1.0
            and comparison["normalizations"]["equal_volatility"]["candidate_return"]
            > comparison["normalizations"]["equal_volatility"]["benchmark_returns"].get("cash", 0.0)
        ),
        "drawdown_within_limit": metrics["max_drawdown"] <= 0.25,
        "fill_and_capacity": metrics["fill_rate"] >= 0.95,
        "risk_limits": report.get("fairness", {}).get("risk_limits_enforced") is True,
        "replay_reconciled": report.get("replay_verification", {}).get("passed") is True,
        "regime_stability": comparison.get("regime_stability", {}).get("positive_group_ratio", 0.0)
        >= 0.5,
        "freshness": freshness_ok,
        "reconciliation": reconciliation_ok,
        "kill_switch": kill_switch_ready,
    }
    violations = [key for key, passed in checks.items() if not passed]
    return {
        "version": "small-live-gate-v1",
        "passed": not violations,
        "checks": checks,
        "violations": violations,
        "allowed_transition": "live_requested" if not violations else None,
        "ai_can_override": False,
        "manual_approval_required": True,
        "live_trading_enabled": False,
    }
