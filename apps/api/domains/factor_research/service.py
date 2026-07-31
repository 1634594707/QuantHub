from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pandas as pd

from apps.api import store
from apps.api.domains.instrument import service as instrument_service
from apps.api.domains.research.service import dataframe_snapshot, snapshot_hash
from core.cross_sectional_research import (
    CrossSectionConfig,
    InsufficientCrossSectionData,
    analyze_cross_sectional_factors,
)
from core.data_feed.factory import get_data_source
from core.data_feed.quality import assess_ohlcv
from core.factor_research import InsufficientFactorData, ResearchConfig, analyze_factors

from .ai_review import AI_REVIEW_TIMEOUT_SECONDS, run_ai_review
from .schemas import (
    CrossSectionResearchRequest,
    FactorAiReviewRequest,
    FactorResearchRequest,
    FactorUniverseCreate,
    FactorUniverseMemberUpsert,
)

logger = logging.getLogger(__name__)

FACTOR_RESEARCH_MODULE = "factor_research"
FACTOR_RESULT_EVIDENCE = "factor_research_result"
FACTOR_AI_EVIDENCE = "factor_ai_review"
FACTOR_MARKET_SNAPSHOT_EVIDENCE = "market_snapshot"
CROSS_SECTION_MODULE = "cross_sectional_factor_research"
CROSS_SECTION_RESULT_EVIDENCE = "cross_sectional_factor_result"
UNIVERSE_SNAPSHOT_EVIDENCE = "universe_snapshot"


def _periods_per_year(market: str, interval: str) -> int:
    normalized = interval.lower()
    if market == "crypto":
        return {"1h": 8_760, "4h": 2_190, "1d": 365}.get(normalized, 365)
    if market == "mt5":
        return {"1h": 6_240, "4h": 1_560, "1d": 252}.get(normalized, 252)
    return {"1h": 1_512, "4h": 378, "1d": 252, "1w": 52}.get(normalized, 252)


def create_factor_universe(req: FactorUniverseCreate) -> dict:
    try:
        universe = store.create_factor_universe(req.name, req.market, req.description)
    except sqlite3.IntegrityError:
        return {"ok": False, "error": "股票池名称已存在"}
    return {"ok": True, "universe": universe}


def list_factor_universes(market: str | None = None) -> dict:
    universes = store.list_factor_universes(market=market)
    return {"ok": True, "count": len(universes), "universes": universes}


def upsert_factor_universe_member(universe_id: str, req: FactorUniverseMemberUpsert) -> dict:
    universe = store.get_factor_universe(universe_id)
    if universe is None:
        return {"ok": False, "error": "股票池不存在"}
    try:
        instrument = instrument_service.resolve_strict(req.symbol, universe["market"])
    except instrument_service.InstrumentResolutionError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        member = store.upsert_factor_universe_member(
            universe_id=universe_id,
            instrument_id=instrument.instrument_id,
            symbol=instrument.code,
            effective_from=req.effective_from.isoformat(),
            effective_to=req.effective_to.isoformat() if req.effective_to else None,
            status=req.status,
            industry=req.industry,
            market_cap=req.market_cap,
            beta=req.beta,
            is_st=req.is_st,
            listed_at=req.listed_at.isoformat() if req.listed_at else None,
            delisted_at=req.delisted_at.isoformat() if req.delisted_at else None,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "member": member}


def list_factor_universe_members(universe_id: str, as_of: date | None = None) -> dict:
    universe = store.get_factor_universe(universe_id)
    if universe is None:
        return {"ok": False, "error": "股票池不存在"}
    members = store.list_factor_universe_members(
        universe_id,
        active_on=as_of.isoformat() if as_of else None,
    )
    return {
        "ok": True,
        "universe": universe,
        "count": len(members),
        "members": members,
    }


