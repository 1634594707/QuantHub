from __future__ import annotations

import math
import statistics
from typing import Any

EVALUATION_VERSION = "market-evaluation-v1"

VALID_METHODS = (
    "trend",
    "momentum",
    "volatility",
    "drawdown",
    "mean_reversion",
    "volume",
)
DEFAULT_METHODS = VALID_METHODS

VALID_STRATEGY_LENSES = ("trend_following", "mean_reversion", "risk_first")
DEFAULT_STRATEGY_LENSES = VALID_STRATEGY_LENSES

_CLOSE_KEYS = ("c", "close")
_VOLUME_KEYS = ("v", "volume")


def _number(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            number = float(value)
            if math.isfinite(number):
                return number
    return None


def _round(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None and math.isfinite(value) else None


def _change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current / previous - 1) * 100


def _window_change(values: list[float], periods: int) -> float | None:
    if len(values) <= periods:
        return None
    return _change(values[-1], values[-periods - 1])


def _sma(values: list[float], periods: int) -> float | None:
    if len(values) < periods:
        return None
    return sum(values[-periods:]) / periods


def _rsi(values: list[float], periods: int = 14) -> float | None:
    if len(values) <= periods:
        return None
    changes = [
        values[index] - values[index - 1] for index in range(len(values) - periods, len(values))
    ]
    average_gain = sum(max(change, 0) for change in changes) / periods
    average_loss = sum(max(-change, 0) for change in changes) / periods
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))


def _max_drawdown(values: list[float]) -> float:
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1)
    return worst * 100


def _dimension(label: str, signal: str, score: int | None, evidence: str) -> dict[str, Any]:
    return {"label": label, "signal": signal, "score": score, "evidence": evidence}


def _trend_dimension(close: list[float], metrics: dict[str, Any]) -> dict[str, Any]:
    sma20 = metrics["sma_20"]
    sma60 = metrics["sma_60"]
    if sma20 is None:
        return _dimension("趋势", "数据不足", None, "至少需要 20 根 K 线")
    latest = close[-1]
    distance20 = _change(latest, sma20) or 0.0
    score = 0
    score += 35 if distance20 >= 3 else 20 if distance20 > 0 else -35 if distance20 <= -3 else -20
    if sma60 is not None:
        score += 35 if sma20 > sma60 else -35
    change20 = metrics["return_20_pct"]
    if change20 is not None:
        score += 30 if change20 >= 5 else 15 if change20 > 0 else -30 if change20 <= -5 else -15
    score = max(-100, min(100, score))
    signal = "上升" if score >= 35 else "下降" if score <= -35 else "震荡"
    evidence = f"现价相对 20 期均线 {distance20:+.2f}%"
    if sma60 is not None:
        evidence += f"，20/60 期均线{'多头' if sma20 > sma60 else '空头'}排列"
    return _dimension("趋势", signal, score, evidence)


def _momentum_dimension(metrics: dict[str, Any]) -> dict[str, Any]:
    return5 = metrics["return_5_pct"]
    return20 = metrics["return_20_pct"]
    if return5 is None:
        return _dimension("动量", "数据不足", None, "至少需要 6 根 K 线")
    reference = return20 if return20 is not None else return5
    score = round(max(-100, min(100, return5 * 8 + reference * 3)))
    signal = "增强" if score >= 25 else "减弱" if score <= -25 else "中性"
    evidence = f"近 5 期收益 {return5:+.2f}%"
    if return20 is not None:
        evidence += f"，近 20 期收益 {return20:+.2f}%"
    return _dimension("动量", signal, score, evidence)


def _volatility_dimension(metrics: dict[str, Any]) -> dict[str, Any]:
    volatility = metrics["annualized_volatility_pct"]
    if volatility is None:
        return _dimension("波动", "数据不足", None, "至少需要 3 根 K 线")
    signal = "低" if volatility < 18 else "中" if volatility < 35 else "高"
    score = 70 if signal == "低" else 20 if signal == "中" else -60
    return _dimension("波动", signal, score, f"收益率年化波动约 {volatility:.2f}%")


def _drawdown_dimension(metrics: dict[str, Any]) -> dict[str, Any]:
    drawdown = metrics["max_drawdown_pct"]
    signal = "可控" if drawdown > -10 else "偏高" if drawdown > -20 else "高风险"
    score = 70 if signal == "可控" else 10 if signal == "偏高" else -70
    return _dimension("回撤", signal, score, f"样本区间最大回撤 {drawdown:.2f}%")


