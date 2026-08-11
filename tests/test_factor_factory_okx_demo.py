from __future__ import annotations

from typing import Any

import pytest

from apps.api.domains.factor_factory.okx_demo import (
    activate_demo_strategy,
    build_demo_release_package,
    refresh_demo_evidence,
)
from apps.api.domains.factor_factory.schemas import FactorFactoryStartRequest
from packages.strategy_package import signing_key_from_env, verify_release_package


def _envelope(data: Any) -> dict[str, Any]:
    return {"status": "ok", "data": data}


class FakeTradingService:
    def __init__(self, *, risk_mode: str = "normal", symbol: str = "BTC-USDT-SWAP") -> None:
        self.risk_mode = risk_mode
        self.symbol = symbol
        self.submissions: list[Any] = []

    def import_demo_strategy(self, package: dict[str, Any]) -> dict[str, Any]:
        return _envelope(
            {
                "strategy_id": package["payload"]["strategy_id"],
                "version": package["payload"]["version"],
                "content_hash": package["content_sha256"],
            }
        )

    def preflight(self, symbols: list[str] | None = None) -> dict[str, Any]:
        assert symbols == [self.symbol]
        return _envelope(
            {
                "account": {"permissions": ["read_only", "trade"]},
                "clock": {"within_tolerance": True},
                "instruments": [
                    {
                        "symbol": self.symbol,
                        "active": True,
                        "product_type": "swap",
                        "settle_currency": "USDT",
                        "minimum_quantity": 0.01,
                        "quantity_step": 0.01,
                        "price_tick": 0.1,
                        "contract_size": 0.01,
                    }
                ],
            }
        )

    def reconcile(self, account_id: str) -> dict[str, Any]:
        assert account_id == "demo"
        return _envelope({"account_id": account_id, "passed": True, "difference_ids": []})

    def dashboard(self) -> dict[str, Any]:
        order = self._order_record() if self.submissions else None
        return _envelope(
            {
                "orders": [order] if order else [],
                "fills": [],
                "account_summary": {
                    "accounts": [
                        {
                            "account_id": "demo",
                            "equity": 10_000.0,
                            "initial_equity": 10_000.0,
                            "max_drawdown": -0.01,
                        }
                    ]
                },
                "reconciliation_diffs": [],
                "risk_states": [{"scope": "global", "mode": self.risk_mode, "reason": "test"}],
                "account_status": {"environment": "demo", "stale": False},
            }
        )

    def submit_order(self, request: Any) -> dict[str, Any]:
        self.submissions.append(request)
        return _envelope(self._order_record())

    def recover_orders(self) -> dict[str, Any]:
        return _envelope([])

    def funding_rate(self, symbol: str) -> dict[str, Any]:
        assert symbol == self.symbol
        return _envelope(
            {
                "symbol": symbol,
                "funding_rate": 0.0001,
                "observed_at": "2026-08-11T00:00:00+00:00",
            }
        )

    def _order_record(self) -> dict[str, Any]:
        request = self.submissions[-1] if self.submissions else None
        return {
            "order_id": "order-demo-1",
            "strategy_id": request.strategy_id if request else "factor-factory-run",
            "strategy_version": request.strategy_version if request else "1.0.0",
            "account_id": "demo",
            "status": "FILLED",
            "quantity": request.quantity if request else 0.02,
            "filled_quantity": request.quantity if request else 0.02,
        }


def _package(monkeypatch, symbol: str = "BTC-USDT-SWAP"):
    monkeypatch.delenv("QH_RUNNER_SIGNING_KEY", raising=False)
    request = FactorFactoryStartRequest(
        source="okx_live",
        symbol=symbol,
        interval="4h",
        paper_target="okx_demo",
    )
    package = build_demo_release_package(
        run_id="a" * 32,
        research_plan_id="plan-1",
        experiment_id="experiment-1",
        definition={
            "key": "factor-key",
            "version": "1.0.0",
            "ast": {
                "op": "pct_change",
                "value": {"op": "field", "name": "close"},
                "periods": 20,
            },
        },
        confirmation_summary={
            "total_return": 0.05,
            "max_drawdown": -0.08,
            "rank_ic": 0.1,
            "metrics": {"sharpe": 1.2},
        },
        data_fingerprint="b" * 64,
        req=request,
    )
    return request, package


def test_demo_request_rejects_non_live_or_daily_context() -> None:
    with pytest.raises(ValueError, match="okx_live"):
        FactorFactoryStartRequest(source="okx_local", paper_target="okx_demo")
    with pytest.raises(ValueError, match="1h 或 4h"):
        FactorFactoryStartRequest(
            source="okx_live",
            symbol="BTC-USDT-SWAP",
            interval="1d",
            paper_target="okx_demo",
        )
    with pytest.raises(ValueError):
        FactorFactoryStartRequest(
            source="okx_live",
            symbol="BTC-USDT-SWAP",
            interval="4h",
            paper_target="okx_demo",
            observation_days=6,
        )


