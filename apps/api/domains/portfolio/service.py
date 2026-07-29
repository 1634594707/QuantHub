from __future__ import annotations

import logging
import os
import re

import pandas as pd
import requests
import yaml

from core.config import CONFIGS_DIR
from core.data_feed.factory import get_data_source
from core.data_feed.tencent_source import _to_tencent_code
from core.signals import get_bus
from strategies import discover_and_register, list_strategies

from . import repository
from .schemas import AllocationCreate


class UnknownStrategyError(ValueError):
    pass


def _load_config() -> dict:
    path = CONFIGS_DIR / "portfolio.yaml"
    if not path.exists():
        return {"cash": 0.0, "holdings": [], "watchlist": [], "breadth_basket": []}
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        "cash": float(config.get("cash", 0)),
        "holdings": list(config.get("holdings", [])),
        "watchlist": list(config.get("watchlist", [])),
        "breadth_basket": [
            (item["code"], item["sector"])
            for item in config.get("breadth_basket", [])
            if isinstance(item, dict) and "code" in item and "sector" in item
        ],
    }


CONFIG = _load_config()


def _market_fetch_disabled() -> bool:
    return os.environ.get("QUANTHUB_DISABLE_MARKET_FETCH") == "1"


def allocation_overview() -> dict:
    allocations = repository.list_allocations()
    signals = get_bus().history(limit=200)
    long_count = sum(1 for signal in signals if signal.direction in ("buy", "bullish"))
    short_count = sum(1 for signal in signals if signal.direction in ("sell", "bearish"))
    total_weight = sum(item["weight"] for item in allocations)
    maximum_weight = max((item["weight"] for item in allocations), default=0.0)
    return {
        "allocations": allocations,
        "summary": {
            "n_alloc": len(allocations),
            "total_weight": round(total_weight, 4),
            "live_count": sum(1 for item in allocations if item["live"]),
            "exposure": {
                "long": long_count,
                "short": short_count,
                "hold": len(signals) - long_count - short_count,
                "total": len(signals),
            },
            "max_weight": round(maximum_weight, 4),
            "concentration": (round(maximum_weight / total_weight, 4) if total_weight > 0 else 0.0),
        },
    }


def create_allocation(req: AllocationCreate) -> dict:
    discover_and_register()
    if req.strategy not in list_strategies():
        raise UnknownStrategyError(req.strategy)
    return repository.create_allocation(
        strategy=req.strategy,
        weight=req.weight,
        symbol=req.symbol,
        live=req.live,
        note=req.note,
    )


def latest_close(symbol: str, market: str, interval: str = "1h") -> float | None:
    if _market_fetch_disabled():
        return None
    if market != "a_shares":
        interval = "1d"
    try:
        frame = get_data_source(market).get_kline(symbol, interval, limit=2)
        return None if frame is None or frame.empty else float(frame["close"].iloc[-1])
    except Exception:
        return None


def tencent_quote_detail(symbol: str, market: str) -> tuple[str | None, float | None, float | None]:
    if _market_fetch_disabled():
        return (None, None, None)
    try:
        code = _to_tencent_code(symbol, market)
        response = requests.get(
            f"https://qt.gtimg.cn/q={code}",
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
            timeout=15,
        )
        response.raise_for_status()
        match = re.search(r'="([^"]+)"', response.content.decode("gbk", errors="replace"))
        if not match:
            return (None, None, None)
        parts = match.group(1).split("~")
        if len(parts) < 5:
            return (None, None, None)
        return (
            parts[1].strip() or None,
            float(parts[3]) if parts[3] else None,
            float(parts[4]) if parts[4] else None,
        )
    except Exception:
        logging.getLogger(__name__).exception("腾讯报价失败 %s/%s", market, symbol)
        return (None, None, None)


def resolve_security_name(symbol: str, market: str, supplied: str = "") -> str:
    if supplied.strip():
        return supplied.strip()
    if market in {"a_shares", "us_stocks"}:
        name, _, _ = tencent_quote_detail(symbol, market)
        return name or ""
    return ""