def run_cross_sectional_research(req: CrossSectionResearchRequest) -> dict:
    universe = store.get_factor_universe(req.universe_id)
    if universe is None:
        return {"ok": False, "error": "股票池不存在"}
    if (
        req.transaction_cost_profile is not None
        and req.transaction_cost_profile.market != universe["market"]
    ):
        return {"ok": False, "error": "transaction_cost_profile.market 与股票池市场不一致"}
    start_text = req.start_date.isoformat() if req.start_date else None
    end_text = req.end_date.isoformat() if req.end_date else None
    members = store.list_factor_universe_members(
        req.universe_id,
        start_date=start_text,
        end_date=end_text,
    )
    if not members:
        return {"ok": False, "error": "所选日期区间没有股票池成分记录"}
    request_payload = req.model_dump(mode="json", exclude={"run_id"}, exclude_none=True)
    run = store.get_research_run(req.run_id) if req.run_id else None
    if req.run_id:
        if run is None or CROSS_SECTION_MODULE not in run.get("modules", []):
            return {"ok": False, "error": "待恢复的横截面研究记录不存在"}
        saved_request = (run.get("input") or {}).get(CROSS_SECTION_MODULE)
        if saved_request != request_payload:
            return {"ok": False, "error": "恢复请求与原横截面研究参数不一致"}
    else:
        run = store.create_research_run(
            symbol=f"UNIVERSE:{req.universe_id}",
            market=universe["market"],
            timeframe=req.interval,
            modules=[CROSS_SECTION_MODULE],
            input_data={CROSS_SECTION_MODULE: request_payload},
            instrument_id=f"universe:{req.universe_id}",
        )
    run_id = str(run["id"])
    store.update_research_run(run_id, {"status": "running"})
    universe_payload = {
        "universe": universe,
        "members": members,
        "sha256": snapshot_hash(members),
        "start_date": start_text,
        "end_date": end_text,
    }
    if not req.run_id:
        store.add_research_evidence(
            run_id=run_id,
            kind=UNIVERSE_SNAPSHOT_EVIDENCE,
            source="factor_universes",
            title=f"{universe['name']} 历史成分快照",
            uri=f"/factor-research?cross_section_run_id={run_id}",
            payload=universe_payload,
        )
    try:
        source = get_data_source(universe["market"])
    except Exception as exc:  # noqa: BLE001 - persist source initialization failures
        error = f"初始化 {universe['market']} 行情源失败: {exc}"
        store.update_research_run(run_id, {"status": "failed", "error": error})
        return {"ok": False, "error": error, "run_id": run_id, "failures": []}
    start = datetime.combine(req.start_date, time.min) if req.start_date else None
    end = datetime.combine(req.end_date, time.max) if req.end_date else None
    frames: dict[str, pd.DataFrame] = {}
    if req.run_id:
        for item in run.get("evidence") or []:
            if item.get("kind") != FACTOR_MARKET_SNAPSHOT_EVIDENCE:
                continue
            payload = item.get("payload") or {}
            symbol = payload.get("symbol")
            bars = payload.get("bars")
            columns = payload.get("columns")
            if (
                not isinstance(symbol, str)
                or not isinstance(bars, list)
                or not isinstance(columns, list)
                or payload.get("sha256") != snapshot_hash(bars)
            ):
                continue
            restored = pd.DataFrame(bars, columns=columns)
            if "datetime" in restored.columns:
                restored["datetime"] = pd.to_datetime(restored["datetime"], errors="coerce")
            restored.attrs["_source"] = payload.get("source", item.get("source", "snapshot"))
            frames[symbol] = restored
    failures: list[dict[str, Any]] = []
    symbols = sorted({str(member["symbol"]) for member in members})
    for symbol in (item for item in symbols if item not in frames):
        last_error = ""
        for attempt in range(1, req.retry_attempts + 1):
            try:
                frame = source.get_kline(
                    symbol,
                    req.interval,
                    start=start,
                    end=end,
                    limit=req.limit,
                )
                quality = assess_ohlcv(frame)
                if not quality.usable:
                    raise ValueError(quality.reason or quality.status)
                frames[symbol] = frame
                snapshot = dataframe_snapshot(frame)
                snapshot["symbol"] = symbol
                store.add_research_evidence(
                    run_id=run_id,
                    kind=FACTOR_MARKET_SNAPSHOT_EVIDENCE,
                    source=str(frame.attrs.get("_source", getattr(source, "name", "unknown"))),
                    title=f"{symbol} 横截面研究行情快照",
                    uri=f"/factor-research?cross_section_run_id={run_id}",
                    payload=snapshot,
                )
                break
            except Exception as exc:  # noqa: BLE001 - each symbol has bounded retries
                last_error = str(exc)
                if attempt == req.retry_attempts:
                    failures.append({"symbol": symbol, "attempts": attempt, "error": last_error})
    try:
        result = analyze_cross_sectional_factors(
            frames,
            members,
            CrossSectionConfig(
                market=universe["market"],
                factor_key=req.factor_key,
                horizon=req.horizon,
                quantiles=req.quantiles,
                min_assets=req.min_assets,
                periods_per_year=_periods_per_year(universe["market"], req.interval),
                transaction_cost_bps=req.transaction_cost_bps,
                participation_rate=req.participation_rate,
                neutralize_industry=req.neutralize_industry,
                neutralize_market_cap=req.neutralize_market_cap,
                neutralize_beta=req.neutralize_beta,
            ),
        )
    except (InsufficientCrossSectionData, ValueError) as exc:
        error = str(exc)
        store.update_research_run(
            run_id,
            {
                "status": "failed",
                "summary": {
                    CROSS_SECTION_MODULE: {
                        "ok": False,
                        "loaded_symbols": len(frames),
                        "failed_symbols": len(failures),
                    }
                },
                "error": error,
            },
        )
        return {
            "ok": False,
            "error": error,
            "run_id": run_id,
            "failures": failures,
        }
    result.update(
        {
            "ok": True,
            "run_id": run_id,
            "universe": universe,
            "transaction_cost_profile": (
                req.transaction_cost_profile.model_dump(mode="json")
                if req.transaction_cost_profile
                else None
            ),
            "loaded_symbols": len(frames),
            "failed_symbols": len(failures),
            "failures": failures,
        }
    )
    store.add_research_evidence(
        run_id=run_id,
        kind=CROSS_SECTION_RESULT_EVIDENCE,
        source=str(result["engine_version"]),
        title=f"{universe['name']} 横截面因子验证",
        uri=f"/factor-research?cross_section_run_id={run_id}",
        payload=result,
    )
    final_status = "partial" if failures else "succeeded"
    store.update_research_run(
        run_id,
        {
            "status": final_status,
            "summary": {
                CROSS_SECTION_MODULE: {
                    "ok": True,
                    **result["summary"],
                    "factor_key": req.factor_key,
                    "factor_status": result["factor"]["status"],
                    "universe_id": req.universe_id,
                    "loaded_symbols": len(frames),
                    "failed_symbols": len(failures),
                }
            },
            "error": "；".join(f"{item['symbol']}: {item['error']}" for item in failures) or None,
        },
    )
    return result


