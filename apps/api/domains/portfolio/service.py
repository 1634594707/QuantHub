from __future__ import annotations

import logging
import math
import os
import re
import time
from datetime import UTC, datetime
from numbers import Real

import pandas as pd
import requests
import yaml

from apps.api import store
from core.config import CONFIGS_DIR, get_config
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
        return {"breadth_basket": []}
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
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


_ONLINE_PRIMARY_SOURCES: dict[str, frozenset[str]] = {
    "a_shares": frozenset({"akshare", "eastmoney", "tencent"}),
    "us_stocks": frozenset({"tencent", "yahoo"}),
    "crypto": frozenset({"okx"}),
}
_NON_EXECUTABLE_MARKET_SOURCES = {
    "",
    "cache",
    "disabled",
    "fallback",
    "local",
    "local_parquet",
    "mock",
    "sample",
    "synthetic",
    "unknown",
}


def _source_name(value: object) -> str:
    return str(value or "").strip().lower()


def _configured_primary_source(market: str) -> str:
    try:
        primary = get_config(market).get("data_sources", {}).get("primary")
    except Exception:  # noqa: BLE001 - a broken configuration must not make a quote executable
        return ""
    return _source_name(primary)


def _is_positive_price(value: object) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return isinstance(value, Real) and math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


def _is_display_valuation_snapshot(snapshot: dict) -> bool:
    """Accept only an explicitly classified primary snapshot for valuation.

    Same-primary cache is retained as a visible, auditable display exception;
    unverified/local/synthetic/unknown frames must not become a price merely
    because they contain a positive numeric close.
    """
    return str(snapshot.get("quality_status") or "").strip().lower() in {
        "closed_bar",
        "cached_primary",
    } and _is_positive_price(snapshot.get("price"))


def _bar_time(frame: pd.DataFrame) -> str | None:
    if "datetime" not in frame or frame.empty:
        return None
    value = frame["datetime"].iloc[-1]
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    return None if pd.isna(parsed) else parsed.isoformat()


def _snapshot_provenance(
    frame: pd.DataFrame, market: str, data_source: object
) -> tuple[str, str, str, str, str, str]:
    """Classify direct-primary, same-primary-cache, and unverified frames.

    ``DataSourceProxy`` attaches the contract and source plan only after a direct
    primary request. Its same-source cache deliberately preserves just
    ``_source``. Treating that difference as explicit provenance prevents a
    cache hit from being mistaken for a fresh execution quote.
    """
    source = _source_name(frame.attrs.get("_source"))
    primary = _configured_primary_source(market)
    declared = _source_name(getattr(data_source, "name", None))
    contract = frame.attrs.get("_data_contract")
    plan = frame.attrs.get("_source_plan")
    semantic = ""
    if isinstance(contract, dict):
        semantic = _source_name(contract.get("kline_semantics"))
    direct_primary = (
        bool(source)
        and source == primary == declared
        and isinstance(contract, dict)
        and _source_name(contract.get("name")) == source
        and isinstance(plan, list)
        and len(plan) == 1
        and isinstance(plan[0], dict)
        and _source_name(plan[0].get("name")) == source
        and plan[0].get("priority") == 1
    )
    if direct_primary and source in _ONLINE_PRIMARY_SOURCES.get(market, frozenset()):
        return source, primary, "primary", "miss", "online", semantic
    if source and source == primary == declared:
        return source, primary, "primary_cache", "hit", "cache", semantic
    return (
        source or "unknown",
        primary or declared or "unknown",
        "unverified",
        "unknown",
        "unknown",
        semantic,
    )


def _unavailable_snapshot(*, source: str, primary_source: str, error: str) -> dict:
    return {
        "price": None,
        "source": source,
        "primary_source": primary_source,
        "source_role": "unavailable",
        "cache_status": "not_attempted",
        "transport": "none",
        "data_semantics": None,
        "bar_at": None,
        "observed_at": None,
        "quality_status": "unavailable",
        "error": error,
    }


