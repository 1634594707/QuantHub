"""策略实验室服务：定义/版本/实验/回测的编排。

回测执行复用 ``apps.api.domains.strategies.service.backtest``，
额外保存数据快照（K 线哈希）与随机种子以保证可复现性。
"""

from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from copy import deepcopy
from typing import Any

import pandas as pd

from apps.api import store
from apps.api.domains.instrument import service as instrument_service
from apps.api.domains.research.service import dataframe_snapshot, snapshot_hash
from apps.api.domains.strategies import service as strategies_service
from apps.api.domains.strategies.schemas import BacktestRequest
from core.data_feed.factory import get_data_source
from core.data_feed.quality import assess_ohlcv

from . import repository
from .domain import BacktestRun, code_hash_of
from .schemas import (
    BacktestRunCreate,
    DefinitionCopy,
    DefinitionCreate,
    DefinitionUpdate,
    ExperimentCopy,
    ExperimentCreate,
    ExperimentUpdate,
    VersionCopy,
    VersionCreate,
    VersionUpdate,
)

logger = logging.getLogger(__name__)

RESEARCH_CONTRACT_KEY = "research_contract"
FACTOR_RESEARCH_MODULE = "factor_research"
MARKET_SNAPSHOT_KIND = "market_snapshot"
FACTOR_RESULT_KIND = "factor_research_result"


def _research_evidence(run: dict[str, Any], kind: str) -> dict[str, Any] | None:
    return next(
        (item for item in reversed(run.get("evidence") or []) if item.get("kind") == kind),
        None,
    )


def _build_research_contract(
    research_run_id: str,
    *,
    symbol: str,
    market: str,
    timeframe: str,
) -> dict[str, Any]:
    run = store.get_research_run(research_run_id)
    if run is None:
        raise ValueError("关联的因子研究记录不存在")
    expected_context = (run.get("symbol"), run.get("market"), run.get("timeframe"))
    actual_context = (symbol, market, timeframe)
    if expected_context != actual_context:
        raise ValueError("策略实验与因子研究的标的、市场、周期必须完全一致")
    if FACTOR_RESEARCH_MODULE not in run.get("modules", []) or run.get("status") != "succeeded":
        raise ValueError("关联的因子研究未完成，不能创建策略实验")
    result_evidence = _research_evidence(run, FACTOR_RESULT_KIND)
    snapshot_evidence = _research_evidence(run, MARKET_SNAPSHOT_KIND)
    result = (result_evidence or {}).get("payload") or {}
    snapshot = (snapshot_evidence or {}).get("payload") or {}
    summary = result.get("summary") or {}
    bars = snapshot.get("bars")
    expected_sha256 = snapshot.get("sha256")
    actual_sha256 = snapshot_hash(bars) if isinstance(bars, list) else None
    if (
        not result_evidence
        or not snapshot_evidence
        or not expected_sha256
        or expected_sha256 != actual_sha256
    ):
        raise ValueError("因子研究行情快照缺失或哈希校验失败")
    if summary.get("data_fingerprint") and snapshot.get("data_fingerprint") != summary.get(
        "data_fingerprint"
    ):
        raise ValueError("因子研究数据指纹与行情快照不一致")
    selected_usable = [
        factor
        for factor in result.get("factors") or []
        if factor.get("exploratory_candidate", factor.get("selected"))
        and factor.get("status") == "usable"
    ]
    if summary.get("multifactor_constructed") is False or not selected_usable:
        raise ValueError("因子研究没有通过统计门禁的组合，不能创建策略实验")
    from apps.api.domains.factor_research.service import seed_builtin_factor_definitions

    seed_builtin_factor_definitions()
    lifecycle_by_factor: dict[str, dict] = {}
    for factor in selected_usable:
        saved_definition = store.get_factor_definition(
            str(factor.get("key")), str(factor.get("formula_version"))
        )
        if saved_definition is None:
            raise ValueError("探索候选缺少可恢复的统一因子定义")
        lifecycle = store.get_latest_factor_lifecycle_event(saved_definition["id"], market)
        if lifecycle is None or lifecycle["state"] not in {
            "research_passed",
            "trading_validated",
        }:
            raise ValueError("探索候选尚未达到 research_passed，不能创建可交易策略实验")
        lifecycle_by_factor[factor["key"]] = lifecycle
    factors: list[dict[str, Any]] = []
    for factor in result.get("factors") or []:
        required = ("key", "label", "formula", "formula_version", "direction", "weight")
        if any(field not in factor for field in required):
            raise ValueError("因子研究结果缺少不可变因子定义")
        factors.append(
            {
                "key": factor["key"],
                "label": factor["label"],
                "formula": factor["formula"],
                "formula_version": factor["formula_version"],
                "direction": factor["direction"],
                "weight": factor["weight"],
                "exploratory_candidate": bool(
                    factor.get("exploratory_candidate", factor.get("selected"))
                ),
                "selected": bool(factor.get("selected")),
                "status": factor.get("status"),
                "lifecycle_state": lifecycle_by_factor.get(factor["key"], {}).get("state"),
                "lifecycle_event_id": lifecycle_by_factor.get(factor["key"], {}).get("id"),
                "lifecycle_evidence": deepcopy(
                    lifecycle_by_factor.get(factor["key"], {}).get("evidence") or {}
                ),
            }
        )
    input_config = (run.get("input") or {}).get(FACTOR_RESEARCH_MODULE) or {}
    return {
        "version": 1,
        "research_run_id": research_run_id,
        "data_fingerprint": summary.get("data_fingerprint") or snapshot.get("data_fingerprint"),
        "market_snapshot_sha256": expected_sha256,
        "engine_version": summary.get("engine_version"),
        "factor_formula_version": summary.get("factor_formula_version"),
        "factors": factors,
        "horizon": summary.get("horizon", input_config.get("horizon")),
        "transaction_cost_bps": summary.get(
            "transaction_cost_bps", input_config.get("transaction_cost_bps")
        ),
        "walk_forward_mode": summary.get(
            "walk_forward_mode", input_config.get("walk_forward_mode")
        ),
        "walk_forward_folds": summary.get(
            "walk_forward_folds", input_config.get("walk_forward_folds")
        ),
        "thresholds": deepcopy(summary.get("thresholds") or {}),
    }