def cross_market_factor_status(factor_key: str) -> dict:
    required_markets = ["a_shares", "us_stocks", "crypto", "mt5"]
    rows: list[dict[str, Any]] = []
    for market in required_markets:
        market_runs = store.list_research_runs_page(
            limit=1,
            market=market,
            module=CROSS_SECTION_MODULE,
            cross_section_factor_key=factor_key,
        )["items"]
        latest = market_runs[0] if market_runs else None
        summary = (latest.get("summary") or {}).get(CROSS_SECTION_MODULE, {}) if latest else {}
        factor_status = summary.get("factor_status")
        passed = bool(
            latest
            and latest.get("status") in {"succeeded", "partial"}
            and factor_status == "usable"
            and int(summary.get("dates") or 0) >= 20
            and int(summary.get("minimum_valid_assets") or 0) >= 3
        )
        rows.append(
            {
                "market": market,
                "state": "passed" if passed else "failed" if latest else "missing",
                "run_id": latest.get("id") if latest else None,
                "run_status": latest.get("status") if latest else None,
                "factor_status": factor_status,
                "dates": summary.get("dates"),
                "minimum_valid_assets": summary.get("minimum_valid_assets"),
                "rank_ic_mean": summary.get("rank_ic_mean"),
                "coverage": summary.get("coverage"),
                "updated_at": latest.get("updated_at") if latest else None,
            }
        )
    validated = all(row["state"] == "passed" for row in rows)
    return {
        "ok": True,
        "factor_key": factor_key,
        "trading_validation_status": "passed" if validated else "insufficient_evidence",
        "trading_validation_passed": validated,
        "required_markets": required_markets,
        "rows": rows,
        "rule": "四个市场最新横截面结果均为 usable，且每个市场至少 20 个有效日期、每日最少 3 个有效标的",
    }


