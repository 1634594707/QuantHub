from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .domain import ReviewStatus


class PublishSignalRequest(BaseModel):
    symbol: str
    market: str = "a_shares"
    direction: Literal["buy", "sell", "hold"] = "hold"
    score: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=0.5, ge=0, le=1)
    source: str = "api"
    timeframe: str = "realtime"
    tags: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("标的代码不能为空")
        return normalized

    @field_validator("market", "source", "timeframe")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("字段不能为空")
        return normalized

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class ReviewSignalRequest(BaseModel):
    status: ReviewStatus
    note: str | None = Field(default=None, max_length=1000)
