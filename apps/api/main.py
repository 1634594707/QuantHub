"""QuantHub 统一 API 网关（单端口）。

把分散在多个源项目里的 FastAPI/Flask 服务收口为 **一个** 进程、一个端口：
前端看板、企微机器人、外部调度器都通过本服务调用 QuantHub 已注册的
全部策略，不再各自起服务。

设计要点：
    - 启动即 discover_and_register()，暴露全部策略
    - 所有业务路由已按领域拆分到 ``apps/api/domains/``，通过 ``include_router`` 挂载
    - 本文件只保留 ``/health`` 健康检查和领域路由的注册入口
    - CORS 放开，方便本地看板直连

启动::

    uv run uvicorn apps.api.main:app --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import get_config
from strategies import discover_and_register, list_strategies

from .deployment import load_settings

# Domain routers (modularized routes)
from .domains.alerts import router as alerts_router
from .domains.automation import router as automation_router
from .domains.backups import router as backups_router
from .domains.ensemble import router as ensemble_router
from .domains.factor_research import router as factor_research_router
from .domains.governance import auth as governance_auth
from .domains.governance import repository as governance_repository
from .domains.governance import router as governance_router
from .domains.incidents import router as incidents_router
from .domains.instrument import router as instrument_router
from .domains.ledger import router as ledger_router
from .domains.market import router as market_router
from .domains.market_data import router as market_data_router
from .domains.news import router as news_router
from .domains.portfolio import router as portfolio_router
from .domains.research import router as research_router
from .domains.search import router as search_router
from .domains.settings import router as settings_router
from .domains.signals import router as signals_router
from .domains.simulation import router as simulation_router
from .domains.strategies import router as strategies_router
from .domains.strategy_lab import router as strategy_lab_router
from .domains.tasks import router as tasks_router

# 加载 apps/api/.env（含 DEEPSEEK_API_KEY 等密钥）；文件缺失时静默跳过
load_dotenv(Path(os.environ.get("QUANTHUB_ENV_PATH", Path(__file__).resolve().parent / ".env")))

logger = logging.getLogger(__name__)


def _source_build_id() -> str:
    root = Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    for source_root in (root / "apps", root / "core", root / "strategies"):
        for path in sorted(source_root.rglob("*.py")):
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


PROCESS_STARTED_AT = datetime.now().astimezone().isoformat(timespec="seconds")
SOURCE_BUILD_ID = _source_build_id()

_DISCOVERED = False


def _ensure_discovered() -> None:
    global _DISCOVERED
    if not _DISCOVERED:
        discover_and_register()
        _DISCOVERED = True


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    _ensure_discovered()
    from .domains.alerts import service as alerts_service
    from .domains.automation import service as automation_service

    automation_service.recover_pending_runs()
    alerts_service.start_monitor()
    try:
        yield
    finally:
        alerts_service.stop_monitor()


deployment = load_settings()
app = FastAPI(title="QuantHub API", version="0.1.0", lifespan=_lifespan)


@app.middleware("http")
async def governance_middleware(request: Request, call_next):
    if request.url.path == "/health" or request.method == "OPTIONS":
        return await call_next(request)
    principal = governance_auth.authenticate(request)
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "需要有效的 Bearer token"})
    permission = governance_auth.required_permission(request.method, request.url.path)
    if permission not in principal["permissions"]:
        return JSONResponse(
            status_code=403,
            content={"detail": f"缺少权限: {permission}"},
        )
    request.state.principal = principal
    if request.method in {"GET", "HEAD"}:
        return await call_next(request)

    result = "succeeded"
    error = None
    try:
        response = await call_next(request)
        if response.status_code >= 400:
            result = "failed"
            error = f"HTTP {response.status_code}"
        return response
    except Exception as exc:
        result = "failed"
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        path_parts = [part for part in request.url.path.split("/") if part]
        try:
            governance_repository.add_audit(
                actor_id=principal["id"],
                action=f"{request.method} {request.url.path}",
                entity_type=path_parts[0] if path_parts else "root",
                entity_id=request.url.path,
                result=result,
                error=error,
            )
        except Exception:
            logger.exception("写入统一审计日志失败")


app.add_middleware(
    CORSMiddleware,
    allow_origins=list(deployment.cors_origins),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Wire modular domain routers
app.include_router(research_router)
app.include_router(alerts_router)
app.include_router(search_router)
app.include_router(market_data_router)
app.include_router(news_router)
app.include_router(tasks_router)
app.include_router(simulation_router)
app.include_router(signals_router)
app.include_router(settings_router)
app.include_router(portfolio_router)
app.include_router(strategies_router)
app.include_router(market_router)
app.include_router(ensemble_router)
app.include_router(factor_research_router)
app.include_router(instrument_router)
app.include_router(incidents_router)
app.include_router(strategy_lab_router)
app.include_router(ledger_router)
app.include_router(automation_router)
app.include_router(backups_router)
app.include_router(governance_router)


# ---------------------------------------------------------------------------
# 健康检查（唯一保留在本文件的路由）
# ---------------------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    """健康检查：返回服务状态、已注册策略数和版本信息。"""
    _ensure_discovered()
    cfg = get_config()
    return {
        "status": "ok",
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "strategies": len(list_strategies()),
        "live_trading": bool(cfg.get("live_trading", False)),
        "version": app.version,
        "deployment_mode": deployment.mode,
        "started_at": PROCESS_STARTED_AT,
        "build_id": SOURCE_BUILD_ID,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=deployment.host, port=8000)
