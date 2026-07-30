from __future__ import annotations

import logging
from typing import Any

from apps.api import store
from core.data_feed.factory import get_data_source
from core.data_feed.quality import assess_ohlcv
from core.factor_research import InsufficientFactorData, ResearchConfig, analyze_factors

from .ai_review import AI_REVIEW_TIMEOUT_SECONDS, run_ai_review
from .schemas import FactorAiReviewRequest, FactorResearchRequest

logger = logging.getLogger(__name__)

FACTOR_RESEARCH_MODULE = "factor_research"
FACTOR_RESULT_EVIDENCE = "factor_research_result"
FACTOR_AI_EVIDENCE = "factor_ai_review"


def _periods_per_year(market: str, interval: str) -> int:
    normalized = interval.lower()
    if market == "crypto":
        return {"1h": 8_760, "4h": 2_190, "1d": 365}.get(normalized, 365)
    if market == "mt5":
        return {"1h": 6_240, "4h": 1_560, "1d": 252}.get(normalized, 252)
    return {"1h": 1_512, "4h": 378, "1d": 252, "1w": 52}.get(normalized, 252)


def run_factor_research(req: FactorResearchRequest) -> dict:
    try:
        source = get_data_source(req.market)
        frame = source.get_kline(req.symbol, req.interval, limit=req.limit)
    except Exception as exc:  # noqa: BLE001 - adapters may raise third-party transport errors
        return {"ok": False, "error": f"获取 K 线失败: {exc}"}
    quality = assess_ohlcv(frame)
    if not quality.usable:
        return {
            "ok": False,
            "error": f"K线质量不合格: {quality.reason or quality.status}",
            "quality": quality.to_dict(),
        }
    try:
        result = analyze_factors(
            frame,
            ResearchConfig(
                horizon=req.horizon,
                periods_per_year=_periods_per_year(req.market, req.interval),
                transaction_cost_bps=req.transaction_cost_bps,
            ),
        )
    except InsufficientFactorData as exc:
        return {"ok": False, "error": str(exc), "quality": quality.to_dict()}
    return {
        "ok": True,
        "symbol": req.symbol,
        "market": req.market,
        "interval": req.interval,
        "source": frame.attrs.get("_source", getattr(source, "name", "unknown")),
        "quality": quality.to_dict(),
        **result,
    }


def _request_payload(req: FactorResearchRequest | FactorAiReviewRequest) -> dict[str, Any]:
    return req.model_dump(exclude={"review_focus", "run_id"}, exclude_none=True)


def _factor_summary(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "因子研究失败")}
    summary = result["summary"]
    signal = result["current_signal"]
    return {
        "ok": True,
        "source": result.get("source"),
        "rows": summary.get("rows"),
        "test_rows": summary.get("test_rows"),
        "usable_factors": summary.get("usable_factors"),
        "selected_factors": summary.get("selected_factors", []),
        "best_factor": summary.get("best_factor"),
        "best_method": summary.get("best_method"),
        "signal_level": signal.get("level"),
        "drawdown": signal.get("drawdown"),
    }


def _create_factor_run(req: FactorResearchRequest) -> dict:
    run = store.create_research_run(
        symbol=req.symbol,
        market=req.market,
        timeframe=req.interval,
        modules=[FACTOR_RESEARCH_MODULE],
        input_data={FACTOR_RESEARCH_MODULE: _request_payload(req)},
    )
    return store.update_research_run(run["id"], {"status": "running"}) or run


def run_and_save_factor_research(req: FactorResearchRequest) -> dict:
    """Run deterministic research and persist its complete server-side snapshot."""
    run: dict[str, Any] | None = None
    persistence_error: str | None = None
    try:
        run = _create_factor_run(req)
    except Exception as exc:  # noqa: BLE001 - research remains useful if storage is unavailable
        persistence_error = str(exc)
        logger.exception("创建因子研究记录失败")

    result = run_factor_research(req)
    if run is None:
        return {
            **result,
            "saved": False,
            "persistence_error": persistence_error or "研究记录存储不可用",
        }

    run_id = str(run["id"])
    if result.get("ok"):
        store.add_research_evidence(
            run_id=run_id,
            kind=FACTOR_RESULT_EVIDENCE,
            source=str(result.get("source") or "factor_engine"),
            title="因子样本外验证",
            uri=f"/factor-research?run_id={run_id}",
            payload=result,
        )
        updated = store.update_research_run(
            run_id,
            {
                "status": "succeeded",
                "summary": {FACTOR_RESEARCH_MODULE: _factor_summary(result)},
                "error": None,
            },
        )
    else:
        updated = store.update_research_run(
            run_id,
            {
                "status": "failed",
                "summary": {FACTOR_RESEARCH_MODULE: _factor_summary(result)},
                "error": result.get("error"),
            },
        )
    return {
        **result,
        "run_id": run_id,
        "saved": True,
        "saved_at": (updated or run).get("updated_at"),
    }


