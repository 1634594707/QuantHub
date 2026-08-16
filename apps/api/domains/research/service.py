from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from apps.api import store
from apps.api.domains.instrument import service as instrument_service
from core.research_decision import (
    ModuleOpinion,
    decide_research,
    decision_from_mapping,
    normalize_direction,
)
from packages.financial_data import HoldingStatus, build_action_guidance

logger = logging.getLogger(__name__)


class ResearchRunNotFoundError(LookupError):
    pass


class ResearchContextMismatchError(ValueError):
    pass


def snapshot_hash(bars: list[dict[str, Any]]) -> str:
    """Hash serialized bars using the canonical research snapshot format."""
    canonical = json.dumps(bars, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def start_module(
    *,
    symbol: str,
    market: str,
    timeframe: str,
    module: str,
    input_data: dict[str, Any],
    run_id: str | None = None,
    owner_id: str = "local-user",
) -> str:
    if run_id:
        run = store.get_research_run(run_id)
        if run is None:
            raise ResearchRunNotFoundError(run_id)
        if run.get("owner_id") != owner_id:
            raise ResearchRunNotFoundError(run_id)
        expected = (run["symbol"], run["market"], run["timeframe"])
        actual = (symbol, market, timeframe)
        if expected != actual:
            raise ResearchContextMismatchError(
                f"研究上下文不一致: run={expected}, request={actual}"
            )
        modules = list(dict.fromkeys([*run["modules"], module]))
        merged_input = {**run["input"], module: input_data}
        store.update_research_run(
            run_id,
            {"status": "running", "modules": modules, "input": merged_input, "error": None},
        )
        return run_id

    instrument = instrument_service.resolve_strict(symbol, market)
    run = store.create_research_run(
        symbol=instrument.code,
        market=instrument.market,
        timeframe=timeframe,
        modules=[module],
        input_data={module: input_data},
        instrument_id=instrument.instrument_id,
        owner_id=owner_id,
    )
    store.update_research_run(run["id"], {"status": "running"})
    return str(run["id"])


def complete_module(run_id: str, module: str, summary: dict[str, Any]) -> None:
    run = store.get_research_run(run_id)
    if run is None:
        return
    merged = {**run["summary"], module: summary}
    store.update_research_run(
        run_id,
        {"status": "succeeded", "summary": merged, "error": None},
    )


def fail_module(run_id: str, module: str, error: str) -> None:
    run = store.get_research_run(run_id)
    if run is None:
        return
    merged = {**run["summary"], module: {"ok": False, "error": error}}
    store.update_research_run(
        run_id,
        {"status": "failed", "summary": merged, "error": error},
    )


def add_evidence(
    run_id: str,
    *,
    kind: str,
    source: str,
    title: str,
    payload: dict[str, Any],
    uri: str | None = None,
) -> None:
    store.add_research_evidence(
        run_id=run_id,
        kind=kind,
        source=source,
        title=title,
        uri=uri,
        payload=payload,
    )


def dataframe_snapshot(df: pd.DataFrame) -> dict[str, Any]:
    """生成可复现、可哈希的 OHLCV 输入快照。"""
    fields = [
        field
        for field in ("datetime", "bar_time", "open", "high", "low", "close", "volume")
        if field in df.columns
    ]
    records: list[dict[str, Any]] = []
    for raw in df[fields].to_dict(orient="records"):
        row: dict[str, Any] = {}
        for key, value in raw.items():
            if pd.isna(value):
                row[key] = None
            elif isinstance(value, pd.Timestamp):
                row[key] = value.isoformat()
            elif hasattr(value, "item"):
                row[key] = value.item()
            else:
                row[key] = value
        records.append(row)
    return {
        "source": str(df.attrs.get("_source", "local")),
        "count": len(records),
        "columns": fields,
        "sha256": snapshot_hash(records),
        "bars": records,
    }


def _evidence_time(run: dict[str, Any], kind: str) -> datetime | None:
    rows = [item for item in run.get("evidence", []) if item.get("kind") == kind]
    if not rows:
        return None
    value = max(float(item.get("captured_at") or 0) for item in rows)
    return datetime.fromtimestamp(value, UTC) if value > 0 else None


def build_research_decision(run: dict[str, Any]) -> dict[str, Any]:
    summary = run.get("summary") or {}
    market = summary.get("market") if isinstance(summary.get("market"), dict) else {}
    quantitative = (
        market.get("quantitative") if isinstance(market.get("quantitative"), dict) else {}
    )
    dimensions = (
        quantitative.get("dimensions") if isinstance(quantitative.get("dimensions"), dict) else {}
    )
    trend = dimensions.get("trend") if isinstance(dimensions.get("trend"), dict) else {}
    trend_direction = normalize_direction(
        trend.get("signal"), available=bool(trend and trend.get("score") is not None)
    )
    opinions = [
        ModuleOpinion(
            module="price_structure",
            direction=trend_direction,
            confidence=(
                min(1.0, abs(float(trend["score"])) / 100)
                if trend.get("score") is not None
                else None
            ),
            evidence_at=_evidence_time(run, "quantitative_evaluation"),
            status="available" if trend_direction != "insufficient" else "missing",
            reason=str(trend.get("evidence") or quantitative.get("error") or "价格结构证据缺失"),
        )
    ]
    ensemble = summary.get("ensemble") if isinstance(summary.get("ensemble"), dict) else {}
    consensus = ensemble.get("consensus") if isinstance(ensemble.get("consensus"), dict) else {}
    consensus_direction = normalize_direction(
        consensus.get("direction"), available=bool(consensus and ensemble.get("ok") is not False)
    )
    opinions.append(
        ModuleOpinion(
            module="model_consensus",
            direction=consensus_direction,
            confidence=(
                float(consensus["confidence"])
                if isinstance(consensus.get("confidence"), (int, float))
                else None
            ),
            evidence_at=_evidence_time(run, "ensemble_output"),
            status="available" if consensus_direction != "insufficient" else "missing",
            reason=(
                f"buy_votes={consensus.get('buy_votes', 0)}, "
                f"sell_votes={consensus.get('sell_votes', 0)}"
                if consensus
                else "模型共识证据缺失"
            ),
        )
    )

    for kind, module in (
        ("fundamental_snapshot", "fundamentals"),
        ("valuation_snapshot", "valuation"),
        ("company_event_snapshot", "company_events"),
        ("macro_event_snapshot", "macro"),
        ("factor_exposure", "validated_factor"),
    ):
        evidence = next(
            (item for item in reversed(run.get("evidence", [])) if item.get("kind") == kind),
            None,
        )
        if evidence is None:
            continue
        evidence_payload = evidence.get("payload") or {}
        eligible = evidence_payload.get("execution_eligible", True) is True
        direction = normalize_direction(evidence_payload.get("direction"), available=eligible)
        opinions.append(
            ModuleOpinion(
                module=module,
                direction=direction,
                confidence=(
                    float(evidence_payload["confidence"])
                    if isinstance(evidence_payload.get("confidence"), (int, float))
                    else None
                ),
                evidence_at=datetime.fromtimestamp(float(evidence["captured_at"]), UTC),
                status="available" if direction != "insufficient" else "failed",
                reason=str(evidence_payload.get("reason") or evidence.get("title") or kind),
                evidence_id=str(evidence.get("id")),
            )
        )

    model_output = next(
        (item for item in reversed(run.get("evidence", [])) if item.get("kind") == "model_output"),
        None,
    )
    payload = (model_output or {}).get("payload") or {}
    stage2 = payload.get("stage2") if isinstance(payload.get("stage2"), dict) else {}
    model_decision = stage2.get("decision") if isinstance(stage2.get("decision"), dict) else {}
    invalidation = []
    if model_decision.get("stop_loss_price") is not None:
        invalidation.append(f"价格触及判断失效位 {model_decision['stop_loss_price']}")
    watch_points = model_decision.get("watch_points")
    reevaluate = [str(item) for item in watch_points] if isinstance(watch_points, list) else []
    configured_modules = set(run.get("modules") or [])
    required_modules = [
        decision_module
        for configured_module, decision_module in (
            ("fundamentals", "fundamentals"),
            ("valuation", "valuation"),
            ("announcements", "company_events"),
            ("macro", "macro"),
        )
        if configured_module in configured_modules
    ]
    decision = decide_research(
        opinions,
        required_modules=required_modules,
        invalidation_conditions=invalidation,
        reevaluate_triggers=reevaluate or ["关键模块获得新的有效证据"],
    )
    return decision.model_dump(mode="json")


def build_evidence_fusion(run: dict[str, Any]) -> dict[str, Any]:
    evidence = run.get("evidence") or []

    def latest(kind: str) -> dict[str, Any] | None:
        return next((item for item in reversed(evidence) if item.get("kind") == kind), None)

    fundamental = latest("fundamental_snapshot")
    valuation = latest("valuation_snapshot")
    company_events = latest("company_event_snapshot")
    macro_events = latest("macro_event_snapshot")
    factor = latest("factor_exposure")
    try:
        from apps.api.domains.ledger.domain import compute_positions
        from apps.api.domains.ledger.repository import list_trades

        position = compute_positions(list_trades(run.get("instrument_id"), limit=10_000)).get(
            run.get("instrument_id")
        )
        holding = position.to_dict() if position else None
    except Exception:  # noqa: BLE001 - evidence coverage must remain readable if ledger is unavailable
        holding = None

    def module(item: dict[str, Any] | None, required_fields: tuple[str, ...]) -> dict[str, Any]:
        payload = (item or {}).get("payload") or {}
        missing = [field for field in required_fields if payload.get(field) is None]
        status = "covered" if item and not missing else "partial" if item else "missing"
        return {
            "status": status,
            "covered": status == "covered",
            "evidence_id": (item or {}).get("id"),
            "captured_at": (item or {}).get("captured_at"),
            "source": (item or {}).get("source"),
            "missing_fields": missing if item else list(required_fields),
            "data": payload,
        }

    factor_module = module(
        factor,
        ("factor_key", "factor_version", "percentile", "status", "market_regime"),
    )
    factor_data = factor_module["data"]
    factor_module["execution_eligible"] = bool(
        factor_module["status"] == "covered"
        and factor_data.get("status") in {"usable", "trading_validated"}
        and factor_data.get("decayed") is not True
    )
    return {
        "technical": {
            "status": "covered" if (run.get("summary") or {}).get("market") else "missing",
            "data": (run.get("summary") or {}).get("market"),
        },
        "fundamental": module(
            fundamental, ("financial_quality", "earnings_trend", "cash_flow_quality")
        ),
        "valuation": module(valuation, ("valuation_range", "valuation_percentile")),
        "company_events": module(company_events, ("total", "verified_count", "direction")),
        "macro": module(
            macro_events,
            ("event_count", "relationship_count", "reliable_transmission_count", "direction"),
        ),
        "factor": factor_module,
        "holding": {
            "status": "held" if holding else "not_held",
            "available": holding is not None,
            "position": holding,
            "evidence_requirements": (
                ["继续持有条件", "减仓条件", "退出条件"]
                if holding
                else ["建仓前验证条件", "失效条件"]
            ),
        },
        "coverage_complete": bool(
            fundamental and valuation and company_events and macro_events and factor
        ),
    }


def persist_research_decision(run_id: str) -> dict[str, Any] | None:
    run = store.get_research_run(run_id)
    if run is None:
        return None
    decision = build_research_decision(run)
    decision_model = decision_from_mapping(decision)
    action_guidance = None
    if decision_model is not None:
        holding_raw = str((run.get("input") or {}).get("holding_status", "not_held"))
        holding_status = (
            HoldingStatus.HELD
            if holding_raw == HoldingStatus.HELD.value
            else HoldingStatus.NOT_HELD
        )
        evidence_coverage = {
            opinion.module: (
                "covered"
                if opinion.status == "available"
                else "stale"
                if opinion.status == "stale"
                else "missing"
            )
            for opinion in decision_model.module_opinions
        }
        action_guidance = build_action_guidance(
            decision_model,
            holding_status=holding_status,
            evidence_coverage=evidence_coverage,
            review_at=datetime.now(UTC) + timedelta(days=30),
        ).model_dump(mode="json")
    summary = {
        **(run.get("summary") or {}),
        "research_decision": decision,
        "evidence_fusion": build_evidence_fusion(run),
        "action_guidance": action_guidance,
    }
    store.update_research_run(run_id, {"summary": summary})
    add_evidence(
        run_id,
        kind="research_decision",
        source=str(decision["decision_version"]),
        title=f"{run['symbol']} 统一研究决策",
        payload=decision,
    )
    if action_guidance is not None:
        add_evidence(
            run_id,
            kind="action_guidance",
            source=str(action_guidance["method_version"]),
            title=f"{run['symbol']} 场景化建议参考",
            payload=action_guidance,
        )
    return decision


def verify_run_snapshots(run: dict[str, Any]) -> dict[str, Any]:
    """Verify all stored market snapshots and report replay prerequisites."""
    checks: list[dict[str, Any]] = []
    evidence = run.get("evidence") or []
    for item in evidence:
        if item.get("kind") != "market_snapshot":
            continue
        payload = item.get("payload") or {}
        bars = payload.get("bars")
        expected = payload.get("sha256")
        actual = snapshot_hash(bars) if isinstance(bars, list) else None
        checks.append(
            {
                "evidence_id": item.get("id"),
                "title": item.get("title"),
                "expected_sha256": expected,
                "actual_sha256": actual,
                "valid": bool(expected and actual and expected == actual),
                "bar_count": len(bars) if isinstance(bars, list) else 0,
            }
        )

    kinds = {str(item.get("kind")) for item in evidence}
    snapshots_valid = bool(checks) and all(item["valid"] for item in checks)
    has_analysis_output = bool(kinds & {"model_output", "ensemble_output", "news"})
    return {
        "ok": snapshots_valid,
        "run_id": run["id"],
        "snapshot_count": len(checks),
        "snapshots_valid": snapshots_valid,
        "has_analysis_output": has_analysis_output,
        "replay_ready": snapshots_valid and has_analysis_output,
        "checks": checks,
    }


def build_export_manifest(run: dict[str, Any]) -> dict[str, Any]:
    evidence = run.get("evidence") or []
    available_times: list[tuple[datetime, str]] = []
    method_versions: set[str] = set()
    manifest: list[dict[str, Any]] = []
    for item in evidence:
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        provenance = (
            payload.get("provenance") if isinstance(payload.get("provenance"), dict) else {}
        )
        available_at = provenance.get("available_at")
        if isinstance(available_at, str):
            try:
                parsed_available_at = datetime.fromisoformat(available_at)
            except ValueError:
                parsed_available_at = None
            if parsed_available_at is not None and parsed_available_at.tzinfo is not None:
                available_times.append((parsed_available_at, available_at))
        source = str(item.get("source") or "")
        if source:
            method_versions.add(source)
        for key in ("method_version", "decision_version", "version"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                method_versions.add(value)
        manifest.append(
            {
                "id": item.get("id"),
                "kind": item.get("kind"),
                "title": item.get("title"),
                "source": item.get("source"),
                "uri": item.get("uri"),
                "captured_at": item.get("captured_at"),
                "available_at": available_at,
                "revision": provenance.get("revision"),
                "content_hash": provenance.get("content_hash"),
            }
        )
    data_cutoff = (
        max(available_times, key=lambda item: item[0])[1]
        if available_times
        else datetime.fromtimestamp(float(run["updated_at"]), UTC).isoformat()
    )
    return {
        "data_cutoff": data_cutoff,
        "method_versions": sorted(method_versions),
        "evidence_manifest": manifest,
        "disclaimer": "研究参考，不构成投资建议或收益承诺；请结合原始来源独立判断。",
    }


def compare_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a stable, compact comparison across research snapshots."""
    contexts = [
        {
            "symbol": run["symbol"],
            "market": run["market"],
            "timeframe": run["timeframe"],
        }
        for run in runs
    ]
    modules = sorted({module for run in runs for module in run.get("modules", [])})
    rows = []
    for run in runs:
        evidence = run.get("evidence") or []
        kind_counts: dict[str, int] = {}
        snapshot_hashes: list[str] = []
        for item in evidence:
            kind = str(item.get("kind", "unknown"))
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
            if kind == "market_snapshot":
                digest = (item.get("payload") or {}).get("sha256")
                if digest:
                    snapshot_hashes.append(str(digest))
        rows.append(
            {
                "id": run["id"],
                "status": run["status"],
                "updated_at": run["updated_at"],
                "modules": run.get("modules", []),
                "module_presence": {module: module in run.get("modules", []) for module in modules},
                "summary": run.get("summary", {}),
                "evidence_count": len(evidence),
                "evidence_kind_counts": kind_counts,
                "snapshot_sha256": snapshot_hashes,
            }
        )
    summary_keys = sorted({key for run in runs for key in run.get("summary", {})})

    def snapshot(run: dict[str, Any]) -> dict[str, Any]:
        summary = run.get("summary") or {}
        market = summary.get("market") if isinstance(summary.get("market"), dict) else {}
        quantitative = (
            market.get("quantitative") if isinstance(market.get("quantitative"), dict) else {}
        )
        metrics = (
            quantitative.get("metrics") if isinstance(quantitative.get("metrics"), dict) else {}
        )
        decision = (
            summary.get("research_decision")
            if isinstance(summary.get("research_decision"), dict)
            else {}
        )
        model_output = next(
            (
                item
                for item in reversed(run.get("evidence") or [])
                if item.get("kind") == "model_output"
            ),
            None,
        )
        payload = (model_output or {}).get("payload") or {}
        stage2 = payload.get("stage2") if isinstance(payload.get("stage2"), dict) else {}
        model_decision = stage2.get("decision") if isinstance(stage2.get("decision"), dict) else {}
        news = summary.get("news") if isinstance(summary.get("news"), dict) else {}
        themes = news.get("themes") if isinstance(news.get("themes"), list) else []
        fundamentals = (
            summary.get("fundamentals") if isinstance(summary.get("fundamentals"), dict) else {}
        )
        valuation = summary.get("valuation") if isinstance(summary.get("valuation"), dict) else {}
        company_events = (
            summary.get("announcements") if isinstance(summary.get("announcements"), dict) else {}
        )
        macro = summary.get("macro") if isinstance(summary.get("macro"), dict) else {}
        guidance = (
            summary.get("action_guidance")
            if isinstance(summary.get("action_guidance"), dict)
            else {}
        )
        return {
            "direction": decision.get("direction", "insufficient"),
            "execution_eligible": decision.get("execution_eligible") is True,
            "conflicts": decision.get("conflicts") or [],
            "decision_version": decision.get("decision_version"),
            "module_opinions": decision.get("module_opinions") or [],
            "metrics": {
                key: metrics.get(key)
                for key in (
                    "latest_price",
                    "return_20_pct",
                    "annualized_volatility_pct",
                    "max_drawdown_pct",
                    "rsi_14",
                )
            },
            "levels": {
                "entry": model_decision.get("entry_price"),
                "invalidation": model_decision.get("stop_loss_price"),
                "target": model_decision.get("take_profit_price"),
            },
            "news_themes": themes,
            "fundamentals": {
                key: fundamentals.get(key)
                for key in ("financial_quality", "earnings_trend", "cash_flow_quality")
            },
            "valuation": {
                key: valuation.get(key)
                for key in ("valuation_range", "valuation_percentile", "method_version")
            },
            "company_events": {
                "direction": company_events.get("direction"),
                "verified_count": company_events.get("verified_count"),
                "event_ids": [
                    item.get("event_id")
                    for item in company_events.get("events", [])
                    if isinstance(item, dict)
                ],
            },
            "macro": {
                "direction": macro.get("direction"),
                "reliable_transmission_count": macro.get("reliable_transmission_count"),
                "event_ids": [
                    item.get("event_id")
                    for item in macro.get("events", [])
                    if isinstance(item, dict)
                ],
            },
            "guidance_status": guidance.get("status"),
            "invalidation_conditions": decision.get("invalidation_conditions") or [],
            "reevaluate_triggers": decision.get("reevaluate_triggers") or [],
        }

    structured = [snapshot(run) for run in runs]
    changes: list[dict[str, Any]] = []
    if len(structured) == 2:
        current, previous = structured
        for field in ("direction", "execution_eligible", "decision_version"):
            if current[field] != previous[field]:
                changes.append(
                    {
                        "kind": "decision" if field != "decision_version" else "rule_version",
                        "field": field,
                        "before": previous[field],
                        "after": current[field],
                    }
                )
        for group in ("metrics", "levels"):
            for field, after in current[group].items():
                before = previous[group].get(field)
                if before != after:
                    changes.append(
                        {
                            "kind": group,
                            "field": field,
                            "before": before,
                            "after": after,
                            "delta": (
                                round(float(after) - float(before), 6)
                                if isinstance(after, (int, float))
                                and isinstance(before, (int, float))
                                else None
                            ),
                        }
                    )
        if current["news_themes"] != previous["news_themes"]:
            changes.append(
                {
                    "kind": "news",
                    "field": "themes",
                    "before": previous["news_themes"],
                    "after": current["news_themes"],
                }
            )
        if current["module_opinions"] != previous["module_opinions"]:
            changes.append(
                {
                    "kind": "module_opinions",
                    "field": "directions",
                    "before": previous["module_opinions"],
                    "after": current["module_opinions"],
                }
            )
        for field in ("fundamentals", "valuation", "company_events", "macro"):
            if current[field] != previous[field]:
                changes.append(
                    {
                        "kind": field,
                        "field": "snapshot",
                        "before": previous[field],
                        "after": current[field],
                    }
                )
        if current["guidance_status"] != previous["guidance_status"]:
            changes.append(
                {
                    "kind": "guidance",
                    "field": "status",
                    "before": previous["guidance_status"],
                    "after": current["guidance_status"],
                }
            )
    return {
        "ok": True,
        "same_context": all(context == contexts[0] for context in contexts[1:]),
        "contexts": contexts,
        "modules": modules,
        "summary_keys": summary_keys,
        "rows": rows,
        "structured_snapshots": structured,
        "changes": changes,
    }
