"""AlphaGPT 因子 DSL + 链上执行 策略模块（实盘默认关闭）。

从 AlphaGPT/model_core + strategy_manager + execution 下沉为
strategies/crypto/alphagpt 插件模块。

导出:
    - AlphaGptStrategy : 策略类（继承 StrategyBase，已 @register_strategy 注册）
    - run_factor_search: 因子搜索便捷入口
"""

from __future__ import annotations

from strategies.crypto.alphagpt.strategy import AlphaGptStrategy, run_factor_search

__all__ = ["AlphaGptStrategy", "run_factor_search"]
