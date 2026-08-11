"""Instrument 路由：/instruments 端点。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from . import service
from .schemas import InstrumentRegister

router = APIRouter(prefix="/instruments", tags=["instrument"])


@router.get("/okx-swaps")
def okx_swaps(
    q: str = Query(default="", description="OKX instId、基础币代码或已登记别名"),
    limit: int = Query(default=100, ge=1, le=500),
    refresh: bool = Query(default=False),
) -> dict:
    return service.okx_swap_catalog(q, limit=limit, refresh=refresh)


@router.get("")
@router.get("/search")
def search(
    q: str = Query(default="", description="代码或名称关键字；空则返回最近更新的标的"),
    market: str | None = Query(default=None, description="可选市场过滤"),
    limit: int = Query(default=20, ge=1, le=200),
) -> dict:
    try:
        instruments = service.search(q, limit=limit, market=market)
    except service.InstrumentResolutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"count": len(instruments), "instruments": [i.to_dict() for i in instruments]}


@router.get("/{code}")
def get_instrument(
    code: str,
    market: str = Query(default="a_shares"),
    name: str = Query(default="", description="可选名称提示，避免回填时触网"),
) -> dict:
    instrument = service.resolve(code, market=market, name_hint=name)
    return {"ok": True, "instrument": instrument.to_dict()}


@router.post("")
def register(req: InstrumentRegister) -> dict:
    instrument = service.register(
        code=req.code,
        market=req.market,
        name=req.name,
        exchange=req.exchange,
        currency=req.currency,
        asset_class=req.asset_class,
    )
    return {"ok": True, "instrument": instrument.to_dict()}
