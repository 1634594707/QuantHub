from __future__ import annotations

from unittest.mock import Mock

import pandas as pd

from strategies.a_shares.supertrend import strategy as supertrend_strategy


class _PrimarySource:
    name = "primary"

    def __init__(self, values: dict[str, pd.DataFrame | Exception]) -> None:
        self.values = values
        self.calls: list[str] = []

    def get_kline(self, symbol: str, interval, *, limit: int):
        self.calls.append(symbol)
        value = self.values[symbol]
        if isinstance(value, Exception):
            raise value
        return value


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"close": [100.0]})


def _strategy(source: _PrimarySource) -> supertrend_strategy.SuperTrendStrategy:
    instance = supertrend_strategy.SuperTrendStrategy(config={"enabled": True})
    return instance


def test_supertrend_rejects_partial_primary_klines_without_publishing(monkeypatch) -> None:
    source = _PrimarySource(
        {
            "510300": _frame(),
            "601988": ConnectionError("primary unavailable"),
        }
    )
    strategy = _strategy(source)
    strategy.publish = Mock()
    monkeypatch.setattr(supertrend_strategy, "get_data_source", lambda market: source)
    monkeypatch.setattr(supertrend_strategy.st_ind, "supertrend", lambda df, **kwargs: df)
    monkeypatch.setattr(strategy, "_signal_from_df", lambda *args, **kwargs: Mock(name="signal"))

    signals = strategy.produce(symbols=list(source.values))

    assert signals == []
    assert source.calls == ["510300", "601988"]
    strategy.publish.assert_not_called()
    assert strategy.last_signal_rejection is not None
    assert strategy.last_signal_rejection["code"] == "market_data_incomplete"
    assert strategy.last_signal_rejection["details"]["failed_symbols"] == ["601988"]
    assert strategy.last_report["execution_eligible"] is False


def test_supertrend_rejects_empty_primary_kline_without_publishing(monkeypatch) -> None:
    source = _PrimarySource({"510300": _frame(), "601988": pd.DataFrame()})
    strategy = _strategy(source)
    strategy.publish = Mock()
    monkeypatch.setattr(supertrend_strategy, "get_data_source", lambda market: source)
    monkeypatch.setattr(supertrend_strategy.st_ind, "supertrend", lambda df, **kwargs: df)
    monkeypatch.setattr(strategy, "_signal_from_df", lambda *args, **kwargs: Mock(name="signal"))

    signals = strategy.produce(symbols=list(source.values))

    assert signals == []
    strategy.publish.assert_not_called()
    assert strategy.last_signal_rejection["code"] == "market_data_incomplete"
    assert strategy.last_signal_rejection["details"]["failed_symbols"] == ["601988"]
    assert strategy.last_signal_rejection["details"]["reason"] == "primary K 线为空"
