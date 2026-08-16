"""Ensemble 编排服务：聚合技术 / LLM / 新闻三类贡献者，产出加权共识。

设计要点：
    - K 线只拉一次，technical 复用同一份 frame 计算 SuperTrend
    - 每个贡献者独立 try/except，失败标记 ``available=False`` 并计入 warnings
    - 共识只统计可用贡献者；n=0 时返回 hold 兜底
    - 结果写入 ResearchRun：market_snapshot + ensemble_output 证据
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from apps.api.domains.research.service import (
    ResearchContextMismatchError,
    add_evidence,
    complete_module,
    dataframe_snapshot,
    fail_module,
    start_module,
)
from core.data_feed.factory import get_data_source
from strategies.a_shares.news_analyzer.analyzer import NewsAnalyzer
from strategies.a_shares.supertrend.indicators import supertrend as st_supertrend
from strategies.a_shares.supertrend.strategy import SuperTrendStrategy
from strategies.ai_analysis.pa_agent.two_stage import (
    PA_PIPELINE_VERSION,
    run_two_stage,
)

from .schemas import EnsembleRequest

logger = logging.getLogger(__name__)

# 贡献者权重（LLM 最重，技术次之，新闻最轻）
_WEIGHT_TECHNICAL = 0.30
_WEIGHT_LLM = 0.40
_WEIGHT_NEWS = 0.30

_ORDER_TYPES_WITH_TRADE = ("限价单", "突破单", "市价单")
_NEWS_LIMIT = 10
_ST_PERIOD = 10
_ST_MULTIPLIER = 3.0

ENSEMBLE_VERSION = "quanthub-ensemble-v1"


def _resolve_market(symbol: str, market: str | None) -> str:
    """与 strategies.service._resolve_pa_market 一致的市场推断。"""
    if market:
        return market
    normalized = (symbol or "").strip().upper()
    if normalized.isdigit() and len(normalized) == 6:
        return "a_shares"
    if any(c.isalpha() for c in normalized) and (
        "-" in normalized or "/" in normalized or len(normalized) >= 6
    ):
        return "crypto"
    return "a_shares"


def _technical_contributor(frame: pd.DataFrame, symbol: str, timeframe: str) -> dict[str, Any]:
    """SuperTrend 技术贡献者。复用已拉取的 frame，避免重复请求。"""
    df = st_supertrend(frame, period=_ST_PERIOD, multiplier=_ST_MULTIPLIER)
    sig = SuperTrendStrategy._signal_from_df(df, symbol, timeframe, _ST_PERIOD, _ST_MULTIPLIER)
    if sig is None:
        return {
            "name": "SuperTrend",
            "kind": "technical",
            "direction": "hold",
            "score": 0.0,
            "confidence": 0.0,
            "weight": _WEIGHT_TECHNICAL,
            "available": False,
            "rationale": "SuperTrend 无法从当前 K 线计算方向",
            "metrics": {},
        }
    return {
        "name": "SuperTrend",
        "kind": "technical",
        "direction": sig.direction,
        "score": float(sig.score),
        "confidence": float(sig.confidence),
        "weight": _WEIGHT_TECHNICAL,
        "available": True,
        "rationale": f"trend={sig.meta.get('trend')}, trend_bars={sig.meta.get('trend_bars')}",
        "metrics": sig.meta,
    }


def _llm_contributor(symbol: str, timeframe: str, frame: pd.DataFrame) -> dict[str, Any]:
    """PA 两阶段 LLM 贡献者。"""
    result = run_two_stage(symbol=symbol, timeframe=timeframe, klines=frame)
    if result.error and not result.stage2_json:
        return {
            "name": "PA-Agent",
            "kind": "llm",
            "direction": "hold",
            "score": 0.0,
            "confidence": 0.0,
            "weight": _WEIGHT_LLM,
            "available": False,
            "rationale": f"PA 分析失败: {result.error}",
            "metrics": {"pipeline_version": PA_PIPELINE_VERSION},
        }
    stage2 = result.stage2_json or {}
    decision = stage2.get("decision") or {}
    order_type = str(decision.get("order_type", "不下单"))
    order_direction = str(decision.get("order_direction", ""))
    is_trade = order_type in _ORDER_TYPES_WITH_TRADE
    if is_trade and order_direction == "做多":
        direction = "buy"
    elif is_trade and order_direction == "做空":
        direction = "sell"
    else:
        direction = "hold"
    raw_conf = decision.get("diagnosis_confidence")
    try:
        confidence = max(0.0, min(1.0, float(raw_conf) / 100.0)) if raw_conf is not None else 0.5
    except (TypeError, ValueError):
        confidence = 0.5
    return {
        "name": "PA-Agent",
        "kind": "llm",
        "direction": direction,
        "score": confidence,
        "confidence": confidence,
        "weight": _WEIGHT_LLM,
        "available": True,
        "rationale": f"order_type={order_type}, direction={order_direction or 'N/A'}",
        "metrics": {
            "pipeline_version": PA_PIPELINE_VERSION,
            "stage1_complete": bool(result.stage1_json),
            "stage2_complete": bool(result.stage2_json),
            "usage": result.usage,
        },
    }


def _news_contributor(symbol: str, market: str) -> dict[str, Any]:
    """新闻情绪贡献者。"""
    ds = get_data_source(market)
    news_list = ds.get_news(symbol=symbol, limit=_NEWS_LIMIT)
    if not news_list:
        return {
            "name": "News-Sentiment",
            "kind": "news",
            "direction": "hold",
            "score": 0.0,
            "confidence": 0.0,
            "weight": _WEIGHT_NEWS,
            "available": False,
            "rationale": "无可用新闻数据",
            "metrics": {},
        }
    analyzer = NewsAnalyzer.from_config(market)
    batch = analyzer.analyze_batch(news_list, use_api=True)
    sentiment_dist = {"positive": 0, "negative": 0, "neutral": 0}
    for item in batch.items:
        sentiment_dist[item.sentiment.label] = sentiment_dist.get(item.sentiment.label, 0) + 1
    total = max(1, batch.total)
    pos = sentiment_dist.get("positive", 0)
    neg = sentiment_dist.get("negative", 0)
    if pos > neg:
        direction = "buy"
    elif neg > pos:
        direction = "sell"
    else:
        direction = "hold"
    confidence = max(pos, neg) / total
    return {
        "name": "News-Sentiment",
        "kind": "news",
        "direction": direction,
        "score": confidence,
        "confidence": confidence,
        "weight": _WEIGHT_NEWS,
        "available": True,
        "rationale": f"pos={pos}, neg={neg}, neutral={sentiment_dist.get('neutral', 0)}, engine={batch.engine}",
        "metrics": {
            "engine": batch.engine,
            "model": batch.model,
            "total": batch.total,
            "sentiment_dist": sentiment_dist,
            "degraded_reason": batch.degraded_reason,
        },
    }


def _aggregate_consensus(contributors: list[dict[str, Any]]) -> dict[str, Any]:
    """加权聚合共识。仅统计 available=True 的贡献者。"""
    available = [c for c in contributors if c.get("available")]
    n = len(available)
    if n == 0:
        return {
            "direction": "hold",
            "score": 0.0,
            "confidence": 0.0,
            "agreement": 0.0,
            "buy_votes": 0,
            "sell_votes": 0,
            "n": 0,
        }
    weighted: dict[str, float] = {"buy": 0.0, "sell": 0.0, "hold": 0.0}
    votes = {"buy": 0, "sell": 0, "hold": 0}
    conf_sum = 0.0
    weight_sum = 0.0
    for c in available:
        direction = c["direction"]
        w = c["weight"]
        conf = c["confidence"]
        weighted[direction] += conf * w
        votes[direction] += 1
        conf_sum += conf * w
        weight_sum += w
    total_weighted = sum(weighted.values())
    if total_weighted <= 0:
        winner = "hold"
        score = 0.0
        agreement = 0.0
    else:
        winner = max(weighted, key=weighted.get)
        score = weighted[winner] / total_weighted
        agreement = weighted[winner] / total_weighted
    confidence = conf_sum / weight_sum if weight_sum > 0 else 0.0
    return {
        "direction": winner,
        "score": round(score, 4),
        "confidence": round(confidence, 4),
        "agreement": round(agreement, 4),
        "buy_votes": votes["buy"],
        "sell_votes": votes["sell"],
        "n": n,
    }


def predict(req: EnsembleRequest, *, owner_id: str = "local-user") -> dict[str, Any]:
    """执行协同预测，返回 EnsembleResp 结构（与前端 types.ts 对齐）。"""
    symbol = req.symbol
    timeframe = req.timeframe
    actual_market = _resolve_market(symbol, req.market)
    warnings: list[str] = []
    contributors: list[dict[str, Any]] = []

    def _fail(error: str) -> dict[str, Any]:
        if req.research_run_id:
            try:
                fail_module(req.research_run_id, "ensemble", error)
            except Exception:  # noqa: BLE001 - persistence failure must not hide analysis error
                logger.warning("Ensemble 失败时写 ResearchRun 失败: %s", error)
        return {
            "ok": False,
            "error": error,
            "symbol": symbol,
            "market": actual_market,
            "timeframe": timeframe,
            "research_run_id": req.research_run_id,
        }

    # 一次性拉取 K 线（technical + llm 共用）
    try:
        source = get_data_source(actual_market)
        frame = source.get_kline(symbol, timeframe, limit=req.limit)
    except Exception as exc:  # noqa: BLE001 - data-source boundary converts failures to result
        logger.exception("Ensemble 取 K 线失败 %s/%s", actual_market, symbol)
        return _fail(f"取 K 线失败: {exc}")

    if frame is None or frame.empty:
        return _fail("K 线为空，无法执行协同预测")

    data_source_name = str(frame.attrs.get("_source", "local"))
    kline_count = int(len(frame))

    # technical 贡献者
    try:
        contributors.append(_technical_contributor(frame, symbol, timeframe))
    except Exception as exc:
        logger.exception("SuperTrend 贡献者失败 %s", symbol)
        warnings.append(f"技术分析失败: {exc}")
        contributors.append(
            {
                "name": "SuperTrend",
                "kind": "technical",
                "direction": "hold",
                "score": 0.0,
                "confidence": 0.0,
                "weight": _WEIGHT_TECHNICAL,
                "available": False,
                "rationale": f"异常: {exc}",
                "metrics": {},
            }
        )

    # llm 贡献者
    try:
        contributors.append(_llm_contributor(symbol, timeframe, frame))
    except Exception as exc:
        logger.exception("PA 贡献者失败 %s", symbol)
        warnings.append(f"PA LLM 调用失败: {exc}")
        contributors.append(
            {
                "name": "PA-Agent",
                "kind": "llm",
                "direction": "hold",
                "score": 0.0,
                "confidence": 0.0,
                "weight": _WEIGHT_LLM,
                "available": False,
                "rationale": f"异常: {exc}",
                "metrics": {"pipeline_version": PA_PIPELINE_VERSION},
            }
        )

    # news 贡献者
    try:
        contributors.append(_news_contributor(symbol, actual_market))
    except Exception as exc:
        logger.exception("新闻贡献者失败 %s", symbol)
        warnings.append(f"新闻分析失败: {exc}")
        contributors.append(
            {
                "name": "News-Sentiment",
                "kind": "news",
                "direction": "hold",
                "score": 0.0,
                "confidence": 0.0,
                "weight": _WEIGHT_NEWS,
                "available": False,
                "rationale": f"异常: {exc}",
                "metrics": {},
            }
        )

    consensus = _aggregate_consensus(contributors)

    # 持久化到研究运行
    run_id = req.research_run_id
    try:
        snapshot = dataframe_snapshot(frame)
        try:
            run_id = start_module(
                symbol=symbol,
                market=actual_market,
                timeframe=timeframe,
                module="ensemble",
                input_data={"limit": req.limit, "timeframe": timeframe},
                run_id=req.research_run_id,
                owner_id=owner_id,
            )
        except ResearchContextMismatchError as exc:
            logger.warning("Ensemble 研究上下文不一致，回退到新建 run: %s", exc)
            run_id = start_module(
                symbol=symbol,
                market=actual_market,
                timeframe=timeframe,
                module="ensemble",
                input_data={"limit": req.limit, "timeframe": timeframe},
                run_id=None,
                owner_id=owner_id,
            )
        add_evidence(
            run_id,
            kind="market_snapshot",
            source=snapshot["source"],
            title=f"Ensemble 输入 K 线 {symbol}",
            payload=snapshot,
        )
        add_evidence(
            run_id,
            kind="ensemble_output",
            source=ENSEMBLE_VERSION,
            title=f"协同预测 {symbol}",
            payload={
                "contributors": contributors,
                "consensus": consensus,
                "weights": {
                    "technical": _WEIGHT_TECHNICAL,
                    "llm": _WEIGHT_LLM,
                    "news": _WEIGHT_NEWS,
                },
                "warnings": warnings,
            },
        )
        complete_module(
            run_id,
            "ensemble",
            {
                "consensus": consensus,
                "n": consensus["n"],
                "version": ENSEMBLE_VERSION,
            },
        )
    except Exception as exc:  # noqa: BLE001 - persistence is best-effort for analysis output
        logger.warning("Ensemble 结果持久化失败 %s: %s", symbol, exc)
        run_id = req.research_run_id

    return {
        "ok": True,
        "research_run_id": run_id,
        "symbol": symbol,
        "market": actual_market,
        "timeframe": timeframe,
        "data_source": data_source_name,
        "kline_count": kline_count,
        "contributors": contributors,
        "consensus": consensus,
        "warnings": warnings,
    }
