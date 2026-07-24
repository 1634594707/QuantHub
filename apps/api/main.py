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
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pa_agent.view_models import (
    build_decision_tree_view,
    build_decision_view,
    build_future_trend_view,
)
from pydantic import BaseModel, Field

from core.config import get_config
from core.data_feed.factory import get_data_source
from core.data_feed.tencent_source import _to_tencent_code
from core.signals import Signal, get_bus
from strategies import discover_and_register, get_strategy, list_strategies
from strategies.ai_analysis.pa_agent.two_stage import run_two_stage

# 加载 apps/api/.env（含 DEEPSEEK_API_KEY 等密钥）；文件缺失时静默跳过
load_dotenv(Path(__file__).resolve().parent / ".env")

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


class ApiKeyRequest(BaseModel):
    api_key: str = Field(
        ..., min_length=1, description="LLM API Key（仅保存在本地 apps/api/.env，不入库）"
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
        has_var_keyword = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
    except (TypeError, ValueError):
        accept = set()
        has_var_keyword = False

    if has_var_keyword:
        # 显式声明的参数优先匹配；其余全部透传给 **kwargs
        kwargs = dict(params)
    else:
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


def _resolve_pa_market(symbol: str, market: str | None = None) -> str:
    """为 PA 分析确定标的所属市场（与 PaAgentStrategy 逻辑一致）。"""
    if market:
        return market
    s = (symbol or "").strip().upper()
    if s.isdigit() and len(s) == 6:
        return "a_shares"
    if any(ch.isalpha() for ch in s) and ("-" in s or "/" in s or len(s) >= 6):
        return "crypto"
    return "a_shares"


@app.post("/strategies/pa_agent/analyze")
def analyze_pa(
    symbol: str,
    timeframe: str = "1h",
    market: str | None = None,
) -> dict[str, Any]:
    """对单个标的执行完整 PA 两阶段分析，返回 view-model 渲染数据。

    - 行情统一走 ``core.data_feed``
    - 分析复用 ``strategies.ai_analysis.pa_agent.two_stage.run_two_stage``
    - 视图渲染复用 ``pa_agent.view_models`` 共享层
    - 失败时 ``ok=false`` 并附带错误信息，前端可降级到 mock
    """
    actual_market = _resolve_pa_market(symbol, market)
    try:
        ds = get_data_source(actual_market)
        df = ds.get_kline(symbol, timeframe, limit=300)
    except Exception as exc:
        logger.exception("PA 分析取 K 线失败 %s/%s", actual_market, symbol)
        return {
            "ok": False,
            "error": f"取 K 线失败: {exc}",
            "symbol": symbol,
            "timeframe": timeframe,
            "market": actual_market,
        }

    if df is None or df.empty:
        return {
            "ok": False,
            "error": "K 线为空",
            "symbol": symbol,
            "timeframe": timeframe,
            "market": actual_market,
        }

    result = run_two_stage(symbol=symbol, timeframe=timeframe, klines=df)
    if result.error and not result.stage2_json:
        return {
            "ok": False,
            "error": result.error,
            "symbol": symbol,
            "timeframe": timeframe,
            "market": actual_market,
        }

    s1 = result.stage1_json or {}
    s2 = result.stage2_json or {}
    decision = s2.get("decision") or {}
    terminal = s2.get("terminal") or {}
    gate_trace = s1.get("gate_trace", [])
    decision_trace = s2.get("decision_trace", [])
    gate_result = str(s1.get("gate_result", "proceed")).lower()
    gate_shortcircuited = gate_result in ("wait", "unknown")

    try:
        decision_view = build_decision_view(
            stage2_decision=decision,
            stage1_diagnosis=s1,
        )
        future_view = build_future_trend_view(stage2_decision=s2)
        tree_view = build_decision_tree_view(
            gate_trace=gate_trace,
            decision_trace=decision_trace,
            terminal=terminal,
            gate_result=s1.get("gate_result"),
            gate_shortcircuited=gate_shortcircuited,
        )
    except Exception as exc:
        logger.exception("PA view-model 渲染失败 %s", symbol)
        return {
            "ok": False,
            "error": f"分析成功但视图渲染失败: {exc}",
            "symbol": symbol,
            "timeframe": timeframe,
            "market": actual_market,
        }

    return {
        "ok": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "market": actual_market,
        "decision": decision_view,
        "future": future_view,
        "tree": tree_view,
        "stage1": s1,
        "stage2": s2,
        "error": result.error,
    }


@app.get("/signals")
def get_signals(limit: int = 50) -> dict[str, Any]:
    _ensure_discovered()
    history = get_bus().history(limit=limit)
    return {"count": len(history), "signals": [_signal_to_dict(s) for s in history]}


# ---------------------------------------------------------------------------
# 行情数据
# ---------------------------------------------------------------------------
@app.get("/data/kline")
def get_kline(
    symbol: str,
    market: str = "a_shares",
    interval: str = "1h",
    limit: int = 240,
) -> dict[str, Any]:
    """返回指定标的的 K 线（OHLCV）。

    - 经 ``core.data_feed`` 的统一数据源代理（A股在线源优先，本地 parquet 回退）。
    - 在线源失败/限频时回退本地 parquet；两者皆无数据时返回 ``ok:false`` / ``candles:[]``，
      供前端优雅降级到模拟数据。
    - A股本地数据为 ordinal 时间编码，``datetime`` 为占位 NaT，故 ``t`` 用 ``bar_time``。
    """
    try:
        ds = get_data_source(market)
        df = ds.get_kline(symbol, interval, limit=limit)
    except Exception as exc:  # 数据源配置缺失等
        logger.exception("K线获取失败 %s/%s", market, symbol)
        return {
            "ok": False,
            "error": str(exc),
            "symbol": symbol,
            "interval": interval,
            "candles": [],
        }

    if df is None or df.empty:
        return {
            "ok": True,
            "source": "empty",
            "symbol": symbol,
            "interval": interval,
            "candles": [],
        }

    candles: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        dt = row.get("datetime")
        if pd.notna(dt):
            t = pd.Timestamp(dt).isoformat()
        else:
            t = str(int(row.get("bar_time", 0)))
        candles.append(
            {
                "t": t,
                "o": float(row["open"]),
                "h": float(row["high"]),
                "l": float(row["low"]),
                "c": float(row["close"]),
                "v": float(row["volume"]) if pd.notna(row.get("volume")) else 0.0,
            }
        )
    return {
        "ok": True,
        "source": df.attrs.get("_source", "local"),
        "symbol": symbol,
        "interval": interval,
        "count": len(candles),
        "candles": candles,
    }


# ---------------------------------------------------------------------------
# 组合与市场面板（静态配置 + 实时价格）
# ---------------------------------------------------------------------------
_HOLDINGS_CFG: list[dict[str, Any]] = [
    {"code": "600519", "name": "贵州茅台", "shares": 100, "cost": 1650.0},
    {"code": "300750", "name": "宁德时代", "shares": 800, "cost": 202.0},
    {"code": "000858", "name": "五粮液", "shares": 500, "cost": 140.0},
    {"code": "002594", "name": "比亚迪", "shares": 300, "cost": 250.0},
    {"code": "601318", "name": "中国平安", "shares": 1200, "cost": 49.0},
]

_WATCHLIST_CFG: list[dict[str, Any]] = [
    {"sym": "NVDA", "name": "英伟达", "market": "us_stocks"},
    {"sym": "AVGO", "name": "博通", "market": "us_stocks"},
    {"sym": "600036", "name": "招商银行", "market": "a_shares"},
    {"sym": "BTC-USDT", "name": "比特币", "market": "crypto"},
]


def _latest_close(symbol: str, market: str, interval: str = "1h") -> float | None:
    """从数据源取最新收盘价；失败返回 None。"""
    # 腾讯源仅支持日/周线，非 A股统一取日线最新收盘
    if market != "a_shares":
        interval = "1d"
    try:
        ds = get_data_source(market)
        df = ds.get_kline(symbol, interval, limit=2)
        if df is None or df.empty:
            return None
        return float(df["close"].iloc[-1])
    except Exception:
        return None


def _tencent_prev_close(symbol: str, market: str) -> float | None:
    """腾讯实时报价取昨收（美股日线常只回 1 根，无法由 K 线算涨跌，改用报价接口）。

    返回 None 表示取不到。
    """
    cur, prev = _tencent_quote(symbol, market)
    return prev


def _tencent_quote(symbol: str, market: str) -> tuple[float | None, float | None]:
    """腾讯实时报价，返回 (当前价, 昨收)；失败返回 (None, None)。

    腾讯 qt 格式（~ 分隔）：索引3=当前价，索引4=昨收。
    """
    try:
        code = _to_tencent_code(symbol, market)
        r = requests.get(
            f"https://qt.gtimg.cn/q={code}",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://quote.eastmoney.com/",
            },
            timeout=15,
        )
        r.raise_for_status()
        m = re.search(r'="([^"]+)"', r.text)
        if not m:
            return (None, None)
        parts = m.group(1).split("~")
        if len(parts) < 5:
            return (None, None)
        return (float(parts[3]), float(parts[4]))
    except Exception:
        logger.exception("腾讯报价失败 %s/%s", market, symbol)
        return (None, None)


