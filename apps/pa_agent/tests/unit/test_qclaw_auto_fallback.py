"""Tests for QClaw auto-fallback on network errors."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import openai

from pa_agent.config.settings import Settings
from pa_agent.orchestrator.two_stage import TwoStageOrchestrator
from tests.fixtures.validators import schema_test_validator


def test_stream_chat_retries_after_qclaw_fallback() -> None:
    settings = Settings()
    settings.provider.model = "openclaw"
    settings.provider.base_url = "http://127.0.0.1:53555/v1"

    client = MagicMock()
    client.stream_chat.side_effect = [
        openai.APIConnectionError(request=MagicMock(), message="Connection error."),
        MagicMock(content='{"gate_result":"wait"}', reasoning_content="", raw={}, usage=MagicMock(
            prompt_tokens=1, completion_tokens=1, total_tokens=2, cached_prompt_tokens=0
        ), latency_ms=1.0),
    ]

    orchestrator = TwoStageOrchestrator(
        client=client,
        assembler=MagicMock(),
        router=MagicMock(),
        validator=schema_test_validator(),
        pending_writer=MagicMock(),
        exp_reader=MagicMock(),
        settings=settings,
    )

    with patch.object(
        orchestrator,
        "_try_qclaw_fallback",
        return_value=True,
    ) as fallback:
        orchestrator._stream_chat_resilient(
            [{"role": "user", "content": "hi"}],
            on_reasoning_token=None,
            on_content_token=None,
            cancel_token=MagicMock(is_set=MagicMock(return_value=False)),
            thinking=True,
            reasoning_effort="max",
            stage_label="Stage 1",
        )

    fallback.assert_called_once()
    assert client.stream_chat.call_count == 2


def test_stream_chat_does_not_retry_when_qclaw_unavailable() -> None:
    settings = Settings()
    client = MagicMock()
    client.stream_chat.side_effect = openai.APIConnectionError(
        request=MagicMock(),
        message="Connection error.",
    )

    orchestrator = TwoStageOrchestrator(
        client=client,
        assembler=MagicMock(),
        router=MagicMock(),
        validator=schema_test_validator(),
        pending_writer=MagicMock(),
        exp_reader=MagicMock(),
        settings=settings,
    )

    with patch.object(orchestrator, "_try_qclaw_fallback", return_value=False):
        try:
            orchestrator._stream_chat_resilient(
                [{"role": "user", "content": "hi"}],
                on_reasoning_token=None,
                on_content_token=None,
                cancel_token=MagicMock(is_set=MagicMock(return_value=False)),
                thinking=True,
                reasoning_effort="max",
                stage_label="Stage 1",
            )
        except openai.APIConnectionError:
            pass

    assert client.stream_chat.call_count == 1


def test_qclaw_fallback_skipped_for_non_openclaw_model() -> None:
    settings = Settings()
    settings.provider.model = "deepseek-v4-pro"

    orchestrator = TwoStageOrchestrator(
        client=MagicMock(),
        assembler=MagicMock(),
        router=MagicMock(),
        validator=schema_test_validator(),
        pending_writer=MagicMock(),
        exp_reader=MagicMock(),
        settings=settings,
    )

    with patch(
        "pa_agent.ai.qclaw_connector.apply_qclaw_provider_to_settings"
    ) as apply:
        assert not orchestrator._try_qclaw_fallback(original_model="deepseek-v4-pro")
        apply.assert_not_called()
