"""风控适配器 — 复用 apps.dispatcher.risk.RiskChecker + 蜜罐检查。

**不重新实现**仓位/敞口/流动性等风控规则，仅做适配：
    1. ``check_order``   : 由调用方组装 ``RiskContext``，委托 ``RiskChecker.check``
       统一校验（仓位 / 总敞口 / 流动性 / 蜜罐），不通过抛 ``RiskError``。
    2. ``check_honeypot``: 蜜罐检查，复用原 AlphaGPT/strategy_manager/risk.py 概念
       （流动性阈值 + Jupiter 卖出路径报价验证）。solana 为重依赖，懒加载；
       实盘关闭场景下若依赖未装则跳过（返回安全）。
"""

from __future__ import annotations

import logging
from typing import Any

from apps.dispatcher.risk import RiskChecker, RiskContext

logger = logging.getLogger(__name__)

# 原 AlphaGPT risk.py 的流动性安全阈值（逐字保留）
_HONEYPOT_MIN_LIQUIDITY_USD = 5000
# SOL 原生代币 mint（用于蜜罐卖出路径验证）
_SOL_MINT = "So11111111111111111111111111111111111111112"


def check_order(intent: dict, **kwargs: Any) -> None:
    """下单前风控校验（复用 RiskChecker，不通过抛 RiskError）。

    Args:
        intent: 下单意图，需含 ``notional``、``symbol`` 等
        kwargs: 账户上下文，用于构造 ``RiskContext``：
            total_equity / position_value / symbol_position_value /
            symbol_liquidity_usd / is_honeypot
    """
    checker = RiskChecker(market="crypto")
    ctx = RiskContext(
        total_equity=float(kwargs.get("total_equity", 0.0)),
        position_value=float(kwargs.get("position_value", 0.0)),
        symbol_position_value=float(kwargs.get("symbol_position_value", 0.0)),
        symbol_liquidity_usd=kwargs.get("symbol_liquidity_usd"),
        is_honeypot=kwargs.get("is_honeypot"),
    )
    checker.check(intent, ctx)
    logger.info("alphagpt 风控通过: %s notional=%s", intent.get("symbol"), intent.get("notional"))


async def check_honeypot(token_address: str, liquidity_usd: float, *, jupiter: Any = None) -> bool:
    """蜜罐检查（复用原 AlphaGPT risk.py 概念）。

    1. 流动性 < 5000 USD → 不安全（阈值逐字保留）
    2. 通过 Jupiter 报价验证卖出路径；无法获取报价 → 疑似蜜罐

    Args:
        token_address: 代币 mint 地址
        liquidity_usd: 代币流动性（USD）
        jupiter: 可选的 Jupiter 聚合器实例（含 ``get_quote`` / ``close`` 异步方法）。
                 缺省时懒加载原 ``execution.jupiter.JupiterAggregator``；
                 若 solana/aiohttp 重依赖未装则跳过（实盘默认关场景）。
    """
    if liquidity_usd < _HONEYPOT_MIN_LIQUIDITY_USD:
        logger.warning("蜜罐检查: 流动性过低 $%s", liquidity_usd)
        return False

    own_jup = False
    if jupiter is None:
        try:
            # 委托原 AlphaGPT execution 层概念；solana/aiohttp 为重依赖
            from execution.jupiter import JupiterAggregator

            jupiter = JupiterAggregator()
            own_jup = True
        except ImportError:
            logger.info("蜜罐检查: solana/execution 依赖未装，跳过（实盘默认关）")
            return True

    try:
        quote = await jupiter.get_quote(
            input_mint=token_address,
            output_mint=_SOL_MINT,
            amount_integer=1000000,
            slippage_bps=1000,
        )
        if not quote:
            logger.warning("蜜罐检查: 无法验证卖出路径（疑似蜜罐）: %s", token_address)
            return False
        return True
    except Exception:
        logger.exception("蜜罐检查异常: %s", token_address)
        return False
    finally:
        if own_jup:
            close = getattr(jupiter, "close", None)
            if close is not None:
                await close()
