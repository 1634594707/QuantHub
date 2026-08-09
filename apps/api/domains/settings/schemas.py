from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator


class OkxDemoCredentialsUpdate(BaseModel):
    api_key: SecretStr = Field(min_length=1, max_length=512, repr=False)
    secret_key: SecretStr = Field(min_length=1, max_length=512, repr=False)
    passphrase: SecretStr = Field(min_length=1, max_length=512, repr=False)

    @field_validator("api_key", "secret_key", "passphrase")
    @classmethod
    def validate_credential(cls, value: SecretStr) -> SecretStr:
        plaintext = value.get_secret_value().strip()
        if not plaintext or "\n" in plaintext or "\r" in plaintext:
            raise ValueError("OKX credential fields must be non-empty single-line values")
        return SecretStr(plaintext)


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


LLMProvider = Literal["deepseek", "openai", "custom"]


class LLMSettingsUpdate(BaseModel):
    provider: LLMProvider
    api_key: str | None = Field(default=None, max_length=20_000)
    base_url: str = Field(min_length=1, max_length=2_000)
    model: str = Field(min_length=1, max_length=300)
    timeout: int = Field(ge=5, le=600)
    max_retries: int = Field(ge=0, le=10)

    @field_validator("api_key")
    @classmethod
    def normalize_optional_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if "\n" in normalized or "\r" in normalized:
            raise ValueError("API Key 不能包含换行")
        return normalized

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("API 地址必须是有效的 http(s) URL")
        if parsed.username or parsed.password:
            raise ValueError("API 地址不能包含用户名或密码")
        return normalized

    @field_validator("model")
    @classmethod
    def normalize_model(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or "\n" in normalized or "\r" in normalized:
            raise ValueError("默认模型无效")
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
