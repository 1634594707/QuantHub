"""Deterministic robustness gates for factor discovery and portfolio research."""

from __future__ import annotations

import math
from typing import Any, Literal

import numpy as np
import pandas as pd

DISCOVERY_SOURCES = ("ai", "template", "random_dsl", "symbolic_regression")


def _rank_ic(left: pd.Series | list[float], right: pd.Series | list[float]) -> float:
    pair = (
        pd.concat([pd.Series(left, dtype=float), pd.Series(right, dtype=float)], axis=1)
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )
    if len(pair) < 3 or pair.iloc[:, 0].nunique() < 2 or pair.iloc[:, 1].nunique() < 2:
        return 0.0
    return float(
        pair.iloc[:, 0].rank(method="average").corr(pair.iloc[:, 1].rank(method="average"))
    )


def parameter_plateau_test(
    results: list[dict[str, Any]],
    *,
    parameter: str,
    metric: str,
    threshold: float,
    direction: Literal["maximize", "minimize"] = "maximize",
    minimum_plateau_size: int = 3,
) -> dict[str, Any]:
    """Require a contiguous parameter neighborhood instead of a lone optimum."""
    ordered = sorted(results, key=lambda item: float(item[parameter]))
    rows = []
    for item in ordered:
        value = float(item[metric])
        passed = value >= threshold if direction == "maximize" else value <= threshold
        rows.append(
            {
                "parameter": float(item[parameter]),
                "metric": value,
                "passed": passed,
            }
        )
    plateaus: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for row in rows:
        if row["passed"]:
            current.append(row)
        elif current:
            plateaus.append(current)
            current = []
    if current:
        plateaus.append(current)
    qualifying = [group for group in plateaus if len(group) >= minimum_plateau_size]
    robust_parameters = [row["parameter"] for group in qualifying for row in group]
    return {
        "passed": bool(qualifying),
        "parameter": parameter,
        "metric": metric,
        "threshold": threshold,
        "direction": direction,
        "minimum_plateau_size": minimum_plateau_size,
        "robust_parameters": robust_parameters,
        "plateaus": [
            {
                "start": group[0]["parameter"],
                "end": group[-1]["parameter"],
                "size": len(group),
                "minimum_metric": min(row["metric"] for row in group),
            }
            for group in qualifying
        ],
        "rows": rows,
    }


def compare_discovery_efficiency(
    candidates: list[dict[str, Any]],
    *,
    per_source_budget: int,
) -> dict[str, Any]:
    """Compare discovery sources under the same immutable candidate budget."""
    if per_source_budget < 1:
        raise ValueError("每个来源的候选预算至少为 1")
    grouped = {
        source: [item for item in candidates if item.get("source") == source]
        for source in DISCOVERY_SOURCES
    }
    missing = [source for source, items in grouped.items() if not items]
    if missing:
        raise ValueError(f"发现效率对照缺少来源: {', '.join(missing)}")
    effective_budget = min(per_source_budget, *(len(items) for items in grouped.values()))
    rows = []
    for source in DISCOVERY_SOURCES:
        selected = grouped[source][:effective_budget]
        valid = [item for item in selected if item.get("validation_passed") is True]
        novel = [item for item in valid if item.get("duplicate") is not True]
        passed = [item for item in novel if item.get("research_passed") is True]
        compute_units = sum(int(item.get("compute_units", 0)) for item in selected)
        llm_tokens = sum(int(item.get("llm_tokens", 0)) for item in selected)
        rows.append(
            {
                "source": source,
                "candidate_budget": effective_budget,
                "valid_candidates": len(valid),
                "novel_valid_candidates": len(novel),
                "research_passed_candidates": len(passed),
                "valid_rate": round(len(valid) / effective_budget, 6),
                "novel_valid_rate": round(len(novel) / effective_budget, 6),
                "research_pass_rate": round(len(passed) / effective_budget, 6),
                "compute_units": compute_units,
                "llm_tokens": llm_tokens,
                "compute_units_per_novel_valid": (
                    round(compute_units / len(novel), 6) if novel else None
                ),
            }
        )
    ranked = sorted(
        rows,
        key=lambda row: (
            -row["novel_valid_rate"],
            -row["research_pass_rate"],
            row["compute_units_per_novel_valid"]
            if row["compute_units_per_novel_valid"] is not None
            else math.inf,
            row["source"],
        ),
    )
    rank_by_source = {row["source"]: index for index, row in enumerate(ranked, start=1)}
    by_source = {row["source"]: row for row in rows}
    ai_rate = float(by_source["ai"]["novel_valid_rate"])
    random_rate = float(by_source["random_dsl"]["novel_valid_rate"])
    return {
        "fixed_candidate_budget": effective_budget,
        "requested_candidate_budget": per_source_budget,
        "sources": [{**row, "rank": rank_by_source[row["source"]]} for row in rows],
        "winner": ranked[0]["source"],
        "primary_metric": "novel_valid_rate",
        "deterministic": True,
        "ai_vs_random_dsl": {
            "novel_valid_rate_delta": round(ai_rate - random_rate, 6),
            "reproducible_improvement_observed": ai_rate > random_rate,
            "claim_allowed": ai_rate > random_rate,
            "required_evidence": "same_locked_candidates_budget_including_all_failures",
        },
        "selection_bias_warning": "必须报告全部来源和失败候选，不能只展示胜出样例",
    }


