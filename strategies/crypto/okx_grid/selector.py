"""智能选币引擎（源自 OKX Grid Master strategy/selector.py）。

多因子截面排名选币策略:
1. 时序因子: 涨跌幅、波动率、动量、RSI
2. 截面因子: 涨跌比例、成交额排名
3. 排名机制: 多因子综合排名取 Top-N

注意：calc_time_series_factors / calc_cross_section_factors / select_coins
      / calc_bollinger_signals / calc_macd_signals 的因子公式严格保持原实现，
      未做任何修改。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def calc_time_series_factors(df):
    """
    计算时序因子 (单个币种)
    :param df: 单个币种的K线数据
    :return: df (追加因子列)
    """
    # === 涨跌幅 ===
    df["涨跌幅"] = df["close"].pct_change()
    df["涨跌幅"].fillna(value=df["close"] / df["open"] - 1, inplace=True)

    # === 波动率 (滚动标准差) ===
    for n in [12, 24]:
        df[f"volatility_{n}"] = df["涨跌幅"].rolling(n).std() * np.sqrt(24 * 365)

    # 综合波动率因子 (用于选币)
    df["波动率"] = df["volatility_12"]

    # === 动量因子 ===
    for n in [6, 12, 24]:
        df[f"momentum_{n}"] = df["close"].pct_change(n)

    # === RSI ===
    for n in [14, 28]:
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(n).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(n).mean()
        rs = gain / loss.replace(0, np.nan)
        df[f"rsi_{n}"] = 100 - (100 / (1 + rs))

    # === 布林带位置 ===
    for n in [20, 50]:
        ma = df["close"].rolling(n).mean()
        std = df["close"].rolling(n).std()
        upper = ma + 2 * std
        lower = ma - 2 * std
        df[f"boll_pos_{n}"] = (df["close"] - lower) / (upper - lower)
        df[f"boll_width_{n}"] = (upper - lower) / ma

    # === 上涨/下跌标记 ===
    df["上涨"] = 0
    df["下跌"] = 0
    df.loc[df["涨跌幅"] > 0, "上涨"] = 1
    df.loc[df["涨跌幅"] <= 0, "下跌"] = 1

    # === 成交量比率 ===
    for n in [12, 24]:
        df[f"vol_ratio_{n}"] = df["volume"] / df["volume"].rolling(n).mean()

    return df


def calc_cross_section_factors(all_coin_data):
    """
    计算截面因子 (所有币种之间对比)
    :param all_coin_data: 合并后的全市场数据
    :return: all_coin_data (追加截面因子)
    """
    # 上涨比例 (市场情绪)
    all_coin_data["上涨数量"] = all_coin_data.groupby("time")["上涨"].transform("sum")
    all_coin_data["下跌数量"] = all_coin_data.groupby("time")["下跌"].transform("sum")
    total = all_coin_data["上涨数量"] + all_coin_data["下跌数量"]
    all_coin_data["上涨比例"] = all_coin_data["上涨数量"] / total.replace(0, np.nan)

    # 成交额排名 (截面百分位)
    all_coin_data["成交额排名"] = all_coin_data.groupby("time")["volume"].rank(
        method="first", ascending=False, pct=True
    )

    # 涨跌幅截面百分位
    all_coin_data["涨跌幅排名"] = all_coin_data.groupby("time")["涨跌幅"].rank(
        method="first", ascending=True, pct=True
    )

    return all_coin_data


def select_coins(data, factor_config, top_n=1):
    """
    多因子排名选币
    :param data: 含有因子值的数据
    :param factor_config: 因子配置字典，如 {'涨跌幅': True, '波动率': True}
                         True=升序排列(选小的), False=降序排列(选大的)
    :param top_n: 选取前N名
    :return: 选中币种的数据
    """
    if data.empty:
        return data

    df = data.dropna(subset=list(factor_config.keys()))
    if df.empty:
        return df

    # 计算每个因子的排名
    rank_cols = []
    for factor, ascending in factor_config.items():
        col_name = f"rank_{factor}"
        df[col_name] = df.groupby("time")[factor].rank(method="first", ascending=ascending)
        rank_cols.append(col_name)

    # 综合排名 (简单加总)
    df["rank_sum"] = df[rank_cols].sum(axis=1)
    df["rank"] = df.groupby("time")["rank_sum"].rank(method="first", ascending=True)

    # 选取Top-N
    selected = df[df["rank"] <= top_n].copy()
    selected.sort_values("time", inplace=True)

    return selected


def calc_bollinger_signals(df, n=20, std_dev=2):
    """布林带信号"""
    df[f"ma_{n}"] = df["close"].rolling(n).mean()
    df[f"std_{n}"] = df["close"].rolling(n).std()
    df[f"boll_upper_{n}"] = df[f"ma_{n}"] + std_dev * df[f"std_{n}"]
    df[f"boll_lower_{n}"] = df[f"ma_{n}"] - std_dev * df[f"std_{n}"]
    return df


def calc_macd_signals(df, fast=12, slow=26, signal=9):
    """MACD信号"""
    df["ema_fast"] = df["close"].ewm(span=fast, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=slow, adjust=False).mean()
    df["dif"] = df["ema_fast"] - df["ema_slow"]
    df["dea"] = df["dif"].ewm(span=signal, adjust=False).mean()
    df["macd_hist"] = 2 * (df["dif"] - df["dea"])
    return df


# ===== QuantHub 适配入口 =====

# 默认因子配置（动量 / 波动率 / 流动性）
# True=升序排列(选小的), False=降序排列(选大的)
DEFAULT_FACTOR_CONFIG = {
    "波动率": False,  # 高波动（网格收益空间大）
    "momentum_12": False,  # 高动量
    "vol_ratio_24": False,  # 高成交活跃（流动性）
}


def run_select(
    klines_dict: dict[str, pd.DataFrame],
    top_n: int = 10,
    factor_config: dict | None = None,
) -> list[str]:
    """选币入口（QuantHub 适配）。

    把多币种 K线字典送入因子计算 + 截面排名，返回最近时间点的 Top-N symbol 列表。
    因子计算公式与原 selector 完全一致，仅在入口做列名适配（datetime → time）。

    Args:
        klines_dict: ``{symbol: klines_df}``，df 需含 datetime/open/high/low/close/volume 列
                     （QuantHub ``OkxSource`` 标准输出）
        top_n: 选取前 N 名
        factor_config: 因子配置（None 用默认 DEFAULT_FACTOR_CONFIG）
    Returns:
        选中币种 symbol 列表（按 rank 升序）
    """
    if not klines_dict:
        return []

    factor_config = factor_config or DEFAULT_FACTOR_CONFIG

    # 1. 单币种时序因子计算 + 拼接成面板
    panels: list[pd.DataFrame] = []
    for sym, df in klines_dict.items():
        if df is None or df.empty:
            continue
        df = df.copy()
        # 适配列名: QuantHub 用 datetime，原 selector 用 time
        if "time" not in df.columns and "datetime" in df.columns:
            df["time"] = df["datetime"]
        df = calc_time_series_factors(df)
        df["symbol"] = sym
        panels.append(df)

    if not panels:
        return []

    all_data = pd.concat(panels, ignore_index=True)
    all_data = calc_cross_section_factors(all_data)
    selected = select_coins(all_data, factor_config, top_n=top_n)

    if selected.empty:
        return []

    # 2. 取最近时间点的 Top-N
    last_time = selected["time"].max()
    latest = selected[selected["time"] == last_time].sort_values("rank")
    return latest["symbol"].tolist()
