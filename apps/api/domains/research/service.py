from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import pandas as pd

from apps.api import store
from apps.api.domains.instrument import service as instrument_service

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
) -> str:
    if run_id:
        run = store.get_research_run(run_id)
        if run is None:
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
    return {
        "ok": True,
        "same_context": all(context == contexts[0] for context in contexts[1:]),
        "contexts": contexts,
        "modules": modules,
        "summary_keys": summary_keys,
        "rows": rows,
    }
