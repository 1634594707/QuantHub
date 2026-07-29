from __future__ import annotations

import os
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def read_runtime_secret(env_name: str) -> str | None:
    return os.environ.get(env_name)


def write_secret(env_name: str, value: str) -> None:
    """Update one variable without removing unrelated local settings."""
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    prefix = f"{env_name}="
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{env_name}={value}"
            break
    else:
        lines.append(f"{env_name}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def set_runtime_secret(env_name: str, value: str) -> None:
    os.environ[env_name] = value
