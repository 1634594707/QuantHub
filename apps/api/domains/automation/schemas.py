from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class AutomationJobUpdate(BaseModel):
    enabled: bool | None = None
    cron: str | None = None
    actor: str = Field(default="local-user", min_length=1, max_length=100)

    @field_validator("cron")
    @classmethod
    def validate_cron(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        if len(normalized.split(" ")) != 5:
            raise ValueError("Cron 必须包含 5 个字段")
        return normalized

    @field_validator("actor")
    @classmethod
    def normalize_actor(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("actor 不能为空")
        return normalized


class AutomationActionRequest(BaseModel):
    actor: str = Field(default="local-user", min_length=1, max_length=100)

    @field_validator("actor")
    @classmethod
    def normalize_actor(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("actor 不能为空")
        return normalized
