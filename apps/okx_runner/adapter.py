from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class InstrumentRules:
    minimum_quantity: float
    quantity_step: float
    price_tick: float
    fee_currency: str
    maximum_leverage: float


@dataclass(frozen=True)
class ExternalOrder:
    external_order_id: str
    client_order_id: str
    status: str
    filled_quantity: float = 0
    average_price: float | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExternalFill:
    external_fill_id: str
    external_order_id: str
    quantity: float
    price: float
    fee: float
    fee_currency: str
    filled_at: datetime


@dataclass(frozen=True)
class AccountSnapshot:
    orders: tuple[ExternalOrder, ...]
    fills: tuple[ExternalFill, ...]
    balances: dict[str, dict[str, float]]
    positions: dict[str, dict[str, float]]
    observed_at: datetime
    realized_pnl: float = 0.0
    peak_equity: float | None = None


class TradingAdapter(Protocol):
    def instrument_rules(self, symbol: str) -> InstrumentRules: ...

    def submit_order(self, request: dict[str, Any]) -> ExternalOrder: ...

    def fetch_order_by_client_id(self, client_order_id: str) -> ExternalOrder | None: ...

    def cancel_order(self, external_order_id: str) -> ExternalOrder: ...

    def account_snapshot(self, account_id: str) -> AccountSnapshot: ...

    def mark_price(self, symbol: str) -> float: ...


class DisabledAdapter:
    """Default adapter keeps external trading impossible until deployment injects one."""

    def instrument_rules(self, symbol: str) -> InstrumentRules:
        raise RuntimeError("no OKX adapter configured")

    def submit_order(self, request: dict[str, Any]) -> ExternalOrder:
        raise RuntimeError("no OKX adapter configured")

    def fetch_order_by_client_id(self, client_order_id: str) -> ExternalOrder | None:
        return None

    def cancel_order(self, external_order_id: str) -> ExternalOrder:
        raise RuntimeError("no OKX adapter configured")

    def account_snapshot(self, account_id: str) -> AccountSnapshot:
        raise RuntimeError("no OKX adapter configured")

    def mark_price(self, symbol: str) -> float:
        raise RuntimeError("no OKX adapter configured")
