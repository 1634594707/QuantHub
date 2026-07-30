from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class FactorResearchRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    market: str = Field(default="a_shares")
    interval: str = Field(default="1d")
    limit: int = Field(default=500, ge=120, le=5_000)
    horizon: int = Field(default=5, ge=1, le=60)
    transaction_cost_bps: float = Field(default=10.0, ge=0, le=200)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("标的代码不能为空")
        return normalized

    @field_validator("market")
    @classmethod
    def validate_market(cls, value: str) -> str:
        if value not in {"a_shares", "us_stocks", "crypto", "mt5"}:
            raise ValueError("不支持的市场")
        return value
