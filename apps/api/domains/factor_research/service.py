from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pandas as pd

from apps.api import store
from apps.api.domains.instrument import service as instrument_service
from apps.api.domains.research.service import dataframe_snapshot, snapshot_hash
from core.cross_sectional_research import (
    MARKET_VALIDATION_THRESHOLDS,
    CrossSectionConfig,
    InsufficientCrossSectionData,
    analyze_cross_sectional_factors,
)
from core.data_feed.factory import get_data_source
from core.data_feed.quality import assess_ohlcv
from core.factor_dsl import (
    FIELD_UNITS,
    FactorDefinition,
    FactorDslError,
    FactorDslLimits,
    builtin_factor_definitions,
    count_parameter_combinations,
    detect_factor_redundancy,
    validate_factor_data_coverage,
    validate_factor_definition,
)
from core.factor_monitoring import (
    candidate_inbox_report,
    factor_drift_report,
    factor_retirement_impact_preview,
    research_simulation_gap_attribution,
    simulation_validation_report,
)
from core.factor_research import (
    FACTOR_RESEARCH_ENGINE_VERSION,
    InsufficientFactorData,
    ResearchConfig,
    analyze_factors,
    benjamini_hochberg,
    block_bootstrap_reality_check,
    deflated_sharpe_ratio,
)
from core.factor_robustness import (
    compare_discovery_efficiency,
    data_perturbation_test,
    nested_nonlinear_benchmark,
    orthogonalized_incremental_ic,
    parameter_plateau_test,
    pareto_rank,
    placebo_test,
    portfolio_incremental_value_report,
    simple_portfolio_benchmarks,
    validate_target_market_portfolio_constraints,
)

from .ai_review import AI_REVIEW_TIMEOUT_SECONDS, run_ai_review
from .schemas import (
    CrossSectionResearchRequest,
    FactorAiReviewRequest,
    FactorAiSearchRoundRequest,
    FactorCandidateInboxRequest,
    FactorCandidateValidationRequest,
    FactorConfirmationSetOpenRequest,
    FactorDefinitionCreate,
    FactorDiscoveryEfficiencyRequest,
    FactorDriftMonitoringRequest,
    FactorExperimentCreate,
    FactorExperimentEventCreate,
    FactorLifecycleTransitionRequest,
    FactorPortfolioConstraintRequest,
    FactorRedundancyRequest,
    FactorResearchPlanCreate,
    FactorResearchRequest,
    FactorRetirementImpactRequest,
    FactorRobustnessRequest,
    FactorSimulationAttributionRequest,
    FactorSimulationValidationRequest,
    FactorUniverseCreate,
    FactorUniverseMemberUpsert,
    TokenFormulaImportRequest,
)

logger = logging.getLogger(__name__)

CURRENT_FACTOR_ENGINE_VERSION = FACTOR_RESEARCH_ENGINE_VERSION

FACTOR_RESEARCH_MODULE = "factor_research"
FACTOR_RESULT_EVIDENCE = "factor_research_result"
FACTOR_AI_EVIDENCE = "factor_ai_review"
FACTOR_MARKET_SNAPSHOT_EVIDENCE = "market_snapshot"
CROSS_SECTION_MODULE = "cross_sectional_factor_research"
CROSS_SECTION_RESULT_EVIDENCE = "cross_sectional_factor_result"
UNIVERSE_SNAPSHOT_EVIDENCE = "universe_snapshot"

FACTOR_EXPERIMENT_TRANSITIONS = {
    "draft": {"queued", "rejected", "cancelled"},
    "queued": {"running", "rejected", "cancelled"},
    "running": {"succeeded", "failed", "cancelled"},
    "succeeded": set(),
    "failed": set(),
    "rejected": set(),
    "cancelled": set(),
}

FACTOR_LIFECYCLE_TRANSITIONS = {
    "draft": {"exploratory", "retired"},
    "exploratory": {"research_passed", "retired"},
    "research_passed": {"trading_validated", "degraded", "retired"},
    "trading_validated": {"degraded", "retired"},
    "degraded": {"research_passed", "retired"},
    "retired": set(),
}
FACTOR_LIFECYCLE_EVIDENCE_FIELDS = {
    "formula_definition_hash",
    "formula_hash",
    "formula_version",
    "data_snapshot_hash",
    "cumulative_attempts",
    "validation_window",
    "cost_profile_version",
    "gate_version",
}


def _periods_per_year(market: str, interval: str) -> int:
    normalized = interval.lower()
    if market == "crypto":
        return {"1h": 8_760, "4h": 2_190, "1d": 365}.get(normalized, 365)
    if market == "mt5":
        return {"1h": 6_240, "4h": 1_560, "1d": 252}.get(normalized, 252)
    return {"1h": 1_512, "4h": 378, "1d": 252, "1w": 52}.get(normalized, 252)


def _factor_definition_payload(definition: FactorDefinition) -> dict:
    validation = validate_factor_definition(definition)
    return {
        **definition.to_dict(),
        "validation": {
            "unit": validation.unit,
            "shape": validation.shape,
            "fields": list(validation.fields),
            "depth": validation.depth,
            "operators": validation.operators,
        },
    }


def seed_builtin_factor_definitions() -> dict:
    definitions = []
    for definition in builtin_factor_definitions():
        definitions.append(store.create_factor_definition(_factor_definition_payload(definition)))
    return {
        "ok": True,
        "count": len(definitions),
        "definitions": definitions,
        "formula_version": definitions[0]["version"] if definitions else None,
    }


def _ensure_builtin_factor_definitions() -> None:
    definitions = builtin_factor_definitions()
    if any(store.get_factor_definition(item.key, item.version) is None for item in definitions):
        seed_builtin_factor_definitions()


def _definition_from_saved(saved: dict) -> FactorDefinition:
    return FactorDefinition(
        key=saved["key"],
        label=saved["label"],
        market=saved["market"],
        ast=saved["ast"],
        direction=saved["direction"],
        horizon=saved["horizon"],
        availability_lag=saved["availability_lag"],
        rationale=saved["rationale"],
        family=saved["family"],
        version=saved["version"],
        parameters=saved["parameters"],
    )


def register_factor_definition(req: FactorDefinitionCreate) -> dict:
    _ensure_builtin_factor_definitions()
    try:
        definition = FactorDefinition(**req.model_dump())
        saved = store.create_factor_definition(_factor_definition_payload(definition))
    except (FactorDslError, TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "definition": saved}


def import_token_formula_definitions(req: TokenFormulaImportRequest) -> dict:
    """Map controlled engine tokens into immutable, auditable FactorDefinitions."""

    _ensure_builtin_factor_definitions()
    try:
        if req.engine == "alphagpt":
            from strategies.crypto.alphagpt.formula_adapter import factor_definitions
        else:
            from strategies.mt5.alphamaster.formula_adapter import factor_definitions

        definitions = factor_definitions(
            req.formulas,
            key_prefix=req.key_prefix,
            label_prefix=req.label_prefix,
            version=req.version,
            horizon=req.horizon,
            availability_lag=req.availability_lag,
            rationale=req.rationale,
        )
        saved = [
            store.create_factor_definition(_factor_definition_payload(item)) for item in definitions
        ]
    except (FactorDslError, TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "engine": req.engine,
        "count": len(saved),
        "definitions": saved,
    }


def list_registered_factor_definitions(
    *, market: str | None = None, family: str | None = None
) -> dict:
    _ensure_builtin_factor_definitions()
    definitions = store.list_factor_definitions(market=market, family=family)
    return {"ok": True, "count": len(definitions), "definitions": definitions}


def get_registered_factor_definition(factor_key: str, version: str) -> dict:
    _ensure_builtin_factor_definitions()
    definition = store.get_factor_definition(factor_key, version)
    if definition is None:
        return {"ok": False, "error": "因子定义不存在"}
    return {"ok": True, "definition": definition}


def _validate_lifecycle_evidence(
    definition: dict,
    req: FactorLifecycleTransitionRequest,
) -> dict[str, Any]:
    evidence = dict(req.evidence)
    missing = sorted(FACTOR_LIFECYCLE_EVIDENCE_FIELDS - evidence.keys())
    if missing:
        raise ValueError(f"生命周期证据缺少字段: {', '.join(missing)}")
    if evidence["formula_definition_hash"] != definition["definition_hash"]:
        raise ValueError("生命周期证据的定义哈希与注册表不一致")
    if evidence["formula_hash"] != definition["formula_hash"]:
        raise ValueError("生命周期证据的公式哈希与注册表不一致")
    if evidence["formula_version"] != definition["version"]:
        raise ValueError("生命周期证据的公式版本与注册表不一致")
    data_hash = evidence["data_snapshot_hash"]
    if (
        not isinstance(data_hash, str)
        or len(data_hash) != 64
        or any(character not in "0123456789abcdef" for character in data_hash.lower())
    ):
        raise ValueError("生命周期证据必须包含 64 位数据快照哈希")
    attempts = evidence["cumulative_attempts"]
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
        raise ValueError("cumulative_attempts 必须为非负整数")
    window = evidence["validation_window"]
    if not isinstance(window, dict) or not window.get("start") or not window.get("end"):
        raise ValueError("validation_window 必须包含 start 和 end")
    for field in ("cost_profile_version", "gate_version"):
        if not isinstance(evidence[field], str) or not evidence[field].strip():
            raise ValueError(f"{field} 必须为非空字符串")
    evidence["target_market"] = req.target_market
    evidence["lifecycle_schema_version"] = "1.0.0"
    return evidence


