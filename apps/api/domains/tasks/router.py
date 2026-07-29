from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query

from apps.api import store

from . import service
from .schemas import AnalysisKind, AnalysisTaskCreate, TaskStatus

router = APIRouter(prefix="/analysis/tasks", tags=["analysis-tasks"])


@router.post("", status_code=202)
def create_task(req: AnalysisTaskCreate) -> dict:
    task, duplicate = service.submit_task(
        kind=req.kind,
        symbol=req.symbol,
        market=req.market,
        timeframe=req.timeframe,
        payload=req.payload,
        timeout_seconds=req.timeout_seconds,
    )
    return {"ok": True, "duplicate": duplicate, "task": task}


@router.get("")
def list_tasks(
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
    )
    return {"ok": True, "task": service.refresh_timeout(task) if task else None}


@router.get("/{task_id}")
def get_task(task_id: str) -> dict:
    task = store.get_analysis_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"分析任务不存在: {task_id}")
    return {"ok": True, "task": service.refresh_timeout(task)}


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str) -> dict:
    task = store.get_analysis_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"分析任务不存在: {task_id}")
    return {"ok": True, "task": service.cancel_task(task)}


@router.post("/{task_id}/retry", status_code=202)
def retry_task(task_id: str) -> dict:
    task = store.get_analysis_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"分析任务不存在: {task_id}")
    if task["status"] not in {"failed", "cancelled", "timeout"}:
        raise HTTPException(status_code=409, detail="只有失败、取消或超时任务可以重试")
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
    )
    return {"ok": True, "task": retried}
