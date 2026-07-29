"""风控校验。

实盘下单前强制风控：
    - 仓位限制（单标的最大占比）
    - 总敞口限制
    - 流动性检查（最小流动性）
    - 蜜罐检查（加密，复用 AlphaGPT risk.py 概念）

研究模式（dry-run）跳过风控，仅记录。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.config import get_config

logger = logging.getLogger(__name__)


class RiskError(Exception):
    """风控不通过。"""


@dataclass
class RiskContext:
    """风控上下文（当前账户状态）。"""

    total_equity: float
    position_value: float = 0.0  # 当前持仓总市值
    symbol_position_value: float = 0.0  # 当前标的持仓市值
    symbol_liquidity_usd: float | None = None  # 标的流动性（加密）
    is_honeypot: bool | None = None  # 是否蜜罐（加密）


class RiskChecker:
    """风控检查器。"""

    def __init__(self, market: str = "crypto") -> None:
        cfg = get_config(market).get("risk", {})
        self.max_position_per_symbol = cfg.get("max_position_per_symbol", 0.15)
        self.max_total_exposure = cfg.get("max_total_exposure", 0.8)
        self.min_liquidity_usd = cfg.get("min_liquidity_usd", 50000)
        self.honeypot_check = cfg.get("honeypot_check", True)
        self.slippage_bps = cfg.get("slippage_bps", 50)

    def check(self, intent: dict, ctx: RiskContext) -> None:
        """校验下单意图。不通过抛 RiskError。"""
        order_value = float(intent.get("notional", 0))
        side = str(intent.get("side", "buy"))
        if order_value <= 0:
            raise RiskError("下单金额非正")

        if ctx.total_equity <= 0:
            raise RiskError("总权益非正")

        # 单标的仓位
        direction = -1.0 if side == "sell" else 1.0
        new_symbol_value = max(0.0, ctx.symbol_position_value + direction * order_value)
        if new_symbol_value / ctx.total_equity > self.max_position_per_symbol:
            raise RiskError(
                f"单标的仓位超限: {new_symbol_value / ctx.total_equity:.2%} > "
                f"{self.max_position_per_symbol:.2%}"
            )

        # 总敞口
        new_total = max(0.0, ctx.position_value + direction * order_value)
        if new_total / ctx.total_equity > self.max_total_exposure:
            raise RiskError(
                f"总敞口超限: {new_total / ctx.total_equity:.2%} > {self.max_total_exposure:.2%}"
            )

        # 流动性（加密）
        if ctx.symbol_liquidity_usd is not None:
            if ctx.symbol_liquidity_usd < self.min_liquidity_usd:
                raise RiskError(
                    f"流动性不足: {ctx.symbol_liquidity_usd} < {self.min_liquidity_usd}"
                )

        # 蜜罐
        if self.honeypot_check and ctx.is_honeypot:
            raise RiskError("蜜罐检查不通过")

        logger.info("风控通过: %s notional=%s", intent.get("symbol"), order_value)