def pareto_rank(
    candidates: list[dict[str, Any]],
    objectives: dict[str, Literal["maximize", "minimize"]],
) -> list[dict[str, Any]]:
    """Assign non-dominated Pareto ranks without collapsing objectives into one score."""
    if not objectives:
        raise ValueError("Pareto 排序至少需要一个目标")

    def dominates(left: dict[str, Any], right: dict[str, Any]) -> bool:
        no_worse = True
        strictly_better = False
        for key, direction in objectives.items():
            left_value = float(left[key])
            right_value = float(right[key])
            if direction == "maximize":
                no_worse = no_worse and left_value >= right_value
                strictly_better = strictly_better or left_value > right_value
            else:
                no_worse = no_worse and left_value <= right_value
                strictly_better = strictly_better or left_value < right_value
        return no_worse and strictly_better

    remaining = list(range(len(candidates)))
    ranks = [0] * len(candidates)
    rank = 1
    while remaining:
        front = [
            index
            for index in remaining
            if not any(
                dominates(candidates[other], candidates[index])
                for other in remaining
                if other != index
            )
        ]
        for index in front:
            ranks[index] = rank
        remaining = [index for index in remaining if index not in front]
        rank += 1
    return [
        {
            **candidate,
            "pareto_rank": ranks[index],
            "pareto_front": ranks[index] == 1,
            "pareto_objectives": objectives,
        }
        for index, candidate in enumerate(candidates)
    ]


def placebo_test(
    factor: pd.Series | list[float],
    label: pd.Series | list[float],
    *,
    permutations: int = 200,
    random_factors: int = 100,
    pseudo_events: int = 100,
    time_shifts: tuple[int, ...] = (-20, -10, -5, 5, 10, 20),
    false_positive_limit: float = 0.05,
    seed: int = 0,
) -> dict[str, Any]:
    factor_series = pd.Series(factor, dtype=float)
    label_series = pd.Series(label, dtype=float)
    observed = abs(_rank_ic(factor_series, label_series))
    rng = np.random.default_rng(seed)
    null_values: list[float] = []
    shuffled = label_series.to_numpy(copy=True)
    for _ in range(max(permutations, 1)):
        rng.shuffle(shuffled)
        null_values.append(abs(_rank_ic(factor_series, shuffled)))
    shifted_values = [
        abs(_rank_ic(factor_series, label_series.shift(shift)))
        for shift in time_shifts
        if shift != 0
    ]
    null_values.extend(shifted_values)
    for _ in range(max(random_factors, 1)):
        null_values.append(abs(_rank_ic(rng.normal(size=len(factor_series)), label_series)))
    event_count = max(3, int(round(len(factor_series) * 0.05)))
    for _ in range(max(pseudo_events, 1)):
        pseudo_event_factor = np.zeros(len(factor_series), dtype=float)
        pseudo_event_factor[
            rng.choice(
                len(factor_series),
                size=min(event_count, len(factor_series)),
                replace=False,
            )
        ] = 1.0
        null_values.append(abs(_rank_ic(pseudo_event_factor, label_series)))
    exceedances = sum(value >= observed for value in null_values)
    empirical_p_value = (1 + exceedances) / (len(null_values) + 1)
    return {
        "passed": empirical_p_value <= false_positive_limit,
        "observed_absolute_rank_ic": round(observed, 6),
        "empirical_p_value": round(empirical_p_value, 6),
        "false_positive_limit": false_positive_limit,
        "null_trials": len(null_values),
        "shuffle_trials": max(permutations, 1),
        "time_shift_trials": len(shifted_values),
        "random_factor_trials": max(random_factors, 1),
        "pseudo_event_trials": max(pseudo_events, 1),
        "seed": seed,
    }


