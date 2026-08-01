"""News analysis request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EVENT_TYPES = Literal[
    "earnings_guidance",
    "earnings_revision",
    "share_repurchase",
    "shareholder_change",
    "dividend",
    "regulatory_penalty",
    "major_contract",
    "trading_status",
]


class NewsAnalyzeRequest(BaseModel):
    """新闻分析请求（POST /news/analyze）。"""

    symbol: str = Field(
        ..., min_length=1, description="股票代码（必填，禁止空输入回退到全市场扫描）"
    )
    market: str = Field(default="a_shares")
    timeframe: str = Field(default="1d")
    limit: int = Field(default=20, ge=1, le=100)
    use_api: bool = Field(default=True, description="是否启用 API 结构化增强")
    research_run_id: str | None = Field(default=None, description="复用已有研究运行 ID")

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("股票代码不能为空")
        return normalized

    @field_validator("market", "timeframe")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("字段不能为空")
        return normalized


class NewsResearchEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=120)
    entity_id: str = Field(min_length=1, max_length=120)
    entity_name: str = Field(min_length=1, max_length=200)
    symbol: str = Field(min_length=1, max_length=40)
    market: Literal["a_shares", "us_stocks", "crypto", "mt5"]
    event_type: EVENT_TYPES
    direction: Literal["positive", "negative", "neutral", "uncertain"]
    strength: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    evidence_excerpt: str = Field(min_length=1, max_length=500)
    event_time: datetime
    published_time: datetime
    collected_time: datetime
    revised_time: datetime | None = None
    available_time: datetime
    source: str = Field(min_length=1, max_length=120)
    source_document_id: str = Field(min_length=1, max_length=200)
    source_url: str | None = Field(default=None, max_length=2_000)
    content_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    entity_matches_target: bool
    publication_time_verified: bool
    restricted_data: bool = False
    extractor: dict[str, Any] = Field(default_factory=dict)
    taxonomy_version: str = Field(default="news-event-taxonomy-1.0.0")

    @field_validator("symbol")
    @classmethod
    def normalize_event_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_point_in_time_order(self) -> NewsResearchEvent:
        timestamps = {
            "event_time": self.event_time,
            "published_time": self.published_time,
            "collected_time": self.collected_time,
            "available_time": self.available_time,
        }
        if any(value.tzinfo is None or value.utcoffset() is None for value in timestamps.values()):
            raise ValueError("事件时间字段必须包含时区")
        if self.event_time > self.published_time:
            raise ValueError("event_time 不能晚于 published_time")
        if self.revised_time is not None:
            if self.revised_time.tzinfo is None or self.revised_time.utcoffset() is None:
                raise ValueError("revised_time 必须包含时区")
            if self.revised_time < self.published_time:
                raise ValueError("revised_time 不能早于 published_time")
        required_available_time = max(
            self.published_time,
            self.collected_time,
            self.revised_time or self.published_time,
        )
        if self.available_time < required_available_time:
            raise ValueError("available_time 必须覆盖公开、采集和修订时间")
        return self


class NewsEventValidationRequest(BaseModel):
    events: list[NewsResearchEvent] = Field(min_length=1, max_length=20_000)
    target_entity_id: str = Field(min_length=1, max_length=120)
    minimum_confidence: float = Field(default=0.75, ge=0, le=1)
    duplicate_similarity: float = Field(default=0.8, ge=0.5, le=1)

    @model_validator(mode="after")
    def validate_unique_event_ids(self) -> NewsEventValidationRequest:
        identifiers = [event.event_id for event in self.events]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("event_id 必须全局唯一")
        return self


class NewsEventOutcome(BaseModel):
    event_id: str = Field(min_length=1, max_length=120)
    forward_returns: dict[str, float]
    market_returns: dict[str, float]
    industry_returns: dict[str, float]
    price_state: Literal["trend_up", "trend_down", "oversold", "range"]
    volume_state: Literal["expanding", "normal", "contracting"]
    liquidity_state: Literal["high", "medium", "low"]

    @model_validator(mode="after")
    def validate_horizons(self) -> NewsEventOutcome:
        required = {"1", "3", "5", "10", "20"}
        for field in ("forward_returns", "market_returns", "industry_returns"):
            if set(getattr(self, field)) != required:
                raise ValueError(f"{field} 必须完整提供 1/3/5/10/20 日收益")
        return self


class NewsEventResearchRequest(NewsEventValidationRequest):
    outcomes: list[NewsEventOutcome] = Field(min_length=1, max_length=20_000)

    @model_validator(mode="after")
    def validate_outcome_ids(self) -> NewsEventResearchRequest:
        outcome_ids = [outcome.event_id for outcome in self.outcomes]
        if len(outcome_ids) != len(set(outcome_ids)):
            raise ValueError("outcomes.event_id 必须唯一")
        event_ids = {event.event_id for event in self.events}
        unknown = sorted(set(outcome_ids) - event_ids)
        if unknown:
            raise ValueError(f"收益结果引用了未知事件: {', '.join(unknown)}")
        return self
