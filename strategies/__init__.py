# -*- coding: utf-8 -*-
"""QuantHub 策略插件层。

子包:
    - a_shares/   : sentiment, news_scanner, selector, supertrend, morning_brief, perks_monitor, realtime_analyzer
    - crypto/     : okx_grid, alphagpt
    - mt5/        : alphamaster (AlphaMaster MT5 因子引擎)
    - ai_analysis/: pa_agent

所有策略继承 strategies.base.StrategyBase，通过 @register_strategy 注册。
"""
from __future__ import annotations

import importlib
import logging
from typing import Any

from strategies.base import (
    StrategyBase,
    StrategyInfo,
    get_strategy,
    list_strategies,
    register_strategy,
)

logger = logging.getLogger(__name__)

__all__ = [
    "StrategyBase", "StrategyInfo",
    "get_strategy", "list_strategies", "register_strategy",
]

# 需要预加载以触发 @register_strategy 的策略模块
_STRATEGY_MODULES: list[str] = [
    "strategies.a_shares.sentiment",
    "strategies.a_shares.supertrend",
    "strategies.a_shares.perks_monitor",
    "strategies.a_shares.news_scanner",
    "strategies.a_shares.selector",
    "strategies.a_shares.morning_brief",
    "strategies.a_shares.realtime_analyzer",
    "strategies.crypto.okx_grid",
    "strategies.crypto.alphagpt",
    "strategies.ai_analysis.pa_agent",
    "strategies.mt5.alphamaster",
]


def discover_and_register() -> dict[str, Any]:
    """预加载全部策略模块，触发装饰器注册，返回注册结果字典。

    看板、调度器、回测入口在启动时调用此函数，确保策略注册到全局 _REGISTRY。
    """
    failed: list[str] = []
    for mod in _STRATEGY_MODULES:
        try:
            importlib.import_module(mod)
        except Exception as exc:  # noqa: BLE001
            failed.append(mod)
            logger.warning("策略模块加载失败: %s (%s)", mod, exc)
    if failed:
        logger.warning("共 %d 个策略模块加载失败；这些模块在看板/调度器中不可用", len(failed))
    return list_strategies()