def data_perturbation_test(
    factor: pd.Series | list[float],
    label: pd.Series | list[float],
    *,
    liquidity: pd.Series | list[float] | None = None,
    missing_rate: float = 0.05,
    noise_scale: float = 0.01,
    cost_bps_increase: float = 20.0,
    delay_periods: int = 1,
    capacity_fraction: float = 0.5,
    minimum_retained_ic: float = 0.5,
    seed: int = 0,
) -> dict[str, Any]:
    factor_series = pd.Series(factor, dtype=float)
    label_series = pd.Series(label, dtype=float)
    liquidity_series = (
        pd.Series(liquidity, dtype=float)
        if liquidity is not None
        else pd.Series(np.arange(len(factor_series), dtype=float) + 1)
    )
    base_ic = _rank_ic(factor_series, label_series)
    rng = np.random.default_rng(seed)
    missing = factor_series.copy()
    missing_count = max(1, int(round(len(missing) * missing_rate)))
    missing.iloc[rng.choice(len(missing), size=min(missing_count, len(missing)), replace=False)] = (
        np.nan
    )
    noise = rng.normal(
        0, max(float(factor_series.std(ddof=0)), 1e-12) * noise_scale, len(factor_series)
    )
    ranked_exposure = factor_series.rank(pct=True).sub(0.5).abs().mul(2)
    cost_adjusted_label = label_series - ranked_exposure * cost_bps_increase / 10_000
    capacity_cutoff = float(liquidity_series.quantile(1 - capacity_fraction))
    capacity_factor = factor_series.where(liquidity_series.ge(capacity_cutoff))
    scenarios = {
        "missing_values": _rank_ic(missing, label_series),
        "price_noise": _rank_ic(factor_series + noise, label_series),
        "cost_increase": _rank_ic(factor_series, cost_adjusted_label),
        "execution_delay": _rank_ic(factor_series, label_series.shift(-delay_periods)),
        "capacity_shrink": _rank_ic(capacity_factor, label_series),
    }
    denominator = max(abs(base_ic), 1e-12)
    rows = [
        {
            "scenario": name,
            "rank_ic": round(value, 6),
            "direction_consistent": value * base_ic >= 0,
            "retained_ic_ratio": round(abs(value) / denominator, 6),
        }
        for name, value in scenarios.items()
    ]
    return {
        "passed": all(
            row["direction_consistent"] and row["retained_ic_ratio"] >= minimum_retained_ic
            for row in rows
        ),
        "base_rank_ic": round(base_ic, 6),
        "minimum_retained_ic": minimum_retained_ic,
        "scenarios": rows,
        "seed": seed,
    }


