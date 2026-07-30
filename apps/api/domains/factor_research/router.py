from __future__ import annotations

from fastapi import APIRouter

from .schemas import FactorResearchRequest
from .service import run_factor_research

router = APIRouter(prefix="/factor-research", tags=["factor-research"])


@router.post("/analyze")
def analyze(req: FactorResearchRequest) -> dict:
    return run_factor_research(req)
