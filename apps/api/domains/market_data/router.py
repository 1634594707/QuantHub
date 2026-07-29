from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .schemas import DataSourceCheckRequest, MarketDataStatusResponse
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
