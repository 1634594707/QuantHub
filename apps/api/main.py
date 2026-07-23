"""QuantHub 统一 API 网关（单端口）。

把分散在多个源项目里的 FastAPI/Flask 服务收口为 **一个** 进程、一个端口：
前端看板、企微机器人、外部调度器都通过本服务调用 QuantHub 已注册的
全部策略，不再各自起服务。

设计要点：
    - 启动即 discover_and_register()，暴露全部策略
    - /strategies/{name}/run 通过 inspect 过滤参数，兼容异构 produce() 签名
      （有的吃 codes，有的无参），单个策略出错不影响网关
    - 信号总线可读可写，便于外部系统注入 / 订阅
    - CORS 放开，方便本地看板直连

启动::

    uv run uvicorn apps.api.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core.config import get_config
from core.signals import Signal, get_bus
from strategies import discover_and_register, get_strategy, list_strategies

logger = logging.getLogger(__name__)

_DISCOVERED = False


def _ensure_discovered() -> None:
    global _DISCOVERED
    if not _DISCOVERED:
        discover_and_register()
        _DISCOVERED = True


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    _ensure_discovered()
    yield


app = FastAPI(title="QuantHub API", version="0.1.0", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# 请求 / 响应模型
# ---------------------------------------------------------------------------
class RunRequest(BaseModel):
    params: dict[str, Any] = Field(
        default_factory=dict, description="透传给策略 produce() 的参数（如 codes/with_kline）"
    )


class PublishRequest(BaseModel):
    symbol: str
    market: str = "a_shares"
    direction: str = "hold"
    score: float = 0.5
    confidence: float = 0.5
    source: str = "api"
    timeframe: str = "realtime"
    tags: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _signal_to_dict(sig: Any) -> dict[str, Any]:
    if hasattr(sig, "to_dict"):
        try:
            return sig.to_dict()
        except Exception:
            pass
    if isinstance(sig, Signal):
        return {
            "symbol": sig.symbol,
            "market": sig.market,
            "timeframe": sig.timeframe,
            "direction": sig.direction,
            "score": sig.score,
            "confidence": sig.confidence,
            "source": sig.source,
            "tags": list(sig.tags or []),
            "meta": sig.meta or {},
            "ts": getattr(sig, "ts", None),
        }
    return dict(sig)


def _call_produce(strategy: Any, params: dict[str, Any]) -> list[Any]:
    """反射式调用 produce()，只传它接受的参数，兼容异构签名。"""
    try:
        sig = inspect.signature(strategy.produce)
        accept = set(sig.parameters.keys())
    except (TypeError, ValueError):
        accept = set()
    kwargs = {k: v for k, v in params.items() if k in accept} if accept else dict(params)
    try:
        result = strategy.produce(**kwargs)
    except TypeError:
        # 签名反射失败时的兜底：无参调用
        result = strategy.produce()
    if result is None:
        return []
    if isinstance(result, (list, tuple)):
        return list(result)
    return [result]


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
@app.get("/health")
def health() -> dict[str, Any]:
    _ensure_discovered()
    cfg = get_config()
    return {
        "status": "ok",
        "time": datetime.now().isoformat(timespec="seconds"),
        "strategies": len(list_strategies()),
        "live_trading": bool(cfg.get("live_trading", False)),
        "version": app.version,
    }


@app.get("/strategies")
def get_strategies() -> dict[str, Any]:
    _ensure_discovered()
    out = []
    for name, info in list_strategies().items():
        out.append(
            {
                "name": name,
                "market": info.market,
                "live_capable": info.live_capable,
                "description": info.description or "",
            }
        )
    return {"count": len(out), "strategies": out}


@app.get("/strategies/{name}")
def get_strategy_info(name: str) -> dict[str, Any]:
    _ensure_discovered()
    ss = list_strategies()
    if name not in ss:
        raise HTTPException(status_code=404, detail=f"未知策略: {name}")
    info = ss[name]
    return {
        "name": name,
        "market": info.market,
        "live_capable": info.live_capable,
        "description": info.description or "",
    }


@app.post("/strategies/{name}/run")
def run_strategy(name: str, req: RunRequest) -> dict[str, Any]:
    _ensure_discovered()
    ss = list_strategies()
    if name not in ss:
        raise HTTPException(status_code=404, detail=f"未知策略: {name}")
    try:
        strategy = get_strategy(name, config={"enabled": True})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"策略实例化失败: {exc}") from exc
    try:
        raw = _call_produce(strategy, req.params)
        signals = [_signal_to_dict(s) for s in raw]
        return {"ok": True, "name": name, "count": len(signals), "signals": signals}
    except Exception as exc:  # 单策略失败不影响网关
        logger.exception("策略 %s 运行失败", name)
        return {"ok": False, "name": name, "error": str(exc), "signals": []}


@app.get("/signals")
def get_signals(limit: int = 50) -> dict[str, Any]:
    _ensure_discovered()
    history = get_bus().history(limit=limit)
    return {"count": len(history), "signals": [_signal_to_dict(s) for s in history]}


@app.post("/signals/publish")
def publish_signal(req: PublishRequest) -> dict[str, Any]:
    _ensure_discovered()
    sig = Signal(
        symbol=req.symbol,
        market=req.market,
        timeframe=req.timeframe,
        direction=req.direction,
        score=req.score,
        confidence=req.confidence,
        source=req.source,
        tags=req.tags,
        meta=req.meta,
    )
    get_bus().publish(sig)
    return {"ok": True, "signal": _signal_to_dict(sig)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
