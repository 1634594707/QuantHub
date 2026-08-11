from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "limit"]
OrderStatus = Literal["pending", "partially_filled", "filled", "cancelled"]


class SimulationOrderCreate(BaseModel):
    signal_id: str | None = None
    symbol: str | None = None
    market: str = "a_shares"
    side: OrderSide | None = None
    order_type: OrderType = "market"
    quantity: float = Field(gt=0)
    limit_price: float | None = Field(default=None, gt=0)
    account_id: str = Field(default="paper", min_length=1, max_length=100)
    factor_key: str | None = Field(default=None, min_length=1, max_length=80)
    factor_version: str | None = Field(default=None, pattern=r"^\d+\.\d+\.\d+$")
    research_run_id: str | None = Field(default=None, min_length=1, max_length=120)
    rebalance_cycle_id: str | None = Field(default=None, min_length=1, max_length=120)
    signal_time: datetime | None = None
    tradable_time: datetime | None = None
    theoretical_price: float | None = Field(default=None, gt=0)
    capacity_used: float = Field(default=0, ge=0)

    @field_validator("signal_id")
    @classmethod
    def normalize_optional_id(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    @field_validator("symbol")
    @classmethod
    def normalize_optional_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value and value.strip() else None

    @field_validator("market", "account_id")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("字段不能为空")
        return normalized

    @model_validator(mode="after")
    def validate_order_context(self):
        if not self.signal_id and (not self.symbol or not self.side):
            raise ValueError("手工模拟订单必须提供 symbol 和 side")
        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("限价单必须提供 limit_price")
        if self.factor_version and not self.factor_key:
            raise ValueError("factor_version 必须与 factor_key 一起提供")
        return self


class SimulationOrderPreviewRequest(BaseModel):
    signal_id: str = Field(min_length=1)
    quantity: float = Field(gt=0)

    @field_validator("signal_id")
    @classmethod
    def normalize_signal_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("字段不能为空")
        return normalized


class SimulationFillCreate(BaseModel):
    quantity: float | None = Field(default=None, gt=0)
    price: float = Field(gt=0)
    fee_rate: float = Field(default=0.0003, ge=0, le=0.1)


# ---- M4 模拟演示（回测沙盒）----
DemoSource = Literal["okx_local", "okx_live", "synthetic"]


class DemoRunRequest(BaseModel):
    """一键回测演示请求。所有参数均有默认值，仅传 {} 即可跑通默认演示。

    数据源语义：
    - ``okx_local``（默认）：本地归档的真实 OKX K 线，离线、完全可复现。
    - ``okx_live``：经公共行情接口实时拉取真实 OKX 行情，首拉落盘快照后可复现。
    - ``synthetic``：确定性合成行情，由 ``dataset`` + ``seed`` 决定。
    """

    source: DemoSource = "okx_local"
    symbol: str | None = Field(default=None, min_length=1, max_length=40)
    use_cache: bool = True
    end: str | None = Field(default=None, min_length=4, max_length=32)

    dataset: str = Field(default="uptrend", min_length=1, max_length=40)
    seed: int = Field(default=12, ge=0, le=999999)
    n_bars: int = Field(default=250, ge=10, le=5000)
    interval: str = Field(default="1d", pattern=r"^(1m|5m|15m|30m|1h|4h|1d)$")
    start: str | None = Field(default=None, min_length=4, max_length=32)
    initial_capital: float = Field(default=1_000_000.0, gt=0, le=1e12)
    commission: float = Field(default=0.0003, ge=0, le=0.1)
    position_fraction: float = Field(default=1.0, gt=0, le=1.0)
    strategy: str = Field(default="factor_follow", min_length=1, max_length=40)
    factor: str | None = Field(default=None, min_length=1, max_length=80)
    factor_params: dict[str, Any] = Field(default_factory=dict)
    factor_ast: dict[str, Any] | None = Field(default=None, min_length=1)
    factor_label: str | None = Field(default=None, min_length=1, max_length=120)
    factor_version: str | None = Field(
        default=None,
        pattern=r"^\d+\.\d+\.\d+$",
    )

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value and value.strip() else None

    @field_validator("start", "end")
    @classmethod
    def normalize_time_bound(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    @model_validator(mode="after")
    def validate_source_context(self):
        if self.source == "okx_local" and self.symbol is None:
            self.symbol = "BTCUSDT"
        if self.source == "okx_live" and self.symbol is None:
            self.symbol = "BTC-USDT-SWAP"
        return self
