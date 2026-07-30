from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .schemas import FactorAiReviewRequest, FactorResearchRequest
from .service import (
    get_factor_research_run,
    list_factor_research_runs,
    review_factor_research,
    run_and_save_factor_research,
)

router = APIRouter(prefix="/factor-research", tags=["factor-research"])


@router.post("/analyze")
def analyze(req: FactorResearchRequest) -> dict:
    return run_and_save_factor_research(req)


@router.post("/ai-review")
def ai_review(req: FactorAiReviewRequest) -> dict:
    """Use the configured LLM to review, but never overwrite, statistical conclusions."""
    return review_factor_research(req)


@router.get("/runs")
def list_runs(
    symbol: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
) -> dict:
    try:
        return list_factor_research_runs(symbol=symbol, limit=limit, cursor=cursor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    result = get_factor_research_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"因子研究记录不存在: {run_id}")
    return result
