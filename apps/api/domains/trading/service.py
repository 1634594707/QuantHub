"""交易域服务层。

对应工作包：
    M1-03 实现 API 到 Runner 交易代理
    M1-04 聚合 Runner 健康和环境状态
    M1-06 Runner 不可用降级
    M3-03 统一数据来源契约

安全边界：
    - 本层是浏览器与 Runner 之间**唯一**的通路。
    - 本层永远不读取 OKX 凭据，也不把 Runner 的服务令牌写进任何返回值。
    - 首期交易范围（P0-05：永续 + 限价单）在这里做服务端强制校验，
      不信任前端传入的 symbol/order_type。
"""

from __future__ import annotations

import logging
from typing import Any

from apps.api.contracts import Source, envelope

from . import errors
from .client import RunnerClient
from .config import (
    FIRST_PHASE_ALLOWED_ORDER_TYPES,
    FIRST_PHASE_ALLOWED_SYMBOLS,
    FIRST_PHASE_PRODUCT,
    TradingProxySettings,
    load_settings,
)
from .schemas import OrderIntentRequest, ResolveDiffRequest, RiskModeRequest

logger = logging.getLogger(__name__)

HEALTH_TTL_SECONDS = 30.0
ACCOUNT_TTL_SECONDS = 60.0
ORDER_TTL_SECONDS = 15.0