def orthogonalized_incremental_ic(
    candidate: pd.Series | list[float],
    deployed_factors: dict[str, pd.Series | list[float]],
    label: pd.Series | list[float],
) -> dict[str, Any]:
    frame = pd.DataFrame({"candidate": candidate, "label": label, **deployed_factors}).replace(
        [np.inf, -np.inf], np.nan
    )
    frame = frame.dropna()
    original_ic = _rank_ic(frame["candidate"], frame["label"])
    if not deployed_factors:
        residual = frame["candidate"].to_numpy(dtype=float)
    else:
        design = frame[list(deployed_factors)].to_numpy(dtype=float)
        design = np.column_stack([np.ones(len(frame)), design])
        values = frame["candidate"].to_numpy(dtype=float)
        coefficients = np.linalg.lstsq(design, values, rcond=None)[0]
        residual = values - design @ coefficients
    incremental_ic = _rank_ic(pd.Series(residual), frame["label"].reset_index(drop=True))
    candidate_variance = float(frame["candidate"].var(ddof=0))
    residual_variance = float(np.var(residual))
    return {
        "original_rank_ic": round(original_ic, 6),
        "incremental_rank_ic": round(incremental_ic, 6),
        "incremental_ic_change": round(incremental_ic - original_ic, 6),
        "residual_variance_ratio": round(
            residual_variance / candidate_variance if candidate_variance > 0 else 0.0,
            6,
        ),
        "observations": len(frame),
        "deployed_factor_count": len(deployed_factors),
        "method": "ols_residualization_then_spearman_ic",
    }


def simple_portfolio_benchmarks(
    factor_returns: dict[str, pd.Series | list[float]],
    expected_ics: dict[str, float],
    *,
    ridge_penalty: float = 1.0,
    periods_per_year: int = 252,
    outer_folds: int = 3,
    minimum_training_fraction: float = 0.5,
) -> dict[str, Any]:
    """Evaluate portfolio weights only on future outer-fold observations."""
    if not factor_returns:
        raise ValueError("组合基准至少需要一个因子收益序列")
    frame = pd.DataFrame(factor_returns).replace([np.inf, -np.inf], np.nan).dropna()
    if len(frame) < 12:
        raise ValueError("外层组合验证至少需要 12 个共同观测")
    if outer_folds < 1:
        raise ValueError("outer_folds 至少为 1")
    if not 0.25 <= minimum_training_fraction < 1:
        raise ValueError("minimum_training_fraction 必须位于 [0.25, 1) 区间")
    keys = list(frame.columns)
    count = len(keys)
    equal = np.full(count, 1 / count)
    ic_values = np.array([max(float(expected_ics.get(key, 0.0)), 0.0) for key in keys])
    ic_weights = ic_values / ic_values.sum() if ic_values.sum() > 0 else equal

    def training_weights(training: pd.DataFrame) -> dict[str, np.ndarray]:
        volatility = training.std(ddof=1).to_numpy(dtype=float)
        inverse_volatility = np.divide(
            1.0,
            volatility,
            out=np.zeros_like(volatility),
            where=volatility > 1e-12,
        )
        risk_parity = (
            inverse_volatility / inverse_volatility.sum() if inverse_volatility.sum() > 0 else equal
        )
        covariance = training.cov().to_numpy(dtype=float)
        ridge_raw = np.linalg.pinv(covariance + ridge_penalty * np.eye(count)) @ ic_values
        ridge_raw = np.clip(ridge_raw, 0, None)
        ridge = ridge_raw / ridge_raw.sum() if ridge_raw.sum() > 0 else equal
        return {
            "equal_weight": equal,
            "ic_weight": ic_weights,
            "risk_parity": risk_parity,
            "ridge_linear": ridge,
        }

    initial_training = max(3, int(math.floor(len(frame) * minimum_training_fraction)))
    test_indices = np.arange(initial_training, len(frame))
    fold_indices = [fold for fold in np.array_split(test_indices, outer_folds) if len(fold)]
    out_of_sample_returns: dict[str, list[float]] = {
        method: [] for method in ("equal_weight", "ic_weight", "risk_parity", "ridge_linear")
    }

    fold_audit: list[dict[str, Any]] = []
    last_weights: dict[str, np.ndarray] | None = None
    for fold_number, indices in enumerate(fold_indices, start=1):
        test_start = int(indices[0])
        training = frame.iloc[:test_start]
        testing = frame.iloc[indices]
        weights_by_method = training_weights(training)
        last_weights = weights_by_method
        for method, weights in weights_by_method.items():
            out_of_sample_returns[method].extend((testing.to_numpy(dtype=float) @ weights).tolist())
        fold_audit.append(
            {
                "fold": fold_number,
                "training_start_offset": 0,
                "training_end_offset": test_start - 1,
                "test_start_offset": test_start,
                "test_end_offset": int(indices[-1]),
                "training_observations": len(training),
                "test_observations": len(testing),
                "weights": {
                    method: {key: round(float(weight), 8) for key, weight in zip(keys, weights)}
                    for method, weights in weights_by_method.items()
                },
            }
        )

    if last_weights is None:
        raise ValueError("外层组合验证没有可用测试窗口")
    rows = []
    for name, returns_list in out_of_sample_returns.items():
        returns = np.asarray(returns_list, dtype=float)
        mean = float(np.mean(returns))
        std = float(np.std(returns, ddof=1))
        rows.append(
            {
                "method": name,
                "weights": {
                    key: round(float(weight), 8) for key, weight in zip(keys, last_weights[name])
                },
                "mean_return": round(mean, 8),
                "volatility": round(std, 8),
                "sharpe": round(mean / std * math.sqrt(periods_per_year), 6) if std else 0.0,
                "observations": len(returns),
            }
        )
    return {
        "methods": rows,
        "training_scope": "expanding_outer_time_series_training_only",
        "outer_folds": len(fold_audit),
        "minimum_training_fraction": minimum_training_fraction,
        "confirmation_set_used_for_weight_selection": False,
        "folds": fold_audit,
        "nonlinear_models_included": False,
        "ridge_penalty": ridge_penalty,
    }