def _saved_factor_result(run: dict) -> dict | None:
    detail = store.get_research_run(str(run["id"]))
    if detail is None:
        return None
    evidence = next(
        (
            item
            for item in reversed(detail.get("evidence") or [])
            if item.get("kind") == FACTOR_RESULT_EVIDENCE
        ),
        None,
    )
    payload = evidence.get("payload") if evidence else None
    return payload if isinstance(payload, dict) else None


def factor_status_matrix(factor_key: str) -> dict:
    """统一输出窗口、横截面和四市场门禁状态及其原始运行引用。"""
    window_rows: list[dict] = []
    factor_runs = store.list_research_runs_page(
        limit=200, module=FACTOR_RESEARCH_MODULE, archived=False
    )["items"]
    for run in factor_runs:
        result = _saved_factor_result(run)
        factor = next(
            (item for item in (result or {}).get("factors", []) if item.get("key") == factor_key),
            None,
        )
        if factor is None:
            continue
        windows = factor.get("windows") if isinstance(factor.get("windows"), list) else []
        window_rows = [
            {
                "dimension": "window",
                "key": str(item.get("fold")),
                "label": f"窗口 {item.get('fold')}",
                "state": "passed" if item.get("status") == "pass" else "failed",
                "rule": "训练样本至少 40、验证样本至少 20、方向调整后验证 IC >= 0.03 且命中率 >= 0.5",
                "evidence": item,
                "run_id": run["id"],
                "updated_at": run["updated_at"],
            }
            for item in windows
        ]
        if window_rows:
            break

    market_status = cross_market_factor_status(factor_key)
    cross_symbol_rows = [
        {
            "dimension": "cross_symbol",
            "key": row["market"],
            "label": f"{row['market']} 横截面",
            "state": row["state"],
            "rule": "最新横截面因子状态为 usable，至少 20 个有效日期且每日最少 3 个有效标的",
            "evidence": {
                "factor_status": row["factor_status"],
                "dates": row["dates"],
                "minimum_valid_assets": row["minimum_valid_assets"],
                "rank_ic_mean": row["rank_ic_mean"],
                "coverage": row["coverage"],
            },
            "run_id": row["run_id"],
            "updated_at": row["updated_at"],
        }
        for row in market_status["rows"]
    ]
    market_rows = [
        {
            "dimension": "market",
            "key": row["market"],
            "label": row["market"],
            "state": row["state"],
            "rule": market_status["rule"],
            "evidence": {"run_id": row["run_id"], "run_status": row["run_status"]},
            "run_id": row["run_id"],
            "updated_at": row["updated_at"],
        }
        for row in market_status["rows"]
    ]
    rows = [*window_rows, *cross_symbol_rows, *market_rows]
    return {
        "ok": True,
        "factor_key": factor_key,
        "dimensions": ["window", "cross_symbol", "market"],
        "rows": rows,
        "counts": {
            state: sum(item["state"] == state for item in rows)
            for state in ("passed", "failed", "missing")
        },
    }


