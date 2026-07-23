# -*- coding: utf-8 -*-
"""集成测试：策略注册 + 信号总线 + dispatcher 路由（dry-run）。

不依赖网络/模型，验证各层接线正确。
"""
from __future__ import annotations

import importlib

import pytest

from core.signals import Signal, get_bus
from strategies import list_strategies


# 导入所有策略模块以触发注册
_STRATEGY_MODULES = [
    "strategies.a_shares.sentiment",
    "strategies.a_shares.supertrend",
    "strategies.a_shares.perks_monitor",
    "strategies.a_shares.news_scanner",
    "strategies.a_shares.selector",
    "strategies.a_shares.morning_brief",
    "strategies.a_shares.realtime_analyzer",
    "strategies.crypto.okx_grid",
    "strategies.crypto.alphagpt",
    "strategies.ai_analysis.pa_agent",
    "strategies.mt5.alphamaster",
]


@pytest.fixture(scope="module", autouse=True)
def _import_all_strategies():
    """导入全部策略模块以触发 @register_strategy。"""
    for mod in _STRATEGY_MODULES:
        importlib.import_module(mod)


def test_all_strategies_registered():
    """11 个策略全部注册。"""
    ss = list_strategies()
    expected = {
        "sentiment", "supertrend", "perks_monitor",
        "news_scanner", "selector", "morning_brief", "realtime_analyzer",
        "okx_grid", "alphagpt", "pa_agent", "alphamaster",
    }
    assert expected.issubset(set(ss.keys())), f"缺失: {expected - set(ss.keys())}"


def test_a_shares_strategies_not_live_capable():
    ss = list_strategies()
    for name in ["sentiment", "supertrend", "perks_monitor", "selector", "morning_brief", "news_scanner", "realtime_analyzer"]:
        assert ss[name].live_capable is False, f"{name} 不应支持实盘"


def test_crypto_strategies_live_capable_but_default_off():
    from strategies import get_strategy
    ss = list_strategies()
    for name in ["okx_grid", "alphagpt", "alphamaster"]:
        assert ss[name].live_capable is True
        s = get_strategy(name, config={"enabled": True, "live": False})
        assert s.is_live() is False   # 默认关闭


def test_signal_bus_dispatch_to_dispatcher():
    """信号发布到总线，dispatcher 缓冲。"""
    from apps.dispatcher.main import Dispatcher
    get_bus().clear_history()
    d = Dispatcher()
    sig = Signal(symbol="000001", market="a_shares", timeframe="daily",
                 direction="buy", score=0.9, confidence=0.8, source="sentiment")
    get_bus().publish(sig)
    # dispatcher 缓冲应有该 symbol
    assert "000001" in d._buffer


def test_dispatcher_dry_run_default():
    """默认 dry-run（live_trading=false）。"""
    from apps.dispatcher.router import OrderRouter
    r = OrderRouter()
    assert r.dry_run is True


def test_order_intent_serializable():
    """订单意图可序列化。"""
    from apps.dispatcher.router import OrderIntent
    intent = OrderIntent(symbol="BTC", market="crypto", side="buy", qty=0.1,
                         price=50000, source="okx_grid")
    d = intent.to_dict()
    assert d["symbol"] == "BTC"
    assert "ts" in d
    s = intent.summary()
    assert "标的" in s


def test_risk_checker_rejects_over_limit():
    """风控超限拒绝。"""
    from apps.dispatcher.risk import RiskChecker, RiskContext, RiskError
    checker = RiskChecker(market="crypto")
    ctx = RiskContext(total_equity=10000, position_value=0, symbol_position_value=0)
    # notional 5000 占比 50% > 15% 限额
    with pytest.raises(RiskError):
        checker.check({"symbol": "BTC", "notional": 5000}, ctx)


def test_risk_checker_passes_within_limit():
    from apps.dispatcher.risk import RiskChecker, RiskContext
    checker = RiskChecker(market="crypto")
    ctx = RiskContext(total_equity=10000, position_value=0, symbol_position_value=0)
    # notional 1000 占比 10% < 15%
    checker.check({"symbol": "BTC", "notional": 1000}, ctx)  # 不抛异常即通过


def test_config_live_trading_off():
    """全局实盘开关默认关闭。"""
    from core.config import get_config
    assert get_config()["live_trading"] is False


def test_strategies_share_single_bus():
    """所有策略共享同一信号总线。"""
    from core.signals import get_bus
    bus1 = get_bus()
    bus2 = get_bus()
    assert bus1 is bus2
