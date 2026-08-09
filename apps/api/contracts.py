"""统一数据来源与新鲜度契约。

对应工作包 M3-03（统一数据来源契约）与 M3-04（统一空/错/缓存/过期状态）。

任何被主 Web 直接消费的响应都应当用本模块的包装器输出，使前端可以在
不认识具体业务字段的情况下，仍然判断出「有数据 / 无数据 / 源异常 / 缓存 / 已过期」。

响应外壳::

    {
      "status": "ok" | "empty" | "stale" | "error",
      "source": {"kind": "runner", "name": "okx_runner", "environment": "demo"},
      "observed_at": "2026-08-09T13:41:59+08:00",
      "freshness": {"age_seconds": 3, "ttl_seconds": 30, "expired": false},
      "error_code": null,
      "data": {...}
    }

``status`` 判定规则（不可由调用方随意覆盖）：
    - 传入 ``error_code`` -> ``error``
    - 数据为空容器 -> ``empty``
    - 超过 ``ttl_seconds`` -> ``stale``
    - 其余 -> ``ok``
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

Status = Literal["ok", "empty", "stale", "error"]
SourceKind = Literal["runner", "database", "external", "derived", "none"]


@dataclass(frozen=True)
class Source:
    kind: SourceKind
    name: str
    environment: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "name": self.name, "environment": self.environment}


def _now() -> datetime:
    return datetime.now(UTC)


def _parse(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _is_empty(data: Any) -> bool:
    if data is None:
        return True
    if isinstance(data, (list, tuple, set, dict, str)) and len(data) == 0:
        return True
    return False


def envelope(
    data: Any,
    *,
    source: Source,
    observed_at: str | datetime | None = None,
    ttl_seconds: float | None = None,
    error_code: str | None = None,
    message: str | None = None,
    detail: str | None = None,
    hint: str | None = None,
    retryable: bool | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造统一响应外壳。``observed_at`` 缺省取当前时间。"""
    observed = _parse(observed_at) or _now()
    age = max(0.0, (_now() - observed).total_seconds())
    expired = bool(ttl_seconds is not None and age > ttl_seconds)

    if error_code:
        status: Status = "error"
    elif _is_empty(data):
        status = "empty"
    elif expired:
        status = "stale"
    else:
        status = "ok"

    payload: dict[str, Any] = {
        "status": status,
        "source": source.as_dict(),
        "observed_at": observed.astimezone().isoformat(timespec="seconds"),
        "freshness": {
            "age_seconds": round(age, 3),
            "ttl_seconds": ttl_seconds,
            "expired": expired,
        },
        "error_code": error_code,
        "data": data,
    }
    if message is not None:
        payload["message"] = message
    if detail is not None:
        payload["detail"] = detail
    if hint is not None:
        payload["hint"] = hint
    if retryable is not None:
        payload["retryable"] = retryable
    if extra:
        payload.update(extra)
    return payload


def error_envelope(
    *,
    source: Source,
    error_code: str,
    message: str,
    detail: str = "",
    hint: str | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    """错误响应外壳。``data`` 恒为 ``None``，禁止在错误时返回占位数据。"""
    return envelope(
        None,
        source=source,
        error_code=error_code,
        message=message,
        detail=detail,
        hint=hint,
        retryable=retryable,
    )
