"""AlphaMaster MT5 因子引擎适配器模块（实盘默认关闭）。

从 AlphaMaster-main/model_core 下沉为 strategies/mt5/alphamaster 插件模块。
通过 sys.path 注入零拷贝复用其因子引擎（MT5FeatureEngineer + StackVM）。

导出:
    - AlphaMasterStrategy : 策略类（继承 StrategyBase，已 @register_strategy 注册）
    - run_factor_search  : MT5 因子搜索便捷入口（无训练权重时回退启发式）
    - compute_target_positions : 连续仓位 tanh + 阈值（等价重实现）
"""

from __future__ import annotations

from strategies.mt5.alphamaster.strategy import (
    AlphaMasterStrategy,
    compute_target_positions,
    run_factor_search,
)

__all__ = ["AlphaMasterStrategy", "compute_target_positions", "run_factor_search"]
