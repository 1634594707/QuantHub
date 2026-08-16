from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.trading_costs import TradingCostProfile

from .service import get_profile, list_profiles, register_profile

router = APIRouter(prefix="/cost-profiles", tags=["cost-profiles"])


@router.get("")
def profiles(market: str | None = None, account_scope: str | None = None) -> dict:
    rows = list_profiles(market=market, account_scope=account_scope)
    return {"ok": True, "count": len(rows), "profiles": rows}


@router.get("/{profile_id}")
def profile(profile_id: str, version: str | None = None) -> dict:
    result = get_profile(profile_id, version)
    if result is None:
        raise HTTPException(status_code=404, detail="成本档案不存在")
    return {"ok": True, "profile": result}


@router.post("")
def create_profile(payload: TradingCostProfile) -> dict:
    try:
        result = register_profile(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "profile": result}
