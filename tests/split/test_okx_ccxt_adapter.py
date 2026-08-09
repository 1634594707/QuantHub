from __future__ import annotations

import unittest

from apps.okx_runner.okx_adapter import OkxCcxtAdapter


class FakeExchange:
    def __init__(self) -> None:
        self.created = None
        self.order = {
            "id": "external-1",
            "clientOrderId": "client-1",
            "symbol": "BTC-USDT-SWAP",
            "status": "open",
            "filled": 0,
            "average": None,
            "timestamp": 1_700_000_000_000,
            "info": {},
        }

    def load_markets(self):
        return {
            "BTC-USDT-SWAP": {
                "precision": {"amount": 0.01, "price": 0.1},
                "limits": {"amount": {"min": 0.01}, "leverage": {"max": 5}},
                "settle": "USDT",
            }
        }

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
        self.assertEqual(exchange.created[5], {"clOrdId": "client-new"})
        snapshot = adapter.account_snapshot("account")
        self.assertEqual(snapshot.fills[0].fee_currency, "USDT")
        self.assertEqual(snapshot.balances["USDT"]["available"], 900)
        self.assertEqual(snapshot.positions["BTC-USDT-SWAP"]["quantity"], 0.01)


if __name__ == "__main__":
    unittest.main()