def nested_nonlinear_benchmark(
    features: dict[str, pd.Series | list[float]],
    label: pd.Series | list[float],
    *,
    outer_folds: int = 3,
    minimum_training_fraction: float = 0.5,
    minimum_improvement: float = 0.02,
    ridge_penalties: tuple[float, ...] = (0.01, 0.1, 1.0),
) -> dict[str, Any]:
    """Compare polynomial nonlinear regression with linear ridge under nested time splits."""
    frame = pd.DataFrame({**features, "__label__": label}).replace([np.inf, -np.inf], np.nan)
    frame = frame.dropna()
    if len(features) < 2:
        raise ValueError("非线性对照至少需要两个特征")
    if len(frame) < 30:
        raise ValueError("嵌套时间序列验证至少需要 30 个共同观测")
    if outer_folds < 2:
        raise ValueError("非线性对照至少需要两个外层窗口")

    feature_names = list(features)

    def design(values: np.ndarray, degree: int) -> np.ndarray:
        columns = [values]
        if degree == 2:
            columns.append(values**2)
            interactions = [
                (values[:, left] * values[:, right]).reshape(-1, 1)
                for left in range(values.shape[1])
                for right in range(left + 1, values.shape[1])
            ]
            if interactions:
                columns.append(np.column_stack(interactions))
        matrix = np.column_stack(columns)
        return np.column_stack([np.ones(len(matrix)), matrix])

    def fit_predict(
        training_x: np.ndarray,
        training_y: np.ndarray,
        testing_x: np.ndarray,
        degree: int,
        penalty: float,
    ) -> np.ndarray:
        mean = training_x.mean(axis=0)
        scale = training_x.std(axis=0)
        scale = np.where(scale > 1e-12, scale, 1.0)
        train_design = design((training_x - mean) / scale, degree)
        test_design = design((testing_x - mean) / scale, degree)
        regularizer = np.eye(train_design.shape[1]) * penalty
        regularizer[0, 0] = 0.0
        coefficients = np.linalg.pinv(train_design.T @ train_design + regularizer) @ (
            train_design.T @ training_y
        )
        return test_design @ coefficients

    values = frame[feature_names].to_numpy(dtype=float)
    labels = frame["__label__"].to_numpy(dtype=float)
    initial_training = max(20, int(math.floor(len(frame) * minimum_training_fraction)))
    fold_indices = [
        fold
        for fold in np.array_split(np.arange(initial_training, len(frame)), outer_folds)
        if len(fold)
    ]
    fold_rows = []
    for fold_number, indices in enumerate(fold_indices, start=1):
        outer_test_start = int(indices[0])
        training_x = values[:outer_test_start]
        training_y = labels[:outer_test_start]
        inner_split = max(10, int(math.floor(len(training_x) * 0.75)))
        if inner_split >= len(training_x):
            inner_split = len(training_x) - 1
        inner_train_x = training_x[:inner_split]
        inner_train_y = training_y[:inner_split]
        inner_valid_x = training_x[inner_split:]
        inner_valid_y = training_y[inner_split:]

        selected: dict[str, dict[str, float | int]] = {}
        for model, degree in (("linear_ridge", 1), ("polynomial_ridge", 2)):
            candidates = []
            for penalty in ridge_penalties:
                predictions = fit_predict(
                    inner_train_x,
                    inner_train_y,
                    inner_valid_x,
                    degree,
                    penalty,
                )
                candidates.append(
                    {
                        "degree": degree,
                        "penalty": penalty,
                        "validation_mse": float(np.mean((inner_valid_y - predictions) ** 2)),
                    }
                )
            selected[model] = min(candidates, key=lambda row: row["validation_mse"])

        outer_rows = {}
        for model, params in selected.items():
            predictions = fit_predict(
                training_x,
                training_y,
                values[indices],
                int(params["degree"]),
                float(params["penalty"]),
            )
            actual = labels[indices]
            mse = float(np.mean((actual - predictions) ** 2))
            rank_ic = _rank_ic(pd.Series(predictions), pd.Series(actual))
            outer_rows[model] = {
                **params,
                "test_mse": mse,
                "test_rank_ic": rank_ic,
            }
        linear_mse = float(outer_rows["linear_ridge"]["test_mse"])
        nonlinear_mse = float(outer_rows["polynomial_ridge"]["test_mse"])
        improvement = (linear_mse - nonlinear_mse) / max(linear_mse, 1e-12)
        fold_rows.append(
            {
                "fold": fold_number,
                "training_end_offset": outer_test_start - 1,
                "test_start_offset": outer_test_start,
                "test_end_offset": int(indices[-1]),
                "models": outer_rows,
                "nonlinear_mse_improvement": round(improvement, 6),
                "nonlinear_won": improvement >= minimum_improvement,
            }
        )
    improvements = [row["nonlinear_mse_improvement"] for row in fold_rows]
    wins = sum(row["nonlinear_won"] for row in fold_rows)
    stable_outperformance = wins > len(fold_rows) / 2 and float(np.mean(improvements)) >= (
        minimum_improvement
    )
    return {
        "eligible_for_simulation": stable_outperformance,
        "stable_outperformance": stable_outperformance,
        "outer_folds": fold_rows,
        "nonlinear_wins": wins,
        "mean_mse_improvement": round(float(np.mean(improvements)), 6),
        "minimum_improvement": minimum_improvement,
        "linear_baseline": "linear_ridge",
        "nonlinear_model": "polynomial_ridge_degree_2",
        "nested_time_series_validation": True,
        "confirmation_set_used_for_selection": False,
    }


