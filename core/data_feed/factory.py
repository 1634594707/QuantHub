"""数据源工厂。

按 market + name 创建对应 DataSource，支持 fallback 链。
所有 source 调用经 CacheStore 透明缓存。
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from core.config import get_config
from core.data_feed.base import Announcement, DataSource, Interval, News
from core.data_feed.cache import CacheStore, cache_key_date

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
            limit = args[4] if len(args) > 4 else kwargs.get("limit", 500)
            date = cache_key_date()
            hit = cache.get_kline(symbol, self.market, interval, date, limit)
            if hit is not None and not hit.empty:
                logger.debug("缓存命中 kline %s %s limit=%s", symbol, interval, limit)
                return hit
            df = fn(self, *args, **kwargs)
            if df is not None and not df.empty:
                cache.set_kline(symbol, self.market, interval, date, df, limit)
            return df

        if kind in ("get_news", "get_announcements"):
            symbol = args[0] if args else kwargs.get("symbol")
            limit = args[1] if len(args) > 1 else kwargs.get("limit", 50)
            docs = cache.get_docs(kind, symbol, limit)
            if docs:
                # 重建对象
                if kind == "get_news":
                    return [News(**d) for d in docs]
                return [Announcement(**d) for d in docs]
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
            try:
                df = src.get_kline(symbol, interval, start, end, limit)
                if df is not None and not df.empty:
                    df.attrs["_source"] = src.name
                    return df
            except Exception as e:
                last_err = e
                logger.warning("数据源 %s get_kline 失败，尝试 fallback: %s", src.name, e)
        if last_err:
            logger.error("所有数据源均失败: %s", last_err)
        return pd.DataFrame()

    @_cached
    def get_news(self, symbol=None, limit=50) -> list[News]:
        sources = [self._primary] + self._fallbacks
        for src in sources:
            try:
                news = src.get_news(symbol, limit)
                if news:
                    return news
            except Exception:
                logger.warning("数据源 %s get_news 失败，尝试 fallback", src.name, exc_info=True)
        return []

    @_cached
    def get_announcements(self, symbol, limit=50) -> list[Announcement]:
        sources = [self._primary] + self._fallbacks
        for src in sources:
            try:
                anns = src.get_announcements(symbol, limit)
                if anns:
                    return anns
            except Exception:
                logger.warning(
                    "数据源 %s get_announcements 失败，尝试 fallback", src.name, exc_info=True
                )
        return []


_REGISTRY: dict[str, type[DataSource]] = {}


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
    if name == "okx":
        from core.data_feed.okx_source import OkxSource

        return OkxSource(**kwargs)
    if name == "tencent":
        from core.data_feed.tencent_source import TencentSource

        return TencentSource(market=market)
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
    primary = _build_source(primary_name, cfg=cfg, market=market, **kwargs)
    fallbacks = []
    for fb in fallback_names:
        try:
            fallbacks.append(_build_source(fb, cfg=cfg, market=market))
        except Exception:
            logger.warning("构建 fallback 数据源 %s 失败", fb, exc_info=True)
    return DataSourceProxy(primary, fallbacks)
