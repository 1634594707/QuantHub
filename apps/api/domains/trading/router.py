"""``/trading/*`` 路由（前端经 vite/反代以 ``/api/trading/*`` 访问）。

对应工作包 M1-02 / M1-03 / M1-04 / M1-06。

前端约定：
    - 所有响应共用 :mod:`apps.api.contracts` 的外壳，含
      ``status`` / ``source`` / ``observed_at`` / ``freshness`` / ``error_code``。
    - ``GET /trading/health`` 永不返回 5xx，Runner 挂掉时以 ``status=error``
      表达，便于工作台在只读页面上安全降级。
    - 其余端点在失败时返回错误码对应的 HTTP 状态，body 仍是同一外壳。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from apps.api.contracts import error_envelope

from . import errors
from .schemas import OrderIntentRequest, ResolveDiffRequest, RiskModeRequest
from .service import get_service

router = APIRouter(prefix="/trading", tags=["trading"])


def _error_response(exc: errors.TradingError) -> JSONResponse:
    service = get_service()
    payload = exc.payload()
    body = error_envelope(
        source=service.source,
        error_code=exc.code,
        message=str(payload["message"]),
        detail=str(payload["detail"]),
        hint=exc.hint,
        retryable=bool(payload["retryable"]),
    )
    return JSONResponse(status_code=exc.spec.http_status, content=body)


@router.get("/health")
def trading_health() -> dict:
    """聚合 Runner 健康与环境。不可达时返回 200 + status=error（M1-06）。"""
    return get_service().health()


@router.get("/dashboard")
def trading_dashboard():
    try:
        return get_service().dashboard()
    except errors.TradingError as exc:
        return _error_response(exc)


@router.get("/preflight")
def trading_preflight(symbols: str | None = Query(default=None, max_length=700)):
    requested = None
    if symbols is not None:
        requested = list(
            dict.fromkeys(symbol.strip().upper() for symbol in symbols.split(",") if symbol.strip())
        )
        if not requested or len(requested) > 10 or any(len(symbol) > 64 for symbol in requested):
            raise HTTPException(status_code=422, detail="symbols 必须包含 1 到 10 个有效合约代码")
    try:
        return get_service().preflight(requested)
    except errors.TradingError as exc:
        return _error_response(exc)


@router.get("/accounts/{account_id}")
def trading_account(account_id: str):
    try:
        return get_service().account(account_id)
    except errors.TradingError as exc:
        return _error_response(exc)


@router.get("/orders/{order_id}")
def trading_order(order_id: str):
    try:
        return get_service().order(order_id)
    except errors.TradingError as exc:
        return _error_response(exc)


@router.post("/orders")
def trading_submit_order(request: OrderIntentRequest):
    try:
        return get_service().submit_order(request)
    except errors.TradingError as exc:
        return _error_response(exc)


@router.post("/orders/{order_id}/cancel")
def trading_cancel_order(order_id: str):
    try:
        return get_service().cancel_order(order_id)
    except errors.TradingError as exc:
        return _error_response(exc)


@router.post("/recovery/orders")
def trading_recover_orders():
    try:
        return get_service().recover_orders()
    except errors.TradingError as exc:
        return _error_response(exc)


@router.post("/reconciliation/{account_id}")
def trading_reconcile(account_id: str):
    try:
        return get_service().reconcile(account_id)
    except errors.TradingError as exc:
        return _error_response(exc)


@router.get("/reconciliation/diffs/{diff_id}")
def trading_reconciliation_diff(diff_id: str):
    try:
        return get_service().reconciliation_diff(diff_id)
    except errors.TradingError as exc:
        return _error_response(exc)


@router.post("/reconciliation/diffs/{diff_id}/resolve")
def trading_resolve_diff(diff_id: str, request: ResolveDiffRequest):
    try:
        return get_service().resolve_diff(diff_id, request)
    except errors.TradingError as exc:
        return _error_response(exc)


@router.post("/risk/mode")
def trading_set_risk_mode(request: RiskModeRequest):
    try:
        return get_service().set_risk_mode(request)
    except errors.TradingError as exc:
        return _error_response(exc)
