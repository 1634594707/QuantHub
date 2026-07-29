"""自动化控制台路由：/automation/*。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from . import service
from .schemas import AutomationActionRequest, AutomationJobUpdate

router = APIRouter(prefix="/automation", tags=["automation"])


def _raise_service_error(exc: Exception) -> None:
    if isinstance(exc, service.AutomationNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, service.AutomationConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


@router.get("/status")
def get_status() -> dict:
    return service.status()


@router.get("/jobs")
def list_jobs() -> dict:
    return service.list_jobs()


@router.get("/jobs/{name}")
def get_job(name: str) -> dict:
    result = service.get_job(name)
    if not result.get("ok"):
        if result.get("jobs") == []:
            raise HTTPException(status_code=503, detail=result.get("error"))
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


@router.patch("/jobs/{name}")
def update_job(name: str, payload: AutomationJobUpdate) -> dict:
    try:
        job = service.update_job(
            name,
            enabled=payload.enabled,
            cron=payload.cron,
            actor=payload.actor,
        )
    except Exception as exc:
        _raise_service_error(exc)
    return {"ok": True, "job": job}


@router.post("/jobs/{name}/run")
def run_job(name: str, payload: AutomationActionRequest) -> dict:
    try:
        run = service.submit_run(name, actor=payload.actor)
    except Exception as exc:
        _raise_service_error(exc)
    return {"ok": True, "run": run}


@router.get("/runs")
def list_runs(
    job_name: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = None,
) -> dict:
    try:
        return service.list_runs(job_name=job_name, run_status=status, limit=limit, cursor=cursor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    try:
        run = service.get_run(run_id)
    except Exception as exc:
        _raise_service_error(exc)
    return {"ok": True, "run": run}


@router.post("/runs/{run_id}/retry")
def retry_run(run_id: str, payload: AutomationActionRequest) -> dict:
    try:
        run = service.retry_run(run_id, actor=payload.actor)
    except Exception as exc:
        _raise_service_error(exc)
    return {"ok": True, "run": run}


@router.post("/runs/{run_id}/acknowledge")
def acknowledge_run(run_id: str, payload: AutomationActionRequest) -> dict:
    try:
        run = service.acknowledge_run(run_id, actor=payload.actor)
    except Exception as exc:
        _raise_service_error(exc)
    return {"ok": True, "run": run}


@router.get("/alerts")
def list_alerts(limit: int = Query(default=100, ge=1, le=500)) -> dict:
    return service.alerts(limit=limit)


@router.get("/audit")
def list_audit(
    limit: int = Query(default=100, ge=1, le=500), cursor: str | None = None
) -> dict:
    try:
        return service.audit_logs(limit=limit, cursor=cursor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
