"""策略实验室路由：/strategy-lab/* 端点。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from . import service
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

router = APIRouter(prefix="/strategy-lab", tags=["strategy-lab"])


@router.post("/definitions")
def create_definition(req: DefinitionCreate) -> dict:
    return service.create_definition(req)


@router.get("/definitions")
def list_definitions(
    limit: int = Query(default=100, ge=1, le=500),
    include_archived: bool = Query(default=False),
) -> dict:
    return service.list_definitions(limit=limit, include_archived=include_archived)


@router.get("/definitions/{definition_id}")
def get_definition(definition_id: str) -> dict:
    return service.get_definition(definition_id)


@router.patch("/definitions/{definition_id}")
def update_definition(definition_id: str, req: DefinitionUpdate) -> dict:
    return service.update_definition(definition_id, req)


@router.post("/definitions/{definition_id}/copy")
def copy_definition(definition_id: str, req: DefinitionCopy) -> dict:
    return service.copy_definition(definition_id, req)


@router.post("/definitions/{definition_id}/archive")
def archive_definition(definition_id: str) -> dict:
    return service.archive_definition(definition_id)


@router.post("/definitions/{definition_id}/versions")
def create_version(definition_id: str, req: VersionCreate) -> dict:
    return service.create_version(definition_id, req)


@router.patch("/versions/{version_id}")
def update_version(version_id: str, req: VersionUpdate) -> dict:
    return service.update_version(version_id, req)


@router.post("/versions/{version_id}/copy")
def copy_version(version_id: str, req: VersionCopy) -> dict:
    return service.copy_version(version_id, req)


@router.post("/versions/{version_id}/archive")
def archive_version(version_id: str) -> dict:
    return service.archive_version(version_id)


@router.post("/experiments")
def create_experiment(req: ExperimentCreate, definition_id: str = Query(...)) -> dict:
    return service.create_experiment(definition_id, req)


@router.get("/experiments")
def list_experiments(
    definition_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    include_archived: bool = Query(default=False),
) -> dict:
    return service.list_experiments(
        definition_id=definition_id,
        limit=limit,
        include_archived=include_archived,
    )


@router.patch("/experiments/{experiment_id}")
def update_experiment(experiment_id: str, req: ExperimentUpdate) -> dict:
    return service.update_experiment(experiment_id, req)


@router.post("/experiments/{experiment_id}/copy")
def copy_experiment(experiment_id: str, req: ExperimentCopy) -> dict:
    return service.copy_experiment(experiment_id, req)


@router.post("/experiments/{experiment_id}/archive")
def archive_experiment(experiment_id: str) -> dict:
    return service.archive_experiment(experiment_id)


@router.post("/experiments/{experiment_id}/backtest")
def run_backtest(experiment_id: str, req: BacktestRunCreate) -> dict:
    return service.run_backtest(experiment_id, req)


@router.get("/experiments/{experiment_id}/runs")
def list_runs(experiment_id: str) -> dict:
    return service.list_runs(experiment_id)


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    return service.get_run(run_id)


@router.get("/compare")
def compare_runs(
    run_ids: list[str] = Query(..., min_length=1, description="待对比的 run_id 列表"),
) -> dict:
    return service.compare_runs(run_ids)