def transition_factor_lifecycle(
    factor_key: str,
    version: str,
    req: FactorLifecycleTransitionRequest,
) -> dict:
    _ensure_builtin_factor_definitions()
    definition = store.get_factor_definition(factor_key, version)
    if definition is None:
        return {"ok": False, "error": "因子定义不存在"}
    if definition["market"] not in {"all", req.target_market}:
        return {"ok": False, "error": "因子定义市场与生命周期目标市场不一致"}
    current = store.ensure_factor_lifecycle_draft(definition["id"], req.target_market)
    if current is None:
        return {"ok": False, "error": "无法初始化因子生命周期"}
    if req.actor_type == "ai":
        return {"ok": False, "error": "AI 只能解释证据或提交候选，不能修改因子生命周期"}
    if req.state not in FACTOR_LIFECYCLE_TRANSITIONS.get(current["state"], set()):
        return {
            "ok": False,
            "error": f"不允许从 {current['state']} 转换到 {req.state}",
        }
    try:
        evidence = _validate_lifecycle_evidence(definition, req)
        if current["state"] == "degraded" and req.state in {"research_passed", "retired"}:
            observed_periods = evidence.get("observed_periods")
            required_periods = evidence.get("required_observation_periods")
            if (
                isinstance(observed_periods, bool)
                or not isinstance(observed_periods, int)
                or isinstance(required_periods, bool)
                or not isinstance(required_periods, int)
                or required_periods < 1
                or observed_periods < required_periods
            ):
                raise ValueError("degraded 状态必须完成预注册观察周期")
            if evidence.get("human_reviewed") is not True:
                raise ValueError("degraded 状态恢复或退役必须经过人工复核")
            if req.state == "research_passed" and evidence.get("recovery_gate_passed") is not True:
                raise ValueError("degraded 恢复必须重新通过恢复门禁")
            if req.state == "retired" and not str(evidence.get("retirement_reason", "")).strip():
                raise ValueError("degraded 退役必须记录 retirement_reason")
        if req.state == "exploratory":
            if req.rule not in {"candidate_approved", "coverage_validated"}:
                raise ValueError("探索候选只能由候选批准或覆盖率门禁产生")
            if evidence["cumulative_attempts"] < 1:
                raise ValueError("探索候选必须至少记录一次试验尝试")
        elif req.state == "research_passed":
            if req.rule != "locked_out_of_sample_statistical_gate":
                raise ValueError("research_passed 只能由锁定的样本外统计门禁产生")
            required_flags = {
                "locked_out_of_sample": True,
                "statistical_gate_passed": True,
                "ai_accessed_locked_labels": False,
                "window_majority_passed": True,
                "group_stability_passed": True,
                "parameter_plateau_passed": True,
            }
            for field, expected in required_flags.items():
                if evidence.get(field) is not expected:
                    raise ValueError(f"research_passed 证据要求 {field}={expected}")
            plan_id = evidence.get("research_plan_id")
            experiment_ids = evidence.get("experiment_ids")
            if not isinstance(plan_id, str) or not plan_id:
                raise ValueError("research_passed 必须回链研究计划")
            if not isinstance(experiment_ids, list) or not experiment_ids:
                raise ValueError("research_passed 必须回链至少一个成功实验")
            experiments = [store.get_factor_experiment(item) for item in experiment_ids]
            if any(item is None for item in experiments):
                raise ValueError("research_passed 引用了不存在的实验")
            if any(
                item["research_plan_id"] != plan_id
                or item["factor_definition_id"] != definition["id"]
                or item["target_market"] != req.target_market
                or item["status"] != "succeeded"
                for item in experiments
                if item is not None
            ):
                raise ValueError("research_passed 的实验、因子、市场或成功状态不一致")
            if evidence["cumulative_attempts"] < max(
                item["attempt_number"] for item in experiments if item is not None
            ):
                raise ValueError("cumulative_attempts 低于已记录实验次数")
        elif req.state == "trading_validated":
            if req.rule != "target_market_trading_gate":
                raise ValueError("trading_validated 只能由目标市场交易门禁产生")
            for field in (
                "cost_passed",
                "capacity_passed",
                "execution_passed",
                "incremental_value_passed",
                "simulation_validation_passed",
                "after_cost_performance_passed",
                "fill_rate_passed",
            ):
                if evidence.get(field) is not True:
                    raise ValueError(f"trading_validated 证据要求 {field}=True")
            if not evidence.get("simulation_run_id"):
                raise ValueError("trading_validated 必须回链模拟交易运行")
            if int(evidence.get("completed_rebalance_cycles", 0)) < 1:
                raise ValueError("trading_validated 至少需要一个完整模拟再平衡周期")
            if int(evidence.get("execution_record_count", 0)) < 1:
                raise ValueError("trading_validated 必须保存逐笔模拟执行审计")
            if evidence.get("observation_period_completed") is not True:
                raise ValueError("trading_validated 必须完成模拟观察期")
            observed_days = evidence.get("observation_days_completed")
            if (
                isinstance(observed_days, bool)
                or not isinstance(observed_days, int | float)
                or float(observed_days) < 7
            ):
                raise ValueError("trading_validated 必须完成至少 7 个真实自然日的模拟观察")
            try:
                observed_from = datetime.fromisoformat(str(evidence["observation_started_at"]))
                observed_to = datetime.fromisoformat(str(evidence["observation_ended_at"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("trading_validated 必须保存模拟观察起止时间") from exc
            if observed_from.tzinfo is None or observed_to.tzinfo is None:
                raise ValueError("模拟观察起止时间必须包含时区")
            if observed_to - observed_from < timedelta(days=7):
                raise ValueError("trading_validated 模拟观察起止时间不足 7 天")
        elif req.state == "degraded":
            if req.rule not in {
                "monitoring_gate_failed",
                "ic_decay",
                "data_drift",
                "cost_breakout",
                "capacity_decay",
            } or not evidence.get("degradation_reason"):
                raise ValueError("degraded 必须由监控门禁失败并保存降级原因")
        elif req.state == "retired":
            if req.rule != "retirement_review" or not evidence.get("retirement_reason"):
                raise ValueError("retired 必须保存人工复核后的退役原因")
        event = store.append_factor_lifecycle_event(
            definition["id"],
            expected_state=current["state"],
            state=req.state,
            target_market=req.target_market,
            actor_type=req.actor_type,
            actor=req.actor,
            rule=req.rule,
            evidence=evidence,
        )
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "factor_key": factor_key,
        "version": version,
        "previous_state": current["state"],
        "current_state": event["state"],
        "event": event,
    }


def get_factor_lifecycle(
    factor_key: str,
    version: str,
    target_market: str | None = None,
) -> dict:
    _ensure_builtin_factor_definitions()
    definition = store.get_factor_definition(factor_key, version)
    if definition is None:
        return {"ok": False, "error": "因子定义不存在"}
    if target_market:
        store.ensure_factor_lifecycle_draft(definition["id"], target_market)
    events = store.list_factor_lifecycle_events(definition["id"], target_market=target_market)
    current_by_market: dict[str, dict] = {}
    for event in events:
        current_by_market[event["target_market"]] = event
    return {
        "ok": True,
        "factor_key": factor_key,
        "version": version,
        "definition_hash": definition["definition_hash"],
        "current_by_market": current_by_market,
        "events": events,
    }


def validate_factor_candidate_data(req: FactorCandidateValidationRequest) -> dict:
    _ensure_builtin_factor_definitions()
    saved = store.get_factor_definition(req.factor_key, req.factor_version)
    if saved is None:
        return {"ok": False, "error": "因子定义尚未注册或版本不存在"}
    definition = _definition_from_saved(saved)
    try:
        report = validate_factor_data_coverage(
            definition,
            pd.DataFrame(req.rows),
            FactorDslLimits(minimum_data_coverage=req.minimum_data_coverage),
        )
    except FactorDslError as exc:
        return {"ok": False, "error": str(exc)}
    validation = store.create_factor_candidate_validation(
        saved["id"],
        snapshot_hash(req.rows),
        {
            **report,
            "minimum_data_coverage": req.minimum_data_coverage,
            "definition_hash": saved["definition_hash"],
        },
    )
    return {"ok": True, "validation": validation}


def analyze_factor_redundancy(req: FactorRedundancyRequest) -> dict:
    _ensure_builtin_factor_definitions()
    definitions: list[FactorDefinition] = []
    missing: list[str] = []
    for reference in req.definitions:
        saved = store.get_factor_definition(reference.key, reference.version)
        if saved is None:
            missing.append(f"{reference.key}@{reference.version}")
        else:
            definitions.append(_definition_from_saved(saved))
    if missing:
        return {"ok": False, "error": f"因子定义不存在: {', '.join(missing)}"}
    frame = pd.DataFrame(req.rows)
    regimes = frame[req.regime_field] if req.regime_field and req.regime_field in frame else None
    try:
        correlation_pairs = detect_factor_redundancy(
            definitions,
            frame,
            minimum_observations=req.minimum_observations,
            high_correlation_threshold=req.high_correlation_threshold,
            monotonic_threshold=req.monotonic_threshold,
            tail_quantile=req.tail_quantile,
            regimes=regimes,
            include_all_pairs=True,
        )
    except FactorDslError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "definition_count": len(definitions),
        "correlation_pairs": correlation_pairs,
        "redundant_pairs": [item for item in correlation_pairs if item["relation"] != "distinct"],
        "redundant_count": sum(item["relation"] != "distinct" for item in correlation_pairs),
        "correlation_scope": {
            "tail_quantile": req.tail_quantile,
            "regime_field": req.regime_field if regimes is not None else None,
        },
    }


def analyze_factor_robustness(req: FactorRobustnessRequest) -> dict:
    factor = pd.Series(req.factor, dtype=float)
    label = pd.Series(req.label, dtype=float)
    result: dict[str, Any] = {
        "placebo": placebo_test(factor, label, seed=req.seed),
        "perturbation": data_perturbation_test(
            factor,
            label,
            liquidity=req.liquidity,
            seed=req.seed,
        ),
        "orthogonalization": orthogonalized_incremental_ic(
            factor,
            {key: pd.Series(values, dtype=float) for key, values in req.deployed_factors.items()},
            label,
        ),
    }
    if req.parameter_results:
        result["parameter_plateau"] = parameter_plateau_test(
            req.parameter_results,
            parameter=str(req.parameter_name),
            metric=str(req.parameter_metric),
            threshold=float(req.parameter_threshold),
        )
    if req.pareto_candidates:
        result["pareto"] = pareto_rank(req.pareto_candidates, req.pareto_objectives)
    if req.factor_returns:
        result["portfolio_benchmarks"] = simple_portfolio_benchmarks(
            {key: pd.Series(values, dtype=float) for key, values in req.factor_returns.items()},
            req.expected_ics,
        )
    if req.candidate_portfolio_returns is not None:
        result["portfolio_incremental_value"] = portfolio_incremental_value_report(
            req.candidate_portfolio_returns,
            req.benchmark_portfolio_returns or [],
            candidate_turnover=req.candidate_turnover,
            benchmark_turnover=req.benchmark_turnover,
            candidate_capacity=req.candidate_capacity,
            benchmark_capacity=req.benchmark_capacity,
            transaction_cost_bps=req.transaction_cost_bps,
            risk_constraints=req.risk_constraints,
        )
    if req.nonlinear_features:
        result["nonlinear_benchmark"] = nested_nonlinear_benchmark(
            {key: pd.Series(values, dtype=float) for key, values in req.nonlinear_features.items()},
            pd.Series(req.nonlinear_label, dtype=float),
            minimum_improvement=req.nonlinear_minimum_improvement,
        )
    return {
        "ok": True,
        "seed": req.seed,
        "reports": result,
        "deterministic": True,
        "dynamic_code_execution": False,
    }


def validate_factor_portfolio_constraints(req: FactorPortfolioConstraintRequest) -> dict:
    return {
        "ok": True,
        "validation": validate_target_market_portfolio_constraints(
            market=req.market,
            weights=req.weights,
            industries=req.industries,
            benchmark_industry_weights=req.benchmark_industry_weights,
            average_daily_values=req.average_daily_values,
            proposed_trade_values=req.proposed_trade_values,
            turnover=req.turnover,
            overrides=req.overrides,
        ),
    }


def build_factor_candidate_inbox(req: FactorCandidateInboxRequest) -> dict:
    return {
        "ok": True,
        "inbox": candidate_inbox_report([item.model_dump(mode="json") for item in req.candidates]),
    }


def preview_factor_retirement_impact(req: FactorRetirementImpactRequest) -> dict:
    return {
        "ok": True,
        "preview": factor_retirement_impact_preview(**req.model_dump(mode="json")),
    }


def get_factor_lineage(factor_key: str, version: str, req: FactorLineageRequest) -> dict:
    _ensure_builtin_factor_definitions()
    definition = store.get_factor_definition(factor_key, version)
    if definition is None:
        return {"ok": False, "error": "因子定义不存在"}
    target_market = req.target_market or (
        definition["market"] if definition["market"] != "all" else "a_shares"
    )
    validations = store.list_factor_candidate_validations(definition["id"], limit=100)
    experiments = [
        item
        for item in store.list_factor_experiments(limit=100_000)
        if item["factor_key"] == factor_key and item["factor_version"] == version
    ]
    experiment_details = [store.get_factor_experiment(item["id"]) for item in experiments]
    lifecycle = store.list_factor_lifecycle_events(definition["id"], target_market=target_market)
    research_runs = []
    for run in store.list_research_runs_page(
        limit=500, module=FACTOR_RESEARCH_MODULE, archived=False
    )["items"]:
        result = _saved_factor_result(run)
        factor = next(
            (item for item in (result or {}).get("factors", []) if item.get("key") == factor_key),
            None,
        )
        if factor is not None:
            research_runs.append(
                {
                    "run_id": run["id"],
                    "status": run["status"],
                    "updated_at": run["updated_at"],
                    "data_fingerprint": (result or {}).get("summary", {}).get("data_fingerprint"),
                    "factor_status": factor.get("status"),
                    "windows": factor.get("windows", []),
                }
            )
    latest_lifecycle = lifecycle[-1] if lifecycle else None
    simulation_runs = [
        {
            "simulation_run_id": event.get("evidence", {}).get("simulation_run_id"),
            "state": event["state"],
            "evidence": event.get("evidence", {}),
        }
        for event in lifecycle
        if event.get("evidence", {}).get("simulation_run_id")
    ]
    return {
        "ok": True,
        "factor_key": factor_key,
        "version": version,
        "target_market": target_market,
        "definition": {
            "definition_hash": definition["definition_hash"],
            "formula_hash": definition["formula_hash"],
            "ast": definition.get("ast"),
            "input_fields": definition.get("input_fields", []),
            "rationale": definition.get("rationale", ""),
            "parameters": definition.get("parameters", {}),
        },
        "trace": {
            "ai_hypothesis": [
                {
                    "source": item["source"],
                    "hypothesis": item["hypothesis"],
                    "proposal": item.get("proposal", {}),
                    "prompt": item.get("prompt", {}),
                }
                for item in experiment_details
                if item is not None
            ],
            "dsl": {"ast": definition.get("ast"), "formula_hash": definition["formula_hash"]},
            "data_validation": validations,
            "experiments": experiment_details,
            "statistics": research_runs,
            "portfolio_decisions": [
                {"state": event["state"], "rule": event["rule"], "evidence": event["evidence"]}
                for event in lifecycle
            ],
            "simulation": simulation_runs,
        },
        "current_state": latest_lifecycle["state"] if latest_lifecycle else "draft",
        "evidence_complete": bool(validations and experiment_details and research_runs),
        "historical_definition_preserved": True,
    }


def analyze_factor_drift(req: FactorDriftMonitoringRequest) -> dict:
    payload = req.model_dump(mode="json")
    factor_version = payload.pop("factor_version")
    target_market = payload.pop("target_market")
    auto_degrade = payload.pop("auto_degrade")
    report = factor_drift_report(**payload)
    lifecycle_action = _apply_drift_lifecycle_action(
        factor_key=req.factor_key,
        factor_version=factor_version,
        target_market=target_market,
        report=report,
        enabled=auto_degrade,
    )
    return {
        "ok": True,
        "monitoring": {
            **report,
            "lifecycle_action": lifecycle_action,
            "completed_within_schedule_cycle": lifecycle_action["status"]
            in {"degraded", "already_degraded", "not_required", "not_eligible", "disabled"},
        },
    }


def _apply_drift_lifecycle_action(
    *,
    factor_key: str,
    factor_version: str,
    target_market: str,
    report: dict[str, Any],
    enabled: bool,
) -> dict[str, Any]:
    if not report["degrade_required"]:
        return {"status": "not_required", "event": None}
    if not enabled:
        return {"status": "disabled", "event": None}
    _ensure_builtin_factor_definitions()
    definition = store.get_factor_definition(factor_key, factor_version)
    if definition is None:
        return {"status": "not_eligible", "reason": "factor_definition_missing", "event": None}
    current = store.ensure_factor_lifecycle_draft(definition["id"], target_market)
    if current is None:
        return {"status": "not_eligible", "reason": "lifecycle_missing", "event": None}
    if current["state"] == "degraded":
        return {"status": "already_degraded", "event": current, "idempotent": True}
    if current["state"] not in {"research_passed", "trading_validated"}:
        return {
            "status": "not_eligible",
            "reason": f"current_state_{current['state']}",
            "event": None,
        }
    evidence = {
        **current["evidence"],
        "degradation_reason": ",".join(report["alerts"]),
        "monitoring_alerts": report["alerts"],
        "monitoring_metrics": report["metrics"],
        "monitoring_thresholds": report["thresholds"],
        "affected_strategies": report["affected_strategies"],
        "affected_strategy_count": report["affected_strategy_count"],
        "schedule_cycle_action": "alert_degrade_and_locate",
        "live_trading_enabled": False,
    }
    transition = transition_factor_lifecycle(
        factor_key,
        factor_version,
        FactorLifecycleTransitionRequest(
            state="degraded",
            target_market=target_market,
            actor_type="system",
            actor="factor_drift_monitor",
            rule="monitoring_gate_failed",
            evidence=evidence,
        ),
    )
    if not transition["ok"]:
        return {"status": "failed", "error": transition["error"], "event": None}
    return {"status": "degraded", "event": transition["event"], "idempotent": False}


def validate_factor_simulation(req: FactorSimulationValidationRequest) -> dict:
    return {
        "ok": True,
        "validation": simulation_validation_report(**req.model_dump(mode="json")),
    }


def attribute_factor_simulation_gap(req: FactorSimulationAttributionRequest) -> dict:
    payload = req.model_dump(mode="json")
    return {
        "ok": True,
        "attribution": research_simulation_gap_attribution(
            payload.pop("research_returns"),
            payload.pop("simulation_returns"),
            **payload,
        ),
    }


def compare_factor_discovery_efficiency(req: FactorDiscoveryEfficiencyRequest) -> dict:
    report = compare_discovery_efficiency(
        [item.model_dump(mode="json") for item in req.candidates],
        per_source_budget=req.per_source_budget,
    )
    return {"ok": True, "report": report}


def _factor_plan_usage(plan_id: str) -> dict[str, int]:
    experiments = store.list_factor_experiments(research_plan_id=plan_id, limit=100_000)
    confirmation_opening = store.get_factor_confirmation_opening(plan_id)
    return {
        "candidates": sum(item["parameter_combinations"] for item in experiments),
        "compute_units": sum(item["estimated_compute_units"] for item in experiments),
        "llm_tokens": sum(
            int(item["pre_registration"].get("maximum_llm_tokens", 0)) for item in experiments
        ),
        "confirmation_set_openings": int(confirmation_opening is not None),
        "confirmation_set_openings_reserved": sum(
            int(item["pre_registration"].get("confirmation_set_openings", 0))
            for item in experiments
        ),
        "experiments": len(experiments),
    }


def create_factor_research_plan_record(req: FactorResearchPlanCreate) -> dict:
    budget = {
        "maximum_candidates": req.maximum_candidates,
        "maximum_compute_units": req.maximum_compute_units,
        "maximum_llm_tokens": req.maximum_llm_tokens,
        "maximum_confirmation_set_openings": req.maximum_confirmation_set_openings,
        "maximum_round_candidates": req.maximum_round_candidates,
        "maximum_formula_complexity": req.maximum_formula_complexity,
        "maximum_duplicate_rate": req.maximum_duplicate_rate,
        "stop_conditions": req.stop_conditions,
        "data_split": req.data_split.model_dump(mode="json") if req.data_split else None,
    }
    try:
        plan = store.create_factor_research_plan(req.id, req.title, req.target_market, budget)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "plan": plan, "usage": _factor_plan_usage(req.id)}


