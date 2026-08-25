"""订单路由器。

根据 signal.market + signal.source 路由到不同执行通道:
    - a_shares : 条件单（A股无直接实盘，记录拟下单）
    - crypto/okx_grid : OKX 永续下单
    - crypto/alphagpt : Solana 链上执行

默认 dry-run，仅输出拟下单 JSON。

``hold``、展示/降级信号和未授权的加密来源均是不可执行结果，
会显式拒绝，不会被转换为买单或隐式 dry-run。
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime

from core.config import get_config
from core.signals import Signal

logger = logging.getLogger(__name__)


# These values are intentionally kept in the dispatcher boundary rather than
# inferred from a strategy name.  A crypto order must have an execution path
# that has been explicitly reviewed and wired to a venue/wallet.
CRYPTO_EXECUTION_SOURCES = frozenset({"okx_grid", "alphagpt"})
# The dispatcher is the only normalized execution boundary for non-crypto
# markets.  Direct callers may still pass a known strategy source for dry-run
# previews, but an arbitrary/typoed source must not become an order intent.
# Keep this allowlist explicit rather than deriving authorization from a
# caller-provided string or silently accepting every non-crypto source.
MARKET_EXECUTION_SOURCES = {
    "a_shares": frozenset({"dispatcher", "sentiment", "supertrend", "selector", "pa_agent"}),
    "mt5": frozenset({"dispatcher", "alphamaster"}),
    "us_stocks": frozenset({"dispatcher"}),
    "ai_analysis": frozenset({"dispatcher", "pa_agent"}),
    "crypto": CRYPTO_EXECUTION_SOURCES,
}
HOLD_SIGNAL_NOT_ORDERABLE = "hold_signal_not_orderable"
CRYPTO_SOURCE_NOT_AUTHORIZED = "crypto_source_not_authorized"
# Stable generic code for non-crypto (and unknown-market) source/market
# authorization failures.
SOURCE_NOT_AUTHORIZED = "source_not_authorized"
CRYPTO_EXECUTION_SOURCE_AMBIGUOUS = "crypto_execution_source_ambiguous"
SIGNAL_NOT_EXECUTION_ELIGIBLE = "signal_not_execution_eligible"
ORDER_VALUES_INVALID = "order_values_invalid"
EXECUTION_CANCELLED = "execution_cancelled"
EXECUTION_FAILED = "execution_failed"
EXECUTION_UNAVAILABLE = "execution_unavailable"


class OrderRoutingError(ValueError):
    """A signal cannot be converted into an order intent.

    ``ValueError`` is used as the base class so existing callers that validate
    input with a standard value exception continue to work, while ``code``
    gives the API/dispatcher a stable machine-readable rejection reason.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def signal_execution_rejection(signal: Signal) -> tuple[str, str] | None:
    """Return a rejection code/message for display or degraded signals.

    Strategy metadata is deliberately advisory for presentation, but the
    dispatcher treats an explicit display/degraded marker (or an explicit
    non-``True`` execution flag) as a hard execution boundary.  Missing
    ``execution_eligible`` is tolerated for older, already production
    execution-capable signals; producers that opt into the field must set it
    to the literal boolean ``True``.
    """

    meta = signal.meta or {}
    reasons: list[str] = []
    if meta.get("display_only"):
        reasons.append("display_only")
    if meta.get("degraded"):
        reasons.append("degraded")
    if meta.get("realtime_only"):
        reasons.append(
            "realtime_only_without_kline" if meta.get("with_kline") is False else "realtime_only"
        )
    if "execution_eligible" in meta and meta.get("execution_eligible") is not True:
        reasons.append("execution_eligible!=true")
    if not reasons:
        return None
    return (
        SIGNAL_NOT_EXECUTION_ELIGIBLE,
        "信号标记为非执行性展示/降级结果: " + ", ".join(reasons),
    )


@dataclass
class OrderIntent:
    """拟下单意图。"""

    symbol: str
    market: str
    side: str  # buy | sell
    qty: float
    price: float | None = None
    order_type: str = "limit"  # limit | market
    notional: float | None = None
    source: str = ""
    ts: datetime = field(default_factory=datetime.now)
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        return d

    def summary(self) -> dict:
        """人类可读摘要（供 CLI 确认）。"""
        return {
            "标的": self.symbol,
            "市场": self.market,
            "方向": self.side,
            "数量": self.qty,
            "价格": self.price,
            "类型": self.order_type,
            "来源": self.source,
        }


