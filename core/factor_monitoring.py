from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def candidate_inbox_report(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a review inbox without collapsing research and trading states."""
    allowed_sources = {"human", "ai", "template", "random_dsl", "symbolic_regression"}
    rows = []
    for candidate in candidates:
        source = str(candidate.get("source", ""))
        if source not in allowed_sources:
            raise ValueError(f"不支持的候选来源: {source}")
        causal_passed = bool(candidate.get("causal_check_passed"))
        data_passed = bool(candidate.get("data_check_passed"))
        future_passed = bool(candidate.get("future_information_check_passed"))
        approved = bool(candidate.get("approved_by")) and bool(candidate.get("budget_approved"))
        can_backtest = causal_passed and data_passed and future_passed and approved
        blockers = []
        if not causal_passed:
            blockers.append("causal_check")
        if not data_passed:
            blockers.append("data_check")
        if not future_passed:
            blockers.append("future_information_check")
        if not candidate.get("approved_by"):
            blockers.append("researcher_approval")
        if not candidate.get("budget_approved"):
            blockers.append("budget_approval")
        rows.append(
            {
                **candidate,
                "source": source,
                "approval_status": "approved" if approved else "pending",
                "can_start_backtest": can_backtest,
                "start_backtest_entry_visible": can_backtest,
                "blockers": blockers,
                "states": {
                    "exploration_score": candidate.get("exploration_score"),
                    "research_status": candidate.get("research_status", "not_started"),
                    "trading_status": candidate.get("trading_status", "not_validated"),
                    "ai_review": candidate.get("ai_review"),
                },
            }
        )
    counts = {source: sum(row["source"] == source for row in rows) for source in allowed_sources}
    return {
        "candidates": rows,
        "count": len(rows),
        "source_counts": dict(sorted(counts.items())),
        "approved_count": sum(row["approval_status"] == "approved" for row in rows),
        "backtest_ready_count": sum(row["can_start_backtest"] for row in rows),
        "single_score_used": False,
    }


def factor_retirement_impact_preview(
    *,
    factor_key: str,
    replacement_factor_key: str | None,
    strategies: list[dict[str, Any]],
    portfolio_allocations: list[dict[str, Any]],
) -> dict[str, Any]:
    impacted_strategies = []
    for strategy in strategies:
        factor_keys = list(strategy.get("factor_keys", []))
        if factor_key not in factor_keys:
            continue
        projected = [key for key in factor_keys if key != factor_key]
        if replacement_factor_key and replacement_factor_key not in projected:
            projected.append(replacement_factor_key)
        impacted_strategies.append(
            {
                **strategy,
                "current_factor_keys": factor_keys,
                "projected_factor_keys": projected,
                "replacement_available": replacement_factor_key is not None,
            }
        )
    impacted_allocations = [
        allocation
        for allocation in portfolio_allocations
        if factor_key in allocation.get("factor_keys", [])
        or allocation.get("factor_key") == factor_key
    ]
    impacted_weight = sum(float(item.get("weight", 0.0)) for item in impacted_allocations)
    return {
        "factor_key": factor_key,
        "replacement_factor_key": replacement_factor_key,
        "impacted_strategies": impacted_strategies,
        "impacted_strategy_count": len(impacted_strategies),
        "impacted_portfolio_allocations": impacted_allocations,
        "impacted_portfolio_weight": round(impacted_weight, 8),
        "uncovered_after_retirement": bool(impacted_strategies and not replacement_factor_key),
        "definition_deletion_allowed": False,
        "required_change": "append_retirement_event_and_preserve_historical_definition",
    }


def _population_stability_index(reference: np.ndarray, current: np.ndarray) -> float:
    edges = np.unique(np.quantile(reference, np.linspace(0, 1, 11)))
    if len(edges) < 3:
        center = float(reference[0]) if len(reference) else 0.0
        edges = np.array([-math.inf, center, math.inf])
    else:
        edges[0], edges[-1] = -math.inf, math.inf
    expected = np.histogram(reference, bins=edges)[0].astype(float)
    actual = np.histogram(current, bins=edges)[0].astype(float)
    expected = np.clip(expected / max(expected.sum(), 1.0), 1e-6, None)
    actual = np.clip(actual / max(actual.sum(), 1.0), 1e-6, None)
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def _distribution_distance(reference: np.ndarray, current: np.ndarray) -> float:
    quantiles = np.linspace(0.01, 0.99, 99)
    reference_quantiles = np.quantile(reference, quantiles)
    current_quantiles = np.quantile(current, quantiles)
    scale = max(float(np.std(reference)), 1e-12)
    return float(np.mean(np.abs(current_quantiles - reference_quantiles)) / scale)


def _correlation_structure_shift(
    reference: dict[str, list[float]], current: dict[str, list[float]]
) -> float:
    common = sorted(set(reference) & set(current))
    if len(common) < 2:
        return 0.0
    reference_corr = pd.DataFrame({key: reference[key] for key in common}).corr().to_numpy()
    current_corr = pd.DataFrame({key: current[key] for key in common}).corr().to_numpy()
    upper = np.triu_indices(len(common), 1)
    differences = np.abs(reference_corr[upper] - current_corr[upper])
    return float(np.nanmean(differences)) if len(differences) else 0.0


def factor_drift_report(
    *,
    reference_values: list[float],
    current_values: list[float],
    reference_ic: float,
    current_ic: float,
    reference_coverage: float,
    current_coverage: float,
    current_cost_bps: float,
    current_capacity_ratio: float,
    reference_correlated_factors: dict[str, list[float]],
    current_correlated_factors: dict[str, list[float]],
    thresholds: dict[str, float],
    affected_strategies: list[dict[str, Any]],
    factor_key: str,
) -> dict[str, Any]:
    reference = np.asarray(reference_values, dtype=float)
    current = np.asarray(current_values, dtype=float)
    reference = reference[np.isfinite(reference)]
    current = current[np.isfinite(current)]
    if len(reference) < 20 or len(current) < 20:
        raise ValueError("漂移监控的参考期和当前期都至少需要 20 个有效观测")
    required_thresholds = {
        "maximum_ic_decay",
        "maximum_coverage_drop",
        "maximum_psi",
        "maximum_distribution_distance",
        "maximum_correlation_shift",
        "maximum_cost_bps",
        "minimum_capacity_ratio",
    }
    missing = sorted(required_thresholds - set(thresholds))
    if missing:
        raise ValueError("漂移阈值必须预注册: " + ", ".join(missing))

    psi = _population_stability_index(reference, current)
    distance = _distribution_distance(reference, current)
    correlation_shift = _correlation_structure_shift(
        reference_correlated_factors, current_correlated_factors
    )
    ic_decay = 1 - abs(current_ic) / max(abs(reference_ic), 1e-12)
    coverage_drop = reference_coverage - current_coverage
    checks = {
        "ic_decay": ic_decay <= thresholds["maximum_ic_decay"],
        "direction_flip": reference_ic * current_ic >= 0,
        "coverage_drop": coverage_drop <= thresholds["maximum_coverage_drop"],
        "population_stability_index": psi <= thresholds["maximum_psi"],
        "distribution_distance": distance <= thresholds["maximum_distribution_distance"],
        "correlation_structure_shift": correlation_shift <= thresholds["maximum_correlation_shift"],
        "cost_breakout": current_cost_bps <= thresholds["maximum_cost_bps"],
        "capacity_decay": current_capacity_ratio >= thresholds["minimum_capacity_ratio"],
    }
    alerts = sorted(key for key, passed in checks.items() if not passed)
    impacted = [
        {
            **strategy,
            "impact": "blocks_new_version" if strategy.get("active", True) else "historical_only",
        }
        for strategy in affected_strategies
        if factor_key in strategy.get("factor_keys", [])
    ]
    return {
        "passed": not alerts,
        "degrade_required": bool(alerts),
        "alerts": alerts,
        "metrics": {
            "reference_ic": reference_ic,
            "current_ic": current_ic,
            "ic_decay": round(ic_decay, 6),
            "coverage_drop": round(coverage_drop, 6),
            "psi": round(psi, 6),
            "distribution_distance": round(distance, 6),
            "correlation_structure_shift": round(correlation_shift, 6),
            "current_cost_bps": current_cost_bps,
            "current_capacity_ratio": current_capacity_ratio,
        },
        "thresholds": thresholds,
        "thresholds_preregistered": True,
        "affected_strategies": impacted,
        "affected_strategy_count": len(impacted),
        "required_action": (
            "alert_degrade_and_locate_within_one_schedule_cycle"
            if alerts
            else "continue_monitoring"
        ),
    }


def simulation_validation_report(
    *,
    completed_rebalance_cycles: int,
    after_cost_return: float,
    fill_rate: float,
    capacity_ratio: float,
    thresholds: dict[str, float],
    execution_records: list[dict[str, Any]],
) -> dict[str, Any]:
    required_fields = {
        "signal_time",
        "tradable_time",
        "theoretical_price",
        "simulated_price",
        "slippage_bps",
        "rejection_reason",
        "capacity_used",
    }
    incomplete = [
        index
        for index, record in enumerate(execution_records)
        if not required_fields.issubset(record)
    ]
    checks = {
        "complete_rebalance_cycle": completed_rebalance_cycles >= 1,
        "after_cost_performance": after_cost_return >= thresholds["minimum_after_cost_return"],
        "fill_rate": fill_rate >= thresholds["minimum_fill_rate"],
        "capacity": capacity_ratio >= thresholds["minimum_capacity_ratio"],
        "execution_audit_complete": not incomplete and bool(execution_records),
    }
    violations = sorted(key for key, passed in checks.items() if not passed)
    return {
        "eligible_for_trading_validated": not violations,
        "violations": violations,
        "checks": checks,
        "completed_rebalance_cycles": completed_rebalance_cycles,
        "thresholds": thresholds,
        "execution_record_count": len(execution_records),
        "incomplete_execution_record_indices": incomplete,
        "live_trading_enabled": False,
        "evidence_scope": "shadow_or_simulation_only",
    }


def research_simulation_gap_attribution(
    research_returns: list[float],
    simulation_returns: list[float],
    *,
    signal_decay: list[float],
    data_delay: list[float],
    execution: list[float],
    costs: list[float],
    portfolio_constraints: list[float],
    research_metrics: dict[str, float],
    simulation_metrics: dict[str, float],
) -> dict[str, Any]:
    series = {
        "research": research_returns,
        "simulation": simulation_returns,
        "signal_decay": signal_decay,
        "data_delay": data_delay,
        "execution": execution,
        "costs": costs,
        "portfolio_constraints": portfolio_constraints,
    }
    lengths = {len(values) for values in series.values()}
    if len(lengths) != 1 or not lengths or next(iter(lengths)) < 1:
        raise ValueError("研究与模拟收益归因序列必须非空且长度一致")
    research = np.asarray(research_returns, dtype=float)
    simulation = np.asarray(simulation_returns, dtype=float)
    gap = simulation - research
    components = {
        key: float(np.sum(np.asarray(values, dtype=float)))
        for key, values in series.items()
        if key not in {"research", "simulation"}
    }
    explained = sum(components.values())
    total_gap = float(np.sum(gap))
    required_metrics = {"ic", "coverage", "turnover", "cost_bps", "fill_rate"}
    missing_research = sorted(required_metrics - set(research_metrics))
    missing_simulation = sorted(required_metrics - set(simulation_metrics))
    if missing_research or missing_simulation:
        raise ValueError("研究期和模拟期必须同时提供 IC、覆盖率、换手、成本和成交率")
    return {
        "total_research_return": round(float(np.sum(research)), 8),
        "total_simulation_return": round(float(np.sum(simulation)), 8),
        "total_gap": round(total_gap, 8),
        "components": {key: round(value, 8) for key, value in components.items()},
        "unexplained_residual": round(total_gap - explained, 8),
        "component_names_locked": sorted(components),
        "research_metrics": research_metrics,
        "simulation_metrics": simulation_metrics,
        "metric_deltas": {
            key: round(float(simulation_metrics[key] - research_metrics[key]), 8)
            for key in sorted(required_metrics)
        },
    }
