from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .public_stream import get_public_stream_manager
from .schemas import (
    DataSourceCheckRequest,
    MarketDataStatusResponse,
    PublicMarketStreamStartRequest,
)
from .service import check_data_source, data_source_status

router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.get("/status", response_model=MarketDataStatusResponse)
def get_data_source_status() -> dict:
    return data_source_status()


@router.post("/check")
def post_data_source_check(req: DataSourceCheckRequest) -> dict:
    try:
        return check_data_source(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/public-streams", status_code=201)
def start_public_market_stream(req: PublicMarketStreamStartRequest) -> dict:
    try:
        return get_public_stream_manager().start(
            inst_id=req.inst_id,
            candle_channel=req.candle_channel,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/public-streams")
def public_market_stream_status(stream_id: str | None = None) -> dict:
    try:
        return get_public_stream_manager().status(stream_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="公共行情流不存在") from exc


@router.delete("/public-streams/{stream_id}")
def stop_public_market_stream(stream_id: str) -> dict:
    try:
        return get_public_stream_manager().stop(stream_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="公共行情流不存在") from exc