def _snapshot_frame(snapshot: dict[str, Any]) -> pd.DataFrame:
    bars = snapshot.get("bars")
    columns = snapshot.get("columns")
    if not isinstance(bars, list) or not isinstance(columns, list):
        raise TypeError("研究行情快照格式不完整")
    if snapshot.get("sha256") != snapshot_hash(bars):
        raise ValueError("研究行情快照哈希校验失败")
    frame = pd.DataFrame(bars, columns=columns)
    for field in ("datetime", "bar_time"):
        if field in frame.columns:
            frame[field] = pd.to_datetime(frame[field], errors="coerce")
    frame.attrs["_source"] = snapshot.get("source", "research_snapshot")
    return frame


def create_definition(req: DefinitionCreate) -> dict:
    definition = repository.create_definition(
        name=req.name,
        strategy_key=req.strategy_key,
        market=req.market,
        description=req.description,
        tags=req.tags,
    )
    return {"ok": True, "definition": definition.to_dict()}


def list_definitions(limit: int = 100, include_archived: bool = False) -> dict:
    items = repository.list_definitions(limit=limit, include_archived=include_archived)
    return {"count": len(items), "definitions": [d.to_dict() for d in items]}


def get_definition(definition_id: str) -> dict:
    definition = repository.get_definition(definition_id)
    if not definition:
        return {"ok": False, "error": "策略定义不存在"}
    versions = repository.list_versions(definition_id, include_archived=True)
    result = definition.to_dict()
    result["versions"] = [v.to_dict() for v in versions]
    return {"ok": True, "definition": result}


def update_definition(definition_id: str, req: DefinitionUpdate) -> dict:
    if not repository.get_definition(definition_id):
        return {"ok": False, "error": "策略定义不存在"}
    try:
        definition = repository.update_definition(
            definition_id,
            name=req.name,
            strategy_key=req.strategy_key,
            market=req.market,
            description=req.description,
            tags=req.tags,
        )
    except sqlite3.IntegrityError:
        return {"ok": False, "error": "策略定义名称已存在"}
    return {"ok": True, "definition": definition.to_dict()}


def copy_definition(definition_id: str, req: DefinitionCopy) -> dict:
    source = repository.get_definition(definition_id)
    if not source:
        return {"ok": False, "error": "策略定义不存在"}
    try:
        copied = repository.create_definition(
            name=req.name,
            strategy_key=source.strategy_key,
            market=source.market,
            description=source.description,
            tags=list(source.tags),
        )
        for version in reversed(repository.list_versions(definition_id)):
            repository.create_version(
                copied.id,
                version.version,
                dict(version.params),
                version.code_hash,
                version.changelog,
            )
    except sqlite3.IntegrityError:
        return {"ok": False, "error": "策略定义名称或版本已存在"}
    return get_definition(copied.id)


