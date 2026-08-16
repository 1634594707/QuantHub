from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

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
    FactorLineageRequest,
    FactorPortfolioConstraintRequest,
    FactorRedundancyRequest,
    FactorResearchPlanCreate,
    FactorResearchRequest,
    FactorRetirementImpactRequest,
    FactorRobustnessRequest,
    FactorSimulationAttributionRequest,
    FactorSimulationValidationRequest,
    FactorUniverseBatchRequest,
    FactorUniverseCreate,
    FactorUniverseMemberUpsert,
    FactorUniverseRollbackRequest,
    TokenFormulaImportRequest,
)
from .service import (
    analyze_factor_drift,
    analyze_factor_redundancy,
    analyze_factor_robustness,
    append_factor_experiment_event,
    apply_factor_universe_batch,
    attribute_factor_simulation_gap,
    build_factor_candidate_inbox,
    compare_factor_discovery_efficiency,
    create_factor_experiment_record,
    create_factor_research_plan_record,
    create_factor_universe,
    cross_market_factor_status,
    factor_ai_proposal_context,
    factor_plan_multiple_testing,
    factor_research_attention,
    factor_status_matrix,
    factor_universe_import_template,
    get_cross_sectional_research_run,
    get_factor_confirmation_set_opening,
    get_factor_experiment_record,
    get_factor_lifecycle,
    get_factor_lineage,
    get_factor_research_plan_record,
    get_factor_research_run,
    get_registered_factor_definition,
    import_token_formula_definitions,
    list_factor_ai_search_round_records,
    list_factor_experiment_records,
    list_factor_research_plan_records,
    list_factor_research_runs,
    list_factor_universe_members,
    list_factor_universes,
    list_registered_factor_definitions,
    open_factor_confirmation_set,
    preview_factor_retirement_impact,
    preview_factor_universe_batch,
    register_factor_definition,
    review_factor_research,
    rollback_factor_universe,
    run_and_save_factor_research,
    run_cross_sectional_research,
    seed_builtin_factor_definitions,
    transition_factor_lifecycle,
    upsert_factor_universe_member,
    validate_factor_ai_search_round,
    validate_factor_candidate_data,
    validate_factor_portfolio_constraints,
    validate_factor_simulation,
)

router = APIRouter(prefix="/factor-research", tags=["factor-research"])


@router.post("/analyze")
def analyze(req: FactorResearchRequest) -> dict:
    return run_and_save_factor_research(req)


@router.post("/ai-review")
def ai_review(req: FactorAiReviewRequest) -> dict:
    """Use the configured LLM to review, but never overwrite, statistical conclusions."""
    return review_factor_research(req)


