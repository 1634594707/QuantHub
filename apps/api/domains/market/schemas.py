"""市场行情域响应 schema：稳定的 OpenAPI 契约。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Candle(BaseModel):
    t: str = Field(..., description="时间戳 ISO 字符串或 bar_time 整数")
    o: float = Field(..., description="开盘价")
    h: float = Field(..., description="最高价")
    l: float = Field(..., description="最低价")
    c: float = Field(..., description="收盘价")
    v: float = Field(default=0.0, description="成交量")


class KlineResponse(BaseModel):
    ok: bool
    source: str | None = Field(default=None, description="数据来源标识")
    symbol: str
    market: str | None = Field(default=None)
    interval: str
    count: int = Field(default=0)
    candles: list[Candle] = Field(default_factory=list)
    error: str | None = Field(default=None, description="ok=false 时的错误说明")


class MarketStatusItem(BaseModel):
    market: str
    primary: str | None = Field(default=None, description="主数据源")


class DataSourceStatusItem(BaseModel):
    name: str
    calls: int = 0
    success_rate: float = 0.0
    error_rate: float = 0.0
    avg_latency_ms: float = 0.0
    last_error: str | None = None


class CacheStatsItem(BaseModel):
    hits: int = 0
    misses: int = 0
    hit_rate: float = 0.0
    size: int = 0


class MarketDataStatusResponse(BaseModel):
    ok: bool
    configured: list[MarketStatusItem] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    cache: dict[str, Any] = Field(default_factory=dict)
    generated_at: float = 0.0
