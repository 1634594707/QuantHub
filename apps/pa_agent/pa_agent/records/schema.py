"""Pydantic v2 data models for PA Agent records persistence.

Defines the canonical schema for analysis records, followup turns,
alarm payloads, validation errors, and experience entries.
"""

from pydantic import BaseModel, ConfigDict


class RecordMeta(BaseModel):
    """Metadata captured at the moment of analysis submission."""

    model_config = ConfigDict(extra="forbid")

    timestamp_local_iso: str  # Local time ISO string, used for filename
    timestamp_local_ms: int  # Local time in milliseconds
    symbol: str
    timeframe: str
    bar_count: int
    ai_provider: dict  # Sanitized provider config snapshot (no plaintext API key)
    decision_stance: str = (
        "conservative"  # conservative | balanced | aggressive | extreme_aggressive
    )


class AnalysisRecord(BaseModel):
    """Full record of a two-stage AI analysis run."""

    model_config = ConfigDict(extra="forbid")

    meta: RecordMeta
    kline_data: list[dict]  # Same data as sent to AI
    htf_text: str
    stage1_messages: list[dict]
    stage1_response: dict | None  # Raw response (includes reasoning_content)
    stage1_diagnosis: dict | None
    stage2_messages: list[dict]
    stage2_response: dict | None
    stage2_decision: dict | None
    strategy_files_used: list[str]
    experience_loaded: list[dict]
    exception: dict | None  # If error occurred: category + debug info
    usage_total: dict  # Cumulative usage for audit


class FollowupTurn(BaseModel):
    """A single turn in the post-analysis free-chat session."""

    model_config = ConfigDict(extra="forbid")

    turn: int
    ts_ms: int
    user: str
    ai_content: str
    ai_reasoning: str | None
    usage: dict
    cancelled: bool = False


class AlarmPayload(BaseModel):
    """Payload emitted when a JSON validation alarm is triggered (R8.6)."""

    model_config = ConfigDict(extra="forbid")

    category: str  # 'a'..'e'
    stage: str  # '阶段一-诊断' or '阶段二-决策'
    timestamp_local_iso: str
    raw_text: str
    parse_position: str | None
    missing_fields: list[str]
    invalid_fields: list[str]
    consecutive_count: int
    history_excerpt: list[dict]


class ValidationError(BaseModel):
    """Structured validation error produced by JsonValidator.

    Note: this is a Pydantic model, not the built-in exception class.
    """

    model_config = ConfigDict(extra="forbid")

    category: str  # 'a', 'b', 'c', or 'd'
    missing_fields: list[str] = []
    invalid_fields: list[str] = []
    raw_text: str
    parse_position: str | None = None
    allowed_values: dict = {}


class ExperienceEntry(BaseModel):
    """A single entry loaded from the experience library."""

    model_config = ConfigDict(extra="forbid")

    filename: str
    case_type: str  # 'success' or 'failure'
    cycle_position: str
    timestamp_ms: int
    content: dict  # Parsed JSON content of the experience file
