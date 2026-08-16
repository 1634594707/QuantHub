from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.strategy_package import StrategyReleasePackage


class PackageImport(BaseModel):
    package: StrategyReleasePackage


class ProtectionOrder(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trigger_price: float = Field(gt=0)
    order_price: float | None = Field(default=None, gt=0)


class OrderRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: str
    strategy_version: str
    # Created by the signal producer or operator once and retained for every retry.
    # It is an order-intent identity, not a browser-derived risk declaration.
    intent_id: str = Field(min_length=3, max_length=128)
    account_id: str
    symbol: str
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit"]
    quantity: float = Field(gt=0)
    price: float | None = Field(default=None, gt=0)
    leverage: float = Field(default=1, gt=0)
    reduce_only: bool = False
    stop_loss: ProtectionOrder | None = None
    take_profit: ProtectionOrder | None = None


class AmendOrderRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quantity: float = Field(gt=0)
    price: float | None = Field(default=None, gt=0)
    stop_loss: ProtectionOrder | None = None
    take_profit: ProtectionOrder | None = None


class ClosePositionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: str
    strategy_version: str
    intent_id: str = Field(min_length=3, max_length=128)
    quantity: float | None = Field(default=None, gt=0)
    order_type: Literal["market", "limit"] = "market"
    price: float | None = Field(default=None, gt=0)


class RiskModeRequest(BaseModel):
    scope: str = "global"
    mode: Literal["normal", "halted", "cancel_only"]
    reason: str = Field(min_length=3)
    operator: str = Field(min_length=2, max_length=100)
