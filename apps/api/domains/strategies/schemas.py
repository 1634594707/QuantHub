from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class StrategyRunRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


class PresetCreate(BaseModel):
    name: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class RunRecordCreate(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)


class BacktestRequest(BaseModel):
    symbol: str
    market: str = "a_shares"
    interval: str = "1d"
    limit: int = Field(default=300, ge=2, le=10_000)
    initial_capital: float = Field(default=100_000, gt=0)
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("标的代码不能为空")
        return normalized


class PaAnalyzeRequest(BaseModel):
    """PA 两阶段分析请求（查询参数形式，与路由 Query 对齐）。"""

    symbol: str = Field(..., min_length=1, description="标的代码")
    timeframe: str = Field(default="1h")
    market: str | None = Field(default=None)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("标的代码不能为空")
        return normalized
