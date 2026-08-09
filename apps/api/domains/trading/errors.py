"""统一交易域错误码。

对应工作包 M1-02（错误码契约）与 M4-06（OKX 错误映射与脱敏）。

设计原则：
    - 前端只依赖本文件定义的稳定内部错误码，永远不解析 OKX 或 Runner 的原始文案。
    - 每个错误码固定映射一个 HTTP 状态码和一句面向用户的中文提示。
    - 错误详情里禁止出现任何凭据字段，脱敏由 :func:`redact` 统一负责。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

# ---------------------------------------------------------------------------
# 内部稳定错误码
# ---------------------------------------------------------------------------

TRADING_RUNNER_UNAVAILABLE: Final = "TRADING_RUNNER_UNAVAILABLE"
TRADING_RUNNER_TIMEOUT: Final = "TRADING_RUNNER_TIMEOUT"
TRADING_RUNNER_UNAUTHORIZED: Final = "TRADING_RUNNER_UNAUTHORIZED"
TRADING_RUNNER_BAD_RESPONSE: Final = "TRADING_RUNNER_BAD_RESPONSE"
TRADING_NOT_FOUND: Final = "TRADING_NOT_FOUND"
TRADING_REJECTED: Final = "TRADING_REJECTED"
TRADING_UPSTREAM_ERROR: Final = "TRADING_UPSTREAM_ERROR"
TRADING_NOT_CONFIGURED: Final = "TRADING_NOT_CONFIGURED"
TRADING_ENVIRONMENT_FORBIDDEN: Final = "TRADING_ENVIRONMENT_FORBIDDEN"
TRADING_LIVE_NOT_APPROVED: Final = "TRADING_LIVE_NOT_APPROVED"
TRADING_INSTRUMENT_NOT_ALLOWED: Final = "TRADING_INSTRUMENT_NOT_ALLOWED"
TRADING_ORDER_TYPE_NOT_ALLOWED: Final = "TRADING_ORDER_TYPE_NOT_ALLOWED"


@dataclass(frozen=True)
class ErrorSpec:
    code: str
    http_status: int
    message: str
    retryable: bool


_SPECS: Final[dict[str, ErrorSpec]] = {
    spec.code: spec
    for spec in (
        ErrorSpec(
            TRADING_RUNNER_UNAVAILABLE, 503, "交易服务不可用：OKX Runner 未启动或无法连接", True
        ),
        ErrorSpec(
            TRADING_RUNNER_TIMEOUT, 504, "交易服务超时：请勿重复提交，请先查询订单真实状态", False
        ),
        ErrorSpec(
            TRADING_RUNNER_UNAUTHORIZED,
            502,
            "交易服务认证失败：网关与 Runner 的服务令牌不匹配",
            False,
        ),
        ErrorSpec(TRADING_RUNNER_BAD_RESPONSE, 502, "交易服务返回了无法解析的响应", False),
        ErrorSpec(TRADING_NOT_FOUND, 404, "未找到对应的交易记录", False),
        ErrorSpec(TRADING_REJECTED, 422, "交易请求被风控或交易规则拒绝", False),
        ErrorSpec(TRADING_UPSTREAM_ERROR, 502, "交易服务内部错误", True),
        ErrorSpec(TRADING_NOT_CONFIGURED, 503, "交易代理未配置：缺少 Runner 地址或服务令牌", False),
        ErrorSpec(TRADING_ENVIRONMENT_FORBIDDEN, 403, "当前运行环境不允许该交易操作", False),
        ErrorSpec(
            TRADING_LIVE_NOT_APPROVED, 403, "实盘未获批准：需要独立审批变量后才能下单", False
        ),
        ErrorSpec(TRADING_INSTRUMENT_NOT_ALLOWED, 422, "该交易品种不在首期允许范围内", False),
        ErrorSpec(TRADING_ORDER_TYPE_NOT_ALLOWED, 422, "该订单类型不在首期允许范围内", False),
    )
}


def spec_for(code: str) -> ErrorSpec:
    return _SPECS.get(code, _SPECS[TRADING_UPSTREAM_ERROR])


class TradingError(Exception):
    """交易域统一异常。所有对外错误都必须经过它。"""

    def __init__(self, code: str, *, detail: str = "", hint: str | None = None) -> None:
        self.spec = spec_for(code)
        self.code = self.spec.code
        self.detail = redact(detail)
        self.hint = hint
        super().__init__(f"{self.code}: {self.spec.message}")

    def payload(self) -> dict[str, object]:
        return {
            "status": "error",
            "error_code": self.code,
            "message": self.spec.message,
            "detail": self.detail,
            "hint": self.hint,
            "retryable": self.spec.retryable,
        }


# ---------------------------------------------------------------------------
# Runner / OKX -> 内部码
# ---------------------------------------------------------------------------


def from_runner_status(status_code: int) -> str:
    """把 Runner 的 HTTP 状态码映射为稳定内部码。

    Runner 的 ``_call`` 只会产生 400（ValueError/RuntimeError）和 404（LookupError），
    其余状态码来自 FastAPI 自身或认证层。
    """
    if status_code == 404:
        return TRADING_NOT_FOUND
    if status_code in {400, 409, 422}:
        return TRADING_REJECTED
    if status_code in {401, 403}:
        return TRADING_RUNNER_UNAUTHORIZED
    if status_code >= 500:
        return TRADING_UPSTREAM_ERROR
    return TRADING_UPSTREAM_ERROR


# OKX 公开错误码 -> 内部码。仅收录对首期永续限价单链路有意义的条目；
# 未收录的一律落到 TRADING_UPSTREAM_ERROR，绝不猜测语义。
_OKX_CODE_MAP: Final[dict[str, str]] = {
    "51000": TRADING_REJECTED,  # 参数错误
    "51001": TRADING_INSTRUMENT_NOT_ALLOWED,  # 合约不存在
    "51008": TRADING_REJECTED,  # 余额不足
    "51009": TRADING_ENVIRONMENT_FORBIDDEN,  # 账户被禁止交易
    "51010": TRADING_REJECTED,  # 账户模式不支持
    "51020": TRADING_REJECTED,  # 下单数量小于最小值
    "51116": TRADING_REJECTED,  # 委托价格超出限价
    "51121": TRADING_REJECTED,  # 下单数量非张数整数倍
    "51400": TRADING_NOT_FOUND,  # 撤单失败：订单不存在
    "51401": TRADING_REJECTED,  # 撤单失败：订单已撤销
    "51402": TRADING_REJECTED,  # 撤单失败：订单已完成
    "50011": TRADING_UPSTREAM_ERROR,  # 请求频率过快
    "50013": TRADING_UPSTREAM_ERROR,  # 系统繁忙
    "50102": TRADING_UPSTREAM_ERROR,  # 时间戳过期
    "50104": TRADING_RUNNER_UNAUTHORIZED,  # 经纪商 ID 不存在
    "50111": TRADING_RUNNER_UNAUTHORIZED,  # API Key 无效
    "50113": TRADING_RUNNER_UNAUTHORIZED,  # 签名无效
    "50114": TRADING_RUNNER_UNAUTHORIZED,  # 无效的授权
}


def from_okx_code(okx_code: str | None) -> str:
    if not okx_code:
        return TRADING_UPSTREAM_ERROR
    return _OKX_CODE_MAP.get(str(okx_code).strip(), TRADING_UPSTREAM_ERROR)


# ---------------------------------------------------------------------------
# 脱敏
# ---------------------------------------------------------------------------

_SENSITIVE_KEYS: Final[tuple[str, ...]] = (
    "apikey",
    "api_key",
    "secret",
    "api_secret",
    "passphrase",
    "password",
    "token",
    "auth_token",
    "authorization",
    "signing_key",
    "signature",
    "sign",
)

_SENSITIVE_PATTERN: Final = re.compile(
    r"(?i)\b("
    + "|".join(re.escape(k) for k in _SENSITIVE_KEYS)
    + r")\b\s*[=:]\s*[\"']?([^\s,\"'}&]+)"
)


def redact(text: str) -> str:
    """把形如 ``api_key=abcdef`` 的片段替换为 ``api_key=***``。"""
    if not text:
        return ""
    return _SENSITIVE_PATTERN.sub(lambda m: f"{m.group(1)}=***", text)


def redact_mapping(payload: object) -> object:
    """递归脱敏任意 JSON 结构中的敏感键。"""
    if isinstance(payload, dict):
        clean: dict[str, object] = {}
        for key, value in payload.items():
            if str(key).lower().replace("-", "_") in _SENSITIVE_KEYS:
                clean[key] = "***"
            else:
                clean[key] = redact_mapping(value)
        return clean
    if isinstance(payload, list):
        return [redact_mapping(item) for item in payload]
    if isinstance(payload, str):
        return redact(payload)
    return payload
