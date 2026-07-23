"""回测框架统一入口。

提供三种回测引擎:
    - grid   : 网格回测（来自 OKX Grid Master 的 simulate_grid_trading）
    - backtrader : backtrader 集成（A股/加密通用）
    - event  : 通用事件驱动回测框架（接入 SuperTrend/情绪/因子）

统一绩效指标计算（绩效指标统一在 metrics 模块）。
"""

from __future__ import annotations

from core.backtest.engine import BacktestResult, BacktraderEngine, EventEngine
from core.backtest.grid import GridBacktester, GridConfig, GridResult
from core.backtest.metrics import compute_metrics

__all__ = [
    "BacktestResult",
    "BacktraderEngine",
    "EventEngine",
    "GridBacktester",
    "GridConfig",
    "GridResult",
    "compute_metrics",
]