@app.get("/portfolio")
def get_portfolio() -> dict[str, Any]:
    """返回账户概览与持仓明细（价格尽可能走实时数据源）。"""
    holdings: list[dict[str, Any]] = []
    total_value = 0.0
    total_cost = 0.0
    daily_pnl = 0.0

    for cfg in _HOLDINGS_CFG:
        code = cfg["code"]
        price = _latest_close(code, "a_shares", "1h")
        if price is None:
            price = cfg["cost"]  # 无实时价时回退成本价
        shares = cfg["shares"]
        cost = cfg["cost"]
        market_value = price * shares
        cost_value = cost * shares
        pnl = market_value - cost_value
        chg_pct = ((price - cost) / cost) * 100 if cost else 0.0
        total_value += market_value
        total_cost += cost_value
        daily_pnl += pnl
        holdings.append(
            {
                "code": code,
                "name": cfg["name"],
                "price": round(price, 2),
                "cost": round(cost, 2),
                "chgPct": round(chg_pct, 2),
                "shares": shares,
                "pnl": round(pnl, 2),
                "winRate": round(min(99, max(1, 50 + chg_pct * 1.5)), 1),
            }
        )

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost) * 100 if total_cost else 0.0
    cash = 426_300.0
    nav = total_value + cash
    win_rate = round(sum(h["winRate"] for h in holdings) / len(holdings), 1) if holdings else 0.0

    return {
        "ok": True,
        "summary": {
            "nav": round(nav, 2),
            "dailyPnl": round(daily_pnl, 2),
            "dailyPnlPct": round(total_pnl_pct, 2),
            "cash": round(cash, 2),
            "winRate": win_rate,
            "totalPositions": len(holdings),
        },
        "holdings": holdings,
    }


