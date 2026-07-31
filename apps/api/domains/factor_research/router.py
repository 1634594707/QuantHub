from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from .schemas import (
    CrossSectionResearchRequest,
    FactorAiReviewRequest,
    FactorResearchRequest,
    FactorUniverseCreate,
    FactorUniverseMemberUpsert,
)
from .service import (
    create_factor_universe,
    cross_market_factor_status,
    factor_research_attention,
    factor_status_matrix,
    get_cross_sectional_research_run,
    get_factor_research_run,
    list_factor_research_runs,
    list_factor_universe_members,
    list_factor_universes,
    review_factor_research,
    run_and_save_factor_research,
    run_cross_sectional_research,
    upsert_factor_universe_member,
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


@router.post("/universes")
def create_universe(req: FactorUniverseCreate) -> dict:
    return create_factor_universe(req)


@router.get("/universes")
def list_universes(
    market: Literal["a_shares", "us_stocks", "crypto", "mt5"] | None = None,
) -> dict:
    return list_factor_universes(market=market)


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
def get_cross_market_status(factor_key: str) -> dict:
    return cross_market_factor_status(factor_key)


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
