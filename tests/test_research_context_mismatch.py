from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

from apps.api import database, store
from apps.api.domains.ensemble import service as ensemble_service
from apps.api.domains.ensemble.schemas import EnsembleRequest
from apps.api.domains.news import service as news_service
from apps.api.domains.strategies import service as strategies_service


def setup_function() -> None:
    global _ORIGINAL_DB, _TEMP_DIR
    _ORIGINAL_DB = store._DB
    _TEMP_DIR = Path(tempfile.mkdtemp(prefix="quanthub-context-mismatch-"))
    database.dispose_engines()
    store._DB = _TEMP_DIR / "store.db"
    store._init()


def teardown_function() -> None:
    database.dispose_engines()
    store._DB = _ORIGINAL_DB
    shutil.rmtree(_TEMP_DIR, ignore_errors=True)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "datetime": pd.date_range("2026-01-01", periods=4, freq="D"),
            "open": [100.0, 101.0, 102.0, 103.0],
            "high": [101.0, 102.0, 103.0, 104.0],
            "low": [99.0, 100.0, 101.0, 102.0],
            "close": [100.5, 101.5, 102.5, 103.5],
            "volume": [10.0, 11.0, 12.0, 13.0],
        }
    )


def _run_id() -> str:
    run = store.create_research_run(
        symbol="600519",
        market="a_shares",
        timeframe="1d",
        modules=["seed"],
        input_data={},
    )
    return str(run["id"])


def test_news_context_mismatch_returns_failure_without_creating_replacement_run() -> None:
    run_id = _run_id()
    source = Mock()
    source.get_news.return_value = [SimpleNamespace(title="news")]
    analyzer = Mock()
    batch = Mock(
        total=1,
        engine="semantic+api",
        model="test",
        degraded_reason=None,
        items=[],
    )
    analyzer.analyze_batch.return_value = batch

    with (
        patch.object(news_service, "get_data_source", return_value=source),
        patch.object(news_service.NewsAnalyzer, "from_config", return_value=analyzer),
    ):
        result = news_service.analyze(
            symbol="AAPL",
            market="us_stocks",
            timeframe="1d",
            research_run_id=run_id,
        )

    assert result["ok"] is False
    assert "研究上下文不一致" in result["error"]
    assert result["research_run_id"] == run_id
    assert len(store.list_research_runs(limit=10)) == 1


def test_ensemble_context_mismatch_returns_failure_without_creating_replacement_run() -> None:
    run_id = _run_id()
    source = Mock()
    source.get_kline.return_value = _frame()

    with patch.object(ensemble_service, "get_data_source", return_value=source):
        result = ensemble_service.predict(
            EnsembleRequest(
                symbol="AAPL",
                market="us_stocks",
                timeframe="1d",
                research_run_id=run_id,
            )
        )

    assert result["ok"] is False
    assert "研究上下文不一致" in result["error"]
    assert result["research_run_id"] == run_id
    assert len(store.list_research_runs(limit=10)) == 1


def test_pa_context_mismatch_returns_failure_without_creating_replacement_run() -> None:
    run_id = _run_id()
    source = Mock()
    source.get_kline.return_value = _frame()
    analysis = SimpleNamespace(
        error=None,
        stage1_json={"gate_result": "proceed", "gate_trace": []},
        stage2_json={"decision": {}, "terminal": {}, "decision_trace": []},
        usage={},
        validation={},
    )

    with (
        patch.object(strategies_service, "get_data_source", return_value=source),
        patch.object(strategies_service, "run_two_stage", return_value=analysis),
        patch.object(strategies_service, "build_decision_view", return_value={}),
        patch.object(strategies_service, "build_future_trend_view", return_value={}),
        patch.object(strategies_service, "build_decision_tree_view", return_value={}),
    ):
        result = strategies_service.pa_analyze(
            symbol="AAPL",
            market="us_stocks",
            timeframe="1d",
            research_run_id=run_id,
        )

    assert result["ok"] is False
    assert "研究上下文不一致" in result["error"]
    assert result["research_run_id"] == run_id
    assert len(store.list_research_runs(limit=10)) == 1
