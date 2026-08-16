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


class PublicMarketStreamStartRequest(BaseModel):
    inst_id: str = Field(default="BTC-USDT-SWAP", min_length=3, max_length=40)
    candle_channel: Literal["candle1H", "candle4H", "candle1D"] = "candle1H"


__all__ = [
    "DataSourceCheckRequest",
    "MarketDataStatusResponse",
    "PublicMarketStreamStartRequest",
]
