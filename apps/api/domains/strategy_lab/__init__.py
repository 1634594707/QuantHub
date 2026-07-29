"""策略实验室域：策略定义、版本、实验与回测运行的统一管理。

为 Phase 3 策略实验室提供持久化与 API 基础：
    - ``StrategyDefinition`` 命名化的策略配置（绑定 strategy_key + market）
    - ``StrategyVersion`` 参数 + 代码哈希 + 变更日志
    - ``Experiment`` 定义 + 版本 + 标的 + 周期的实验单元
    - ``BacktestRun`` 完整回测结果（权益曲线 / 成交 / 指标 / 数据快照 / 种子）
"""

from __future__ import annotations

from .router import router

__all__ = ["router"]
