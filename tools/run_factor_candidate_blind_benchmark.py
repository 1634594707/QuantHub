"""Run the preregistered fixed-budget factor-candidate blind benchmark.

The generator side never receives rolling-validation data or its fingerprint. The
output is evidence about candidate-source quality, not permission to trade.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from apps.api.domains.factor_factory.alpha_mining import (
    AI_PROMPT_VERSION,
    ALPHA_MINING_VERSION,
    AlphaProposal,
    generate_ai_proposals,
    generate_grammar_proposals,
)
from apps.api.domains.factor_factory.schemas import FactorFactoryStartRequest
from apps.api.domains.factor_factory.service import (
    CandidateSpec,
    _ast_complexity,
    _ast_operator_families,
    _backtest_partition,
    _brain_candidate_specs,
    _candidate_preflight,
    _candidate_specs,
    _preliminary_gate,
    _score,
    _shift_ast_parameters,
    _split_frame,
)
from core.backtest.dataset import generate_dataset
from core.backtest.market_data import fingerprint_frame
from core.factor_dsl import (
    FactorDefinition,
    FactorDslError,
    evaluate_factor_ast,
    validate_factor_definition,
)

OUTPUT = Path("docs/Plan/evidence/factor-cohort-v1-2026-08-12")
DEFAULT_OUTPUT = OUTPUT / "ai-candidate-blind-benchmark.json"
SOURCE_ORDER = ("ai", "template", "random_dsl", "symbolic_regression", "human")
BATCHES = (
    {
        "batch_id": "blind-a",
        "preset": "uptrend",
        "dataset_seed": 81201,
        "generator_seed": 91801,
    },
    {
        "batch_id": "blind-b",
        "preset": "sideways",
        "dataset_seed": 81202,
        "generator_seed": 91802,
    },
    {
        "batch_id": "blind-c",
        "preset": "volatile",
        "dataset_seed": 81203,
        "generator_seed": 91803,
    },
)
PROTOCOL = {
    "version": "factor-candidate-blind-benchmark-v1",
    "batch_count": len(BATCHES),
    "preregistered_batches": BATCHES,
    "candidate_budget_per_source_per_batch": 6,
    "sources": list(SOURCE_ORDER),
    "market": "crypto",
    "symbol": "BTCUSDT",
    "interval": "4h",
    "bars_per_batch": 720,
    "commission_bps": 3.0,
    "generation_inputs": [
        "market",
        "symbol",
        "interval",
        "cost_and_risk_contract",
        "generic_research_brief",
    ],
    "hidden_from_generation": [
        "rolling_validation_rows",
        "rolling_validation_fingerprint",
        "rolling_validation_returns",
        "program_gate_results",
        "relative_benchmark_results",
        "locked_confirmation_rows",
    ],
    "evaluation_denominator": "requested fixed candidate budget",
    "relative_benchmark": "max(cash_return, buy_and_hold_after_shared_cost_return)",
    "semantic_duplicate_threshold": 0.985,
    "adjacent_parameter_rule": "same AST after removing window/period values and all changed values have ratio <= 1.5 or absolute difference <= 3",
    "ai_diversity_thresholds": {
        "minimum_generated_candidates": 12,
        "maximum_adjacent_window_only_rate": 0.40,
        "maximum_family_concentration": 0.50,
        "minimum_unique_economic_mechanism_rate": 0.60,
        "minimum_operator_family_count": 4,
    },
    "quality_upgrade_claim": {
        "minimum_blind_batches_with_ai_samples": 3,
        "requires_prior_prompt_or_model_baseline": True,
        "requires_positive_effective_nonduplicate_rate_delta_in_every_batch": True,
        "requires_positive_gate_or_excess_rate_delta_in_majority_of_batches": True,
    },
    "confirmation_labels_accessed": False,
    "live_trading_enabled": False,
}


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _manual_proposals() -> list[AlphaProposal]:
    close = {"op": "field", "name": "close"}
    high = {"op": "field", "name": "high"}
    low = {"op": "field", "name": "low"}
    volume = {"op": "field", "name": "volume"}
    returns_1 = {"op": "pct_change", "value": close, "periods": 1}
    rows = [
        (
            "manual_risk_adjusted_trend",
            "manual_trend",
            {
                "op": "div",
                "left": {"op": "pct_change", "value": close, "periods": 24},
                "right": {"op": "rolling_std", "value": returns_1, "window": 24},
            },
            "Persistent price displacement should be discounted when realized risk expands.",
        ),
        (
            "manual_liquidity_reversal",
            "manual_reversal",
            {
                "op": "mul",
                "left": {
                    "op": "neg",
                    "value": {"op": "rolling_zscore", "value": returns_1, "window": 18},
                },
                "right": {"op": "rank", "value": volume, "window": 36},
            },
            "Short price shocks are more likely to mean-revert when liquidity participation is high.",
        ),
        (
            "manual_breakout_pressure",
            "manual_breakout",
            {
                "op": "div",
                "left": {
                    "op": "sub",
                    "left": close,
                    "right": {"op": "rolling_max", "value": high, "window": 36},
                },
                "right": {"op": "rolling_std", "value": close, "window": 36},
            },
            "A volatility-scaled range break may identify persistent supply-demand imbalance.",
        ),
        (
            "manual_path_efficiency",
            "manual_efficiency",
            {
                "op": "div",
                "left": {
                    "op": "abs",
                    "value": {"op": "pct_change", "value": close, "periods": 24},
                },
                "right": {
                    "op": "rolling_sum",
                    "value": {"op": "abs", "value": returns_1},
                    "window": 24,
                },
            },
            "Net displacement per unit of traveled path may separate clean trends from noise.",
        ),
        (
            "manual_close_location",
            "manual_order_flow_proxy",
            {
                "op": "rolling_mean",
                "value": {
                    "op": "mul",
                    "left": {
                        "op": "sub",
                        "left": {
                            "op": "div",
                            "left": {"op": "sub", "left": close, "right": low},
                            "right": {"op": "sub", "left": high, "right": low},
                        },
                        "right": {"op": "const", "value": 0.5},
                    },
                    "right": {"op": "rank", "value": volume, "window": 24},
                },
                "window": 6,
            },
            "Repeated closes near one side of the range with active volume may proxy order pressure.",
        ),
        (
            "manual_volatility_state",
            "manual_regime",
            {
                "op": "neg",
                "value": {
                    "op": "rolling_zscore",
                    "value": {"op": "rolling_std", "value": returns_1, "window": 12},
                    "window": 72,
                },
            },
            "Volatility compression may be associated with more stable subsequent risk taking.",
        ),
    ]
    return [
        AlphaProposal(
            candidate_id=candidate_id,
            label=candidate_id.replace("_", " "),
            family=family,
            source="human",
            ast=ast,
            hypothesis=hypothesis,
            invalidation="The mechanism fails the shared validation and stress gates.",
            research_claims={"economic_mechanism": hypothesis},
        )
        for candidate_id, family, ast, hypothesis in rows
    ]


def _source_specs(
    source: str,
    *,
    run_id: str,
    seed: int,
    budget: int,
    interval: str,
    provider: str | None,
    maximum_ai_tokens: int,
) -> tuple[list[CandidateSpec], dict[str, Any]]:
    started = time.perf_counter()
    if source == "ai":
        proposals, audit = generate_ai_proposals(
            brief=(
                "Find causal price-volume alpha expressions with stable after-cost returns, "
                "controlled drawdown, distinct economic mechanisms, and falsifiable failure states."
            ),
            interval=interval,
            count=budget,
            market="crypto",
            maximum_tokens=maximum_ai_tokens,
            provider=provider,
            market_context={
                "market": "crypto",
                "symbol": "BTCUSDT",
                "interval": interval,
                "commission_bps": PROTOCOL["commission_bps"],
                "execution_delay": "one_bar",
                "risk_budget": "shared_preregistered_gate",
                "blind_generation_nonce": seed,
            },
        )
        specs = _brain_candidate_specs(run_id, proposals)
    elif source == "template":
        pool = _candidate_specs(run_id, 30, interval=interval)
        specs = [item for item in pool if item.source == "template"][:budget]
        audit = {"status": "generated", "candidate_count": len(specs), "token_usage": {}}
    elif source in {"random_dsl", "symbolic_regression"}:
        proposals = generate_grammar_proposals(
            seed=seed,
            count=budget,
            interval=interval,
            market="crypto",
            source_mode=source,
        )
        specs = _brain_candidate_specs(run_id, proposals)
        audit = {"status": "generated", "candidate_count": len(specs), "token_usage": {}}
    elif source == "human":
        specs = _brain_candidate_specs(run_id, _manual_proposals()[:budget])
        audit = {"status": "generated", "candidate_count": len(specs), "token_usage": {}}
    else:
        raise ValueError(f"unknown source: {source}")
    return specs, {**audit, "wall_time_ms": round((time.perf_counter() - started) * 1000, 3)}


def _parameter_signature(node: Any) -> Any:
    if isinstance(node, list):
        return [_parameter_signature(item) for item in node]
    if not isinstance(node, dict):
        return node
    return {
        key: "<parameter>" if key in {"window", "periods"} else _parameter_signature(value)
        for key, value in sorted(node.items())
    }


def _parameters(node: Any) -> tuple[int, ...]:
    values: list[int] = []
    if isinstance(node, dict):
        for key, value in sorted(node.items()):
            if key in {"window", "periods"} and isinstance(value, int):
                values.append(value)
            else:
                values.extend(_parameters(value))
    elif isinstance(node, list):
        for value in node:
            values.extend(_parameters(value))
    return tuple(values)


def _adjacent_parameter_candidate_ids(specs: list[CandidateSpec]) -> set[str]:
    grouped: dict[str, list[CandidateSpec]] = {}
    for spec in specs:
        grouped.setdefault(_canonical_hash(_parameter_signature(spec.ast)), []).append(spec)
    adjacent: set[str] = set()
    for group in grouped.values():
        for index, left in enumerate(group):
            left_values = _parameters(left.ast)
            for right in group[index + 1 :]:
                right_values = _parameters(right.ast)
                if len(left_values) != len(right_values) or left_values == right_values:
                    continue
                if all(
                    abs(a - b) <= 3 or max(a, b) / max(1, min(a, b)) <= 1.5
                    for a, b in zip(left_values, right_values, strict=True)
                ):
                    adjacent.update((left.key, right.key))
    return adjacent


def _evaluate_metrics(
    spec: CandidateSpec,
    *,
    frame: pd.DataFrame,
    partitions: dict[str, pd.DataFrame],
    req: FactorFactoryStartRequest,
) -> tuple[dict[str, Any], dict[str, Any], float]:
    raw_signal = evaluate_factor_ast(spec.ast, frame)
    signal = pd.Series(np.tanh(raw_signal.astype(float) / 2), index=frame.index)
    signal_by_time = pd.Series(signal.to_numpy(), index=frame["datetime"])
    metrics: dict[str, Any] = {}
    for partition_name in ("discovery", "rolling_validation"):
        partition = partitions[partition_name]
        partition_signal = signal_by_time.reindex(partition["datetime"]).reset_index(drop=True)
        metrics[partition_name] = _backtest_partition(partition, partition_signal, req=req)
    validation = partitions["rolling_validation"]
    validation_signal = signal_by_time.reindex(validation["datetime"]).reset_index(drop=True)
    metrics["rolling_validation_cost_stress"] = _backtest_partition(
        validation,
        validation_signal,
        req=req,
        commission_bps=min(200.0, req.commission_bps * 2),
    )
    metrics["rolling_validation_delay_stress"] = _backtest_partition(
        validation,
        validation_signal.shift(1).fillna(0),
        req=req,
    )
    metrics["rolling_validation_capacity_stress"] = _backtest_partition(
        validation,
        validation_signal,
        req=req,
        position_fraction=0.25,
    )
    perturbed = validation.copy()
    noise = pd.Series(
        np.sin(np.arange(len(perturbed), dtype=float)) * 0.0005, index=perturbed.index
    )
    for column in ("open", "high", "low", "close"):
        perturbed[column] = perturbed[column].astype(float) * (1 + noise)
    perturbed_signal = evaluate_factor_ast(spec.ast, perturbed)
    metrics["rolling_validation_data_perturbation"] = _backtest_partition(
        perturbed,
        pd.Series(np.tanh(perturbed_signal.astype(float) / 2), index=perturbed.index),
        req=req,
    )
    neighbor_returns: list[float] = []
    for multiplier in (0.8, 1.2):
        neighbor_ast = _shift_ast_parameters(spec.ast, multiplier)
        neighbor_signal = evaluate_factor_ast(neighbor_ast, validation)
        neighbor = _backtest_partition(
            validation,
            pd.Series(np.tanh(neighbor_signal.astype(float) / 2), index=validation.index),
            req=req,
        )
        neighbor_returns.append(float(neighbor["summary"]["total_return"]))
    metrics["parameter_plateau"] = {
        "neighbor_returns": neighbor_returns,
        "positive_neighbors": sum(
            value >= req.thresholds.minimum_validation_return for value in neighbor_returns
        ),
        "return_dispersion": float(np.std(neighbor_returns)),
        "passed": all(
            value >= req.thresholds.minimum_validation_return for value in neighbor_returns
        ),
    }
    metrics["complexity"] = _ast_complexity(spec.ast)
    return metrics, _preliminary_gate(metrics, req), _score(metrics)


def _source_result(
    source: str,
    *,
    specs: list[CandidateSpec],
    generation_audit: dict[str, Any],
    frame: pd.DataFrame,
    partitions: dict[str, pd.DataFrame],
    req: FactorFactoryStartRequest,
    budget: int,
    benchmark_return: float,
) -> dict[str, Any]:
    legal_specs: list[CandidateSpec] = []
    invalid: list[dict[str, str]] = []
    formula_hashes: list[str] = []
    for spec in specs:
        try:
            definition = FactorDefinition(
                key=spec.key,
                label=spec.label,
                market=req.market,
                ast=spec.ast,
                family=spec.family,
            )
            validate_factor_definition(definition)
            legal_specs.append(spec)
            formula_hashes.append(definition.formula_hash)
        except (FactorDslError, KeyError, TypeError, ValueError) as exc:
            invalid.append({"candidate_id": spec.key, "reason": str(exc)})
    accepted, rejected, preflight = _candidate_preflight(
        legal_specs,
        partitions["discovery"],
        budget=budget,
    )
    adjacent_ids = _adjacent_parameter_candidate_ids(legal_specs)
    evaluated: list[dict[str, Any]] = []
    evaluation_errors: list[dict[str, str]] = []
    started = time.perf_counter()
    for spec in accepted:
        try:
            metrics, gate, score = _evaluate_metrics(
                spec,
                frame=frame,
                partitions=partitions,
                req=req,
            )
            summary = metrics["rolling_validation"]["summary"]
            validation_return = float(summary["total_return"])
            evaluated.append(
                {
                    "candidate_id": spec.key,
                    "family": spec.family,
                    "formula_hash": FactorDefinition(
                        key=spec.key,
                        label=spec.label,
                        market=req.market,
                        ast=spec.ast,
                        family=spec.family,
                    ).formula_hash,
                    "complexity": metrics["complexity"],
                    "operator_families": sorted(_ast_operator_families(spec.ast)),
                    "adjacent_window_only_variant": spec.key in adjacent_ids,
                    "economic_mechanism": str(
                        spec.research_claims.get("economic_mechanism") or spec.hypothesis
                    ),
                    "validation_return": validation_return,
                    "validation_sharpe": (summary.get("metrics") or {}).get("sharpe"),
                    "relative_benchmark_excess": validation_return - benchmark_return,
                    "relative_benchmark_exceeded": validation_return > benchmark_return,
                    "gate_passed": bool(gate["passed"]),
                    "gate": gate,
                    "score": score,
                }
            )
        except (FactorDslError, KeyError, TypeError, ValueError) as exc:
            evaluation_errors.append({"candidate_id": spec.key, "reason": str(exc)})
    evaluation_ms = round((time.perf_counter() - started) * 1000, 3)
    token_usage = generation_audit.get("token_usage") or {}
    total_tokens = int(token_usage.get("total_tokens") or 0)
    mechanism_count = len(
        {
            str(item["economic_mechanism"]).strip().lower()
            for item in evaluated
            if str(item["economic_mechanism"]).strip()
        }
    )
    family_counts = Counter(item.family for item in legal_specs)
    generated_count = len(specs)
    nonduplicate_count = len(accepted)
    gate_pass_count = sum(item["gate_passed"] for item in evaluated)
    excess_count = sum(item["relative_benchmark_exceeded"] for item in evaluated)
    deterministic_bar_operations = len(evaluated) * (
        len(partitions["discovery"]) + 7 * len(partitions["rolling_validation"])
    )
    return {
        "source": source,
        "requested_budget": budget,
        "generation": generation_audit,
        "generated_count": generated_count,
        "generation_shortfall": budget - generated_count,
        "legal_count": len(legal_specs),
        "legal_rate": len(legal_specs) / budget,
        "exact_duplicate_count": len(formula_hashes) - len(set(formula_hashes)),
        "semantic_nonduplicate_count": nonduplicate_count,
        "nonduplicate_rate": nonduplicate_count / budget,
        "research_gate_pass_count": gate_pass_count,
        "research_gate_pass_rate": gate_pass_count / budget,
        "relative_benchmark_excess_count": excess_count,
        "relative_benchmark_excess_rate": excess_count / budget,
        "family_count": len(family_counts),
        "family_concentration": max(family_counts.values(), default=0) / max(1, len(legal_specs)),
        "operator_families": sorted(
            {family for item in evaluated for family in item["operator_families"]}
        ),
        "unique_economic_mechanism_count": mechanism_count,
        "unique_economic_mechanism_rate": mechanism_count / budget,
        "adjacent_window_only_count": len(adjacent_ids),
        "adjacent_window_only_rate": len(adjacent_ids) / budget,
        "compute_cost": {
            "generation_wall_time_ms": generation_audit.get("wall_time_ms"),
            "evaluation_wall_time_ms": evaluation_ms,
            "deterministic_backtest_bar_operations": deterministic_bar_operations,
            "bar_operations_per_requested_candidate": deterministic_bar_operations / budget,
            "llm_total_tokens": total_tokens,
            "llm_tokens_per_requested_candidate": total_tokens / budget,
            "llm_tokens_per_legal_candidate": (
                total_tokens / len(legal_specs) if legal_specs else None
            ),
        },
        "preflight": preflight,
        "invalid": invalid,
        "evaluation_errors": evaluation_errors,
        "candidates": evaluated,
        "confirmation_labels_accessed": False,
        "live_trading_enabled": False,
    }


def _aggregate(batch_results: list[dict[str, Any]], budget: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    total_budget = budget * len(batch_results)
    for source in SOURCE_ORDER:
        rows = [batch["sources"][source] for batch in batch_results]
        totals = {
            "requested_budget": total_budget,
            "generated_count": sum(row["generated_count"] for row in rows),
            "legal_count": sum(row["legal_count"] for row in rows),
            "semantic_nonduplicate_count": sum(row["semantic_nonduplicate_count"] for row in rows),
            "research_gate_pass_count": sum(row["research_gate_pass_count"] for row in rows),
            "relative_benchmark_excess_count": sum(
                row["relative_benchmark_excess_count"] for row in rows
            ),
            "adjacent_window_only_count": sum(row["adjacent_window_only_count"] for row in rows),
            "llm_total_tokens": sum(row["compute_cost"]["llm_total_tokens"] for row in rows),
            "deterministic_backtest_bar_operations": sum(
                row["compute_cost"]["deterministic_backtest_bar_operations"] for row in rows
            ),
        }
        mechanisms = {
            str(candidate["economic_mechanism"]).strip().lower()
            for row in rows
            for candidate in row["candidates"]
            if str(candidate["economic_mechanism"]).strip()
        }
        family_counts = Counter(
            candidate["family"] for row in rows for candidate in row["candidates"]
        )
        operators = sorted(
            {
                family
                for row in rows
                for candidate in row["candidates"]
                for family in candidate["operator_families"]
            }
        )
        result[source] = {
            **totals,
            "legal_rate": totals["legal_count"] / total_budget,
            "nonduplicate_rate": totals["semantic_nonduplicate_count"] / total_budget,
            "research_gate_pass_rate": totals["research_gate_pass_count"] / total_budget,
            "relative_benchmark_excess_rate": (
                totals["relative_benchmark_excess_count"] / total_budget
            ),
            "adjacent_window_only_rate": totals["adjacent_window_only_count"] / total_budget,
            "unique_economic_mechanism_count": len(mechanisms),
            "unique_economic_mechanism_rate": len(mechanisms) / total_budget,
            "family_count": len(family_counts),
            "family_concentration": (
                max(family_counts.values(), default=0) / max(1, sum(family_counts.values()))
            ),
            "operator_families": operators,
            "operator_family_count": len(operators),
            "batch_rates": [
                {
                    "batch_id": batch["batch_id"],
                    "legal_rate": batch["sources"][source]["legal_rate"],
                    "nonduplicate_rate": batch["sources"][source]["nonduplicate_rate"],
                    "research_gate_pass_rate": batch["sources"][source]["research_gate_pass_rate"],
                    "relative_benchmark_excess_rate": batch["sources"][source][
                        "relative_benchmark_excess_rate"
                    ],
                }
                for batch in batch_results
            ],
        }
    return result


def run_benchmark(
    *,
    budget: int = 6,
    provider: str | None = None,
    maximum_ai_tokens: int = 12_000,
) -> dict[str, Any]:
    if budget != PROTOCOL["candidate_budget_per_source_per_batch"]:
        raise ValueError(
            "budget differs from preregistration; update the protocol version before changing it"
        )
    protocol_hash = _canonical_hash(PROTOCOL)
    batch_results: list[dict[str, Any]] = []
    for batch_index, batch in enumerate(BATCHES, start=1):
        frame = generate_dataset(
            preset=str(batch["preset"]),
            seed=int(batch["dataset_seed"]),
            n_bars=int(PROTOCOL["bars_per_batch"]),
            interval=str(PROTOCOL["interval"]),
            start="2024-01-01",
        )
        frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
        partitions = _split_frame(frame)
        validation_fingerprint = fingerprint_frame(partitions["rolling_validation"])
        label_commitment = _canonical_hash(
            {
                "protocol_hash": protocol_hash,
                "batch_id": batch["batch_id"],
                "rolling_validation_fingerprint": validation_fingerprint,
            }
        )
        req = FactorFactoryStartRequest(
            market="crypto",
            source="synthetic",
            symbol=str(PROTOCOL["symbol"]),
            dataset=str(batch["preset"]),
            seed=int(batch["dataset_seed"]),
            interval=str(PROTOCOL["interval"]),
            n_bars=int(PROTOCOL["bars_per_batch"]),
            candidate_budget=budget,
            candidate_mode="library",
            use_ai=False,
            ai_candidate_count=0,
            commission_bps=float(PROTOCOL["commission_bps"]),
        )
        validation = partitions["rolling_validation"]
        buy_hold = _backtest_partition(
            validation,
            pd.Series(np.ones(len(validation)), index=validation.index),
            req=req,
        )
        benchmark_return = max(0.0, float(buy_hold["summary"]["total_return"]))
        sources: dict[str, Any] = {}
        for source_index, source in enumerate(SOURCE_ORDER, start=1):
            run_id = f"blind{batch_index}{source_index}".ljust(32, "0")
            try:
                specs, generation_audit = _source_specs(
                    source,
                    run_id=run_id,
                    seed=int(batch["generator_seed"]) + source_index * 10_000,
                    budget=budget,
                    interval=str(PROTOCOL["interval"]),
                    provider=provider,
                    maximum_ai_tokens=maximum_ai_tokens,
                )
            except Exception as exc:  # noqa: BLE001 - failed generators remain evidence
                specs = []
                generation_audit = {
                    "status": "failed",
                    "candidate_count": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                    "token_usage": {},
                    "wall_time_ms": None,
                }
            sources[source] = _source_result(
                source,
                specs=specs,
                generation_audit=generation_audit,
                frame=frame,
                partitions=partitions,
                req=req,
                budget=budget,
                benchmark_return=benchmark_return,
            )
        batch_results.append(
            {
                "batch_id": batch["batch_id"],
                "generation_context": {
                    "market": PROTOCOL["market"],
                    "symbol": PROTOCOL["symbol"],
                    "interval": PROTOCOL["interval"],
                    "commission_bps": PROTOCOL["commission_bps"],
                    "validation_labels_exposed": False,
                },
                "hidden_label_commitment": label_commitment,
                "revealed_after_generation": {
                    "dataset_preset": batch["preset"],
                    "dataset_seed": batch["dataset_seed"],
                    "rolling_validation_fingerprint": validation_fingerprint,
                    "rolling_validation_rows": len(validation),
                    "relative_benchmark_return": benchmark_return,
                },
                "sources": sources,
                "confirmation_labels_accessed": False,
            }
        )
    aggregate = _aggregate(batch_results, budget)
    ai = aggregate["ai"]
    thresholds = PROTOCOL["ai_diversity_thresholds"]
    ai_batches_with_samples = sum(
        batch["sources"]["ai"]["generated_count"] > 0 for batch in batch_results
    )
    ai_diversity_checks = {
        "minimum_generated_candidates": ai["generated_count"]
        >= thresholds["minimum_generated_candidates"],
        "maximum_adjacent_window_only_rate": ai["adjacent_window_only_rate"]
        <= thresholds["maximum_adjacent_window_only_rate"],
        "maximum_family_concentration": ai["family_concentration"]
        <= thresholds["maximum_family_concentration"],
        "minimum_unique_economic_mechanism_rate": ai["unique_economic_mechanism_rate"]
        >= thresholds["minimum_unique_economic_mechanism_rate"],
        "minimum_operator_family_count": ai["operator_family_count"]
        >= thresholds["minimum_operator_family_count"],
    }
    fair_budget = all(
        batch["sources"][source]["requested_budget"] == budget
        for batch in batch_results
        for source in SOURCE_ORDER
    )
    all_sources_sampled = all(
        batch["sources"][source]["generated_count"] > 0
        for batch in batch_results
        for source in SOURCE_ORDER
    )
    metrics_complete = all(
        key in aggregate[source]
        for source in SOURCE_ORDER
        for key in (
            "legal_rate",
            "nonduplicate_rate",
            "research_gate_pass_rate",
            "relative_benchmark_excess_rate",
            "deterministic_backtest_bar_operations",
        )
    )
    quality_claim_blockers = []
    if ai_batches_with_samples < len(BATCHES):
        quality_claim_blockers.append("ai_samples_missing_in_one_or_more_blind_batches")
    quality_claim_blockers.append("no_preregistered_prior_prompt_or_model_baseline_in_this_run")
    if not all(ai_diversity_checks.values()):
        quality_claim_blockers.append("ai_diversity_thresholds_not_all_met")
    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "generator": "tools/run_factor_candidate_blind_benchmark.py",
        "evidence_kind": "fixed_budget_multi_batch_blind_benchmark",
        "protocol": PROTOCOL,
        "protocol_hash": protocol_hash,
        "implementation_versions": {
            "alpha_mining": ALPHA_MINING_VERSION,
            "ai_prompt": AI_PROMPT_VERSION,
        },
        "batches": batch_results,
        "aggregate": aggregate,
        "ai_diversity_checks": ai_diversity_checks,
        "conclusion": {
            "fixed_budget_protocol_executed": fair_budget,
            "fixed_budget_five_source_comparison_completed": fair_budget and all_sources_sampled,
            "required_metric_schema_recorded": metrics_complete,
            "required_five_source_metrics_completed": metrics_complete and all_sources_sampled,
            "multi_batch_ai_quality_test_completed": ai_batches_with_samples == len(BATCHES),
            "ai_candidate_diversity_preregistered_thresholds_passed": all(
                ai_diversity_checks.values()
            ),
            "prompt_or_model_quality_improvement_supported": False,
            "quality_improvement_claim_blockers": quality_claim_blockers,
            "roadmap_claims_supported": {
                "fixed_candidate_budget_comparison": fair_budget and all_sources_sampled,
                "quality_and_compute_metrics": metrics_complete and all_sources_sampled,
                "multi_batch_upgrade_quality_claim": False,
                "ai_not_mainly_adjacent_window_variants": False,
                "reproducible_effective_nonduplicate_improvement": False,
            },
        },
        "confirmation_labels_accessed": False,
        "locked_confirmation_evaluated": False,
        "live_trading_enabled": False,
    }
    return result


def _update_manifest(output_path: Path) -> None:
    manifest_path = output_path.parent / "manifest.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = set(manifest.get("files") or [])
    files.add(output_path.name)
    manifest["files"] = sorted(files)
    manifest["ai_candidate_blind_benchmark"] = output_path.name
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--provider", default=None)
    parser.add_argument("--maximum-ai-tokens", type=int, default=12_000)
    args = parser.parse_args()
    result = run_benchmark(
        provider=args.provider,
        maximum_ai_tokens=args.maximum_ai_tokens,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _update_manifest(args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "protocol_hash": result["protocol_hash"],
                "conclusion": result["conclusion"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
