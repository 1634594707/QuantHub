from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from . import service
from .schemas import DataSourceIncidentCheck, DataSourceRecoveryAcknowledge

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("")
def list_incidents(
    limit: int = Query(default=100, ge=1, le=500), cursor: str | None = None
) -> dict:
    try:
        return service.list_incidents(limit=limit, cursor=cursor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/data-sources/check")
def check_data_source_incident(req: DataSourceIncidentCheck) -> dict:
    return service.check_incident_data_source(req)


@router.post("/data-sources/{incident_id}/acknowledge")
def acknowledge_data_source_recovery(
    incident_id: str,
    req: DataSourceRecoveryAcknowledge,
) -> dict:
    return service.acknowledge_data_source_recovery(incident_id, req.resolution)


@router.get("/data-sources/history")
def get_data_source_history(limit: int = Query(default=200, ge=1, le=1000)) -> dict:
    return service.data_source_history(limit=limit)
