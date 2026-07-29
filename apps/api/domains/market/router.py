"""Data 领域路由：/data/* 端点（例如 K 线），保持与前端现有调用的路径兼容。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from . import service
from .schemas import KlineResponse

router = APIRouter(tags=["data"])


@router.get("/data/kline", response_model=KlineResponse)
def get_kline(
    symbol: str,
    market: str = Query(default="a_shares"),
    interval: str = Query(default="1h"),
    limit: int = Query(default=240, ge=1, le=5000),
) -> dict:
    return service.fetch_kline(symbol=symbol, market=market, interval=interval, limit=limit)
