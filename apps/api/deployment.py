"""Validated deployment settings for local, LAN and PostgreSQL modes."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .database import deployment_mode

LOCAL_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


@dataclass(frozen=True)
class DeploymentSettings:
    mode: str
    host: str
    cors_origins: tuple[str, ...]
    auth_required: bool


def load_settings() -> DeploymentSettings:
    mode = deployment_mode()
    raw_origins = os.environ.get("QUANTHUB_CORS_ORIGINS", "")
    origins = tuple(item.strip() for item in raw_origins.split(",") if item.strip())
    if mode == "local":
        return DeploymentSettings(
            mode=mode,
            host=os.environ.get("QUANTHUB_HOST", "127.0.0.1"),
            cors_origins=origins or LOCAL_ORIGINS,
            auth_required=os.environ.get("QUANTHUB_AUTH_REQUIRED") == "1",
        )

    if not origins:
        raise RuntimeError(f"{mode} 模式必须设置 QUANTHUB_CORS_ORIGINS")
    if "*" in origins:
        raise RuntimeError(f"{mode} 模式禁止在 QUANTHUB_CORS_ORIGINS 中使用 *")
    bootstrap_token = os.environ.get("QUANTHUB_BOOTSTRAP_ADMIN_TOKEN", "")
    if len(bootstrap_token) < 32:
        raise RuntimeError(f"{mode} 模式必须设置至少 32 个字符的 QUANTHUB_BOOTSTRAP_ADMIN_TOKEN")
    return DeploymentSettings(
        mode=mode,
        host=os.environ.get("QUANTHUB_HOST", "0.0.0.0"),
        cors_origins=origins,
        auth_required=True,
    )
