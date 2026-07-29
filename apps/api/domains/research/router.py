from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from apps.api import store
from apps.api.domains.instrument import service as instrument_service

from . import service
from .schemas import (
    ResearchCompareRequest,
    ResearchEvidenceCreate,
    ResearchRunCreate,
    ResearchRunUpdate,
)

router = APIRouter(prefix="/research", tags=["research"])


@router.post("/compare")
def compare_runs(req: ResearchCompareRequest) -> dict:
    runs = []
    for run_id in req.run_ids:
        run = store.get_research_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"研究运行不存在: {run_id}")
        runs.append(run)
    return service.compare_runs(runs)


@router.post("/runs", status_code=201)
def create_run(req: ResearchRunCreate) -> dict:
    try:
        instrument = instrument_service.resolve_strict(req.symbol, req.market)
    except instrument_service.InstrumentResolutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    run = store.create_research_run(
        symbol=instrument.code,
        market=instrument.market,
        timeframe=req.timeframe,
        modules=req.modules,
        input_data=req.input,
        instrument_id=instrument.instrument_id,
    )
    return {"ok": True, "run": run}


@router.get("/runs")
def list_runs(
    symbol: str | None = None,
    status: str | None = None,
    favorite: bool | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = None,
) -> dict:
    normalized = symbol.strip().upper() if symbol else None
    try:
        page = store.list_research_runs_page(
            limit=limit,
            symbol=normalized,
            status=status,
            favorite=favorite,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "ok": True,
        "count": len(page["items"]),
        "total": page["total"],
        "next_cursor": page["next_cursor"],
        "runs": page["items"],
    }


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = store.get_research_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"研究运行不存在: {run_id}")
    return {"ok": True, "run": run}


@router.get("/runs/{run_id}/export")
def export_run(run_id: str) -> dict:
    """Return a portable research snapshot with all recorded evidence."""
    run = store.get_research_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"研究运行不存在: {run_id}")
    return {
        "ok": True,
        "export_version": "1.0",
        "exported_at": run["updated_at"],
        "run": run,
    }


@router.get("/runs/{run_id}/verify")
def verify_run(run_id: str) -> dict:
    run = store.get_research_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"研究运行不存在: {run_id}")
    return service.verify_run_snapshots(run)


@router.patch("/runs/{run_id}")
def update_run(run_id: str, req: ResearchRunUpdate) -> dict:
    patch = req.model_dump(exclude_unset=True)
    run = store.update_research_run(run_id, patch)
    if run is None:
        raise HTTPException(status_code=404, detail=f"研究运行不存在: {run_id}")
    return {"ok": True, "run": run}


@router.post("/runs/{run_id}/evidence", status_code=201)
def add_evidence(run_id: str, req: ResearchEvidenceCreate) -> dict:
    evidence = store.add_research_evidence(
        run_id=run_id,
        kind=req.kind,
        source=req.source,
        title=req.title.strip(),
        uri=req.uri,
        payload=req.payload,
    )
    if evidence is None:
        raise HTTPException(status_code=404, detail=f"研究运行不存在: {run_id}")
    return {"ok": True, "evidence": evidence}
