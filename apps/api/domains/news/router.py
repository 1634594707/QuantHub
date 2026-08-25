"""News analysis domain router: /news/health and /news/analyze endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

from . import service
from .schemas import NewsAnalyzeRequest, NewsEventResearchRequest, NewsEventValidationRequest

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/health")
def news_health() -> dict:
    """新闻分析健康端点：返回完整模型路径的可用性。"""
    return service.health()


@router.post("/analyze")
def analyze_news(req: NewsAnalyzeRequest, request: Request) -> dict:
    """抓取新闻并执行结构化分析。

    - 配置的 FinBERT2 与 LLM 必须完整成功，才返回可用结构化新闻分析
    - 模型或 LLM 不可用时返回明确失败，不持久化新闻证据
    """
    return service.analyze(
        symbol=req.symbol,
        market=req.market,
        timeframe=req.timeframe,
        limit=req.limit,
        research_run_id=req.research_run_id,
        owner_id=str((getattr(request.state, "principal", None) or {}).get("id") or "local-user"),
    )


@router.post("/events/validate")
def validate_news_events(req: NewsEventValidationRequest) -> dict:
    return service.validate_research_events(req)


@router.post("/events/research")
def research_news_events(req: NewsEventResearchRequest) -> dict:
    return service.research_events(req)
