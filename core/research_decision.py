"""Deterministic research decision contract shared by reports and execution gates."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

NormalizedDirection = Literal["long", "short", "neutral", "insufficient"]
DecisionDirection = Literal["long", "short", "neutral", "conflicted", "insufficient"]

DECISION_VERSION = "research-decision-v1"


class ModuleOpinion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module: str = Field(min_length=1, max_length=80)
    direction: NormalizedDirection
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_at: datetime | None = None
    status: Literal["available", "stale", "failed", "missing"] = "available"
    reason: str = Field(default="", max_length=1000)
    evidence_id: str | None = Field(default=None, max_length=160)


class DecisionConflict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["opposite_direction", "direction_neutral_mismatch", "stale", "insufficient"]
    modules: list[str]
    reason: str
    blocking: bool = True


class ResearchDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    direction: DecisionDirection
    execution_eligible: bool
    module_opinions: list[ModuleOpinion]
    conflicts: list[DecisionConflict] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    reevaluate_triggers: list[str] = Field(default_factory=list)
    decision_version: str = DECISION_VERSION
    decided_at: datetime
    input_fingerprint: str


_DIRECTION_ALIASES: dict[str, NormalizedDirection] = {
    "buy": "long",
    "long": "long",
    "bullish": "long",
    "做多": "long",
    "偏强": "long",
    "上涨": "long",
    "sell": "short",
    "short": "short",
    "bearish": "short",
    "做空": "short",
    "偏弱": "short",
    "下降": "short",
    "hold": "neutral",
    "neutral": "neutral",
    "观望": "neutral",
    "中性": "neutral",
    "震荡": "neutral",
    "insufficient": "insufficient",
    "unknown": "insufficient",
    "数据不足": "insufficient",
}


def normalize_direction(value: Any, *, available: bool = True) -> NormalizedDirection:
    if not available or value is None:
        return "insufficient"
    return _DIRECTION_ALIASES.get(str(value).strip().lower(), "insufficient")


def _fingerprint(opinions: list[ModuleOpinion], version: str) -> str:
    payload = {
        "decision_version": version,
        "module_opinions": [item.model_dump(mode="json") for item in opinions],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def decide_research(
    opinions: list[ModuleOpinion],
    *,
    invalidation_conditions: list[str] | None = None,
    reevaluate_triggers: list[str] | None = None,
    decided_at: datetime | None = None,
    decision_version: str = DECISION_VERSION,
) -> ResearchDecision:
    """Apply the conflict matrix without allowing prose to override state."""
    ordered = sorted(opinions, key=lambda item: item.module)
    usable = [item for item in ordered if item.status == "available"]
    directional = {item.direction for item in usable if item.direction in {"long", "short"}}
    has_neutral = any(item.direction == "neutral" for item in usable)
    unavailable = [
        item for item in ordered if item.status != "available" or item.direction == "insufficient"
    ]
    conflicts: list[DecisionConflict] = []

    if directional == {"long", "short"}:
        conflicts.append(
            DecisionConflict(
                kind="opposite_direction",
                modules=[item.module for item in usable if item.direction in directional],
                reason="有效模块同时包含做多与做空意见",
            )
        )
    elif directional and has_neutral:
        conflicts.append(
            DecisionConflict(
                kind="direction_neutral_mismatch",
                modules=[item.module for item in usable],
                reason="方向性意见与中性意见未形成一致结论",
            )
        )
    stale = [item.module for item in ordered if item.status == "stale"]
    if stale:
        conflicts.append(DecisionConflict(kind="stale", modules=stale, reason="关键模块证据已过期"))
    if unavailable:
        conflicts.append(
            DecisionConflict(
                kind="insufficient",
                modules=[item.module for item in unavailable],
                reason="存在失败、缺失或无法归一化的模块证据",
            )
        )

    if any(item.kind in {"opposite_direction", "direction_neutral_mismatch"} for item in conflicts):
        direction: DecisionDirection = "conflicted"
    elif unavailable or len(usable) < 2:
        direction = "insufficient"
    elif directional == {"long"}:
        direction = "long"
    elif directional == {"short"}:
        direction = "short"
    else:
        direction = "neutral"

    execution_eligible = direction in {"long", "short"} and not any(
        item.blocking for item in conflicts
    )
    return ResearchDecision(
        direction=direction,
        execution_eligible=execution_eligible,
        module_opinions=ordered,
        conflicts=conflicts,
        invalidation_conditions=list(dict.fromkeys(invalidation_conditions or [])),
        reevaluate_triggers=list(dict.fromkeys(reevaluate_triggers or [])),
        decision_version=decision_version,
        decided_at=decided_at or datetime.now(UTC),
        input_fingerprint=_fingerprint(ordered, decision_version),
    )


def decision_from_mapping(value: dict[str, Any] | None) -> ResearchDecision | None:
    if not value:
        return None
    try:
        return ResearchDecision.model_validate(value)
    except (TypeError, ValueError):
        return None
