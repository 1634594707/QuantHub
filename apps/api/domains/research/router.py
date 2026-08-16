from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request

from apps.api import store
from apps.api.domains.instrument import service as instrument_service
from packages.financial_data import UserResearchPreference

from . import service
from .schemas import (
    ResearchCompareRequest,
    ResearchEvidenceCreate,
    ResearchRunCreate,
    ResearchRunsBatchUpdate,
    ResearchRunUpdate,
    UserResearchPreferenceUpdate,
)

router = APIRouter(prefix="/research", tags=["research"])


def _owner_id(request: Request) -> str:
    principal = getattr(request.state, "principal", None) or {}
    return str(principal.get("id") or "local-user")


def _owned_run(run_id: str, request: Request) -> dict:
    run = store.get_research_run(run_id)
    if run is None or run.get("owner_id") != _owner_id(request):
        raise HTTPException(status_code=404, detail=f"研究运行不存在: {run_id}")
    return run


@router.get("/preferences/me")
def get_my_preference(request: Request) -> dict:
    user_id = _owner_id(request)
    payload = store.get_user_research_preference(user_id)
    if payload is None:
        payload = UserResearchPreference(
            user_id=user_id,
            updated_at=datetime.now(UTC),
        ).model_dump(mode="json")
    return {"ok": True, "preference": payload}


@router.put("/preferences/me")
def update_my_preference(req: UserResearchPreferenceUpdate, request: Request) -> dict:
    preference = UserResearchPreference(
        user_id=_owner_id(request),
        updated_at=datetime.now(UTC),
        **req.model_dump(),
    ).model_dump(mode="json")
    return {
        "ok": True,
        "preference": store.save_user_research_preference(_owner_id(request), preference),
    }


@router.post("/compare")
def compare_runs(req: ResearchCompareRequest, request: Request) -> dict:
    runs = []
    for run_id in req.run_ids:
        runs.append(_owned_run(run_id, request))
    return service.compare_runs(runs)


@router.post("/runs", status_code=201)
def create_run(req: ResearchRunCreate, request: Request) -> dict:
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
        owner_id=_owner_id(request),
    )
    return {"ok": True, "run": run}


@router.get("/runs")
def list_runs(
    request: Request,
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
            owner_id=_owner_id(request),
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
def get_run(run_id: str, request: Request) -> dict:
    run = _owned_run(run_id, request)
    return {"ok": True, "run": run}


@router.patch("/runs/batch")
def update_runs_batch(req: ResearchRunsBatchUpdate, request: Request) -> dict:
    patch = req.model_dump(exclude_unset=True, exclude={"run_ids"})
    existing = {
        run_id
        for run_id in req.run_ids
        if (run := store.get_research_run(run_id)) is not None
        and run.get("owner_id") == _owner_id(request)
    }
    if len(existing) != len(req.run_ids):
        missing = [run_id for run_id in req.run_ids if run_id not in existing]
        raise HTTPException(status_code=404, detail=f"研究运行不存在: {', '.join(missing)}")
    runs = store.update_research_runs(req.run_ids, patch)
    return {"ok": True, "count": len(runs), "runs": runs}


@router.get("/runs/{run_id}/export")
def export_run(run_id: str, request: Request) -> dict:
    """Return a portable research snapshot with all recorded evidence."""
    run = _owned_run(run_id, request)
    return {
        "ok": True,
        "export_version": "2.0",
        "exported_at": run["updated_at"],
        **service.build_export_manifest(run),
        "run": run,
    }


@router.get("/runs/{run_id}/verify")
def verify_run(run_id: str, request: Request) -> dict:
    run = _owned_run(run_id, request)
    return service.verify_run_snapshots(run)


@router.patch("/runs/{run_id}")
def update_run(run_id: str, req: ResearchRunUpdate, request: Request) -> dict:
    _owned_run(run_id, request)
    patch = req.model_dump(exclude_unset=True)
    run = store.update_research_run(run_id, patch)
    if run is None:
        raise HTTPException(status_code=404, detail=f"研究运行不存在: {run_id}")
    return {"ok": True, "run": run}


@router.post("/runs/{run_id}/evidence", status_code=201)
def add_evidence(run_id: str, req: ResearchEvidenceCreate, request: Request) -> dict:
    _owned_run(run_id, request)
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
