from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from core.factor_research import benjamini_hochberg


def _newey_west_mean_test(values: pd.Series, max_lag: int) -> tuple[float, int]:
    clean = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    count = len(clean)
    if count < 3:
        return 1.0, count
    centered = clean.to_numpy() - float(clean.mean())
    long_run_variance = float(np.dot(centered, centered) / count)
    for lag in range(1, min(max_lag, count - 1) + 1):
        covariance = float(np.dot(centered[lag:], centered[:-lag]) / count)
        long_run_variance += 2 * (1 - lag / (max_lag + 1)) * covariance
    standard_error = math.sqrt(max(long_run_variance, 0.0) / count)
    if standard_error <= 1e-12:
        return (0.0 if abs(float(clean.mean())) > 1e-12 else 1.0), count
    statistic = abs(float(clean.mean()) / standard_error)
    p_value = math.erfc(statistic / math.sqrt(2))
    return float(min(max(p_value, 0.0), 1.0)), count


def cross_sectional_candidate_report(
    factor: pd.DataFrame,
    future_return: pd.DataFrame,
    *,
    expected_direction: int = 1,
    horizon: int = 5,
    minimum_assets: int = 30,
) -> dict[str, Any]:
    common_index = factor.index.intersection(future_return.index)
    common_columns = factor.columns.intersection(future_return.columns)
    ic_values = []
    asset_counts = []
    for session in common_index:
        rows = (
            pd.DataFrame(
                {
                    "factor": factor.loc[session, common_columns],
                    "future": future_return.loc[session, common_columns],
                }
            )
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
        )
        if len(rows) < minimum_assets:
            continue
        if rows["factor"].nunique() < 2 or rows["future"].nunique() < 2:
            continue
        ic = rows["factor"].rank().corr(rows["future"].rank())
        if pd.notna(ic):
            ic_values.append(float(ic) * expected_direction)
            asset_counts.append(len(rows))
    series = pd.Series(ic_values, dtype=float)
    p_value, effective_sessions = _newey_west_mean_test(series, max(horizon - 1, 0))
    mean_ic = float(series.mean()) if len(series) else 0.0
    positive_ratio = float(series.gt(0).mean()) if len(series) else 0.0
    return {
        "rank_ic_mean": round(mean_ic, 6),
        "rank_ic_median": round(float(series.median()), 6) if len(series) else 0.0,
        "positive_rank_ic_ratio": round(positive_ratio, 6),
        "raw_p_value": round(p_value, 8),
        "effective_sessions": effective_sessions,
        "minimum_assets": min(asset_counts) if asset_counts else 0,
        "median_assets": round(float(np.median(asset_counts)), 2) if asset_counts else 0.0,
        "passed": bool(
            effective_sessions >= 120
            and mean_ic >= 0.03
            and positive_ratio >= 0.6
            and p_value <= 0.05
        ),
        "thresholds": {
            "minimum_effective_sessions": 120,
            "minimum_rank_ic": 0.03,
            "minimum_positive_ratio": 0.6,
            "maximum_p_value": 0.05,
        },
    }


def finalize_experiment_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    adjusted = benjamini_hochberg([float(item["raw_p_value"]) for item in candidates])
    rows = []
    for candidate, adjusted_p_value in zip(candidates, adjusted, strict=True):
        passed = bool(candidate["passed"] and adjusted_p_value <= 0.05)
        rows.append(
            {
                **candidate,
                "adjusted_p_value": round(adjusted_p_value, 8),
                "passed": passed,
                "status": "passed" if passed else "failed",
            }
        )
    return rows


def cross_sectional_residual(primary: pd.DataFrame, control: pd.DataFrame) -> pd.DataFrame:
    """Remove the same-session cross-sectional linear exposure to one control."""
    common_index = primary.index.intersection(control.index)
    common_columns = primary.columns.intersection(control.columns)
    left = primary.loc[common_index, common_columns]
    right = control.loc[common_index, common_columns]
    valid = left.notna() & right.notna()
    left = left.where(valid)
    right = right.where(valid)
    left_centered = left.sub(left.mean(axis=1), axis=0)
    right_centered = right.sub(right.mean(axis=1), axis=0)
    denominator = right_centered.pow(2).sum(axis=1).replace(0, np.nan)
    beta = left_centered.mul(right_centered).sum(axis=1).div(denominator)
    return left_centered.sub(right_centered.mul(beta, axis=0))


def adx_direction_factor(
    high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, period: int
) -> pd.DataFrame:
    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    previous_close = close.shift(1)
    true_range = pd.DataFrame(
        np.maximum.reduce(
            [
                (high - low).to_numpy(),
                (high - previous_close).abs().to_numpy(),
                (low - previous_close).abs().to_numpy(),
            ]
        ),
        index=close.index,
        columns=close.columns,
    )
    average_range = true_range.rolling(period, min_periods=period).mean().replace(0, np.nan)
    plus_di = plus_dm.rolling(period, min_periods=period).mean().div(average_range)
    minus_di = minus_dm.rolling(period, min_periods=period).mean().div(average_range)
    dx = plus_di.sub(minus_di).abs().div(plus_di.add(minus_di).replace(0, np.nan))
    adx = dx.rolling(period, min_periods=period).mean()
    return adx.mul(np.sign(plus_di - minus_di))


