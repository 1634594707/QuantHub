"""A股多因子选股神器策略模块。

导出:
    - SelectorStrategy : 选股策略类（继承 StrategyBase，已 @register_strategy 注册）
    - run_daily_select : 便捷选股入口（供 scheduler 调用）
"""

from __future__ import annotations

from strategies.a_shares.selector.strategy import SelectorStrategy, run_daily_select

__all__ = ["SelectorStrategy", "run_daily_select"]
