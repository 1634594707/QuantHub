"""Time-series factor evaluation and lightweight strategy comparison.

The module intentionally keeps factor formation and forward returns separated. Factor
direction is learned on the first 70% of the sample and evaluated on the remaining 30%,
which makes the reported ``usable`` status an out-of-sample result rather than an
in-sample fit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
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

METHOD_META = {
    "buy_hold": "买入持有",
    "trend": "趋势跟随",
    "momentum": "动量轮动",
    "mean_reversion": "均值回归",
    "breakout": "通道突破",
    "multifactor": "多因子组合",
}


class InsufficientFactorData(ValueError):
    """Raised when the input cannot support an honest train/test evaluation."""


@dataclass(frozen=True)
class ResearchConfig:
    horizon: int = 5
    periods_per_year: int = 252
    transaction_cost_bps: float = 10.0
    train_ratio: float = 0.7
    minimum_rows: int = 100


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


def _evaluate_factor(
    key: str,
    factor: pd.Series,
    forward_return: pd.Series,
    decay_forwards: dict[int, pd.Series],
    split_index: int,
    horizon: int,
) -> dict[str, Any]:
    valid = pd.concat([factor.rename("factor"), forward_return.rename("forward")], axis=1).dropna()
    purge_start = max(0, split_index - horizon)
    train = valid.loc[valid.index < purge_start]
    test = valid.loc[valid.index >= split_index]
    train_ic = _safe_corr(train["factor"], train["forward"], "spearman")
    learned_direction = 1 if train_ic >= 0 else -1
    test_ic_raw = _safe_corr(test["factor"], test["forward"], "spearman")
    test_ic = test_ic_raw * learned_direction
    full_ic = _safe_corr(valid["factor"], valid["forward"], "spearman") * learned_direction
    pearson_ic = _safe_corr(valid["factor"], valid["forward"], "pearson") * learned_direction
    directed_test_factor = test["factor"].mul(learned_direction)
    rolling = _rolling_ic(
        directed_test_factor.reset_index(drop=True), test["forward"].reset_index(drop=True)
    )
    rolling_valid = rolling.dropna()
    rolling_ic_mean = float(rolling_valid.mean()) if len(rolling_valid) else test_ic
    rolling_ic_std = float(rolling_valid.std(ddof=0)) if len(rolling_valid) else 0.0
    icir = rolling_ic_mean / rolling_ic_std if rolling_ic_std > 0 else 0.0
    positive_ic_ratio = (
        float(rolling_valid.gt(0).mean()) if len(rolling_valid) else float(test_ic > 0)
    )
    decay = []
    for decay_horizon, decay_forward in decay_forwards.items():
        decay_test = pd.concat(
            [factor.rename("factor"), decay_forward.rename("forward")], axis=1
        ).dropna()
        decay_test = decay_test.loc[decay_test.index >= split_index]
        decay_ic = _safe_corr(decay_test["factor"], decay_test["forward"], "spearman")
        decay.append({"horizon": decay_horizon, "ic": round(decay_ic * learned_direction, 4)})
    if len(test):
        aligned = test["factor"].mul(learned_direction).mul(test["forward"])
        hit_rate = float(aligned.gt(0).mean())
    else:
        hit_rate = 0.0
    stable = train_ic * learned_direction > 0 and test_ic > 0 and positive_ic_ratio >= 0.5
    enough = len(valid) >= 60 and len(test) >= 20
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
    label, category, description = FACTOR_META[key]
    return {
        "key": key,
        "label": label,
        "category": category,
        "description": description,
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
        "p_value": round(_correlation_p_value(test_ic, len(test)), 4),
        "decay": decay,
        "hit_rate": round(hit_rate, 4),
        "observations": len(valid),
        "test_observations": len(test),
        "stable": stable,
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
    gains = float(net.clip(lower=0).sum())
    losses = abs(float(net.clip(upper=0).sum()))
    profit_factor = gains / losses if losses > 0 else (99.0 if gains > 0 else 0.0)
    duration = 0
    max_drawdown_duration = 0
    for underwater in drawdown.lt(0):
        duration = duration + 1 if underwater else 0
        max_drawdown_duration = max(max_drawdown_duration, duration)
    holding_lengths: list[int] = []
    active_length = 0
    for is_held in held.gt(0):
        if is_held:
            active_length += 1
        elif active_length:
            holding_lengths.append(active_length)
            active_length = 0
    if active_length:
        holding_lengths.append(active_length)
    active = net.loc[held.gt(0)]
    win_rate = float(active.gt(0).mean()) if len(active) else 0.0
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
        "max_drawdown_duration": max_drawdown_duration,
        "average_holding_period": round(float(np.mean(holding_lengths)), 1)
        if holding_lengths
        else 0.0,
        "win_rate": round(win_rate, 4),
        "turnover": round(float(turnover.sum()), 2),
        "trades": trades,
        "exposure": round(float(held.mean()), 4),
    }
    return result, equity, drawdown


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
    train_end: int,
    limit: int = 4,
) -> list[dict[str, Any]]:
    candidates = sorted(evaluations, key=lambda item: item["train_ic"], reverse=True)
    selected: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate["train_ic"] < 0.03:
            continue
        series = directional[candidate["key"]].iloc[:train_end]
        redundant = any(
            abs(_safe_corr(series, directional[item["key"]].iloc[:train_end])) >= 0.80
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
    split_index = int(len(data) * config.train_ratio)
    train_end = max(0, split_index - config.horizon)
    evaluations = [
        _evaluate_factor(key, factor, forward_return, decay_forwards, split_index, config.horizon)
        for key, factor in factors.items()
    ]
    evaluations.sort(key=lambda item: (item["status"] == "usable", item["score"]), reverse=True)

    directions = {item["key"]: item["learned_direction"] for item in evaluations}
    directional = {key: series.mul(directions.get(key, 1)) for key, series in factors.items()}
    usable = [item for item in evaluations if item["status"] == "usable"]
    selected = _select_training_factors(evaluations, directional, train_end)
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
            "train_rows": train_end,
            "purged_rows": split_index - train_end,
            "test_rows": len(data) - split_index,
            "horizon": config.horizon,
            "transaction_cost_bps": config.transaction_cost_bps,
            "usable_factors": len(usable),
            "selected_factors": selected_keys,
            "best_factor": evaluations[0]["key"] if evaluations else None,
            "best_method": methods[0]["key"] if methods else None,
            "evaluation_scope": "out_of_sample",
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
        "methodology": {
            "split": f"前 70% 样本训练，隔离 {config.horizon} 个周期后，用后 30% 样本验证",
            "execution": "信号延迟一个周期执行，计入双边换手成本",
            "usable_rule": "样本外 Rank IC >= 0.03、滚动 IC 正值占比 >= 50% 且命中率 >= 50%",
            "warning": "方法收益仅统计样本外区间；历史统计不代表未来收益，仍需多标的横截面复核",
        },
    }
