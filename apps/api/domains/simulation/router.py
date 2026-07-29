from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from apps.api import store

from . import service
from .schemas import (
    OrderStatus,
    SimulationFillCreate,
    SimulationOrderCreate,
    SimulationOrderPreviewRequest,
)

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.get("/account")
def get_account() -> dict:
    return service.account_snapshot()


@router.post("/orders/preview")
def preview_order(req: SimulationOrderPreviewRequest) -> dict:
    try:
        preview = service.preview_order(req)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"信号不存在: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "preview": preview}


@router.post("/orders", status_code=201)
def create_order(req: SimulationOrderCreate) -> dict:
    try:
        order = service.create_order(req)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"信号不存在: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "order": order}


@router.get("/orders")
def list_orders(
    status: OrderStatus | None = None,
    symbol: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = None,
) -> dict:
    try:
        page = store.list_simulation_orders_page(
            status=status,
            symbol=symbol.strip().upper() if symbol else None,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "ok": True,
        "count": len(page["items"]),
        "total": page["total"],
        "next_cursor": page["next_cursor"],
        "orders": page["items"],
    }


@router.get("/orders/{order_id}")
def get_order(order_id: str) -> dict:
    order = store.get_simulation_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"模拟订单不存在: {order_id}")
    return {"ok": True, "order": order}


@router.post("/orders/{order_id}/fills")
def fill_order(order_id: str, req: SimulationFillCreate) -> dict:
    try:
        order = service.fill_order(order_id, req)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"模拟订单不存在: {order_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "order": order}


@router.post("/orders/{order_id}/executions/{execution_id}/ledger-sync")
def retry_ledger_sync(order_id: str, execution_id: str) -> dict:
    try:
        order = service.sync_execution_to_ledger(order_id, execution_id)
    except KeyError as exc:
        missing_id = exc.args[0]
        if missing_id == order_id:
            detail = f"模拟订单不存在: {order_id}"
        else:
            detail = f"模拟成交不存在: {execution_id}"
        raise HTTPException(status_code=404, detail=detail) from exc
    return {"ok": True, "order": order}


@router.post("/orders/{order_id}/cancel")
def cancel_order(order_id: str) -> dict:
    try:
        order = store.cancel_simulation_order(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if order is None:
        raise HTTPException(status_code=404, detail=f"模拟订单不存在: {order_id}")
    return {"ok": True, "order": order}
