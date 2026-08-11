"""可复现的合成行情数据集生成器。

设计目标（对应"模拟演示能力"要求）：
- **确定性 / 可复现**：给定 (preset, seed, n_bars, interval, start) 必产生完全相同的结果，
  不依赖任何网络或随机全局状态（使用 ``numpy.random.default_rng(seed)``）。
- **数据集可切换**：内置多组市场形态预设（上行 / 下行 / 震荡 / 高波动 / 加密 / A股）。
- **时间区间可切换**：通过 ``interval``（1m~1d）与 ``start`` / ``n_bars`` 控制采样粒度与起点。

仅依赖 numpy / pandas，无任何外部网络调用。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

# 间隔 -> 分钟数（用于合成时间轴，与真实 K 线周期语义一致）
INTERVAL_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


def _interval_delta(interval: str) -> timedelta:
    minutes = INTERVAL_MINUTES.get(interval, 1440)
    return timedelta(minutes=minutes)


class DatasetPreset:
    """单一市场形态预设的元数据与生成参数。"""

    def __init__(
        self,
        key: str,
        label: str,
        description: str,
        drift: float,
        vol: float,
        start_price: float,
        regime: str = "none",
    ) -> None:
        self.key = key
        self.label = label
        self.description = description
        self.drift = drift
        self.vol = vol
        self.start_price = start_price
        self.regime = regime

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "drift": self.drift,
            "vol": self.vol,
            "start_price": self.start_price,
            "regime": self.regime,
        }


# 预设注册表：市场形态 + 典型参数，便于前端下拉切换"数据集"。
DATASET_PRESETS: dict[str, DatasetPreset] = {
    "uptrend": DatasetPreset(
        "uptrend",
        "稳健上行",
        "温和正漂移 + 低波动，适合验证趋势/动量类策略",
        drift=0.0006,
        vol=0.012,
        start_price=100.0,
    ),
    "downtrend": DatasetPreset(
        "downtrend",
        "震荡下行",
        "持续负漂移，验证空头/防御类逻辑",
        drift=-0.0006,
        vol=0.013,
        start_price=100.0,
    ),
    "sideways": DatasetPreset(
        "sideways",
        "区间震荡",
        "均值回复主导，适合验证反转/均值回复因子",
        drift=0.0,
        vol=0.010,
        start_price=100.0,
        regime="mean_revert",
    ),
    "volatile": DatasetPreset(
        "volatile",
        "高波动",
        "高波动 + 偶发跳变，压力测试风控与回撤",
        drift=0.0002,
        vol=0.028,
        start_price=100.0,
        regime="jumps",
    ),
    "crypto": DatasetPreset(
        "crypto",
        "加密行情(BTC 风格)",
        "高漂移 + 高波动，24h 连续采样",
        drift=0.0012,
        vol=0.035,
        start_price=30000.0,
    ),
    "a_share": DatasetPreset(
        "a_share",
        "A股风格",
        "板块轮动式趋势 + 涨跌幅约束感",
        drift=0.0005,
        vol=0.018,
        start_price=50.0,
        regime="trend_burst",
    ),
}


def list_presets() -> list[dict[str, Any]]:
    """返回所有数据集预设（供 API / 前端下拉）。"""
    return [preset.to_dict() for preset in DATASET_PRESETS.values()]


def generate_dataset(
    preset: str = "uptrend",
    seed: int = 42,
    n_bars: int = 250,
    interval: str = "1d",
    start: str = "2024-01-01",
) -> pd.DataFrame:
    """生成确定性合成 OHLCV 行情。

    Args:
        preset: 数据集预设 key（见 ``DATASET_PRESETS``）。
        seed: 随机种子，保证可复现。
        n_bars: K 线根数。
        interval: 周期（1m/5m/15m/30m/1h/4h/1d）。
        start: 起始时间（ISO 日期或日期时间），默认 2024-01-01。

    Returns:
        DataFrame，列：[datetime, open, high, low, close, volume]。
    """
    spec = DATASET_PRESETS.get(preset)
    if spec is None:
        raise KeyError(f"未知数据集预设: {preset}")
    if n_bars <= 0:
        raise ValueError("n_bars 必须为正整数")

    rng = np.random.default_rng(seed)
    # 每根 bar 的对数收益：漂移 + 波动 + 形态扰动
    per_bar_drift = spec.drift
    per_bar_vol = spec.vol
    log_returns = rng.normal(per_bar_drift, per_bar_vol, size=n_bars)

    if spec.regime == "mean_revert":
        # 均值回复：价格偏离 0 轴越远，反向拉回越强
        prices = np.empty(n_bars + 1)
        prices[0] = spec.start_price
        for i in range(n_bars):
            pull = -0.05 * np.log(prices[i] / spec.start_price)
            prices[i + 1] = prices[i] * np.exp(log_returns[i] + pull)
    elif spec.regime == "jumps":
        # 高波动 + 偶发跳变
        jump_mask = rng.random(n_bars) < 0.03
        jumps = rng.choice([-1, 1], size=n_bars) * rng.uniform(0.04, 0.09, size=n_bars)
        prices = spec.start_price * np.exp(np.cumsum(log_returns + np.where(jump_mask, jumps, 0.0)))
        prices = np.concatenate([[spec.start_price], prices])
    elif spec.regime == "trend_burst":
        # A股风格：缓慢趋势 + 短脉冲
        burst = np.where(rng.random(n_bars) < 0.08, rng.uniform(0.01, 0.03, size=n_bars), 0.0)
        prices = spec.start_price * np.exp(np.cumsum(log_returns + burst))
        prices = np.concatenate([[spec.start_price], prices])
    else:
        # 纯随机游走（上行 / 下行）
        prices = spec.start_price * np.exp(np.cumsum(log_returns))
        prices = np.concatenate([[spec.start_price], prices])

    prices = np.maximum(prices, 0.01)  # 防非正价格

    # 构造 OHLC：以收盘价为枢轴加日内噪声
    closes = prices[1:]
    opens = prices[:-1]
    intraday = np.abs(rng.normal(0, spec.vol * 0.6, size=n_bars))
    highs = np.maximum(opens, closes) * (1 + intraday * 0.5)
    lows = np.minimum(opens, closes) * (1 - intraday * 0.5)
    lows = np.maximum(lows, 0.01)

    # 时间轴
    try:
        base = datetime.fromisoformat(start)
    except ValueError:
        base = datetime.fromisoformat("2024-01-01")
    delta = _interval_delta(interval)
    datetimes = [base + delta * i for i in range(n_bars)]

    # 成交量：与绝对收益正相关 + 基准噪声
    abs_ret = np.abs(np.diff(prices))
    volume = (
        (1000 + 9000 * (abs_ret / (spec.vol + 1e-9)) + rng.uniform(0, 500, size=n_bars))
        .round()
        .astype(int)
    )
    volume = np.clip(volume, 100, None)

    return pd.DataFrame(
        {
            "datetime": datetimes,
            "open": np.round(opens, 4),
            "high": np.round(highs, 4),
            "low": np.round(lows, 4),
            "close": np.round(closes, 4),
            "volume": volume,
        }
    )