def list_factor_research_runs(
    *, symbol: str | None = None, limit: int = 20, cursor: str | None = None
) -> dict:
    normalized = symbol.strip().upper() if symbol else None
    page = store.list_research_runs_page(
        limit=limit,
        symbol=normalized,
        module=FACTOR_RESEARCH_MODULE,
        cursor=cursor,
    )
    return {
        "ok": True,
        "runs": page["items"],
        "total": page["total"],
        "next_cursor": page["next_cursor"],
    }


def get_factor_research_run(run_id: str) -> dict | None:
    run = store.get_research_run(run_id)
    if run is None or FACTOR_RESEARCH_MODULE not in run.get("modules", []):
        return None
    evidence = run.get("evidence", [])
    statistical = next(
        (item for item in reversed(evidence) if item.get("kind") == FACTOR_RESULT_EVIDENCE),
        None,
    )
    ai_evidence = next(
        (item for item in reversed(evidence) if item.get("kind") == FACTOR_AI_EVIDENCE),
        None,
    )
    run_summary = {key: value for key, value in run.items() if key != "evidence"}
    result = dict(statistical["payload"]) if statistical else None
    if result is not None:
        result.update({"run_id": run_id, "saved": True, "saved_at": run["updated_at"]})
    ai_review = dict(ai_evidence["payload"]) if ai_evidence else None
    if ai_review is not None:
        ai_review.update({"run_id": run_id, "saved": True})
    return {"ok": True, "run": run_summary, "result": result, "ai_review": ai_review}


def _factor_run_for_review(req: FactorAiReviewRequest) -> tuple[dict[str, Any] | None, str | None]:
    if not req.run_id:
        return run_factor_research(FactorResearchRequest(**_request_payload(req))), None
    detail = get_factor_research_run(req.run_id)
    if detail is None or detail.get("result") is None:
        return None, "因子研究记录不存在或没有可复核的统计结果"
    expected = (detail["run"].get("input") or {}).get(FACTOR_RESEARCH_MODULE, {})
    if expected != _request_payload(req):
        return None, "AI 复核参数与已保存的因子研究记录不一致"
    return detail["result"], None


def _save_ai_outcome(run_id: str, response: dict[str, Any]) -> None:
    run = store.get_research_run(run_id)
    if run is None:
        return
    summary = dict(run.get("summary") or {})
    if response.get("ok"):
        review = response.get("review") or {}
        meta = response.get("meta") or {}
        store.add_research_evidence(
            run_id=run_id,
            kind=FACTOR_AI_EVIDENCE,
            source=str(meta.get("model") or meta.get("provider") or "configured_llm"),
            title="AI 科研复核",
            uri=f"/factor-research?run_id={run_id}",
            payload=response,
        )
        summary[FACTOR_AI_EVIDENCE] = {
            "ok": True,
            "verdict": review.get("verdict"),
            "confidence": review.get("confidence"),
            "model": meta.get("model"),
            "input_fingerprint": meta.get("input_fingerprint"),
            "statistical_conclusions_locked": meta.get("statistical_conclusions_locked"),
        }
        store.update_research_run(
            run_id, {"status": "succeeded", "summary": summary, "error": None}
        )
        return
    summary[FACTOR_AI_EVIDENCE] = {"ok": False, "error": response.get("error")}
    store.update_research_run(
        run_id,
        {"status": "partial", "summary": summary, "error": response.get("error")},
    )


def review_factor_research(req: FactorAiReviewRequest) -> dict:
    """Review a saved server snapshot, or rebuild one for backward-compatible callers."""
    result, context_error = _factor_run_for_review(req)
    if context_error:
        return {"ok": False, "error": context_error, "run_id": req.run_id}
    if result is None or not result.get("ok"):
        return result or {"ok": False, "error": "因子研究结果不可用"}
    try:
        response = run_ai_review(result, focus=req.review_focus)
    except Exception as exc:  # noqa: BLE001 - normalize provider/configuration failures for the UI
        error_text = str(exc).strip()
        if "timed out" in error_text.lower() or "timeout" in type(exc).__name__.lower():
            response = {
                "ok": False,
                "error": (
                    f"AI 高级推理超过 {AI_REVIEW_TIMEOUT_SECONDS} 秒，请检查模型网关后重试；"
                    "本次统计结论未受影响"
                ),
            }
        else:
            response = {"ok": False, "error": f"AI 科研复核失败: {exc}"}
    if req.run_id:
        _save_ai_outcome(req.run_id, response)
        response = {**response, "run_id": req.run_id, "saved": True}
    return response
