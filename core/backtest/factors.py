"""内置交易因子库（用于回测 demo 的"因子"维度）。

所有因子都返回与输入 K 线等长的 ``pandas.Series``，取值约束在 **[-1, 1]**：
- 符号表示方向（正=看多，负=看空）
- 绝对值表示强度（用于按权重建仓）

纯 numpy / pandas 实现，无外部依赖。因子只读取 ``close`` 序列，便于与合成或真实数据通用。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd


def _momentum(df: pd.DataFrame, lookback: int = 20, z_window: int = 60) -> pd.Series:
    """动量因子：滚动收益做 z-score，再经 tanh 压到 [-1, 1]。"""
    close = df["close"].astype(float)
    ret = close.pct_change(lookback)
    roll_mean = ret.rolling(z_window, min_periods=10).mean()
    roll_std = ret.rolling(z_window, min_periods=10).std()
    z = (ret - roll_mean) / (roll_std + 1e-9)
    return np.tanh(z / 2.0)


def _mean_reversion(df: pd.DataFrame, lookback: int = 10, z_window: int = 60) -> pd.Series:
    """均值回复因子：动量的反向（contrarian）。"""
    return -_momentum(df, lookback=lookback, z_window=z_window)


def _rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """RSI 因子：归一化到 [-1, 1] = (RSI - 50) / 50。"""
    close = df["close"].astype(float)
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.rolling(period, min_periods=1).mean()
    avg_loss = loss.rolling(period, min_periods=1).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    rsi = 100 - 100 / (1 + rs)
    return (rsi - 50) / 50.0


def _ma_cross(df: pd.DataFrame, fast: int = 5, slow: int = 20) -> pd.Series:
    """均线交叉因子：快线在慢线上方为 +1，反之为 -1。"""
    close = df["close"].astype(float)
    ma_fast = close.rolling(fast, min_periods=1).mean()
    ma_slow = close.rolling(slow, min_periods=1).mean()
    diff = (ma_fast - ma_slow) / (ma_slow.abs() + 1e-9)
    return np.tanh(diff * 20.0)


class FactorDef:
    """因子定义：可调用 + 元数据。"""

    def __init__(
        self,
        key: str,
        label: str,
        description: str,
        fn: Callable[[pd.DataFrame, Any], pd.Series],
        default_params: dict[str, Any],
    ) -> None:
        self.key = key
        self.label = label
        self.description = description
        self.fn = fn
        self.default_params = default_params

    def compute(self, df: pd.DataFrame, **params: Any) -> pd.Series:
        merged = {**self.default_params, **params}
        return self.fn(df, **merged)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "default_params": self.default_params,
        }


FACTORS: dict[str, FactorDef] = {
    "momentum": FactorDef(
        "momentum",
        "动量",
        "滚动收益 z-score，捕捉趋势延续",
        _momentum,
        {"lookback": 20, "z_window": 60},
    ),
    "mean_reversion": FactorDef(
        "mean_reversion",
        "均值回复",
        "动量的反向，捕捉超买超卖回归",
        _mean_reversion,
        {"lookback": 10, "z_window": 60},
    ),
    "rsi": FactorDef(
        "rsi",
        "RSI",
        "相对强弱指标归一化，区间反转信号",
        _rsi,
        {"period": 14},
    ),
    "ma_cross": FactorDef(
        "ma_cross",
        "均线交叉",
        "快/慢均线交叉方向",
        _ma_cross,
        {"fast": 5, "slow": 20},
    ),
}


def list_factors() -> list[dict[str, Any]]:
    """返回所有因子定义（供 API / 前端下拉）。"""
    return [factor.to_dict() for factor in FACTORS.values()]


def compute_factor(name: str, df: pd.DataFrame, **params: Any) -> pd.Series:
    """计算指定因子信号序列。"""
    factor = FACTORS.get(name)
    if factor is None:
        raise KeyError(f"未知因子: {name}")
    return factor.compute(df, **params)
