from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

WorkspaceProfile = Literal[
    "stock_investor", "active_trader", "quant_research", "operations", "custom"
]

DEFAULT_WORKSPACES: dict[str, list[str]] = {
    "stock_investor": ["overview", "market", "risk", "settings"],
    "active_trader": ["overview", "market", "trading", "risk"],
    "quant_research": ["overview", "market", "strategy", "trading"],
    "operations": ["overview", "settings", "risk"],
    "custom": ["overview"],
}

PROFILE_LABELS = {
    "stock_investor": "股票投资",
    "active_trader": "主动交易",
    "quant_research": "量化研究",
    "operations": "运营管理",
    "custom": "自定义",
}


class WorkspacePreferenceUpdate(BaseModel):
    profile: WorkspaceProfile = "stock_investor"
    hidden_workspaces: list[str] = Field(default_factory=list, max_length=20)
    hidden_modules: list[str] = Field(default_factory=list, max_length=100)
    pinned_routes: list[str] = Field(default_factory=list, max_length=50)
    default_home: str = Field(default="/", min_length=1, max_length=200)
    default_market: str = Field(default="a_shares", min_length=1, max_length=40)
    recent_routes: list[str] = Field(default_factory=list, max_length=20)
    version: int | None = Field(default=None, ge=0)

    @field_validator("hidden_workspaces", "hidden_modules", "pinned_routes", "recent_routes")
    @classmethod
    def normalize_lists(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class ResearchReportCreate(BaseModel):
    mode: Literal["quick", "investor", "professional", "quant"] = "investor"
    task_id: str | None = None


class ResearchReportRegenerate(BaseModel):
    section_key: str = Field(min_length=1, max_length=100)
