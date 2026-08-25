"""A 股实时分析器的数据适配。

所有行情都从 ``core.data_feed`` 的已配置 primary 获取。这里不再保留
东方财富、腾讯直连或跨供应商回退；空结果和 provider 错误由调用方按
不可发布信号处理。
"""

from __future__ import annotations

import logging
import math
import re
import statistics
from typing import Any

from core.data_feed.base import DataSource, Interval, RealtimeQuote
from core.data_feed.factory import get_data_source

_INDEX_SYMBOLS = (
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sz399006", "创业板指"),
)
logger = logging.getLogger(__name__)


def normalize_code(code: str) -> str:
    c = code.strip().upper().replace(" ", "")
    if (c.startswith("SH") and len(c) == 8 and c[2:].isdigit()) or (
        c.startswith("SZ") and len(c) == 8 and c[2:].isdigit()
    ):
        c = c[2:]
    if "." in c:
        left, right = c.split(".", 1)
        if left.isdigit() and right in {"SH", "SS", "SZ"}:
            c = left
    if not re.fullmatch(r"\d{6}", c):
        raise ValueError(f"Unsupported code format: {code}")
    return c


def parse_codes(raw: str) -> list[str]:
    parts = [x for x in re.split(r"[,，\s]+", raw.strip()) if x]
    out: list[str] = []
    for part in parts:
        try:
            code = normalize_code(part)
        except ValueError:
            continue
        if code not in out:
            out.append(code)
    return out


def fetch_quotes(codes: list[str], *, source: DataSource | None = None) -> list[dict]:
    """Return only complete provider quotes from the configured A-share primary."""
    if not codes:
        return []
    source = source or get_data_source("a_shares")
    quotes: list[dict] = []
    for code in codes:
        try:
            quote = source.get_realtime_quote(code)
        except Exception as exc:  # noqa: BLE001 - the strategy records an explicit rejection
            logger.warning("A股 primary 实时行情失败 %s，不切换数据源: %s", code, exc)
            continue
        if quote is not None:
            quotes.append(_quote_dict(quote, code))
    return quotes


def fetch_index_baseline(*, source: DataSource | None = None) -> list[dict]:
    """Fetch index snapshots from the same primary; breadth is intentionally absent.

    The former Eastmoney breadth endpoint was a second provider. A missing
    breadth value is reported as missing evidence instead of being filled from
    that old path.
    """
    source = source or get_data_source("a_shares")
    rows: list[dict] = []
    for symbol, display_name in _INDEX_SYMBOLS:
        try:
            quote = source.get_realtime_quote(symbol)
        except Exception as exc:  # noqa: BLE001 - optional context must not change primary
            logger.warning("A股 primary 指数行情失败 %s，不切换数据源: %s", symbol, exc)
            continue
        if quote is None:
            continue
        row = _quote_dict(quote, symbol)
        row["name"] = quote.name or display_name
        row["up_count"] = None
        row["down_count"] = None
        row["breadth_available"] = False
        rows.append(row)
    return rows


def fetch_kline(code: str, days: int = 60, *, source: DataSource | None = None) -> dict:
    """Return daily bars from the same configured primary, without local fallback."""
    source = source or get_data_source("a_shares")
    source_name = str(getattr(source, "name", "unknown"))
    try:
        frame = source.get_kline(code, Interval.DAILY, limit=days)
    except Exception:  # noqa: BLE001 - the strategy handles insufficient evidence
        return _empty_kline(source_name)
    if frame is None or frame.empty:
        return _empty_kline(source_name)

    klines: list[dict[str, Any]] = []
    closes: list[float] = []
    for _, row in frame.iterrows():
        close = _finite_float(row.get("close"))
        if close is None:
            continue
        timestamp = row.get("datetime")
        date = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
        klines.append(
            {
                "date": date,
                "open": _finite_float(row.get("open")),
                "close": close,
                "high": _finite_float(row.get("high")),
                "low": _finite_float(row.get("low")),
                "volume": _finite_float(row.get("volume")),
            }
        )
        closes.append(close)

    metrics = {
        "latest_date": klines[-1]["date"] if klines else None,
        "close": closes[-1] if closes else None,
        "ret_5d_pct": _ret(closes, 5),
        "ret_10d_pct": _ret(closes, 10),
        "ret_20d_pct": _ret(closes, 20),
        "ma5": _ma(closes, 5),
        "ma10": _ma(closes, 10),
        "ma20": _ma(closes, 20),
        "high_10d": max(closes[-10:]) if len(closes) >= 10 else (max(closes) if closes else None),
        "low_10d": min(closes[-10:]) if len(closes) >= 10 else (min(closes) if closes else None),
    }
    contract = frame.attrs.get("_data_contract", {})
    return {
        "metrics": metrics,
        "klines": klines,
        "available": bool(klines),
        "source": str(frame.attrs.get("_source") or source_name),
        "semantics": contract.get("kline_semantics", "bar_snapshot"),
    }


def _quote_dict(quote: RealtimeQuote, requested_symbol: str) -> dict:
    return {
        "code": requested_symbol.upper(),
        "name": quote.name,
        "last": quote.price,
        "pct": quote.change_pct,
        "prev_close": quote.prev_close,
        "source": quote.source,
        "market": quote.market,
        "observed_at": quote.observed_at.isoformat(),
        "verified": True,
    }


def _finite_float(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _empty_kline(source_name: str) -> dict:
    return {
        "metrics": {},
        "klines": [],
        "available": False,
        "source": source_name,
        "semantics": "bar_snapshot",
    }


def _ma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return round(statistics.mean(values[-window:]), 4)


def _ret(values: list[float], window: int) -> float | None:
    if len(values) <= window:
        return None
    base = values[-(window + 1)]
    if not base:
        return None
    return round((values[-1] / base - 1) * 100, 4)
