"""K线与行情数据服务（供 data 路由使用）。"""

from __future__ import annotations

import logging
import os
from typing import Any

import pandas as pd

from core.data_feed.factory import get_data_source

logger = logging.getLogger(__name__)


def fetch_kline(
    symbol: str, market: str = "a_shares", interval: str = "1h", limit: int = 240
) -> dict[str, Any]:
    """返回指定标的的 K 线（OHLCV），与原 main.py 中 /data/kline 行为一致。"""
    if os.environ.get("QUANTHUB_DISABLE_MARKET_FETCH") == "1":
        return {
            "ok": True,
            "source": "disabled",
            "symbol": symbol,
            "interval": interval,
            "count": 0,
            "candles": [],
        }
    try:
        ds = get_data_source(market)
        df = ds.get_kline(symbol, interval, limit=limit)
    except Exception as exc:
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
        # A frame without adapter provenance must never be relabelled as a
        # trusted local source. Downstream risk gates treat ``unknown`` as
        # non-executable until the adapter supplies its source contract.
        "source": df.attrs.get("_source", "unknown"),
        "symbol": symbol,
        "interval": interval,
        "count": len(candles),
        "candles": candles,
    }
