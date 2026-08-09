"""网关 -> OKX Runner 的 HTTP 客户端。

对应工作包 M1-03。

要点：
    - 只有本模块知道 Runner 的地址与服务令牌，绝不把它们写进响应或日志。
    - 所有网络异常统一转换成 :class:`TradingError`，不向上抛裸 requests 异常。
    - ``transport`` 可注入，便于契约测试不依赖真实网络。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import errors
from .config import TradingProxySettings

logger = logging.getLogger(__name__)

_SAFE_METHODS = {"GET", "HEAD"}


@dataclass(frozen=True)
class RunnerResponse:
    status_code: int
    body: Any


Transport = Callable[[str, str, dict[str, str], bytes | None, float], RunnerResponse]


def _requests_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
) -> RunnerResponse:
    import requests  # noqa: PLC0415  # 延迟导入，避免测试注入 transport 时也要求安装

    response = requests.request(method, url, headers=headers, data=body, timeout=timeout)
    try:
        parsed = response.json()
    except ValueError:
        parsed = None
    return RunnerResponse(status_code=response.status_code, body=parsed)


class RunnerClient:
    def __init__(self, settings: TradingProxySettings, transport: Transport | None = None) -> None:
        self.settings = settings
        self._transport = transport or _requests_transport

    # -- 内部 ---------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.settings.auth_token:
            headers["Authorization"] = f"Bearer {self.settings.auth_token}"
        return headers

    def _url(self, path: str) -> str:
        return f"{self.settings.base_url}{path if path.startswith('/') else '/' + path}"

    # -- 对外 ---------------------------------------------------------------

    def call(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        if not self.settings.configured:
            raise errors.TradingError(
                errors.TRADING_NOT_CONFIGURED,
                detail="QH_RUNNER_BASE_URL 或 QH_RUNNER_AUTH_TOKEN 未设置",
                hint="在服务端环境变量中配置 Runner 地址与服务令牌后重启网关",
            )

        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        timeout = (
            self.settings.connect_timeout_seconds
            if method in _SAFE_METHODS
            else self.settings.timeout_seconds
        )

        try:
            response = self._transport(method, self._url(path), self._headers(), body, timeout)
        except Exception as exc:  # noqa: BLE001 - 需要把全部传输层异常归一
            raise _transport_error(exc, method, path) from exc

        if response.status_code >= 400:
            raise _response_error(response, method, path)

        if response.body is None:
            raise errors.TradingError(
                errors.TRADING_RUNNER_BAD_RESPONSE,
                detail=f"{method} {path} 返回了非 JSON 响应",
            )
        return errors.redact_mapping(response.body)


def _transport_error(exc: Exception, method: str, path: str) -> errors.TradingError:
    name = type(exc).__name__
    text = errors.redact(str(exc))
    # requests 的超时/连接异常类名在不同版本下稳定，用类名而非 isinstance 以避免硬依赖
    if "Timeout" in name:
        logger.warning("Runner 请求超时 %s %s", method, path)
        return errors.TradingError(
            errors.TRADING_RUNNER_TIMEOUT,
            detail=f"{method} {path} 超时",
            hint="不要重复提交。请调用订单恢复接口，以 OKX 回报确认真实状态",
        )
    if "Connection" in name or "NewConnection" in name:
        logger.warning("Runner 不可达 %s %s", method, path)
        return errors.TradingError(
            errors.TRADING_RUNNER_UNAVAILABLE,
            detail=f"{method} {path} 无法连接",
            hint="确认 OKX Runner 进程已启动且端口可达",
        )
    logger.exception("Runner 调用异常 %s %s", method, path)
    return errors.TradingError(errors.TRADING_UPSTREAM_ERROR, detail=f"{name}: {text}")


def _response_error(response: RunnerResponse, method: str, path: str) -> errors.TradingError:
    detail = ""
    okx_code: str | None = None
    if isinstance(response.body, dict):
        detail = str(response.body.get("detail") or response.body.get("message") or "")
        raw = response.body.get("raw")
        if isinstance(raw, dict):
            okx_code = raw.get("code")
    code = (
        errors.from_okx_code(okx_code)
        if okx_code
        else errors.from_runner_status(response.status_code)
    )
    logger.warning(
        "Runner 返回错误 %s %s -> HTTP %s / %s", method, path, response.status_code, code
    )
    return errors.TradingError(code, detail=detail or f"Runner HTTP {response.status_code}")