def factor_research_attention(*, stale_hours: float = 24.0, limit: int = 100) -> dict:
    """列出首页需要复验、已失效和数据过期的最新单标的因子研究。"""
    now = datetime.now(UTC).timestamp()
    latest: dict[tuple[str, str, str], dict] = {}
    for run in store.list_research_runs_page(
        limit=500, module=FACTOR_RESEARCH_MODULE, archived=False
    )["items"]:
        key = (run["market"], run["symbol"], run["timeframe"])
        latest.setdefault(key, run)
    items: list[dict] = []
    for run in latest.values():
        result = _saved_factor_result(run)
        if result is None:
            continue
        factors = result.get("factors") if isinstance(result.get("factors"), list) else []
        rejected = [item.get("key") for item in factors if item.get("status") == "reject"]
        watch = [item.get("key") for item in factors if item.get("status") == "watch"]
        inconsistent = [
            item.get("key") for item in factors if item.get("multi_window_consistent") is False
        ]
        age_hours = max(0.0, (now - float(run["updated_at"])) / 3600)
        states: list[str] = []
        if watch or inconsistent:
            states.append("needs_revalidation")
        if rejected:
            states.append("invalidated")
        if age_hours >= stale_hours:
            states.append("data_stale")
        if not states:
            continue
        items.append(
            {
                "run_id": run["id"],
                "symbol": run["symbol"],
                "market": run["market"],
                "timeframe": run["timeframe"],
                "states": states,
                "updated_at": run["updated_at"],
                "age_hours": round(age_hours, 4),
                "evidence": {
                    "watch_factors": watch,
                    "inconsistent_factors": inconsistent,
                    "rejected_factors": rejected,
                },
            }
        )
    items.sort(key=lambda item: (len(item["states"]), item["updated_at"]), reverse=True)
    items = items[:limit]
    return {
        "ok": True,
        "stale_hours": stale_hours,
        "rules": {
            "needs_revalidation": "存在 watch 状态或多窗口一致性失败的因子",
            "invalidated": "存在 reject 状态因子",
            "data_stale": f"研究更新时间距当前至少 {stale_hours:g} 小时",
        },
        "counts": {
            state: sum(state in item["states"] for item in items)
            for state in ("needs_revalidation", "invalidated", "data_stale")
        },
        "items": items,
    }


def get_cross_sectional_research_run(run_id: str) -> dict | None:
    run = store.get_research_run(run_id)
    if run is None or CROSS_SECTION_MODULE not in run.get("modules", []):
        return None
    evidence = run.get("evidence") or []
    result_evidence = next(
        (item for item in reversed(evidence) if item.get("kind") == CROSS_SECTION_RESULT_EVIDENCE),
        None,
    )
    universe_evidence = next(
        (item for item in reversed(evidence) if item.get("kind") == UNIVERSE_SNAPSHOT_EVIDENCE),
        None,
    )
    market_snapshots = [
        item for item in evidence if item.get("kind") == FACTOR_MARKET_SNAPSHOT_EVIDENCE
    ]
    run_summary = {key: value for key, value in run.items() if key != "evidence"}
    return {
        "ok": True,
        "run": run_summary,
        "result": result_evidence.get("payload") if result_evidence else None,
        "universe_snapshot": universe_evidence.get("payload") if universe_evidence else None,
        "market_snapshots": market_snapshots,
    }


def run_factor_research(req: FactorResearchRequest, *, capture_snapshot: bool = False) -> dict:
    try:
        source = get_data_source(req.market)
        start = datetime.combine(req.start_date, time.min) if req.start_date else None
        end = datetime.combine(req.end_date, time.max) if req.end_date else None
        frame = source.get_kline(
            req.symbol,
            req.interval,
            start=start,
            end=end,
            limit=req.limit,
        )
    except Exception as exc:  # noqa: BLE001 - adapters may raise third-party transport errors
        return {"ok": False, "error": f"获取 K 线失败: {exc}"}
    if req.start_date or req.end_date:
        if "datetime" not in frame.columns:
            return {"ok": False, "error": "所选数据源未返回 datetime，无法执行日期区间研究"}
        timestamps = pd.to_datetime(frame["datetime"], errors="coerce", utc=True).dt.tz_convert(
            None
        )
        if not timestamps.notna().any():
            return {"ok": False, "error": "所选数据源没有可用 datetime，无法执行日期区间研究"}
        attributes = dict(frame.attrs)
        if start is not None:
            frame = frame.loc[timestamps.ge(start)]
            timestamps = timestamps.loc[frame.index]
        if end is not None:
            frame = frame.loc[timestamps.le(end)]
        frame = frame.copy()
        frame.attrs.update(attributes)
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
                walk_forward_mode=req.walk_forward_mode,
                walk_forward_folds=req.walk_forward_folds,
            ),
        )
    except InsufficientFactorData as exc:
        return {"ok": False, "error": str(exc), "quality": quality.to_dict()}
    response = {
        "ok": True,
        "symbol": req.symbol,
        "market": req.market,
        "interval": req.interval,
        "requested_period": {
            "start_date": req.start_date.isoformat() if req.start_date else None,
            "end_date": req.end_date.isoformat() if req.end_date else None,
        },
        "source": frame.attrs.get("_source", getattr(source, "name", "unknown")),
        "quality": quality.to_dict(),
        "transaction_cost_profile": (
            req.transaction_cost_profile.model_dump(mode="json")
            if req.transaction_cost_profile
            else None
        ),
        **result,
    }
    if capture_snapshot:
        snapshot = dataframe_snapshot(frame)
        snapshot["data_fingerprint"] = result["summary"]["data_fingerprint"]
        response["_market_snapshot"] = snapshot
    return response


