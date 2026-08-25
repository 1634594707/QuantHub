"""数据源工厂。

按 market + name 创建唯一的 configured primary DataSource。
所有 source 调用经 CacheStore 透明缓存；primary 失败或返回空结果时不切换供应商。
"""

from __future__ import annotations

import functools
import logging
import time
from pathlib import Path
from typing import Any

import pandas as pd

from core.config import get_config
from core.data_feed.base import Announcement, DataSource, Interval, News, RealtimeQuote
from core.data_feed.cache import CacheStore, cache_key_date
from core.data_feed.telemetry import telemetry

logger = logging.getLogger(__name__)


def _source_contract(source: DataSource) -> dict:
    """Normalize legacy and third-party adapters into serializable metadata."""
    try:
        contract = source.data_contract()
    except (AttributeError, TypeError):
        contract = None
    if isinstance(contract, dict):
        return contract
    return {
        "name": str(source.name),
        "market": str(source.market),
        "operations": ["get_kline"],
        "intervals": [item.value for item in Interval],
        "kline_semantics": "bar_snapshot",
        "realtime_quote_semantics": None,
        "tick_by_tick": False,
    }


def _cached(fn):
    """装饰 get_kline/get_news/get_announcements，自动读写缓存。"""

    @functools.wraps(fn)
    def wrapper(self: DataSourceProxy, *args, **kwargs):
        kind = fn.__name__
        cache: CacheStore = self._cache
        if cache is None:
            return fn(self, *args, **kwargs)

        if kind == "get_kline":
            symbol = args[0]
            interval = args[1] if len(args) > 1 else kwargs.get("interval")
            interval = Interval(interval).value if not isinstance(interval, str) else interval
            start = args[2] if len(args) > 2 else kwargs.get("start")
            end = args[3] if len(args) > 3 else kwargs.get("end")
            limit = args[4] if len(args) > 4 else kwargs.get("limit", 500)
            bounded_request = start is not None or end is not None
            date = cache_key_date()
            hit = (
                None
                if bounded_request
                else cache.get_kline(
                    symbol,
                    self.market,
                    interval,
                    date,
                    source=self.name,
                    limit=limit,
                )
            )
            if (
                hit is not None
                and self.market == "us_stocks"
                and len(hit) < min(int(limit or 0), 20)
            ):
                logger.info(
                    "忽略美股短历史缓存 %s %s: %d/%d 条",
                    symbol,
                    interval,
                    len(hit),
                    limit,
                )
                hit = None
            if hit is not None and not hit.empty:
                telemetry.record_cache(hit=True)
                logger.debug("缓存命中 kline %s %s limit=%s", symbol, interval, limit)
                return hit
            telemetry.record_cache(hit=False)
            df = fn(self, *args, **kwargs)
            if df is not None and not df.empty and not bounded_request:
                cache.set_kline(
                    symbol,
                    self.market,
                    interval,
                    date,
                    df,
                    source=self.name,
                    limit=limit,
                )
            return df

        if kind in ("get_news", "get_announcements"):
            symbol = args[0] if args else kwargs.get("symbol")
            limit = args[1] if len(args) > 1 else kwargs.get("limit", 50)
            docs = cache.get_docs(
                kind,
                symbol,
                market=self.market,
                source=self.name,
                limit=limit,
            )
            if docs:
                telemetry.record_cache(hit=True)
                # 重建对象
                if kind == "get_news":
                    return [News(**d) for d in docs]
                return [Announcement(**d) for d in docs]
            telemetry.record_cache(hit=False)
            result = fn(self, *args, **kwargs)
            # 空结果不入缓存：避免将 primary 的短暂不可用永久固化为无数据。
            if not result:
                return result
            try:
                payload = [{**d.__dict__, "ts": d.ts.isoformat()} for d in result]
                cache.set_docs(
                    kind,
                    symbol,
                    payload,
                    market=self.market,
                    source=self.name,
                    limit=limit,
                )
            except Exception:
                logger.debug("缓存写入失败 %s", kind, exc_info=True)
            return result
        return fn(self, *args, **kwargs)

    return wrapper


