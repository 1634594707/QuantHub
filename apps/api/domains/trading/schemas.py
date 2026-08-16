"""``/api/trading/*`` 请求模型。

对应工作包 M1-02。所有字段都必须由服务端再校验一次；浏览器提交的任何
风险相关声明（例如"已通过风控"）一律忽略，风控结论只以 Runner 为准。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProtectionOrder(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trigger_price: float = Field(gt=0)
    order_price: float | None = Field(default=None, gt=0)


class OrderIntentRequest(BaseModel):
    """订单意图。``intent_id`` 是幂等键，重复提交必须返回同一笔订单。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: str = Field(min_length=1, max_length=128)
    strategy_version: str = Field(min_length=1, max_length=64)
    intent_id: str = Field(min_length=3, max_length=128)
    account_id: str = Field(min_length=1, max_length=128)
    symbol: str = Field(min_length=3, max_length=64)
    side: Literal["buy", "sell"]
    order_type: Literal["limit", "market"]
    quantity: float = Field(gt=0)
    price: float | None = Field(default=None, gt=0)
    leverage: float = Field(default=1, gt=0)
    reduce_only: bool = False
    stop_loss: ProtectionOrder | None = None
    take_profit: ProtectionOrder | None = None

    def to_runner_payload(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "intent_id": self.intent_id,
            "account_id": self.account_id,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "quantity": self.quantity,
            "price": self.price,
            "leverage": self.leverage,
            "reduce_only": self.reduce_only,
            "stop_loss": self.stop_loss.model_dump(mode="json") if self.stop_loss else None,
            "take_profit": self.take_profit.model_dump(mode="json") if self.take_profit else None,
        }


class AmendOrderRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quantity: float = Field(gt=0)
    price: float | None = Field(default=None, gt=0)
    stop_loss: ProtectionOrder | None = None
    take_profit: ProtectionOrder | None = None


class ClosePositionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: str = Field(min_length=1, max_length=128)
    strategy_version: str = Field(min_length=1, max_length=64)
    intent_id: str = Field(min_length=3, max_length=128)
    quantity: float | None = Field(default=None, gt=0)
    order_type: Literal["market", "limit"] = "market"
    price: float | None = Field(default=None, gt=0)


class RiskModeRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: str = Field(default="global", min_length=1, max_length=128)
    mode: Literal["normal", "halted", "cancel_only"]
    reason: str = Field(min_length=3, max_length=500)
    operator: str = Field(min_length=2, max_length=100)


class ResolveDiffRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    owner: str = Field(min_length=2, max_length=100)
    resolution: str = Field(min_length=3, max_length=500)