def _request_payload(req: FactorResearchRequest | FactorAiReviewRequest) -> dict[str, Any]:
    return req.model_dump(
        mode="json",
        exclude={"review_focus", "run_id"},
        exclude_none=True,
    )


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
        "engine_version": summary.get("engine_version"),
        "factor_formula_version": summary.get("factor_formula_version"),
        "data_fingerprint": summary.get("data_fingerprint"),
        "thresholds": summary.get("thresholds", {}),
        "walk_forward_mode": summary.get("walk_forward_mode"),
        "walk_forward_folds": summary.get("walk_forward_folds"),
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
        try:
            from apps.api.domains.incidents import repository as incident_repository

            incident_repository.observe_research_failure(
                kind="research_persistence",
                fingerprint=f"{req.market}:{req.symbol}:{req.interval}",
                error=persistence_error,
                context={"symbol": req.symbol, "market": req.market, "interval": req.interval},
            )
        except Exception:  # noqa: BLE001 - original research request must still proceed
            logger.exception("记录因子研究持久化故障失败")

    result = run_factor_research(req, capture_snapshot=True)
    market_snapshot = result.pop("_market_snapshot", None)
    if run is None:
        return {
            **result,
            "saved": False,
            "persistence_error": persistence_error or "研究记录存储不可用",
        }

    run_id = str(run["id"])
    if result.get("ok"):
        if market_snapshot:
            store.add_research_evidence(
                run_id=run_id,
                kind=FACTOR_MARKET_SNAPSHOT_EVIDENCE,
                source=str(result.get("source") or "factor_engine"),
                title="因子研究锁定行情快照",
                uri=f"/factor-research?run_id={run_id}",
                payload=market_snapshot,
            )
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
    *,
    symbol: str | None = None,
    market: str | None = None,
    interval: str | None = None,
    status: str | None = None,
    favorite: bool | None = None,
    archived: bool = False,
    tag: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    research_limit: int | None = None,
    horizon: int | None = None,
    transaction_cost_bps: float | None = None,
    walk_forward_mode: str | None = None,
    walk_forward_folds: int | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict:
    normalized = symbol.strip().upper() if symbol else None
    if created_from and created_to and created_from > created_to:
        raise ValueError("created_from 不能晚于 created_to")
    page = store.list_research_runs_page(
        limit=limit,
        symbol=normalized,
        module=FACTOR_RESEARCH_MODULE,
        market=market,
        timeframe=interval,
        cursor=cursor,
        status=status,
        favorite=favorite,
        archived=archived,
        tag=tag,
        created_from=(
            datetime.combine(created_from, time.min).timestamp() if created_from else None
        ),
        created_to=(
            datetime.combine(created_to + timedelta(days=1), time.min).timestamp()
            if created_to
            else None
        ),
        factor_limit=research_limit,
        factor_horizon=horizon,
        factor_transaction_cost_bps=transaction_cost_bps,
        factor_walk_forward_mode=walk_forward_mode,
        factor_walk_forward_folds=walk_forward_folds,
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
