# -*- coding: utf-8 -*-
"""统一绩效指标计算。"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def compute_metrics(
    returns: pd.Series,
    final_equity: float,
    max_drawdown: float,
    periods_per_year: int = 252,
) -> dict[str, float]:
    """计算统一绩效指标。

    Args:
        returns: 每期收益率序列
        final_equity: 期末权益
        max_drawdown: 最大回撤（负数）
        periods_per_year: 年化周期数（A股日线 252，加密 365）
    """
    if returns is None or returns.empty:
        return {
            "annual_return": 0.0, "annual_volatility": 0.0,
            "sharpe": 0.0, "sortino": 0.0, "calmar": 0.0,
            "max_drawdown": 0.0, "win_rate": 0.0,
        }

    mean_r = float(returns.mean())
    std_r = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    annual_return = mean_r * periods_per_year
    annual_vol = std_r * math.sqrt(periods_per_year)
    sharpe = (annual_return / annual_vol) if annual_vol > 0 else 0.0

    downside = returns[returns < 0]
    downside_std = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    sortino = (annual_return / (downside_std * math.sqrt(periods_per_year))) if downside_std > 0 else 0.0

    calmar = (annual_return / abs(max_drawdown)) if max_drawdown < 0 else 0.0
    win_rate = float((returns > 0).sum() / len(returns)) if len(returns) > 0 else 0.0

    return {
        "annual_return": annual_return,
        "annual_volatility": annual_vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "max_drawdown": max_drawdown,
        "win_rate": win_rate,
    }
