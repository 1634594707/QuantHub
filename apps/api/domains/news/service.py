"""News analysis service: health check and analyze endpoints."""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from apps.api.domains.research.service import (
    ResearchContextMismatchError,
    add_evidence,
    complete_module,
    fail_module,
    snapshot_hash,
    start_module,
)
from core.data_feed.factory import get_data_source
from strategies.a_shares.news_analyzer.analyzer import NewsAnalyzer

logger = logging.getLogger(__name__)


def health() -> dict[str, Any]:
    """返回新闻分析健康状态（语义引擎 + API 增强可用性）。"""
    analyzer = NewsAnalyzer.from_config("a_shares")
    status = analyzer.health()
    return {"ok": True, **status}


def analyze(
    symbol: str,
    market: str = "a_shares",
    timeframe: str = "1d",
    limit: int = 20,
    use_api: bool = True,
    research_run_id: str | None = None,
) -> dict[str, Any]:
    """抓取新闻并执行结构化分析。

    - 始终先走 SentimentAnalyzer 做本地兜底情绪分析
    - API 可用时启用结构化增强（NER/主题/摘要）
    - API 不可用时返回 degraded=true，仅包含情绪分析
    - 无新闻时返回 ok=true, total=0, degraded_reason=no_news
    - 支持传入 ``research_run_id`` 复用同一研究运行；上下文不一致时回退到新建 run
    """
    analyzer = NewsAnalyzer.from_config(market)
    ds = get_data_source(market)

    def _fail(error: str) -> dict[str, Any]:
        if research_run_id:
            try:
                fail_module(research_run_id, "news", error)
            except Exception:
                logger.warning("新闻失败时写 ResearchRun 失败: %s", error)
        return {
            "ok": False,
            "error": error,
            "symbol": symbol,
            "market": market,
            "total": 0,
            "items": [],
            "research_run_id": research_run_id,
        }

    try:
        news_list = ds.get_news(symbol=symbol, limit=max(1, int(limit)))
    except Exception as exc:
        logger.exception("获取新闻失败: %s", symbol)
        return _fail(f"获取新闻失败: {exc}")

    if not news_list:
        return {
            "ok": True,
            "symbol": symbol,
            "market": market,
            "total": 0,
            "items": [],
            "engine": "semantic",
            "degraded": True,
            "degraded_reason": "no_news",
            "sentiment_dist": {"positive": 0, "negative": 0, "neutral": 0},
            "topic_dist": {},
            "event_impact_dist": {
                "positive": 0,
                "negative": 0,
                "neutral": 0,
                "uncertain": 0,
            },
            "top_entities": [],
            "research_run_id": None,
        }

    batch = analyzer.analyze_batch(news_list, use_api=use_api)

    # 聚合主题/情绪分布
    sentiment_dist = {"positive": 0, "negative": 0, "neutral": 0}
    event_impact_dist = {"positive": 0, "negative": 0, "neutral": 0, "uncertain": 0}
    topic_dist: dict[str, int] = {}
    entity_counter: Counter[tuple[str, str]] = Counter()
    for item in batch.items:
        sentiment_dist[item.sentiment.label] = sentiment_dist.get(item.sentiment.label, 0) + 1
        impact_label = item.event_impact.label
        event_impact_dist[impact_label] = event_impact_dist.get(impact_label, 0) + 1
        topic_dist[item.topic] = topic_dist.get(item.topic, 0) + 1
        entity_counter.update((entity.text, entity.type) for entity in item.entities)

    top_entities = [
        {"text": text, "type": entity_type, "count": count}
        for (text, entity_type), count in entity_counter.most_common(10)
    ]

    result = {
        "ok": True,
        "symbol": symbol,
        "market": market,
        "total": batch.total,
        "items": [item.to_dict() for item in batch.items],
        "engine": batch.engine,
        "model": batch.model,
        "degraded": batch.engine != "semantic+api",
        "degraded_reason": batch.degraded_reason,
        "sentiment_dist": sentiment_dist,
        "topic_dist": topic_dist,
        "event_impact_dist": event_impact_dist,
        "top_entities": top_entities,
    }

    # 持久化到研究运行
    run_id = research_run_id
    try:
        try:
            run_id = start_module(
                symbol=symbol,
                market=market,
                timeframe=timeframe,
                module="news",
                input_data={
                    "limit": limit,
                    "use_api": use_api,
                    "engine": batch.engine,
                    "timeframe": timeframe,
                },
                run_id=research_run_id,
            )
        except ResearchContextMismatchError as exc:
            logger.warning("新闻研究上下文不一致，回退到新建 run: %s", exc)
            run_id = start_module(
                symbol=symbol,
                market=market,
                timeframe=timeframe,
                module="news",
                input_data={
                    "limit": limit,
                    "use_api": use_api,
                    "engine": batch.engine,
                    "timeframe": timeframe,
                },
                run_id=None,
            )
        first_title = batch.items[0].title if batch.items else symbol
        add_evidence(
            run_id,
            kind="news",
            source=batch.engine,
            title=first_title,
            uri=None,
            payload={
                "symbol": symbol,
                "total": batch.total,
                "engine": batch.engine,
                "model": batch.model,
                "sentiment_dist": sentiment_dist,
                "topic_dist": topic_dist,
                "items": result["items"],
                "sha256": snapshot_hash(result["items"]),
            },
        )
        complete_module(
            run_id,
            "news",
            {
                "engine": batch.engine,
                "total": batch.total,
                "sentiment_dist": sentiment_dist,
                "topic_dist": topic_dist,
                "event_impact_dist": event_impact_dist,
                "top_entities": top_entities,
            },
        )
        result["research_run_id"] = run_id
    except Exception as exc:
        logger.warning("新闻分析结果持久化失败: %s", exc)
        result["research_run_id"] = research_run_id

    return result