class OrderRouter:
    """订单路由器。

    dry_run=True 时仅打印拟下单 JSON，不实际报单。
    """

    def __init__(self, dry_run: bool | None = None) -> None:
        if dry_run is None:
            # 默认根据全局 live_trading 决定
            dry_run = not get_config().get("live_trading", False)
        self.dry_run = dry_run

    def route(self, signal: Signal, qty: float, price: float | None = None) -> OrderIntent:
        """根据信号生成订单意图并路由。"""
        execution_rejection = signal_execution_rejection(signal)
        if execution_rejection is not None:
            code, message = execution_rejection
            raise OrderRoutingError(code, message)

        # ``hold`` is a useful display/research outcome, but it is not an
        # order side.  Never turn it into a buy as a compatibility shortcut.
        if signal.direction == "hold":
            raise OrderRoutingError(
                HOLD_SIGNAL_NOT_ORDERABLE,
                "hold 信号仅用于展示，不生成订单",
            )

        # Every market has an explicit execution-source allowlist.  In
        # particular, an unknown crypto source must not be silently converted
        # into a dry-run intent, and a non-crypto typo must not bypass the same
        # authorization boundary.  Validate in dry-run too so an unreviewed
        # source cannot look legitimate in previews and later be promoted.
        allowed_sources = MARKET_EXECUTION_SOURCES.get(signal.market)
        if allowed_sources is None or signal.source not in allowed_sources:
            code = (
                CRYPTO_SOURCE_NOT_AUTHORIZED if signal.market == "crypto" else SOURCE_NOT_AUTHORIZED
            )
            raise OrderRoutingError(
                code,
                f"未授权的执行来源/市场: market={signal.market!r} source={signal.source or '<empty>'}",
            )

        # Never let NaN/Infinity/zero/negative values reach a venue adapter or
        # produce a misleading dry-run intent.  A missing price is allowed for
        # market orders and for the existing dry-run preview contract; when a
        # price is supplied it must always be finite and strictly positive.
        try:
            qty_value = float(qty)
        except (TypeError, ValueError) as exc:
            raise OrderRoutingError(ORDER_VALUES_INVALID, "订单数量必须是有限正数") from exc
        if isinstance(qty, bool) or not math.isfinite(qty_value) or qty_value <= 0:
            raise OrderRoutingError(ORDER_VALUES_INVALID, "订单数量必须是有限正数")

        price_value: float | None
        if price is None:
            price_value = None
        else:
            try:
                price_value = float(price)
            except (TypeError, ValueError) as exc:
                raise OrderRoutingError(ORDER_VALUES_INVALID, "订单价格必须是有限正数") from exc
            if isinstance(price, bool) or not math.isfinite(price_value) or price_value <= 0:
                raise OrderRoutingError(ORDER_VALUES_INVALID, "订单价格必须是有限正数")

        if price_value is not None and not math.isfinite(qty_value * price_value):
            raise OrderRoutingError(ORDER_VALUES_INVALID, "订单名义价值必须是有限数")

        intent = OrderIntent(
            symbol=signal.symbol,
            market=signal.market,
            side=signal.direction,
            qty=qty_value,
            price=price_value,
            notional=qty_value * price_value if price_value is not None else None,
            source=signal.source,
            meta={"signal_score": signal.score, "signal_confidence": signal.confidence},
        )

        if self.dry_run:
            self._dry_run(intent)
            return intent

        # 实盘路由（需各模块 enable + live + 密钥）
        if signal.market == "crypto":
            try:
                if signal.source == "okx_grid":
                    self._route_okx(intent)
                elif signal.source == "alphagpt":
                    self._route_solana(intent)
            except OrderRoutingError:
                # Execution failures/cancellation must never fall through to
                # the success return below.  Keep the stable routing error
                # code for dispatcher/API callers.
                raise
            except Exception as exc:  # noqa: BLE001 - execution boundary
                logger.exception("加密执行通道异常: %s", intent.symbol)
                raise OrderRoutingError(
                    EXECUTION_FAILED,
                    f"加密执行通道异常: {exc}",
                ) from exc
        else:
            # A股没有已接入的实盘通道。 仅 dry-run 可以展示拟下单意图；
            # 实盘调用必须明确失败，不能把日志写入误报成已提交的条件单。
            self._route_a_shares(intent)
        return intent

    def _dry_run(self, intent: OrderIntent) -> None:
        logger.info("[DRY-RUN] 拟下单: %s", intent.to_dict())
        print(json.dumps(intent.to_dict(), ensure_ascii=False, indent=2, default=str))

    def _route_okx(self, intent: OrderIntent) -> None:
        from apps.dispatcher.confirm import cli_confirm

        if not cli_confirm(intent.summary()):
            logger.info("用户取消 OKX 下单: %s", intent.symbol)
            raise OrderRoutingError(EXECUTION_CANCELLED, "用户取消 OKX 下单")
        try:
            from core.data_feed.okx_source import OkxSource

            cfg = get_config("crypto").get("modules", {}).get("okx_grid", {}).get("api", {})
            ex = OkxSource(
                api_key=cfg.get("key"),
                secret=cfg.get("secret"),
                passphrase=cfg.get("passphrase"),
            )._exchange
            symbol = intent.symbol if "/" in intent.symbol else f"{intent.symbol}/USDT:USDT"
            if intent.order_type == "market":
                receipt = ex.create_market_order(symbol, intent.side, intent.qty)
            else:
                receipt = ex.create_limit_order(symbol, intent.side, intent.qty, intent.price)
            if receipt is None:
                raise RuntimeError("OKX 执行通道未返回订单回执")
            logger.info("OKX 下单成功: %s", intent.symbol)
        except Exception as exc:  # noqa: BLE001 - preserve venue failure
            logger.exception("OKX 下单失败: %s", intent.symbol)
            raise OrderRoutingError(
                EXECUTION_FAILED,
                f"OKX 下单失败: {exc}",
            ) from exc

    def _route_solana(self, intent: OrderIntent) -> None:
        from apps.dispatcher.confirm import cli_confirm

        if not cli_confirm(intent.summary()):
            logger.info("用户取消 Solana 下单: %s", intent.symbol)
            raise OrderRoutingError(EXECUTION_CANCELLED, "用户取消 Solana 下单")
        # The Solana executor is not wired into this dispatcher boundary yet.
        # Do not report a successful OrderIntent merely because confirmation
        # was accepted; callers must receive an explicit unavailable result.
        raise OrderRoutingError(
            EXECUTION_UNAVAILABLE,
            "Solana 执行通道尚未接入，未提交订单",
        )

    def _route_a_shares(self, intent: OrderIntent) -> None:
        raise OrderRoutingError(
            EXECUTION_UNAVAILABLE,
            "A股实盘通道尚未接入，未提交条件单",
        )