class TradingService:
    def __init__(
        self,
        settings: TradingProxySettings | None = None,
        client: RunnerClient | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.client = client or RunnerClient(self.settings)

    # -- 通用 ---------------------------------------------------------------

    @property
    def source(self) -> Source:
        return Source(kind="runner", name="okx_runner", environment=self.settings.environment)

    def _wrap(self, data: Any, ttl: float | None = None, observed_at: str | None = None) -> dict:
        return envelope(data, source=self.source, ttl_seconds=ttl, observed_at=observed_at)

    # -- M1-04 健康与环境聚合 ------------------------------------------------

    def health(self) -> dict:
        """聚合 Runner 健康、版本、环境、连接与权限。

        永远不返回密钥。Runner 不可达时返回 ``status=error`` 而不是抛异常，
        以便前端在只读页面上安全降级（M1-06）。
        """
        base = {
            "configured": self.settings.configured,
            "trading_enabled": self.settings.trading_enabled,
            "environment": self.settings.environment,
            "live_approved": self.settings.live_approved,
            "first_phase_scope": {
                "product": FIRST_PHASE_PRODUCT,
                "allowed_order_types": list(FIRST_PHASE_ALLOWED_ORDER_TYPES),
                "allowed_symbols": list(FIRST_PHASE_ALLOWED_SYMBOLS),
                "enforced": self.settings.enforce_first_phase_scope,
            },
        }

        if not self.settings.configured:
            return envelope(
                None,
                source=self.source,
                error_code=errors.TRADING_NOT_CONFIGURED,
                message=errors.spec_for(errors.TRADING_NOT_CONFIGURED).message,
                hint="设置 QH_RUNNER_BASE_URL / QH_RUNNER_AUTH_TOKEN 后重启网关",
                retryable=False,
                extra={"runner": base},
            )

        try:
            payload = self.client.call("GET", "/health")
        except errors.TradingError as exc:
            body = exc.payload()
            return envelope(
                None,
                source=self.source,
                error_code=exc.code,
                message=str(body["message"]),
                detail=str(body["detail"]),
                hint=exc.hint,
                retryable=bool(body["retryable"]),
                extra={"runner": base | {"reachable": False}},
            )

        runner = base | {
            "reachable": True,
            "version": payload.get("version"),
            "product": payload.get("product"),
            "runner_environment": payload.get("environment"),
            # database 是服务端本地路径，属于部署信息而非凭据，但仍不向浏览器透出。
            "permissions": "trade" if self.settings.trading_enabled else "read_only",
        }
        mismatch = (
            payload.get("environment") is not None
            and payload.get("environment") != self.settings.environment
        )
        if mismatch:
            runner["environment_mismatch"] = True
        return envelope(runner, source=self.source, ttl_seconds=HEALTH_TTL_SECONDS)

    # -- 首期范围强制 --------------------------------------------------------

    def _enforce_scope(self, request: OrderIntentRequest) -> None:
        if not self.settings.enforce_first_phase_scope:
            return
        if request.order_type not in FIRST_PHASE_ALLOWED_ORDER_TYPES:
            raise errors.TradingError(
                errors.TRADING_ORDER_TYPE_NOT_ALLOWED,
                detail=f"order_type={request.order_type}",
                hint=f"首期仅允许 {', '.join(FIRST_PHASE_ALLOWED_ORDER_TYPES)}",
            )
        if request.order_type == "limit" and request.price is None:
            raise errors.TradingError(
                errors.TRADING_REJECTED,
                detail="限价单必须提供 price",
            )
        if request.symbol not in FIRST_PHASE_ALLOWED_SYMBOLS:
            raise errors.TradingError(
                errors.TRADING_INSTRUMENT_NOT_ALLOWED,
                detail=f"symbol={request.symbol}",
                hint=f"首期仅允许 {', '.join(FIRST_PHASE_ALLOWED_SYMBOLS)}",
            )

    def _require_trading(self) -> None:
        if not self.settings.configured:
            raise errors.TradingError(errors.TRADING_NOT_CONFIGURED)
        if self.settings.environment == "shadow":
            raise errors.TradingError(
                errors.TRADING_ENVIRONMENT_FORBIDDEN,
                detail="shadow 环境为只读，不允许下单或撤单",
                hint="切换到 demo 环境并完成 M4 验收后再试",
            )
        if self.settings.environment == "live" and not self.settings.live_approved:
            raise errors.TradingError(
                errors.TRADING_LIVE_NOT_APPROVED,
                detail="QH_RUNNER_LIVE_APPROVED != 1",
                hint="实盘需要独立审批变量与 M5-06 安全评审",
            )

    # -- 读操作 -------------------------------------------------------------

    def dashboard(self) -> dict:
        return self._wrap(self.client.call("GET", "/api/dashboard"), ttl=ORDER_TTL_SECONDS)

    def account(self, account_id: str) -> dict:
        data = self.client.call("GET", f"/api/accounts/{account_id}")
        observed = data.get("latest_snapshot_at") if isinstance(data, dict) else None
        return self._wrap(data, ttl=ACCOUNT_TTL_SECONDS, observed_at=observed)

    def order(self, order_id: str) -> dict:
        data = self.client.call("GET", f"/api/orders/{order_id}")
        observed = data.get("updated_at") if isinstance(data, dict) else None
        return self._wrap(data, ttl=ORDER_TTL_SECONDS, observed_at=observed)

    def reconciliation_diff(self, diff_id: str) -> dict:
        return self._wrap(self.client.call("GET", f"/api/reconciliation/diffs/{diff_id}"))

    # -- 写操作 -------------------------------------------------------------

    def submit_order(self, request: OrderIntentRequest) -> dict:
        self._require_trading()
        self._enforce_scope(request)
        data = self.client.call("POST", "/api/orders", request.to_runner_payload())
        return self._wrap(data, ttl=ORDER_TTL_SECONDS)

    def cancel_order(self, order_id: str) -> dict:
        self._require_trading()
        return self._wrap(self.client.call("POST", f"/api/orders/{order_id}/cancel"))

    def recover_orders(self) -> dict:
        # 恢复是只读语义的补偿动作，shadow 下同样允许，用于验证链路。
        if not self.settings.configured:
            raise errors.TradingError(errors.TRADING_NOT_CONFIGURED)
        return self._wrap(self.client.call("POST", "/api/recovery/orders"))

    def reconcile(self, account_id: str) -> dict:
        if not self.settings.configured:
            raise errors.TradingError(errors.TRADING_NOT_CONFIGURED)
        return self._wrap(self.client.call("POST", f"/api/reconciliation/{account_id}"))

    def resolve_diff(self, diff_id: str, request: ResolveDiffRequest) -> dict:
        if not self.settings.configured:
            raise errors.TradingError(errors.TRADING_NOT_CONFIGURED)
        return self._wrap(
            self.client.call(
                "POST",
                f"/api/reconciliation/diffs/{diff_id}/resolve",
                {"owner": request.owner, "resolution": request.resolution},
            )
        )

    def set_risk_mode(self, request: RiskModeRequest) -> dict:
        if not self.settings.configured:
            raise errors.TradingError(errors.TRADING_NOT_CONFIGURED)
        return self._wrap(
            self.client.call(
                "POST",
                "/api/risk/mode",
                {
                    "scope": request.scope,
                    "mode": request.mode,
                    "reason": request.reason,
                    "operator": request.operator,
                },
            )
        )


_service: TradingService | None = None


def get_service() -> TradingService:
    """进程内单例。测试通过 :func:`set_service` 注入替身。"""
    global _service
    if _service is None:
        _service = TradingService()
    return _service


def set_service(service: TradingService | None) -> None:
    global _service
    _service = service
