from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from apps.api.domains.factor_research.schemas import CrossSectionResearchRequest


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


class FactorResearchJobCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    frequency: Literal["daily", "weekly", "monthly"]
    hour: int = Field(default=18, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    day_of_week: int = Field(default=0, ge=0, le=6)
    day_of_month: int = Field(default=1, ge=1, le=28)
    enabled: bool = True
    request: CrossSectionResearchRequest
    actor: str = Field(default="local-user", min_length=1, max_length=100)

    @field_validator("name", "actor")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def reject_resume_request(self) -> FactorResearchJobCreate:
        if self.request.run_id is not None:
            raise ValueError("定时作业不能设置 run_id")
        return self

    def cron(self) -> str:
        if self.frequency == "daily":
            return f"{self.minute} {self.hour} * * *"
        if self.frequency == "weekly":
            return f"{self.minute} {self.hour} * * {self.day_of_week}"
        return f"{self.minute} {self.hour} {self.day_of_month} * *"


class FactorResearchJobUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    actor: str = Field(default="local-user", min_length=1, max_length=100)

    @field_validator("name", "actor")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None