def latest_close_snapshot(symbol: str, market: str, interval: str = "1h") -> dict:
    """Return a price with provenance for fail-closed simulation risk checks.

    ``observed_at`` deliberately remains the latest source bar timestamp rather
    than request time: a fresh HTTP response cannot make historical data tradable.
    """
    primary_source = _configured_primary_source(market)
    if _market_fetch_disabled():
        return _unavailable_snapshot(
            source="disabled",
            primary_source=primary_source,
            error="行情获取已由 QUANTHUB_DISABLE_MARKET_FETCH 禁用",
        )
    try:
        data_source = get_data_source(market)
        frame = data_source.get_kline(symbol, interval, limit=2)
    except Exception as exc:  # noqa: BLE001 - provider exceptions become explicit unavailable snapshots
        return _unavailable_snapshot(
            source="unknown",
            primary_source=primary_source,
            error=f"行情源失败: {exc}",
        )
    if frame is None or frame.empty or "close" not in frame:
        return _unavailable_snapshot(
            source="unknown",
            primary_source=primary_source,
            error="行情源未返回有效收盘价",
        )
    source, primary_source, source_role, cache_status, transport, semantics = _snapshot_provenance(
        frame, market, data_source
    )
    bar_at = _bar_time(frame)
    close = frame["close"].iloc[-1]
    if pd.isna(close) or not _is_positive_price(close):
        return {
            "price": None,
            "source": source,
            "primary_source": primary_source,
            "source_role": source_role,
            "cache_status": cache_status,
            "transport": transport,
            "data_semantics": semantics or None,
            "bar_at": bar_at,
            "observed_at": bar_at,
            "quality_status": "unavailable",
            "error": "行情源未返回有效收盘价",
        }
    if source_role == "primary" and bar_at and semantics == "bar_snapshot":
        quality = "closed_bar"
        error = None
    elif source_role == "primary_cache":
        quality = "cached_primary"
        error = "行情为同源 primary 缓存，不可用于模拟订单风控"
    else:
        quality = "unavailable"
        if source in _NON_EXECUTABLE_MARKET_SOURCES:
            error = "行情来源不是在线 primary，不能作为可执行行情"
        elif source != primary_source:
            error = "行情来源与已配置 primary 不一致"
        elif not bar_at:
            error = "行情源缺少 bar 时间，不能作为可执行行情"
        else:
            error = "行情来源或数据语义不可用于模拟风控"
    return {
        "price": float(close),
        "source": source,
        "primary_source": primary_source,
        "source_role": source_role,
        "cache_status": cache_status,
        "transport": transport,
        "data_semantics": semantics or None,
        "bar_at": bar_at,
        "observed_at": bar_at,
        "quality_status": quality,
        "error": error,
    }


def latest_close(symbol: str, market: str, interval: str = "1h") -> float | None:
    """Return only a direct online-primary close for legacy read-only callers.

    Cached, local, synthetic, and otherwise unverified values remain
    visible through :func:`latest_close_snapshot` with their provenance, but are
    never silently downgraded into a generic current-price scalar.
    """
    snapshot = latest_close_snapshot(symbol, market, interval)
    price = snapshot["price"]
    return (
        float(price)
        if snapshot.get("quality_status") == "closed_bar" and _is_positive_price(price)
        else None
    )


def tencent_quote_detail(
    symbol: str, market: str
) -> tuple[str | None, float | None, float | None, str | None]:
    if _market_fetch_disabled():
        return (None, None, None, "行情获取已由 QUANTHUB_DISABLE_MARKET_FETCH 禁用")
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
            return (None, None, None, "腾讯报价响应缺少有效载荷")
        parts = match.group(1).split("~")
        if len(parts) < 5:
            return (None, None, None, "腾讯报价响应字段不完整")
        return (
            parts[1].strip() or None,
            float(parts[3]) if parts[3] else None,
            float(parts[4]) if parts[4] else None,
            None,
        )
    except Exception as exc:  # noqa: BLE001 - provider-specific errors become an unavailable detail
        logging.getLogger(__name__).exception("腾讯报价失败 %s/%s", market, symbol)
        return (None, None, None, f"腾讯报价失败: {exc}")


def resolve_security_name(symbol: str, market: str, supplied: str = "") -> str:
    """Resolve display-only metadata; never supply a market price or identity."""
    if supplied.strip():
        return supplied.strip()
    if market in {"a_shares", "us_stocks"}:
        name, *_ = tencent_quote_detail(symbol, market)
        return name or ""
    return ""


def _quote_unavailable(
    symbol: str,
    market: str,
    name: str,
    observed_at: str,
    *,
    source: str,
    error: str,
) -> dict:
    """Build the one explicit unavailable response used by every quote branch."""
    return {
        "sym": symbol,
        "name": name,
        "market": market,
        "price": None,
        "chgPct": None,
        "available": False,
        "source": source or "unknown",
        "observed_at": observed_at,
        "freshness": "unavailable",
        "status": "unavailable",
        "error": error,
    }


