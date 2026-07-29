from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ApiKeyUpdate(BaseModel):
    api_key: str = Field(
        min_length=1,
        max_length=20_000,
        description="LLM API Key（仅保存在本地 apps/api/.env，不入库）",
    )

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("API Key 不能为空")
        if "\n" in normalized or "\r" in normalized:
            raise ValueError("API Key 不能包含换行")
        return normalized


NotificationChannel = Literal["wecom", "webhook", "telegram"]


class NotificationEnabledUpdate(BaseModel):
    enabled: bool


class NotificationChannelUpdate(BaseModel):
    enabled: bool
    webhook_url: str | None = Field(default=None, max_length=20_000)
    mentioned_mobile: str | None = Field(default=None, max_length=2_000)
    url: str | None = Field(default=None, max_length=20_000)
    bot_token: str | None = Field(default=None, max_length=20_000)
    chat_id: str | None = Field(default=None, max_length=2_000)

    @field_validator("webhook_url", "mentioned_mobile", "url", "bot_token", "chat_id")
    @classmethod
    def validate_secret(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if "\n" in normalized or "\r" in normalized:
            raise ValueError("通知配置不能包含换行")
        return normalized or None