MARKET_PORTFOLIO_PROFILES: dict[str, dict[str, Any]] = {
    "a_shares": {
        "maximum_weight": 0.10,
        "maximum_industry_deviation": 0.05,
        "maximum_participation_rate": 0.10,
        "maximum_turnover": 0.50,
        "long_only": True,
        "lot_size": 100,
        "settlement": "T+1",
    },
    "us_stocks": {
        "maximum_weight": 0.12,
        "maximum_industry_deviation": 0.07,
        "maximum_participation_rate": 0.08,
        "maximum_turnover": 0.60,
        "long_only": False,
        "lot_size": 1,
        "settlement": "T+1",
    },
    "crypto": {
        "maximum_weight": 0.20,
        "maximum_industry_deviation": 0.15,
        "maximum_participation_rate": 0.05,
        "maximum_turnover": 1.50,
        "long_only": False,
        "lot_size": None,
        "settlement": "continuous",
    },
    "mt5": {
        "maximum_weight": 0.15,
        "maximum_industry_deviation": 0.10,
        "maximum_participation_rate": 0.05,
        "maximum_turnover": 1.00,
        "long_only": False,
        "lot_size": None,
        "settlement": "broker_contract",
    },
}


def validate_target_market_portfolio_constraints(
    *,
    market: str,
    weights: dict[str, float],
    industries: dict[str, str],
    benchmark_industry_weights: dict[str, float],
    average_daily_values: dict[str, float],
    proposed_trade_values: dict[str, float],
    turnover: float,
    overrides: dict[str, float | bool] | None = None,
) -> dict[str, Any]:
    if market not in MARKET_PORTFOLIO_PROFILES:
        raise ValueError("不支持的目标市场组合约束")
    profile = {**MARKET_PORTFOLIO_PROFILES[market], **(overrides or {})}
    violations = []
    total_weight = sum(weights.values())
    if abs(total_weight - 1.0) > 1e-6:
        violations.append("weights_must_sum_to_one")
    if profile["long_only"] and any(weight < 0 for weight in weights.values()):
        violations.append("long_only")
    overweight = sorted(
        symbol
        for symbol, weight in weights.items()
        if abs(weight) > float(profile["maximum_weight"])
    )
    if overweight:
        violations.append("maximum_weight")
    industry_weights: dict[str, float] = {}
    for symbol, weight in weights.items():
        industry = industries.get(symbol, "unknown")
        industry_weights[industry] = industry_weights.get(industry, 0.0) + weight
    industry_deviations = {
        industry: weight - float(benchmark_industry_weights.get(industry, 0.0))
        for industry, weight in industry_weights.items()
    }
    if any(
        abs(value) > float(profile["maximum_industry_deviation"])
        for value in industry_deviations.values()
    ):
        violations.append("maximum_industry_deviation")
    participation_rates = {
        symbol: abs(float(proposed_trade_values.get(symbol, 0.0)))
        / max(float(average_daily_values.get(symbol, 0.0)), 1e-12)
        for symbol in weights
    }
    if any(
        rate > float(profile["maximum_participation_rate"]) for rate in participation_rates.values()
    ):
        violations.append("maximum_participation_rate")
    if turnover > float(profile["maximum_turnover"]):
        violations.append("maximum_turnover")
    return {
        "passed": not violations,
        "market": market,
        "profile": profile,
        "violations": sorted(set(violations)),
        "overweight_symbols": overweight,
        "industry_weights": {key: round(value, 8) for key, value in industry_weights.items()},
        "industry_deviations": {key: round(value, 8) for key, value in industry_deviations.items()},
        "participation_rates": {key: round(value, 8) for key, value in participation_rates.items()},
        "turnover": turnover,
    }


