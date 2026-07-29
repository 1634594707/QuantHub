"""组合账本域：基于成交与现金流水计算持仓与绩效。

为 Phase 3 组合账本提供：
    - ``Trade`` 成交流水（买/卖，含费用）
    - ``CashEntry`` 现金流水（出入金）
    - ``Position`` 由成交计算的持仓（均成本、已实现盈亏）
    - ``Benchmark`` 基准曲线与指标
持仓不再依赖静态 holdings，而是由 Trade + CashEntry 流水实时计算。
"""

from __future__ import annotations

from .router import router

__all__ = ["router"]
