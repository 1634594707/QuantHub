# -*- coding: utf-8 -*-
"""A股 FinBERT2 新闻情绪策略模块。

导出:
    - SentimentStrategy : 策略类（继承 StrategyBase，已 @register_strategy）
    - run_daily_scan    : 供 apps.scheduler 调用的每日扫描入口
"""
from __future__ import annotations

from typing import Optional

from core.config import get_config
from core.signals import Signal
from strategies.a_shares.sentiment.strategy import SentimentStrategy

__all__ = ["SentimentStrategy", "run_daily_scan"]


def run_daily_scan(symbols: Optional[list[str]] = None) -> list[Signal]:
    """每日情绪扫描入口（apps.scheduler 调用）。

    实例化 sentiment 策略并执行 produce，返回当日信号列表。
    symbols 为空时返回空列表（由上游选股模块注入标的）。
    """
    cfg = get_config("a_shares").get("modules", {}).get("sentiment", {})
    strategy = SentimentStrategy(config=cfg)
    return strategy.produce(symbols=symbols)