# 市场广度样本篮子：覆盖主要行业的代表性成分（用于样本口径广度，非全市场）
_BREADTH_BASKET: list[tuple[str, str]] = [
    ("600519", "白酒"),
    ("000858", "白酒"),
    ("601318", "保险"),
    ("600036", "银行"),
    ("601012", "光伏"),
    ("300750", "新能源"),
    ("600276", "医药"),
    ("000333", "家电"),
    ("600900", "电力"),
    ("002594", "汽车"),
    ("688981", "半导体"),
    ("600030", "券商"),
]


@app.get("/market/breadth")
def get_market_breadth() -> dict[str, Any]:
    """市场广度（样本口径）。

    全市场涨跌家数需 akshare/东财，当前环境代理不放行无法获取；此处用腾讯实时报价
    取一篮子代表性成分（覆盖主要行业）真实计算涨跌分布，并明确标注 sample=true，
    绝不伪装成全市场数据。
    """
    up = flat = down = 0
    sector_chg: dict[str, list[float]] = {}
    for code, sector in _BREADTH_BASKET:
        cur, prev = _tencent_quote(code, "a_shares")
        if cur is None or not prev:
            continue
        chg = (cur - prev) / prev * 100
        if chg > 0.05:
            up += 1
        elif chg < -0.05:
            down += 1
        else:
            flat += 1
        sector_chg.setdefault(sector, []).append(chg)
    sectors = [{"name": s, "chgPct": round(sum(v) / len(v), 2)} for s, v in sector_chg.items()]
    sectors.sort(key=lambda x: x["chgPct"], reverse=True)
    return {
        "ok": True,
        "sample": True,
        "note": "样本广度：一篮子代表性成分（腾讯实时报价），非全市场涨跌家数",
        "up": up,
        "flat": flat,
        "down": down,
        "sectors": sectors,
    }


