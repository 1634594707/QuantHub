# -*- coding: utf-8 -*-
"""A股 SuperTrend 趋势跟踪策略模块。

导出:
    - SuperTrendStrategy : 策略类（继承 StrategyBase，已 @register_strategy 注册）
    - run_scan           : 便捷扫描入口
    - supertrend         : SuperTrend 指标计算函数
"""
from __future__ import annotations

from strategies.a_shares.supertrend.indicators import supertrend
from strategies.a_shares.supertrend.strategy import SuperTrendStrategy, run_scan

__all__ = ["SuperTrendStrategy", "run_scan", "supertrend"]