def build_preregistered_experiments(
    *,
    open_price: pd.DataFrame,
    high: pd.DataFrame,
    low: pd.DataFrame,
    close: pd.DataFrame,
    volume: pd.DataFrame,
) -> list[dict[str, Any]]:
    daily_return = close.pct_change()
    tradable = volume.gt(0) & daily_return.abs().lt(0.095)
    future_returns = {
        horizon: close.shift(-horizon).div(close).sub(1).where(tradable.shift(-1).fillna(False))
        for horizon in (1, 3, 5, 10)
    }
    experiments: list[dict[str, Any]] = []

    adx_candidates = []
    for period in (10, 14, 20):
        factor = adx_direction_factor(high, low, close, period).where(tradable)
        for horizon in (1, 3, 5, 10):
            adx_candidates.append(
                {
                    "candidate_key": f"adx_{period}_h{horizon}",
                    "parameters": {"adx_period": period, "horizon": horizon},
                    **cross_sectional_candidate_report(
                        factor, future_returns[horizon], horizon=horizon
                    ),
                }
            )
    experiments.append(
        {
            "experiment_id": "exp-01-adx-direction",
            "hypothesis": "ADX 方向强度在 A 股横截面具有正向残差预测力",
            "primary_label": "future_return_without_point_in_time_industry_residualization",
            "parameter_budget": {"adx_period": [10, 14, 20], "horizon": [1, 3, 5, 10]},
            "target_market": "a_shares",
            "pass_criteria": "BH 后 p<=0.05、Rank IC>=0.03、正向比例>=0.6",
            "limitations": ["缺少时点行业暴露，不能完成行业中性残差标签"],
            "candidates": finalize_experiment_candidates(adx_candidates),
        }
    )

    momentum_candidates = []
    volatility = daily_return.rolling(20, min_periods=15).std(ddof=0)
    for period in (20, 60, 120):
        factor = close.pct_change(period).div(volatility.mul(math.sqrt(period))).where(tradable)
        momentum_candidates.append(
            {
                "candidate_key": f"vol_adjusted_momentum_{period}",
                "parameters": {"momentum_period": period, "volatility_period": 20, "horizon": 5},
                **cross_sectional_candidate_report(factor, future_returns[5], horizon=5),
            }
        )
    experiments.append(
        {
            "experiment_id": "exp-02-volatility-adjusted-residual-momentum",
            "hypothesis": "波动调整后的中期动量具有跨参数稳定性",
            "primary_label": "five_session_future_return",
            "parameter_budget": {"momentum_period": [20, 60, 120], "volatility_period": [20]},
            "target_market": "a_shares",
            "pass_criteria": "BH 后 p<=0.05、Rank IC>=0.03、正向比例>=0.6",
            "limitations": ["缺少时点行业、市值和 Beta 暴露"],
            "candidates": finalize_experiment_candidates(momentum_candidates),
        }
    )

    volume_mean = volume.rolling(20, min_periods=15).mean().replace(0, np.nan)
    volume_shock = volume.div(volume_mean)
    breakout_candidates = []
    for period in (20, 40, 60):
        factor = close.div(high.shift(1).rolling(period, min_periods=period).max()).sub(1)
        factor = factor.where(volume_shock.ge(1.5) & tradable)
        breakout_candidates.append(
            {
                "candidate_key": f"breakout_{period}_volume_shock",
                "parameters": {"breakout_period": period, "volume_multiple": 1.5, "horizon": 5},
                **cross_sectional_candidate_report(factor, future_returns[5], horizon=5),
            }
        )
    experiments.append(
        {
            "experiment_id": "exp-03-breakout-volume-shock",
            "hypothesis": "成交额冲击确认的突破在次日可成交约束后继续延续",
            "primary_label": "five_session_future_return",
            "parameter_budget": {"breakout_period": [20, 40, 60], "volume_multiple": [1.5]},
            "target_market": "a_shares",
            "pass_criteria": "BH 后 p<=0.05、Rank IC>=0.03、正向比例>=0.6",
            "execution_constraints": ["涨跌停过滤", "次日有成交量", "T+1", "成本后另行验证"],
            "candidates": finalize_experiment_candidates(breakout_candidates),
        }
    )

    gap = open_price.div(close.shift(1)).sub(1)
    reversal_candidates = []
    regimes = {
        "normal_pullback": volume_shock.lt(1.5) & gap.abs().lt(0.03),
        "liquidity_shock": volume_shock.ge(1.5),
        "announcement_gap": gap.abs().ge(0.03),
    }
    for lookback in (1, 3, 5):
        base = close.pct_change(lookback).mul(-1)
        for regime, mask in regimes.items():
            factor = base.where(mask & tradable)
            reversal_candidates.append(
                {
                    "candidate_key": f"reversal_{lookback}_{regime}",
                    "parameters": {"lookback": lookback, "regime": regime, "horizon": 3},
                    **cross_sectional_candidate_report(factor, future_returns[3], horizon=3),
                }
            )
    experiments.append(
        {
            "experiment_id": "exp-04-short-term-reversal",
            "hypothesis": "1 至 5 日反转在正常回撤、流动性冲击和跳空状态中具有不同预测力",
            "primary_label": "three_session_future_return",
            "parameter_budget": {
                "lookback": [1, 3, 5],
                "regime": list(regimes),
            },
            "target_market": "a_shares",
            "pass_criteria": "BH 后 p<=0.05、Rank IC>=0.03、正向比例>=0.6",
            "execution_constraints": ["涨跌停过滤", "次日有成交量", "T+1"],
            "candidates": finalize_experiment_candidates(reversal_candidates),
        }
    )

    intraday_return = close.div(open_price).sub(1)
    overnight_return = open_price.div(close.shift(1)).sub(1)
    overnight_incremental = cross_sectional_residual(overnight_return, intraday_return)
    intraday_reversal_incremental = cross_sectional_residual(
        intraday_return.mul(-1), overnight_return
    )
    session_candidates = []
    for horizon in (1, 3, 5):
        for candidate_key, factor, component in (
            ("overnight_gap_continuation", overnight_return, "raw_overnight"),
            ("overnight_gap_incremental", overnight_incremental, "overnight_residual"),
            ("intraday_reversal", intraday_return.mul(-1), "raw_intraday"),
            (
                "intraday_reversal_incremental",
                intraday_reversal_incremental,
                "intraday_residual",
            ),
        ):
            session_candidates.append(
                {
                    "candidate_key": f"{candidate_key}_h{horizon}",
                    "parameters": {"component": component, "horizon": horizon},
                    **cross_sectional_candidate_report(
                        factor.where(tradable), future_returns[horizon], horizon=horizon
                    ),
                }
            )
    experiments.append(
        {
            "experiment_id": "exp-05-overnight-intraday-decomposition",
            "hypothesis": "隔夜缺口延续与日内反转在互相残差化后仍具有独立增量 IC",
            "primary_label": "future_return_with_cross_sectional_component_residualization",
            "parameter_budget": {
                "component": [
                    "raw_overnight",
                    "overnight_residual",
                    "raw_intraday",
                    "intraday_residual",
                ],
                "horizon": [1, 3, 5],
            },
            "target_market": "a_shares",
            "pass_criteria": "BH 后 p<=0.05、Rank IC>=0.03、正向比例>=0.6",
            "candidates": finalize_experiment_candidates(session_candidates),
        }
    )

    previous_close = close.shift(1)
    high_return = high.div(previous_close).sub(1)
    close_return = close.div(previous_close).sub(1)
    sealed_limit = close_return.ge(0.095) & close.div(high).ge(0.995) & volume.gt(0)
    opened_limit = high_return.ge(0.095) & close_return.lt(0.095) & volume.gt(0)
    seal_strength = close.sub(low).div(high.sub(low).replace(0, np.nan))
    limit_candidates = []
    for horizon in (1, 3, 5):
        for candidate_key, factor in (
            ("sealed_limit_continuation", close_return.where(sealed_limit)),
            ("opened_limit_reversal", close_return.mul(-1).where(opened_limit)),
            ("limit_seal_strength", seal_strength.where(sealed_limit)),
        ):
            limit_candidates.append(
                {
                    "candidate_key": f"{candidate_key}_h{horizon}",
                    "parameters": {"limit_threshold": 0.095, "horizon": horizon},
                    **cross_sectional_candidate_report(
                        factor,
                        future_returns[horizon],
                        horizon=horizon,
                        minimum_assets=10,
                    ),
                }
            )
    experiments.append(
        {
            "experiment_id": "exp-07-limit-up-state",
            "hypothesis": "涨停封板、开板和封板强度对后续收益具有不同条件效应",
            "primary_label": "future_return_excluding_next_session_limit_or_suspension",
            "parameter_budget": {
                "state": ["sealed_limit", "opened_limit", "seal_strength"],
                "horizon": [1, 3, 5],
            },
            "target_market": "a_shares",
            "pass_criteria": "BH 后 p<=0.05、Rank IC>=0.03、正向比例>=0.6",
            "execution_constraints": [
                "次日涨停无法买入的样本不计入可执行标签",
                "次日停牌或无成交量的样本不计入可执行标签",
                "T+1",
            ],
            "limitations": ["统一使用 9.5% 阈值，尚未按历史板块制度区分 10% 与 20%"],
            "candidates": finalize_experiment_candidates(limit_candidates),
        }
    )
    for experiment in experiments:
        experiment["status"] = (
            "passed" if any(item["passed"] for item in experiment["candidates"]) else "failed"
        )
        experiment["successful_candidates"] = sum(
            item["passed"] for item in experiment["candidates"]
        )
    return experiments
