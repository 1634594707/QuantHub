from __future__ import annotations

from typing import Any


def provider_key_env(config: dict[str, Any], provider: str | None = None) -> str:
    provider = provider or config.get("llm", {}).get("provider", "deepseek")
    provider_config = config.get("llm", {}).get(provider, {})
    fallback = {
        "deepseek": "DEEPSEEK_API_KEY",
        "openai": "OPENAI_API_KEY",
        "custom": "QUANTHUB_CUSTOM_LLM_API_KEY",
    }.get(provider, "QUANTHUB_LLM_API_KEY")
    return str(provider_config.get("api_key_env", fallback))


def mask_secret(secret: str) -> str:
    if len(secret) <= 8:
        return "****"
    return f"{secret[:4]}...{secret[-4:]}"
