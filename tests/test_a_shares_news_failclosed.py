from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from apps.api.domains.ensemble import service as ensemble_service
from apps.api.domains.news import service as news_service
from apps.api.domains.news.schemas import NewsAnalyzeRequest
from core.data_feed import News
from strategies.a_shares.news_analyzer.analyzer import NewsAnalyzer
from strategies.a_shares.news_analyzer.schema import NewsBatchResult
from strategies.a_shares.news_analyzer.strategy import NewsAnalyzerStrategy
from strategies.a_shares.news_scanner.strategy import NewsScannerStrategy
from strategies.a_shares.sentiment.analyzer import SentimentAnalyzer
from strategies.a_shares.sentiment.strategy import SentimentStrategy


def _news() -> News:
    return News(
        title="公司公告业绩增长",
        content="经营数据持续改善",
        ts=datetime(2026, 8, 24, tzinfo=UTC),
        source="fixture",
        symbols=["600519"],
    )


class _UnavailableSentiment:
    unavailable_reason = "FinBERT2 fixture unavailable"

    def analyze(self, text: str) -> tuple[None, float, str]:
        return None, 0.0, "unavailable"


class _VerifiedSentiment:
    unavailable_reason = None
    engine = "transformers"

    def is_available(self) -> bool:
        return True

    def analyze(self, text: str) -> tuple[float, float, str]:
        return 0.8, 0.8, "transformers"


def _display_only_batch(reason: str = "api_unavailable") -> NewsBatchResult:
    return NewsBatchResult(
        items=[],
        engine="display_only",
        model=None,
        total=1,
        ok=False,
        degraded_reason=reason,
        display_only=True,
    )


def _complete_llm_item() -> dict[str, object]:
    return {
        "sentiment": "positive",
        "sentiment_score": 0.7,
        "topic": "company",
        "entities": [{"text": "示例公司", "type": "org"}],
        "summary": "示例公司披露业绩增长。",
        "event_type": "earnings_guidance",
        "event_direction": "positive",
        "event_strength": 0.8,
        "event_confidence": 0.9,
        "event_evidence": "业绩增长",
    }


def test_sentiment_analyzer_returns_unavailable_without_configured_model(tmp_path: Path) -> None:
    analyzer = SentimentAnalyzer(model_path=tmp_path / "missing-finbert2")

    score, certainty, engine = analyzer.analyze("公司业绩大幅增长，经营表现改善")

    assert score is None
    assert certainty == 0.0
    assert engine == "unavailable"
    assert analyzer.is_available() is False
    assert "模型目录不存在" in str(analyzer.unavailable_reason)


def test_sentiment_strategy_never_publishes_fallback_and_rejects_symbol_list_alias() -> None:
    source = Mock()
    source.get_news.return_value = [_news()]
    strategy = SentimentStrategy()
    strategy._analyzer = _UnavailableSentiment()  # type: ignore[assignment]

    with (
        patch("strategies.a_shares.sentiment.strategy.get_data_source", return_value=source),
        patch.object(strategy, "publish") as publish,
    ):
        signals = strategy.produce(symbols=["600519"])

    assert signals == []
    publish.assert_not_called()
    assert strategy.last_report is not None
    assert strategy.last_report["display_only"] is True
    assert strategy.last_report["execution_eligible"] is False
    assert strategy.last_signal_rejection is not None
    assert strategy.last_signal_rejection["code"] == "sentiment_model_unavailable"
    with pytest.raises(TypeError):
        strategy.produce(symbol_list=["600519"])  # type: ignore[call-arg]


def test_news_analyzer_marks_missing_llm_as_display_only() -> None:
    analyzer = NewsAnalyzer()
    analyzer._sentiment_analyzer = _VerifiedSentiment()

    with patch.object(analyzer, "_check_api_available", return_value=False):
        batch = analyzer.analyze_batch([_news()])

    assert batch.ok is False
    assert batch.display_only is True
    assert batch.engine == "display_only"
    assert batch.degraded_reason == "api_unavailable"


def test_news_analyzer_rejects_llm_values_that_would_require_coercion() -> None:
    analyzer = NewsAnalyzer()
    analyzer._sentiment_analyzer = _VerifiedSentiment()
    invalid_item = _complete_llm_item()
    invalid_item["sentiment_score"] = -0.7

    with (
        patch.object(analyzer, "_check_api_available", return_value=True),
        patch.object(analyzer, "_api_enhance_batch", return_value=([invalid_item], "fixture-llm")),
    ):
        batch = analyzer.analyze_batch([_news()])

    assert batch.ok is False
    assert batch.display_only is True
    assert batch.degraded_reason == "api_invalid_response"


def test_news_request_rejects_legacy_use_api_switch() -> None:
    with pytest.raises(ValidationError, match="use_api"):
        NewsAnalyzeRequest(symbol="600519", use_api=False)


def test_news_analyzer_strategy_does_not_publish_display_only_batch() -> None:
    source = Mock()
    source.get_news.return_value = [_news()]
    analyzer = Mock()
    analyzer.analyze_batch.return_value = _display_only_batch()
    strategy = NewsAnalyzerStrategy()
    strategy._analyzer = analyzer

    with (
        patch("strategies.a_shares.news_analyzer.strategy.get_data_source", return_value=source),
        patch.object(strategy, "publish") as publish,
    ):
        signals = strategy.produce(symbols=["600519"])

    assert signals == []
    publish.assert_not_called()
    assert strategy.last_report is not None
    assert strategy.last_report["execution_eligible"] is False
    assert strategy.last_signal_rejection is not None
    assert strategy.last_signal_rejection["code"] == "news_analysis_unavailable"


def test_news_api_and_ensemble_reject_unusable_news_model_output() -> None:
    source = Mock()
    source.get_news.return_value = [_news()]
    analyzer = Mock()
    analyzer.analyze_batch.return_value = _display_only_batch("api_call_failed")

    with (
        patch.object(news_service, "get_data_source", return_value=source),
        patch.object(news_service.NewsAnalyzer, "from_config", return_value=analyzer),
        patch.object(news_service, "start_module") as start_module,
        patch.object(news_service, "add_evidence") as add_evidence,
    ):
        result = news_service.analyze(symbol="600519", research_run_id=None)

    assert result["ok"] is False
    assert "新闻分析不可用" in result["error"]
    start_module.assert_not_called()
    add_evidence.assert_not_called()

    with (
        patch.object(ensemble_service, "get_data_source", return_value=source),
        patch.object(ensemble_service.NewsAnalyzer, "from_config", return_value=analyzer),
    ):
        contributor = ensemble_service._news_contributor("600519", "a_shares")

    assert contributor["available"] is False
    assert contributor["metrics"]["display_only"] is True


def test_news_scanner_llm_failure_does_not_create_neutral_signal() -> None:
    source = Mock()
    source.get_news.return_value = [_news()]
    llm = Mock()
    llm.chat.side_effect = RuntimeError("provider unavailable")
    strategy = NewsScannerStrategy()

    with (
        patch("strategies.a_shares.news_scanner.strategy.get_llm", return_value=llm),
        patch("strategies.a_shares.news_scanner.strategy.get_data_source", return_value=source),
        patch.object(strategy, "publish") as publish,
    ):
        signals = strategy.produce(symbols=["600519"])

    assert signals == []
    publish.assert_not_called()
    assert strategy.last_report is not None
    assert strategy.last_report["status"] == "unavailable"
    assert strategy.last_report["execution_eligible"] is False
