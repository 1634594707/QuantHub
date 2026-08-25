"""AlphaMaster MT5 因子引擎适配器模块（实盘默认关闭）。

从 AlphaMaster/model_core 下沉为 strategies/mt5/alphamaster 插件模块。
运行时仅内置 MT5FeatureEngineer、StackVM 与公式词表所需文件。

导出:
    - AlphaMasterStrategy : 策略类（继承 StrategyBase，已 @register_strategy 注册）
    - run_factor_search  : MT5 因子搜索便捷入口（训练产物缺失时显式不可用）
    - compute_target_positions : 连续仓位 tanh + 阈值（等价重实现）
"""

from __future__ import annotations

from strategies.mt5.alphamaster.strategy import (
    AlphaMasterStrategy,
    compute_target_positions,
    describe_formulas,
    engine_info,
    run_factor_search,
    validate_formulas,
)

__all__ = [
    "AlphaMasterStrategy",
    "compute_target_positions",
    "describe_formulas",
    "engine_info",
    "run_factor_search",
    "validate_formulas",
]
