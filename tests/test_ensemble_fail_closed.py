from __future__ import annotations

from unittest.mock import Mock, patch

import pandas as pd

from apps.api.domains.ensemble import service
from apps.api.domains.ensemble.schemas import EnsembleRequest
from apps.api.domains.signals import service as signal_service
from apps.api.domains.signals.schemas import PublishSignalRequest


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


def _contributor(
    name: str,
    kind: str,
    *,
    available: bool,
    direction: str = "hold",
    confidence: float = 0.0,
    weight: float = 0.3,
) -> dict:
    return {
        "name": name,
        "kind": kind,
        "direction": direction,
        "score": confidence,
        "confidence": confidence,
        "weight": weight,
        "available": available,
        "rationale": "test fixture",
        "metrics": {},
    }


def test_ensemble_fails_closed_when_every_contributor_is_unavailable() -> None:
    source = Mock()
    source.get_kline.return_value = _frame()

    with (
        patch.object(service, "get_data_source", return_value=source),
        patch.object(
            service,
            "_technical_contributor",
            return_value=_contributor("SuperTrend", "technical", available=False),
        ),
        patch.object(
            service,
            "_llm_contributor",
            return_value=_contributor("PA-Agent", "llm", available=False, weight=0.4),
        ),
        patch.object(
            service,
            "_news_contributor",
            return_value=_contributor("News-Sentiment", "news", available=False),
        ),
        patch.object(service, "start_module") as start_module,
        patch.object(service, "complete_module") as complete_module,
        patch.object(service, "fail_module") as fail_module,
        patch.object(
            service.store,
            "get_research_run",
            return_value={
                "id": "run-1",
                "owner_id": "local-user",
                "symbol": "600519",
                "market": "a_shares",
                "timeframe": "1d",
            },
        ),
    ):
        result = service.predict(
            EnsembleRequest(symbol="600519", market="a_shares", research_run_id="run-1")
        )

    assert result["ok"] is False
    assert result["status"] == "unavailable"
    assert result["degraded"] is True
    assert result["execution_eligible"] is False
    assert result["data_source"] == "unknown"
    assert "consensus" not in result
    assert len(result["contributors"]) == 3
    assert all(item["available"] is False for item in result["contributors"])
    assert "所有协同预测贡献者均不可用" in result["error"]
    start_module.assert_not_called()
    complete_module.assert_not_called()
    fail_module.assert_called_once_with("run-1", "ensemble", result["error"])


def test_partial_ensemble_is_explicitly_degraded_and_not_execution_eligible() -> None:
    source = Mock()
    frame = _frame()
    frame.attrs["_source"] = "tencent"
    source.get_kline.return_value = frame
    technical = _contributor(
        "SuperTrend", "technical", available=True, direction="buy", confidence=0.8
    )

    with (
        patch.object(service, "get_data_source", return_value=source),
        patch.object(service, "_technical_contributor", return_value=technical),
        patch.object(
            service,
            "_llm_contributor",
            return_value=_contributor("PA-Agent", "llm", available=False, weight=0.4),
        ),
        patch.object(
            service,
            "_news_contributor",
            return_value=_contributor("News-Sentiment", "news", available=False),
        ),
        patch.object(service, "start_module", return_value="run-2"),
        patch.object(service, "add_evidence") as add_evidence,
        patch.object(service, "complete_module") as complete_module,
    ):
        result = service.predict(EnsembleRequest(symbol="600519", market="a_shares"))

    assert result["ok"] is True
    assert result["status"] == "degraded"
    assert result["degraded"] is True
    assert result["execution_eligible"] is False
    assert result["consensus"]["n"] == 1
    assert any("部分贡献者不可用" in warning for warning in result["warnings"])

    output_payload = next(
        call.kwargs["payload"]
        for call in add_evidence.call_args_list
        if call.kwargs["kind"] == "ensemble_output"
    )
    assert output_payload["status"] == "degraded"
    assert output_payload["execution_eligible"] is False
    summary = complete_module.call_args.args[2]
    assert summary["status"] == "degraded"
    assert summary["execution_eligible"] is False


def test_ensemble_fails_closed_when_research_publication_fails() -> None:
    source = Mock()
    frame = _frame()
    frame.attrs["_source"] = "tencent"
    source.get_kline.return_value = frame
    contributor = _contributor(
        "SuperTrend", "technical", available=True, direction="buy", confidence=0.8
    )

    with (
        patch.object(service, "get_data_source", return_value=source),
        patch.object(service, "_technical_contributor", return_value=contributor),
        patch.object(
            service,
            "_llm_contributor",
            return_value=_contributor("PA-Agent", "llm", available=True, weight=0.4),
        ),
        patch.object(
            service,
            "_news_contributor",
            return_value=_contributor("News-Sentiment", "news", available=True),
        ),
        patch.object(service, "start_module", return_value="run-persist-fail"),
        patch.object(service, "add_evidence", side_effect=RuntimeError("store offline")),
        patch.object(service, "fail_module") as fail_module,
    ):
        result = service.predict(EnsembleRequest(symbol="600519", market="a_shares"))

    assert result["ok"] is False
    assert result["status"] == "unavailable"
    assert result["execution_eligible"] is False
    assert result["published"] is False
    assert "持久化失败" in result["error"]
    fail_module.assert_called_once_with("run-persist-fail", "ensemble", result["error"])


def test_signal_publish_rejects_explicit_non_execution_eligible_ensemble() -> None:
    request = PublishSignalRequest(
        symbol="600519",
        market="a_shares",
        direction="buy",
        confidence=0.8,
        source="ensemble",
        meta={"execution_eligible": False},
    )

    with patch.object(signal_service.instrument_service, "resolve_strict") as resolve:
        try:
            signal_service.publish(request)
        except ValueError as exc:
            assert str(exc).startswith("SIGNAL_EXECUTION_BLOCKED")
        else:  # pragma: no cover - assertion keeps the gate explicit
            raise AssertionError("degraded ensemble signal must be rejected")
    resolve.assert_not_called()


def test_signal_publish_rejects_degraded_or_display_only_ensemble() -> None:
    for marker in ({"degraded": True}, {"display_only": True}, {"execution_eligible": "true"}):
        request = PublishSignalRequest(
            symbol="600519",
            market="a_shares",
            direction="sell",
            confidence=0.8,
            source="ensemble",
            meta=marker,
        )
        with patch.object(signal_service.instrument_service, "resolve_strict") as resolve:
            try:
                signal_service.publish(request)
            except ValueError as exc:
                assert str(exc).startswith("SIGNAL_EXECUTION_BLOCKED")
            else:  # pragma: no cover - assertion keeps the gate explicit
                raise AssertionError(f"marker {marker!r} must be rejected")
        resolve.assert_not_called()
