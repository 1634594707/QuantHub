from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from apps.api.domains.instrument import service as instrument_service

from . import repository, service
from .schemas import AllocationCreate, HoldingCreate, HoldingUpdate, WatchCreate, WatchUpdate

router = APIRouter(tags=["portfolio"])


def _owner_id(request: Request) -> str:
    principal = getattr(request.state, "principal", None) or {}
    return str(principal.get("id") or "local-user")


@router.get("/portfolio/manage")
def get_portfolio_manage() -> dict:
    return service.allocation_overview()


@router.post("/portfolio/manage/allocations")
def create_allocation(req: AllocationCreate) -> dict:
    try:
        allocation = service.create_allocation(req)
    except service.UnknownStrategyError as exc:
        raise HTTPException(status_code=404, detail=f"未知策略: {req.strategy}") from exc
    return {"ok": True, "alloc": allocation}


@router.delete("/portfolio/manage/allocations/{allocation_id}")
def delete_allocation(allocation_id: str) -> dict:
    repository.delete_allocation(allocation_id)
    return {"ok": True}


@router.post("/portfolio/manage/allocations/{allocation_id}/live")
def update_allocation_live(allocation_id: str, live: bool = False) -> dict:
    repository.update_live(allocation_id, live)
    return {"ok": True}


@router.get("/portfolio")
def get_portfolio() -> dict:
    return service.portfolio_snapshot()


@router.post("/portfolio/holdings")
def add_holding(req: HoldingCreate) -> dict:
    try:
        instrument = instrument_service.resolve_strict(req.code, req.market, req.name)
    except instrument_service.InstrumentResolutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    name = instrument.name or service.resolve_security_name(req.code, req.market, req.name)
    return {
        "ok": True,
        "holding": repository.add_holding(
            instrument.code,
            name,
            req.shares,
            req.cost,
            instrument.market,
            instrument.instrument_id,
        ),
    }


@router.patch("/portfolio/holdings/{holding_id}")
def update_holding(holding_id: str, req: HoldingUpdate) -> dict:
    patch = req.model_dump(exclude_unset=True)
    current = next((item for item in repository.list_holdings() if item["id"] == holding_id), None)
    if current is None:
        raise HTTPException(status_code=404, detail=f"持仓不存在: {holding_id}")
    code = str(patch.get("code", current["code"]))
    market = str(patch.get("market", current["market"]))
    try:
        instrument = instrument_service.resolve_strict(code, market, str(patch.get("name", "")))
    except instrument_service.InstrumentResolutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    patch.update(
        {
            "code": instrument.code,
            "market": instrument.market,
            "instrument_id": instrument.instrument_id,
        }
    )
    if not str(patch.get("name", "")).strip():
        patch["name"] = instrument.name or service.resolve_security_name(code, market)
    holding = repository.update_holding(holding_id, patch)
    if holding is None:
        raise HTTPException(status_code=404, detail=f"持仓不存在: {holding_id}")
    return {"ok": True, "holding": holding}


@router.delete("/portfolio/holdings/{holding_id}")
def delete_holding(holding_id: str) -> dict:
    if not repository.delete_holding(holding_id):
        raise HTTPException(status_code=404, detail=f"持仓不存在: {holding_id}")
    return {"ok": True}


@router.get("/market/breadth")
def get_market_breadth() -> dict:
    return service.market_breadth()


@router.get("/market/watchlist")
def get_watchlist(request: Request) -> dict:
    return service.watchlist_snapshot(_owner_id(request))


@router.post("/market/watchlist")
def add_watchlist(req: WatchCreate, request: Request) -> dict:
    try:
        instrument = instrument_service.resolve_strict(req.sym, req.market, req.name)
    except instrument_service.InstrumentResolutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    name = instrument.name or service.resolve_security_name(req.sym, req.market, req.name)
    return {
        "ok": True,
        "watch": repository.add_watchlist(
            instrument.code,
            name,
            instrument.market,
            instrument.instrument_id,
            _owner_id(request),
        ),
    }


@router.patch("/market/watchlist/{watch_id}")
def update_watchlist(watch_id: str, req: WatchUpdate, request: Request) -> dict:
    patch = req.model_dump(exclude_unset=True)
    owner_id = _owner_id(request)
    current = next(
        (item for item in repository.list_watchlist(owner_id) if item["id"] == watch_id), None
    )
    if current is None:
        raise HTTPException(status_code=404, detail=f"关注标的不存在: {watch_id}")
    symbol = str(patch.get("sym", current["sym"]))
    market = str(patch.get("market", current["market"]))
    try:
        instrument = instrument_service.resolve_strict(symbol, market, str(patch.get("name", "")))
    except instrument_service.InstrumentResolutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    patch.update(
        {
            "sym": instrument.code,
            "market": instrument.market,
            "instrument_id": instrument.instrument_id,
        }
    )
    if not str(patch.get("name", "")).strip():
        patch["name"] = instrument.name or service.resolve_security_name(symbol, market)
    watch = repository.update_watchlist(watch_id, patch, owner_id)
    if watch is None:
        raise HTTPException(status_code=404, detail=f"关注标的不存在: {watch_id}")
    return {"ok": True, "watch": watch}


@router.delete("/market/watchlist/{watch_id}")
def delete_watchlist(watch_id: str, request: Request) -> dict:
    if not repository.delete_watchlist(watch_id, _owner_id(request)):
        raise HTTPException(status_code=404, detail=f"关注标的不存在: {watch_id}")
    return {"ok": True}


@router.get("/market/quote")
def get_quote(symbol: str, market: str = "a_shares") -> dict:
    return service.quote_item(symbol.strip().upper(), market)
