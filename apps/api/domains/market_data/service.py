from __future__ import annotations

import time

from core.config import get_config
from core.data_feed.cache import CacheStore
from core.data_feed.factory import get_configured_source, get_data_source
from core.data_feed.telemetry import telemetry

from .schemas import DataSourceCheckRequest


def data_source_status() -> dict:
    configured = []
    for market in ("a_shares", "crypto"):
        cfg = get_config(market).get("data_sources", {})
        proxy = get_data_source(market)
        configured.append(
            {
                "market": market,
                "primary": cfg.get("primary"),
                "plans": {
                    "kline": {
                        interval: proxy.source_plan("get_kline", interval)
                        for interval in ("1m", "5m", "15m", "30m", "1h", "1d", "1w")
                    },
                    "news": proxy.source_plan("get_news"),
                    "announcements": proxy.source_plan("get_announcements"),
                },
            }
        )
    snapshot = telemetry.snapshot().to_dict()
    return {
        "ok": True,
        "configured": configured,
        "sources": snapshot["sources"],
        "cache": {**snapshot["cache"], **CacheStore().stats()},
        "generated_at": snapshot["generated_at"],
    }


def check_data_source(req: DataSourceCheckRequest) -> dict:
    source = get_configured_source(req.market, req.source)
    started = time.perf_counter()
    try:
        if req.operation == "get_kline":
            result = source.get_kline(req.symbol, req.interval, limit=2)
            count = 0 if result is None else len(result)
        elif req.operation == "get_news":
            result = source.get_news(req.symbol, limit=1)
            count = len(result or [])
        else:
            result = source.get_announcements(req.symbol, limit=1)
            count = len(result or [])
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        ok = count > 0
        error = None if ok else "empty_result"
        telemetry.record_source(
            req.source, req.operation, success=ok, latency_ms=latency_ms, error=error
        )
        return {
            "ok": ok,
            "source": req.source,
            "operation": req.operation,
            "count": count,
            "latency_ms": latency_ms,
            "error": error,
        }
    except Exception as exc:  # noqa: BLE001 - adapters expose heterogeneous failures
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        error = str(exc)
        telemetry.record_source(
            req.source, req.operation, success=False, latency_ms=latency_ms, error=error
        )
        return {
            "ok": False,
            "source": req.source,
            "operation": req.operation,
            "count": 0,
            "latency_ms": latency_ms,
            "error": error,
        }