def list_factor_research_plan_records(target_market: str | None = None) -> dict:
    plans = store.list_factor_research_plans(target_market)
    return {
        "ok": True,
        "count": len(plans),
        "plans": [{**plan, "usage": _factor_plan_usage(plan["id"])} for plan in plans],
    }


def get_factor_research_plan_record(plan_id: str) -> dict:
    plan = store.get_factor_research_plan(plan_id)
    if plan is None:
        return {"ok": False, "error": "研究计划不存在"}
    return {"ok": True, "plan": plan, "usage": _factor_plan_usage(plan_id)}


def get_factor_confirmation_set_opening(plan_id: str) -> dict:
    if store.get_factor_research_plan(plan_id) is None:
        return {"ok": False, "error": "研究计划不存在"}
    opening = store.get_factor_confirmation_opening(plan_id)
    return {"ok": True, "opened": opening is not None, "opening": opening}


def open_factor_confirmation_set(plan_id: str, req: FactorConfirmationSetOpenRequest) -> dict:
    plan = store.get_factor_research_plan(plan_id)
    if plan is None:
        return {"ok": False, "error": "研究计划不存在"}
    data_split = plan["budget"].get("data_split")
    if not isinstance(data_split, dict):
        return {"ok": False, "error": "研究计划未预注册发现集、滚动验证集和锁定确认集"}

    existing = store.get_factor_confirmation_opening(plan_id)
    normalized_fingerprint = req.confirmation_data_fingerprint.lower()
    if existing is not None:
        same_request = (
            existing["experiment_id"] == req.experiment_id
            and existing["confirmation_data_fingerprint"] == normalized_fingerprint
            and existing["opened_by"] == req.opened_by
            and existing["irreversible_ack"] is req.irreversible_ack
        )
        if not same_request:
            return {"ok": False, "error": "锁定确认集已经开启且审计记录不可修改"}
        return {
            "ok": True,
            "opened": True,
            "opening": existing,
            "idempotent_replay": True,
            "further_experiments_blocked": True,
        }

    locked_confirmation = data_split.get("locked_confirmation", {})
    expected_fingerprint = str(locked_confirmation.get("data_fingerprint", "")).lower()
    if normalized_fingerprint != expected_fingerprint:
        return {"ok": False, "error": "确认集数据指纹与预注册锁定分区不一致"}

    experiment = store.get_factor_experiment(req.experiment_id)
    if experiment is None:
        return {"ok": False, "error": "用于开启确认集的实验不存在"}
    if experiment["research_plan_id"] != plan_id:
        return {"ok": False, "error": "实验不属于当前研究计划"}
    if experiment["status"] != "succeeded":
        return {"ok": False, "error": "只有已成功完成的预注册实验才能开启确认集"}
    if int(experiment["pre_registration"].get("confirmation_set_openings", 0)) != 1:
        return {"ok": False, "error": "实验未预注册一次确认集开启权限"}
    if int(plan["budget"].get("maximum_confirmation_set_openings", 0)) < 1:
        return {"ok": False, "error": "研究计划没有确认集开启预算"}

    try:
        opening = store.create_factor_confirmation_opening(
            research_plan_id=plan_id,
            experiment_id=req.experiment_id,
            confirmation_data_fingerprint=normalized_fingerprint,
            opened_by=req.opened_by,
            irreversible_ack=req.irreversible_ack,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "opened": True,
        "opening": opening,
        "idempotent_replay": False,
        "further_experiments_blocked": True,
    }


