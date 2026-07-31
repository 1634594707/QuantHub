from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from core.trading_costs import TradingCostProfile


class FactorResearchRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    market: str = Field(default="a_shares")
    interval: str = Field(default="1d")
    limit: int = Field(default=500, ge=120, le=5_000)
    horizon: int = Field(default=5, ge=1, le=60)
    transaction_cost_bps: float = Field(default=10.0, ge=0, le=200)
    transaction_cost_profile: TradingCostProfile | None = None
    start_date: date | None = None
    end_date: date | None = None
    walk_forward_mode: Literal["expanding", "rolling"] = "expanding"
    walk_forward_folds: int = Field(default=3, ge=1, le=10)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("标的代码不能为空")
        return normalized

    @field_validator("market")
    @classmethod
    def validate_market(cls, value: str) -> str:
        if value not in {"a_shares", "us_stocks", "crypto", "mt5"}:
            raise ValueError("不支持的市场")
        return value

    @model_validator(mode="after")
    def validate_date_range(self) -> FactorResearchRequest:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date 不能晚于 end_date")
        if self.transaction_cost_profile is not None:
            if self.transaction_cost_profile.market != self.market:
                raise ValueError("transaction_cost_profile.market 与研究市场不一致")
            total_bps = self.transaction_cost_profile.total_transaction_cost_bps
            if total_bps > 200:
                raise ValueError("transaction_cost_profile 总成本不能超过 200 bp")
            self.transaction_cost_bps = total_bps
        return self


class FactorAiReviewRequest(FactorResearchRequest):
    """AI review uses a saved server snapshot when run_id is provided."""

    review_focus: str = Field(default="稳健性与失效风险", max_length=120)
    run_id: str | None = Field(default=None, min_length=1, max_length=64)


class FactorUniverseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    market: Literal["a_shares", "us_stocks", "crypto", "mt5"]
    description: str = Field(default="", max_length=300)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip()


class FactorUniverseMemberUpsert(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    effective_from: date
    effective_to: date | None = None
    status: Literal["active", "suspended", "delisted"] = "active"
    industry: str = Field(default="", max_length=80)
    market_cap: float | None = Field(default=None, gt=0)
    beta: float | None = Field(default=None, ge=-10, le=10)
    is_st: bool = False
    listed_at: date | None = None
    delisted_at: date | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_member_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("industry")
    @classmethod
    def normalize_industry(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_member_dates(self) -> FactorUniverseMemberUpsert:
        if self.effective_to and self.effective_from > self.effective_to:
            raise ValueError("effective_from 不能晚于 effective_to")
        if self.listed_at and self.delisted_at and self.listed_at > self.delisted_at:
            raise ValueError("listed_at 不能晚于 delisted_at")
        return self


class CrossSectionResearchRequest(BaseModel):
    run_id: str | None = Field(default=None, min_length=1, max_length=64)
    universe_id: str = Field(min_length=1, max_length=64)
    factor_key: str = Field(default="trend_strength", min_length=1, max_length=60)
    interval: Literal["1d"] = "1d"
    limit: int = Field(default=500, ge=120, le=5_000)
    horizon: int = Field(default=5, ge=1, le=60)
    start_date: date | None = None
    end_date: date | None = None
    quantiles: int = Field(default=5, ge=2, le=10)
    min_assets: int = Field(default=5, ge=3, le=500)
    transaction_cost_bps: float = Field(default=10.0, ge=0, le=200)
    transaction_cost_profile: TradingCostProfile | None = None
    participation_rate: float = Field(default=0.1, gt=0, le=0.5)
    neutralize_industry: bool = True
    neutralize_market_cap: bool = True
    neutralize_beta: bool = True
    retry_attempts: int = Field(default=2, ge=1, le=5)

    @model_validator(mode="after")
    def validate_cross_section_dates(self) -> CrossSectionResearchRequest:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date 不能晚于 end_date")
        if self.transaction_cost_profile is not None:
            if self.transaction_cost_profile.market not in {
                "a_shares",
                "us_stocks",
                "crypto",
                "mt5",
            }:
                raise ValueError("transaction_cost_profile.market 不受支持")
            total_bps = self.transaction_cost_profile.total_transaction_cost_bps
            if total_bps > 200:
                raise ValueError("transaction_cost_profile 总成本不能超过 200 bp")
            self.transaction_cost_bps = total_bps
            if self.transaction_cost_profile.participation_rate is not None:
                self.participation_rate = self.transaction_cost_profile.participation_rate
        return self
