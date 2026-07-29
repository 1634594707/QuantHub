from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ResearchStatus = Literal[
    "draft",
    "queued",
    "running",
    "succeeded",
    "partial",
    "failed",
    "cancelled",
    "timeout",
]


class ResearchRunCreate(BaseModel):
    symbol: str = Field(description="规范化后的证券代码")
    market: str = Field(default="a_shares")
    timeframe: str = Field(default="1d")
    modules: list[str] = Field(default_factory=list)
    input: dict[str, Any] = Field(default_factory=dict)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("股票代码不能为空")
        return normalized

    @field_validator("market", "timeframe")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("字段不能为空")
        return normalized

    @field_validator("modules")
    @classmethod
    def normalize_modules(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class ResearchRunUpdate(BaseModel):
    status: ResearchStatus | None = None
    summary: dict[str, Any] | None = None
    error: str | None = None
    note: str | None = Field(default=None, max_length=4000)
    favorite: bool | None = None


class ResearchEvidenceCreate(BaseModel):
    kind: str = Field(min_length=1, description="e.g. market_snapshot/news/model_output")
    source: str = Field(min_length=1, description="数据源、模型或策略名称")
    title: str = ""
    uri: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("kind", "source")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("字段不能为空")
        return normalized


class ResearchCompareRequest(BaseModel):
    run_ids: list[str] = Field(min_length=2, max_length=5)

    @field_validator("run_ids")
    @classmethod
    def normalize_run_ids(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if len(normalized) < 2:
            raise ValueError("至少需要两个不同的研究运行")
        return normalized
