"""In-process telemetry for data-source and cache operations.

导出形式化数据模型 ``DataSourceStatus`` / ``DataSnapshot``，作为行情治理
与配置页展示的稳定契约；``DataFeedTelemetry`` 负责采集与聚合。
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field


@dataclass
class _Metric:
    calls: int = 0
    successes: int = 0
    errors: int = 0
    latency_ms_total: float = 0.0
    last_called_at: float | None = None
    last_success_at: float | None = None
    last_error: str | None = None


@dataclass
class DataSourceStatus:
    """单个数据源 + 操作的运行时状态。"""

    source: str
    operation: str
    calls: int = 0
    successes: int = 0
    errors: int = 0
    success_rate: float = 0.0
    error_rate: float = 0.0
    avg_latency_ms: float = 0.0
    last_called_at: float | None = None
    last_success_at: float | None = None
    last_error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CacheStats:
    """缓存命中统计。"""

    hits: int = 0
    misses: int = 0
    requests: int = 0
    hit_rate: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DataSnapshot:
    """数据源运行时快照：所有 source 状态 + 缓存统计 + 生成时间。"""

    sources: list[DataSourceStatus] = field(default_factory=list)
    cache: CacheStats = field(default_factory=CacheStats)
    generated_at: float = field(default_factory=lambda: time.time())

    def to_dict(self) -> dict:
        return {
            "sources": [s.to_dict() for s in self.sources],
            "cache": self.cache.to_dict(),
            "generated_at": self.generated_at,
        }


class DataFeedTelemetry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sources: dict[tuple[str, str], _Metric] = {}
        self._cache_hits = 0
        self._cache_misses = 0

    def record_source(
        self,
        source: str,
        operation: str,
        *,
        success: bool,
        latency_ms: float,
        error: str | None = None,
    ) -> None:
        with self._lock:
            metric = self._sources.setdefault((source, operation), _Metric())
            metric.calls += 1
            metric.successes += int(success)
            metric.errors += int(not success)
            metric.latency_ms_total += max(0.0, latency_ms)
            called_at = time.time()
            metric.last_called_at = called_at
            if success:
                metric.last_success_at = called_at
            metric.last_error = None if success else (error or "empty_result")

    def record_cache(self, *, hit: bool) -> None:
        with self._lock:
            if hit:
                self._cache_hits += 1
            else:
                self._cache_misses += 1

    def snapshot(self) -> DataSnapshot:
        """返回形式化 ``DataSnapshot``（含 sources + cache + generated_at）。"""
        with self._lock:
            sources: list[DataSourceStatus] = []
            for (source, operation), metric in sorted(self._sources.items()):
                calls = metric.calls
                sources.append(
                    DataSourceStatus(
                        source=source,
                        operation=operation,
                        calls=calls,
                        successes=metric.successes,
                        errors=metric.errors,
                        success_rate=round(metric.successes / calls, 4) if calls else 0.0,
                        error_rate=round(metric.errors / calls, 4) if calls else 0.0,
                        avg_latency_ms=round(metric.latency_ms_total / calls, 2) if calls else 0.0,
                        last_called_at=metric.last_called_at,
                        last_success_at=metric.last_success_at,
                        last_error=metric.last_error,
                    )
                )
            cache_total = self._cache_hits + self._cache_misses
            cache = CacheStats(
                hits=self._cache_hits,
                misses=self._cache_misses,
                requests=cache_total,
                hit_rate=round(self._cache_hits / cache_total, 4) if cache_total else 0.0,
            )
        return DataSnapshot(sources=sources, cache=cache)

    def reset(self) -> None:
        with self._lock:
            self._sources.clear()
            self._cache_hits = 0
            self._cache_misses = 0


telemetry = DataFeedTelemetry()
