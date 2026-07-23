# -*- coding: utf-8 -*-
"""A股股东回馈羊毛监控策略模块。

迁移自原 ``Python撸大A羊毛`` 项目，复用 ``core.data_feed`` 公告数据层与
``core.alert`` 企微推送，不再重新实现东方财富爬虫与 WeChatPusher。

导入即触发 ``@register_strategy`` 注册到全局策略表。
"""
from __future__ import annotations

from strategies.a_shares.perks_monitor.strategy import (
    DEFAULT_STOCK_POOL,
    PERKS_KEYWORDS,
    PerksMonitorStrategy,
    scan_announcements,
)

__all__ = [
    "PerksMonitorStrategy",
    "scan_announcements",
    "PERKS_KEYWORDS",
    "DEFAULT_STOCK_POOL",
]

# 引用一次类，确保 @register_strategy 装饰器已执行
_ = PerksMonitorStrategy
