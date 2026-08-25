"""Strategies must not revive hard-coded example universes when config is absent."""

from unittest.mock import Mock

from strategies.a_shares.morning_brief.strategy import MorningBriefStrategy
from strategies.a_shares.perks_monitor.strategy import PerksMonitorStrategy
from strategies.a_shares.realtime_analyzer.strategy import RealtimeAnalyzerStrategy
from strategies.a_shares.selector.strategy import SelectorStrategy
from strategies.a_shares.supertrend import strategy as supertrend_strategy
from strategies.us_stocks.realtime_analyzer.strategy import RealtimeAnalyzerUsStrategy


def test_supertrend_without_symbols_is_unavailable_without_constructing_source(monkeypatch) -> None:
    source_factory = Mock(side_effect=AssertionError("source must not be constructed"))
    monkeypatch.setattr(supertrend_strategy, "get_data_source", source_factory)

    strategy = supertrend_strategy.SuperTrendStrategy(config={"enabled": True})
    assert strategy.produce() == []
    source_factory.assert_not_called()
    assert strategy.last_signal_rejection["code"] == "symbols_required"
    assert strategy.last_report["execution_eligible"] is False


def test_supertrend_empty_config_symbols_is_not_replaced_by_examples(monkeypatch) -> None:
    source_factory = Mock(side_effect=AssertionError("source must not be constructed"))
    monkeypatch.setattr(supertrend_strategy, "get_data_source", source_factory)

    strategy = supertrend_strategy.SuperTrendStrategy(config={"enabled": True, "symbols": []})
    assert strategy.produce() == []
    source_factory.assert_not_called()
    assert strategy.last_signal_rejection["code"] == "symbols_required"


def test_morning_brief_without_symbols_is_unavailable_without_fetching_data(monkeypatch) -> None:
    source_factory = Mock(side_effect=AssertionError("source must not be constructed"))
    monkeypatch.setattr(
        "strategies.a_shares.morning_brief.strategy.get_data_source", source_factory
    )

    strategy = MorningBriefStrategy(config={"enabled": True})
    assert strategy.produce() == []
    source_factory.assert_not_called()
    assert strategy.last_signal_rejection["code"] == "symbols_required"
    assert strategy.last_report["execution_eligible"] is False


def test_morning_brief_unknown_style_is_rejected_instead_of_using_full(monkeypatch) -> None:
    source_factory = Mock(side_effect=AssertionError("source must not be constructed"))
    monkeypatch.setattr(
        "strategies.a_shares.morning_brief.strategy.get_data_source", source_factory
    )

    strategy = MorningBriefStrategy(config={"enabled": True, "symbols": ["sh000001"]})
    assert strategy.produce(style="legacy") == []
    source_factory.assert_not_called()
    assert strategy.last_signal_rejection["code"] == "invalid_style"
    assert strategy.last_signal_rejection["details"]["style"] == "legacy"


def test_explicit_morning_brief_symbols_are_preserved() -> None:
    strategy = MorningBriefStrategy(config={"symbols": [" sh000001 ", ""]})
    assert strategy._resolve_symbols(None) == ["sh000001"]
    assert strategy._resolve_symbols(["sz399006"]) == ["sz399006"]


def test_explicit_supertrend_symbols_are_preserved() -> None:
    strategy = supertrend_strategy.SuperTrendStrategy(config={"symbols": [" 510300 "]})
    assert strategy._resolve_symbols(None) == ["510300"]
    assert strategy._resolve_symbols(["601988"]) == ["601988"]


def test_a_share_realtime_analyzer_without_codes_does_not_use_examples(monkeypatch) -> None:
    source_factory = Mock(side_effect=AssertionError("source must not be constructed"))
    monkeypatch.setattr(
        "strategies.a_shares.realtime_analyzer.strategy.get_data_source", source_factory
    )

    strategy = RealtimeAnalyzerStrategy(config={"enabled": True})
    assert strategy.produce() == []
    source_factory.assert_not_called()
    assert strategy.last_signal_rejection["code"] == "symbols_required"


def test_us_realtime_analyzer_without_codes_does_not_use_examples(monkeypatch) -> None:
    source_factory = Mock(side_effect=AssertionError("source must not be constructed"))
    monkeypatch.setattr(
        "strategies.us_stocks.realtime_analyzer.strategy.get_data_source", source_factory
    )

    strategy = RealtimeAnalyzerUsStrategy(config={"enabled": True})
    assert strategy.produce() == []
    source_factory.assert_not_called()
    assert strategy.last_signal_rejection["code"] == "symbols_required"


def test_perks_monitor_without_configured_pool_is_unavailable_without_fetching(monkeypatch) -> None:
    source_factory = Mock(side_effect=AssertionError("source must not be constructed"))
    monkeypatch.setattr(
        "strategies.a_shares.perks_monitor.strategy.get_data_source", source_factory
    )

    strategy = PerksMonitorStrategy(config={})
    assert strategy.produce() == []
    source_factory.assert_not_called()
    assert strategy.last_signal_rejection["code"] == "symbols_required"
    assert strategy.last_report["execution_eligible"] is False


def test_perks_monitor_explicit_symbols_do_not_require_default_pool(monkeypatch) -> None:
    strategy = PerksMonitorStrategy(config={})
    monkeypatch.setattr(strategy, "_fetch_announcements", lambda _symbol: [])

    assert strategy.produce(symbols=["600519"]) == []
    assert strategy.last_signal_rejection is None


def test_selector_without_explicit_universe_does_not_use_hs300_default(monkeypatch) -> None:
    source_factory = Mock(side_effect=AssertionError("source must not be constructed"))
    monkeypatch.setattr("strategies.a_shares.selector.strategy.get_data_source", source_factory)
    monkeypatch.setattr(
        "strategies.a_shares.selector.strategy._get_index_constituents",
        Mock(side_effect=AssertionError("universe must not be resolved")),
    )

    strategy = SelectorStrategy(config={"enabled": True})
    assert strategy.produce() == []
    source_factory.assert_not_called()
    assert strategy.last_signal_rejection["code"] == "universe_required"
