from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTRACT_VERSION = "1.0.0"
SNAPSHOT_CONTRACT_VERSION = "1.1.0"


class Market(StrEnum):
    A_SHARES = "a_shares"
    US_STOCKS = "us_stocks"
    OKX = "okx"
    MT5 = "mt5"


def canonical_instrument_id(market: Market | str, symbol: str) -> str:
    market_value = Market(market).value
    normalized = re.sub(r"[^A-Z0-9._-]", "", symbol.strip().upper().replace("/", "-"))
    if not normalized:
        raise ValueError("symbol must contain an alphanumeric identifier")
    return f"{market_value}:{normalized}"


class Provenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str = Field(min_length=1)
    source_record_id: str | None = None
    fetched_at: datetime
    available_at: datetime
    revision: str = "1"
    license: str | None = None

    @model_validator(mode="after")
    def validate_times(self) -> Provenance:
        if self.fetched_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("provenance timestamps must be timezone-aware")
        return self


class Instrument(BaseModel):
    model_config = ConfigDict(frozen=True)

    protocol_version: str = CONTRACT_VERSION
    instrument_id: str
    market: Market
    symbol: str
    name: str
    currency: str = Field(min_length=3, max_length=3)
    timezone: str
    trading_calendar: str
    active_from: datetime | None = None
    active_to: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_id(self) -> Instrument:
        expected = canonical_instrument_id(self.market, self.symbol)
        if self.instrument_id != expected:
            raise ValueError(f"instrument_id must be {expected}")
        return self


class Candle(BaseModel):
    model_config = ConfigDict(frozen=True)

    protocol_version: str = CONTRACT_VERSION
    instrument_id: str
    interval: str
    event_time: datetime
    available_at: datetime
    fetched_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = Field(ge=0)
    provenance: Provenance

    @model_validator(mode="after")
    def validate_candle(self) -> Candle:
        for value in (self.event_time, self.available_at, self.fetched_at):
            if value.tzinfo is None:
                raise ValueError("candle timestamps must be timezone-aware")
        if self.available_at < self.event_time:
            raise ValueError("available_at cannot precede event_time")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high is below another OHLC value")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low is above another OHLC value")
        for value in (self.open, self.high, self.low, self.close, self.volume):
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("candle OHLCV values must be finite numbers")
        return self

    @property
    def content_hash(self) -> str:
        payload = self.model_dump_json(exclude={"fetched_at"})
        return sha256(payload.encode("utf-8")).hexdigest()


def normalize_candles(rows: list[Candle]) -> tuple[Candle, ...]:
    ordered = sorted(rows, key=lambda row: (row.event_time, row.available_at))
    unique: dict[datetime, Candle] = {}
    for row in ordered:
        unique[row.event_time.astimezone(UTC)] = row
    return tuple(unique[key] for key in sorted(unique))


class Adjustment(StrEnum):
    NONE = "none"
    PRE = "pre"
    POST = "post"


class BarStatus(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALTED = "halted"
    MISSING = "missing"


class SnapshotQuality(StrEnum):
    VERIFIED = "verified"
    DEGRADED = "degraded"
    INVALID = "invalid"
    EMPTY = "empty"
    EXPIRED = "expired"


class CandleSnapshot(BaseModel):
    """Immutable, replayable Stock行情快照协议。"""

    model_config = ConfigDict(frozen=True)

    protocol_version: str = SNAPSHOT_CONTRACT_VERSION
    snapshot_id: str = Field(min_length=1)
    instrument_id: str
    interval: str = Field(min_length=1)
    adjustment: Adjustment = Adjustment.NONE
    candles: tuple[Candle, ...] = ()
    bar_status: BarStatus = BarStatus.CLOSED
    source: str = Field(min_length=1)
    fetched_at: datetime
    available_at: datetime
    quality: SnapshotQuality
    quality_reason: str | None = None
    content_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_snapshot(self) -> CandleSnapshot:
        if self.fetched_at.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("snapshot timestamps must be timezone-aware")
        if self.quality == SnapshotQuality.VERIFIED and not self.candles:
            raise ValueError("verified snapshots require candles")
        if self.quality == SnapshotQuality.INVALID and not self.quality_reason:
            raise ValueError("invalid snapshots require quality_reason")
        if self.candles:
            # Explicit checks keep malformed provider rows from entering reports.
            for candle in self.candles:
                if candle.instrument_id != self.instrument_id or candle.interval != self.interval:
                    raise ValueError("snapshot candles must match instrument and interval")
            if tuple(sorted(self.candles, key=lambda c: c.event_time)) != self.candles:
                raise ValueError("snapshot candles must be ordered by event_time")
        computed = sha256(canonical_snapshot_payload(self).encode("utf-8")).hexdigest()
        if self.content_hash is not None and self.content_hash != computed:
            raise ValueError("snapshot content_hash does not match payload")
        object.__setattr__(self, "content_hash", computed)
        return self


def canonical_snapshot_payload(snapshot: CandleSnapshot) -> str:
    """Return stable JSON excluding the derived content hash."""
    payload = snapshot.model_dump(mode="json", exclude={"content_hash"})
    # Fetch timestamps describe retrieval, not market content; excluding them
    # makes repeated reads of the same closed bars deduplicate correctly.
    payload.pop("fetched_at", None)
    for candle in payload.get("candles", []):
        candle.pop("fetched_at", None)
        if isinstance(candle.get("provenance"), dict):
            candle["provenance"].pop("fetched_at", None)
    return __import__("json").dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
