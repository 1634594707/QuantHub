from __future__ import annotations

import os
import time
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

    def _resolve_market(self, symbol: str) -> tuple[str, dict[str, Any]]:
        markets = self.exchange.load_markets()
        direct = markets.get(symbol)
        if direct is not None:
            return symbol, direct
        for exchange_symbol, market in markets.items():
            info = market.get("info") or {}
            if symbol in {str(market.get("id") or ""), str(info.get("instId") or "")}:
                return exchange_symbol, market
        raise ValueError(f"OKX symbol is not available: {symbol}")

    @staticmethod
    def _internal_symbol(exchange_symbol: str, market: dict[str, Any]) -> str:
        info = market.get("info") or {}
        return str(market.get("id") or info.get("instId") or exchange_symbol)

    def _internal_symbol_for(self, exchange_symbol: str) -> str:
        try:
            resolved, market = self._resolve_market(exchange_symbol)
        except ValueError:
            return exchange_symbol
        return self._internal_symbol(resolved, market)

    @staticmethod
    def _rules(exchange_symbol: str, market: dict[str, Any]) -> InstrumentRules:
        limits = market.get("limits") or {}
        precision = market.get("precision") or {}
        return InstrumentRules(
            minimum_quantity=float((limits.get("amount") or {}).get("min") or 0),
            quantity_step=_step(precision.get("amount"), 1e-8),
            price_tick=_step(precision.get("price"), 1e-8),
            fee_currency=str(market.get("settle") or market.get("quote") or "USDT"),
            maximum_leverage=float((limits.get("leverage") or {}).get("max") or 1),
            minimum_notional=(
                float((limits.get("cost") or {}).get("min"))
                if (limits.get("cost") or {}).get("min") is not None
                else None
            ),
            contract_size=(
                float(market["contractSize"]) if market.get("contractSize") is not None else None
            ),
            product_type=str(market.get("type") or "unknown"),
            exchange_symbol=exchange_symbol,
        )

    def preflight(self, symbols: list[str]) -> dict[str, Any]:
        raw_config = self.exchange.private_get_account_config()
        account = (raw_config.get("data") or [{}])[0]
        server_time = self.exchange.fetch_time()
        local_time = int(time.time() * 1000)
        drift_ms = abs(local_time - int(server_time)) if server_time is not None else None
        instruments: list[dict[str, Any]] = []
        for symbol in symbols:
            exchange_symbol, market = self._resolve_market(symbol)
            rules = self._rules(exchange_symbol, market)
            ticker = self.exchange.fetch_ticker(exchange_symbol)
            reference_price = ticker.get("mark") or ticker.get("last") or ticker.get("close")
            estimated_minimum_notional = rules.minimum_notional
            if estimated_minimum_notional is None and reference_price is not None:
                multiplier = rules.contract_size if rules.contract_size is not None else 1.0
                estimated_minimum_notional = (
                    rules.minimum_quantity * multiplier * float(reference_price)
                )
            instruments.append(
                {
                    "symbol": symbol,
                    "exchange_symbol": exchange_symbol,
                    "product_type": rules.product_type,
                    "active": bool(market.get("active", True)),
                    "settle_currency": rules.fee_currency,
                    "minimum_quantity": rules.minimum_quantity,
                    "quantity_step": rules.quantity_step,
                    "price_tick": rules.price_tick,
                    "contract_size": rules.contract_size,
                    "minimum_notional": estimated_minimum_notional,
                    "minimum_notional_estimated": rules.minimum_notional is None,
                    "maximum_leverage": rules.maximum_leverage,
                    "reference_price": float(reference_price)
                    if reference_price is not None
                    else None,
                }
            )
        permissions = [
            item.strip() for item in str(account.get("perm") or "").split(",") if item.strip()
        ]
        ip_field_exposed = "ip" in account
        return {
            "environment": "demo",
            "observed_at": datetime.now(UTC).isoformat(),
            "account": {
                "account_level": account.get("acctLv"),
                "position_mode": account.get("posMode"),
                "auto_loan": account.get("autoLoan"),
                "spot_offset_type": account.get("spotOffsetType"),
                "role_type": account.get("roleType"),
                "permissions": permissions,
            },
            "ip_whitelist": {
                "field_exposed": ip_field_exposed,
                "status": (
                    "configured"
                    if ip_field_exposed and bool(account.get("ip"))
                    else "not_configured"
                    if ip_field_exposed
                    else "manual_confirmation_required"
                ),
            },
            "clock": {
                "server_time_available": server_time is not None,
                "absolute_drift_ms": drift_ms,
                "within_tolerance": drift_ms is not None and drift_ms <= 5_000,
                "tolerance_ms": 5_000,
            },
            "instruments": instruments,
        }

    @staticmethod
    def _order(payload: dict[str, Any]) -> ExternalOrder:
        info = payload.get("info") or {}
        client_id = str(payload.get("clientOrderId") or info.get("clOrdId") or "")
        external_id = str(payload.get("id") or info.get("ordId") or "")
        status = (
            payload.get("status")
            or info.get("state")
            or ("submitted" if external_id else "unknown")
        )
        return ExternalOrder(
            external_order_id=external_id,
            client_order_id=client_id,
            status=str(status),
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

    @staticmethod
    def _order_from_okx_info(info: dict[str, Any]) -> ExternalOrder:
        average = info.get("avgPx")
        return ExternalOrder(
            external_order_id=str(info.get("ordId") or ""),
            client_order_id=str(info.get("clOrdId") or ""),
            status=str(info.get("state") or "unknown"),
            filled_quantity=float(info.get("accFillSz") or info.get("fillSz") or 0),
            average_price=float(average) if average not in {None, ""} else None,
            raw={
                "cancel_source": info.get("cancelSource"),
                "cancel_source_reason": info.get("cancelSourceReason"),
                "updated_at": info.get("uTime"),
            },
        )

    def instrument_rules(self, symbol: str) -> InstrumentRules:
        exchange_symbol, market = self._resolve_market(symbol)
        return self._rules(exchange_symbol, market)

    def submit_order(self, request: dict[str, Any]) -> ExternalOrder:
        exchange_symbol, market = self._resolve_market(request["symbol"])
        trade_mode = "cross" if bool(market.get("contract")) else "cash"
        params: dict[str, Any] = {
            "clOrdId": request["client_order_id"],
            "tdMode": trade_mode,
        }
        if request.get("reduce_only"):
            params["reduceOnly"] = True
        if request.get("stop_loss"):
            params["stopLoss"] = {
                "triggerPrice": request["stop_loss"]["trigger_price"],
                "price": request["stop_loss"].get("order_price"),
            }
        if request.get("take_profit"):
            params["takeProfit"] = {
                "triggerPrice": request["take_profit"]["trigger_price"],
                "price": request["take_profit"].get("order_price"),
            }
        payload = self.exchange.create_order(
            exchange_symbol,
            request["order_type"],
            request["side"],
            request["quantity"],
            request.get("price"),
            params,
        )
        order = self._order(payload)
        self._symbols_by_order[order.external_order_id] = exchange_symbol
        return order

    def amend_order(
        self, external_order_id: str, symbol: str, request: dict[str, Any]
    ) -> ExternalOrder:
        exchange_symbol, _ = self._resolve_market(symbol)
        params: dict[str, Any] = {}
        if request.get("stop_loss"):
            params["stopLoss"] = {
                "triggerPrice": request["stop_loss"]["trigger_price"],
                "price": request["stop_loss"].get("order_price"),
            }
        if request.get("take_profit"):
            params["takeProfit"] = {
                "triggerPrice": request["take_profit"]["trigger_price"],
                "price": request["take_profit"].get("order_price"),
            }
        payload = self.exchange.edit_order(
            external_order_id,
            exchange_symbol,
            request["order_type"],
            request["side"],
            request["quantity"],
            request.get("price"),
            params,
        )
        return self._order(payload)

    def _fetch_all_orders(
        self, params: dict[str, Any] | None = None, symbol: str | None = None
    ) -> list[dict[str, Any]]:
        """Read open and closed orders across CCXT implementations.

        OKX does not expose CCXT's generic ``fetch_orders`` endpoint. Keep the
        fallback here so risk snapshots, idempotency recovery, and cancellation
        all use the same provider-compatible order view.
        """
        query = params or {}
        exchange_symbol = self._resolve_market(symbol)[0] if symbol else None
        try:
            return list(self.exchange.fetch_orders(exchange_symbol, None, None, query))
        except Exception as exc:  # noqa: BLE001 - CCXT uses provider-specific NotSupported errors
            if "not supported" not in str(exc).lower():
                raise
        open_orders = list(self.exchange.fetch_open_orders(exchange_symbol, None, None, query))
        try:
            closed_orders = list(
                self.exchange.fetch_closed_orders(exchange_symbol, None, None, query)
            )
        except Exception as exc:  # noqa: BLE001 - CCXT uses provider-specific NotSupported errors
            if "not supported" not in str(exc).lower():
                raise
            closed_orders = []
        seen: set[str] = set()
        merged: list[dict[str, Any]] = []
        for payload in open_orders + closed_orders:
            order_id = str(payload.get("id") or payload.get("info", {}).get("ordId") or "")
            if order_id and order_id in seen:
                continue
            if order_id:
                seen.add(order_id)
            merged.append(payload)
        return merged

    def fetch_order_by_client_id(
        self, client_order_id: str, symbol: str | None = None
    ) -> ExternalOrder | None:
        orders = self._fetch_all_orders({"clOrdId": client_order_id}, symbol)
        for payload in orders:
            order = self._order(payload)
            if order.client_order_id == client_order_id:
                if payload.get("symbol"):
                    self._symbols_by_order[order.external_order_id] = payload["symbol"]
                return order
        if symbol:
            exchange_symbol, market = self._resolve_market(symbol)
            raw = self.exchange.private_get_trade_order(
                {
                    "instId": self._internal_symbol(exchange_symbol, market),
                    "clOrdId": client_order_id,
                }
            )
            for info in raw.get("data") or []:
                if str(info.get("clOrdId") or "") == client_order_id:
                    order = self._order_from_okx_info(info)
                    self._symbols_by_order[order.external_order_id] = exchange_symbol
                    return order
        return None

    def cancel_order(self, external_order_id: str) -> ExternalOrder:
        symbol = self._symbols_by_order.get(external_order_id)
        if symbol is None:
            for payload in self._fetch_all_orders():
                if str(payload.get("id")) == external_order_id:
                    symbol = payload.get("symbol")
                    break
        if not symbol:
            raise LookupError("cannot resolve symbol for external order")
        return self._order(self.exchange.cancel_order(external_order_id, symbol))

    def account_snapshot(self, account_id: str) -> AccountSnapshot:
        raw_orders = self._fetch_all_orders()
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
        positions: dict[str, dict[str, Any]] = {}
        realized_pnl = 0.0
        unrealized_pnl = 0.0
        for position in self.exchange.fetch_positions():
            symbol = self._internal_symbol_for(str(position["symbol"]))
            contracts = float(position.get("contracts") or 0)
            side = str(position.get("side") or "long").lower()
            signed_quantity = -contracts if side == "short" else contracts
            position_unrealized = float(
                position.get("unrealizedPnl") or position.get("unrealized_pnl") or 0
            )
            position_realized = float(
                position.get("realizedPnl") or position.get("realized_pnl") or 0
            )
            positions[symbol] = {
                "quantity": signed_quantity,
                "mark_price": float(position.get("markPrice") or position.get("mark_price") or 0),
                "entry_price": float(
                    position.get("entryPrice") or position.get("entry_price") or 0
                ),
                "unrealized_pnl": position_unrealized,
                "leverage": float(position.get("leverage") or 0),
                "position_side": side,
            }
            unrealized_pnl += position_unrealized
            realized_pnl += position_realized

        account_info = (balance.get("info") or {}).get("data") or []
        account_info = account_info[0] if account_info else {}
        equity_value = account_info.get("totalEq") or account_info.get("equity")
        equity = (
            float(equity_value)
            if equity_value not in {None, ""}
            else sum(values["total"] for values in balances.values())
        )
        account_unrealized = account_info.get("upl")
        if account_unrealized not in {None, ""}:
            unrealized_pnl = float(account_unrealized)
        return AccountSnapshot(
            orders=orders,
            fills=fills,
            balances=balances,
            positions=positions,
            observed_at=datetime.now(UTC),
            realized_pnl=realized_pnl,
            peak_equity=equity,
            unrealized_pnl=unrealized_pnl,
            equity=equity,
        )

    def mark_price(self, symbol: str) -> float:
        exchange_symbol, _ = self._resolve_market(symbol)
        ticker = self.exchange.fetch_ticker(exchange_symbol)
        value = ticker.get("mark") or ticker.get("last") or ticker.get("close")
        if value is None or float(value) <= 0:
            raise RuntimeError(f"no usable mark price for {symbol}")
        return float(value)

    def funding_rate(self, symbol: str) -> dict[str, Any]:
        exchange_symbol, market = self._resolve_market(symbol)
        payload = self.exchange.fetch_funding_rate(exchange_symbol)
        info = payload.get("info") or {}
        rate = payload.get("fundingRate")
        if rate is None:
            rate = info.get("fundingRate")
        if rate is None:
            raise RuntimeError(f"no usable funding rate for {symbol}")
        return {
            "symbol": self._internal_symbol(exchange_symbol, market),
            "exchange_symbol": exchange_symbol,
            "funding_rate": float(rate),
            "funding_timestamp": payload.get("fundingTimestamp") or info.get("fundingTime"),
            "next_funding_timestamp": payload.get("nextFundingTimestamp")
            or info.get("nextFundingTime"),
            "observed_at": datetime.now(UTC).isoformat(),
        }


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
