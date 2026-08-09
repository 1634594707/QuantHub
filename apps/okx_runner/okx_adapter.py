from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from .adapter import AccountSnapshot, ExternalFill, ExternalOrder, InstrumentRules


def _step(value: Any, default: float) -> float:
    if value is None:
        return default
    numeric = float(value)
    if numeric >= 1 and numeric.is_integer():
        return 10 ** (-int(numeric))
    return numeric


class OkxCcxtAdapter:
    def __init__(self, exchange: Any) -> None:
        self.exchange = exchange
        self._symbols_by_order: dict[str, str] = {}

    @staticmethod
    def _order(payload: dict[str, Any]) -> ExternalOrder:
        info = payload.get("info") or {}
        client_id = str(payload.get("clientOrderId") or info.get("clOrdId") or "")
        external_id = str(payload.get("id") or info.get("ordId") or "")
        return ExternalOrder(
            external_order_id=external_id,
            client_order_id=client_id,
            status=str(payload.get("status") or "unknown"),
            filled_quantity=float(payload.get("filled") or 0),
            average_price=(
                float(payload["average"]) if payload.get("average") is not None else None
            ),
            raw={
                "code": info.get("code"),
                "message": info.get("msg"),
                "timestamp": payload.get("timestamp"),
            },
        )

    def instrument_rules(self, symbol: str) -> InstrumentRules:
        markets = self.exchange.load_markets()
        market = markets.get(symbol)
        if market is None:
            raise ValueError(f"OKX symbol is not available: {symbol}")
        limits = market.get("limits") or {}
        precision = market.get("precision") or {}
        return InstrumentRules(
            minimum_quantity=float((limits.get("amount") or {}).get("min") or 0),
            quantity_step=_step(precision.get("amount"), 1e-8),
            price_tick=_step(precision.get("price"), 1e-8),
            fee_currency=str(market.get("settle") or market.get("quote") or "USDT"),
            maximum_leverage=float((limits.get("leverage") or {}).get("max") or 1),
        )

    def submit_order(self, request: dict[str, Any]) -> ExternalOrder:
        payload = self.exchange.create_order(
            request["symbol"],
            request["order_type"],
            request["side"],
            request["quantity"],
            request.get("price"),
            {"clOrdId": request["client_order_id"]},
        )
        order = self._order(payload)
        self._symbols_by_order[order.external_order_id] = request["symbol"]
        return order

    def fetch_order_by_client_id(self, client_order_id: str) -> ExternalOrder | None:
        orders = self.exchange.fetch_orders(None, None, None, {"clOrdId": client_order_id})
        for payload in orders:
            order = self._order(payload)
            if order.client_order_id == client_order_id:
                if payload.get("symbol"):
                    self._symbols_by_order[order.external_order_id] = payload["symbol"]
                return order
        return None

    def cancel_order(self, external_order_id: str) -> ExternalOrder:
        symbol = self._symbols_by_order.get(external_order_id)
        if symbol is None:
            for payload in self.exchange.fetch_orders():
                if str(payload.get("id")) == external_order_id:
                    symbol = payload.get("symbol")
                    break
        if not symbol:
            raise LookupError("cannot resolve symbol for external order")
        return self._order(self.exchange.cancel_order(external_order_id, symbol))

    def account_snapshot(self, account_id: str) -> AccountSnapshot:
        raw_orders = self.exchange.fetch_orders()
        orders = tuple(self._order(payload) for payload in raw_orders)
        for payload, order in zip(raw_orders, orders, strict=True):
            if payload.get("symbol"):
                self._symbols_by_order[order.external_order_id] = payload["symbol"]
        fills = tuple(
            ExternalFill(
                external_fill_id=str(trade["id"]),
                external_order_id=str(trade.get("order") or ""),
                quantity=float(trade.get("amount") or 0),
                price=float(trade.get("price") or 0),
                fee=float((trade.get("fee") or {}).get("cost") or 0),
                fee_currency=str((trade.get("fee") or {}).get("currency") or "USDT"),
                filled_at=datetime.fromtimestamp(float(trade.get("timestamp") or 0) / 1000, UTC),
            )
            for trade in self.exchange.fetch_my_trades()
        )
        balance = self.exchange.fetch_balance()
        currencies = set(balance.get("total", {})) | set(balance.get("free", {}))
        balances = {
            currency: {
                "total": float(balance.get("total", {}).get(currency) or 0),
                "available": float(balance.get("free", {}).get(currency) or 0),
            }
            for currency in currencies
        }
        positions = {
            str(position["symbol"]): {
                "quantity": float(position.get("contracts") or 0),
                "mark_price": float(position.get("markPrice") or 0),
            }
            for position in self.exchange.fetch_positions()
        }
        equity = sum(values["total"] for values in balances.values())
        return AccountSnapshot(
            orders=orders,
            fills=fills,
            balances=balances,
            positions=positions,
            observed_at=datetime.now(UTC),
            # OKX's unified account equity can be exposed by a deployment adapter
            # with a richer account endpoint. The baseline retains a server-side
            # total balance value until then and never accepts a browser value.
            peak_equity=equity,
        )

    def mark_price(self, symbol: str) -> float:
        ticker = self.exchange.fetch_ticker(symbol)
        value = ticker.get("mark") or ticker.get("last") or ticker.get("close")
        if value is None or float(value) <= 0:
            raise RuntimeError(f"no usable mark price for {symbol}")
        return float(value)


def create_okx_adapter_from_env(environment: str) -> OkxCcxtAdapter:
    source = os.environ.get("QH_OKX_CREDENTIAL_SOURCE", "environment").strip().lower()
    if source == "local_vault":
        if environment != "demo":
            raise RuntimeError("The local OKX Demo vault can only be used in demo mode")
        if any(
            os.environ.get(name, "").strip()
            for name in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_PASSPHRASE")
        ):
            raise RuntimeError(
                "Local vault and environment OKX credentials cannot both be configured"
            )
        from packages.credential_vault import load_okx_demo_credentials

        stored = load_okx_demo_credentials()
        credentials = {
            "apiKey": stored.api_key,
            "secret": stored.secret_key,
            "password": stored.passphrase,
        }
    elif source == "environment":
        if os.name == "nt":
            from packages.credential_vault import okx_demo_credential_status

            if okx_demo_credential_status()["configured"]:
                raise RuntimeError(
                    "Local vault and environment OKX credentials cannot both be configured"
                )
        credentials = {
            "apiKey": os.environ.get("OKX_API_KEY", ""),
            "secret": os.environ.get("OKX_API_SECRET", ""),
            "password": os.environ.get("OKX_PASSPHRASE", ""),
        }
    else:
        raise RuntimeError("QH_OKX_CREDENTIAL_SOURCE must be environment or local_vault")
    if not all(credentials.values()):
        raise RuntimeError("OKX deployment credentials are incomplete")
    try:
        import ccxt
    except ImportError as exc:
        raise RuntimeError("Runner demo/live mode requires the crypto dependency group") from exc
    exchange = ccxt.okx(credentials | {"enableRateLimit": True})
    exchange.session.trust_env = True
    if environment == "demo":
        exchange.set_sandbox_mode(True)
    return OkxCcxtAdapter(exchange)
