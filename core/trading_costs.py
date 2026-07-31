"""带来源和生效区间的交易成本档案。

研究引擎只接受已经换算为单边 bp 的成本组件。原始费率、点差、资金费率
和合约参数仍保留在组件中，便于审计；没有来源或无法换算的组件不能进入
可交易性验证。
"""

from __future__ import annotations

from datetime import date, datetime
from math import isfinite
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class TradingCostComponent(BaseModel):
    key: str = Field(min_length=1, max_length=60)
    label: str = Field(min_length=1, max_length=120)
    value: float = Field(ge=0)
    unit: str = Field(min_length=1, max_length=40)
    normalized_bps: float | None = Field(default=None, ge=0, le=10_000)
    source_url: str = Field(min_length=1, max_length=500)
    source_captured_at: datetime
    effective_from: date
    effective_to: date | None = None
    market: str = Field(min_length=1, max_length=40)
    symbol: str | None = Field(default=None, max_length=80)
    account_scope: str | None = Field(default=None, max_length=120)
    charge_basis: Literal["per_fill", "per_bar"] = "per_fill"

    @field_validator("key", "label", "unit", "source_url", "market", "account_scope", "symbol")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("value", "normalized_bps")
    @classmethod
    def reject_non_finite(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("交易成本数值必须是有限数字")
        return value

    @field_validator("source_captured_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("source_captured_at 必须包含时区")
        return value

    @model_validator(mode="after")
    def validate_effective_dates(self) -> TradingCostComponent:
        if self.effective_from and self.effective_to and self.effective_from > self.effective_to:
            raise ValueError("effective_from 不能晚于 effective_to")
        if not self.source_url.startswith(("https://", "http://")):
            raise ValueError("source_url 必须是 HTTP(S) 地址")
        return self


class TradingExecutionConstraint(BaseModel):
    key: str = Field(min_length=1, max_length=60)
    label: str = Field(min_length=1, max_length=120)
    value: str | float | int | bool
    unit: str = Field(min_length=1, max_length=40)
    source_url: str = Field(min_length=1, max_length=500)
    source_captured_at: datetime
    effective_from: date
    effective_to: date | None = None

    @model_validator(mode="after")
    def validate_source_and_dates(self) -> TradingExecutionConstraint:
        if not self.source_url.startswith(("https://", "http://")):
            raise ValueError("source_url 必须是 HTTP(S) 地址")
        if self.source_captured_at.tzinfo is None or self.source_captured_at.utcoffset() is None:
            raise ValueError("source_captured_at 必须包含时区")
        if self.effective_to and self.effective_from > self.effective_to:
            raise ValueError("effective_from 不能晚于 effective_to")
        return self


class TradingCostProfile(BaseModel):
    market: str = Field(min_length=1, max_length=40)
    components: list[TradingCostComponent] = Field(min_length=1, max_length=20)
    participation_rate: float | None = Field(default=None, gt=0, le=1)
    execution_constraints: list[TradingExecutionConstraint] = Field(
        default_factory=list, max_length=30
    )

    @property
    def total_transaction_cost_bps(self) -> float:
        missing = [item.key for item in self.components if item.normalized_bps is None]
        if missing:
            raise ValueError(f"成本组件缺少 normalized_bps: {', '.join(missing)}")
        return round(sum(float(item.normalized_bps or 0) for item in self.components), 8)

    @model_validator(mode="after")
    def validate_market_scope(self) -> TradingCostProfile:
        mismatched = [item.key for item in self.components if item.market != self.market]
        if mismatched:
            raise ValueError(f"成本组件市场与档案不一致: {', '.join(mismatched)}")
        return self


# 这些键是 QuantHub 成本档案的公开契约，不对应或推断任何券商、交易所或
# MT5 终端字段。每个实际数值仍必须由用户提供带来源的成本组件或执行约束。
MARKET_EXECUTION_REQUIREMENTS: dict[str, dict[str, set[str]]] = {
    "a_shares": {
        "components": {"commission", "stamp_tax", "transfer_fee"},
        "constraints": {"limit_up", "limit_down", "suspended", "lot_size"},
    },
    "us_stocks": {
        "components": {"spread", "commission"},
        "constraints": {"corporate_action_adjusted"},
    },
    "crypto": {
        "components": {"fee_tier", "funding_rate", "spread", "slippage"},
        "constraints": set(),
    },
    "mt5": {
        "components": {"spread", "overnight_swap", "contract_multiplier", "slippage"},
        "constraints": {"contract_multiplier"},
    },
}


def execution_profile_gaps(profile: TradingCostProfile) -> dict[str, list[str]]:
    """返回进入市场执行模拟前仍缺少的明确档案项。"""
    requirements = MARKET_EXECUTION_REQUIREMENTS.get(profile.market)
    if requirements is None:
        return {"market": [profile.market]}
    component_keys = {item.key for item in profile.components}
    constraint_keys = {item.key for item in profile.execution_constraints}
    return {
        "components": sorted(requirements["components"] - component_keys),
        "constraints": sorted(requirements["constraints"] - constraint_keys),
    }


class TradingExecutionBar(BaseModel):
    """单个已知历史 bar 的执行状态，不从行情数据源猜测交易状态。"""

    timestamp: str = Field(min_length=1, max_length=80)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)
    suspended: bool = False
    at_limit_up: bool = False
    at_limit_down: bool = False
    corporate_action_adjusted: bool | None = None


class TradingExecutionSimulation(BaseModel):
    """以目标持仓序列计算容量受限成交、权益和交易级成本。"""

    bars: list[TradingExecutionBar] = Field(min_length=1, max_length=20_000)
    desired_quantities: list[float] = Field(min_length=1, max_length=20_000)
    initial_cash: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_lengths(self) -> TradingExecutionSimulation:
        if len(self.bars) != len(self.desired_quantities):
            raise ValueError("bars 与 desired_quantities 长度必须一致")
        return self


def _constraint_value(profile: TradingCostProfile, key: str) -> str | float | int | bool | None:
    item = next((row for row in profile.execution_constraints if row.key == key), None)
    return item.value if item else None


def _positive_number(value: str | float | bool | None, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0:
        raise ValueError(f"执行约束 {key} 必须是大于 0 的数值")
    return float(value)


def simulate_execution(
    profile: TradingCostProfile,
    simulation: TradingExecutionSimulation,
) -> dict:
    """执行来源完整的成本档案，绝不以缺失字段补造市场规则或费率。

    ``desired_quantities`` 是每根 bar 结束时希望持有的单位数。成交量乘以
    ``participation_rate`` 是本根 bar 的最大可成交数量；成交受市场约束阻断时，
    未成交数量会带到下一根 bar 的目标差额中。
    """
    gaps = execution_profile_gaps(profile)
    missing = {name: values for name, values in gaps.items() if values}
    if missing:
        details = "；".join(f"{name}: {', '.join(values)}" for name, values in missing.items())
        raise ValueError(f"执行档案不完整: {details}")
    if profile.participation_rate is None:
        raise ValueError("执行档案必须提供 participation_rate")

    fill_bps = sum(
        float(component.normalized_bps or 0)
        for component in profile.components
        if component.charge_basis == "per_fill"
    )
    carry_bps = sum(
        float(component.normalized_bps or 0)
        for component in profile.components
        if component.charge_basis == "per_bar"
    )
    lot_size = (
        _positive_number(_constraint_value(profile, "lot_size"), "lot_size")
        if profile.market == "a_shares"
        else 1.0
    )
    multiplier = (
        _positive_number(_constraint_value(profile, "contract_multiplier"), "contract_multiplier")
        if profile.market == "mt5"
        else 1.0
    )
    cash = float(simulation.initial_cash)
    quantity = 0.0
    filled_abs = 0.0
    requested_abs = 0.0
    total_cost = 0.0
    fills: list[dict] = []
    equity_curve: list[dict] = []

    for bar, desired in zip(simulation.bars, simulation.desired_quantities, strict=True):
        requested = float(desired) - quantity
        requested_abs += abs(requested)
        reason: str | None = None
        permitted = requested
        if bar.suspended:
            permitted = 0.0
            reason = "suspended"
        elif profile.market == "a_shares" and requested > 0 and bar.at_limit_up:
            permitted = 0.0
            reason = "limit_up"
        elif profile.market == "a_shares" and requested < 0 and bar.at_limit_down:
            permitted = 0.0
            reason = "limit_down"
        elif profile.market == "us_stocks" and bar.corporate_action_adjusted is not True:
            permitted = 0.0
            reason = "corporate_action_unadjusted"

        capacity = bar.volume * float(profile.participation_rate)
        if lot_size > 1:
            capacity = capacity - (capacity % lot_size)
            permitted = (abs(permitted) - (abs(permitted) % lot_size)) * (
                1 if permitted >= 0 else -1
            )
        filled = min(abs(permitted), capacity) * (1 if permitted >= 0 else -1)
        if (permitted and not filled) or abs(filled) < abs(permitted):
            reason = reason or "participation_capacity"
        notional = abs(filled) * bar.close * multiplier
        fill_cost = notional * fill_bps / 10_000
        cash -= filled * bar.close * multiplier + fill_cost
        quantity += filled
        carry_cost = abs(quantity) * bar.close * multiplier * carry_bps / 10_000
        cash -= carry_cost
        total_cost += fill_cost + carry_cost
        filled_abs += abs(filled)
        equity = cash + quantity * bar.close * multiplier
        fills.append(
            {
                "timestamp": bar.timestamp,
                "requested_quantity": requested,
                "filled_quantity": filled,
                "unfilled_quantity": requested - filled,
                "capacity_quantity": capacity,
                "block_reason": reason,
                "fill_cost": round(fill_cost, 8),
                "carry_cost": round(carry_cost, 8),
            }
        )
        equity_curve.append({"timestamp": bar.timestamp, "equity": round(equity, 8)})

    ending_equity = equity_curve[-1]["equity"]
    return {
        "market": profile.market,
        "fill_bps": round(fill_bps, 8),
        "carry_bps": round(carry_bps, 8),
        "participation_rate": profile.participation_rate,
        "fills": fills,
        "equity_curve": equity_curve,
        "metrics": {
            "requested_quantity": round(requested_abs, 8),
            "filled_quantity": round(filled_abs, 8),
            "fill_rate": round(filled_abs / requested_abs, 8) if requested_abs else 1.0,
            "total_cost": round(total_cost, 8),
            "ending_quantity": round(quantity, 8),
            "ending_equity": ending_equity,
            "total_return": round(ending_equity / simulation.initial_cash - 1, 8),
        },
    }