def _quote_item(sym: str, market: str, name: str) -> dict[str, Any]:
    """单个标的实时报价（复用 K 线/腾讯报价逻辑），返回统一 item 结构。

    A股/美股经腾讯源取真实日线；加密货币在当前环境无可用数据源→available=false。
    """
    interval = "1d"
    try:
        ds = get_data_source(market)
        df = ds.get_kline(sym, interval, limit=10)
    except Exception:
        df = None
    if df is None or df.empty or "close" not in df.columns or pd.isna(df["close"].iloc[-1]):
        return {
            "sym": sym,
            "name": name,
            "market": market,
            "price": None,
            "chgPct": None,
            "available": False,
        }
    closes = df["close"].dropna().tolist()
    price = float(closes[-1])
    if len(closes) >= 2:
        prev = float(closes[-2])
    else:
        # 美股日线常只回 1 根，改用腾讯实时报价取昨收算真实涨跌
        prev = _tencent_prev_close(sym, market)
    chg = ((price - prev) / prev * 100) if prev else 0.0
    return {
        "sym": sym,
        "name": name,
        "market": market,
        "price": round(price, 2),
        "chgPct": round(chg, 2),
        "available": True,
    }


@app.get("/market/watchlist")
def get_watchlist() -> dict[str, Any]:
    """关注列表（价格走实时数据源；无法接入的市场诚实标注 available=false）。"""
    items = [
        _quote_item(cfg["sym"], cfg.get("market", "a_shares"), cfg["name"])
        for cfg in _WATCHLIST_CFG
    ]
    return {"ok": True, "items": items}


@app.get("/market/quote")
def get_quote(symbol: str, market: str = "a_shares") -> dict[str, Any]:
    """单标的实时报价：A股/美股走腾讯源（真实日线），加密货币当前环境无源→available=false。"""
    return _quote_item(symbol, market, symbol)


# ---------------------------------------------------------------------------
# 配置（本地密钥管理）
# ---------------------------------------------------------------------------
def _llm_key_env() -> str:
    cfg = get_config()
    provider = cfg.get("llm", {}).get("provider", "deepseek")
    prov_cfg = cfg.get("llm", {}).get(provider, {})
    return str(prov_cfg.get("api_key_env", "DEEPSEEK_API_KEY"))


def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


def _write_env(key: str, value: str) -> None:
    """将 key=value 写入 apps/api/.env（更新或追加），不删除其他内容。"""
    env_path = Path(__file__).resolve().parent / ".env"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    found = False
    prefix = f"{key}="
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@app.get("/config/apikey")
def get_api_key_status() -> dict[str, Any]:
    """返回当前 LLM API Key 是否已配置（仅返回脱敏尾号）。"""
    env_name = _llm_key_env()
    val = os.environ.get(env_name)
    return {
        "ok": True,
        "configured": bool(val),
        "provider": get_config().get("llm", {}).get("provider", "deepseek"),
        "key_env": env_name,
        "masked": _mask_key(val) if val else None,
    }


@app.post("/config/apikey")
def set_api_key(req: ApiKeyRequest) -> dict[str, Any]:
    """保存 API Key 到本地 .env 并热重载 LLM 客户端（无需重启网关）。"""
    from core.llm import _clients as _llm_clients

    env_name = _llm_key_env()
    key = req.api_key.strip()

    _write_env(env_name, key)
    os.environ[env_name] = key

    # 清除缓存：LLM 客户端单例 + 配置 lru_cache，让下次 get_llm() 重新读取环境变量
    _llm_clients.clear()
    get_config.cache_clear()

    return {
        "ok": True,
        "configured": True,
        "provider": get_config().get("llm", {}).get("provider", "deepseek"),
        "key_env": env_name,
        "masked": _mask_key(key),
    }


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
