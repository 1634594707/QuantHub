"""The retired Demo surface is history-only and cannot create new runs."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from apps.api.domains.simulation import service as simulation_service
from apps.api.main import app


def test_demo_run_writer_routes_and_service_are_removed() -> None:
    paths = app.openapi()["paths"]

    assert "/simulation/demo/run" not in paths
    assert "/simulation/demo/presets" not in paths
    assert not hasattr(simulation_service, "run_demo")


def test_historical_demo_records_remain_available_read_only(tmp_path, monkeypatch) -> None:
    (tmp_path / "legacy1.json").write_text(
        json.dumps(
            {
                "run_id": "legacy1",
                "created_at": "2026-01-01T00:00:00+00:00",
                "config": {"symbol": "BTC-USDT"},
                "summary": {"total_return": 0.1},
                "data_provenance": {"source": "historical"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(simulation_service, "DEMO_RUNS_DIR", tmp_path)

    with TestClient(app) as client:
        listing = client.get("/simulation/demo/runs")
        detail = client.get("/simulation/demo/runs/legacy1")
        retired_write = client.post("/simulation/demo/run", json={})

    assert listing.status_code == 200
    assert listing.json()["runs"][0]["run_id"] == "legacy1"
    assert detail.status_code == 200
    assert detail.json()["run"]["run_id"] == "legacy1"
    assert retired_write.status_code == 404
