from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTRACT_VERSION = "1.0.0"


def canonical_json(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")

    def json_default(item: Any) -> Any:
        if isinstance(item, (datetime, Decimal)):
            return item.isoformat() if isinstance(item, datetime) else str(item)
        if hasattr(item, "__dict__"):
            return vars(item)
        raise TypeError(f"unsupported canonical JSON value: {type(item).__name__}")

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=json_default,
    )


def content_hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


class EvidenceKind(StrEnum):
    FACT = "fact"
    COMPUTATION = "computation"
    AI_INTERPRETATION = "ai_interpretation"


class DataSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    protocol_version: str = CONTRACT_VERSION
    snapshot_id: str
    dataset: str
    version: str
    created_at: datetime
    available_through: datetime
    record_count: int = Field(ge=0)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_refs: tuple[str, ...]

    @model_validator(mode="after")
    def validate_times(self) -> DataSnapshot:
        if self.created_at.tzinfo is None or self.available_through.tzinfo is None:
            raise ValueError("snapshot timestamps must be timezone-aware")
        return self


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    protocol_version: str = CONTRACT_VERSION
    evidence_id: str
    kind: EvidenceKind
    title: str
    value: Any
    source: str
    observed_at: datetime
    available_at: datetime
    snapshot_id: str | None = None
    calculation: str | None = None
    model: str | None = None

    @model_validator(mode="after")
    def validate_kind(self) -> Evidence:
        if self.kind is EvidenceKind.COMPUTATION and not self.calculation:
            raise ValueError("computed evidence requires calculation provenance")
        if self.kind is EvidenceKind.AI_INTERPRETATION and not self.model:
            raise ValueError("AI evidence requires a model identifier")
        if self.available_at.tzinfo is None or self.observed_at.tzinfo is None:
            raise ValueError("evidence timestamps must be timezone-aware")
        return self


class ResearchRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    protocol_version: str = CONTRACT_VERSION
    run_id: str
    product: str
    engine_version: str
    started_at: datetime
    completed_at: datetime
    snapshot_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    parameters: dict[str, Any]
    result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
