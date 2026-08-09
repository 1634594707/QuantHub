from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION = "1.0.0"


class ModelRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    system: str
    prompt: str
    timeout_seconds: float = Field(default=60, gt=0, le=300)


class ModelResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    content: str
    request_id: str | None = None


class ModelClient(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse: ...


_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|secret|token|passphrase)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+=*"),
)


def redact_secrets(value: str) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS:

        def replacement(match: re.Match[str]) -> str:
            matched = match.group(0)
            if matched.lower().startswith("bearer "):
                return "Bearer=[REDACTED]"
            return matched.split("=", 1)[0].split(":", 1)[0] + "=[REDACTED]"

        redacted = pattern.sub(replacement, redacted)
    return redacted


class RetryingModelClient:
    def __init__(
        self,
        transport: Callable[[ModelRequest], ModelResponse],
        *,
        max_attempts: int = 3,
        backoff_seconds: float = 0.05,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self._transport = transport
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds

    def complete(self, request: ModelRequest) -> ModelResponse:
        safe_request = request.model_copy(
            update={
                "system": redact_secrets(request.system),
                "prompt": redact_secrets(request.prompt),
            }
        )
        last_error: Exception | None = None
        for attempt in range(self._max_attempts):
            try:
                return self._transport(safe_request)
            except (TimeoutError, ConnectionError) as exc:
                last_error = exc
                if attempt + 1 < self._max_attempts:
                    time.sleep(self._backoff_seconds * (2**attempt))
        assert last_error is not None
        raise last_error
