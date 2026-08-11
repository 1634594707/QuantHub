from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from packages.model_client import redact_secrets

# Stable, desensitized error codes surfaced to API clients and persisted in logs.
ERR_OKX_AUTH_FAILED = "OKX_AUTH_FAILED"
ERR_OKX_RATE_LIMITED = "OKX_RATE_LIMITED"
ERR_OKX_REJECTED = "OKX_REJECTED"
ERR_NETWORK_UNREACHABLE = "NETWORK_UNREACHABLE"
ERR_CLOCK_DRIFT = "CLOCK_DRIFT"
ERR_STALE_SNAPSHOT = "STALE_SNAPSHOT"
ERR_RISK_HALTED = "RISK_HALTED"
ERR_INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
ERR_WS_DISCONNECTED = "WS_DISCONNECTED"
ERR_INTERNAL = "INTERNAL_ERROR"
ERR_UNKNOWN = "UNKNOWN_ERROR"

# Tokens that identify fields which must never be echoed into logs/messages.
SENSITIVE_KEY_TOKENS = (
    "api_key",
    "apikey",
    "secret",
    "passphrase",
    "password",
    "private_key",
    "token",
    "authorization",
    "sign",
    "signature",
)


@dataclass
class RunnerError:
    """Stable, desensitized error contract returned to callers and stored on disk."""

    code: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)
    recoverable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": _scrub(self.message),
            "recoverable": self.recoverable,
            "detail": _scrub(self.detail),
        }

    def redacted_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def _scrub(value: Any) -> Any:
    """Recursively strip sensitive keys and redact secret strings."""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if any(token in str(key).lower() for token in SENSITIVE_KEY_TOKENS):
                cleaned[key] = "[REDACTED]"
            else:
                cleaned[key] = _scrub(item)
        return cleaned
    if isinstance(value, (list, tuple, set)):
        return [_scrub(item) for item in value]
    if isinstance(value, str):
        return redact_secrets(value)
    return value


def map_exception(exc: Exception) -> RunnerError:
    """Classify an arbitrary provider/runtime exception into a stable RunnerError.

    Never lets raw exception text (which may contain API keys, signatures, or
    stack frames) escape into the message. Callers should persist the *result*
    of this function, never the raw exception.
    """
    name = type(exc).__name__
    message = str(exc)
    try:
        import ccxt

        if isinstance(exc, ccxt.AuthenticationError):
            return RunnerError(
                ERR_OKX_AUTH_FAILED,
                "OKX 拒绝了身份凭证（API key / 签名 / passphrase 不匹配）",
                {"cause": name},
                recoverable=False,
            )
        if isinstance(exc, ccxt.RateLimitExceeded):
            return RunnerError(
                ERR_OKX_RATE_LIMITED,
                "OKX 触发了请求频率限制，请稍后重试",
                {"cause": name},
                recoverable=True,
            )
        if isinstance(exc, ccxt.ExchangeNotAvailable):
            return RunnerError(
                ERR_NETWORK_UNREACHABLE,
                "OKX 服务当前不可用或网络不可达",
                {"cause": name},
                recoverable=True,
            )
        if isinstance(exc, ccxt.NetworkError):
            return RunnerError(
                ERR_NETWORK_UNREACHABLE,
                "与 OKX 的网络连接失败",
                {"cause": name},
                recoverable=True,
            )
        if isinstance(exc, ccxt.ExchangeError):
            return RunnerError(
                ERR_OKX_REJECTED,
                "OKX 拒绝了请求",
                {"cause": name},
                recoverable=True,
            )
    except ImportError:  # ccxt group not installed in this environment
        pass

    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return RunnerError(
            ERR_NETWORK_UNREACHABLE, "网络连接失败", {"cause": name}, recoverable=True
        )

    if isinstance(exc, ValueError):
        text = message.lower()
        if "stale" in text or "invalid timestamp" in text:
            return RunnerError(
                ERR_STALE_SNAPSHOT,
                "账户快照时间戳异常（可能时钟漂移或数据过期）",
                {"cause": name},
                recoverable=False,
            )
        if "halted" in text:
            return RunnerError(
                ERR_RISK_HALTED,
                "账户或全局处于停机模式，订单被拒绝",
                {"cause": name},
                recoverable=False,
            )
        if "no positive equity" in text or "insufficient" in text:
            return RunnerError(
                ERR_INSUFFICIENT_BALANCE,
                "账户权益不足，无法继续",
                {"cause": name},
                recoverable=False,
            )
        return RunnerError(
            ERR_INTERNAL,
            "请求参数或内部状态非法",
            {"cause": name},
            recoverable=False,
        )

    return RunnerError(ERR_UNKNOWN, "发生未预期的错误", {"cause": name}, recoverable=True)