def _quote_field(quote: object, field: str, default: object = None) -> object:
    """Read a RealtimeQuote field without accepting an alternate provider shape."""
    if isinstance(quote, dict):
        return quote.get(field, default)
    return getattr(quote, field, default)


def _quote_timestamp(value: object) -> str | None:
    if value is None:
        return None
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.isoformat()


def _quote_operation_plan(data_source: object, operation: str, interval: str | None = None) -> list:
    """Return the source's declared operation plan; missing metadata is failure."""
    planner = getattr(data_source, "source_plan", None)
    if not callable(planner):
        return []
    try:
        plan = planner(operation, interval) if interval is not None else planner(operation)
    except Exception:  # noqa: BLE001 - missing source capability is unavailable
        return []
    return plan if isinstance(plan, list) else []


def _quote_from_realtime(
    quote: object,
    *,
    symbol: str,
    market: str,
    requested_name: str,
    observed_at: str,
    primary_source: str,
) -> dict:
    source = _source_name(_quote_field(quote, "source"))
    quote_market = _source_name(_quote_field(quote, "market"))
    price = _quote_field(quote, "price")
    quote_time = _quote_timestamp(_quote_field(quote, "observed_at"))
    if (
        source != primary_source
        or quote_market != _source_name(market)
        or not _is_positive_price(price)
    ):
        return _quote_unavailable(
            symbol,
            market,
            requested_name,
            observed_at,
            source=source or primary_source,
            error="实时行情来源、市场或价格未通过 primary 校验",
        )
    if quote_time is None:
        return _quote_unavailable(
            symbol,
            market,
            requested_name,
            observed_at,
            source=source,
            error="实时行情缺少有效观察时间",
        )
    previous = _quote_field(quote, "prev_close")
    change = _quote_field(quote, "change_pct")
    if not _is_positive_price(previous):
        previous = None
    if not isinstance(change, Real) or isinstance(change, bool) or not math.isfinite(float(change)):
        change = ((float(price) - float(previous)) / float(previous) * 100) if previous else None
    return {
        "sym": symbol,
        "name": requested_name or str(_quote_field(quote, "name") or symbol),
        "market": market,
        "price": round(float(price), 2),
        "chgPct": round(float(change), 2) if change is not None else None,
        "available": True,
        "source": source,
        "observed_at": quote_time,
        "freshness": "live",
        "status": "available",
        "error": None,
    }


