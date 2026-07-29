"""组合账本路由：/ledger/* 端点。

提供成交、现金流水、持仓、组合 summary、风险敞口与基准管理的 API。
所有持仓由 ``Trade`` + ``CashEntry`` 流水实时计算，取代静态 holdings。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from . import service
from .schemas import (
    BenchmarkCorrection,
    BenchmarkCreate,
    CashEntryCorrection,
    CashEntryCreate,
    TradeCorrection,
    TradeCreate,
)

router = APIRouter(prefix="/ledger", tags=["ledger"])


# ---- Trade 成交流水 ----
@router.post("/trades")
def post_trade(req: TradeCreate) -> dict:
    """记录一笔成交（buy/sell），返回带现金影响的成交记录。"""
    try:
        return service.record_trade(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/trades")
def get_trades(
    instrument_id: str | None = Query(default=None, description="按标的过滤"),
    limit: int = Query(default=200, ge=1, le=10_000),
    cursor: str | None = None,
) -> dict:
    """查询成交流水（按时间倒序）。"""
    try:
        return service.list_trades(instrument_id=instrument_id, limit=limit, cursor=cursor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/trades/{trade_id}")
def patch_trade(trade_id: str, req: TradeCorrection) -> dict:
    result = service.correct_trade(trade_id, req)
    if not result.get("ok"):
        status = 404 if result.get("error") == "成交记录不存在" else 422
        raise HTTPException(status_code=status, detail=result.get("error"))
    return result


# ---- CashEntry 现金流水 ----
@router.post("/cash")
def post_cash(req: CashEntryCreate) -> dict:
    """记录一笔现金出入金流水。"""
    return service.record_cash(req)


@router.get("/cash")
def get_cash(
    limit: int = Query(default=200, ge=1, le=10_000), cursor: str | None = None
) -> dict:
    """查询现金流水（按时间倒序）。"""
    try:
        return service.list_cash(limit=limit, cursor=cursor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/cash/{entry_id}")
def patch_cash(entry_id: str, req: CashEntryCorrection) -> dict:
    return service.correct_cash(entry_id, req)


# ---- Position 持仓 ----
@router.get("/positions")
def get_positions(refresh_prices: bool = Query(default=True)) -> dict:
    """从成交流水计算当前持仓；可关闭行情刷新以快速完成成交对账。"""
    return service.get_positions(refresh_prices=refresh_prices)


@router.get("/positions/{instrument_id}")
def get_position(instrument_id: str) -> dict:
    """查询单个标的持仓。"""
    return service.get_position(instrument_id)


# ---- Portfolio Summary 组合级指标 ----
@router.get("/summary")
def get_summary() -> dict:
    """组合级指标：NAV、已实现/未实现盈亏、现金、持仓数、收益率。"""
    return service.portfolio_summary()


# ---- Performance 绩效分析 ----
@router.get("/performance")
def get_performance() -> dict:
    """组合绩效：TWR、最大回撤、基准超额。

    权益曲线由成交流水 + 现金流水按时间顺序重建；
    基准对比需先用 ``POST /ledger/benchmarks`` 落库一条基准曲线。
    """
    return service.performance()


@router.get("/attribution")
def get_attribution(
    start_at: float | None = Query(default=None),
    end_at: float | None = Query(default=None),
    period: str = Query(default="month"),
) -> dict:
    result = service.attribution(start_at=start_at, end_at=end_at, period=period)
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error"))
    return result


@router.get("/timeline")
def get_timeline(instrument_id: str = Query(..., min_length=1)) -> dict:
    return service.decision_timeline(instrument_id)


@router.get("/positions/{instrument_id}/decision-context")
def get_position_decision_context(instrument_id: str) -> dict:
    result = service.position_decision_context(instrument_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


# ---- Exposures 风险敞口 ----
@router.get("/exposures")
def get_exposures() -> dict:
    """风险敞口：按市场、方向、个股聚合。"""
    return service.exposures()


# ---- Benchmark 基准 ----
@router.post("/benchmarks")
def post_benchmark(req: BenchmarkCreate) -> dict:
    """登记或更新基准曲线与指标。"""
    return service.register_benchmark(req)


@router.get("/benchmarks")
def get_benchmarks() -> dict:
    """列出全部基准。"""
    return service.list_benchmarks()


@router.patch("/benchmarks/{benchmark_id}")
def patch_benchmark(benchmark_id: str, req: BenchmarkCorrection) -> dict:
    return service.correct_benchmark(benchmark_id, req)


@router.get("/corrections")
def get_corrections(
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=10_000),
) -> dict:
    return service.list_corrections(entity_type=entity_type, entity_id=entity_id, limit=limit)
