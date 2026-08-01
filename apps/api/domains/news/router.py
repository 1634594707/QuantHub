"""News analysis domain router: /news/health and /news/analyze endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from . import service
from .schemas import NewsAnalyzeRequest, NewsEventResearchRequest, NewsEventValidationRequest

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/health")
def news_health() -> dict:
    """新闻分析健康端点：返回语义引擎 + API 增强可用性。"""
    return service.health()


@router.post("/analyze")
def analyze_news(req: NewsAnalyzeRequest) -> dict:
    """抓取新闻并执行结构化分析。

    - 始终先走 SentimentAnalyzer 做本地兜底情绪分析
    - API 可用时启用结构化增强（NER/主题/摘要）
    - API 不可用时返回 degraded=true，仅包含情绪分析
    """
    return service.analyze(
        symbol=req.symbol,
        market=req.market,
        timeframe=req.timeframe,
        limit=req.limit,
        use_api=req.use_api,
        research_run_id=req.research_run_id,
    )


@router.post("/events/validate")
def validate_news_events(req: NewsEventValidationRequest) -> dict:
    return service.validate_research_events(req)


@router.post("/events/research")
def research_news_events(req: NewsEventResearchRequest) -> dict:
    return service.research_events(req)
