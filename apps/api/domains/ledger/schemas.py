"""组合账本请求 schema。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class TradeCreate(BaseModel):
    instrument_id: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1)
    market: str = Field(default="a_shares")
    direction: str = Field(..., description="buy / sell")
    quantity: float = Field(..., gt=0)
    price: float = Field(..., gt=0)
    fee: float = Field(default=0, ge=0)
    source: str = Field(default="manual")
    note: str = Field(default="")

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: str) -> str:
        v = value.strip().lower()
        if v not in ("buy", "sell"):
            raise ValueError("direction 必须是 buy 或 sell")
        return v

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class CashEntryCreate(BaseModel):
    direction: str = Field(..., description="in / out")
    amount: float = Field(..., gt=0)
    currency: str = Field(default="CNY")
    source: str = Field(default="manual")
    note: str = Field(default="")

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: str) -> str:
        v = value.strip().lower()
        if v not in ("in", "out"):
            raise ValueError("direction 必须是 in 或 out")
        return v


class BenchmarkCreate(BaseModel):
    name: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1)
    market: str = Field(default="a_shares")
    equity_curve: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class TradeCorrection(BaseModel):
    reason: str = Field(..., min_length=1)
    instrument_id: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1)
    market: str = Field(default="a_shares")
    direction: str = Field(..., description="buy / sell")
    quantity: float = Field(..., gt=0)
    price: float = Field(..., gt=0)
    fee: float = Field(default=0, ge=0)
    source: str = Field(default="manual")
    note: str = Field(default="")

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ("buy", "sell"):
            raise ValueError("direction 必须是 buy 或 sell")
        return normalized

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class CashEntryCorrection(BaseModel):
    reason: str = Field(..., min_length=1)
    direction: str = Field(..., description="in / out")
    amount: float = Field(..., gt=0)
    currency: str = Field(default="CNY")
    source: str = Field(default="manual")
    note: str = Field(default="")

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ("in", "out"):
            raise ValueError("direction 必须是 in 或 out")
        return normalized


class BenchmarkCorrection(BaseModel):
    reason: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    code: str = Field(..., min_length=1)
    market: str = Field(default="a_shares")
    equity_curve: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
