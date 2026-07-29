from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from . import repository, service
from .schemas import (
    BacktestRequest,
    PresetCreate,
    RunRecordCreate,
    StrategyRunRequest,
)

router = APIRouter(prefix="/strategies", tags=["strategies"])


def _not_found(name: str, exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail=f"未知策略: {name}")


@router.get("")
def list_catalog() -> dict:
    rows = service.catalog()
    return {"count": len(rows), "strategies": rows}


@router.get("/presets")
def all_presets() -> dict:
    return {"presets": repository.list_presets()}


@router.get("/runs")
def all_runs() -> dict:
    return {"runs": repository.list_runs()}


@router.get("/alphamaster/engine")
def alphamaster_engine() -> dict:
    return {"ok": True, "engine": service.alphamaster_engine_info()}


@router.get("/{name}")
def strategy_info(name: str) -> dict:
    try:
        return service.strategy_info(name)
    except service.UnknownStrategyError as exc:
        raise _not_found(name, exc) from exc


@router.post("/{name}/run")
def run_strategy(name: str, req: StrategyRunRequest) -> dict:
    try:
        return service.run(name, req.params)
    except service.UnknownStrategyError as exc:
        raise _not_found(name, exc) from exc


@router.get("/{name}/presets")
def presets(name: str) -> dict:
    return {"presets": repository.list_presets().get(name, [])}


@router.post("/{name}/presets")
def create_preset(name: str, req: PresetCreate) -> dict:
    try:
        service.strategy_info(name)
    except service.UnknownStrategyError as exc:
        raise _not_found(name, exc) from exc
    return {"ok": True, "preset": repository.save_preset(name, req.name, req.params)}


@router.delete("/{name}/presets/{preset_id}")
def delete_preset(name: str, preset_id: str) -> dict:
    repository.delete_preset(name, preset_id)
    return {"ok": True}


@router.post("/{name}/runs")
def create_run(name: str, req: RunRecordCreate) -> dict:
    return {"ok": True, "run": repository.save_run(name, req.params, req.result)}


@router.post("/{name}/backtest")
def backtest(name: str, req: BacktestRequest) -> dict:
    try:
        return service.backtest(name, req)
    except service.UnknownStrategyError as exc:
        raise _not_found(name, exc) from exc


@router.get("/{name}/live")
def live_status(name: str) -> dict:
    try:
        return service.live_status(name)
    except service.UnknownStrategyError as exc:
        raise _not_found(name, exc) from exc


@router.post("/{name}/live/tick")
def live_tick(name: str) -> dict:
    try:
        return service.live_tick(name)
    except service.UnknownStrategyError as exc:
        raise _not_found(name, exc) from exc


@router.post("/pa_agent/analyze")
def pa_analyze(
    symbol: str = Query(..., min_length=1, description="标的代码"),
    timeframe: str = Query(default="1h"),
    market: str | None = Query(default=None),
    research_run_id: str | None = Query(default=None, description="复用已有研究运行 ID"),
) -> dict:
    return service.pa_analyze(
        symbol=symbol,
        timeframe=timeframe,
        market=market,
        research_run_id=research_run_id,
    )