def _factor_ai_search_usage(plan_id: str) -> dict[str, int]:
    rounds = store.list_factor_ai_search_rounds(plan_id)
    return {
        "rounds": len(rounds),
        "candidates": sum(item["candidate_count"] for item in rounds),
        "duplicates": sum(item["duplicate_count"] for item in rounds),
        "llm_tokens": sum(item["llm_tokens"] for item in rounds),
        "stopped_rounds": sum(1 for item in rounds if item["stopped"]),
    }


def _factor_ai_failure_feedback(plan_id: str) -> dict[str, dict[str, Any]]:
    feedback: dict[str, dict[str, Any]] = {}
    experiments = store.list_factor_experiments(research_plan_id=plan_id, limit=100_000)
    for experiment in experiments:
        detail = store.get_factor_experiment(experiment["id"])
        for event in (detail or {}).get("events", []):
            if event["status"] not in {"failed", "rejected"}:
                continue
            failure_code = event.get("failure_code") or "other"
            item = feedback.setdefault(
                failure_code,
                {"count": 0, "reasons": [], "factor_keys": []},
            )
            item["count"] += 1
            reason = event.get("failure_reason")
            if reason and reason not in item["reasons"]:
                item["reasons"].append(reason)
            factor_key = experiment["factor_key"]
            if factor_key not in item["factor_keys"]:
                item["factor_keys"].append(factor_key)
    return dict(sorted(feedback.items()))


