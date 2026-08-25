from __future__ import annotations

from unittest.mock import Mock

import pandas as pd

from strategies.crypto.okx_grid import strategy as okx_strategy


class _PrimarySource:
    name = "okx"

    def __init__(self, values: dict[str, pd.DataFrame | Exception]) -> None:
        self.values = values
        self.calls: list[str] = []

    def get_kline(self, symbol: str, interval: str, *, limit: int):
        self.calls.append(symbol)
        value = self.values[symbol]
        if isinstance(value, Exception):
            raise value
        return value


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"close": [100.0]})


def _strategy(source: _PrimarySource) -> okx_strategy.OkxGridStrategy:
    instance = okx_strategy.OkxGridStrategy(config={"enabled": True})
    instance._source = source
    return instance


def test_okx_grid_rejects_partial_primary_klines_without_publishing(monkeypatch) -> None:
    source = _PrimarySource(
        {
            "BTC/USDT:USDT": _frame(),
            "ETH/USDT:USDT": ConnectionError("primary unavailable"),
        }
    )
    selector = _strategy(source)
    publish = Mock()
    selector.publish = publish
    run_select = Mock(return_value=["BTC/USDT:USDT"])
    monkeypatch.setattr(okx_strategy, "run_select", run_select)

    signals = selector.produce(symbols=list(source.values))

    assert signals == []
    assert source.calls == ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    run_select.assert_not_called()
    publish.assert_not_called()
    assert selector.last_signal_rejection is not None
    assert selector.last_signal_rejection["code"] == "market_data_incomplete"
    assert selector.last_signal_rejection["details"]["failed_symbols"] == ["ETH/USDT:USDT"]
    assert selector.last_report["execution_eligible"] is False


def test_okx_grid_rejects_empty_primary_kline_without_publishing(monkeypatch) -> None:
    source = _PrimarySource(
        {
            "BTC/USDT:USDT": _frame(),
            "ETH/USDT:USDT": pd.DataFrame(),
        }
    )
    selector = _strategy(source)
    selector.publish = Mock()
    run_select = Mock(return_value=["BTC/USDT:USDT"])
    monkeypatch.setattr(okx_strategy, "run_select", run_select)

    signals = selector.produce(symbols=list(source.values))

    assert signals == []
    run_select.assert_not_called()
    selector.publish.assert_not_called()
    assert selector.last_signal_rejection["code"] == "market_data_incomplete"
    assert selector.last_signal_rejection["details"]["failed_symbols"] == ["ETH/USDT:USDT"]
    assert selector.last_signal_rejection["details"]["reason"] == "primary K 线为空"