def test_demo_request_normalizes_screenshot_style_nvda_symbol() -> None:
    request = FactorFactoryStartRequest(
        source="okx_live",
        symbol="NVDAUSDT",
        interval="4h",
        paper_target="okx_demo",
    )

    assert request.symbol == "NVDA-USDT-SWAP"


def test_a_share_research_uses_akshare_and_local_paper() -> None:
    request = FactorFactoryStartRequest(
        market="a_shares",
        source="akshare_live",
        symbol="600519",
        interval="1d",
        paper_target="simulation_orders",
        candidate_mode="manual",
        candidate_budget=1,
        manual_candidates=[{"expression": "rolling_zscore(pct_change(close, 5), 20)"}],
    )

    assert request.market == "a_shares"
    assert request.source == "akshare_live"
    assert request.symbol == "600519"


def test_release_package_is_signed_and_demo_only(monkeypatch) -> None:
    request, package = _package(monkeypatch)

    verified = verify_release_package(
        package,
        signing_key_from_env(),
        runner_version="1.0.0",
        environment="demo",
    )

    assert verified.allowed_environments == ("demo",)
    assert verified.signal_frequency == request.interval
    assert verified.risk_limits.kill_switch_required is True
    assert verified.parameters["factor_ast"]["op"] == "pct_change"


def test_demo_activation_maps_position_and_uses_stable_intent(monkeypatch) -> None:
    _request_value, package = _package(monkeypatch)
    trading = FakeTradingService()

    activated = activate_demo_strategy(
        package=package,
        run_id="a" * 32,
        market_time="2026-08-11T00:00:00+00:00",
        signal=0.2,
        price=50_000,
        trading=trading,
    )

    assert activated["status"] == "submitted"
    assert activated["target_exposure"] == 0.1
    assert activated["target_quantity"] == 2.0
    assert activated["limit_price"] == 50_025.0
    request = trading.submissions[0]
    assert request.order_type == "limit"
    assert request.quantity == 2.0
    assert request.intent_id.startswith("ff-")
    assert activated["baseline_account_equity"] == 10_000.0


def test_demo_activation_stops_before_submit_when_risk_mode_blocks(monkeypatch) -> None:
    _request_value, package = _package(monkeypatch)
    trading = FakeTradingService(risk_mode="cancel_only")

    activated = activate_demo_strategy(
        package=package,
        run_id="a" * 32,
        market_time="2026-08-11T00:00:00+00:00",
        signal=0.2,
        price=50_000,
        trading=trading,
    )

    assert activated["status"] == "blocked"
    assert activated["readiness"]["checks"]["risk_mode_normal"] is False
    assert trading.submissions == []


def test_refresh_demo_evidence_records_orders_reconciliation_and_funding(monkeypatch) -> None:
    _request_value, package = _package(monkeypatch)
    trading = FakeTradingService()
    activate_demo_strategy(
        package=package,
        run_id="a" * 32,
        market_time="2026-08-11T00:00:00+00:00",
        signal=0.2,
        price=50_000,
        trading=trading,
    )

    evidence = refresh_demo_evidence(
        strategy_id=package.payload.strategy_id,
        strategy_version=package.payload.version,
        symbol=package.payload.universe["symbols"][0],
        trading=trading,
    )

    assert evidence["order_count"] == 1
    assert evidence["fill_rate"] == 1.0
    assert evidence["reconciliation_clear"] is True
    assert evidence["risk_mode_normal"] is True
    assert evidence["funding_rate"]["funding_rate"] == 0.0001


def test_nvda_demo_uses_selected_symbol_for_preflight_order_and_funding(monkeypatch) -> None:
    request, package = _package(monkeypatch, "NVDAUSDT")
    trading = FakeTradingService(symbol=request.symbol)

    activated = activate_demo_strategy(
        package=package,
        run_id="a" * 32,
        market_time="2026-08-11T00:00:00+00:00",
        signal=0.1,
        price=200.0,
        trading=trading,
    )
    evidence = refresh_demo_evidence(
        strategy_id=package.payload.strategy_id,
        strategy_version=package.payload.version,
        symbol=request.symbol,
        trading=trading,
    )

    assert activated["status"] == "submitted"
    assert trading.submissions[0].symbol == "NVDA-USDT-SWAP"
    assert evidence["symbol"] == "NVDA-USDT-SWAP"
    assert evidence["funding_rate"]["symbol"] == "NVDA-USDT-SWAP"
