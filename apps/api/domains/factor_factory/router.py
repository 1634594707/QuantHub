from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from .alpha_mining import alpha_expression_catalog
from .schemas import FactorFactoryObserveRequest, FactorFactoryStartRequest
from .service import (
    get_factor_factory_run,
    list_factor_factory_archive,
    list_factor_factory_runs,
    observe_factor_factory,
    start_factor_factory,
)

router = APIRouter(prefix="/factor-factory", tags=["factor-factory"])


@router.get("/alpha-dsl")
def get_alpha_dsl() -> dict:
    return {"ok": True, **alpha_expression_catalog()}


@router.post("/runs", status_code=201)
def create_run(req: FactorFactoryStartRequest) -> dict:
    try:
        return start_factor_factory(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/runs")
def list_runs(
    status: Literal[
        "discovering",
        "no_qualified_factor",
        "no_research_passed_factor",
        "paper_observing",
        "paper_rejected",
        "trading_validated",
        "degraded",
        "failed",
    ]
    | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    return list_factor_factory_runs(status=status, limit=limit)


@router.get("/archive")
def list_archive(
    lifecycle_state: Literal[
        "draft",
        "exploratory",
        "research_passed",
        "trading_validated",
        "degraded",
        "retired",
    ]
    | None = None,
    eligible_only: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    return list_factor_factory_archive(
        lifecycle_state=lifecycle_state,
        eligible_only=eligible_only,
        limit=limit,
    )


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    result = get_factor_factory_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="自动因子运行不存在")
    return result


@router.post("/runs/{run_id}/observe")
def observe_run(run_id: str, req: FactorFactoryObserveRequest) -> dict:
    try:
        return observe_factor_factory(run_id, force_refresh=req.force_refresh)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
