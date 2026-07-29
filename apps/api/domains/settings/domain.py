from __future__ import annotations

from typing import Any


def provider_key_env(config: dict[str, Any]) -> str:
    provider = config.get("llm", {}).get("provider", "deepseek")
    provider_config = config.get("llm", {}).get(provider, {})
    return str(provider_config.get("api_key_env", "DEEPSEEK_API_KEY"))


def mask_secret(secret: str) -> str:
    if len(secret) <= 8:
        return "****"
    return f"{secret[:4]}...{secret[-4:]}"
