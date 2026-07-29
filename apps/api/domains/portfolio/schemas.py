from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class AllocationCreate(BaseModel):
    strategy: str
    weight: float = Field(default=0.0, ge=0.0, le=1.0)
    symbol: str | None = None
    live: bool = False
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("strategy")
    @classmethod
    def normalize_strategy(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("策略不能为空")
        return normalized

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value and value.strip() else None


class HoldingCreate(BaseModel):
    code: str = Field(min_length=1)
    name: str = ""
    shares: float = Field(default=0, ge=0)
    cost: float = Field(default=0, ge=0)
    market: str = "a_shares"

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("证券代码不能为空")
        return normalized


class HoldingUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    shares: float | None = Field(default=None, ge=0)
    cost: float | None = Field(default=None, ge=0)
    market: str | None = None

    @field_validator("code")
    @classmethod
    def normalize_optional_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("证券代码不能为空")
        return normalized


class WatchCreate(BaseModel):
    sym: str = Field(min_length=1)
    name: str = ""
    market: str = "a_shares"

    @field_validator("sym")
    @classmethod
    def normalize_watch_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("证券代码不能为空")
        return normalized


class WatchUpdate(BaseModel):
    sym: str | None = None
    name: str | None = None
    market: str | None = None

    @field_validator("sym")
    @classmethod
    def normalize_optional_watch_symbol(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("证券代码不能为空")
        return normalized