def archive_definition(definition_id: str) -> dict:
    definition = repository.archive_definition(definition_id)
    if not definition:
        return {"ok": False, "error": "策略定义不存在"}
    return {"ok": True, "definition": definition.to_dict()}


def create_version(definition_id: str, req: VersionCreate) -> dict:
    if not repository.get_definition(definition_id):
        return {"ok": False, "error": "策略定义不存在"}
    version = repository.create_version(
        definition_id=definition_id,
        version=req.version,
        params=req.params,
        code_hash=req.code_hash or code_hash_of(str(req.params)),
        changelog=req.changelog,
    )
    return {"ok": True, "version": version.to_dict()}


def update_version(version_id: str, req: VersionUpdate) -> dict:
    if not repository.get_version(version_id):
        return {"ok": False, "error": "策略版本不存在"}
    try:
        version = repository.update_version(
            version_id,
            version=req.version,
            params=req.params,
            code_hash=req.code_hash or code_hash_of(str(req.params)),
            changelog=req.changelog,
        )
    except sqlite3.IntegrityError:
        return {"ok": False, "error": "同一策略定义下的版本号已存在"}
    return {"ok": True, "version": version.to_dict()}


def copy_version(version_id: str, req: VersionCopy) -> dict:
    source = repository.get_version(version_id)
    if not source:
        return {"ok": False, "error": "策略版本不存在"}
    try:
        version = repository.create_version(
            source.definition_id,
            req.version,
            dict(source.params),
            source.code_hash,
            source.changelog,
        )
    except sqlite3.IntegrityError:
        return {"ok": False, "error": "同一策略定义下的版本号已存在"}
    return {"ok": True, "version": version.to_dict()}


def archive_version(version_id: str) -> dict:
    version = repository.archive_version(version_id)
    if not version:
        return {"ok": False, "error": "策略版本不存在"}
    return {"ok": True, "version": version.to_dict()}


