"""apps.api 统一网关集成测试（TestClient，不依赖网络/模型）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["strategies"] == 11  # 11 个已注册策略
    assert "version" in body


def test_list_strategies(client):
    r = client.get("/strategies")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 11
    names = {s["name"] for s in body["strategies"]}
    assert {"sentiment", "realtime_analyzer", "alphamaster", "pa_agent"} <= names


def test_unknown_strategy_404(client):
    r = client.get("/strategies/does_not_exist")
    assert r.status_code == 404
    r2 = client.post("/strategies/does_not_exist/run", json={"params": {}})
    assert r2.status_code == 404


def test_run_realtime_analyzer_offline(client):
    """离线（无网络/LLM）下实时分析器降级为快照，网关应返回 200 + 结构化结果。"""
    r = client.post("/strategies/realtime_analyzer/run", json={"params": {"codes": ["600519"]}})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "realtime_analyzer"
    assert isinstance(body["signals"], list)
    # 离线降级也应产出至少一条快照信号
    assert body["count"] >= 1
    sig = body["signals"][0]
    assert sig["source"] == "realtime_analyzer"
    assert "report" in sig["meta"]


def test_signal_publish_and_read(client):
    r = client.post(
        "/signals/publish",
        json={
            "symbol": "BTC",
            "market": "crypto",
            "direction": "buy",
            "score": 0.9,
            "confidence": 0.7,
            "source": "api_test",
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r2 = client.get("/signals", params={"limit": 50})
    assert r2.status_code == 200
    sigs = r2.json()["signals"]
    assert any(s["source"] == "api_test" and s["symbol"] == "BTC" for s in sigs)
