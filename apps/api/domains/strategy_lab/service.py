"""策略实验室服务：定义/版本/实验/回测的编排。

回测执行复用 ``apps.api.domains.strategies.service.backtest``，
额外保存数据快照（K 线哈希）与随机种子以保证可复现性。
"""

from __future__ import annotations

import logging
import sqlite3
import time
import uuid

from apps.api.domains.instrument import service as instrument_service
from apps.api.domains.research.service import dataframe_snapshot
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
    try:
        instrument = instrument_service.resolve_strict(req.symbol, req.market)
    except instrument_service.InstrumentResolutionError as exc:
        return {"ok": False, "error": str(exc)}
    experiment = repository.create_experiment(
        definition_id=definition_id,
        instrument_id=instrument.instrument_id,
        symbol=instrument.code,
        market=instrument.market,
        timeframe=req.timeframe,
        version_id=req.version_id,
        params=req.params,
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
    if not repository.get_experiment(experiment_id):
        return {"ok": False, "error": "实验不存在"}
    if req.version_id and not repository.get_version(req.version_id):
        return {"ok": False, "error": "策略版本不存在"}
    try:
        instrument = instrument_service.resolve_strict(req.symbol, req.market)
    except instrument_service.InstrumentResolutionError as exc:
        return {"ok": False, "error": str(exc)}
    experiment = repository.update_experiment(
        experiment_id,
        instrument_id=instrument.instrument_id,
        symbol=instrument.code,
        market=instrument.market,
        timeframe=req.timeframe,
        version_id=req.version_id,
        params=req.params,
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

    # 取 K 线并生成数据快照（哈希）
    try:
        frame = get_data_source(experiment.market).get_kline(
            experiment.symbol,
            experiment.timeframe,
            limit=req.limit,
        )
    except Exception as exc:
        repository.update_experiment_status(experiment_id, "failed")
        run = BacktestRun(
            id=run_id,
            experiment_id=experiment_id,
            symbol=experiment.symbol,
            market=experiment.market,
            timeframe=experiment.timeframe,
            params=experiment.params,
            initial_capital=req.initial_capital,
            status="failed",
            error=f"取 K 线失败: {exc}",
            started_at=started_at,
            finished_at=time.time(),
        )
        repository.save_run(run)
        return {"ok": False, "error": run.error, "run_id": run_id}

    if frame is None or frame.empty:
        repository.update_experiment_status(experiment_id, "failed")
        return {"ok": False, "error": "K 线为空"}

    quality = assess_ohlcv(frame)
    snapshot = dataframe_snapshot(frame)
    snapshot["quality"] = quality.to_dict()

    # 复用现有回测引擎
    bt_req = BacktestRequest(
        symbol=experiment.symbol,
        market=experiment.market,
        interval=experiment.timeframe,
        limit=req.limit,
        initial_capital=req.initial_capital,
        params=experiment.params,
    )
    result = strategies_service.backtest(definition.strategy_key, bt_req)

    if not result.get("ok"):
        repository.update_experiment_status(experiment_id, "failed")
        run = BacktestRun(
            id=run_id,
            experiment_id=experiment_id,
            symbol=experiment.symbol,
            market=experiment.market,
            timeframe=experiment.timeframe,
            params=experiment.params,
            data_snapshot=snapshot,
            initial_capital=req.initial_capital,
            status="failed",
            error=result.get("error", "回测失败"),
            started_at=started_at,
            finished_at=time.time(),
        )
        repository.save_run(run)
        return {"ok": False, "error": run.error, "run_id": run_id}

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