def create_experiment(definition_id: str, req: ExperimentCreate) -> dict:
    if not repository.get_definition(definition_id):
        return {"ok": False, "error": "策略定义不存在"}
    if req.version_id:
        version = repository.get_version(req.version_id)
        if not version or version.definition_id != definition_id:
            return {"ok": False, "error": "策略版本不存在或不属于当前策略定义"}
    try:
        instrument = instrument_service.resolve_strict(req.symbol, req.market)
    except instrument_service.InstrumentResolutionError as exc:
        return {"ok": False, "error": str(exc)}
    params = dict(req.params)
    params.pop(RESEARCH_CONTRACT_KEY, None)
    if req.research_run_id:
        try:
            params[RESEARCH_CONTRACT_KEY] = _build_research_contract(
                req.research_run_id,
                symbol=instrument.code,
                market=instrument.market,
                timeframe=req.timeframe,
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
    experiment = repository.create_experiment(
        definition_id=definition_id,
        instrument_id=instrument.instrument_id,
        symbol=instrument.code,
        market=instrument.market,
        timeframe=req.timeframe,
        version_id=req.version_id,
        research_run_id=req.research_run_id,
        params=params,
        note=req.note,
    )
    return {"ok": True, "experiment": experiment.to_dict()}


def list_experiments(
    definition_id: str | None = None, limit: int = 100, include_archived: bool = False
) -> dict:
    items = repository.list_experiments(
        definition_id=definition_id,
        limit=limit,
        include_archived=include_archived,
    )
    return {"count": len(items), "experiments": [e.to_dict() for e in items]}


def update_experiment(experiment_id: str, req: ExperimentUpdate) -> dict:
    current = repository.get_experiment(experiment_id)
    if not current:
        return {"ok": False, "error": "实验不存在"}
    if req.version_id:
        version = repository.get_version(req.version_id)
        if not version or version.definition_id != current.definition_id:
            return {"ok": False, "error": "策略版本不存在或不属于当前策略定义"}
    try:
        instrument = instrument_service.resolve_strict(req.symbol, req.market)
    except instrument_service.InstrumentResolutionError as exc:
        return {"ok": False, "error": str(exc)}
    if current.research_run_id:
        if req.research_run_id and req.research_run_id != current.research_run_id:
            return {"ok": False, "error": "已关联研究的实验不能更换研究运行"}
        if (instrument.code, instrument.market, req.timeframe) != (
            current.symbol,
            current.market,
            current.timeframe,
        ):
            return {"ok": False, "error": "已关联研究的实验不能修改标的、市场或周期"}
        contract = current.params.get(RESEARCH_CONTRACT_KEY)
        if not isinstance(contract, dict):
            return {"ok": False, "error": "实验缺少不可变研究契约"}
        research_run_id = current.research_run_id
    elif req.research_run_id:
        try:
            contract = _build_research_contract(
                req.research_run_id,
                symbol=instrument.code,
                market=instrument.market,
                timeframe=req.timeframe,
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        research_run_id = req.research_run_id
    else:
        contract = None
        research_run_id = None
    params = dict(req.params)
    params.pop(RESEARCH_CONTRACT_KEY, None)
    if contract is not None:
        params[RESEARCH_CONTRACT_KEY] = deepcopy(contract)
    experiment = repository.update_experiment(
        experiment_id,
        instrument_id=instrument.instrument_id,
        symbol=instrument.code,
        market=instrument.market,
        timeframe=req.timeframe,
        version_id=req.version_id,
        research_run_id=research_run_id,
        params=params,
        note=req.note,
    )
    return {"ok": True, "experiment": experiment.to_dict()}


def copy_experiment(experiment_id: str, req: ExperimentCopy) -> dict:
    source = repository.get_experiment(experiment_id)
    if not source:
        return {"ok": False, "error": "实验不存在"}
    copied = repository.create_experiment(
        source.definition_id,
        source.instrument_id,
        source.symbol,
        source.market,
        source.timeframe,
        source.version_id,
        source.research_run_id,
        dict(source.params),
        req.note or source.note,
    )
    return {"ok": True, "experiment": copied.to_dict()}


def archive_experiment(experiment_id: str) -> dict:
    experiment = repository.archive_experiment(experiment_id)
    if not experiment:
        return {"ok": False, "error": "实验不存在"}
    return {"ok": True, "experiment": experiment.to_dict()}


def run_backtest(experiment_id: str, req: BacktestRunCreate) -> dict:
    """在实验下执行回测，保存完整结果与数据快照。"""
    experiment = repository.get_experiment(experiment_id)
    if not experiment:
        return {"ok": False, "error": "实验不存在"}

    definition = repository.get_definition(experiment.definition_id)
    if not definition:
        return {"ok": False, "error": "策略定义不存在"}

    repository.update_experiment_status(experiment_id, "running")
    started_at = time.time()
    run_id = str(uuid.uuid4())

    def fail(error: str, snapshot: dict[str, Any] | None = None) -> dict:
        repository.update_experiment_status(experiment_id, "failed")
        run = BacktestRun(
            id=run_id,
            experiment_id=experiment_id,
            symbol=experiment.symbol,
            market=experiment.market,
            timeframe=experiment.timeframe,
            params=experiment.params,
            data_snapshot=snapshot or {},
            initial_capital=req.initial_capital,
            seed=req.seed,
            status="failed",
            error=error,
            started_at=started_at,
            finished_at=time.time(),
        )
        repository.save_run(run)
        return {"ok": False, "error": error, "run_id": run_id}

    snapshot: dict[str, Any]
    try:
        if experiment.research_run_id:
            contract = experiment.params.get(RESEARCH_CONTRACT_KEY)
            if not isinstance(contract, dict):
                return fail("实验缺少不可变研究契约")
            if contract.get("research_run_id") != experiment.research_run_id:
                return fail("实验研究运行与不可变契约不一致")
            research_run = store.get_research_run(experiment.research_run_id)
            if research_run is None:
                return fail("关联的因子研究记录不存在")
            if (
                research_run.get("symbol"),
                research_run.get("market"),
                research_run.get("timeframe"),
            ) != (experiment.symbol, experiment.market, experiment.timeframe):
                return fail("实验上下文与关联研究记录不一致")
            snapshot_evidence = _research_evidence(research_run, MARKET_SNAPSHOT_KIND)
            snapshot = deepcopy((snapshot_evidence or {}).get("payload") or {})
            if snapshot.get("sha256") != contract.get("market_snapshot_sha256"):
                return fail("实验契约与关联研究行情快照哈希不一致", snapshot)
            if snapshot.get("data_fingerprint") != contract.get("data_fingerprint"):
                return fail("实验契约与关联研究数据指纹不一致", snapshot)
            frame = _snapshot_frame(snapshot)
        else:
            frame = get_data_source(experiment.market).get_kline(
                experiment.symbol,
                experiment.timeframe,
                limit=req.limit,
            )
            snapshot = dataframe_snapshot(frame) if frame is not None and not frame.empty else {}
    except Exception as exc:  # noqa: BLE001 - normalize snapshot and adapter failures
        message = str(exc) if experiment.research_run_id else f"取 K 线失败: {exc}"
        return fail(message)

    if frame is None or frame.empty:
        return fail("K 线为空", snapshot)

    quality = assess_ohlcv(frame)
    snapshot["quality"] = quality.to_dict()

    # 复用现有回测引擎
    bt_req = BacktestRequest(
        symbol=experiment.symbol,
        market=experiment.market,
        interval=experiment.timeframe,
        limit=req.limit,
        initial_capital=req.initial_capital,
        params={
            key: value for key, value in experiment.params.items() if key != RESEARCH_CONTRACT_KEY
        },
    )
    result = strategies_service.backtest(definition.strategy_key, bt_req, klines=frame)

    if not result.get("ok"):
        return fail(result.get("error", "回测失败"), snapshot)

    summary = result.get("summary", {})
    metrics = {k: v for k, v in summary.items() if k != "metrics"}
    if "metrics" in summary:
        metrics.update(summary["metrics"])

    run = BacktestRun(
        id=run_id,
        experiment_id=experiment_id,
        symbol=experiment.symbol,
        market=experiment.market,
        timeframe=experiment.timeframe,
        params=experiment.params,
        data_snapshot=snapshot,
        initial_capital=req.initial_capital,
        equity_curve=result.get("equity", []),
        trades=result.get("trades", []),
        metrics=metrics,
        seed=req.seed,
        status="succeeded",
        started_at=started_at,
        finished_at=time.time(),
    )
    repository.save_run(run)
    repository.update_experiment_status(experiment_id, "succeeded")
    return {"ok": True, "run_id": run_id, "run": run.to_dict()}


def get_run(run_id: str) -> dict:
    run = repository.get_run(run_id)
    if not run:
        return {"ok": False, "error": "回测运行不存在"}
    return {"ok": True, "run": run.to_dict()}


def list_runs(experiment_id: str) -> dict:
    runs = repository.list_runs(experiment_id)
    return {"count": len(runs), "runs": [r.to_dict() for r in runs]}


def compare_runs(run_ids: list[str]) -> dict:
    """对比多个回测运行的指标。"""
    runs = []
    for rid in run_ids:
        run = repository.get_run(rid)
        if run:
            runs.append(run)
    if not runs:
        return {"ok": False, "error": "未找到任何有效回测运行"}
    comparison = []
    for run in runs:
        experiment = repository.get_experiment(run.experiment_id)
        version = (
            repository.get_version(experiment.version_id)
            if experiment and experiment.version_id
            else None
        )
        comparison.append(
            {
                "run_id": run.id,
                "symbol": run.symbol,
                "market": run.market,
                "timeframe": run.timeframe,
                "initial_capital": run.initial_capital,
                "seed": run.seed,
                "status": run.status,
                "metrics": run.metrics,
                "n_trades": len(run.trades),
                "data_snapshot_sha256": run.data_snapshot.get("sha256"),
                "data_snapshot": run.data_snapshot,
                "params": run.params,
                "code_hash": version.code_hash if version else None,
            }
        )
    baseline = comparison[0]
    differences = []
    for item in comparison[1:]:
        differences.append(
            {
                "against_run_id": baseline["run_id"],
                "run_id": item["run_id"],
                "data_snapshot": _mapping_diff(baseline["data_snapshot"], item["data_snapshot"]),
                "params": _mapping_diff(baseline["params"], item["params"]),
                "code_hash": {
                    "before": baseline["code_hash"],
                    "after": item["code_hash"],
                    "changed": baseline["code_hash"] != item["code_hash"],
                },
                "metrics": _mapping_diff(baseline["metrics"], item["metrics"]),
            }
        )
    return {"ok": True, "comparison": comparison, "differences": differences}


def _mapping_diff(before: dict, after: dict) -> list[dict]:
    return [
        {
            "field": key,
            "before": before.get(key),
            "after": after.get(key),
            "changed": before.get(key) != after.get(key),
        }
        for key in sorted(set(before) | set(after))
    ]
