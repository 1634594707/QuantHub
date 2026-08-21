from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from apps.api import store

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="quanthub-analysis")
_submit_lock = threading.Lock()


def _event_time(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        numeric = float(value)
        # Offline A-share parquet files preserve an ordinal bar sequence
        # (typically ~1-2 million), not Unix time. Treat it as a captured-now
        # price point instead of fabricating a 1970 timestamp for valuation.
        if 0 < numeric < 100_000_000:
            return datetime.now(UTC)
        seconds = numeric / 1000 if numeric > 10_000_000_000 else numeric
        return datetime.fromtimestamp(seconds, UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _fingerprint(kind: str, symbol: str, market: str, timeframe: str, request: dict) -> str:
    canonical = json.dumps(
        {
            "kind": kind,
            "symbol": symbol,
            "market": market,
            "timeframe": timeframe,
            "request": request,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def submit_task(
    *,
    kind: str,
    symbol: str,
    market: str,
    timeframe: str,
    payload: dict[str, Any],
    timeout_seconds: int,
    attempt: int = 1,
    parent_task_id: str | None = None,
    owner_id: str = "local-user",
) -> tuple[dict, bool]:
    request = {**payload, "timeout_seconds": timeout_seconds}
    fingerprint = _fingerprint(kind, symbol, market, timeframe, request)
    with _submit_lock:
        active = store.find_active_analysis_task(fingerprint, owner_id=owner_id)
        if active is not None:
            active = refresh_timeout(active)
            if active["status"] in {"queued", "running"}:
                return active, True
        task = store.create_analysis_task(
            kind=kind,
            symbol=symbol,
            market=market,
            timeframe=timeframe,
            fingerprint=fingerprint,
            request=request,
            attempt=attempt,
            parent_task_id=parent_task_id,
            owner_id=owner_id,
        )
    _executor.submit(_execute_task, task["id"])
    return task, False


def _run_analysis(task: dict) -> dict[str, Any]:
    request = {key: value for key, value in task["request"].items() if key != "timeout_seconds"}
    if task["kind"] == "evaluation":
        return _run_evaluation(task, request)
    if task["kind"] == "pa":
        from apps.api.domains.strategies.service import pa_analyze

        return pa_analyze(
            symbol=task["symbol"],
            timeframe=task["timeframe"],
            market=task["market"],
            research_run_id=request.get("research_run_id"),
            owner_id=str(task.get("owner_id") or "local-user"),
        )
    if task["kind"] == "news":
        from apps.api.domains.news.service import analyze as analyze_news

        return analyze_news(
            symbol=task["symbol"],
            market=task["market"],
            timeframe=task["timeframe"],
            limit=int(request.get("limit", 20)),
            use_api=bool(request.get("use_api", True)),
            research_run_id=request.get("research_run_id"),
            owner_id=str(task.get("owner_id") or "local-user"),
        )
    if task["kind"] == "ensemble":
        from apps.api.domains.ensemble.schemas import EnsembleRequest
        from apps.api.domains.ensemble.service import predict as ensemble_predict

        req = EnsembleRequest(
            symbol=task["symbol"],
            market=task["market"],
            timeframe=task["timeframe"],
            limit=int(request.get("limit", 200)),
            research_run_id=request.get("research_run_id"),
        )
        return ensemble_predict(req, owner_id=str(task.get("owner_id") or "local-user"))
    return {"ok": False, "error": f"未知分析类型: {task['kind']}"}


def _run_evaluation(task: dict, request: dict[str, Any]) -> dict[str, Any]:
    from apps.api.domains.evaluation.service import (
        DEFAULT_METHODS,
        DEFAULT_STRATEGY_LENSES,
        VALID_METHODS,
        VALID_STRATEGY_LENSES,
        evaluate_market,
    )
    from apps.api.domains.instrument import service as instrument_service
    from apps.api.domains.market.service import fetch_kline
    from apps.api.domains.research.service import (
        add_evidence,
        complete_module,
        fail_module,
        snapshot_hash,
    )

    modules = [
        module
        for module in request.get("modules", ["market", "news", "pa", "ensemble"])
        if module
        in {
            "market",
            "news",
            "pa",
            "ensemble",
            "fundamentals",
            "valuation",
            "announcements",
            "macro",
        }
    ]
    modules = list(dict.fromkeys(modules)) or ["market", "news", "pa", "ensemble"]
    evaluation_profile = str(request.get("evaluation_profile", "balanced"))
    if evaluation_profile not in {"quick", "balanced", "comprehensive"}:
        evaluation_profile = "balanced"
    requested_methods = request.get("market_methods", DEFAULT_METHODS)
    if not isinstance(requested_methods, list):
        requested_methods = list(DEFAULT_METHODS)
    market_methods = list(
        dict.fromkeys(method for method in requested_methods if method in VALID_METHODS)
    ) or list(DEFAULT_METHODS)
    requested_lenses = request.get("strategy_lenses", DEFAULT_STRATEGY_LENSES)
    if not isinstance(requested_lenses, list):
        requested_lenses = list(DEFAULT_STRATEGY_LENSES)
    strategy_lenses = list(
        dict.fromkeys(lens for lens in requested_lenses if lens in VALID_STRATEGY_LENSES)
    ) or list(DEFAULT_STRATEGY_LENSES)
    instrument = instrument_service.resolve_strict(task["symbol"], task["market"])
    resume_run_id = request.get("research_run_id")
    run = store.get_research_run(str(resume_run_id)) if resume_run_id else None
    if run is not None and run.get("owner_id") != task.get("owner_id"):
        run = None
    if run is None:
        run = store.create_research_run(
            symbol=instrument.code,
            market=instrument.market,
            timeframe=task["timeframe"],
            modules=modules,
            input_data={
                "evaluation": True,
                "modules": modules,
                "evaluation_profile": evaluation_profile,
                "market_methods": market_methods,
                "strategy_lenses": strategy_lenses,
                "research_mode": str(request.get("research_mode", "investor")),
                "holding_status": str(request.get("holding_status", "not_held")),
            },
            instrument_id=instrument.instrument_id,
            owner_id=str(task.get("owner_id") or "local-user"),
        )
    run_id = str(run["id"])
    store.update_research_run(run_id, {"status": "running", "error": None})
    steps: dict[str, dict[str, Any]] = {
        module: {"status": "pending", "error": None} for module in modules
    }

    def save_progress(current: str | None = None) -> None:
        store.update_analysis_task(
            task["id"],
            {
                "result": {
                    "research_run_id": run_id,
                    "current_step": current,
                    "steps": steps,
                }
            },
        )

    save_progress()
    errors: list[str] = []
    succeeded = 0
    market_price: Decimal | None = None
    market_price_at: datetime | None = None

    for module in modules:
        current_task = store.get_analysis_task(task["id"])
        if current_task is None or current_task["status"] in {"cancelled", "timeout"}:
            terminal = current_task["status"] if current_task else "cancelled"
            store.update_research_run(
                run_id,
                {
                    "status": terminal,
                    "error": current_task["error"] if current_task else "任务已停止",
                },
            )
            return {
                "ok": False,
                "research_run_id": run_id,
                "steps": steps,
                "error": current_task["error"] if current_task else "任务已停止",
            }
        steps[module] = {"status": "running", "error": None}
        save_progress(module)

        current_task = store.get_analysis_task(task["id"])
        if current_task is None or current_task["status"] in {"cancelled", "timeout"}:
            terminal = current_task["status"] if current_task else "cancelled"
            terminal_error = current_task["error"] if current_task else "任务已停止"
            store.update_research_run(run_id, {"status": terminal, "error": terminal_error})
            return {
                "ok": False,
                "research_run_id": run_id,
                "steps": steps,
                "error": terminal_error,
            }
        try:
            if module == "market":
                market_result = fetch_kline(
                    symbol=instrument.code,
                    market=instrument.market,
                    interval=task["timeframe"],
                    limit=int(request.get("market_limit", 240)),
                )
                if not market_result.get("ok") or not market_result.get("candles"):
                    raise RuntimeError(market_result.get("error") or "行情数据为空")
                candles = market_result["candles"]
                market_price = Decimal(str(candles[-1]["c"]))
                market_price_at = _event_time(candles[-1]["t"])
                add_evidence(
                    run_id,
                    kind="market_snapshot",
                    source=str(market_result.get("source", "unknown")),
                    title=f"{instrument.code} {task['timeframe']} 行情快照",
                    payload={
                        "bars": candles,
                        "sha256": snapshot_hash(candles),
                        "count": len(candles),
                        "latest_time": candles[-1]["t"],
                    },
                )
                try:
                    quantitative = evaluate_market(
                        candles,
                        methods=market_methods,
                        strategy_lenses=strategy_lenses,
                        periods_per_year=(
                            {"1h": 8760, "1d": 365, "1w": 52}.get(task["timeframe"], 365)
                            if instrument.market == "crypto"
                            else {"1h": 252 * 4, "1d": 252, "1w": 52}.get(task["timeframe"], 252)
                        ),
                    )
                except ValueError as exc:
                    quantitative = {
                        "version": "market-evaluation-v1",
                        "methods": market_methods,
                        "strategy_lenses": strategy_lenses,
                        "data_quality": "不足",
                        "confidence": "低",
                        "metrics": {},
                        "dimensions": {},
                        "strategies": [],
                        "error": str(exc),
                    }
                add_evidence(
                    run_id,
                    kind="quantitative_evaluation",
                    source=str(quantitative.get("version", "market-evaluation-v1")),
                    title=f"{instrument.code} 可解释量化评估",
                    payload=quantitative,
                )
                complete_module(
                    run_id,
                    "market",
                    {
                        "source": market_result.get("source"),
                        "count": len(candles),
                        "latest_time": candles[-1]["t"],
                        "latest_price": candles[-1]["c"],
                        "evaluation_profile": evaluation_profile,
                        "quantitative": quantitative,
                    },
                )
            elif module == "news":
                from apps.api.domains.news.service import analyze as analyze_news

                news_result = analyze_news(
                    symbol=instrument.code,
                    market=instrument.market,
                    timeframe=task["timeframe"],
                    limit=int(request.get("news_limit", 20)),
                    use_api=bool(request.get("use_api", True)),
                    research_run_id=run_id,
                    owner_id=str(task.get("owner_id") or "local-user"),
                )
                if not news_result.get("ok"):
                    raise RuntimeError(news_result.get("error") or "新闻分析失败")
                if news_result.get("research_run_id") is None:
                    complete_module(
                        run_id, "news", {"total": 0, "degraded": True, "degraded_reason": "no_news"}
                    )
            elif module == "pa":
                from apps.api.domains.strategies.service import pa_analyze

                pa_result = pa_analyze(
                    symbol=instrument.code,
                    timeframe=task["timeframe"],
                    market=instrument.market,
                    research_run_id=run_id,
                    owner_id=str(task.get("owner_id") or "local-user"),
                )
                if not pa_result.get("ok"):
                    raise RuntimeError(pa_result.get("error") or "价格行为分析失败")
            elif module == "ensemble":
                from apps.api.domains.ensemble.schemas import EnsembleRequest
                from apps.api.domains.ensemble.service import predict as ensemble_predict

                ensemble_result = ensemble_predict(
                    EnsembleRequest(
                        symbol=instrument.code,
                        market=instrument.market,
                        timeframe=task["timeframe"],
                        limit=int(request.get("ensemble_limit", 200)),
                        research_run_id=run_id,
                    ),
                    owner_id=str(task.get("owner_id") or "local-user"),
                )
                if not ensemble_result.get("ok"):
                    raise RuntimeError(ensemble_result.get("error") or "多模型判断失败")
            elif module == "fundamentals":
                from apps.api.domains.financials.service import evaluate_fundamentals

                fundamental_result = evaluate_fundamentals(
                    instrument_id=instrument.instrument_id,
                    market=instrument.market,
                )
                add_evidence(
                    run_id,
                    kind="fundamental_snapshot",
                    source=str(fundamental_result["provenance"]["source"]),
                    title=f"{instrument.code} 点时基本面快照",
                    payload=fundamental_result,
                    uri=fundamental_result["provenance"].get("source_url"),
                )
                complete_module(run_id, "fundamentals", fundamental_result)
            elif module == "valuation":
                from apps.api.domains.financials.service import evaluate_valuation

                if market_price is None or market_price_at is None:
                    current_run = store.get_research_run(run_id) or {}
                    market_summary = (current_run.get("summary") or {}).get("market") or {}
                    latest_price = market_summary.get("latest_price")
                    market_evidence = next(
                        (
                            item
                            for item in reversed(current_run.get("evidence") or [])
                            if item.get("kind") == "market_snapshot"
                        ),
                        None,
                    )
                    if latest_price is not None and market_evidence is not None:
                        market_price = Decimal(str(latest_price))
                        market_price_at = datetime.fromtimestamp(
                            float(market_evidence["captured_at"]), UTC
                        )
                if market_price is None or market_price_at is None:
                    raise RuntimeError("估值模块缺少可复核的价格时点")
                valuation_result = evaluate_valuation(
                    instrument_id=instrument.instrument_id,
                    market=instrument.market,
                    price=market_price,
                    price_at=market_price_at,
                )
                add_evidence(
                    run_id,
                    kind="valuation_snapshot",
                    source=str(valuation_result["provenance"]["source"]),
                    title=f"{instrument.code} 点时估值快照",
                    payload=valuation_result,
                    uri=valuation_result["provenance"].get("source_url"),
                )
                complete_module(run_id, "valuation", valuation_result)
            elif module == "announcements":
                from apps.api.domains.research_data.service import evaluate_company_events

                evaluate_company_events(
                    instrument_id=instrument.instrument_id,
                    symbol=instrument.code,
                    market=instrument.market,
                    run_id=run_id,
                    limit=int(request.get("announcement_limit", 30)),
                )
            elif module == "macro":
                from apps.api.domains.research_data.service import evaluate_macro_events

                evaluate_macro_events(
                    instrument_id=instrument.instrument_id,
                    run_id=run_id,
                    owner_id=str(task.get("owner_id") or "local-user"),
                    market=instrument.market,
                )
            steps[module] = {"status": "succeeded", "error": None}
            succeeded += 1
        except Exception as exc:  # noqa: BLE001 - 单模块失败不能中断其余评估模块
            error = str(exc)
            steps[module] = {"status": "failed", "error": error}
            errors.append(f"{module}: {error}")
            fail_module(run_id, module, error)
        save_progress(module)

    final_run = store.get_research_run(run_id) or {}
    final_summary = final_run.get("summary", {})
    all_modules = final_run.get("modules", modules)
    successful_modules = [
        module
        for module in all_modules
        if module in final_summary
        and not (
            isinstance(final_summary[module], dict) and final_summary[module].get("ok") is False
        )
    ]
    failed_modules = [
        module
        for module in all_modules
        if isinstance(final_summary.get(module), dict) and final_summary[module].get("ok") is False
    ]
    final_status = (
        "succeeded"
        if len(successful_modules) == len(all_modules) and not failed_modules
        else "partial"
        if successful_modules
        else "failed"
    )
    error_text = "；".join(errors) if errors else None
    from apps.api.domains.research.service import persist_research_decision

    persist_research_decision(run_id)
    store.update_research_run(run_id, {"status": final_status, "error": error_text})
    return {
        "ok": bool(successful_modules),
        "partial": final_status == "partial",
        "research_run_id": run_id,
        "steps": steps,
        "error": error_text,
    }


def _execute_task(task_id: str) -> None:
    task = store.get_analysis_task(task_id)
    if task is None or task["status"] != "queued":
        return
    started = time.time()
    store.update_analysis_task(
        task_id,
        {"status": "running", "started_at": started, "error": None},
    )
    try:
        result = _run_analysis(task)
        current = store.get_analysis_task(task_id)
        if current is None or current["status"] in {"cancelled", "timeout"}:
            return
        finished = time.time()
        status = "succeeded" if result.get("ok", True) else "failed"
        store.update_analysis_task(
            task_id,
            {
                "status": status,
                "result": result,
                "error": result.get("error") if status == "failed" else None,
                "finished_at": finished,
                "duration_ms": round((finished - started) * 1000),
            },
        )
    except Exception as exc:  # noqa: BLE001 - 后台任务边界统一持久化未处理异常
        finished = time.time()
        current = store.get_analysis_task(task_id)
        if current is not None and current["status"] not in {"cancelled", "timeout"}:
            store.update_analysis_task(
                task_id,
                {
                    "status": "failed",
                    "error": str(exc),
                    "finished_at": finished,
                    "duration_ms": round((finished - started) * 1000),
                },
            )


def refresh_timeout(task: dict) -> dict:
    if task["status"] not in {"queued", "running"}:
        return task
    timeout_seconds = int(task["request"].get("timeout_seconds", 90))
    clock_started = task["started_at"] or task["created_at"]
    if time.time() - clock_started <= timeout_seconds:
        return task
    finished = time.time()
    error = (
        f"任务排队超过 {timeout_seconds} 秒"
        if task["status"] == "queued"
        else f"任务超过 {timeout_seconds} 秒"
    )
    updated = (
        store.update_analysis_task(
            task["id"],
            {
                "status": "timeout",
                "error": error,
                "finished_at": finished,
                "duration_ms": round((finished - clock_started) * 1000),
            },
        )
        or task
    )
    _sync_evaluation_terminal(updated)
    return updated


def cancel_task(task: dict) -> dict:
    if task["status"] not in {"queued", "running"}:
        return task
    finished = time.time()
    started = task["started_at"] or task["created_at"]
    updated = (
        store.update_analysis_task(
            task["id"],
            {
                "status": "cancelled",
                "error": "用户取消",
                "finished_at": finished,
                "duration_ms": round((finished - started) * 1000),
            },
        )
        or task
    )
    _sync_evaluation_terminal(updated)
    return updated


def _sync_evaluation_terminal(task: dict) -> None:
    if task.get("kind") != "evaluation" or task.get("status") not in {"cancelled", "timeout"}:
        return
    result = task.get("result")
    run_id = result.get("research_run_id") if isinstance(result, dict) else None
    if not run_id or store.get_research_run(str(run_id)) is None:
        return
    store.update_research_run(str(run_id), {"status": task["status"], "error": task.get("error")})


def resume_pending_tasks() -> int:
    """Requeue persisted unfinished tasks after an API process restart."""
    pending = [
        *store.list_analysis_tasks(limit=500, status="queued"),
        *store.list_analysis_tasks(limit=500, status="running"),
    ]
    for task in pending:
        if task["status"] == "running":
            store.update_analysis_task(
                task["id"],
                {
                    "status": "queued",
                    "started_at": None,
                    "error": "服务重启后已重新排队",
                },
            )
        _executor.submit(_execute_task, task["id"])
    return len(pending)
