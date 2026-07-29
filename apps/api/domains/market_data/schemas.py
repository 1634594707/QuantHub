"""市场数据状态域响应 schema：稳定的 OpenAPI 契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from apps.api.domains.market.schemas import MarketDataStatusResponse


class DataSourceCheckRequest(BaseModel):
    market: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)
    operation: Literal["get_kline", "get_news", "get_announcements"]
    symbol: str = Field(..., min_length=1)
    interval: str = Field(..., min_length=1)


__all__ = ["DataSourceCheckRequest", "MarketDataStatusResponse"]
