# -*- coding: utf-8 -*-
"""core.signals 单测。"""
from __future__ import annotations

from datetime import datetime

import pytest

from core.signals import Signal, SignalBus, get_bus


def test_signal_valid():
    s = Signal(symbol="000001", market="a_shares", timeframe="daily",
               direction="buy", score=0.8, confidence=0.7, source="sentiment")
    assert s.symbol == "000001"
    assert s.direction == "buy"


def test_signal_invalid_score():
    with pytest.raises(ValueError):
        Signal(symbol="x", market="a_shares", timeframe="daily",
               direction="buy", score=1.5, confidence=0.7, source="t")


def test_signal_invalid_direction():
    with pytest.raises(ValueError):
        Signal(symbol="x", market="a_shares", timeframe="daily",
               direction="wait", score=0.5, confidence=0.5, source="t")


def test_signal_to_dict():
    s = Signal(symbol="BTC", market="crypto", timeframe="1h",
               direction="sell", score=0.9, confidence=0.8, source="okx_grid")
    d = s.to_dict()
    assert d["symbol"] == "BTC"
    assert d["direction"] == "sell"
    assert isinstance(d["ts"], str)


def test_bus_pubsub():
    bus = SignalBus()
    received: list[Signal] = []
    bus.subscribe(received.append, market="a_shares")
    s1 = Signal(symbol="000001", market="a_shares", timeframe="daily",
                direction="buy", score=0.7, confidence=0.6, source="t")
    s2 = Signal(symbol="BTC", market="crypto", timeframe="1h",
                direction="sell", score=0.8, confidence=0.7, source="t")
    bus.publish(s1)
    bus.publish(s2)
    assert len(received) == 1          # 过滤了 crypto
    assert received[0].symbol == "000001"


def test_bus_history():
    bus = SignalBus()
    bus.clear_history()
    for i in range(3):
        bus.publish(Signal(symbol=f"s{i}", market="a_shares", timeframe="d",
                           direction="buy", score=0.5, confidence=0.5, source="t"))
    assert len(bus.history()) == 3
    assert len(bus.history(source="other")) == 0


def test_bus_handler_exception_isolated():
    bus = SignalBus()

    def bad(_):
        raise RuntimeError("boom")

    ok: list[Signal] = []
    bus.subscribe(bad)
    bus.subscribe(ok.append)
    s = Signal(symbol="x", market="a_shares", timeframe="d",
               direction="buy", score=0.5, confidence=0.5, source="t")
    bus.publish(s)
    # bad 抛异常不阻断 ok
    assert len(ok) == 1


def test_get_bus_singleton():
    assert get_bus() is get_bus()
