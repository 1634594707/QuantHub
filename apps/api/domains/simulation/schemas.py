from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "limit"]
OrderStatus = Literal["pending", "partially_filled", "filled", "cancelled"]


class SimulationOrderCreate(BaseModel):
    signal_id: str | None = None
    symbol: str | None = None
    market: str = "a_shares"
    side: OrderSide | None = None
    order_type: OrderType = "market"
    quantity: float = Field(gt=0)
    limit_price: float | None = Field(default=None, gt=0)
    account_id: str = Field(default="paper", min_length=1, max_length=100)
    factor_key: str | None = Field(default=None, min_length=1, max_length=80)
    factor_version: str | None = Field(default=None, pattern=r"^\d+\.\d+\.\d+$")
    research_run_id: str | None = Field(default=None, min_length=1, max_length=120)
    rebalance_cycle_id: str | None = Field(default=None, min_length=1, max_length=120)
    signal_time: datetime | None = None
    tradable_time: datetime | None = None
    theoretical_price: float | None = Field(default=None, gt=0)
    capacity_used: float = Field(default=0, ge=0)

    @field_validator("signal_id")
    @classmethod
    def normalize_optional_id(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    @field_validator("symbol")
    @classmethod
    def normalize_optional_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value and value.strip() else None

    @field_validator("market", "account_id")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("字段不能为空")
        return normalized

    @model_validator(mode="after")
    def validate_order_context(self):
        if not self.signal_id and (not self.symbol or not self.side):
            raise ValueError("手工模拟订单必须提供 symbol 和 side")
        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("限价单必须提供 limit_price")
        if self.factor_version and not self.factor_key:
            raise ValueError("factor_version 必须与 factor_key 一起提供")
        return self


class SimulationOrderPreviewRequest(BaseModel):
    signal_id: str = Field(min_length=1)
    quantity: float = Field(gt=0)

    @field_validator("signal_id")
    @classmethod
    def normalize_signal_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("字段不能为空")
        return normalized


class SimulationFillCreate(BaseModel):
    quantity: float | None = Field(default=None, gt=0)
    price: float = Field(gt=0)
    fee_rate: float = Field(default=0.0003, ge=0, le=0.1)
