"""数据源工厂。

按 market + name 创建对应 DataSource，支持 fallback 链。
所有 source 调用经 CacheStore 透明缓存。
"""

from __future__ import annotations

import functools
import logging
import time
from pathlib import Path
from typing import Any

import pandas as pd

from core.config import get_config
from core.data_feed.base import Announcement, DataSource, Interval, News
from core.data_feed.cache import CacheStore, cache_key_date
from core.data_feed.telemetry import telemetry

logger = logging.getLogger(__name__)


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
                else cache.get_kline(symbol, self.market, interval, date, limit)
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
                cache.set_kline(symbol, self.market, interval, date, df, limit)
            return df

        if kind in ("get_news", "get_announcements"):
            symbol = args[0] if args else kwargs.get("symbol")
            limit = args[1] if len(args) > 1 else kwargs.get("limit", 50)
            docs = cache.get_docs(kind, symbol, limit)
            if docs:
                telemetry.record_cache(hit=True)
                # 重建对象
                if kind == "get_news":
                    return [News(**d) for d in docs]
                return [Announcement(**d) for d in docs]
            telemetry.record_cache(hit=False)
            result = fn(self, *args, **kwargs)
            # 空结果不入缓存：避免 primary 离线/失败时把空列表永久固化，导致 fallback 源无法被使用
            if not result:
                return result
            try:
                payload = [{**d.__dict__, "ts": d.ts.isoformat()} for d in result]
                cache.set_docs(kind, symbol, payload, limit)
            except Exception:
                logger.debug("缓存写入失败 %s", kind, exc_info=True)
            return result
        return fn(self, *args, **kwargs)

    return wrapper


class DataSourceProxy(DataSource):
    """数据源代理：包装真实 source，叠加缓存与 fallback。"""

    def __init__(
        self,
        primary: DataSource,
        fallbacks: list[DataSource] | None = None,
        cache: CacheStore | None = None,
    ) -> None:
        self._primary = primary
        self._fallbacks = fallbacks or []
        self._cache = cache or CacheStore()
        self.name = primary.name
        self.market = primary.market

    def supported_intervals(self):
        return self._primary.supported_intervals()

    @_cached
    def get_kline(self, symbol, interval, start=None, end=None, limit=500) -> pd.DataFrame:
        sources = [self._primary] + self._fallbacks
        last_err: Exception | None = None
        for src in sources:
            started = time.perf_counter()
            try:
                df = src.get_kline(symbol, interval, start, end, limit)
                if df is not None and not df.empty:
                    telemetry.record_source(
                        src.name,
                        "get_kline",
                        success=True,
                        latency_ms=(time.perf_counter() - started) * 1000,
                    )
                    df.attrs["_source"] = src.name
                    return df
                telemetry.record_source(
                    src.name,
                    "get_kline",
                    success=False,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error="empty_result",
                )
            except Exception as e:  # noqa: BLE001 - isolate failures from third-party adapters
                telemetry.record_source(
                    src.name,
                    "get_kline",
                    success=False,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error=str(e),
                )
                last_err = e
                logger.warning("数据源 %s get_kline 失败，尝试 fallback: %s", src.name, e)
        if last_err:
            logger.error("所有数据源均失败: %s", last_err)
        return pd.DataFrame()

    @_cached
    def get_news(self, symbol=None, limit=50) -> list[News]:
        sources = [self._primary] + self._fallbacks
        for src in sources:
            started = time.perf_counter()
            try:
                news = src.get_news(symbol, limit)
                if news:
                    telemetry.record_source(
                        src.name,
                        "get_news",
                        success=True,
                        latency_ms=(time.perf_counter() - started) * 1000,
                    )
                    return news
                telemetry.record_source(
                    src.name,
                    "get_news",
                    success=False,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error="empty_result",
                )
            except Exception as exc:
                telemetry.record_source(
                    src.name,
                    "get_news",
                    success=False,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error=str(exc),
                )
                logger.warning("数据源 %s get_news 失败，尝试 fallback", src.name, exc_info=True)
        return []

    @_cached
    def get_announcements(self, symbol, limit=50) -> list[Announcement]:
        sources = [self._primary] + self._fallbacks
        for src in sources:
            started = time.perf_counter()
            try:
                anns = src.get_announcements(symbol, limit)
                if anns:
                    telemetry.record_source(
                        src.name,
                        "get_announcements",
                        success=True,
                        latency_ms=(time.perf_counter() - started) * 1000,
                    )
                    return anns
                telemetry.record_source(
                    src.name,
                    "get_announcements",
                    success=False,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error="empty_result",
                )
            except Exception as exc:
                telemetry.record_source(
                    src.name,
                    "get_announcements",
                    success=False,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error=str(exc),
                )
                logger.warning(
                    "数据源 %s get_announcements 失败，尝试 fallback", src.name, exc_info=True
                )
        return []


_REGISTRY: dict[str, type[DataSource]] = {}
_OPTIONAL_DEPENDENCY_FAILURES: set[tuple[str, str]] = set()


def _log_source_construction_failure(name: str, role: str, exc: Exception) -> None:
    """同一可选依赖故障每个进程只记录一次可见告警。"""
    message = str(exc)
    if not isinstance(exc, (ImportError, ModuleNotFoundError)):
        logger.warning("构建 %s 数据源 %s 失败，继续尝试后续数据源: %s", role, name, message)
        return
    fingerprint = (name, message)
    if fingerprint in _OPTIONAL_DEPENDENCY_FAILURES:
        logger.debug("已聚合可选依赖故障 %s: %s", name, message)
        return
    _OPTIONAL_DEPENDENCY_FAILURES.add(fingerprint)
    logger.warning("可选依赖不可用，已聚合本进程后续同类告警；数据源 %s: %s", name, message)


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
    """按市场获取带缓存与 fallback 的数据源代理。

    Args:
        market: "a_shares" | "crypto"
        **kwargs: 透传给具体 source（如 OKX 密钥）
    """
    cfg = get_config(market)
    sources_cfg = cfg.get("data_sources", {})
    primary_name = sources_cfg.get("primary")
    fallback_names = sources_cfg.get("fallback", [])
    if not primary_name:
        raise ValueError(f"市场 {market} 未配置 data_sources.primary")
    built_sources: list[DataSource] = []
    source_names = [primary_name, *fallback_names]
    for index, source_name in enumerate(source_names):
        try:
            source_kwargs = kwargs if index == 0 else {}
            built_sources.append(
                _build_source(source_name, cfg=cfg, market=market, **source_kwargs)
            )
        except Exception as exc:  # noqa: BLE001 - optional adapters may fail during construction
            role = "primary" if index == 0 else "fallback"
            _log_source_construction_failure(source_name, role, exc)

    if not built_sources:
        configured = ", ".join(source_names)
        raise RuntimeError(f"市场 {market} 的数据源均不可用: {configured}")

    # 主源的可选依赖缺失时，将首个可用 fallback 提升为当前源。
    # 这样离线研究不会在数据源构造阶段提前中断。
    primary = built_sources[0]
    return DataSourceProxy(primary, built_sources[1:])


def get_configured_source(market: str, name: str) -> DataSource:
    """构造市场配置中明确列出的单个数据源，不启用 fallback。"""
    cfg = get_config(market)
    sources_cfg = cfg.get("data_sources", {})
    configured = [sources_cfg.get("primary"), *sources_cfg.get("fallback", [])]
    if name not in configured:
        raise ValueError(f"市场 {market} 未配置数据源 {name}")
    return _build_source(name, cfg=cfg, market=market)