def factor_ai_proposal_context(plan_id: str) -> dict:
    plan = store.get_factor_research_plan(plan_id)
    if plan is None:
        return {"ok": False, "error": "研究计划不存在"}
    _ensure_builtin_factor_definitions()
    definitions = store.list_factor_definitions(market=plan["target_market"])
    definition_context = [
        {
            "key": item["factor_key"],
            "version": item["version"],
            "family": item["family"],
            "market": item["market"],
            "input_fields": item.get("input_fields", []),
            "formula_hash": item["formula_hash"],
            "rationale": item.get("rationale", ""),
        }
        for item in definitions
    ]
    formula_groups: dict[str, list[str]] = {}
    family_groups: dict[str, list[str]] = {}
    for item in definition_context:
        identity = f"{item['key']}@{item['version']}"
        formula_groups.setdefault(item["formula_hash"], []).append(identity)
        family_groups.setdefault(item["family"], []).append(identity)
    redundancy_clusters = {
        "formula_hash": [
            {"formula_hash": key, "definitions": values}
            for key, values in sorted(formula_groups.items())
            if len(values) > 1
        ],
        "family": [
            {"family": key, "definitions": values}
            for key, values in sorted(family_groups.items())
            if len(values) > 1
        ],
    }
    plan_usage = _factor_plan_usage(plan_id)
    ai_search_usage = _factor_ai_search_usage(plan_id)
    budget = plan["budget"]
    remaining_budget = {
        "candidates": max(
            0,
            int(budget["maximum_candidates"])
            - plan_usage["candidates"]
            - ai_search_usage["candidates"],
        ),
        "compute_units": max(0, int(budget["maximum_compute_units"]) - plan_usage["compute_units"]),
        "llm_tokens": max(
            0,
            int(budget["maximum_llm_tokens"])
            - plan_usage["llm_tokens"]
            - ai_search_usage["llm_tokens"],
        ),
        "confirmation_set_openings": max(
            0,
            int(budget["maximum_confirmation_set_openings"])
            - plan_usage["confirmation_set_openings"],
        ),
        "maximum_round_candidates": int(budget["maximum_round_candidates"]),
        "maximum_formula_complexity": int(budget["maximum_formula_complexity"]),
        "maximum_duplicate_rate": float(budget["maximum_duplicate_rate"]),
    }
    context = {
        "research_plan": {
            "id": plan["id"],
            "title": plan["title"],
            "target_market": plan["target_market"],
        },
        "data_catalog": [
            {"field": field, "unit": unit} for field, unit in sorted(FIELD_UNITS.items())
        ],
        "existing_factor_definitions": definition_context,
        "redundancy_clusters": redundancy_clusters,
        "failure_feedback": _factor_ai_failure_feedback(plan_id),
        "plan_usage": plan_usage,
        "ai_search_usage": ai_search_usage,
        "remaining_budget": remaining_budget,
        "stop_conditions": budget.get("stop_conditions", {}),
        "confirmation_labels_exposed": False,
    }
    context_fingerprint = hashlib.sha256(
        json.dumps(context, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return {"ok": True, "context": context, "context_fingerprint": context_fingerprint}


def validate_factor_ai_search_round(plan_id: str, req: FactorAiSearchRoundRequest) -> dict:
    plan = store.get_factor_research_plan(plan_id)
    if plan is None:
        return {"ok": False, "error": "研究计划不存在"}
    existing = store.get_factor_ai_search_round(plan_id, req.round_id)
    max_complexity = max(req.formula_complexities)
    approval = {
        "approved_by": req.approved_by,
        "approved_candidate_ids": sorted(req.approved_candidate_ids),
        "budget_approved": req.budget_approved_ack,
    }
    if existing is not None:
        same_request = (
            existing["candidate_count"] == req.candidate_count
            and existing["duplicate_count"] == req.duplicate_count
            and existing["max_formula_complexity"] == max_complexity
            and existing["llm_tokens"] == req.llm_tokens
            and existing["input_fingerprint"].lower() == req.input_fingerprint.lower()
            and existing.get("approval") == approval
        )
        if not same_request:
            return {"ok": False, "error": "AI 搜索轮次已存在且不可修改"}
        return {"ok": True, "round": existing, "idempotent_replay": True}

    budget = plan["budget"]
    rounds = store.list_factor_ai_search_rounds(plan_id)
    search_usage = _factor_ai_search_usage(plan_id)
    plan_usage = _factor_plan_usage(plan_id)
    duplicate_rate = req.duplicate_count / req.candidate_count
    violations: list[str] = []
    if rounds and rounds[-1]["stopped"]:
        violations.append("search_already_stopped")
    if req.candidate_count > int(budget["maximum_round_candidates"]):
        violations.append("round_candidate_budget")
    if max_complexity > int(budget["maximum_formula_complexity"]):
        violations.append("formula_complexity_budget")
    if duplicate_rate > float(budget["maximum_duplicate_rate"]):
        violations.append("duplicate_rate_budget")
    if plan_usage["candidates"] + search_usage["candidates"] + req.candidate_count > int(
        budget["maximum_candidates"]
    ):
        violations.append("total_candidate_budget")
    if plan_usage["llm_tokens"] + search_usage["llm_tokens"] + req.llm_tokens > int(
        budget["maximum_llm_tokens"]
    ):
        violations.append("total_llm_token_budget")

    stop_conditions = budget.get("stop_conditions", {})
    maximum_rounds = stop_conditions.get("maximum_rounds")
    if isinstance(maximum_rounds, int) and not isinstance(maximum_rounds, bool):
        if len(rounds) >= maximum_rounds:
            violations.append("maximum_rounds")
    minimum_novel = stop_conditions.get("minimum_novel_candidates")
    if isinstance(minimum_novel, int) and not isinstance(minimum_novel, bool):
        if req.candidate_count - req.duplicate_count < minimum_novel:
            violations.append("minimum_novel_candidates")
    cumulative_candidates = search_usage["candidates"] + req.candidate_count
    cumulative_duplicates = search_usage["duplicates"] + req.duplicate_count
    cumulative_duplicate_limit = stop_conditions.get("maximum_cumulative_duplicate_rate")
    if isinstance(cumulative_duplicate_limit, int | float) and not isinstance(
        cumulative_duplicate_limit, bool
    ):
        if cumulative_duplicates / cumulative_candidates > float(cumulative_duplicate_limit):
            violations.append("maximum_cumulative_duplicate_rate")
    stop_on_failure_codes = stop_conditions.get("stop_on_failure_codes", [])
    if isinstance(stop_on_failure_codes, list):
        matched_failure_codes = sorted(
            set(stop_on_failure_codes) & set(_factor_ai_failure_feedback(plan_id))
        )
        if matched_failure_codes:
            violations.append("failure_feedback:" + ",".join(matched_failure_codes))

    status = "stopped" if violations else "allowed"
    stop_reason = ";".join(violations) or None
    try:
        round_record = store.create_factor_ai_search_round(
            research_plan_id=plan_id,
            round_id=req.round_id,
            candidate_count=req.candidate_count,
            duplicate_count=req.duplicate_count,
            max_formula_complexity=max_complexity,
            llm_tokens=req.llm_tokens,
            input_fingerprint=req.input_fingerprint.lower(),
            approval=approval,
            status=status,
            stop_reason=stop_reason,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "round": round_record,
        "gate_violations": violations,
        "usage": _factor_ai_search_usage(plan_id),
        "researcher_approval": round_record["approval"],
    }


def list_factor_ai_search_round_records(plan_id: str) -> dict:
    if store.get_factor_research_plan(plan_id) is None:
        return {"ok": False, "error": "研究计划不存在"}
    rounds = store.list_factor_ai_search_rounds(plan_id)
    return {
        "ok": True,
        "count": len(rounds),
        "rounds": rounds,
        "usage": _factor_ai_search_usage(plan_id),
    }


def create_factor_experiment_record(req: FactorExperimentCreate) -> dict:
    _ensure_builtin_factor_definitions()
    plan = store.get_factor_research_plan(req.research_plan_id)
    if plan is None:
        return {"ok": False, "error": "研究计划尚未创建"}
    if store.get_factor_confirmation_opening(req.research_plan_id) is not None:
        return {"ok": False, "error": "锁定确认集已开启；继续调参必须创建新的研究计划"}
    if plan["target_market"] != req.target_market:
        return {"ok": False, "error": "实验目标市场与研究计划不一致"}
    data_split = plan["budget"].get("data_split")
    if isinstance(data_split, dict):
        if req.data_start is None or req.data_end is None:
            return {"ok": False, "error": "预注册数据分区的研究计划必须声明实验数据范围"}
        discovery_start = date.fromisoformat(data_split["discovery"]["start"])
        validation_end = date.fromisoformat(data_split["rolling_validation"]["end"])
        confirmation_start = date.fromisoformat(data_split["locked_confirmation"]["start"])
        if req.data_start < discovery_start or req.data_end > validation_end:
            return {"ok": False, "error": "实验数据范围必须限制在发现集和滚动验证集内"}
        if req.data_end >= confirmation_start:
            return {"ok": False, "error": "实验创建阶段不得读取锁定确认集"}
    definition = store.get_factor_definition(req.factor_key, req.factor_version)
    if definition is None:
        return {"ok": False, "error": "因子定义尚未注册或版本不存在"}
    if definition["market"] not in {"all", req.target_market}:
        return {"ok": False, "error": "因子定义市场与目标市场不一致"}
    candidate_validation = store.get_factor_candidate_validation(req.candidate_validation_id)
    if candidate_validation is None:
        return {"ok": False, "error": "候选尚未通过数据覆盖率验证"}
    if candidate_validation["factor_definition_id"] != definition["id"]:
        return {"ok": False, "error": "数据验证凭证与因子定义不匹配"}
    try:
        parameter_combinations = count_parameter_combinations(req.parameter_grid)
    except FactorDslError as exc:
        return {"ok": False, "error": str(exc)}
    if parameter_combinations > req.pre_registration.maximum_candidates:
        return {
            "ok": False,
            "error": "参数组合数超过预注册 maximum_candidates 预算",
        }
    usage = _factor_plan_usage(req.research_plan_id)
    requested_usage = {
        "candidates": parameter_combinations,
        "compute_units": req.estimated_compute_units,
        "llm_tokens": req.pre_registration.maximum_llm_tokens,
        "confirmation_set_openings_reserved": req.pre_registration.confirmation_set_openings,
    }
    budget_keys = {
        "candidates": "maximum_candidates",
        "compute_units": "maximum_compute_units",
        "llm_tokens": "maximum_llm_tokens",
        "confirmation_set_openings_reserved": "maximum_confirmation_set_openings",
    }
    for usage_key, budget_key in budget_keys.items():
        if usage[usage_key] + requested_usage[usage_key] > int(plan["budget"][budget_key]):
            return {"ok": False, "error": f"研究计划已超过 {budget_key} 总预算"}
    if req.parent_experiment_id:
        parent = store.get_factor_experiment(req.parent_experiment_id)
        if parent is None:
            return {"ok": False, "error": "父实验不存在"}
        if parent["research_plan_id"] != req.research_plan_id:
            return {"ok": False, "error": "父实验不属于同一研究计划"}
    try:
        experiment = store.create_factor_experiment(
            research_plan_id=req.research_plan_id,
            hypothesis=req.hypothesis,
            source=req.source,
            parent_experiment_id=req.parent_experiment_id,
            factor_definition_id=definition["id"],
            candidate_validation_id=req.candidate_validation_id,
            target_market=req.target_market,
            data_start=req.data_start.isoformat() if req.data_start else None,
            data_end=req.data_end.isoformat() if req.data_end else None,
            parameter_grid=req.parameter_grid,
            parameter_combinations=parameter_combinations,
            estimated_compute_units=req.estimated_compute_units,
            model=req.model,
            prompt=req.prompt,
            proposal={
                "applicable_regimes": req.applicable_regimes,
                "invalidation_conditions": req.invalidation_conditions,
                "falsification_tests": req.falsification_tests,
                "ai_trace": req.ai_trace,
            },
            pre_registration=req.pre_registration.model_dump(mode="json"),
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "experiment": experiment,
        "plan_usage": _factor_plan_usage(req.research_plan_id),
        "statistical_status_locked": True,
    }


def append_factor_experiment_event(experiment_id: str, req: FactorExperimentEventCreate) -> dict:
    experiment = store.get_factor_experiment(experiment_id)
    if experiment is None:
        return {"ok": False, "error": "因子实验不存在"}
    current_status = experiment["status"]
    if req.status not in FACTOR_EXPERIMENT_TRANSITIONS.get(current_status, set()):
        return {
            "ok": False,
            "error": f"不允许从 {current_status} 转换到 {req.status}；重试必须新建实验记录",
        }
    if req.status == "succeeded":
        candidates = req.result.get("candidate_results")
        if (
            not isinstance(candidates, list)
            or len(candidates) != experiment["parameter_combinations"]
        ):
            return {
                "ok": False,
                "error": "成功结果必须为每个参数组合保存 candidate_results",
            }
        for index, candidate in enumerate(candidates, start=1):
            if not isinstance(candidate, dict):
                return {"ok": False, "error": f"candidate_results[{index}] 必须为对象"}
            raw_p_value = candidate.get("raw_p_value")
            effective_sample_size = candidate.get("effective_sample_size")
            if (
                isinstance(raw_p_value, bool)
                or not isinstance(raw_p_value, int | float)
                or not 0 <= float(raw_p_value) <= 1
            ):
                return {"ok": False, "error": f"candidate_results[{index}] p 值无效"}
            if (
                isinstance(effective_sample_size, bool)
                or not isinstance(effective_sample_size, int)
                or effective_sample_size < 1
            ):
                return {
                    "ok": False,
                    "error": f"candidate_results[{index}] 有效样本量无效",
                }
    event = store.add_factor_experiment_event(
        experiment_id,
        status=req.status,
        result=req.result,
        failure_reason=req.failure_reason,
        failure_code=req.failure_code,
        evidence=req.evidence,
    )
    return {
        "ok": True,
        "event": event,
        "experiment": store.get_factor_experiment(experiment_id),
        "statistical_status_locked": True,
    }


def get_factor_experiment_record(experiment_id: str) -> dict:
    experiment = store.get_factor_experiment(experiment_id)
    if experiment is None:
        return {"ok": False, "error": "因子实验不存在"}
    return {"ok": True, "experiment": experiment}


def list_factor_experiment_records(
    *,
    research_plan_id: str | None = None,
    source: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> dict:
    experiments = store.list_factor_experiments(
        research_plan_id=research_plan_id,
        source=source,
        status=status,
        limit=limit,
    )
    return {
        "ok": True,
        "count": len(experiments),
        "cumulative_attempts": (
            max((item["attempt_number"] for item in experiments), default=0)
            if research_plan_id
            else None
        ),
        "experiments": experiments,
    }


def factor_plan_multiple_testing(plan_id: str) -> dict:
    plan = store.get_factor_research_plan(plan_id)
    if plan is None:
        return {"ok": False, "error": "研究计划不存在"}
    experiments = store.list_factor_experiments(research_plan_id=plan_id, limit=100_000)
    rows: list[dict[str, Any]] = []
    pending_candidates = 0
    terminal_statuses = {"succeeded", "failed", "rejected", "cancelled"}
    for experiment in sorted(experiments, key=lambda item: item["attempt_number"]):
        count = experiment["parameter_combinations"]
        if experiment["status"] not in terminal_statuses:
            pending_candidates += count
            continue
        if experiment["status"] == "succeeded":
            detail = store.get_factor_experiment(experiment["id"])
            terminal_event = detail["events"][-1] if detail and detail["events"] else None
            candidates = (terminal_event or {}).get("result", {}).get("candidate_results", [])
        else:
            candidates = [
                {
                    "candidate_key": f"{experiment['factor_key']}:{index + 1}",
                    "raw_p_value": 1.0,
                    "effective_sample_size": None,
                }
                for index in range(count)
            ]
        raw_values = [float(item["raw_p_value"]) for item in candidates]
        batch_adjusted = benjamini_hochberg(raw_values)
        for index, (candidate, batch_p_value) in enumerate(
            zip(candidates, batch_adjusted, strict=True), start=1
        ):
            candidate_key = candidate.get("candidate_key") or f"{experiment['factor_key']}:{index}"
            row = {
                "experiment_id": experiment["id"],
                "attempt_number": experiment["attempt_number"],
                "source": experiment["source"],
                "factor_key": experiment["factor_key"],
                "factor_family": experiment["factor_family"],
                "candidate_key": candidate_key,
                "experiment_status": experiment["status"],
                "raw_p_value": float(candidate["raw_p_value"]),
                "batch_adjusted_p_value": batch_p_value,
                "effective_sample_size": candidate.get("effective_sample_size"),
            }
            returns = candidate.get("excess_returns", candidate.get("returns"))
            if (
                isinstance(returns, list)
                and len(returns) >= 3
                and all(
                    not isinstance(value, bool) and isinstance(value, int | float)
                    for value in returns
                )
            ):
                row["_returns"] = [float(value) for value in returns]
                row["return_series_basis"] = (
                    "excess_returns" if "excess_returns" in candidate else "strategy_returns"
                )
            rows.append(row)
    global_adjusted = benjamini_hochberg([row["raw_p_value"] for row in rows])
    cumulative_candidates = sum(item["parameter_combinations"] for item in experiments)
    for row, adjusted_p_value in zip(rows, global_adjusted, strict=True):
        row["global_adjusted_p_value"] = adjusted_p_value
        if "_returns" in row:
            row["deflated_sharpe"] = deflated_sharpe_ratio(
                row["_returns"],
                trials=max(cumulative_candidates, 1),
            )
            row["return_observations"] = len(row["_returns"])
    reality_check_returns = {
        f"{row['experiment_id']}:{row['candidate_key']}": row["_returns"]
        for row in rows
        if "_returns" in row
    }
    reality_check = block_bootstrap_reality_check(
        reality_check_returns,
        bootstrap_samples=500,
        seed=int(hashlib.sha256(plan_id.encode("utf-8")).hexdigest()[:8], 16),
    )
    for row in rows:
        row.pop("_returns", None)
    return {
        "ok": True,
        "research_plan_id": plan_id,
        "target_market": plan["target_market"],
        "cumulative_experiments": len(experiments),
        "cumulative_registered_candidates": cumulative_candidates,
        "corrected_candidates": len(rows),
        "pending_candidates": pending_candidates,
        "method": "benjamini_hochberg_all_terminal_candidates",
        "deflated_sharpe_method": "deflated_sharpe_non_normal_multiple_trials",
        "reality_check": reality_check,
        "rows": rows,
    }


def create_factor_universe(req: FactorUniverseCreate) -> dict:
    try:
        universe = store.create_factor_universe(req.name, req.market, req.description)
    except sqlite3.IntegrityError:
        return {"ok": False, "error": "股票池名称已存在"}
    return {"ok": True, "universe": universe}


def list_factor_universes(market: str | None = None) -> dict:
    universes = store.list_factor_universes(market=market)
    return {"ok": True, "count": len(universes), "universes": universes}


def upsert_factor_universe_member(universe_id: str, req: FactorUniverseMemberUpsert) -> dict:
    universe = store.get_factor_universe(universe_id)
    if universe is None:
        return {"ok": False, "error": "股票池不存在"}
    try:
        instrument = instrument_service.resolve_strict(req.symbol, universe["market"])
    except instrument_service.InstrumentResolutionError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        member = store.upsert_factor_universe_member(
            universe_id=universe_id,
            instrument_id=instrument.instrument_id,
            symbol=instrument.code,
            effective_from=req.effective_from.isoformat(),
            effective_to=req.effective_to.isoformat() if req.effective_to else None,
            status=req.status,
            industry=req.industry,
            market_cap=req.market_cap,
            beta=req.beta,
            is_st=req.is_st,
            listed_at=req.listed_at.isoformat() if req.listed_at else None,
            delisted_at=req.delisted_at.isoformat() if req.delisted_at else None,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "member": member}


def list_factor_universe_members(universe_id: str, as_of: date | None = None) -> dict:
    universe = store.get_factor_universe(universe_id)
    if universe is None:
        return {"ok": False, "error": "股票池不存在"}
    members = store.list_factor_universe_members(
        universe_id,
        active_on=as_of.isoformat() if as_of else None,
    )
    return {
        "ok": True,
        "universe": universe,
        "count": len(members),
        "members": members,
    }


def run_cross_sectional_research(req: CrossSectionResearchRequest) -> dict:
    universe = store.get_factor_universe(req.universe_id)
    if universe is None:
        return {"ok": False, "error": "股票池不存在"}
    if (
        req.transaction_cost_profile is not None
        and req.transaction_cost_profile.market != universe["market"]
    ):
        return {"ok": False, "error": "transaction_cost_profile.market 与股票池市场不一致"}
    start_text = req.start_date.isoformat() if req.start_date else None
    end_text = req.end_date.isoformat() if req.end_date else None
    members = store.list_factor_universe_members(
        req.universe_id,
        start_date=start_text,
        end_date=end_text,
    )
    if not members:
        return {"ok": False, "error": "所选日期区间没有股票池成分记录"}
    request_payload = req.model_dump(mode="json", exclude={"run_id"}, exclude_none=True)
    run = store.get_research_run(req.run_id) if req.run_id else None
    if req.run_id:
        if run is None or CROSS_SECTION_MODULE not in run.get("modules", []):
            return {"ok": False, "error": "待恢复的横截面研究记录不存在"}
        saved_request = (run.get("input") or {}).get(CROSS_SECTION_MODULE)
        if isinstance(saved_request, dict):
            try:
                saved_request = CrossSectionResearchRequest(**saved_request).model_dump(
                    mode="json",
                    exclude={"run_id"},
                    exclude_none=True,
                )
            except ValueError:
                pass
        if saved_request != request_payload:
            return {"ok": False, "error": "恢复请求与原横截面研究参数不一致"}
    else:
        run = store.create_research_run(
            symbol=f"UNIVERSE:{req.universe_id}",
            market=universe["market"],
            timeframe=req.interval,
            modules=[CROSS_SECTION_MODULE],
            input_data={CROSS_SECTION_MODULE: request_payload},
            instrument_id=f"universe:{req.universe_id}",
        )
    run_id = str(run["id"])
    store.update_research_run(run_id, {"status": "running"})
    universe_payload = {
        "universe": universe,
        "members": members,
        "sha256": snapshot_hash(members),
        "start_date": start_text,
        "end_date": end_text,
    }
    if not req.run_id:
        store.add_research_evidence(
            run_id=run_id,
            kind=UNIVERSE_SNAPSHOT_EVIDENCE,
            source="factor_universes",
            title=f"{universe['name']} 历史成分快照",
            uri=f"/factor-research?cross_section_run_id={run_id}",
            payload=universe_payload,
        )
    try:
        source = get_data_source(universe["market"])
    except Exception as exc:  # noqa: BLE001 - persist source initialization failures
        error = f"初始化 {universe['market']} 行情源失败: {exc}"
        store.update_research_run(run_id, {"status": "failed", "error": error})
        return {"ok": False, "error": error, "run_id": run_id, "failures": []}
    start = datetime.combine(req.start_date, time.min) if req.start_date else None
    end = datetime.combine(req.end_date, time.max) if req.end_date else None
    frames: dict[str, pd.DataFrame] = {}
    if req.run_id:
        for item in run.get("evidence") or []:
            if item.get("kind") != FACTOR_MARKET_SNAPSHOT_EVIDENCE:
                continue
            payload = item.get("payload") or {}
            symbol = payload.get("symbol")
            bars = payload.get("bars")
            columns = payload.get("columns")
            if (
                not isinstance(symbol, str)
                or not isinstance(bars, list)
                or not isinstance(columns, list)
                or payload.get("sha256") != snapshot_hash(bars)
            ):
                continue
            restored = pd.DataFrame(bars, columns=columns)
            if "datetime" in restored.columns:
                restored["datetime"] = pd.to_datetime(restored["datetime"], errors="coerce")
            restored.attrs["_source"] = payload.get("source", item.get("source", "snapshot"))
            frames[symbol] = restored
    failures: list[dict[str, Any]] = []
    symbols = sorted({str(member["symbol"]) for member in members})
    for symbol in (item for item in symbols if item not in frames):
        last_error = ""
        for attempt in range(1, req.retry_attempts + 1):
            try:
                frame = source.get_kline(
                    symbol,
                    req.interval,
                    start=start,
                    end=end,
                    limit=req.limit,
                )
                quality = assess_ohlcv(frame)
                if not quality.usable:
                    raise ValueError(quality.reason or quality.status)
                frames[symbol] = frame
                snapshot = dataframe_snapshot(frame)
                snapshot["symbol"] = symbol
                store.add_research_evidence(
                    run_id=run_id,
                    kind=FACTOR_MARKET_SNAPSHOT_EVIDENCE,
                    source=str(frame.attrs.get("_source", getattr(source, "name", "unknown"))),
                    title=f"{symbol} 横截面研究行情快照",
                    uri=f"/factor-research?cross_section_run_id={run_id}",
                    payload=snapshot,
                )
                break
            except Exception as exc:  # noqa: BLE001 - each symbol has bounded retries
                last_error = str(exc)
                if attempt == req.retry_attempts:
                    failures.append({"symbol": symbol, "attempts": attempt, "error": last_error})
    try:
        result = analyze_cross_sectional_factors(
            frames,
            members,
            CrossSectionConfig(
                market=universe["market"],
                factor_key=req.factor_key,
                horizon=req.horizon,
                quantiles=req.quantiles,
                min_assets=req.min_assets,
                periods_per_year=_periods_per_year(universe["market"], req.interval),
                transaction_cost_bps=req.transaction_cost_bps,
                participation_rate=req.participation_rate,
                portfolio_mode=req.portfolio_mode,
                neutralize_industry=req.neutralize_industry,
                neutralize_market_cap=req.neutralize_market_cap,
                neutralize_beta=req.neutralize_beta,
            ),
        )
    except (InsufficientCrossSectionData, ValueError) as exc:
        error = str(exc)
        store.update_research_run(
            run_id,
            {
                "status": "failed",
                "summary": {
                    CROSS_SECTION_MODULE: {
                        "ok": False,
                        "loaded_symbols": len(frames),
                        "failed_symbols": len(failures),
                    }
                },
                "error": error,
            },
        )
        return {
            "ok": False,
            "error": error,
            "run_id": run_id,
            "failures": failures,
        }
    result.update(
        {
            "ok": True,
            "run_id": run_id,
            "universe": universe,
            "transaction_cost_profile": (
                req.transaction_cost_profile.model_dump(mode="json")
                if req.transaction_cost_profile
                else None
            ),
            "loaded_symbols": len(frames),
            "failed_symbols": len(failures),
            "failures": failures,
        }
    )
    store.add_research_evidence(
        run_id=run_id,
        kind=CROSS_SECTION_RESULT_EVIDENCE,
        source=str(result["engine_version"]),
        title=f"{universe['name']} 横截面因子验证",
        uri=f"/factor-research?cross_section_run_id={run_id}",
        payload=result,
    )
    final_status = "partial" if failures else "succeeded"
    store.update_research_run(
        run_id,
        {
            "status": final_status,
            "summary": {
                CROSS_SECTION_MODULE: {
                    "ok": True,
                    **result["summary"],
                    "factor_key": req.factor_key,
                    "factor_status": result["factor"]["status"],
                    "universe_id": req.universe_id,
                    "loaded_symbols": len(frames),
                    "failed_symbols": len(failures),
                }
            },
            "error": "；".join(f"{item['symbol']}: {item['error']}" for item in failures) or None,
        },
    )
    return result


def cross_market_factor_status(factor_key: str, target_market: str | None = None) -> dict:
    markets = ["a_shares", "us_stocks", "crypto", "mt5"]
    if target_market is not None and target_market not in markets:
        return {"ok": False, "error": "不支持的目标市场", "factor_key": factor_key}
    rows: list[dict[str, Any]] = []
    for market in markets:
        market_runs = store.list_research_runs_page(
            limit=1,
            market=market,
            module=CROSS_SECTION_MODULE,
            cross_section_factor_key=factor_key,
        )["items"]
        latest = market_runs[0] if market_runs else None
        summary = (latest.get("summary") or {}).get(CROSS_SECTION_MODULE, {}) if latest else {}
        factor_status = summary.get("factor_status")
        thresholds = summary.get("validation_thresholds") or MARKET_VALIDATION_THRESHOLDS[market]
        effective_dates = int(summary.get("effective_dates") or summary.get("dates") or 0)
        minimum_valid_assets = int(summary.get("minimum_valid_assets") or 0)
        passed = bool(
            latest
            and latest.get("status") in {"succeeded", "partial"}
            and factor_status == "usable"
            and effective_dates >= int(thresholds["minimum_effective_dates"])
            and minimum_valid_assets >= int(thresholds["minimum_valid_assets"])
        )
        rows.append(
            {
                "market": market,
                "state": "passed" if passed else "failed" if latest else "missing",
                "run_id": latest.get("id") if latest else None,
                "run_status": latest.get("status") if latest else None,
                "factor_status": factor_status,
                "dates": summary.get("dates"),
                "effective_dates": effective_dates or None,
                "minimum_valid_assets": minimum_valid_assets or None,
                "validation_thresholds": thresholds,
                "rank_ic_mean": summary.get("rank_ic_mean"),
                "coverage": summary.get("coverage"),
                "updated_at": latest.get("updated_at") if latest else None,
            }
        )
    target_row = next((row for row in rows if row["market"] == target_market), None)
    validated = bool(target_row and target_row["state"] == "passed")
    if target_market is None:
        validation_status = "target_market_required"
        rule = "必须指定目标市场；其他市场仅作为迁移与稳健性证据，不阻断目标市场结论"
    else:
        validation_status = "passed" if validated else "insufficient_evidence"
        thresholds = (
            target_row.get("validation_thresholds")
            if target_row
            else MARKET_VALIDATION_THRESHOLDS[target_market]
        )
        rule = (
            f"目标市场 {target_market} 的最新横截面结果必须为 usable，"
            f"有效日期至少 {thresholds['minimum_effective_dates']}，"
            f"每日有效标的至少 {thresholds['minimum_valid_assets']}；其他市场只作迁移证据"
        )
    return {
        "ok": True,
        "factor_key": factor_key,
        "target_market": target_market,
        "trading_validation_status": validation_status,
        "trading_validation_passed": validated,
        "required_markets": [target_market] if target_market else [],
        "transfer_markets": [market for market in markets if market != target_market],
        "rows": rows,
        "rule": rule,
    }


def _saved_factor_result(run: dict) -> dict | None:
    detail = store.get_research_run(str(run["id"]))
    if detail is None:
        return None
    evidence = next(
        (
            item
            for item in reversed(detail.get("evidence") or [])
            if item.get("kind") == FACTOR_RESULT_EVIDENCE
        ),
        None,
    )
    payload = evidence.get("payload") if evidence else None
    return payload if isinstance(payload, dict) else None


def factor_status_matrix(factor_key: str) -> dict:
    """统一输出窗口、横截面和四市场门禁状态及其原始运行引用。"""
    window_rows: list[dict] = []
    factor_runs = store.list_research_runs_page(
        limit=200, module=FACTOR_RESEARCH_MODULE, archived=False
    )["items"]
    for run in factor_runs:
        result = _saved_factor_result(run)
        factor = next(
            (item for item in (result or {}).get("factors", []) if item.get("key") == factor_key),
            None,
        )
        if factor is None:
            continue
        windows = factor.get("windows") if isinstance(factor.get("windows"), list) else []
        window_rows = [
            {
                "dimension": "window",
                "key": str(item.get("fold")),
                "label": f"窗口 {item.get('fold')}",
                "state": "passed" if item.get("status") == "pass" else "failed",
                "rule": "训练样本至少 40、验证样本至少 20、方向调整后验证 IC >= 0.03 且命中率 >= 0.5",
                "evidence": item,
                "run_id": run["id"],
                "updated_at": run["updated_at"],
            }
            for item in windows
        ]
        if window_rows:
            break

    market_status = cross_market_factor_status(factor_key)
    cross_symbol_rows = [
        {
            "dimension": "cross_symbol",
            "key": row["market"],
            "label": f"{row['market']} 横截面",
            "state": row["state"],
            "rule": ("最新横截面因子状态为 usable，且有效日期和每日标的数达到该市场门槛"),
            "evidence": {
                "factor_status": row["factor_status"],
                "dates": row["dates"],
                "minimum_valid_assets": row["minimum_valid_assets"],
                "rank_ic_mean": row["rank_ic_mean"],
                "coverage": row["coverage"],
            },
            "run_id": row["run_id"],
            "updated_at": row["updated_at"],
        }
        for row in market_status["rows"]
    ]
    market_rows = [
        {
            "dimension": "market",
            "key": row["market"],
            "label": row["market"],
            "state": row["state"],
            "rule": market_status["rule"],
            "evidence": {"run_id": row["run_id"], "run_status": row["run_status"]},
            "run_id": row["run_id"],
            "updated_at": row["updated_at"],
        }
        for row in market_status["rows"]
    ]
    rows = [*window_rows, *cross_symbol_rows, *market_rows]
    return {
        "ok": True,
        "factor_key": factor_key,
        "dimensions": ["window", "cross_symbol", "market"],
        "rows": rows,
        "counts": {
            state: sum(item["state"] == state for item in rows)
            for state in ("passed", "failed", "missing")
        },
    }


def factor_research_attention(*, stale_hours: float = 24.0, limit: int = 100) -> dict:
    """列出首页需要复验、已失效和数据过期的最新单标的因子研究。"""
    now = datetime.now(UTC).timestamp()
    latest: dict[tuple[str, str, str], dict] = {}
    for run in store.list_research_runs_page(
        limit=500, module=FACTOR_RESEARCH_MODULE, archived=False
    )["items"]:
        key = (run["market"], run["symbol"], run["timeframe"])
        latest.setdefault(key, run)
    items: list[dict] = []
    for run in latest.values():
        result = _saved_factor_result(run)
        if result is None:
            continue
        factors = result.get("factors") if isinstance(result.get("factors"), list) else []
        rejected = [item.get("key") for item in factors if item.get("status") == "reject"]
        watch = [item.get("key") for item in factors if item.get("status") == "watch"]
        inconsistent = [
            item.get("key") for item in factors if item.get("multi_window_consistent") is False
        ]
        age_hours = max(0.0, (now - float(run["updated_at"])) / 3600)
        states: list[str] = []
        if watch or inconsistent:
            states.append("needs_revalidation")
        if rejected:
            states.append("invalidated")
        if age_hours >= stale_hours:
            states.append("data_stale")
        if not states:
            continue
        items.append(
            {
                "run_id": run["id"],
                "symbol": run["symbol"],
                "market": run["market"],
                "timeframe": run["timeframe"],
                "states": states,
                "updated_at": run["updated_at"],
                "age_hours": round(age_hours, 4),
                "evidence": {
                    "watch_factors": watch,
                    "inconsistent_factors": inconsistent,
                    "rejected_factors": rejected,
                },
            }
        )
    items.sort(key=lambda item: (len(item["states"]), item["updated_at"]), reverse=True)
    items = items[:limit]
    return {
        "ok": True,
        "stale_hours": stale_hours,
        "rules": {
            "needs_revalidation": "存在 watch 状态或多窗口一致性失败的因子",
            "invalidated": "存在 reject 状态因子",
            "data_stale": f"研究更新时间距当前至少 {stale_hours:g} 小时",
        },
        "counts": {
            state: sum(state in item["states"] for item in items)
            for state in ("needs_revalidation", "invalidated", "data_stale")
        },
        "items": items,
    }


def get_cross_sectional_research_run(run_id: str) -> dict | None:
    run = store.get_research_run(run_id)
    if run is None or CROSS_SECTION_MODULE not in run.get("modules", []):
        return None
    evidence = run.get("evidence") or []
    result_evidence = next(
        (item for item in reversed(evidence) if item.get("kind") == CROSS_SECTION_RESULT_EVIDENCE),
        None,
    )
    universe_evidence = next(
        (item for item in reversed(evidence) if item.get("kind") == UNIVERSE_SNAPSHOT_EVIDENCE),
        None,
    )
    market_snapshots = [
        item for item in evidence if item.get("kind") == FACTOR_MARKET_SNAPSHOT_EVIDENCE
    ]
    run_summary = {key: value for key, value in run.items() if key != "evidence"}
    return {
        "ok": True,
        "run": run_summary,
        "result": result_evidence.get("payload") if result_evidence else None,
        "universe_snapshot": universe_evidence.get("payload") if universe_evidence else None,
        "market_snapshots": market_snapshots,
    }


def run_factor_research(req: FactorResearchRequest, *, capture_snapshot: bool = False) -> dict:
    try:
        source = get_data_source(req.market)
        start = datetime.combine(req.start_date, time.min) if req.start_date else None
        end = datetime.combine(req.end_date, time.max) if req.end_date else None
        frame = source.get_kline(
            req.symbol,
            req.interval,
            start=start,
            end=end,
            limit=req.limit,
        )
    except Exception as exc:  # noqa: BLE001 - adapters may raise third-party transport errors
        return {"ok": False, "error": f"获取 K 线失败: {exc}"}
    if req.start_date or req.end_date:
        if "datetime" not in frame.columns:
            return {"ok": False, "error": "所选数据源未返回 datetime，无法执行日期区间研究"}
        timestamps = pd.to_datetime(frame["datetime"], errors="coerce", utc=True).dt.tz_convert(
            None
        )
        if not timestamps.notna().any():
            return {"ok": False, "error": "所选数据源没有可用 datetime，无法执行日期区间研究"}
        attributes = dict(frame.attrs)
        if start is not None:
            frame = frame.loc[timestamps.ge(start)]
            timestamps = timestamps.loc[frame.index]
        if end is not None:
            frame = frame.loc[timestamps.le(end)]
        frame = frame.copy()
        frame.attrs.update(attributes)
    quality = assess_ohlcv(frame)
    if not quality.usable:
        # 把 reason + status 暴露给上层调用方以便排查空数据
        return {
            "ok": False,
            "error": f"K线质量不合格: {quality.reason or quality.status}",
            "quality": quality.to_dict(),
            "diagnostic": {
                "market": req.market,
                "symbol": req.symbol,
                "interval": req.interval,
                "limit": req.limit,
                "start_date": req.start_date.isoformat() if req.start_date else None,
                "end_date": req.end_date.isoformat() if req.end_date else None,
                "source": getattr(source, "name", "unknown"),
                "rows_raw": int(len(frame)) if frame is not None else 0,
            },
        }
    try:
        result = analyze_factors(
            frame,
            ResearchConfig(
                horizon=req.horizon,
                periods_per_year=_periods_per_year(req.market, req.interval),
                transaction_cost_bps=req.transaction_cost_bps,
                walk_forward_mode=req.walk_forward_mode,
                walk_forward_folds=req.walk_forward_folds,
                availability_lag=req.availability_lag,
            ),
        )
    except InsufficientFactorData as exc:
        return {"ok": False, "error": str(exc), "quality": quality.to_dict()}
    response = {
        "ok": True,
        "symbol": req.symbol,
        "market": req.market,
        "interval": req.interval,
        "requested_period": {
            "start_date": req.start_date.isoformat() if req.start_date else None,
            "end_date": req.end_date.isoformat() if req.end_date else None,
        },
        "source": frame.attrs.get("_source", getattr(source, "name", "unknown")),
        "quality": quality.to_dict(),
        "transaction_cost_profile": (
            req.transaction_cost_profile.model_dump(mode="json")
            if req.transaction_cost_profile
            else None
        ),
        **result,
    }
    if capture_snapshot:
        snapshot = dataframe_snapshot(frame)
        snapshot["data_fingerprint"] = result["summary"]["data_fingerprint"]
        response["_market_snapshot"] = snapshot
    return response


def _request_payload(req: FactorResearchRequest | FactorAiReviewRequest) -> dict[str, Any]:
    return req.model_dump(
        mode="json",
        exclude={"review_focus", "run_id"},
        exclude_none=True,
    )


def _factor_summary(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "因子研究失败")}
    summary = result["summary"]
    signal = result["current_signal"]
    return {
        "ok": True,
        "source": result.get("source"),
        "rows": summary.get("rows"),
        "test_rows": summary.get("test_rows"),
        "usable_factors": summary.get("usable_factors"),
        "selected_factors": summary.get("selected_factors", []),
        "exploratory_candidates": summary.get(
            "exploratory_candidates", summary.get("selected_factors", [])
        ),
        "multifactor_constructed": summary.get("multifactor_constructed"),
        "best_factor": summary.get("best_factor"),
        "best_method": summary.get("best_method"),
        "engine_version": summary.get("engine_version"),
        "factor_formula_version": summary.get("factor_formula_version"),
        "data_fingerprint": summary.get("data_fingerprint"),
        "thresholds": summary.get("thresholds", {}),
        "walk_forward_mode": summary.get("walk_forward_mode"),
        "walk_forward_folds": summary.get("walk_forward_folds"),
        "signal_level": signal.get("level"),
        "drawdown": signal.get("drawdown"),
    }


def _create_factor_run(req: FactorResearchRequest) -> dict:
    run = store.create_research_run(
        symbol=req.symbol,
        market=req.market,
        timeframe=req.interval,
        modules=[FACTOR_RESEARCH_MODULE],
        input_data={FACTOR_RESEARCH_MODULE: _request_payload(req)},
    )
    return store.update_research_run(run["id"], {"status": "running"}) or run


def run_and_save_factor_research(req: FactorResearchRequest) -> dict:
    """Run deterministic research and persist its complete server-side snapshot."""
    run: dict[str, Any] | None = None
    persistence_error: str | None = None
    try:
        run = _create_factor_run(req)
    except Exception as exc:  # noqa: BLE001 - research remains useful if storage is unavailable
        persistence_error = str(exc)
        logger.exception("创建因子研究记录失败")
        try:
            from apps.api.domains.incidents import repository as incident_repository

            incident_repository.observe_research_failure(
                kind="research_persistence",
                fingerprint=f"{req.market}:{req.symbol}:{req.interval}",
                error=persistence_error,
                context={"symbol": req.symbol, "market": req.market, "interval": req.interval},
            )
        except Exception:  # noqa: BLE001 - original research request must still proceed
            logger.exception("记录因子研究持久化故障失败")

    result = run_factor_research(req, capture_snapshot=True)
    market_snapshot = result.pop("_market_snapshot", None)
    if run is None:
        return {
            **result,
            "saved": False,
            "persistence_error": persistence_error or "研究记录存储不可用",
        }

    run_id = str(run["id"])
    if result.get("ok"):
        if market_snapshot:
            store.add_research_evidence(
                run_id=run_id,
                kind=FACTOR_MARKET_SNAPSHOT_EVIDENCE,
                source=str(result.get("source") or "factor_engine"),
                title="因子研究锁定行情快照",
                uri=f"/factor-research?run_id={run_id}",
                payload=market_snapshot,
            )
        store.add_research_evidence(
            run_id=run_id,
            kind=FACTOR_RESULT_EVIDENCE,
            source=str(result.get("source") or "factor_engine"),
            title="因子样本外验证",
            uri=f"/factor-research?run_id={run_id}",
            payload=result,
        )
        updated = store.update_research_run(
            run_id,
            {
                "status": "succeeded",
                "summary": {FACTOR_RESEARCH_MODULE: _factor_summary(result)},
                "error": None,
            },
        )
    else:
        updated = store.update_research_run(
            run_id,
            {
                "status": "failed",
                "summary": {FACTOR_RESEARCH_MODULE: _factor_summary(result)},
                "error": result.get("error"),
            },
        )
    return {
        **result,
        "run_id": run_id,
        "saved": True,
        "saved_at": (updated or run).get("updated_at"),
    }


def list_factor_research_runs(
    *,
    symbol: str | None = None,
    market: str | None = None,
    interval: str | None = None,
    status: str | None = None,
    favorite: bool | None = None,
    archived: bool = False,
    tag: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    research_limit: int | None = None,
    horizon: int | None = None,
    transaction_cost_bps: float | None = None,
    walk_forward_mode: str | None = None,
    walk_forward_folds: int | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict:
    normalized = symbol.strip().upper() if symbol else None
    if created_from and created_to and created_from > created_to:
        raise ValueError("created_from 不能晚于 created_to")
    page = store.list_research_runs_page(
        limit=limit,
        symbol=normalized,
        module=FACTOR_RESEARCH_MODULE,
        market=market,
        timeframe=interval,
        cursor=cursor,
        status=status,
        favorite=favorite,
        archived=archived,
        tag=tag,
        created_from=(
            datetime.combine(created_from, time.min).timestamp() if created_from else None
        ),
        created_to=(
            datetime.combine(created_to + timedelta(days=1), time.min).timestamp()
            if created_to
            else None
        ),
        factor_limit=research_limit,
        factor_horizon=horizon,
        factor_transaction_cost_bps=transaction_cost_bps,
        factor_walk_forward_mode=walk_forward_mode,
        factor_walk_forward_folds=walk_forward_folds,
    )
    return {
        "ok": True,
        "runs": page["items"],
        "total": page["total"],
        "next_cursor": page["next_cursor"],
    }


def get_factor_research_run(run_id: str) -> dict | None:
    run = store.get_research_run(run_id)
    if run is None or FACTOR_RESEARCH_MODULE not in run.get("modules", []):
        return None
    evidence = run.get("evidence", [])
    statistical = next(
        (item for item in reversed(evidence) if item.get("kind") == FACTOR_RESULT_EVIDENCE),
        None,
    )
    ai_evidence = next(
        (item for item in reversed(evidence) if item.get("kind") == FACTOR_AI_EVIDENCE),
        None,
    )
    run_summary = {key: value for key, value in run.items() if key != "evidence"}
    result = dict(statistical["payload"]) if statistical else None
    if result is not None:
        engine_version = result.get("summary", {}).get("engine_version")
        result["compatibility"] = {
            "current_engine_version": CURRENT_FACTOR_ENGINE_VERSION,
            "record_engine_version": engine_version,
            "legacy_engine_record": engine_version != CURRENT_FACTOR_ENGINE_VERSION,
            "policy": (
                "historical_result_preserved_read_only"
                if engine_version != CURRENT_FACTOR_ENGINE_VERSION
                else "current_engine"
            ),
        }
        result.update({"run_id": run_id, "saved": True, "saved_at": run["updated_at"]})
    ai_review = dict(ai_evidence["payload"]) if ai_evidence else None
    if ai_review is not None:
        ai_review.update({"run_id": run_id, "saved": True})
    return {"ok": True, "run": run_summary, "result": result, "ai_review": ai_review}


def _factor_run_for_review(req: FactorAiReviewRequest) -> tuple[dict[str, Any] | None, str | None]:
    if not req.run_id:
        return run_factor_research(FactorResearchRequest(**_request_payload(req))), None
    detail = get_factor_research_run(req.run_id)
    if detail is None or detail.get("result") is None:
        return None, "因子研究记录不存在或没有可复核的统计结果"
    expected = (detail["run"].get("input") or {}).get(FACTOR_RESEARCH_MODULE, {})
    if expected != _request_payload(req):
        return None, "AI 复核参数与已保存的因子研究记录不一致"
    return detail["result"], None


def _save_ai_outcome(run_id: str, response: dict[str, Any]) -> None:
    run = store.get_research_run(run_id)
    if run is None:
        return
    summary = dict(run.get("summary") or {})
    if response.get("ok"):
        review = response.get("review") or {}
        meta = response.get("meta") or {}
        store.add_research_evidence(
            run_id=run_id,
            kind=FACTOR_AI_EVIDENCE,
            source=str(meta.get("model") or meta.get("provider") or "configured_llm"),
            title="AI 科研复核",
            uri=f"/factor-research?run_id={run_id}",
            payload=response,
        )
        summary[FACTOR_AI_EVIDENCE] = {
            "ok": True,
            "verdict": review.get("verdict"),
            "confidence": review.get("confidence"),
            "model": meta.get("model"),
            "input_fingerprint": meta.get("input_fingerprint"),
            "statistical_conclusions_locked": meta.get("statistical_conclusions_locked"),
        }
        store.update_research_run(
            run_id, {"status": "succeeded", "summary": summary, "error": None}
        )
        return
    summary[FACTOR_AI_EVIDENCE] = {"ok": False, "error": response.get("error")}
    store.update_research_run(
        run_id,
        {"status": "partial", "summary": summary, "error": response.get("error")},
    )


def review_factor_research(req: FactorAiReviewRequest) -> dict:
    """Review a saved server snapshot, or rebuild one for backward-compatible callers."""
    result, context_error = _factor_run_for_review(req)
    if context_error:
        return {"ok": False, "error": context_error, "run_id": req.run_id}
    if result is None or not result.get("ok"):
        return result or {"ok": False, "error": "因子研究结果不可用"}
    try:
        response = run_ai_review(result, focus=req.review_focus)
    except Exception as exc:  # noqa: BLE001 - normalize provider/configuration failures for the UI
        error_text = str(exc).strip()
        if "timed out" in error_text.lower() or "timeout" in type(exc).__name__.lower():
            response = {
                "ok": False,
                "error": (
                    f"AI 高级推理超过 {AI_REVIEW_TIMEOUT_SECONDS} 秒，请检查模型网关后重试；"
                    "本次统计结论未受影响"
                ),
            }
        else:
            response = {"ok": False, "error": f"AI 科研复核失败: {exc}"}
    if req.run_id:
        _save_ai_outcome(req.run_id, response)
        response = {**response, "run_id": req.run_id, "saved": True}
    return response