@router.get("/attention")
def research_attention(
    stale_hours: float = Query(default=24.0, gt=0, le=24 * 365),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    return factor_research_attention(stale_hours=stale_hours, limit=limit)


@router.get("/status-matrix/{factor_key}")
def status_matrix(factor_key: str) -> dict:
    return factor_status_matrix(factor_key)


@router.post("/definitions")
def create_definition(req: FactorDefinitionCreate) -> dict:
    result = register_factor_definition(req)
    if not result["ok"]:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.post("/definitions/seed-builtins")
def seed_builtin_definitions() -> dict:
    return seed_builtin_factor_definitions()


@router.post("/definitions/import-token-formulas")
def import_token_definitions(req: TokenFormulaImportRequest) -> dict:
    result = import_token_formula_definitions(req)
    if not result["ok"]:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.get("/definitions")
def list_definitions(
    market: Literal["a_shares", "us_stocks", "crypto", "mt5"] | None = None,
    family: str | None = Query(default=None, min_length=1, max_length=80),
) -> dict:
    return list_registered_factor_definitions(market=market, family=family)


@router.get("/definitions/{factor_key}/{version}")
def get_definition(factor_key: str, version: str) -> dict:
    result = get_registered_factor_definition(factor_key, version)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/definitions/{factor_key}/{version}/lifecycle")
def factor_lifecycle(
    factor_key: str,
    version: str,
    target_market: Literal["a_shares", "us_stocks", "crypto", "mt5"] | None = None,
) -> dict:
    result = get_factor_lifecycle(factor_key, version, target_market)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/definitions/{factor_key}/{version}/lifecycle/transitions")
def transition_lifecycle(
    factor_key: str,
    version: str,
    req: FactorLifecycleTransitionRequest,
) -> dict:
    result = transition_factor_lifecycle(factor_key, version, req)
    if not result["ok"]:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.post("/candidate-validations")
def validate_candidate(req: FactorCandidateValidationRequest) -> dict:
    result = validate_factor_candidate_data(req)
    if not result["ok"]:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.post("/redundancy/analyze")
def analyze_redundancy(req: FactorRedundancyRequest) -> dict:
    result = analyze_factor_redundancy(req)
    if not result["ok"]:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.post("/robustness/analyze")
def analyze_robustness(req: FactorRobustnessRequest) -> dict:
    return analyze_factor_robustness(req)


@router.post("/portfolio-constraints/validate")
def validate_portfolio_constraints(req: FactorPortfolioConstraintRequest) -> dict:
    return validate_factor_portfolio_constraints(req)


@router.post("/candidates/inbox")
def candidate_inbox(req: FactorCandidateInboxRequest) -> dict:
    return build_factor_candidate_inbox(req)


@router.post("/retirement/impact-preview")
def retirement_impact_preview(req: FactorRetirementImpactRequest) -> dict:
    return preview_factor_retirement_impact(req)


@router.post("/lineage/{factor_key}/{version}")
def factor_lineage(factor_key: str, version: str, req: FactorLineageRequest) -> dict:
    result = get_factor_lineage(factor_key, version, req)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/monitoring/drift")
def monitor_drift(req: FactorDriftMonitoringRequest) -> dict:
    return analyze_factor_drift(req)


@router.post("/simulation/validate")
def validate_simulation(req: FactorSimulationValidationRequest) -> dict:
    return validate_factor_simulation(req)


@router.post("/simulation/attribute-gap")
def attribute_simulation_gap(req: FactorSimulationAttributionRequest) -> dict:
    return attribute_factor_simulation_gap(req)


@router.post("/efficiency/compare")
def compare_discovery_efficiency(req: FactorDiscoveryEfficiencyRequest) -> dict:
    return compare_factor_discovery_efficiency(req)


@router.post("/plans")
def create_research_plan(req: FactorResearchPlanCreate) -> dict:
    result = create_factor_research_plan_record(req)
    if not result["ok"]:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.get("/plans")
def list_research_plans(
    target_market: Literal["a_shares", "us_stocks", "crypto", "mt5"] | None = None,
) -> dict:
    return list_factor_research_plan_records(target_market)


@router.get("/plans/{plan_id}")
def get_research_plan(plan_id: str) -> dict:
    result = get_factor_research_plan_record(plan_id)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/plans/{plan_id}/confirmation-set/open")
def open_confirmation_set(plan_id: str, req: FactorConfirmationSetOpenRequest) -> dict:
    result = open_factor_confirmation_set(plan_id, req)
    if not result["ok"]:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.get("/plans/{plan_id}/confirmation-set")
def get_confirmation_set_opening(plan_id: str) -> dict:
    result = get_factor_confirmation_set_opening(plan_id)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/plans/{plan_id}/multiple-testing")
def get_plan_multiple_testing(plan_id: str) -> dict:
    result = factor_plan_multiple_testing(plan_id)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/plans/{plan_id}/ai-proposal-context")
def get_ai_proposal_context(plan_id: str) -> dict:
    result = factor_ai_proposal_context(plan_id)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/plans/{plan_id}/ai-search-rounds")
def create_ai_search_round(plan_id: str, req: FactorAiSearchRoundRequest) -> dict:
    result = validate_factor_ai_search_round(plan_id, req)
    if not result["ok"]:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.get("/plans/{plan_id}/ai-search-rounds")
def list_ai_search_rounds(plan_id: str) -> dict:
    result = list_factor_ai_search_round_records(plan_id)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/experiments")
def create_experiment(req: FactorExperimentCreate) -> dict:
    result = create_factor_experiment_record(req)
    if not result["ok"]:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.get("/experiments")
def list_experiments(
    research_plan_id: str | None = Query(default=None, min_length=1, max_length=80),
    source: Literal[
        "human", "ai", "template", "random_dsl", "symbolic_regression", "parameter_search"
    ]
    | None = None,
    status: Literal["draft", "queued", "running", "succeeded", "failed", "rejected", "cancelled"]
    | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    return list_factor_experiment_records(
        research_plan_id=research_plan_id,
        source=source,
        status=status,
        limit=limit,
    )


@router.get("/experiments/{experiment_id}")
def get_experiment(experiment_id: str) -> dict:
    result = get_factor_experiment_record(experiment_id)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/experiments/{experiment_id}/events")
def add_experiment_event(experiment_id: str, req: FactorExperimentEventCreate) -> dict:
    result = append_factor_experiment_event(experiment_id, req)
    if not result["ok"]:
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.post("/universes")
def create_universe(req: FactorUniverseCreate) -> dict:
    return create_factor_universe(req)


@router.get("/universes")
def list_universes(
    market: Literal["a_shares", "us_stocks", "crypto", "mt5"] | None = None,
) -> dict:
    return list_factor_universes(market=market)


@router.get("/universes/import-template")
def universe_import_template() -> dict:
    return factor_universe_import_template()


@router.post("/universes/{universe_id}/batch/preview")
def preview_universe_batch(universe_id: str, req: FactorUniverseBatchRequest) -> dict:
    result = preview_factor_universe_batch(universe_id, req)
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error"))
    return result


@router.post("/universes/{universe_id}/batch/apply")
def apply_universe_batch(universe_id: str, req: FactorUniverseBatchRequest) -> dict:
    result = apply_factor_universe_batch(universe_id, req)
    if not result.get("ok") and not result.get("batch"):
        raise HTTPException(status_code=422, detail=result.get("error"))
    return result


@router.post("/universes/{universe_id}/rollback")
def rollback_universe(universe_id: str, req: FactorUniverseRollbackRequest) -> dict:
    result = rollback_factor_universe(universe_id, req)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


@router.post("/universes/{universe_id}/members")
def upsert_universe_member(universe_id: str, req: FactorUniverseMemberUpsert) -> dict:
    return upsert_factor_universe_member(universe_id, req)


@router.get("/universes/{universe_id}/members")
def list_universe_members(universe_id: str, as_of: date | None = None) -> dict:
    return list_factor_universe_members(universe_id, as_of=as_of)


@router.post("/cross-sectional/analyze")
def analyze_cross_section(req: CrossSectionResearchRequest) -> dict:
    return run_cross_sectional_research(req)


@router.get("/cross-sectional/runs/{run_id}")
def get_cross_section_run(run_id: str) -> dict:
    result = get_cross_sectional_research_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"横截面因子研究记录不存在: {run_id}")
    return result


@router.get("/cross-sectional/status/{factor_key}")
def get_cross_market_status(
    factor_key: str,
    target_market: Literal["a_shares", "us_stocks", "crypto", "mt5"] | None = None,
) -> dict:
    return cross_market_factor_status(factor_key, target_market)


@router.get("/runs")
def list_runs(
    symbol: str | None = None,
    market: Literal["a_shares", "us_stocks", "crypto", "mt5"] | None = None,
    interval: str | None = None,
    status: Literal[
        "draft", "queued", "running", "succeeded", "partial", "failed", "cancelled", "timeout"
    ]
    | None = None,
    favorite: bool | None = None,
    archived: bool = False,
    tag: str | None = Query(default=None, min_length=1, max_length=40),
    created_from: date | None = None,
    created_to: date | None = None,
    research_limit: int | None = Query(default=None, ge=120, le=5_000),
    horizon: int | None = Query(default=None, ge=1, le=60),
    transaction_cost_bps: float | None = Query(default=None, ge=0, le=200),
    walk_forward_mode: Literal["expanding", "rolling"] | None = None,
    walk_forward_folds: int | None = Query(default=None, ge=1, le=10),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
) -> dict:
    try:
        return list_factor_research_runs(
            symbol=symbol,
            market=market,
            interval=interval,
            status=status,
            favorite=favorite,
            archived=archived,
            tag=tag,
            created_from=created_from,
            created_to=created_to,
            research_limit=research_limit,
            horizon=horizon,
            transaction_cost_bps=transaction_cost_bps,
            walk_forward_mode=walk_forward_mode,
            walk_forward_folds=walk_forward_folds,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    result = get_factor_research_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"因子研究记录不存在: {run_id}")
    return result
