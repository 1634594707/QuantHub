"""core.backtest 单测。"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from core.backtest.engine import EventEngine
from core.backtest.grid import GridBacktester, GridConfig
from core.backtest.metrics import compute_metrics


def _make_klines(n=100, base=100.0):
    """生成震荡 K 线（适合网格）。"""
    dates = [datetime(2026, 1, 1) + timedelta(days=i) for i in range(n)]
    np.random.seed(42)
    # 在 base 上下 10% 震荡
    close = base * (1 + 0.1 * np.sin(np.linspace(0, 4 * np.pi, n)))
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": close * 0.99,
            "high": close * 1.01,
            "low": close * 0.98,
            "close": close,
            "volume": 1000.0,
        }
    )


def test_grid_backtester_runs():
    df = _make_klines()
    bt = GridBacktester(GridConfig(upper=1.1, lower=0.9, grids=10, amount_per_grid=100))
    res = bt.run(df)
    assert not res.equity_curve.empty
    assert isinstance(res.final_equity, float)
    assert isinstance(res.total_return, float)


def test_grid_backtester_empty():
    bt = GridBacktester()
    res = bt.run(pd.DataFrame())
    assert res.final_equity == 0.0
    assert res.equity_curve.empty


def test_event_engine_runs():
    df = _make_klines(50)

    def on_bar(bar, ctx):
        # 简单策略: 价格低于 95 买入，高于 105 卖出
        p = float(bar["close"])
        if p < 95 and ctx.cash > 100:
            ctx.buy(p, 1, bar["datetime"])
        elif p > 105 and ctx.position > 0:
            ctx.sell(p, ctx.position, bar["datetime"])

    eng = EventEngine(initial_capital=10000)
    res = eng.run(df, on_bar)
    assert not res.equity_curve.empty
    assert res.engine == "event"


def test_compute_metrics_empty():
    m = compute_metrics(pd.Series(dtype=float), 0, 0)
    assert m["sharpe"] == 0.0


def test_compute_metrics_normal():
    returns = pd.Series([0.01, -0.005, 0.02, 0.0, -0.01])
    m = compute_metrics(returns, 10500, -0.02)
    assert "sharpe" in m
    assert "win_rate" in m
    assert 0 <= m["win_rate"] <= 1
