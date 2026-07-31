from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

AlertRuleType = Literal[
    "price_above",
    "price_below",
    "change_pct_above",
    "change_pct_below",
    "volatility_above",
    "signal_created",
    "evaluation_changed",
    "risk_invalidated",
    "factor_status_changed",
    "factor_ic_decay",
    "factor_drawdown_breach",
    "factor_data_stale",
]

THRESHOLD_RULE_TYPES = {
    "price_above",
    "price_below",
    "change_pct_above",
    "change_pct_below",
    "volatility_above",
    "risk_invalidated",
    "factor_ic_decay",
    "factor_drawdown_breach",
    "factor_data_stale",
}


class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    rule_type: AlertRuleType
    symbol: str = Field(min_length=1, max_length=100)
    market: str = Field(default="a_shares", min_length=1, max_length=50)
    threshold: float | None = None
    enabled: bool = True
    frequency_minutes: int = Field(default=15, ge=1, le=10_080)
    quiet_start: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    quiet_end: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    expires_at: float | None = None
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name", "market")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_rule(self):
        if self.rule_type in THRESHOLD_RULE_TYPES and self.threshold is None:
            raise ValueError(f"{self.rule_type} 必须设置 threshold")
        if (self.quiet_start is None) != (self.quiet_end is None):
            raise ValueError("quiet_start 和 quiet_end 必须同时设置")
        if self.rule_type == "risk_invalidated" and self.context.get("condition") not in {
            "above",
            "below",
        }:
            raise ValueError("risk_invalidated 的 context.condition 必须是 above 或 below")
        factor_rule_types = {
            "factor_status_changed",
            "factor_ic_decay",
            "factor_drawdown_breach",
            "factor_data_stale",
        }
        if self.rule_type in factor_rule_types:
            factor_key = self.context.get("factor_key")
            if not isinstance(factor_key, str) or not factor_key.strip():
                raise ValueError(f"{self.rule_type} 必须设置 context.factor_key")
        if self.rule_type == "factor_ic_decay":
            baseline = self.context.get("baseline_test_ic")
            if not isinstance(baseline, (int, float)):
                raise ValueError("factor_ic_decay 必须设置 context.baseline_test_ic")
        if self.rule_type in {"factor_ic_decay", "factor_drawdown_breach", "factor_data_stale"}:
            if self.threshold is None or self.threshold <= 0:
                raise ValueError(f"{self.rule_type} 的 threshold 必须大于 0")
        return self


class AlertRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = None
    threshold: float | None = None
    frequency_minutes: int | None = Field(default=None, ge=1, le=10_080)
    quiet_start: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    quiet_end: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    expires_at: float | None = None


class AlertEventAcknowledge(BaseModel):
    acknowledged: bool = True
