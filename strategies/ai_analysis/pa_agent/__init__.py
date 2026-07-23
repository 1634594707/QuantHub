"""价格行为两阶段 LLM 分析策略模块（PA Agent 迁移版）。

导出:
    - PaAgentStrategy : 策略类（继承 StrategyBase，已 @register_strategy）
    - run_analysis    : 供 apps.scheduler / CLI 调用的便捷分析入口
    - run_scheduled  : 供 apps.scheduler 定时批量遍历标的
"""

from __future__ import annotations

from strategies.ai_analysis.pa_agent.strategy import (
    PaAgentStrategy,
    run_analysis,
    run_scheduled,
)

__all__ = ["PaAgentStrategy", "run_analysis", "run_scheduled"]