def _mean_reversion_dimension(metrics: dict[str, Any]) -> dict[str, Any]:
    rsi = metrics["rsi_14"]
    distance = metrics["price_vs_sma_20_pct"]
    if rsi is None or distance is None:
        return _dimension("均值偏离", "数据不足", None, "至少需要 20 根 K 线")
    if rsi <= 30 and distance < -3:
        signal, score = "超卖", 70
    elif rsi >= 70 and distance > 3:
        signal, score = "超买", -70
    else:
        signal = "常态"
        score = round(max(-40, min(40, -distance * 4)))
    return _dimension(
        "均值偏离", signal, score, f"RSI(14) {rsi:.1f}，现价偏离 20 期均线 {distance:+.2f}%"
    )


def _volume_dimension(metrics: dict[str, Any]) -> dict[str, Any]:
    ratio = metrics["volume_ratio_20"]
    change5 = metrics["return_5_pct"]
    if ratio is None:
        return _dimension("量价", "数据不足", None, "成交量缺失或不足 20 根 K 线")
    if ratio >= 1.5:
        signal = "放量上涨" if (change5 or 0) > 0 else "放量下跌"
        score = 45 if (change5 or 0) > 0 else -55
    elif ratio <= 0.65:
        signal, score = "缩量", -10
    else:
        signal, score = "平稳", 10
    return _dimension("量价", signal, score, f"最新成交量为 20 期均量的 {ratio:.2f} 倍")


def _confidence(available: int, requested: int, bar_count: int) -> str:
    coverage = available / max(requested, 1)
    if coverage >= 0.85 and bar_count >= 60:
        return "高"
    if coverage >= 0.6 and bar_count >= 20:
        return "中"
    return "低"


def _strategy_views(
    dimensions: dict[str, dict[str, Any]],
    selected: list[str],
    confidence: str,
) -> list[dict[str, Any]]:
    views: list[dict[str, Any]] = []
    trend_score = dimensions.get("trend", {}).get("score")
    momentum_score = dimensions.get("momentum", {}).get("score")
    reversion_score = dimensions.get("mean_reversion", {}).get("score")
    volatility_score = dimensions.get("volatility", {}).get("score")
    drawdown_score = dimensions.get("drawdown", {}).get("score")

    if "trend_following" in selected:
        scores = [score for score in (trend_score, momentum_score) if isinstance(score, int)]
        combined = sum(scores) / len(scores) if scores else None
        stance = (
            "顺势关注"
            if combined is not None and combined >= 30
            else "回避追涨"
            if combined is not None and combined <= -30
            else "等待确认"
        )
        rationale = (
            "趋势与动量共同转强"
            if stance == "顺势关注"
            else "趋势或动量尚未形成正向共振"
            if stance == "等待确认"
            else "趋势与动量偏弱"
        )
        signal = (
            "favorable"
            if stance == "顺势关注"
            else "caution"
            if stance == "回避追涨"
            else "neutral"
        )
        views.append(
            {
                "key": "trend_following",
                "label": "趋势跟随",
                "stance": stance,
                "signal": signal,
                "confidence": confidence,
                "rationale": rationale,
            }
        )

    if "mean_reversion" in selected:
        if reversion_score is None:
            stance, rationale = "数据不足", "缺少 RSI 或均线偏离数据"
        elif reversion_score >= 50:
            stance, rationale = "等待止跌", "价格处于超卖区，反转需要价格确认"
        elif reversion_score <= -50:
            stance, rationale = "谨防回落", "价格处于超买区，不宜把强势等同于低风险"
        else:
            stance, rationale = "无明显偏离", "价格仍在常态波动区间"
        signal = "caution" if stance == "谨防回落" else "neutral"
        views.append(
            {
                "key": "mean_reversion",
                "label": "均值回归",
                "stance": stance,
                "signal": signal,
                "confidence": confidence,
                "rationale": rationale,
            }
        )

    if "risk_first" in selected:
        scores = [score for score in (volatility_score, drawdown_score) if isinstance(score, int)]
        combined = sum(scores) / len(scores) if scores else None
        stance = (
            "风险可控"
            if combined is not None and combined >= 35
            else "降低暴露"
            if combined is not None and combined <= -20
            else "控制仓位"
        )
        rationale = (
            "波动与回撤均处于较低区间"
            if stance == "风险可控"
            else "波动或历史回撤偏高"
            if stance == "降低暴露"
            else "风险指标处于中间区间"
        )
        signal = (
            "favorable"
            if stance == "风险可控"
            else "caution"
            if stance == "降低暴露"
            else "neutral"
        )
        views.append(
            {
                "key": "risk_first",
                "label": "风险优先",
                "stance": stance,
                "signal": signal,
                "confidence": confidence,
                "rationale": rationale,
            }
        )
    return views


