from __future__ import annotations

import os
from pathlib import Path

from dotenv import set_key, unset_key

ENV_PATH = Path(os.environ.get("QUANTHUB_ENV_PATH", Path(__file__).resolve().parents[2] / ".env"))


def read_runtime_secret(env_name: str) -> str | None:
    return os.environ.get(env_name)


def write_secret(env_name: str, value: str) -> None:
    """Update one variable without removing unrelated local settings."""
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PATH.touch(exist_ok=True)
    set_key(str(ENV_PATH), env_name, value, quote_mode="always")


def delete_secret(env_name: str) -> None:
    if ENV_PATH.exists():
        unset_key(str(ENV_PATH), env_name)


def set_runtime_secret(env_name: str, value: str) -> None:
    os.environ[env_name] = value


def clear_runtime_secret(env_name: str) -> None:
    os.environ.pop(env_name, None)
