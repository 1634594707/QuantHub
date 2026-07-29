from __future__ import annotations

from fastapi import APIRouter, Query

from . import service

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
def global_search(
    q: str = Query(..., min_length=1, max_length=200),
    limit_per_group: int = Query(default=6, ge=1, le=20),
) -> dict:
    return service.search(q, limit_per_group=limit_per_group)