def evaluate_market(
    candles: list[dict[str, Any]],
    *,
    methods: list[str] | None = None,
    strategy_lenses: list[str] | None = None,
    periods_per_year: int = 252,
) -> dict[str, Any]:
    selected_methods = list(
        dict.fromkeys(method for method in (methods or DEFAULT_METHODS) if method in VALID_METHODS)
    )
    selected_lenses = list(
        dict.fromkeys(
            lens
            for lens in (strategy_lenses or DEFAULT_STRATEGY_LENSES)
            if lens in VALID_STRATEGY_LENSES
        )
    )
    if not selected_methods:
        selected_methods = list(DEFAULT_METHODS)
    if not selected_lenses:
        selected_lenses = list(DEFAULT_STRATEGY_LENSES)

    close = [
        value for row in candles if (value := _number(row, _CLOSE_KEYS)) is not None and value > 0
    ]
    if len(close) < 2:
        raise ValueError("量化评估至少需要 2 根有效收盘价 K 线")
    returns = [close[index] / close[index - 1] - 1 for index in range(1, len(close))]
    sma20 = _sma(close, 20)
    sma60 = _sma(close, 60)
    volatility = (
        statistics.stdev(returns) * math.sqrt(max(periods_per_year, 1)) * 100
        if len(returns) >= 2
        else None
    )
    volume_ratio = None
    recent_volume = [_number(row, _VOLUME_KEYS) for row in candles[-20:]]
    if len(recent_volume) == 20 and all(
        value is not None and value >= 0 for value in recent_volume
    ):
        valid_volume = [float(value) for value in recent_volume if value is not None]
        average_volume = sum(valid_volume) / 20
        volume_ratio = valid_volume[-1] / average_volume if average_volume > 0 else None

    metrics = {
        "latest_price": _round(close[-1], 4),
        "return_5_pct": _round(_window_change(close, 5)),
        "return_20_pct": _round(_window_change(close, 20)),
        "return_60_pct": _round(_window_change(close, 60)),
        "sma_20": _round(sma20, 4),
        "sma_60": _round(sma60, 4),
        "price_vs_sma_20_pct": _round(_change(close[-1], sma20)) if sma20 is not None else None,
        "rsi_14": _round(_rsi(close), 1),
        "annualized_volatility_pct": _round(volatility),
        "max_drawdown_pct": _round(_max_drawdown(close)),
        "volume_ratio_20": _round(volume_ratio),
    }
    builders = {
        "trend": lambda: _trend_dimension(close, metrics),
        "momentum": lambda: _momentum_dimension(metrics),
        "volatility": lambda: _volatility_dimension(metrics),
        "drawdown": lambda: _drawdown_dimension(metrics),
        "mean_reversion": lambda: _mean_reversion_dimension(metrics),
        "volume": lambda: _volume_dimension(metrics),
    }
    dimensions = {method: builders[method]() for method in selected_methods}
    available = sum(item["score"] is not None for item in dimensions.values())
    confidence = _confidence(available, len(selected_methods), len(close))
    strategies = _strategy_views(dimensions, selected_lenses, confidence)
    signals = {item["signal"] for item in strategies}
    disagreement = "favorable" in signals and "caution" in signals

    return {
        "version": EVALUATION_VERSION,
        "bar_count": len(close),
        "methods": selected_methods,
        "strategy_lenses": selected_lenses,
        "confidence": confidence,
        "metrics": metrics,
        "dimensions": dimensions,
        "strategies": strategies,
        "has_strategy_disagreement": disagreement,
        "data_quality": "充足" if confidence == "高" else "可用" if confidence == "中" else "有限",
    }
