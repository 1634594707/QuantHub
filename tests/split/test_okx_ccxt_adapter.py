from __future__ import annotations

import json
import time
import unittest

from apps.okx_runner.okx_adapter import OkxCcxtAdapter


class FakeExchange:
    def __init__(self) -> None:
        self.created = None
        self.order = {
            "id": "external-1",
            "clientOrderId": "client-1",
            "symbol": "BTC/USDT:USDT",
            "status": "open",
            "filled": 0,
            "average": None,
            "timestamp": 1_700_000_000_000,
            "info": {},
        }

    def load_markets(self):
        return {
            "BTC/USDT:USDT": {
                "id": "BTC-USDT-SWAP",
                "info": {"instId": "BTC-USDT-SWAP"},
                "type": "swap",
                "contract": True,
                "contractSize": 0.01,
                "active": True,
                "precision": {"amount": 0.01, "price": 0.1},
                "limits": {"amount": {"min": 0.01}, "leverage": {"max": 5}},
                "settle": "USDT",
                "quote": "USDT",
            }
        }

    def private_get_account_config(self):
        return {
            "data": [
                {
                    "acctLv": "2",
                    "posMode": "net_mode",
                    "autoLoan": False,
                    "roleType": "0",
                    "perm": "read_only,trade",
                    "uid": "must-not-leak",
                }
            ]
        }

    def fetch_time(self):
        return int(time.time() * 1000)

    def fetch_ticker(self, symbol):
        self.last_ticker_symbol = symbol
        return {"mark": 60000}

    def create_order(self, *args):
        self.created = args
        payload = dict(self.order)
        payload["clientOrderId"] = args[5]["clOrdId"]
        return payload

    def fetch_orders(self, *args):
        return [self.order]

    def cancel_order(self, order_id, symbol):
        return dict(self.order, status="canceled")

    def fetch_my_trades(self):
        return [
            {
                "id": "fill-1",
                "order": "external-1",
                "amount": 0.01,
                "price": 60000,
                "timestamp": 1_700_000_001_000,
                "fee": {"cost": 0.1, "currency": "USDT"},
            }
        ]

    def fetch_balance(self):
        return {"total": {"USDT": 1000}, "free": {"USDT": 900}}

    def fetch_positions(self):
        return [{"symbol": "BTC-USDT-SWAP", "contracts": 0.01, "markPrice": 60000}]


class FetchOrdersUnsupportedExchange(FakeExchange):
    def __init__(self) -> None:
        super().__init__()
        self.open_orders_args = None
        self.closed_orders_args = None

    def fetch_orders(self, *args):
        raise RuntimeError("okx fetchOrders() is not supported yet")

    def fetch_open_orders(self, *args):
        self.open_orders_args = args
        return []

    def fetch_closed_orders(self, *args):
        self.closed_orders_args = args
        return []

    def private_get_trade_order(self, params):
        return {
            "code": "0",
            "data": [
                {
                    "ordId": "external-1",
                    "clOrdId": params["clOrdId"],
                    "instId": params["instId"],
                    "state": "canceled",
                    "accFillSz": "0",
                    "avgPx": "",
                    "cancelSource": "1",
                    "cancelSourceReason": "Order was canceled by you.",
                    "uTime": "1700000000000",
                }
            ],
        }


class OkxCcxtAdapterTests(unittest.TestCase):
    def test_adapter_maps_rules_orders_fills_balances_and_positions(self) -> None:
        exchange = FakeExchange()
        adapter = OkxCcxtAdapter(exchange)
        rules = adapter.instrument_rules("BTC-USDT-SWAP")
        self.assertEqual(rules.quantity_step, 0.01)
        order = adapter.submit_order(
            {
                "symbol": "BTC-USDT-SWAP",
                "order_type": "limit",
                "side": "buy",
                "quantity": 0.1,
                "price": 60000,
                "client_order_id": "client-new",
            }
        )
        self.assertEqual(order.client_order_id, "client-new")
        self.assertEqual(exchange.created[0], "BTC/USDT:USDT")
        self.assertEqual(exchange.created[5], {"clOrdId": "client-new", "tdMode": "cross"})
        snapshot = adapter.account_snapshot("account")
        self.assertEqual(snapshot.fills[0].fee_currency, "USDT")
        self.assertEqual(snapshot.balances["USDT"]["available"], 900)
        self.assertEqual(snapshot.positions["BTC-USDT-SWAP"]["quantity"], 0.01)

    def test_preflight_is_safe_and_uses_real_ccxt_market_keys(self) -> None:
        exchange = FakeExchange()
        result = OkxCcxtAdapter(exchange).preflight(["BTC-USDT-SWAP"])

        self.assertEqual(result["account"]["account_level"], "2")
        self.assertEqual(result["account"]["position_mode"], "net_mode")
        self.assertEqual(result["account"]["permissions"], ["read_only", "trade"])
        self.assertEqual(result["ip_whitelist"]["status"], "manual_confirmation_required")
        self.assertTrue(result["clock"]["within_tolerance"])
        instrument = result["instruments"][0]
        self.assertEqual(instrument["symbol"], "BTC-USDT-SWAP")
        self.assertEqual(instrument["exchange_symbol"], "BTC/USDT:USDT")
        self.assertEqual(instrument["minimum_quantity"], 0.01)
        self.assertEqual(instrument["minimum_notional"], 6.0)
        self.assertTrue(instrument["minimum_notional_estimated"])
        self.assertNotIn("must-not-leak", json.dumps(result))

    def test_order_recovery_falls_back_to_symbol_scoped_closed_orders(self) -> None:
        exchange = FetchOrdersUnsupportedExchange()
        order = OkxCcxtAdapter(exchange).fetch_order_by_client_id("client-1", "BTC-USDT-SWAP")

        self.assertIsNotNone(order)
        assert order is not None
        self.assertEqual(order.status, "canceled")
        self.assertEqual(exchange.open_orders_args[0], "BTC/USDT:USDT")
        self.assertEqual(exchange.closed_orders_args[0], "BTC/USDT:USDT")
        self.assertEqual(exchange.closed_orders_args[3], {"clOrdId": "client-1"})


if __name__ == "__main__":
    unittest.main()
