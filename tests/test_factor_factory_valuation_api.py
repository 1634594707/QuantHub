from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.domains.factor_factory.router import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_valuation_endpoint_maps_unknown_run_to_404() -> None:
    with patch(
        "apps.api.domains.factor_factory.router.value_factor_factory_cohort",
        side_effect=KeyError("自动因子运行不存在"),
    ):
        response = _client().post(
            "/factor-factory/runs/missing/cohort/valuation",
            json={},
        )

    assert response.status_code == 404
    assert "自动因子运行不存在" in response.json()["detail"]


def test_valuation_endpoint_maps_non_okx_run_to_422() -> None:
    with patch(
        "apps.api.domains.factor_factory.router.value_factor_factory_cohort",
        side_effect=ValueError("实时 cohort 估值当前只支持 OKX 公共行情运行"),
    ):
        response = _client().post(
            "/factor-factory/runs/synthetic/cohort/valuation",
            json={},
        )

    assert response.status_code == 422
    assert "只支持 OKX 公共行情" in response.json()["detail"]


def test_valuation_endpoint_maps_stale_quote_to_422() -> None:
    with patch(
        "apps.api.domains.factor_factory.router.value_factor_factory_cohort",
        side_effect=ValueError("公共行情流没有新鲜 ticker/BBO/trade 可用于估值"),
    ):
        response = _client().post(
            "/factor-factory/runs/okx/cohort/valuation",
            json={"stream_id": "BTC-USDT-SWAP:candle1H"},
        )

    assert response.status_code == 422
    assert "没有新鲜" in response.json()["detail"]
