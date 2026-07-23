"""订单路由器。

根据 signal.market + signal.source 路由到不同执行通道:
    - a_shares : 条件单（A股无直接实盘，记录拟下单）
    - crypto/okx_grid : OKX 永续下单
    - crypto/alphagpt : Solana 链上执行

默认 dry-run，仅输出拟下单 JSON。
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime

from core.config import get_config
from core.signals import Signal

logger = logging.getLogger(__name__)


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
        intent = OrderIntent(
            symbol=signal.symbol,
            market=signal.market,
            side=signal.direction if signal.direction != "hold" else "buy",
            qty=qty,
            price=price,
            source=signal.source,
            meta={"signal_score": signal.score, "signal_confidence": signal.confidence},
        )

        if self.dry_run:
            self._dry_run(intent)
            return intent

        # 实盘路由（需各模块 enable + live + 密钥）
        if signal.market == "crypto":
            if signal.source == "okx_grid":
                self._route_okx(intent)
            elif signal.source == "alphagpt":
                self._route_solana(intent)
            else:
                logger.warning("未知加密来源，转 dry-run: %s", signal.source)
                self._dry_run(intent)
        else:
            # A股无直接实盘通道，记录条件单
            self._route_a_shares(intent)
        return intent

    def _dry_run(self, intent: OrderIntent) -> None:
        logger.info("[DRY-RUN] 拟下单: %s", intent.to_dict())
        print(json.dumps(intent.to_dict(), ensure_ascii=False, indent=2, default=str))

    def _route_okx(self, intent: OrderIntent) -> None:
        from apps.dispatcher.confirm import cli_confirm

        if not cli_confirm(intent.summary()):
            logger.info("用户取消 OKX 下单: %s", intent.symbol)
            return
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
                ex.create_market_order(symbol, intent.side, intent.qty)
            else:
                ex.create_limit_order(symbol, intent.side, intent.qty, intent.price)
            logger.info("OKX 下单成功: %s", intent.symbol)
        except Exception:
            logger.exception("OKX 下单失败: %s", intent.symbol)

    def _route_solana(self, intent: OrderIntent) -> None:
        from apps.dispatcher.confirm import cli_confirm

        if not cli_confirm(intent.summary()):
            logger.info("用户取消 Solana 下单: %s", intent.symbol)
            return
        # 链上执行由 strategies/crypto/alphagpt 的 execution 模块负责
        logger.info("[链上] Solana 下单委托 alphagpt 执行: %s", intent.symbol)

    def _route_a_shares(self, intent: OrderIntent) -> None:
        logger.info("[A股] 记录条件单（无直接实盘通道）: %s", intent.to_dict())
