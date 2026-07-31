"""策略实验室请求 schema。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DefinitionCreate(BaseModel):
    name: str = Field(..., min_length=1)
    strategy_key: str = Field(..., min_length=1)
    market: str = Field(default="a_shares")
    description: str = Field(default="")
    tags: list[str] = Field(default_factory=list)


class VersionCreate(BaseModel):
    version: str = Field(..., min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    code_hash: str = Field(default="")
    changelog: str = Field(default="")


class ExperimentCreate(BaseModel):
    symbol: str = Field(..., min_length=1)
    market: str = Field(default="a_shares")
    timeframe: str = Field(default="1d")
    version_id: str | None = Field(default=None)
    research_run_id: str | None = Field(default=None, min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)
    note: str = Field(default="")


class BacktestRunCreate(BaseModel):
    initial_capital: float = Field(default=100_000, gt=0)
    limit: int = Field(default=300, ge=2, le=10_000)
    seed: str | None = Field(default=None)


class DefinitionUpdate(BaseModel):
    name: str = Field(..., min_length=1)
    strategy_key: str = Field(..., min_length=1)
    market: str = Field(default="a_shares")
    description: str = Field(default="")
    tags: list[str] = Field(default_factory=list)


class DefinitionCopy(BaseModel):
    name: str = Field(..., min_length=1)


class VersionUpdate(BaseModel):
    version: str = Field(..., min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    code_hash: str = Field(default="")
    changelog: str = Field(default="")


class VersionCopy(BaseModel):
    version: str = Field(..., min_length=1)


class ExperimentUpdate(BaseModel):
    symbol: str = Field(..., min_length=1)
    market: str = Field(default="a_shares")
    timeframe: str = Field(default="1d")
    version_id: str | None = Field(default=None)
    research_run_id: str | None = Field(default=None, min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)
    note: str = Field(default="")


class ExperimentCopy(BaseModel):
    note: str = Field(default="")
