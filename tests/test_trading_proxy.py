"""``/api/trading/*`` 交易代理契约测试。

对应工作包 M1-02 / M1-03 / M1-04 / M1-06 / M3-03 / M4-06 的可自动化部分。

覆盖：
    - 响应外壳字段（status/source/observed_at/freshness/error_code）
    - Runner 不可达、超时、认证失败、404、拒单的错误码映射
    - shadow 环境禁止下单
    - 可交易目录、限价/市价、修改与只减仓平仓服务端强制
    - 幂等透传
    - 凭据永不出现在响应中
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from apps.api.domains.trading import errors
from apps.api.domains.trading.client import RunnerClient, RunnerResponse
from apps.api.domains.trading.config import TradingProxySettings
from apps.api.domains.trading.service import TradingService, set_service
from apps.api.main import app

SECRET_TOKEN = "runner-service-token-should-never-leak"  # noqa: S105 - 测试哨兵值


def make_settings(
    environment: str = "demo",
    *,
    base_url: str = "http://127.0.0.1:8103",
    live_approved: bool = False,
    enforce_scope: bool = True,
) -> TradingProxySettings:
    return TradingProxySettings(
        base_url=base_url,
        auth_token=SECRET_TOKEN,
        timeout_seconds=1.0,
        connect_timeout_seconds=1.0,
        environment=environment,  # type: ignore[arg-type]
        live_approved=live_approved,
        enforce_first_phase_scope=enforce_scope,
    )


class RecordingTransport:
    """可编程的假传输层，记录所有出站调用。"""

    def __init__(self, responses: dict[tuple[str, str], Any]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def __call__(self, method, url, headers, body, timeout):  # noqa: ANN001
        path = url.split("8103", 1)[-1] if "8103" in url else url
        self.calls.append(
            {"method": method, "url": url, "headers": headers, "body": body, "timeout": timeout}
        )
        outcome = self.responses.get((method, path))
        if outcome is None:
            raise AssertionError(f"未预设的 Runner 调用: {method} {path}")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _Timeout(Exception):
    """类名含 Timeout，触发客户端的超时分支。"""


class ConnectionError_(Exception):
    """类名含 Connection，触发客户端的不可达分支。"""


def build_client(
    settings: TradingProxySettings, responses: dict
) -> tuple[TestClient, RecordingTransport]:
    configured_responses = dict(responses)
    if settings.environment == "demo" and ("POST", "/api/orders") in configured_responses:
        configured_responses.setdefault(
            ("GET", "/api/preflight?symbols=BTC-USDT-SWAP"),
            RunnerResponse(200, demo_preflight("BTC-USDT-SWAP")),
        )
    transport = RecordingTransport(configured_responses)
    service = TradingService(settings, RunnerClient(settings, transport))
    set_service(service)
    return TestClient(app), transport


class TradingProxyContractTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_service(None)

    # -- 响应外壳 (M3-03) ---------------------------------------------------

    def test_health_envelope_has_contract_fields(self) -> None:
        client, _ = build_client(
            make_settings(),
            {
                ("GET", "/health"): RunnerResponse(
                    200,
                    {
                        "status": "ok",
                        "product": "okx_runner",
                        "version": "1.0.0",
                        "environment": "demo",
                        "database": "/srv/runner-demo.db",
                    },
                )
            },
        )
        response = client.get("/trading/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        for field in ("status", "source", "observed_at", "freshness", "error_code", "data"):
            self.assertIn(field, body, f"响应外壳缺少 {field}")
        self.assertEqual(body["status"], "ok")
        self.assertEqual(
            body["source"], {"kind": "runner", "name": "okx_runner", "environment": "demo"}
        )
        self.assertTrue(body["data"]["reachable"])
        self.assertEqual(body["data"]["permissions"], "trade")
        self.assertEqual(body["data"]["first_phase_scope"]["product"], "swap")

    def test_health_never_exposes_runner_token_or_database_path(self) -> None:
        client, _ = build_client(
            make_settings(),
            {
                ("GET", "/health"): RunnerResponse(
                    200,
                    {
                        "status": "ok",
                        "product": "okx_runner",
                        "version": "1.0.0",
                        "environment": "demo",
                        "database": "/srv/runner-demo.db",
                    },
                )
            },
        )
        raw = client.get("/trading/health").text
        self.assertNotIn(SECRET_TOKEN, raw)
        self.assertNotIn("/srv/runner-demo.db", raw)

    # -- M1-06 降级 ---------------------------------------------------------

    def test_health_reports_error_status_when_runner_unreachable(self) -> None:
        client, _ = build_client(make_settings(), {("GET", "/health"): ConnectionError_("refused")})
        response = client.get("/trading/health")
        # 健康探针必须保持 200，否则前端只读页面会整页失败
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "error")
        self.assertEqual(body["error_code"], errors.TRADING_RUNNER_UNAVAILABLE)
        self.assertFalse(body["runner"]["reachable"])
        self.assertTrue(body["retryable"])

    def test_health_reports_not_configured_without_base_url(self) -> None:
        client, _ = build_client(make_settings(base_url=""), {})
        body = client.get("/trading/health").json()
        self.assertEqual(body["error_code"], errors.TRADING_NOT_CONFIGURED)
        self.assertFalse(body["runner"]["configured"])
        self.assertFalse(body["runner"]["trading_enabled"])

    # -- 错误码映射 (M1-02 / M4-06) -----------------------------------------

    def test_timeout_maps_to_stable_code_and_warns_against_resubmit(self) -> None:
        client, _ = build_client(
            make_settings(), {("POST", "/api/orders"): _Timeout("read timed out")}
        )
        response = client.post("/trading/orders", json=valid_order())
        self.assertEqual(response.status_code, 504)
        body = response.json()
        for field in ("status", "source", "observed_at", "freshness", "error_code", "data"):
            self.assertIn(field, body, f"错误响应外壳缺少 {field}")
        self.assertEqual(body["status"], "error")
        self.assertEqual(body["source"]["name"], "okx_runner")
        self.assertIsInstance(body["observed_at"], str)
        self.assertFalse(body["freshness"]["expired"])
        self.assertEqual(body["error_code"], errors.TRADING_RUNNER_TIMEOUT)
        self.assertFalse(body["retryable"])
        self.assertIn("不要重复提交", body["hint"])
        self.assertIsNone(body["data"])

    def test_runner_404_maps_to_not_found(self) -> None:
        client, _ = build_client(
            make_settings(),
            {("GET", "/api/orders/missing"): RunnerResponse(404, {"detail": "order not found"})},
        )
        response = client.get("/trading/orders/missing")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error_code"], errors.TRADING_NOT_FOUND)

    def test_runner_400_maps_to_rejected(self) -> None:
        client, _ = build_client(
            make_settings(),
            {("POST", "/api/orders"): RunnerResponse(400, {"detail": "risk rejected"})},
        )
        response = client.post("/trading/orders", json=valid_order())
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error_code"], errors.TRADING_REJECTED)

    def test_runner_401_maps_to_unauthorized(self) -> None:
        client, _ = build_client(
            make_settings(),
            {("GET", "/api/dashboard"): RunnerResponse(401, {"detail": "bad token"})},
        )
        response = client.get("/trading/dashboard")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error_code"], errors.TRADING_RUNNER_UNAUTHORIZED)

    def test_okx_error_code_takes_precedence_over_http_status(self) -> None:
        client, _ = build_client(
            make_settings(),
            {
                ("POST", "/api/orders"): RunnerResponse(
                    400, {"detail": "exchange rejected", "raw": {"code": "51001"}}
                )
            },
        )
        response = client.post("/trading/orders", json=valid_order())
        self.assertEqual(response.json()["error_code"], errors.TRADING_INSTRUMENT_NOT_ALLOWED)

    # -- 环境与范围强制 (P0-05 / 阶段 8 红线) --------------------------------

    def test_shadow_environment_refuses_order_submission(self) -> None:
        client, transport = build_client(make_settings("shadow"), {})
        response = client.post("/trading/orders", json=valid_order())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error_code"], errors.TRADING_ENVIRONMENT_FORBIDDEN)
        self.assertEqual(transport.calls, [], "shadow 环境不得向 Runner 发出任何下单调用")

    def test_live_without_approval_is_refused(self) -> None:
        client, transport = build_client(make_settings("live", live_approved=False), {})
        response = client.post("/trading/orders", json=valid_order())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error_code"], errors.TRADING_LIVE_NOT_APPROVED)
        self.assertEqual(transport.calls, [])

    def test_market_order_is_forwarded_after_dynamic_preflight(self) -> None:
        path = "/api/preflight?symbols=BTC-USDT-SWAP"
        client, transport = build_client(
            make_settings(),
            {
                ("GET", path): RunnerResponse(200, demo_preflight("BTC-USDT-SWAP")),
                ("POST", "/api/orders"): RunnerResponse(
                    200, {"order_id": "market-1", "status": "SUBMITTED"}
                ),
            },
        )
        payload = valid_order() | {"order_type": "market", "price": None}
        response = client.post("/trading/orders", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["order_id"], "market-1")
        self.assertEqual([call["method"] for call in transport.calls], ["GET", "POST"])

    def test_inactive_demo_symbol_is_refused_by_dynamic_preflight(self) -> None:
        path = "/api/preflight?symbols=ETH-USDT-SWAP"
        client, transport = build_client(
            make_settings(),
            {("GET", path): RunnerResponse(200, demo_preflight("ETH-USDT-SWAP", active=False))},
        )
        response = client.post("/trading/orders", json=valid_order() | {"symbol": "ETH-USDT-SWAP"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error_code"], errors.TRADING_INSTRUMENT_NOT_ALLOWED)
        self.assertEqual(len(transport.calls), 1)

    def test_active_demo_nvda_contract_is_allowed(self) -> None:
        symbol = "NVDA-USDT-SWAP"
        path = f"/api/preflight?symbols={symbol}"
        client, transport = build_client(
            make_settings(),
            {
                ("GET", path): RunnerResponse(200, demo_preflight(symbol)),
                ("POST", "/api/orders"): RunnerResponse(
                    200,
                    {"order_id": "nvda-demo-order", "status": "PENDING_SUBMIT"},
                ),
            },
        )

        response = client.post("/trading/orders", json=valid_order() | {"symbol": symbol})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["order_id"], "nvda-demo-order")
        self.assertEqual([call["method"] for call in transport.calls], ["GET", "POST"])

    def test_demo_rejects_spot_or_non_usdt_contracts(self) -> None:
        cases = [
            ("BTC-USDT", "spot", "USDT"),
            ("BTC-USD-SWAP", "swap", "USD"),
        ]
        for symbol, product_type, settle_currency in cases:
            with self.subTest(symbol=symbol):
                path = f"/api/preflight?symbols={symbol}"
                client, transport = build_client(
                    make_settings(),
                    {
                        ("GET", path): RunnerResponse(
                            200,
                            demo_preflight(
                                symbol,
                                product_type=product_type,
                                settle_currency=settle_currency,
                            ),
                        )
                    },
                )

                response = client.post(
                    "/trading/orders",
                    json=valid_order() | {"symbol": symbol},
                )

                self.assertEqual(response.status_code, 422)
                self.assertEqual(
                    response.json()["error_code"],
                    errors.TRADING_INSTRUMENT_NOT_ALLOWED,
                )
                self.assertEqual(len(transport.calls), 1)

    def test_live_environment_keeps_static_btc_allowlist(self) -> None:
        client, transport = build_client(make_settings("live", live_approved=True), {})

        response = client.post(
            "/trading/orders",
            json=valid_order() | {"symbol": "NVDA-USDT-SWAP"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error_code"], errors.TRADING_INSTRUMENT_NOT_ALLOWED)
        self.assertEqual(transport.calls, [])

    def test_limit_order_without_price_is_refused(self) -> None:
        client, transport = build_client(make_settings(), {})
        response = client.post("/trading/orders", json=valid_order() | {"price": None})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error_code"], errors.TRADING_REJECTED)
        self.assertEqual(transport.calls, [])

    def test_amend_order_forwards_structured_protection(self) -> None:
        path = "/api/orders/order-1/amend"
        client, transport = build_client(
            make_settings(),
            {("POST", path): RunnerResponse(200, {"order_id": "order-1", "status": "SUBMITTED"})},
        )
        response = client.post(
            "/trading/orders/order-1/amend",
            json={
                "quantity": 0.02,
                "price": 51000,
                "stop_loss": {"trigger_price": 49000},
                "take_profit": {"trigger_price": 55000},
            },
        )
        self.assertEqual(response.status_code, 200)
        sent = json.loads(transport.calls[0]["body"])
        self.assertEqual(sent["stop_loss"]["trigger_price"], 49000.0)
        self.assertEqual(sent["take_profit"]["trigger_price"], 55000.0)

    def test_demo_quick_close_uses_dynamic_instrument_validation(self) -> None:
        symbol = "ETH-USDT-SWAP"
        preflight_path = f"/api/preflight?symbols={symbol}"
        close_path = f"/api/positions/acc-1/{symbol}/close"
        client, transport = build_client(
            make_settings(),
            {
                ("GET", preflight_path): RunnerResponse(200, demo_preflight(symbol)),
                ("POST", close_path): RunnerResponse(
                    200, {"order_id": "close-1", "status": "SUBMITTED"}
                ),
            },
        )
        response = client.post(
            f"/trading/positions/acc-1/{symbol}/close",
            json={
                "strategy_id": "demo-strategy",
                "strategy_version": "1.0.0",
                "intent_id": "close-intent",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([call["method"] for call in transport.calls], ["GET", "POST"])

    def test_live_quick_close_uses_static_allowlist_without_demo_preflight(self) -> None:
        path = "/api/positions/acc-1/BTC-USDT-SWAP/close"
        client, transport = build_client(
            make_settings("live", live_approved=True),
            {
                ("POST", path): RunnerResponse(
                    200, {"order_id": "close-live-1", "status": "SUBMITTED"}
                )
            },
        )
        response = client.post(
            "/trading/positions/acc-1/BTC-USDT-SWAP/close",
            json={
                "strategy_id": "demo-strategy",
                "strategy_version": "1.0.0",
                "intent_id": "close-live-intent",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(transport.calls[0]["method"], "POST")

    # -- 正常链路 -----------------------------------------------------------

    def test_successful_order_forwards_intent_and_marks_idempotent_replay(self) -> None:
        runner_payload = {
            "order_id": "order-abc",
            "client_order_id": "cid-1",
            "status": "PENDING_SUBMIT",
            "idempotent_replay": True,
            "updated_at": "2026-08-09T05:00:00+00:00",
        }
        client, transport = build_client(
            make_settings(), {("POST", "/api/orders"): RunnerResponse(200, runner_payload)}
        )
        response = client.post("/trading/orders", json=valid_order())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["data"]["idempotent_replay"])

        self.assertEqual(len(transport.calls), 2)
        sent = transport.calls[-1]
        self.assertEqual(sent["method"], "POST")
        self.assertIn("/api/orders", sent["url"])
        # 服务令牌走 Header，不出现在 body
        self.assertEqual(sent["headers"]["Authorization"], f"Bearer {SECRET_TOKEN}")
        self.assertNotIn(SECRET_TOKEN.encode(), sent["body"])

    def test_account_uses_runner_snapshot_time_for_freshness(self) -> None:
        client, _ = build_client(
            make_settings(),
            {
                ("GET", "/api/accounts/acc-1"): RunnerResponse(
                    200,
                    {
                        "account_id": "acc-1",
                        "latest_snapshot_at": "2020-01-01T00:00:00+00:00",
                        "balances": [{"currency": "USDT", "total": 10, "available": 10}],
                        "positions": [],
                        "orders": [],
                    },
                )
            },
        )
        body = client.get("/trading/accounts/acc-1").json()
        # 2020 年的快照必然超过 60 秒 TTL，应判定为 stale 而不是 ok
        self.assertEqual(body["status"], "stale")
        self.assertTrue(body["freshness"]["expired"])
        self.assertGreater(body["freshness"]["age_seconds"], 60)

    def test_preflight_proxies_only_the_server_allowed_symbols(self) -> None:
        payload = {
            "environment": "demo",
            "observed_at": datetime.now(UTC).isoformat(),
            "account": {
                "account_level": "2",
                "position_mode": "net_mode",
                "permissions": ["read_only", "trade"],
            },
            "ip_whitelist": {
                "field_exposed": False,
                "status": "manual_confirmation_required",
            },
            "clock": {"absolute_drift_ms": 398, "within_tolerance": True},
            "instruments": [{"symbol": "BTC-USDT-SWAP", "active": True}],
        }
        path = "/api/preflight?symbols=BTC-USDT-SWAP"
        client, transport = build_client(
            make_settings(), {("GET", path): RunnerResponse(200, payload)}
        )

        response = client.get("/trading/preflight")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["data"]["account"]["position_mode"], "net_mode")
        self.assertEqual(body["data"]["instruments"][0]["symbol"], "BTC-USDT-SWAP")
        self.assertEqual(transport.calls[0]["url"].split("8103", 1)[-1], path)

    def test_preflight_accepts_a_requested_demo_contract(self) -> None:
        symbol = "NVDA-USDT-SWAP"
        path = f"/api/preflight?symbols={symbol}"
        client, transport = build_client(
            make_settings(),
            {("GET", path): RunnerResponse(200, demo_preflight(symbol))},
        )

        response = client.get(f"/trading/preflight?symbols={symbol}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["instruments"][0]["symbol"], symbol)
        self.assertEqual(transport.calls[0]["url"].split("8103", 1)[-1], path)

    def test_shadow_preflight_is_rejected_before_calling_runner(self) -> None:
        client, transport = build_client(make_settings("shadow"), {})

        response = client.get("/trading/preflight")

        self.assertEqual(response.status_code, 403)
        body = response.json()
        self.assertEqual(body["error_code"], errors.TRADING_ENVIRONMENT_FORBIDDEN)
        self.assertIn("demo", body["hint"])
        self.assertEqual(transport.calls, [])

    def test_risk_mode_is_proxied_with_operator_and_reason(self) -> None:
        client, transport = build_client(
            make_settings(),
            {
                ("POST", "/api/risk/mode"): RunnerResponse(
                    200, {"scope": "global", "mode": "halted"}
                )
            },
        )
        response = client.post(
            "/trading/risk/mode",
            json={
                "scope": "global",
                "mode": "halted",
                "reason": "对账差异未关闭",
                "operator": "aplicity",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["mode"], "halted")
        self.assertIn(b"aplicity", transport.calls[0]["body"])

    def test_recovery_is_allowed_in_shadow_for_link_validation(self) -> None:
        client, _ = build_client(
            make_settings("shadow"),
            {("POST", "/api/recovery/orders"): RunnerResponse(200, [])},
        )
        body = client.post("/trading/recovery/orders").json()
        # 空列表应表达为 empty，而不是伪造成 ok
        self.assertEqual(body["status"], "empty")
        self.assertEqual(body["data"], [])


class RedactionTests(unittest.TestCase):
    def test_redact_masks_sensitive_assignments(self) -> None:
        self.assertEqual(errors.redact("api_key=abc123 failed"), "api_key=*** failed")
        self.assertEqual(errors.redact("passphrase: hunter2"), "passphrase=***")

    def test_redact_mapping_masks_nested_keys(self) -> None:
        payload = {
            "ok": True,
            "credentials": {"apiKey": "k", "secret": "s", "passphrase": "p"},
            "orders": [{"id": "1", "signature": "sig"}],
        }
        clean = errors.redact_mapping(payload)
        self.assertEqual(
            clean["credentials"], {"apiKey": "***", "secret": "***", "passphrase": "***"}
        )
        self.assertEqual(clean["orders"][0]["signature"], "***")
        self.assertTrue(clean["ok"])

    def test_unknown_okx_code_falls_back_without_guessing(self) -> None:
        self.assertEqual(errors.from_okx_code("99999"), errors.TRADING_UPSTREAM_ERROR)
        self.assertEqual(errors.from_okx_code(None), errors.TRADING_UPSTREAM_ERROR)


def valid_order() -> dict:
    return {
        "strategy_id": "demo-strategy",
        "strategy_version": "1.0.0",
        "intent_id": "intent-0001",
        "account_id": "acc-1",
        "symbol": "BTC-USDT-SWAP",
        "side": "buy",
        "order_type": "limit",
        "quantity": 0.01,
        "price": 50000.0,
        "leverage": 1,
    }


def demo_preflight(
    symbol: str,
    *,
    active: bool = True,
    product_type: str = "swap",
    settle_currency: str = "USDT",
) -> dict[str, Any]:
    return {
        "environment": "demo",
        "observed_at": datetime.now(UTC).isoformat(),
        "account": {"permissions": ["read_only", "trade"]},
        "clock": {"within_tolerance": True},
        "instruments": [
            {
                "symbol": symbol,
                "active": active,
                "product_type": product_type,
                "settle_currency": settle_currency,
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