def quote_item(symbol: str, market: str, name: str = "") -> dict:
    """Return a quote from exactly one configured primary interface.

    A primary that declares realtime quotes is queried through that interface;
    its failure is terminal for this request.  Primaries without that capability
    may expose a daily bar, but only that primary's declared K-line interface is
    used and the bar itself supplies both price and change when available.
    """
    requested_name = name.strip()
    observed_at = datetime.now(UTC).isoformat()
    if _market_fetch_disabled():
        return _quote_unavailable(
            symbol,
            market,
            requested_name,
            observed_at,
            source="disabled",
            error="行情获取已由 QUANTHUB_DISABLE_MARKET_FETCH 禁用",
        )

    primary_source = _configured_primary_source(market)
    try:
        data_source = get_data_source(market)
    except Exception as exc:  # noqa: BLE001 - primary construction failure is explicit unavailable
        return _quote_unavailable(
            symbol,
            market,
            requested_name,
            observed_at,
            source=primary_source or "unknown",
            error=f"行情源失败: {exc}",
        )

    declared_source = _source_name(getattr(data_source, "name", None))
    if not primary_source or declared_source != primary_source:
        return _quote_unavailable(
            symbol,
            market,
            requested_name,
            observed_at,
            source=declared_source or primary_source,
            error="行情源与已配置 primary 不一致",
        )

    realtime_plan = _quote_operation_plan(data_source, "get_realtime_quote")
    if realtime_plan:
        try:
            realtime = data_source.get_realtime_quote(symbol)
        except Exception as exc:  # noqa: BLE001 - do not switch endpoint after primary failure
            return _quote_unavailable(
                symbol,
                market,
                requested_name,
                observed_at,
                source=primary_source,
                error=f"实时行情源失败: {exc}",
            )
        if realtime is None:
            return _quote_unavailable(
                symbol,
                market,
                requested_name,
                observed_at,
                source=primary_source,
                error="实时行情源未返回有效报价",
            )
        return _quote_from_realtime(
            realtime,
            symbol=symbol,
            market=market,
            requested_name=requested_name,
            observed_at=observed_at,
            primary_source=primary_source,
        )

    kline_plan = _quote_operation_plan(data_source, "get_kline", "1d")
    if not kline_plan:
        return _quote_unavailable(
            symbol,
            market,
            requested_name,
            observed_at,
            source=primary_source,
            error="primary 未声明实时行情或日线接口",
        )
    try:
        frame = data_source.get_kline(symbol, "1d", limit=2)
    except Exception as exc:  # noqa: BLE001 - the configured primary is terminal
        return _quote_unavailable(
            symbol,
            market,
            requested_name,
            observed_at,
            source=primary_source,
            error=f"行情源失败: {exc}",
        )
    if frame is None or frame.empty or "close" not in frame:
        return _quote_unavailable(
            symbol,
            market,
            requested_name,
            observed_at,
            source=primary_source,
            error="行情源未返回有效收盘价",
        )
    source, primary_source, source_role, _cache_status, _transport, _semantics = (
        _snapshot_provenance(frame, market, data_source)
    )
    bar_at = _bar_time(frame)
    closes = pd.to_numeric(frame["close"], errors="coerce").dropna().tolist()
    if (
        source != primary_source
        or source_role not in {"primary", "primary_cache"}
        or not bar_at
        or not closes
        or not _is_positive_price(closes[-1])
    ):
        return _quote_unavailable(
            symbol,
            market,
            requested_name,
            observed_at,
            source=source,
            error="行情来源或收盘价未通过 primary 校验",
        )
    price = float(closes[-1])
    previous = float(closes[-2]) if len(closes) >= 2 and _is_positive_price(closes[-2]) else None
    change = ((price - previous) / previous * 100) if previous else None
    return {
        "sym": symbol,
        "name": requested_name or symbol,
        "market": market,
        "price": round(price, 2),
        "chgPct": round(change, 2) if change is not None else None,
        "available": True,
        "source": source,
        "observed_at": bar_at,
        "freshness": "daily_close",
        "status": "available",
        "error": None,
    }


def portfolio_snapshot() -> dict:
    holdings = []
    total_value = total_cost = total_pnl = 0.0
    unpriced_positions = 0
    cached_positions = 0
    for item in repository.list_holdings():
        name = item["name"].strip()
        if not name:
            name = resolve_security_name(item["code"], item["market"])
            if name:
                repository.update_holding(item["id"], {"name": name})
        quote = latest_close_snapshot(item["code"], item["market"])
        raw_price = quote.get("price")
        price = float(raw_price) if _is_display_valuation_snapshot(quote) else None
        cost_value = item["cost"] * item["shares"]
        if price is None:
            unpriced_positions += 1
            holdings.append(
                {
                    **item,
                    "name": name,
                    "price": None,
                    "available": False,
                    "marketValue": None,
                    "costValue": round(cost_value, 2),
                    "chgPct": None,
                    "pnl": None,
                    "chgBasedScore": None,
                    "valuationStatus": "unavailable",
                    "marketSnapshot": quote,
                }
            )
            total_cost += cost_value
            continue
        value = price * item["shares"]
        pnl = value - cost_value
        change = ((price - item["cost"]) / item["cost"] * 100) if item["cost"] else 0.0
        valuation_status = str(quote.get("quality_status") or "unavailable")
        if valuation_status == "cached_primary":
            cached_positions += 1
        total_value += value
        total_cost += cost_value
        total_pnl += pnl
        holdings.append(
            {
                **item,
                "name": name,
                "price": round(price, 2),
                "available": valuation_status != "unavailable",
                "marketValue": round(value, 2),
                "costValue": round(cost_value, 2),
                "chgPct": round(change, 2),
                "pnl": round(pnl, 2),
                "chgBasedScore": round(min(99, max(1, 50 + change * 1.5)), 1),
                "valuationStatus": valuation_status,
                "marketSnapshot": quote,
            }
        )
    valuation_complete = unpriced_positions == 0
    pnl_percent = (total_pnl / total_cost * 100) if valuation_complete and total_cost else 0.0
    if not holdings:
        valuation_status = "available"
    elif not valuation_complete:
        valuation_status = "partial" if unpriced_positions < len(holdings) else "unavailable"
    elif cached_positions:
        valuation_status = "cached"
    else:
        valuation_status = "available"
    if not holdings:
        score = 0.0
    elif not valuation_complete:
        score = None
    else:
        score = round(sum(item["chgBasedScore"] for item in holdings) / len(holdings), 1)
    return {
        "ok": True,
        "summary": {
            # A missing quote must never be replaced with cost basis and exposed
            # as NAV. Keep cost basis separately for reconciliation instead.
            "nav": round(total_value, 2) if valuation_complete else None,
            "dailyPnl": round(total_pnl, 2) if valuation_complete else None,
            "dailyPnlPct": round(pnl_percent, 2) if valuation_complete else None,
            "cash": 0.0,
            "chgBasedScore": score,
            "totalPositions": len(holdings),
            "pricedPositions": len(holdings) - unpriced_positions,
            "unpricedPositions": unpriced_positions,
            "costBasis": round(total_cost, 2),
            "valuationStatus": valuation_status,
        },
        "holdings": holdings,
    }