def portfolio_incremental_value_report(
    candidate_returns: pd.Series | list[float],
    benchmark_returns: pd.Series | list[float],
    *,
    candidate_turnover: pd.Series | list[float] | None = None,
    benchmark_turnover: pd.Series | list[float] | None = None,
    candidate_capacity: pd.Series | list[float] | None = None,
    benchmark_capacity: pd.Series | list[float] | None = None,
    transaction_cost_bps: float = 10.0,
    risk_constraints: dict[str, float] | None = None,
) -> dict[str, Any]:
    frame = pd.DataFrame(
        {
            "candidate": candidate_returns,
            "benchmark": benchmark_returns,
        }
    ).replace([np.inf, -np.inf], np.nan)
    frame = frame.dropna()
    if len(frame) < 3:
        raise ValueError("组合增量报告至少需要 3 个共同观测")
    candidate_turnover_series = (
        pd.Series(candidate_turnover, dtype=float).reindex(frame.index).fillna(0.0)
        if candidate_turnover is not None
        else pd.Series(0.0, index=frame.index)
    )
    benchmark_turnover_series = (
        pd.Series(benchmark_turnover, dtype=float).reindex(frame.index).fillna(0.0)
        if benchmark_turnover is not None
        else pd.Series(0.0, index=frame.index)
    )
    candidate_net = frame["candidate"] - candidate_turnover_series * transaction_cost_bps / 10_000
    benchmark_net = frame["benchmark"] - benchmark_turnover_series * transaction_cost_bps / 10_000

    def metrics(values: pd.Series) -> dict[str, float]:
        equity = (1 + values).cumprod()
        drawdown = equity.div(equity.cummax()).sub(1)
        var_95 = float(values.quantile(0.05))
        tail = values.loc[values.le(var_95)]
        return {
            "total_return": float(equity.iloc[-1] - 1),
            "max_drawdown": float(drawdown.min()),
            "cvar_95": float(tail.mean()) if not tail.empty else var_95,
        }

    candidate_metrics = metrics(candidate_net)
    benchmark_metrics = metrics(benchmark_net)
    candidate_capacity_value = (
        float(pd.Series(candidate_capacity, dtype=float).median())
        if candidate_capacity is not None
        else None
    )
    benchmark_capacity_value = (
        float(pd.Series(benchmark_capacity, dtype=float).median())
        if benchmark_capacity is not None
        else None
    )
    increments = {
        "total_return": candidate_metrics["total_return"] - benchmark_metrics["total_return"],
        "turnover": float(candidate_turnover_series.mean() - benchmark_turnover_series.mean()),
        "capacity": (
            candidate_capacity_value - benchmark_capacity_value
            if candidate_capacity_value is not None and benchmark_capacity_value is not None
            else None
        ),
        "max_drawdown": candidate_metrics["max_drawdown"] - benchmark_metrics["max_drawdown"],
        "cvar_95": candidate_metrics["cvar_95"] - benchmark_metrics["cvar_95"],
    }
    improved_objectives = [
        key
        for key, improved in {
            "total_return": increments["total_return"] > 0,
            "turnover": increments["turnover"] < 0,
            "capacity": increments["capacity"] is not None and increments["capacity"] > 0,
            "max_drawdown": increments["max_drawdown"] > 0,
            "cvar_95": increments["cvar_95"] > 0,
        }.items()
        if improved
    ]
    constraints = risk_constraints or {}
    violations = []
    maximum_drawdown = constraints.get("maximum_drawdown")
    if maximum_drawdown is not None and candidate_metrics["max_drawdown"] < -abs(maximum_drawdown):
        violations.append("maximum_drawdown")
    minimum_cvar = constraints.get("minimum_cvar_95")
    if minimum_cvar is not None and candidate_metrics["cvar_95"] < minimum_cvar:
        violations.append("minimum_cvar_95")
    maximum_turnover = constraints.get("maximum_turnover")
    if maximum_turnover is not None and float(candidate_turnover_series.mean()) > maximum_turnover:
        violations.append("maximum_turnover")
    adopted = bool(improved_objectives) and not violations
    return {
        "adopted": adopted,
        "decision": "combination_adopted" if adopted else "research_valid_combination_not_adopted",
        "cost_adjusted": True,
        "transaction_cost_bps": transaction_cost_bps,
        "candidate": {key: round(value, 8) for key, value in candidate_metrics.items()},
        "benchmark": {key: round(value, 8) for key, value in benchmark_metrics.items()},
        "increments": {
            key: None if value is None else round(value, 8) for key, value in increments.items()
        },
        "improved_objectives": improved_objectives,
        "risk_constraints_passed": not violations,
        "risk_violations": violations,
        "observations": len(frame),
    }
