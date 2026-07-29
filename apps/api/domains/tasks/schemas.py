from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

AnalysisKind = Literal["pa", "news", "ensemble", "evaluation"]
TaskStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "timeout"]


class AnalysisTaskCreate(BaseModel):
    kind: AnalysisKind
    symbol: str
    market: str = "a_shares"
    timeframe: str = "1d"
    payload: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=90, ge=10, le=900)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("股票代码不能为空")
        return normalized

    @field_validator("market", "timeframe")
    @classmethod
    def normalize_context(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("研究上下文不能为空")
        return normalized
