"""A股晨会简报策略模块。

导出:
    - MorningBriefStrategy : 策略类（继承 StrategyBase，已 @register_strategy）
    - generate             : 供 apps.scheduler 调用的当日简报生成入口
"""

from __future__ import annotations

from strategies.a_shares.morning_brief.strategy import MorningBriefStrategy, generate

__all__ = ["MorningBriefStrategy", "generate"]
