from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from . import repository, service
from .domain import SignalStatus
from .schemas import PublishSignalRequest, ReviewSignalRequest

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("")
def list_signals(
    limit: int = Query(default=50, ge=1, le=2000),
    source: str | None = None,
    market: str | None = None,
    status: SignalStatus | None = None,
    cursor: str | None = None,
) -> dict:
    try:
        page = repository.list_signals_page(
            limit=limit,
            source=source,
            market=market,
            status=status,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "count": len(page["items"]),
        "total": page["total"],
        "next_cursor": page["next_cursor"],
        "signals": page["items"],
    }


@router.post("/publish")
def publish_signal(req: PublishSignalRequest) -> dict:
    try:
        signal = service.publish(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "signal": signal}


@router.delete("/{signal_id}")
def delete_signal(signal_id: str) -> dict:
    repository.delete_signal(signal_id)
    return {"ok": True}


@router.patch("/{signal_id}/status")
def review_signal(signal_id: str, req: ReviewSignalRequest) -> dict:
    try:
        signal = service.review(signal_id, target=req.status, note=req.note)
    except service.SignalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"信号不存在: {signal_id}") from exc
    except service.InvalidSignalTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "signal": signal}
