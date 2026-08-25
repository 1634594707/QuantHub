from __future__ import annotations

import sys
import types

import pandas as pd
import pytest

from strategies.a_shares.selector import strategy


class _SelectorSource:
    name = "primary"

    def __init__(self, frames: dict[str, pd.DataFrame | Exception]) -> None:
        self.frames = frames
        self.calls: list[str] = []

    def get_kline(self, symbol: str, interval, *, limit: int):
        self.calls.append(symbol)
        value = self.frames[symbol]
        if isinstance(value, Exception):
            raise value
        return value


def _short_frame(rows: int = 20) -> pd.DataFrame:
    return pd.DataFrame({"close": [float(item) for item in range(1, rows + 1)]})


def test_index_constituents_uses_only_primary_endpoint(monkeypatch) -> None:
    calls: list[str] = []
    akshare = types.ModuleType("akshare")

    def primary(*, symbol: str) -> pd.DataFrame:
        calls.append(symbol)
        return pd.DataFrame({"品种代码": ["000001", "300001", "688001"]})

    akshare.index_stock_cons = primary
    monkeypatch.setitem(sys.modules, "akshare", akshare)

    assert strategy._get_index_constituents("hs300") == ["000001"]
    assert calls == ["000300"]


def test_index_constituents_primary_failure_is_visible_and_does_not_fallback(monkeypatch) -> None:
    calls: list[str] = []
    akshare = types.ModuleType("akshare")

    def primary(*, symbol: str) -> pd.DataFrame:
        calls.append(f"primary:{symbol}")
        raise ConnectionError("primary unavailable")

    def unauthorized_secondary(*, symbol: str) -> pd.DataFrame:
        calls.append(f"secondary:{symbol}")
        return pd.DataFrame({"成分券代码": ["000001"]})

    akshare.index_stock_cons = primary
    akshare.index_stock_cons_weight_csindex = unauthorized_secondary
    monkeypatch.setitem(sys.modules, "akshare", akshare)

    with pytest.raises(RuntimeError, match="指数成分股主源获取失败: 000300") as exc_info:
        strategy._get_index_constituents("hs300")

    assert isinstance(exc_info.value.__cause__, ConnectionError)
    assert calls == ["primary:000300"]


def test_gem_star_constituents_do_not_return_a_partial_universe(monkeypatch) -> None:
    calls: list[str] = []
    akshare = types.ModuleType("akshare")

    def primary(*, symbol: str) -> pd.DataFrame:
        calls.append(symbol)
        raise ConnectionError("primary unavailable")

    akshare.index_stock_cons = primary
    monkeypatch.setitem(sys.modules, "akshare", akshare)

    with pytest.raises(RuntimeError, match="指数成分股主源获取失败: 399006"):
        strategy._get_index_constituents("gem_star")

    assert calls == ["399006"]


def test_selector_does_not_publish_partial_results_when_primary_kline_fails(monkeypatch) -> None:
    source = _SelectorSource(
        {
            "000001": _short_frame(),
            "000002": ConnectionError("primary unavailable"),
        }
    )
    monkeypatch.setattr(strategy, "_get_index_constituents", lambda universe: ["000001", "000002"])
    monkeypatch.setattr(strategy, "get_data_source", lambda market: source)
    monkeypatch.setattr(
        strategy,
        "_score_short",
        lambda df, fund_flow=None: {"score": 80.0, "buy_signal_count": 2},
    )

    selector = strategy.SelectorStrategy(config={"enabled": True})
    monkeypatch.setattr(selector, "publish", lambda signal: (_ for _ in ()).throw(AssertionError()))

    signals = selector.produce(universe="hs300", term="short", top_n=20)

    assert signals == []
    assert source.calls == ["000001", "000002"]
    assert selector.last_signal_rejection is not None
    assert selector.last_signal_rejection["code"] == "market_data_incomplete"
    assert selector.last_signal_rejection["details"]["failed_symbols"] == ["000002"]
    assert selector.last_report["execution_eligible"] is False


def test_selector_rejects_short_primary_kline_without_partial_results(monkeypatch) -> None:
    source = _SelectorSource({"000001": _short_frame(19)})
    monkeypatch.setattr(strategy, "_get_index_constituents", lambda universe: ["000001"])
    monkeypatch.setattr(strategy, "get_data_source", lambda market: source)
    monkeypatch.setattr(
        strategy,
        "_score_short",
        lambda df, fund_flow=None: {"score": 80.0, "buy_signal_count": 2},
    )

    selector = strategy.SelectorStrategy(config={"enabled": True})
    signals = selector.produce(universe="hs300", term="short", top_n=20)

    assert signals == []
    assert selector.last_signal_rejection["code"] == "market_data_incomplete"
    assert selector.last_signal_rejection["details"]["failed_symbols"] == ["000001"]
    assert "需要至少 20 根" in selector.last_signal_rejection["details"]["reason"]


def test_selector_rejects_unavailable_score_without_partial_results(monkeypatch) -> None:
    source = _SelectorSource({"000001": _short_frame()})
    monkeypatch.setattr(strategy, "_get_index_constituents", lambda universe: ["000001"])
    monkeypatch.setattr(strategy, "get_data_source", lambda market: source)
    monkeypatch.setattr(strategy, "_score_short", lambda df, fund_flow=None: None)

    selector = strategy.SelectorStrategy(config={"enabled": True})
    signals = selector.produce(universe="hs300", term="short", top_n=20)

    assert signals == []
    assert selector.last_signal_rejection["code"] == "market_data_incomplete"
    assert selector.last_signal_rejection["details"]["reason"] == "评分器返回不可用结果"


def test_selector_rejects_score_failure_without_partial_results(monkeypatch) -> None:
    source = _SelectorSource({"000001": _short_frame()})
    monkeypatch.setattr(strategy, "_get_index_constituents", lambda universe: ["000001"])
    monkeypatch.setattr(strategy, "get_data_source", lambda market: source)

    def fail_score(df, fund_flow=None):
        raise ValueError("invalid OHLCV")

    monkeypatch.setattr(strategy, "_score_short", fail_score)

    selector = strategy.SelectorStrategy(config={"enabled": True})
    signals = selector.produce(universe="hs300", term="short", top_n=20)

    assert signals == []
    assert selector.last_signal_rejection["code"] == "market_data_incomplete"
    assert "评分计算失败" in selector.last_signal_rejection["details"]["reason"]
