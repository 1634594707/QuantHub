from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Environment = Literal["shadow", "demo", "live"]


@dataclass(frozen=True)
class RunnerSettings:
    version: str
    host: str
    port: int
    database_path: Path
    environment: Environment
    signing_key: bytes
    log_name: str = "quanthub-okx-runner"
    auth_token: str | None = None


def load_settings() -> RunnerSettings:
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.get("QH_RUNNER_ENVIRONMENT", "shadow")
    if environment not in {"shadow", "demo", "live"}:
        raise RuntimeError("QH_RUNNER_ENVIRONMENT must be shadow, demo or live")
    if environment == "live" and os.environ.get("QH_RUNNER_LIVE_APPROVED") != "1":
        raise RuntimeError("live Runner requires an explicit independent safety approval")
    raw_key = os.environ.get("QH_RUNNER_SIGNING_KEY", "")
    signing_key = raw_key.encode("utf-8") if raw_key else b"development-factor-signing-key-32b"
    path = (
        Path(
            os.environ.get(
                "QH_RUNNER_DATABASE_PATH",
                root / "data" / "okx_runner" / f"runner-{environment}.db",
            )
        )
        .expanduser()
        .resolve()
    )
    host = os.environ.get("QH_RUNNER_HOST", "127.0.0.1")
    auth_token = os.environ.get("QH_RUNNER_AUTH_TOKEN") or None
    if (
        host not in {"127.0.0.1", "localhost", "::1"} or environment != "shadow"
    ) and auth_token is None:
        raise RuntimeError("non-local or trading-mode Runner requires QH_RUNNER_AUTH_TOKEN")
    return RunnerSettings(
        version="1.0.0",
        host=host,
        port=int(os.environ.get("QH_RUNNER_PORT", "8103")),
        database_path=path,
        environment=environment,  # type: ignore[arg-type]
        signing_key=signing_key,
        auth_token=auth_token,
    )
