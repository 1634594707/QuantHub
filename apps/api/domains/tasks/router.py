from __future__ import annotations

import json
import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from apps.api import store

from . import service
from .schemas import AnalysisKind, AnalysisTaskCreate, TaskStatus

router = APIRouter(prefix="/analysis/tasks", tags=["analysis-tasks"])


def _owner_id(request: Request) -> str:
    principal = getattr(request.state, "principal", None) or {}
    return str(principal.get("id") or "local-user")


def _owned_task(task_id: str, request: Request) -> dict:
    task = store.get_analysis_task(task_id)
    if task is None or task.get("owner_id") != _owner_id(request):
        raise HTTPException(status_code=404, detail=f"分析任务不存在: {task_id}")
    return task


@router.post("", status_code=202)
def create_task(req: AnalysisTaskCreate, request: Request) -> dict:
    task, duplicate = service.submit_task(
        kind=req.kind,
        symbol=req.symbol,
        market=req.market,
        timeframe=req.timeframe,
        payload=req.payload,
        timeout_seconds=req.timeout_seconds,
        owner_id=_owner_id(request),
    )
    return {"ok": True, "duplicate": duplicate, "task": task}


@router.get("")
def list_tasks(
    request: Request,
    status: TaskStatus | None = None,
    kind: AnalysisKind | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = None,
) -> dict:
    try:
        page = store.list_analysis_tasks_page(
            limit=limit,
            status=status,
            kind=kind,
            cursor=cursor,
            owner_id=_owner_id(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    tasks = [service.refresh_timeout(task) for task in page["items"]]
    return {
        "ok": True,
        "count": len(tasks),
        "total": page["total"],
        "next_cursor": page["next_cursor"],
        "tasks": tasks,
    }


@router.get("/recent")
def get_recent_task(
    request: Request,
    kind: AnalysisKind,
    symbol: str = Query(..., min_length=1),
    market: str = Query(..., min_length=1),
    timeframe: str = Query(..., min_length=1),
    within_seconds: int = Query(default=900, ge=60, le=86_400),
) -> dict:
    task = store.find_recent_analysis_task(
        kind=kind,
        symbol=symbol.strip().upper(),
        market=market,
        timeframe=timeframe,
        since=time.time() - within_seconds,
        owner_id=_owner_id(request),
    )
    return {"ok": True, "task": service.refresh_timeout(task) if task else None}


@router.get("/{task_id}")
def get_task(task_id: str, request: Request) -> dict:
    task = _owned_task(task_id, request)
    return {"ok": True, "task": service.refresh_timeout(task)}


@router.get("/{task_id}/stream")
def stream_task(task_id: str, request: Request) -> StreamingResponse:
    """以 SSE 推送分析任务状态，直到任务进入终态。"""
    _owned_task(task_id, request)
    owner_id = _owner_id(request)

    def events():
        last_updated = None
        while True:
            task = store.get_analysis_task(task_id)
            if task is None or task.get("owner_id") != owner_id:
                return
            task = service.refresh_timeout(task)
            updated = task.get("updated_at")
            if updated != last_updated:
                last_updated = updated
                yield f"event: task\ndata: {json.dumps(task, ensure_ascii=False)}\n\n"
            if task["status"] not in {"queued", "running"}:
                yield "event: done\ndata: {}\n\n"
                return
            time.sleep(0.5)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str, request: Request) -> dict:
    task = _owned_task(task_id, request)
    return {"ok": True, "task": service.cancel_task(task)}


@router.post("/{task_id}/retry", status_code=202)
def retry_task(task_id: str, request: Request) -> dict:
    task = _owned_task(task_id, request)
    result = task.get("result")
    is_partial = (
        task["status"] == "succeeded" and isinstance(result, dict) and result.get("partial") is True
    )
    if task["status"] not in {"failed", "cancelled", "timeout"} and not is_partial:
        raise HTTPException(status_code=409, detail="只有失败、部分成功、取消或超时任务可以重试")
    timeout_seconds = int(task["request"].get("timeout_seconds", 90))
    payload = {key: value for key, value in task["request"].items() if key != "timeout_seconds"}
    if task["kind"] == "evaluation" and task.get("result"):
        result = task["result"]
        steps = result.get("steps") if isinstance(result, dict) else None
        failed_modules = [
            module
            for module, step in (steps.items() if isinstance(steps, dict) else [])
            if isinstance(step, dict) and step.get("status") == "failed"
        ]
        if failed_modules:
            payload["modules"] = failed_modules
        if isinstance(result, dict) and result.get("research_run_id"):
            payload["research_run_id"] = result["research_run_id"]
    retried, _ = service.submit_task(
        kind=task["kind"],
        symbol=task["symbol"],
        market=task["market"],
        timeframe=task["timeframe"],
        payload=payload,
        timeout_seconds=timeout_seconds,
        attempt=task["attempt"] + 1,
        parent_task_id=task["id"],
        owner_id=_owner_id(request),
    )
    return {"ok": True, "task": retried}