class DataSourceProxy(DataSource):
    """数据源代理：包装唯一 primary，叠加缓存但绝不切换供应商。"""

    def __init__(self, primary: DataSource, cache: CacheStore | None = None) -> None:
        # Older callers passed a positional list of secondary providers here.
        # Reject that shape at construction time instead of accepting it as a
        # truthy cache object and failing later (or, worse, reviving a hidden
        # provider chain through duck-typed methods).
        if isinstance(cache, (list, tuple, set, dict)):
            raise TypeError("DataSourceProxy 只接受单一 primary；不再接受 fallback 数据源列表")
        self._primary = primary
        self._cache = cache or CacheStore()
        self.name = primary.name
        self.market = primary.market

    def supported_intervals(self):
        return self._primary.supported_intervals()

    def data_contract(self) -> dict:
        """Expose only the configured primary's capabilities."""
        return _source_contract(self._primary)

    def source_plan(self, operation: str, interval: Interval | str | None = None) -> list[dict]:
        """Expose the single configured primary after capability filtering."""
        normalized_interval = Interval(interval) if isinstance(interval, str) else interval
        contract = _source_contract(self._primary)
        if operation not in contract["operations"]:
            return []
        if (
            operation == "get_kline"
            and normalized_interval is not None
            and normalized_interval.value not in contract["intervals"]
        ):
            return []
        return [{"priority": 1, **contract}]

    def get_realtime_quote(self, symbol: str) -> RealtimeQuote | None:
        """Read a live quote from the one configured primary without caching.

        A missing capability, empty result, or provider failure remains visible
        to the caller; it never triggers a secondary market/source lookup.
        """
        src = self._primary
        if not self.source_plan("get_realtime_quote"):
            raise RuntimeError(f"数据源 {src.name} 未声明实时行情能力")
        started = time.perf_counter()
        try:
            quote = src.get_realtime_quote(symbol)
        except Exception as exc:  # noqa: BLE001 - preserve provider failure without fallback
            telemetry.record_source(
                src.name,
                "get_realtime_quote",
                success=False,
                latency_ms=(time.perf_counter() - started) * 1000,
                error=str(exc),
            )
            logger.warning("数据源 %s get_realtime_quote 失败，不切换数据源: %s", src.name, exc)
            raise
        telemetry.record_source(
            src.name,
            "get_realtime_quote",
            success=quote is not None,
            latency_ms=(time.perf_counter() - started) * 1000,
            error=None if quote is not None else "empty_result",
        )
        return quote

    @_cached
    def get_kline(self, symbol, interval, start=None, end=None, limit=500) -> pd.DataFrame:
        src = self._primary
        plan = self.source_plan("get_kline", interval)
        started = time.perf_counter()
        try:
            df = src.get_kline(symbol, interval, start, end, limit)
        except Exception as exc:  # noqa: BLE001 - preserve provider failure without fallback
            telemetry.record_source(
                src.name,
                "get_kline",
                success=False,
                latency_ms=(time.perf_counter() - started) * 1000,
                error=str(exc),
            )
            logger.warning("数据源 %s get_kline 失败，不切换数据源: %s", src.name, exc)
            raise
        if df is None or df.empty:
            telemetry.record_source(
                src.name,
                "get_kline",
                success=False,
                latency_ms=(time.perf_counter() - started) * 1000,
                error="empty_result",
            )
            return pd.DataFrame()
        telemetry.record_source(
            src.name,
            "get_kline",
            success=True,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        df.attrs["_source"] = src.name
        df.attrs["_source_plan"] = plan
        df.attrs["_data_contract"] = _source_contract(src)
        return df

    @_cached
    def get_news(self, symbol=None, limit=50) -> list[News]:
        src = self._primary
        started = time.perf_counter()
        try:
            news = src.get_news(symbol, limit)
        except Exception as exc:  # noqa: BLE001 - preserve provider failure without fallback
            telemetry.record_source(
                src.name,
                "get_news",
                success=False,
                latency_ms=(time.perf_counter() - started) * 1000,
                error=str(exc),
            )
            logger.warning("数据源 %s get_news 失败，不切换数据源", src.name, exc_info=True)
            raise
        telemetry.record_source(
            src.name,
            "get_news",
            success=bool(news),
            latency_ms=(time.perf_counter() - started) * 1000,
            error=None if news else "empty_result",
        )
        return news or []

    @_cached
    def get_announcements(self, symbol, limit=50) -> list[Announcement]:
        src = self._primary
        started = time.perf_counter()
        try:
            anns = src.get_announcements(symbol, limit)
        except Exception as exc:  # noqa: BLE001 - preserve provider failure without fallback
            telemetry.record_source(
                src.name,
                "get_announcements",
                success=False,
                latency_ms=(time.perf_counter() - started) * 1000,
                error=str(exc),
            )
            logger.warning(
                "数据源 %s get_announcements 失败，不切换数据源", src.name, exc_info=True
            )
            raise
        telemetry.record_source(
            src.name,
            "get_announcements",
            success=bool(anns),
            latency_ms=(time.perf_counter() - started) * 1000,
            error=None if anns else "empty_result",
        )
        return anns or []


_REGISTRY: dict[str, type[DataSource]] = {}
_OPTIONAL_DEPENDENCY_FAILURES: set[tuple[str, str]] = set()


def _log_source_construction_failure(name: str, exc: Exception) -> None:
    """记录 primary 构造失败；调用方必须显式处理，绝不提升备用源。"""
    message = str(exc)
    if not isinstance(exc, (ImportError, ModuleNotFoundError)):
        logger.error("构建 primary 数据源 %s 失败: %s", name, message)
        return
    fingerprint = (name, message)
    if fingerprint in _OPTIONAL_DEPENDENCY_FAILURES:
        logger.debug("已聚合可选依赖故障 %s: %s", name, message)
        return
    _OPTIONAL_DEPENDENCY_FAILURES.add(fingerprint)
    logger.error("primary 数据源 %s 的可选依赖不可用: %s", name, message)


def register_source(name: str, cls: type[DataSource]) -> None:
    """注册数据源（供插件扩展）。"""
    _REGISTRY[name] = cls


def _build_source(
    name: str, cfg: dict | None = None, market: str = "abstract", **kwargs: Any
) -> DataSource:
    """按名称构造数据源实例。

    Args:
        name:   数据源名（akshare/eastmoney/okx/local_parquet/已注册名）
        cfg:    合并后的市场配置（含 data_sources.<name> 的专属配置）
        market: 该实例所属市场（写入 LocalParquetSource）
        **kwargs: 透传（如 OKX 密钥）
    """
    sources_cfg = (cfg or {}).get("data_sources", {})
    src_cfg = sources_cfg.get(name, {}) or {}

    if name == "akshare":
        from core.data_feed.akshare_source import AkshareSource

        return AkshareSource()
    if name == "eastmoney":
        from core.data_feed.eastmoney_source import EastmoneySource

        return EastmoneySource()
    if name == "sina_news":
        from core.data_feed.sina_news_source import SinaNewsSource

        return SinaNewsSource()
    if name == "okx":
        from core.data_feed.okx_source import OkxSource

        return OkxSource(**kwargs)
    if name == "tencent":
        from core.data_feed.tencent_source import TencentSource

        return TencentSource(market=market)
    if name == "yahoo":
        from core.data_feed.yahoo_source import YahooSource

        return YahooSource(market=market)
    if name == "local_parquet":
        from core.config import get_repo_root
        from core.data_feed.local_parquet import LocalParquetSource

        root = src_cfg.get("root", "data")
        root_p = Path(root)
        if not root_p.is_absolute():
            root_p = get_repo_root() / root
        return LocalParquetSource(
            root=root_p,
            groups=src_cfg.get("groups", {}),
            time_mode=src_cfg.get("time_mode", "auto"),
            market=market,
        )
    if name in _REGISTRY:
        return _REGISTRY[name](**kwargs)
    raise ValueError(f"未知数据源: {name}")


def get_data_source(market: str = "a_shares", **kwargs: Any) -> DataSourceProxy:
    """按市场获取唯一 configured primary 的带缓存代理。

    primary 构造失败、请求失败或空结果均不会自动切换到其他供应商或本地存储。
    需要诊断其他已配置数据源时，调用 :func:`get_configured_source` 显式构造。
    """
    cfg = get_config(market)
    sources_cfg = cfg.get("data_sources", {})
    if "fallback" in sources_cfg:
        raise ValueError(
            f"市场 {market} 使用了已移除的 data_sources.fallback；请显式选择一个 primary"
        )
    primary_name = sources_cfg.get("primary")
    if not primary_name:
        raise ValueError(f"市场 {market} 未配置 data_sources.primary")
    try:
        primary = _build_source(primary_name, cfg=cfg, market=market, **kwargs)
    except Exception as exc:  # noqa: BLE001 - provider construction is fail-closed
        _log_source_construction_failure(primary_name, exc)
        raise RuntimeError(f"市场 {market} 的 primary 数据源不可用: {primary_name}") from exc
    primary._configured_priority = 1
    return DataSourceProxy(primary)


def get_configured_source(market: str, name: str) -> DataSource:
    """显式构造配置中声明的单个数据源，用于诊断，不启用自动回退。"""
    cfg = get_config(market)
    sources_cfg = cfg.get("data_sources", {})
    if "fallback" in sources_cfg:
        raise ValueError(
            f"市场 {market} 使用了已移除的 data_sources.fallback；请显式选择诊断数据源"
        )
    configured = {
        str(source_name)
        for source_name, source_cfg in sources_cfg.items()
        if source_name != "primary" and isinstance(source_cfg, dict)
    }
    primary = sources_cfg.get("primary")
    if isinstance(primary, str):
        configured.add(primary)
    if name not in configured:
        raise ValueError(f"市场 {market} 未配置数据源 {name}")
    return _build_source(name, cfg=cfg, market=market)
