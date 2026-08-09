"""交易代理配置。

对应工作包 M1-01（唯一公开运行边界）与 P0-05（首期 OKX 范围裁决）。

铁律：
    - 浏览器永远不提供 Runner 地址和服务令牌，只能由服务端环境变量注入。
    - OKX 的 API Key / Secret / Passphrase 只存在于 Runner 进程，网关不读取、不透传。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

Environment = Literal["shadow", "demo", "live"]

# P0-05 决议：首期只支持 OKX **永续（SWAP）**，只放开限价单与撤单。
# 变更本常量必须同步更新 docs/Plan/evidence/P0-05-okx-first-scope.md 与验收台账。
FIRST_PHASE_PRODUCT: Environment | str = "swap"
FIRST_PHASE_ALLOWED_ORDER_TYPES: tuple[str, ...] = ("limit",)
FIRST_PHASE_ALLOWED_SYMBOLS: tuple[str, ...] = ("BTC-USDT-SWAP",)


@dataclass(frozen=True)
class TradingProxySettings:
    base_url: str
    auth_token: str | None
    timeout_seconds: float
    connect_timeout_seconds: float
    environment: Environment
    live_approved: bool
    enforce_first_phase_scope: bool

    @property
    def configured(self) -> bool:
        """Runner 地址存在，且非 shadow 环境时必须同时具备服务令牌。"""
        if not self.base_url:
            return False
        if self.environment != "shadow" and not self.auth_token:
            return False
        return True

    @property
    def trading_enabled(self) -> bool:
        """是否允许发起真实下单/撤单。shadow 环境永远只读。"""
        if not self.configured:
            return False
        if self.environment == "shadow":
            return False
        if self.environment == "live":
            return self.live_approved
        return True


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def load_settings() -> TradingProxySettings:
    environment = os.environ.get("QH_RUNNER_ENVIRONMENT", "shadow").strip() or "shadow"
    if environment not in {"shadow", "demo", "live"}:
        environment = "shadow"
    return TradingProxySettings(
        base_url=os.environ.get("QH_RUNNER_BASE_URL", "http://127.0.0.1:8103").strip().rstrip("/"),
        auth_token=os.environ.get("QH_RUNNER_AUTH_TOKEN") or None,
        timeout_seconds=_float_env("QH_RUNNER_TIMEOUT_SECONDS", 8.0),
        connect_timeout_seconds=_float_env("QH_RUNNER_CONNECT_TIMEOUT_SECONDS", 3.0),
        environment=environment,  # type: ignore[arg-type]
        live_approved=os.environ.get("QH_RUNNER_LIVE_APPROVED") == "1",
        enforce_first_phase_scope=os.environ.get("QH_TRADING_SCOPE_ENFORCED", "1") != "0",
    )
