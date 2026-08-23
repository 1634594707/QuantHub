from __future__ import annotations

import json
import time

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from apps.api import store

from . import service
from .schemas import ResearchReportCreate, ResearchReportRegenerate, WorkspacePreferenceUpdate

router = APIRouter(prefix="/workspace", tags=["workspace"])
research_router = APIRouter(prefix="/research", tags=["research-report"])


def _principal(request: Request) -> dict:
    return getattr(request.state, "principal", None) or {
        "id": "local-user",
        "permissions": ["read"],
    }


def _owner_id(request: Request) -> str:
    return str(_principal(request).get("id") or "local-user")


@router.get("/profiles")
def profiles(request: Request) -> dict:
    return service.workspace_config(
        _owner_id(request), list(_principal(request).get("permissions", []))
    )


@router.get("/config")
def get_config(request: Request) -> dict:
    return service.workspace_config(
        _owner_id(request), list(_principal(request).get("permissions", []))
    )


@router.put("/config")
def update_config(req: WorkspacePreferenceUpdate, request: Request) -> dict:
    try:
        saved = store.save_workspace_preference(
            _owner_id(request), req.model_dump(exclude={"version"}), expected_version=req.version
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return service.workspace_config(
        _owner_id(request), list(_principal(request).get("permissions", []))
    ) | {"config": saved}


@router.get("/config/audit")
def config_audit(request: Request, limit: int = Query(default=100, ge=1, le=500)) -> dict:
    items = store.list_workspace_preference_audit(_owner_id(request), limit=limit)
    return {"ok": True, "count": len(items), "audit": items}


def _owned_report(report_id: str, request: Request) -> dict:
    report = store.get_research_report(report_id, owner_id=_owner_id(request))
    if report is None:
        raise HTTPException(status_code=404, detail="研究报告不存在")
    return report


@router.post("/research-runs/{run_id}/reports", status_code=201)
def create_report(run_id: str, req: ResearchReportCreate, request: Request) -> dict:
    run = store.get_research_run(run_id)
    if run is None or run.get("owner_id") != _owner_id(request):
        raise HTTPException(status_code=404, detail="研究运行不存在")
    report = store.create_research_report(
        research_run_id=run_id, mode=req.mode, owner_id=_owner_id(request), task_id=req.task_id
    )
    from .report_service import generate_report

    report = generate_report(report, run)
    return {"ok": True, "report": report}


@research_router.post("/runs/{run_id}/reports", status_code=201)
def create_report_alias(run_id: str, req: ResearchReportCreate, request: Request) -> dict:
    return create_report(run_id, req, request)


@router.get("/reports/{report_id}")
def get_report(report_id: str, request: Request) -> dict:
    return {"ok": True, "report": _owned_report(report_id, request)}


@research_router.get("/reports/{report_id}")
def get_report_alias(report_id: str, request: Request) -> dict:
    return get_report(report_id, request)


@router.get("/reports/{report_id}/events")
def report_events(
    report_id: str, request: Request, after_sequence: int = Query(default=0, ge=0)
) -> dict:
    _owned_report(report_id, request)
    events = store.list_research_report_events(report_id, after_sequence=after_sequence)
    return {
        "ok": True,
        "events": events,
        "next_sequence": events[-1]["sequence"] if events else after_sequence,
    }


@research_router.get("/reports/{report_id}/events")
def report_events_alias(
    report_id: str, request: Request, after_sequence: int = Query(default=0, ge=0)
) -> dict:
    return report_events(report_id, request, after_sequence)


@router.get("/reports/{report_id}/stream")
def report_stream(
    report_id: str,
    request: Request,
    after_sequence: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    _owned_report(report_id, request)
    if last_event_id and last_event_id.isdigit():
        after_sequence = max(after_sequence, int(last_event_id))

    def events():
        cursor = after_sequence
        idle = 0
        while idle < 3:
            batch = store.list_research_report_events(report_id, after_sequence=cursor)
            if batch:
                for event in batch:
                    cursor = event["sequence"]
                    yield f"id: {cursor}\nevent: {event['event_type']}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                idle = 0
            else:
                heartbeat = store.append_research_report_event(
                    report_id,
                    event_type="heartbeat",
                    payload={"after_sequence": cursor},
                )
                cursor = heartbeat["sequence"]
                yield f"id: {cursor}\nevent: heartbeat\ndata: {json.dumps(heartbeat, ensure_ascii=False, default=str)}\n\n"
                idle += 1
                time.sleep(0.2)
                report = store.get_research_report(report_id, owner_id=_owner_id(request))
                if report and report["status"] in {"completed", "failed", "cancelled"}:
                    break

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@research_router.get("/reports/{report_id}/stream")
def report_stream_alias(
    report_id: str,
    request: Request,
    after_sequence: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    return report_stream(report_id, request, after_sequence, last_event_id)


@router.post("/reports/{report_id}/cancel")
def cancel_report(report_id: str, request: Request) -> dict:
    report = _owned_report(report_id, request)
    if report["status"] not in {"completed", "failed", "cancelled"}:
        store.update_research_report(report_id, {"status": "cancelled"})
        store.append_research_report_event(
            report_id, event_type="report_error", payload={"reason": "用户取消", "blocking": True}
        )
    return {"ok": True, "report": _owned_report(report_id, request)}


@research_router.post("/reports/{report_id}/cancel")
def cancel_report_alias(report_id: str, request: Request) -> dict:
    return cancel_report(report_id, request)


@router.post("/reports/{report_id}/sections/regenerate")
def regenerate_section(report_id: str, req: ResearchReportRegenerate, request: Request) -> dict:
    report = _owned_report(report_id, request)
    run = store.get_research_run(report["research_run_id"])
    if run is None:
        raise HTTPException(status_code=404, detail="研究运行不存在")
    from .report_service import generate_report

    new_report = store.create_research_report(
        research_run_id=run["id"],
        mode=report["mode"],
        owner_id=_owner_id(request),
        task_id=report.get("task_id"),
    )
    return {"ok": True, "report": generate_report(new_report, run, only_section=req.section_key)}


@research_router.post("/reports/{report_id}/sections/regenerate")
def regenerate_section_alias(
    report_id: str, req: ResearchReportRegenerate, request: Request
) -> dict:
    return regenerate_section(report_id, req, request)
