"""Time-series factor evaluation and lightweight strategy comparison.

The module intentionally keeps factor formation and forward returns separated. Factor
direction is learned on the first 70% of the sample and evaluated on the remaining 30%,
which makes the reported ``usable`` status an out-of-sample result rather than an
in-sample fit.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import numpy as np
import pandas as pd

FACTOR_META = {
    "trend_strength": ("趋势强度", "趋势", "20/60 周期指数均线偏离"),
    "momentum_20": ("20 周期动量", "趋势", "过去 20 个周期的价格动量"),
    "macd_histogram": ("MACD 柱", "趋势", "MACD 与信号线差值的价格标准化"),
    "adx_direction": ("ADX 方向", "趋势", "方向运动与趋势强度的联合信号"),
    "mean_reversion": ("均值回归", "反转", "价格偏离 20 周期均值后的修复强度"),
    "rsi_reversal": ("RSI 反转", "反转", "RSI(14) 超买超卖的反向信号"),
    "bollinger_reversal": ("布林反转", "反转", "价格偏离布林中轨的反向标准分"),
    "breakout_20": ("20 周期突破", "突破", "价格在近 20 周期高低区间中的位置"),
    "volume_confirmation": ("量价确认", "量价", "短期动量与相对成交量的共同变化"),
    "obv_momentum": ("OBV 动量", "量价", "20 周期能量潮变化占成交量的比例"),
    "chaikin_flow": ("Chaikin 资金流", "量价", "收盘位置加权的 20 周期资金流"),
    "low_volatility": ("低波动", "风险", "过去 20 周期的实现波动率倒数方向"),
    "atr_contraction": ("ATR 收缩", "风险", "真实波幅占价格比例的反向信号"),
    "downside_risk": ("下行波动", "风险", "过去 20 周期下行波动率的反向信号"),
}

FACTOR_FORMULAS = {
    "trend_strength": "EMA(close,20) / EMA(close,60) - 1",
    "momentum_20": "close / close.shift(20) - 1",
    "macd_histogram": "(EMA(close,12) - EMA(close,26) - EMA(MACD,9)) / close",
    "adx_direction": "((DI_PLUS(14) - DI_MINUS(14)) / 100) * (ADX(14) / 100)",
    "mean_reversion": "(SMA(close,20) - close) / STD(close,20)",
    "rsi_reversal": "(50 - RSI(close,14)) / 50",
    "bollinger_reversal": "(SMA(close,20) - close) / (2 * STD(close,20))",
    "breakout_20": "(close - MIN(close,20)) / (MAX(close,20) - MIN(close,20)) - 0.5",
    "volume_confirmation": "RETURN(close,5) * CLIP(volume / SMA(volume,20) - 1,-3,3)",
    "obv_momentum": "DIFF(OBV(close,volume),20) / SUM(volume,20)",
    "chaikin_flow": "SUM(((2*close-high-low)/(high-low))*volume,20) / SUM(volume,20)",
    "low_volatility": "-STD(RETURN(close,1),20)",
    "atr_contraction": "-ATR(high,low,close,14) / close",
    "downside_risk": "-STD(MIN(RETURN(close,1),0),20)",
}

METHOD_META = {
    "buy_hold": "买入持有",
    "trend": "趋势跟随",
    "momentum": "动量轮动",
    "mean_reversion": "均值回归",
    "breakout": "通道突破",
    "multifactor": "多因子组合",
}

FACTOR_RESEARCH_ENGINE_VERSION = "2.0.0"
FACTOR_FORMULA_VERSION = "1.0.0"

METHOD_METRIC_DEFINITIONS = [
    {
        "key": "total_return",
        "label": "总收益",
        "formula": "样本外净值末值 - 1",
        "unit": "decimal_return",
        "source": "样本外 K 线 close、position 和 transaction_cost_bps",
    },
    {
        "key": "annual_return",
        "label": "年化收益",
        "formula": "净值末值 ** (periods_per_year / 样本外周期数) - 1",
        "unit": "decimal_return_per_year",
        "source": "样本外净收益序列和 periods_per_year",
    },
    {
        "key": "sharpe",
        "label": "夏普",
        "formula": "annual_return / annual_volatility；无风险利率按 0 处理",
        "unit": "ratio",
        "source": "样本外净收益序列和 periods_per_year",
    },
    {
        "key": "annual_volatility",
        "label": "年化波动",
        "formula": "净收益总体标准差 * sqrt(periods_per_year)",
        "unit": "decimal_return_per_year",
        "source": "样本外净收益序列和 periods_per_year",
    },
    {
        "key": "downside_deviation",
        "label": "下行偏差",
        "formula": "负净收益平方均值开方 * sqrt(periods_per_year)",
        "unit": "decimal_return_per_year",
        "source": "样本外净收益序列和 periods_per_year",
    },
    {
        "key": "sortino",
        "label": "Sortino",
        "formula": "annual_return / downside_deviation",
        "unit": "ratio",
        "source": "样本外净收益序列",
    },
    {
        "key": "calmar",
        "label": "Calmar",
        "formula": "annual_return / abs(max_drawdown)",
        "unit": "ratio",
        "source": "样本外净值序列",
    },
    {
        "key": "max_drawdown",
        "label": "最大回撤",
        "formula": "净值 / 历史净值峰值 - 1 的最小值",
        "unit": "decimal_return",
        "source": "样本外净值序列",
    },
    {
        "key": "var_95",
        "label": "95% VaR",
        "formula": "样本外净收益的 5% 分位数",
        "unit": "decimal_return_per_period",
        "source": "样本外净收益序列",
    },
    {
        "key": "cvar_95",
        "label": "95% CVaR",
        "formula": "净收益 <= VaR 的样本均值",
        "unit": "decimal_return_per_period",
        "source": "样本外净收益序列",
    },
    {
        "key": "profit_factor",
        "label": "利润因子",
        "formula": "闭合交易正收益之和 / abs(闭合交易负收益之和)",
        "unit": "ratio",
        "source": "按 position 开平配对后的闭合交易净收益",
    },
    {
        "key": "win_rate",
        "label": "胜率",
        "formula": "正收益闭合交易数 / 闭合交易总数",
        "unit": "fraction",
        "source": "按 position 开平配对后的闭合交易净收益",
    },
    {
        "key": "average_trade_return",
        "label": "平均交易收益",
        "formula": "闭合交易净收益的算术平均",
        "unit": "decimal_return_per_trade",
        "source": "按 position 开平配对后的闭合交易净收益",
    },
    {
        "key": "average_holding_period",
        "label": "平均持有周期",
        "formula": "闭合交易持有周期数的算术平均",
        "unit": "bars_per_trade",
        "source": "position 的连续持有区间",
    },
    {
        "key": "turnover",
        "label": "换手",
        "formula": "sum(abs(position.shift(1).diff()))，首期按持仓计入",
        "unit": "one_way_position_units",
        "source": "样本外 position 序列",
    },
    {
        "key": "exposure",
        "label": "敞口",
        "formula": "样本外持仓 position 的均值",
        "unit": "fraction_of_periods",
        "source": "样本外 position 序列",
    },
    {
        "key": "transaction_cost_bps",
        "label": "单边交易成本",
        "formula": "每单位换手从净收益中扣除 transaction_cost_bps / 10000",
        "unit": "basis_points_per_side",
        "source": "研究请求参数；当前未从行情源推断费率",
    },
]


class InsufficientFactorData(ValueError):
    """Raised when the input cannot support an honest train/test evaluation."""


@dataclass(frozen=True)
class ResearchConfig:
    horizon: int = 5
    periods_per_year: int = 252
    transaction_cost_bps: float = 10.0
    train_ratio: float = 0.7
    minimum_rows: int = 100
    significance_level: float = 0.05
    walk_forward_mode: str = "expanding"
    walk_forward_folds: int = 3


def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty or "close" not in frame.columns:
        raise InsufficientFactorData("K线为空或缺少 close 字段")
    data = frame.copy()
    if "datetime" in data.columns:
        parsed = pd.to_datetime(data["datetime"], errors="coerce")
        if parsed.notna().any():
            data = data.assign(datetime=parsed).sort_values("datetime")
    for column in ("open", "high", "low", "close", "volume"):
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.loc[data["close"].gt(0)].drop_duplicates(
        subset=["datetime"] if "datetime" in data.columns else None, keep="last"
    )
    return data.reset_index(drop=True)


def _safe_corr(left: pd.Series, right: pd.Series, method: str = "pearson") -> float:
    pair = pd.concat([left, right], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(pair) < 10 or pair.iloc[:, 0].nunique() < 2 or pair.iloc[:, 1].nunique() < 2:
        return 0.0
    if method == "spearman":
        pair = pair.rank(method="average")
    value = pair.iloc[:, 0].corr(pair.iloc[:, 1], method="pearson")
    return float(value) if pd.notna(value) else 0.0


def _factor_series(data: pd.DataFrame) -> dict[str, pd.Series]:
    close = data["close"]
    high = data.get("high", close)
    low = data.get("low", close)
    returns = close.pct_change()
    ema20 = close.ewm(span=20, adjust=False, min_periods=20).mean()
    ema60 = close.ewm(span=60, adjust=False, min_periods=60).mean()
    mean20 = close.rolling(20, min_periods=20).mean()
    std20 = close.rolling(20, min_periods=20).std(ddof=0).replace(0, np.nan)
    low20 = close.rolling(20, min_periods=20).min()
    high20 = close.rolling(20, min_periods=20).max()
    delta = close.diff()
    average_gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    average_loss = delta.clip(upper=0).abs().ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    relative_strength = average_gain.div(average_loss.replace(0, np.nan))
    rsi = 100 - 100 / (1 + relative_strength)
    rsi = rsi.mask(average_loss.eq(0) & average_gain.gt(0), 100).fillna(50)
    ema12 = close.ewm(span=12, adjust=False, min_periods=26).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    macd = ema12.sub(ema26)
    macd_signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    previous_close = close.shift(1)
    true_range = pd.concat(
        [high.sub(low), high.sub(previous_close).abs(), low.sub(previous_close).abs()], axis=1
    ).max(axis=1)
    atr14 = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    up_move = high.diff()
    down_move = low.shift(1).sub(low)
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    plus_di = plus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().div(atr14).mul(100)
    minus_di = minus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().div(atr14).mul(100)
    dx = plus_di.sub(minus_di).abs().div(plus_di.add(minus_di).replace(0, np.nan)).mul(100)
    adx = dx.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    factors: dict[str, pd.Series] = {
        "trend_strength": ema20.div(ema60).sub(1),
        "momentum_20": close.pct_change(20),
        "macd_histogram": macd.sub(macd_signal).div(close),
        "adx_direction": plus_di.sub(minus_di).div(100).mul(adx.div(100)),
        "mean_reversion": mean20.sub(close).div(std20),
        "rsi_reversal": pd.Series(50, index=data.index).sub(rsi).div(50),
        "bollinger_reversal": mean20.sub(close).div(std20.mul(2)),
        "breakout_20": close.sub(low20).div(high20.sub(low20).replace(0, np.nan)).sub(0.5),
        "low_volatility": returns.rolling(20, min_periods=20).std(ddof=0).mul(-1),
        "atr_contraction": atr14.div(close).mul(-1),
        "downside_risk": returns.clip(upper=0).rolling(20, min_periods=20).std(ddof=0).mul(-1),
    }
    if "volume" in data.columns and data["volume"].notna().any():
        volume = data["volume"].clip(lower=0)
        relative_volume = volume.div(volume.rolling(20, min_periods=20).mean()).sub(1)
        factors["volume_confirmation"] = close.pct_change(5).mul(relative_volume.clip(-3, 3))
        obv = np.sign(returns.fillna(0)).mul(volume).cumsum()
        factors["obv_momentum"] = obv.diff(20).div(volume.rolling(20, min_periods=20).sum())
        money_flow_multiplier = (
            close.mul(2).sub(high).sub(low).div(high.sub(low).replace(0, np.nan))
        )
        factors["chaikin_flow"] = (
            money_flow_multiplier.mul(volume)
            .rolling(20, min_periods=20)
            .sum()
            .div(volume.rolling(20, min_periods=20).sum().replace(0, np.nan))
        )
    else:
        factors["volume_confirmation"] = pd.Series(np.nan, index=data.index)
        factors["obv_momentum"] = pd.Series(np.nan, index=data.index)
        factors["chaikin_flow"] = pd.Series(np.nan, index=data.index)
    return factors


def _rolling_ic(factor: pd.Series, forward_return: pd.Series, window: int = 60) -> pd.Series:
    values = pd.Series(np.nan, index=factor.index, dtype=float)
    for end in range(window - 1, len(factor)):
        start = end - window + 1
        values.iloc[end] = _safe_corr(
            factor.iloc[start : end + 1], forward_return.iloc[start : end + 1], "spearman"
        )
    return values


def _correlation_p_value(correlation: float, observations: int) -> float:
    if observations < 4 or abs(correlation) >= 1:
        return 0.0 if abs(correlation) >= 1 else 1.0
    statistic = abs(correlation) * math.sqrt((observations - 2) / max(1 - correlation**2, 1e-12))
    return math.erfc(statistic / math.sqrt(2))


def _newey_west_correlation_test(
    left: pd.Series,
    right: pd.Series,
    max_lag: int,
) -> tuple[float, int, int]:
    """Return a two-sided HAC p-value and its correlation-equivalent sample size."""
    pair = pd.concat([left, right], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    observations = len(pair)
    if observations < 4 or pair.iloc[:, 0].nunique() < 2 or pair.iloc[:, 1].nunique() < 2:
        return 1.0, observations, 0

    ranked = pair.rank(method="average").to_numpy(dtype=float)
    dependent = ranked[:, 1]
    design = np.column_stack([np.ones(observations), ranked[:, 0]])
    coefficients = np.linalg.lstsq(design, dependent, rcond=None)[0]
    residuals = dependent - design @ coefficients
    scores = design * residuals[:, None]
    meat = scores.T @ scores
    lag_count = min(max(int(max_lag), 0), observations - 1)
    for lag in range(1, lag_count + 1):
        weight = 1 - lag / (lag_count + 1)
        cross = scores[lag:].T @ scores[:-lag]
        meat += weight * (cross + cross.T)

    inverse_information = np.linalg.pinv(design.T @ design)
    covariance = inverse_information @ meat @ inverse_information
    if observations > design.shape[1]:
        covariance *= observations / (observations - design.shape[1])
    variance = max(float(covariance[1, 1]), 0.0)
    if variance <= 1e-20:
        p_value = 0.0 if abs(float(coefficients[1])) > 1e-12 else 1.0
        return p_value, observations, lag_count

    statistic = abs(float(coefficients[1])) / math.sqrt(variance)
    p_value = math.erfc(statistic / math.sqrt(2))
    correlation = float(pd.Series(ranked[:, 0]).corr(pd.Series(ranked[:, 1])))
    if abs(correlation) <= 1e-12:
        effective_observations = observations
    else:
        implied = 2 + statistic**2 * max(1 - correlation**2, 0) / correlation**2
        effective_observations = int(round(min(max(implied, 3), observations)))
    return min(max(p_value, 0.0), 1.0), effective_observations, lag_count


def _data_fingerprint(data: pd.DataFrame) -> str:
    columns = [
        column
        for column in ("datetime", "open", "high", "low", "close", "volume")
        if column in data.columns
    ]
    canonical = data[columns].to_csv(
        index=False,
        date_format="%Y-%m-%dT%H:%M:%S.%f",
        float_format="%.12g",
        na_rep="",
        lineterminator="\n",
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _range_metadata(data: pd.DataFrame, start: int, end: int) -> dict[str, Any]:
    return {
        "start_index": start,
        "end_index": end - 1,
        "start": _timestamp(data, start) if end > start else None,
        "end": _timestamp(data, end - 1) if end > start else None,
        "rows": max(end - start, 0),
    }


def _walk_forward_windows(data: pd.DataFrame, config: ResearchConfig) -> list[dict[str, Any]]:
    if config.walk_forward_mode not in {"expanding", "rolling"}:
        raise ValueError("walk_forward_mode 必须为 expanding 或 rolling")
    if config.walk_forward_folds < 1:
        raise ValueError("walk_forward_folds 必须大于等于 1")

    initial_test_start = int(len(data) * config.train_ratio)
    test_rows = len(data) - initial_test_start
    fold_count = min(config.walk_forward_folds, max(1, test_rows // 20))
    boundaries = np.linspace(initial_test_start, len(data), fold_count + 1, dtype=int)
    base_train_rows = max(initial_test_start - config.horizon, 1)
    windows = []
    for fold in range(fold_count):
        test_start = int(boundaries[fold])
        test_end = int(boundaries[fold + 1])
        purge_start = max(0, test_start - config.horizon)
        train_start = 0
        if config.walk_forward_mode == "rolling":
            train_start = max(0, purge_start - base_train_rows)
        windows.append(
            {
                "fold": fold + 1,
                "mode": config.walk_forward_mode,
                "train": _range_metadata(data, train_start, purge_start),
                "purge": _range_metadata(data, purge_start, test_start),
                "test": _range_metadata(data, test_start, test_end),
            }
        )
    return windows


def _benjamini_hochberg(p_values: list[float]) -> list[float]:
    """Return monotonic false-discovery-rate adjusted p-values."""
    if not p_values:
        return []
    ordered = sorted(enumerate(p_values), key=lambda item: item[1])
    adjusted = [1.0] * len(p_values)
    running_minimum = 1.0
    for rank, (original_index, p_value) in reversed(list(enumerate(ordered, start=1))):
        running_minimum = min(running_minimum, float(p_value) * len(p_values) / rank)
        adjusted[original_index] = min(max(running_minimum, 0.0), 1.0)
    return adjusted


def _apply_multiple_testing_control(
    evaluations: list[dict[str, Any]], significance_level: float
) -> None:
    adjusted = _benjamini_hochberg([float(item.pop("_p_value_raw")) for item in evaluations])
    for item, adjusted_p_value in zip(evaluations, adjusted, strict=True):
        significant = adjusted_p_value <= significance_level
        item["adjusted_p_value"] = round(adjusted_p_value, 4)
        item["statistically_significant"] = significant
        if item["status"] == "usable" and not significant:
            item["status"] = "watch"


def _evaluate_factor(
    key: str,
    factor: pd.Series,
    forward_return: pd.Series,
    decay_forwards: dict[int, pd.Series],
    windows: list[dict[str, Any]],
    horizon: int,
) -> dict[str, Any]:
    valid = pd.concat([factor.rename("factor"), forward_return.rename("forward")], axis=1).dropna()
    window_results: list[dict[str, Any]] = []
    directed_test_factors: list[pd.Series] = []
    directed_test_returns: list[pd.Series] = []
    learned_directions: list[int] = []
    final_train = valid.iloc[0:0]
    final_test = valid.iloc[0:0]
    for window in windows:
        train_range = window["train"]
        test_range = window["test"]
        train = valid.loc[
            (valid.index >= train_range["start_index"]) & (valid.index <= train_range["end_index"])
        ]
        test = valid.loc[
            (valid.index >= test_range["start_index"]) & (valid.index <= test_range["end_index"])
        ]
        train_ic_raw = _safe_corr(train["factor"], train["forward"], "spearman")
        learned_direction = 1 if train_ic_raw >= 0 else -1
        test_ic = _safe_corr(test["factor"], test["forward"], "spearman") * learned_direction
        directed_factor = test["factor"].mul(learned_direction)
        hit_rate = float(directed_factor.mul(test["forward"]).gt(0).mean()) if len(test) else 0.0
        enough = len(train) >= 40 and len(test) >= 20
        window_status = (
            "pass"
            if enough and test_ic >= 0.03 and hit_rate >= 0.5
            else "watch"
            if enough and test_ic > 0
            else "reject"
        )
        window_p_value, window_effective, window_hac_lags = _newey_west_correlation_test(
            directed_factor,
            test["forward"],
            max(horizon - 1, 0),
        )
        window_results.append(
            {
                **window,
                "direction": "positive" if learned_direction > 0 else "inverse",
                "train_observations": len(train),
                "test_observations": len(test),
                "train_ic": round(abs(train_ic_raw), 4),
                "test_ic": round(test_ic, 4),
                "hit_rate": round(hit_rate, 4),
                "p_value": round(window_p_value, 4),
                "effective_observations": window_effective,
                "hac_lags": window_hac_lags,
                "status": window_status,
            }
        )
        directed_test_factors.append(directed_factor)
        directed_test_returns.append(test["forward"])
        learned_directions.append(learned_direction)
        final_train = train
        final_test = test

    learned_direction = learned_directions[-1]
    train_ic = _safe_corr(final_train["factor"], final_train["forward"], "spearman")
    window_ics = [float(item["test_ic"]) for item in window_results]
    test_ic = float(np.median(window_ics)) if window_ics else 0.0
    directed_test_factor = pd.concat(directed_test_factors).sort_index()
    directed_test_return = pd.concat(directed_test_returns).sort_index()
    full_ic = _safe_corr(valid["factor"], valid["forward"], "spearman") * learned_direction
    pearson_ic = _safe_corr(valid["factor"], valid["forward"], "pearson") * learned_direction
    rolling = _rolling_ic(
        directed_test_factor.reset_index(drop=True), directed_test_return.reset_index(drop=True)
    )
    rolling_valid = rolling.dropna()
    rolling_ic_mean = float(rolling_valid.mean()) if len(rolling_valid) else test_ic
    rolling_ic_std = float(rolling_valid.std(ddof=0)) if len(rolling_valid) else 0.0
    icir = rolling_ic_mean / rolling_ic_std if rolling_ic_std > 0 else 0.0
    positive_ic_ratio = (
        float(rolling_valid.gt(0).mean()) if len(rolling_valid) else float(test_ic > 0)
    )
    decay = []
    final_test_start = windows[-1]["test"]["start_index"]
    final_test_end = windows[-1]["test"]["end_index"]
    for decay_horizon, decay_forward in decay_forwards.items():
        decay_test = pd.concat(
            [factor.rename("factor"), decay_forward.rename("forward")], axis=1
        ).dropna()
        decay_test = decay_test.loc[
            (decay_test.index >= final_test_start) & (decay_test.index <= final_test_end)
        ]
        decay_ic = _safe_corr(decay_test["factor"], decay_test["forward"], "spearman")
        decay.append({"horizon": decay_horizon, "ic": round(decay_ic * learned_direction, 4)})
    if len(directed_test_factor):
        aligned = directed_test_factor.mul(directed_test_return)
        hit_rate = float(aligned.gt(0).mean())
    else:
        hit_rate = 0.0
    passed_windows = sum(item["status"] == "pass" for item in window_results)
    multi_window_consistent = passed_windows > len(window_results) / 2
    stable = multi_window_consistent and test_ic > 0 and positive_ic_ratio >= 0.5
    enough = len(valid) >= 60 and len(directed_test_factor) >= 20
    score = 100 * (
        0.35 * min(max(test_ic, 0) / 0.15, 1)
        + 0.20 * min(max(icir, 0), 1)
        + 0.20 * min(max(hit_rate - 0.5, 0) / 0.1, 1)
        + 0.15 * positive_ic_ratio
        + 0.10 * float(stable)
    )
    status = "usable" if enough and stable and test_ic >= 0.03 and hit_rate >= 0.5 else "watch"
    if not enough or test_ic <= 0:
        status = "reject"
    p_value, effective_observations, hac_lags = _newey_west_correlation_test(
        directed_test_factor,
        directed_test_return,
        max(horizon - 1, 0),
    )
    status_transitions = sum(
        current["status"] != previous["status"] for previous, current in pairwise(window_results)
    )
    direction_flips = sum(current != previous for previous, current in pairwise(learned_directions))
    window_ic_iqr = (
        float(np.percentile(window_ics, 75) - np.percentile(window_ics, 25)) if window_ics else 0.0
    )
    label, category, description = FACTOR_META[key]
    return {
        "key": key,
        "label": label,
        "category": category,
        "description": description,
        "formula": FACTOR_FORMULAS[key],
        "formula_version": FACTOR_FORMULA_VERSION,
        "direction": "positive" if learned_direction > 0 else "inverse",
        "status": status,
        "score": round(score, 1),
        "ic": round(full_ic, 4),
        "rank_ic": round(full_ic, 4),
        "pearson_ic": round(pearson_ic, 4),
        "train_ic": round(abs(train_ic), 4),
        "test_ic": round(test_ic, 4),
        "rolling_ic_mean": round(rolling_ic_mean, 4),
        "rolling_ic_std": round(rolling_ic_std, 4),
        "icir": round(icir, 3),
        "positive_ic_ratio": round(positive_ic_ratio, 4),
        "p_value": round(p_value, 4),
        "_p_value_raw": p_value,
        "p_value_method": "newey_west_hac",
        "hac_lags": hac_lags,
        "decay": decay,
        "hit_rate": round(hit_rate, 4),
        "observations": len(valid),
        "test_observations": len(directed_test_factor),
        "effective_observations": effective_observations,
        "effective_observations_basis": "hac_implied",
        "stable": stable,
        "window_pass_rate": round(passed_windows / len(window_results), 4),
        "passed_windows": passed_windows,
        "window_count": len(window_results),
        "worst_window_ic": round(min(window_ics), 4) if window_ics else 0.0,
        "median_window_ic": round(test_ic, 4),
        "window_ic_iqr": round(window_ic_iqr, 4),
        "status_transitions": status_transitions,
        "direction_flips": direction_flips,
        "multi_window_consistent": multi_window_consistent,
        "windows": window_results,
        "learned_direction": learned_direction,
    }


def _position_from_signal(signal: pd.Series, entry: float = 0.0, exit_: float = 0.0) -> pd.Series:
    position = pd.Series(0.0, index=signal.index)
    held = 0.0
    for index, value in signal.items():
        if pd.isna(value):
            position.loc[index] = held
            continue
        if held == 0 and value > entry:
            held = 1.0
        elif held == 1 and value < exit_:
            held = 0.0
        position.loc[index] = held
    return position


def _strategy_metrics(
    key: str,
    returns: pd.Series,
    position: pd.Series,
    config: ResearchConfig,
) -> tuple[dict[str, Any], pd.Series, pd.Series]:
    held = position.shift(1).fillna(0).clip(0, 1)
    turnover = held.diff().abs().fillna(held.abs())
    net = held.mul(returns.fillna(0)).sub(turnover.mul(config.transaction_cost_bps / 10_000))
    equity = (1 + net).cumprod()
    drawdown = equity.div(equity.cummax()).sub(1)
    years = max(len(net) / config.periods_per_year, 1 / config.periods_per_year)
    annual_return = float(equity.iloc[-1] ** (1 / years) - 1) if len(equity) else 0.0
    annual_vol = float(net.std(ddof=0) * np.sqrt(config.periods_per_year))
    sharpe = annual_return / annual_vol if annual_vol > 0 else 0.0
    downside = net.clip(upper=0)
    downside_deviation = float(np.sqrt(downside.pow(2).mean()) * np.sqrt(config.periods_per_year))
    sortino = annual_return / downside_deviation if downside_deviation > 0 else 0.0
    max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0
    calmar = annual_return / abs(max_drawdown) if max_drawdown < 0 else 0.0
    var_95 = float(net.quantile(0.05)) if len(net) else 0.0
    tail = net.loc[net.le(var_95)]
    cvar_95 = float(tail.mean()) if len(tail) else var_95
    ulcer_index = float(np.sqrt(drawdown.pow(2).mean())) if len(drawdown) else 0.0
    duration = 0
    max_drawdown_duration = 0
    for underwater in drawdown.lt(0):
        duration = duration + 1 if underwater else 0
        max_drawdown_duration = max(max_drawdown_duration, duration)
    trade_returns, holding_lengths, open_trade = _closed_trade_returns(net, held)
    gains = sum(value for value in trade_returns if value > 0)
    losses = abs(sum(value for value in trade_returns if value < 0))
    profit_factor = gains / losses if losses > 0 else (99.0 if gains > 0 else 0.0)
    win_rate = (
        sum(value > 0 for value in trade_returns) / len(trade_returns) if trade_returns else 0.0
    )
    winning_returns = [value for value in trade_returns if value > 0]
    losing_returns = [value for value in trade_returns if value < 0]
    average_win = float(np.mean(winning_returns)) if winning_returns else 0.0
    average_loss = float(np.mean(losing_returns)) if losing_returns else 0.0
    payoff_ratio = average_win / abs(average_loss) if average_loss < 0 else 0.0
    trades = int(held.diff().fillna(held).gt(0).sum())
    result = {
        "key": key,
        "label": METHOD_META[key],
        "total_return": round(float(equity.iloc[-1] - 1), 4) if len(equity) else 0.0,
        "annual_return": round(annual_return, 4),
        "sharpe": round(float(sharpe), 3),
        "annual_volatility": round(annual_vol, 4),
        "downside_deviation": round(downside_deviation, 4),
        "sortino": round(float(sortino), 3),
        "calmar": round(float(calmar), 3),
        "risk_adjusted_score": round(0.4 * sharpe + 0.35 * sortino + 0.25 * calmar, 3),
        "max_drawdown": round(max_drawdown, 4),
        "var_95": round(var_95, 4),
        "cvar_95": round(cvar_95, 4),
        "ulcer_index": round(ulcer_index, 4),
        "profit_factor": round(min(profit_factor, 99.0), 3),
        "profit_factor_basis": "closed_trades",
        "max_drawdown_duration": max_drawdown_duration,
        "average_holding_period": round(float(np.mean(holding_lengths)), 1)
        if holding_lengths
        else 0.0,
        "win_rate": round(win_rate, 4),
        "win_rate_basis": "closed_trades",
        "closed_trades": len(trade_returns),
        "open_trade": open_trade,
        "average_trade_return": round(float(np.mean(trade_returns)), 4) if trade_returns else 0.0,
        "average_win": round(average_win, 4),
        "average_loss": round(average_loss, 4),
        "payoff_ratio": round(payoff_ratio, 3),
        "turnover": round(float(turnover.sum()), 2),
        "trades": trades,
        "exposure": round(float(held.mean()), 4),
    }
    return result, equity, drawdown


def _closed_trade_returns(
    net_returns: pd.Series,
    held: pd.Series,
) -> tuple[list[float], list[int], bool]:
    trade_returns: list[float] = []
    holding_lengths: list[int] = []
    active = False
    growth = 1.0
    holding_period = 0
    previous_held = False
    for index in held.index:
        is_held = bool(held.loc[index] > 0)
        period_return = float(net_returns.loc[index])
        if is_held and not previous_held:
            active = True
            growth = 1 + period_return
            holding_period = 1
        elif active and is_held:
            growth *= 1 + period_return
            holding_period += 1
        elif active and not is_held:
            growth *= 1 + period_return
            trade_returns.append(growth - 1)
            holding_lengths.append(holding_period)
            active = False
            growth = 1.0
            holding_period = 0
        previous_held = is_held
    return trade_returns, holding_lengths, active


def _strategy_total_return_at_cost(
    returns: pd.Series,
    position: pd.Series,
    transaction_cost_bps: float,
) -> float:
    held = position.shift(1).fillna(0).clip(0, 1)
    turnover = held.diff().abs().fillna(held.abs())
    net = held.mul(returns.fillna(0)).sub(turnover.mul(transaction_cost_bps / 10_000))
    return float((1 + net).prod() - 1)


def _cost_sensitivity(
    returns: pd.Series,
    position: pd.Series,
    config: ResearchConfig,
) -> dict[str, Any]:
    cost_levels = sorted({0.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, config.transaction_cost_bps})
    curve = [
        {
            "transaction_cost_bps": cost,
            "total_return": round(_strategy_total_return_at_cost(returns, position, cost), 4),
        }
        for cost in cost_levels
    ]
    zero_cost_return = _strategy_total_return_at_cost(returns, position, 0.0)
    maximum_cost = 1_000.0
    maximum_cost_return = _strategy_total_return_at_cost(returns, position, maximum_cost)
    breakeven: float | None
    if zero_cost_return <= 0:
        breakeven = 0.0
    elif maximum_cost_return > 0:
        breakeven = None
    else:
        lower, upper = 0.0, maximum_cost
        for _ in range(40):
            midpoint = (lower + upper) / 2
            if _strategy_total_return_at_cost(returns, position, midpoint) > 0:
                lower = midpoint
            else:
                upper = midpoint
        breakeven = round((lower + upper) / 2, 2)
    return {
        "basis": "multifactor_final_out_of_sample_window",
        "curve": curve,
        "breakeven_transaction_cost_bps": breakeven,
    }


def _indicator_snapshot(data: pd.DataFrame, periods_per_year: int) -> list[dict[str, Any]]:
    close = data["close"]
    high = data["high"]
    low = data["low"]
    returns = close.pct_change()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = delta.clip(upper=0).abs().ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rsi = 100 - 100 / (1 + gain.div(loss.replace(0, np.nan)))
    rsi = rsi.mask(loss.eq(0) & gain.gt(0), 100).fillna(50)
    macd = close.ewm(span=12, adjust=False).mean().sub(close.ewm(span=26, adjust=False).mean())
    macd_hist = macd.sub(macd.ewm(span=9, adjust=False).mean())
    previous_close = close.shift(1)
    true_range = pd.concat(
        [high.sub(low), high.sub(previous_close).abs(), low.sub(previous_close).abs()], axis=1
    ).max(axis=1)
    atr = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    up_move = high.diff()
    down_move = low.shift(1).sub(low)
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    plus_di = plus_dm.ewm(alpha=1 / 14, adjust=False).mean().div(atr).mul(100)
    minus_di = minus_dm.ewm(alpha=1 / 14, adjust=False).mean().div(atr).mul(100)
    dx = plus_di.sub(minus_di).abs().div(plus_di.add(minus_di).replace(0, np.nan)).mul(100)
    adx = dx.ewm(alpha=1 / 14, adjust=False).mean()
    mean20 = close.rolling(20).mean()
    std20 = close.rolling(20).std(ddof=0)
    bollinger_b = close.sub(mean20.sub(std20.mul(2))).div(std20.mul(4).replace(0, np.nan))
    realized_vol = returns.rolling(20).std(ddof=0).mul(math.sqrt(periods_per_year))
    downside_vol = (
        returns.clip(upper=0).pow(2).rolling(20).mean().pow(0.5).mul(math.sqrt(periods_per_year))
    )
    if "volume" in data and data["volume"].notna().any():
        relative_volume = data["volume"].div(data["volume"].rolling(20).mean())
    else:
        relative_volume = pd.Series(np.nan, index=data.index)

    latest_rsi = float(rsi.iloc[-1])
    latest_macd = float(macd_hist.iloc[-1] / close.iloc[-1])
    latest_adx = float(adx.iloc[-1])
    latest_atr = float(atr.iloc[-1] / close.iloc[-1])
    latest_bollinger = float(bollinger_b.iloc[-1])
    latest_volume = float(relative_volume.iloc[-1]) if pd.notna(relative_volume.iloc[-1]) else None
    latest_realized = float(realized_vol.iloc[-1])
    latest_downside = float(downside_vol.iloc[-1])
    return [
        {
            "key": "rsi_14",
            "label": "RSI(14)",
            "value": round(latest_rsi, 2),
            "state": "negative"
            if latest_rsi >= 70
            else "positive"
            if latest_rsi <= 30
            else "neutral",
            "interpretation": "超买"
            if latest_rsi >= 70
            else "超卖"
            if latest_rsi <= 30
            else "中性",
        },
        {
            "key": "macd_histogram",
            "label": "MACD 柱 / 价格",
            "value": round(latest_macd, 6),
            "state": "positive" if latest_macd > 0 else "negative",
            "interpretation": "多头动能" if latest_macd > 0 else "空头动能",
        },
        {
            "key": "adx_14",
            "label": "ADX(14)",
            "value": round(latest_adx, 2),
            "state": "positive" if latest_adx >= 25 else "neutral",
            "interpretation": "趋势明确" if latest_adx >= 25 else "震荡为主",
        },
        {
            "key": "atr_pct",
            "label": "ATR(14) / 价格",
            "value": round(latest_atr, 4),
            "state": "negative" if latest_atr >= 0.04 else "neutral",
            "interpretation": "高波动" if latest_atr >= 0.04 else "常规波动",
        },
        {
            "key": "bollinger_b",
            "label": "布林 %B",
            "value": round(latest_bollinger, 3),
            "state": "negative"
            if latest_bollinger > 1
            else "positive"
            if latest_bollinger < 0
            else "neutral",
            "interpretation": "上轨外"
            if latest_bollinger > 1
            else "下轨外"
            if latest_bollinger < 0
            else "通道内",
        },
        {
            "key": "relative_volume",
            "label": "相对成交量",
            "value": round(latest_volume, 3) if latest_volume is not None else None,
            "state": "positive"
            if latest_volume is not None and latest_volume >= 1.5
            else "neutral",
            "interpretation": "显著放量"
            if latest_volume is not None and latest_volume >= 1.5
            else "常规量能",
        },
        {
            "key": "realized_volatility",
            "label": "年化实现波动",
            "value": round(latest_realized, 4),
            "state": "negative" if latest_realized >= 0.4 else "neutral",
            "interpretation": "风险偏高" if latest_realized >= 0.4 else "风险可控",
        },
        {
            "key": "downside_volatility",
            "label": "年化下行波动",
            "value": round(latest_downside, 4),
            "state": "negative" if latest_downside >= 0.25 else "neutral",
            "interpretation": "下行风险偏高" if latest_downside >= 0.25 else "下行风险常规",
        },
    ]


def _select_training_factors(
    evaluations: list[dict[str, Any]],
    directional: dict[str, pd.Series],
    train_start: int,
    train_end: int,
    limit: int = 4,
) -> list[dict[str, Any]]:
    candidates = sorted(evaluations, key=lambda item: item["train_ic"], reverse=True)
    selected: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate["train_ic"] < 0.03:
            continue
        series = directional[candidate["key"]].iloc[train_start:train_end]
        redundant = any(
            abs(
                _safe_corr(
                    series,
                    directional[item["key"]].iloc[train_start:train_end],
                )
            )
            >= 0.80
            for item in selected
        )
        if not redundant:
            selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected or candidates[: min(3, len(candidates))]


def _timestamp(data: pd.DataFrame, index: int) -> str:
    if "datetime" in data.columns and pd.notna(data.iloc[index]["datetime"]):
        value = data.iloc[index]["datetime"]
        return value.isoformat() if hasattr(value, "isoformat") else str(value)
    return str(index)


def _sample_curve(
    data: pd.DataFrame, values: dict[str, pd.Series], max_points: int = 320
) -> list[dict]:
    if data.empty:
        return []
    indexes = list(range(0, len(data), max(1, len(data) // max_points)))
    if indexes[-1] != len(data) - 1:
        indexes.append(len(data) - 1)
    points = []
    for index in indexes:
        point: dict[str, Any] = {"t": _timestamp(data, index)}
        for key, series in values.items():
            value = series.iloc[index]
            point[key] = round(float(value), 6) if pd.notna(value) and np.isfinite(value) else None
        points.append(point)
    return points


def _drawdown_level(value: float) -> tuple[str, str, str]:
    if value <= -0.15:
        return "risk_off", "风险退出", "回撤超过 15%，停止新增仓位并检查策略失效"
    if value <= -0.10:
        return "reduce", "减仓", "回撤超过 10%，降低风险敞口并收紧止损"
    if value <= -0.05:
        return "watch", "观察", "回撤超过 5%，暂停加仓并等待结构修复"
    return "normal", "正常", "回撤处于常规波动区间"


def _drawdown_signals(data: pd.DataFrame, drawdown: pd.Series) -> tuple[dict, list[dict]]:
    levels = drawdown.fillna(0).map(lambda value: _drawdown_level(float(value))[0])
    changes = levels.ne(levels.shift(1))
    events = []
    for index in levels.index[changes][-12:]:
        code, label, guidance = _drawdown_level(float(drawdown.loc[index]))
        events.append(
            {
                "t": _timestamp(data, int(index)),
                "level": code,
                "label": label,
                "drawdown": round(float(drawdown.loc[index]), 4),
                "guidance": guidance,
            }
        )
    latest = float(drawdown.iloc[-1])
    code, label, guidance = _drawdown_level(latest)
    five_bars_ago = float(drawdown.iloc[-6]) if len(drawdown) >= 6 else latest
    if code in {"normal", "watch"} and latest - five_bars_ago >= 0.02:
        code, label, guidance = (
            "recovery",
            "修复",
            "回撤在 5 个周期内修复超过 2%，等待趋势确认后再恢复仓位",
        )
    return {
        "level": code,
        "label": label,
        "drawdown": round(latest, 4),
        "guidance": guidance,
    }, events


def analyze_factors(frame: pd.DataFrame, config: ResearchConfig | None = None) -> dict[str, Any]:
    """Evaluate factors, compare rule-based methods and produce drawdown signals."""
    config = config or ResearchConfig()
    data = _clean_frame(frame)
    required = max(config.minimum_rows, 60 + config.horizon)
    if len(data) < required:
        raise InsufficientFactorData(f"有效 K 线不足：需要至少 {required} 条，实际 {len(data)} 条")

    close = data["close"]
    returns = close.pct_change().fillna(0)
    forward_return = close.shift(-config.horizon).div(close).sub(1)
    decay_forwards = {
        horizon: close.shift(-horizon).div(close).sub(1) for horizon in (1, 3, 5, 10, 20)
    }
    factors = _factor_series(data)
    windows = _walk_forward_windows(data, config)
    final_window = windows[-1]
    split_index = int(final_window["test"]["start_index"])
    train_start = int(final_window["train"]["start_index"])
    train_end = int(final_window["train"]["end_index"]) + 1
    evaluations = [
        _evaluate_factor(key, factor, forward_return, decay_forwards, windows, config.horizon)
        for key, factor in factors.items()
    ]
    _apply_multiple_testing_control(evaluations, config.significance_level)
    evaluations.sort(key=lambda item: (item["status"] == "usable", item["score"]), reverse=True)

    directions = {item["key"]: item["learned_direction"] for item in evaluations}
    directional = {key: series.mul(directions.get(key, 1)) for key, series in factors.items()}
    usable = [item for item in evaluations if item["status"] == "usable"]
    selected = _select_training_factors(evaluations, directional, train_start, train_end)
    selected_keys = [item["key"] for item in selected]
    raw_weights = {item["key"]: max(float(item["train_ic"]), 0.001) for item in selected}
    total_weight = sum(raw_weights.values()) or 1.0
    weights = {key: value / total_weight for key, value in raw_weights.items()}
    normalized: list[pd.Series] = []
    for key in selected_keys:
        series = directional[key]
        rolling_mean = series.rolling(60, min_periods=20).mean()
        rolling_std = series.rolling(60, min_periods=20).std(ddof=0).replace(0, np.nan)
        normalized.append(series.sub(rolling_mean).div(rolling_std).clip(-3, 3).mul(weights[key]))
    composite = (
        pd.concat(normalized, axis=1).sum(axis=1, min_count=1)
        if normalized
        else pd.Series(0, index=data.index)
    )

    for item in evaluations:
        item["selected"] = item["key"] in weights
        item["weight"] = round(weights.get(item["key"], 0.0), 4)

    positions = {
        "buy_hold": pd.Series(1.0, index=data.index),
        "trend": _position_from_signal(directional["trend_strength"], 0.0, -0.005),
        "momentum": _position_from_signal(directional["momentum_20"], 0.02, -0.01),
        "mean_reversion": _position_from_signal(directional["mean_reversion"], 0.75, -0.1),
        "breakout": _position_from_signal(directional["breakout_20"], 0.4, -0.05),
        "multifactor": _position_from_signal(composite, 0.25, -0.25),
    }
    methods, curves, drawdowns = [], {}, {}
    test_data = data.iloc[split_index:].reset_index(drop=True)
    test_returns = returns.iloc[split_index:].reset_index(drop=True)
    for key, position in positions.items():
        test_position = position.iloc[split_index:].reset_index(drop=True)
        metrics, equity, drawdown = _strategy_metrics(key, test_returns, test_position, config)
        methods.append(metrics)
        curves[key] = equity
        drawdowns[key] = drawdown
    methods.sort(
        key=lambda item: (item["risk_adjusted_score"], item["annual_return"]), reverse=True
    )
    multifactor_test_position = positions["multifactor"].iloc[split_index:].reset_index(drop=True)
    cost_analysis = _cost_sensitivity(test_returns, multifactor_test_position, config)

    full_asset_equity = close.div(close.iloc[0])
    full_asset_drawdown = full_asset_equity.div(full_asset_equity.cummax()).sub(1)
    current_signal, signal_events = _drawdown_signals(data, full_asset_drawdown)
    test_close = close.iloc[split_index:].reset_index(drop=True)
    asset_equity = test_close.div(test_close.iloc[0])
    asset_drawdown = asset_equity.div(asset_equity.cummax()).sub(1)
    multi_drawdown = drawdowns["multifactor"]
    current_signal["strategy_drawdown"] = round(float(multi_drawdown.iloc[-1]), 4)
    current_signal["asset_peak_drawdown"] = round(float(full_asset_drawdown.min()), 4)

    for item in evaluations:
        item.pop("learned_direction", None)
    method_lookup = {item["key"]: item for item in methods}
    return {
        "summary": {
            "rows": len(data),
            "train_rows": train_end - train_start,
            "purged_rows": int(final_window["purge"]["rows"]),
            "test_rows": len(data) - split_index,
            "walk_forward_test_rows": sum(int(window["test"]["rows"]) for window in windows),
            "horizon": config.horizon,
            "transaction_cost_bps": config.transaction_cost_bps,
            "significance_level": config.significance_level,
            "significance_method": "newey_west_hac_benjamini_hochberg",
            "walk_forward_mode": config.walk_forward_mode,
            "requested_walk_forward_folds": config.walk_forward_folds,
            "walk_forward_folds": len(windows),
            "window_pass_requirement": "strict_majority",
            "usable_factors": len(usable),
            "selected_factors": selected_keys,
            "best_factor": evaluations[0]["key"] if evaluations else None,
            "best_method": methods[0]["key"] if methods else None,
            "evaluation_scope": "walk_forward_out_of_sample",
            "engine_version": FACTOR_RESEARCH_ENGINE_VERSION,
            "factor_formula_version": FACTOR_FORMULA_VERSION,
            "data_fingerprint": _data_fingerprint(data),
            "research_period": {
                "start": _timestamp(data, 0),
                "end": _timestamp(data, len(data) - 1),
            },
            "thresholds": {
                "minimum_rank_ic": 0.03,
                "minimum_hit_rate": 0.5,
                "minimum_positive_ic_ratio": 0.5,
                "minimum_train_observations_per_window": 40,
                "minimum_test_observations_per_window": 20,
                "significance_level": config.significance_level,
                "window_pass_requirement": "strict_majority",
            },
            "windows": windows,
        },
        "factors": evaluations,
        "methods": methods,
        "indicators": _indicator_snapshot(data, config.periods_per_year),
        "current_signal": current_signal,
        "signal_events": signal_events,
        "latest": {
            "close": round(float(close.iloc[-1]), 4),
            "multifactor_position": int(positions["multifactor"].iloc[-1]),
            "multifactor_return": method_lookup["multifactor"]["total_return"],
        },
        "curve": _sample_curve(
            test_data,
            {
                "asset": asset_equity,
                "multifactor": curves["multifactor"],
                "asset_drawdown": asset_drawdown,
                "strategy_drawdown": multi_drawdown,
            },
        ),
        "method_curves": {
            key: _sample_curve(test_data, {"equity": equity}) for key, equity in curves.items()
        },
        "cost_analysis": cost_analysis,
        "methodology": {
            "split": (
                f"后 30% 样本划分为 {len(windows)} 个 {config.walk_forward_mode} "
                f"walk-forward 窗口，每个窗口隔离 {config.horizon} 个周期"
            ),
            "execution": "信号延迟一个周期执行，计入双边换手成本",
            "usable_rule": (
                "严格多数 walk-forward 窗口通过，样本外 Rank IC 中位数 >= 0.03、"
                "滚动 IC 正值占比 >= 50%、命中率 >= 50%，且 Newey-West HAC "
                "显著性经 Benjamini-Hochberg 校正后 <= 0.05"
            ),
            "warning": (
                "方法收益仅统计最后一个完全隔离的样本外窗口；历史统计不代表未来收益，"
                "仍需多标的横截面复核"
            ),
            "metric_definitions": METHOD_METRIC_DEFINITIONS,
        },
    }
