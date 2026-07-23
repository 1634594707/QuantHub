"""信号中枢 dispatcher。

职责:
    1. 汇聚各策略产出的 Signal（订阅信号总线）
    2. 多源打分加权聚合（按 configs/base.yaml: signals.weights）
    3. 风控校验（仓位/流动性/蜜罐）
    4. 路由到 OKX / 链上 / 条件单
    5. 默认 dry-run，仅输出拟下单 JSON
    6. 实盘模式需 CLI 二次确认

CLI 二次确认:
    live_trading=true 且模块 live=true 时，下单前在终端要求输入确认码。
"""

from __future__ import annotations

from apps.dispatcher.confirm import cli_confirm
from apps.dispatcher.risk import RiskChecker, RiskError
from apps.dispatcher.router import OrderIntent, OrderRouter

__all__ = [
    "OrderIntent",
    "OrderRouter",
    "RiskChecker",
    "RiskError",
    "cli_confirm",
]