def quote_item(symbol: str, market: str, name: str = "") -> dict:
    requested_name = name.strip()
    if _market_fetch_disabled():
        return {
            "sym": symbol,
            "name": requested_name,
            "market": market,
            "price": None,
            "chgPct": None,
            "available": False,
        }
    if market in {"a_shares", "us_stocks"}:
        resolved, current, previous = tencent_quote_detail(symbol, market)
        if current is not None:
            change = ((current - previous) / previous * 100) if previous else 0.0
            return {
                "sym": symbol,
                "name": requested_name or resolved or symbol,
                "market": market,
                "price": round(current, 2),
                "chgPct": round(change, 2),
                "available": True,
            }
    try:
        frame = get_data_source(market).get_kline(symbol, "1d", limit=10)
    except Exception:
        frame = None
    if frame is None or frame.empty or "close" not in frame or pd.isna(frame["close"].iloc[-1]):
        return {
            "sym": symbol,
            "name": name,
            "market": market,
            "price": None,
            "chgPct": None,
            "available": False,
        }
    closes = frame["close"].dropna().tolist()
    price = float(closes[-1])
    if len(closes) >= 2:
        previous = float(closes[-2])
    else:
        _, _, previous = tencent_quote_detail(symbol, market)
    change = ((price - previous) / previous * 100) if previous else 0.0
    return {
        "sym": symbol,
        "name": name,
        "market": market,
        "price": round(price, 2),
        "chgPct": round(change, 2),
        "available": True,
    }


def portfolio_snapshot() -> dict:
    repository.seed_holdings(CONFIG["holdings"])
    holdings = []
    total_value = total_cost = daily_pnl = 0.0
    for item in repository.list_holdings():
        name = item["name"].strip()
        if not name:
            name = resolve_security_name(item["code"], item["market"])
            if name:
                repository.update_holding(item["id"], {"name": name})
        price = latest_close(item["code"], item["market"]) or item["cost"]
        value = price * item["shares"]
        cost_value = item["cost"] * item["shares"]
        pnl = value - cost_value
        change = ((price - item["cost"]) / item["cost"] * 100) if item["cost"] else 0.0
        total_value += value
        total_cost += cost_value
        daily_pnl += pnl
        holdings.append(
            {
                **item,
                "name": name,
                "price": round(price, 2),
                "chgPct": round(change, 2),
                "pnl": round(pnl, 2),
                "chgBasedScore": round(min(99, max(1, 50 + change * 1.5)), 1),
            }
        )
    pnl_percent = ((total_value - total_cost) / total_cost * 100) if total_cost else 0.0
    score = (
        round(sum(item["chgBasedScore"] for item in holdings) / len(holdings), 1)
        if holdings
        else 0.0
    )
    return {
        "ok": True,
        "summary": {
            "nav": round(total_value + CONFIG["cash"], 2),
            "dailyPnl": round(daily_pnl, 2),
            "dailyPnlPct": round(pnl_percent, 2),
            "cash": round(CONFIG["cash"], 2),
            "chgBasedScore": score,
            "totalPositions": len(holdings),
        },
        "holdings": holdings,
    }


def watchlist_snapshot() -> dict:
    repository.seed_watchlist(CONFIG["watchlist"])
    output = []
    for item in repository.list_watchlist():
        quote = quote_item(item["sym"], item["market"], item["name"])
        if not item["name"].strip() and quote.get("name"):
            repository.update_watchlist(item["id"], {"name": quote["name"]})
        output.append({**quote, "id": item["id"]})
    return {"ok": True, "items": output}


def market_breadth() -> dict:
    if _market_fetch_disabled():
        return {
            "ok": True,
            "sample": True,
            "note": "市场数据获取已禁用",
            "up": 0,
            "flat": 0,
            "down": 0,
            "sectors": [],
        }
    up = flat = down = 0
    sectors: dict[str, list[float]] = {}
    for code, sector in CONFIG["breadth_basket"]:
        _, current, previous = tencent_quote_detail(code, "a_shares")
        if current is None or not previous:
            continue
        change = (current - previous) / previous * 100
        if change > 0.05:
            up += 1
        elif change < -0.05:
            down += 1
        else:
            flat += 1
        sectors.setdefault(sector, []).append(change)
    rows = [
        {"name": key, "chgPct": round(sum(values) / len(values), 2)}
        for key, values in sectors.items()
    ]
    rows.sort(key=lambda item: item["chgPct"], reverse=True)
    return {
        "ok": True,
        "sample": True,
        "note": "样本广度：一篮子代表性成分（腾讯实时报价），非全市场涨跌家数",
        "up": up,
        "flat": flat,
        "down": down,
        "sectors": rows,
    }
