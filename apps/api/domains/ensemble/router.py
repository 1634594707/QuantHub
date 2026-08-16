"""Ensemble 领域路由：/predict/ensemble 端点。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from . import service
from .schemas import EnsembleRequest

router = APIRouter(prefix="/predict", tags=["ensemble"])


@router.post("/ensemble")
def predict_ensemble(req: EnsembleRequest, request: Request) -> dict:
    """多算法协同预测：技术 + LLM + 新闻加权聚合为共识。

    - K 线只拉一次，三类贡献者独立 try/except，失败标记 available=False
    - 结果写入 ResearchRun（market_snapshot + ensemble_output 证据）
    - 传入 research_run_id 时复用同一运行；上下文不一致时回退到新建 run
    """
    owner_id = str((getattr(request.state, "principal", None) or {}).get("id") or "local-user")
    return service.predict(req, owner_id=owner_id)
