"""真实行情接入（OKX）与可复现快照管理。

模拟实验室共有三条数据通道，均可在同一套回测流水线上运行：

- ``okx_local``：本地归档的**真实 OKX K 线**（``data/OKX_K线数据/{SYMBOL}_{TF}.parquet``）。
  完全离线、天然可复现，适合反复对比因子与策略。
- ``okx_live``：经 ccxt 调用 **OKX 公共行情接口**实时拉取。首次拉取即落盘快照
  （``data/market_cache/okx/*.json``），同参数复跑直接命中快照，因此"实时取数"
  与"可复现"两个要求同时满足。
- ``synthetic``：确定性合成数据，见 ``core.backtest.dataset``（无网络依赖）。

所有通道最终都输出同一张表：``[datetime, open, high, low, close, volume]``，
并附带 ``fingerprint``（数据内容 sha256），用于证明两次运行用的是同一份数据。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# 本地真实 OKX K 线归档目录（仓库内已有 19 个币种 × 4 个周期）
LOCAL_ARCHIVE_DIR = Path("data/OKX_K线数据")
# 实时拉取的快照缓存目录（保证可复现）
MARKET_CACHE_DIR = Path("data/market_cache/okx")
# 本地归档索引缓存（避免每次扫描 70+ 个 parquet）
LOCAL_INDEX_PATH = Path("data/market_cache/okx_local_index.json")

# 统一周期 -> 本地归档文件后缀
LOCAL_INTERVAL_TO_SUFFIX: dict[str, str] = {
    "5m": "M5",
    "15m": "M15",
    "1h": "H1",
    "1d": "D1",
}
# 实时通道支持的周期（OKX 公共接口原生支持）
LIVE_INTERVALS: tuple[str, ...] = ("1m", "5m", "15m", "30m", "1h", "4h", "1d")

INTERVAL_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}

OHLCV_COLUMNS = ["datetime", "open", "high", "low", "close", "volume"]


class MarketDataError(RuntimeError):
    """行情获取失败（缺少归档 / 网络不可用 / 参数非法）。"""


@dataclass
class MarketSnapshot:
    """一次取数的结果与其可复现凭据。"""

    df: pd.DataFrame
    source: str
    symbol: str
    interval: str
    fingerprint: str
    provenance: dict[str, Any]


# ---------------------------------------------------------------- 公共工具


def fingerprint_frame(df: pd.DataFrame) -> str:
    """对 OHLCV 内容做规范化 sha256，作为"同一份数据"的证据。"""
    hasher = hashlib.sha256()
    for row in df.itertuples(index=False):
        line = (
            f"{pd.Timestamp(row.datetime).isoformat()}|"
            f"{float(row.open):.8f}|{float(row.high):.8f}|{float(row.low):.8f}|"
            f"{float(row.close):.8f}|{float(row.volume):.8f}\n"
        )
        hasher.update(line.encode("utf-8"))
    return hasher.hexdigest()


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MarketDataError(f"无法解析时间: {value}（请使用 YYYY-MM-DD 或 ISO 格式）") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def current_bar_boundary(interval: str, *, now: datetime | None = None) -> datetime:
    """Return the UTC opening timestamp for the current interval bar."""
    minutes = INTERVAL_MINUTES.get(interval)
    if minutes is None:
        raise MarketDataError(f"无法计算未知周期 {interval} 的 K 线边界")
    current = now or datetime.now(UTC)
    current = current.replace(tzinfo=UTC) if current.tzinfo is None else current.astimezone(UTC)
    interval_seconds = minutes * 60
    boundary_seconds = int(current.timestamp()) // interval_seconds * interval_seconds
    return datetime.fromtimestamp(boundary_seconds, UTC)


def _normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df[OHLCV_COLUMNS].copy()
    out["datetime"] = pd.to_datetime(out["datetime"], utc=True)
    for column in ("open", "high", "low", "close", "volume"):
        out[column] = out[column].astype(float)
    out = out.dropna().sort_values("datetime").drop_duplicates("datetime")
    return out.reset_index(drop=True)


# ---------------------------------------------------------------- 本地归档通道


def _scan_local_archive() -> dict[str, Any]:
    """扫描本地归档，产出 {symbol: {interval: {rows, first, last}}} 索引。"""
    if not LOCAL_ARCHIVE_DIR.exists():
        return {"built_at": datetime.now(UTC).isoformat(), "symbols": {}}

    suffix_to_interval = {value: key for key, value in LOCAL_INTERVAL_TO_SUFFIX.items()}
    symbols: dict[str, dict[str, Any]] = {}
    for path in sorted(LOCAL_ARCHIVE_DIR.glob("*.parquet")):
        parts = path.stem.split("_")
        if len(parts) != 2:
            continue
        raw_symbol, raw_suffix = parts
        interval = suffix_to_interval.get(raw_suffix)
        if interval is None or not raw_symbol.isupper():
            continue
        try:
            frame = pd.read_parquet(path, columns=["time"])
        except Exception as exc:  # noqa: BLE001 - 单个损坏文件不应阻断整体索引
            logger.warning("读取归档失败 %s: %s", path.name, exc)
            continue
        if frame.empty:
            continue
        first = datetime.fromtimestamp(int(frame["time"].min()), UTC)
        last = datetime.fromtimestamp(int(frame["time"].max()), UTC)
        symbols.setdefault(raw_symbol, {})[interval] = {
            "rows": int(len(frame)),
            "first": first.isoformat(),
            "last": last.isoformat(),
            "file": path.name,
        }
    return {"built_at": datetime.now(UTC).isoformat(), "symbols": symbols}


def local_archive_index(refresh: bool = False) -> dict[str, Any]:
    """返回本地归档索引（带磁盘缓存，24 小时或显式 refresh 时重建）。"""
    if not refresh and LOCAL_INDEX_PATH.exists():
        try:
            cached = json.loads(LOCAL_INDEX_PATH.read_text(encoding="utf-8"))
            built_at = datetime.fromisoformat(cached["built_at"])
            if datetime.now(UTC) - built_at < timedelta(hours=24):
                return cached
        except Exception as exc:  # noqa: BLE001 - 缓存损坏时重建即可
            logger.warning("归档索引缓存不可用，重建: %s", exc)

    index = _scan_local_archive()
    try:
        LOCAL_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOCAL_INDEX_PATH.write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        logger.warning("归档索引写入失败: %s", exc)
    return index


def list_local_symbols() -> list[dict[str, Any]]:
    """供前端下拉：本地归档可用标的及其周期覆盖区间。"""
    index = local_archive_index()
    rows: list[dict[str, Any]] = []
    for symbol, intervals in sorted(index["symbols"].items()):
        base = symbol.removesuffix("USDT")
        rows.append(
            {
                "symbol": symbol,
                "label": f"{base}/USDT",
                "intervals": sorted(intervals.keys(), key=lambda k: INTERVAL_MINUTES.get(k, 0)),
                "coverage": intervals,
            }
        )
    return rows


def load_local_ohlcv(
    symbol: str,
    interval: str = "1d",
    *,
    n_bars: int = 250,
    start: str | None = None,
    end: str | None = None,
) -> MarketSnapshot:
    """从本地归档读取真实 OKX K 线。

    区间语义：给定 ``start`` 时从该时刻起向后取 ``n_bars`` 根；未给定时取最新 ``n_bars`` 根。
    ``end`` 可进一步截断。
    """
    suffix = LOCAL_INTERVAL_TO_SUFFIX.get(interval)
    if suffix is None:
        raise MarketDataError(
            f"本地归档不支持周期 {interval}（可用: {', '.join(LOCAL_INTERVAL_TO_SUFFIX)}）"
        )
    path = LOCAL_ARCHIVE_DIR / f"{symbol.upper()}_{suffix}.parquet"
    if not path.exists():
        raise MarketDataError(f"本地归档缺少数据文件: {path.name}")

    raw = pd.read_parquet(path)
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(raw["time"].astype("int64"), unit="s", utc=True),
            "open": raw["open"].astype(float),
            "high": raw["high"].astype(float),
            "low": raw["low"].astype(float),
            "close": raw["close"].astype(float),
            "volume": raw["tick_volume"].astype(float),
        }
    )
    frame = _normalize_frame(frame)
    total_rows = len(frame)
    available_first = frame["datetime"].iloc[0].isoformat() if total_rows else None
    available_last = frame["datetime"].iloc[-1].isoformat() if total_rows else None

    start_at = _parse_time(start)
    end_at = _parse_time(end)
    if start_at is not None:
        frame = frame[frame["datetime"] >= pd.Timestamp(start_at)]
    if end_at is not None:
        frame = frame[frame["datetime"] <= pd.Timestamp(end_at)]
    if frame.empty:
        raise MarketDataError(
            f"{symbol} {interval} 在所选区间内无数据"
            f"（归档覆盖 {available_first} ~ {available_last}）"
        )

    frame = frame.head(n_bars) if start_at is not None else frame.tail(n_bars)
    frame = frame.reset_index(drop=True)

    return MarketSnapshot(
        df=frame,
        source="okx_local",
        symbol=symbol.upper(),
        interval=interval,
        fingerprint=fingerprint_frame(frame),
        provenance={
            "channel": "本地归档真实 OKX K 线",
            "file": str(path).replace("\\", "/"),
            "archive_rows": total_rows,
            "archive_first": available_first,
            "archive_last": available_last,
            "selected_first": frame["datetime"].iloc[0].isoformat(),
            "selected_last": frame["datetime"].iloc[-1].isoformat(),
            "bars": int(len(frame)),
            "offline": True,
            "reproducible": "文件内容不变即完全可复现",
        },
    )


# ---------------------------------------------------------------- 实时通道


# 实时可选标的（OKX instId 语义；SWAP 为 USDT 本位永续）
LIVE_SYMBOLS: list[dict[str, str]] = [
    {"symbol": "BTC-USDT-SWAP", "label": "BTC/USDT 永续", "kind": "swap"},
    {"symbol": "ETH-USDT-SWAP", "label": "ETH/USDT 永续", "kind": "swap"},
    {"symbol": "SOL-USDT-SWAP", "label": "SOL/USDT 永续", "kind": "swap"},
    {"symbol": "XRP-USDT-SWAP", "label": "XRP/USDT 永续", "kind": "swap"},
    {"symbol": "DOGE-USDT-SWAP", "label": "DOGE/USDT 永续", "kind": "swap"},
    {"symbol": "BTC-USDT", "label": "BTC/USDT 现货", "kind": "spot"},
    {"symbol": "ETH-USDT", "label": "ETH/USDT 现货", "kind": "spot"},
    {"symbol": "SOL-USDT", "label": "SOL/USDT 现货", "kind": "spot"},
]


def to_ccxt_symbol(inst_id: str) -> str:
    """OKX instId -> ccxt 统一符号。BTC-USDT-SWAP -> BTC/USDT:USDT；BTC-USDT -> BTC/USDT。"""
    parts = inst_id.upper().split("-")
    if len(parts) == 3 and parts[2] == "SWAP":
        return f"{parts[0]}/{parts[1]}:{parts[1]}"
    if len(parts) == 2:
        return f"{parts[0]}/{parts[1]}"
    raise MarketDataError(f"无法识别的 OKX 标的: {inst_id}")


def _cache_key(symbol: str, interval: str, n_bars: int, start: str | None, end: str | None) -> str:
    raw = f"{symbol}|{interval}|{n_bars}|{start or ''}|{end or ''}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _cache_path(symbol: str, interval: str, key: str) -> Path:
    safe_symbol = symbol.replace("/", "-").replace(":", "-")
    return MARKET_CACHE_DIR / f"{safe_symbol}_{interval}_{key}.json"


def _frame_from_rows(rows: list[list[float]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    frame["datetime"] = pd.to_datetime(frame["ts"].astype("int64"), unit="ms", utc=True)
    return _normalize_frame(frame)


def _build_public_exchange() -> Any:
    try:
        import ccxt
    except ImportError as exc:  # pragma: no cover - 依赖缺失时的清晰报错
        raise MarketDataError("实时行情需要 ccxt 依赖（uv sync --group crypto）") from exc

    exchange = ccxt.okx({"enableRateLimit": True})
    # ccxt 默认 trust_env=False 会忽略系统代理；本机 OKX 走代理访问，必须显式打开
    exchange.session.trust_env = True
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    if proxy:
        exchange.proxies = {"http": proxy, "https": proxy}
    return exchange


def fetch_live_ohlcv(
    symbol: str = "BTC-USDT-SWAP",
    interval: str = "1d",
    *,
    n_bars: int = 250,
    start: str | None = None,
    end: str | None = None,
    use_cache: bool = True,
    allow_partial: bool = False,
) -> MarketSnapshot:
    """从 OKX 公共行情接口拉取真实 K 线，并落盘快照保证可复现。

    命中快照时不发起网络请求；``use_cache=False`` 可强制刷新（会覆盖同参数快照）。
    """
    if interval not in LIVE_INTERVALS:
        raise MarketDataError(f"实时通道不支持周期 {interval}（可用: {', '.join(LIVE_INTERVALS)}）")

    key = _cache_key(symbol, interval, n_bars, start, end)
    path = _cache_path(symbol, interval, key)

    if use_cache and path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            frame = _frame_from_rows(payload["rows"])
            if start is None and len(frame) < n_bars and not allow_partial:
                raise ValueError(f"快照只有 {len(frame)} 根，少于请求的 {n_bars} 根")
            return MarketSnapshot(
                df=frame,
                source="okx_live",
                symbol=symbol,
                interval=interval,
                fingerprint=payload.get("fingerprint") or fingerprint_frame(frame),
                provenance={
                    "channel": "OKX 公共行情接口（命中本地快照）",
                    "cache_hit": True,
                    "cache_file": str(path).replace("\\", "/"),
                    "fetched_at": payload.get("fetched_at"),
                    "ccxt_symbol": payload.get("ccxt_symbol"),
                    "requested_bars": n_bars,
                    "partial": len(frame) < n_bars,
                    "requested_start": start,
                    "requested_end": end,
                    "bars": int(len(frame)),
                    "selected_first": frame["datetime"].iloc[0].isoformat(),
                    "selected_last": frame["datetime"].iloc[-1].isoformat(),
                    "offline": True,
                    "reproducible": "快照文件存在即完全可复现",
                },
            )
        except Exception as exc:  # noqa: BLE001 - 快照损坏时回落到真实拉取
            logger.warning("行情快照不可用，改为实时拉取: %s", exc)

    ccxt_symbol = to_ccxt_symbol(symbol)
    exchange = _build_public_exchange()
    start_at = _parse_time(start)
    end_at = _parse_time(end)
    minutes = INTERVAL_MINUTES.get(interval, 1440)

    rows: list[list[float]] = []
    fetched_at = datetime.now(UTC)
    try:
        interval_ms = minutes * 60_000
        window_anchor = end_at or fetched_at
        effective_start = start_at or (window_anchor - timedelta(minutes=minutes * (n_bars + 5)))
        since = int(effective_start.timestamp() * 1000)
        limit_ts = int((end_at or fetched_at).timestamp() * 1000)
        target_rows = n_bars if start_at is not None else n_bars + 5
        seen_timestamps: set[int] = set()
        while len(seen_timestamps) < target_rows and since <= limit_ts:
            batch_limit = min(300, target_rows - len(seen_timestamps))
            batch = exchange.fetch_ohlcv(ccxt_symbol, interval, since, batch_limit)
            if not batch:
                break
            new_rows = [
                item
                for item in batch
                if int(item[0]) <= limit_ts and int(item[0]) not in seen_timestamps
            ]
            if not new_rows:
                break
            rows.extend(new_rows)
            seen_timestamps.update(int(item[0]) for item in new_rows)
            next_since = max(int(item[0]) for item in new_rows) + interval_ms
            if next_since <= since:
                break
            since = next_since
            if since > limit_ts:
                break
            time.sleep(exchange.rateLimit / 1000)
    except MarketDataError:
        raise
    except Exception as exc:  # noqa: BLE001 - ccxt 抛出交易所专有异常
        raise MarketDataError(f"OKX 实时行情拉取失败: {type(exc).__name__}: {exc}") from exc

    if not rows:
        raise MarketDataError(f"OKX 未返回 {symbol} {interval} 的行情数据")

    frame = _frame_from_rows(rows)
    if end_at is not None:
        frame = frame[frame["datetime"] <= pd.Timestamp(end_at)]
    frame = (frame.head(n_bars) if start_at is not None else frame.tail(n_bars)).reset_index(
        drop=True
    )
    if frame.empty:
        raise MarketDataError(f"{symbol} {interval} 在所选区间内无数据")
    if start_at is None and len(frame) < n_bars and not allow_partial:
        raise MarketDataError(
            f"OKX 仅返回 {len(frame)} 根 {symbol} {interval} K 线，少于请求的 {n_bars} 根"
        )

    digest = fingerprint_frame(frame)
    cache_written = False
    try:
        MARKET_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "symbol": symbol,
                    "ccxt_symbol": ccxt_symbol,
                    "interval": interval,
                    "n_bars": n_bars,
                    "start": start,
                    "end": end,
                    "fetched_at": fetched_at.isoformat(),
                    "fingerprint": digest,
                    "rows": [
                        [
                            int(pd.Timestamp(item.datetime).timestamp() * 1000),
                            float(item.open),
                            float(item.high),
                            float(item.low),
                            float(item.close),
                            float(item.volume),
                        ]
                        for item in frame.itertuples(index=False)
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        cache_written = True
    except OSError as exc:
        logger.warning("行情快照写入失败: %s", exc)

    return MarketSnapshot(
        df=frame,
        source="okx_live",
        symbol=symbol,
        interval=interval,
        fingerprint=digest,
        provenance={
            "channel": "OKX 公共行情接口（实时拉取）",
            "cache_hit": False,
            "cache_written": cache_written,
            "cache_file": str(path).replace("\\", "/"),
            "fetched_at": fetched_at.isoformat(),
            "ccxt_symbol": ccxt_symbol,
            "requested_bars": n_bars,
            "partial": len(frame) < n_bars,
            "requested_start": start,
            "requested_end": end,
            "bars": int(len(frame)),
            "selected_first": frame["datetime"].iloc[0].isoformat(),
            "selected_last": frame["datetime"].iloc[-1].isoformat(),
            "offline": False,
            "reproducible": "快照已落盘，同参数复跑将命中快照",
        },
    )


# ---------------------------------------------------------------- 统一入口


def list_sources() -> list[dict[str, Any]]:
    """供前端下拉：三条数据通道的说明与能力。"""
    local = list_local_symbols()
    return [
        {
            "key": "okx_local",
            "label": "OKX 真实行情（本地归档）",
            "description": "仓库内已归档的真实 OKX K 线，离线可跑、结果完全可复现",
            "realtime": False,
            "needs_network": False,
            "intervals": list(LOCAL_INTERVAL_TO_SUFFIX.keys()),
            "symbols": [{"symbol": row["symbol"], "label": row["label"]} for row in local],
            "symbol_coverage": {row["symbol"]: row["coverage"] for row in local},
        },
        {
            "key": "okx_live",
            "label": "OKX 真实行情（实时拉取）",
            "description": "经公共行情接口实时取数，首拉即落盘快照，同参数复跑命中快照",
            "realtime": True,
            "needs_network": True,
            "intervals": list(LIVE_INTERVALS),
            "symbols": [{"symbol": row["symbol"], "label": row["label"]} for row in LIVE_SYMBOLS],
            "symbol_coverage": {},
        },
        {
            "key": "synthetic",
            "label": "合成行情（确定性）",
            "description": "按 seed 生成的确定性行情，用于压力形态测试，不含真实市场数据",
            "realtime": False,
            "needs_network": False,
            "intervals": list(INTERVAL_MINUTES.keys()),
            "symbols": [],
            "symbol_coverage": {},
        },
    ]


def load_market_data(
    source: str,
    *,
    symbol: str | None = None,
    interval: str = "1d",
    n_bars: int = 250,
    start: str | None = None,
    end: str | None = None,
    use_cache: bool = True,
    allow_partial: bool = False,
) -> MarketSnapshot:
    """按数据源统一取数（真实通道专用；合成通道由 dataset 模块负责）。"""
    if source == "okx_local":
        if not symbol:
            raise MarketDataError("本地归档通道必须指定标的")
        return load_local_ohlcv(symbol, interval, n_bars=n_bars, start=start, end=end)
    if source == "okx_live":
        return fetch_live_ohlcv(
            symbol or "BTC-USDT-SWAP",
            interval,
            n_bars=n_bars,
            start=start,
            end=end,
            use_cache=use_cache,
            allow_partial=allow_partial,
        )
    raise MarketDataError(f"未知真实数据源: {source}")