def watchlist_snapshot(owner_id: str = "local-user") -> dict:
    output = []
    now = time.time()
    scheduled_macro = [
        event
        for event in store.list_macro_events(
            available_as_of=datetime.now(UTC),
            limit=200,
        )
        if event.get("state") == "scheduled"
        and isinstance((event.get("provenance") or {}).get("event_at"), str)
        and datetime.fromisoformat(event["provenance"]["event_at"]).timestamp() >= now
    ]
    scheduled_macro.sort(
        key=lambda event: datetime.fromisoformat(event["provenance"]["event_at"]).timestamp()
    )
    for item in repository.list_watchlist(owner_id):
        quote = quote_item(item["sym"], item["market"], item["name"])
        if not item["name"].strip() and quote.get("name"):
            repository.update_watchlist(item["id"], {"name": quote["name"]}, owner_id)
        runs = store.list_research_runs(
            limit=1,
            symbol=item["sym"],
            market=item["market"],
            owner_id=owner_id,
        )
        latest_run = runs[0] if runs else None
        decision = ((latest_run or {}).get("summary") or {}).get("research_decision") or {}
        updated_at = float(latest_run["updated_at"]) if latest_run else None
        output.append(
            {
                **quote,
                "id": item["id"],
                "latest_research_run_id": latest_run.get("id") if latest_run else None,
                "research_direction": decision.get("direction"),
                "research_execution_eligible": decision.get("execution_eligible") is True,
                "research_updated_at": updated_at,
                "evidence_age_hours": round((now - updated_at) / 3600, 2) if updated_at else None,
                "next_event": scheduled_macro[0] if scheduled_macro else None,
            }
        )
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
    primary_source = _configured_primary_source("a_shares")
    try:
        data_source = get_data_source("a_shares")
    except Exception as exc:  # noqa: BLE001 - display breadth has no secondary source
        return {
            "ok": True,
            "sample": True,
            "note": f"市场广度不可用：primary 行情源失败（{exc}）",
            "up": 0,
            "flat": 0,
            "down": 0,
            "sectors": [],
        }
    if _source_name(
        getattr(data_source, "name", None)
    ) != primary_source or not _quote_operation_plan(data_source, "get_realtime_quote"):
        return {
            "ok": True,
            "sample": True,
            "note": "市场广度不可用：已配置 primary 未声明实时行情能力",
            "up": 0,
            "flat": 0,
            "down": 0,
            "sectors": [],
        }
    up = flat = down = 0
    sectors: dict[str, list[float]] = {}
    for code, sector in CONFIG["breadth_basket"]:
        try:
            quote = data_source.get_realtime_quote(code)
        except Exception as exc:  # noqa: BLE001 - one primary failure stays missing
            logging.getLogger(__name__).warning(
                "primary 市场广度行情失败 %s/%s: %s", "a_shares", code, exc
            )
            continue
        source = _source_name(_quote_field(quote, "source"))
        quote_market = _source_name(_quote_field(quote, "market"))
        current = _quote_field(quote, "price")
        previous = _quote_field(quote, "prev_close")
        if (
            source != primary_source
            or quote_market != "a_shares"
            or not _is_positive_price(current)
            or not _is_positive_price(previous)
        ):
            continue
        current_value = float(current)
        previous_value = float(previous)
        change = (current_value - previous_value) / previous_value * 100
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
        "note": f"样本广度：一篮子代表性成分（{primary_source} primary 实时报价），非全市场涨跌家数",
        "up": up,
        "flat": flat,
        "down": down,
        "sectors": rows,
    }
