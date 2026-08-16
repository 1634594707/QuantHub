from __future__ import annotations

import math
import re
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTRACT_VERSION = "1.0.0"
SNAPSHOT_CONTRACT_VERSION = "1.1.0"
REALTIME_CONTRACT_VERSION = "2.0.0"


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


class MarketEventKind(StrEnum):
    HISTORICAL_SNAPSHOT = "historical_snapshot"
    CLOSED_BAR_LIVE = "closed_bar_live"
    FORMING_BAR = "forming_bar"
    TICKER = "ticker"
    BEST_BID_ASK = "best_bid_ask"
    TRADE = "trade"


class MarketEventQuality(StrEnum):
    FRESH = "fresh"
    DELAYED = "delayed"
    STALE = "stale"
    GAP_RECOVERED = "gap_recovered"
    INVALID = "invalid"


class MarketEvent(BaseModel):
    """Unified immutable freshness contract for research, valuation, and execution."""

    model_config = ConfigDict(frozen=True)

    protocol_version: str = REALTIME_CONTRACT_VERSION
    event_id: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    kind: MarketEventKind
    event_time: datetime
    fetched_at: datetime
    received_at: datetime
    source: str = Field(min_length=1)
    quality_status: MarketEventQuality = MarketEventQuality.FRESH
    bar_open_time: datetime | None = None
    bar_close_time: datetime | None = None
    is_closed: bool | None = None
    age_ms: int | None = Field(default=None, ge=0)
    price: float | None = None
    bid: float | None = None
    ask: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = Field(default=None, ge=0)
    recovery: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_event(self) -> MarketEvent:
        timestamps = [self.event_time, self.fetched_at, self.received_at]
        timestamps.extend(
            value for value in (self.bar_open_time, self.bar_close_time) if value is not None
        )
        if any(value.tzinfo is None for value in timestamps):
            raise ValueError("market event timestamps must be timezone-aware")
        if self.received_at < self.event_time:
            raise ValueError("received_at cannot precede event_time")
        if self.kind in {
            MarketEventKind.HISTORICAL_SNAPSHOT,
            MarketEventKind.CLOSED_BAR_LIVE,
            MarketEventKind.FORMING_BAR,
        }:
            if self.bar_open_time is None or self.bar_close_time is None:
                raise ValueError("bar events require bar_open_time and bar_close_time")
            if self.bar_close_time <= self.bar_open_time:
                raise ValueError("bar_close_time must follow bar_open_time")
            if self.is_closed is None:
                raise ValueError("bar events require is_closed")
            if self.kind == MarketEventKind.FORMING_BAR and self.is_closed:
                raise ValueError("forming_bar cannot be closed")
            if self.kind != MarketEventKind.FORMING_BAR and not self.is_closed:
                raise ValueError("closed bar events must be closed")
        elif self.is_closed is not None:
            raise ValueError("non-bar events must not set is_closed")
        numeric = [
            value
            for value in (
                self.price,
                self.bid,
                self.ask,
                self.open,
                self.high,
                self.low,
                self.close,
                self.volume,
            )
            if value is not None
        ]
        if any(not math.isfinite(value) for value in numeric):
            raise ValueError("market event prices and volume must be finite")
        if self.bid is not None and self.ask is not None and self.ask < self.bid:
            raise ValueError("ask cannot be below bid")
        computed_age = max(0, int((self.received_at - self.event_time).total_seconds() * 1000))
        object.__setattr__(self, "age_ms", computed_age)
        return self

    def usable_for_research_signal(self) -> bool:
        return bool(
            self.kind in {MarketEventKind.HISTORICAL_SNAPSHOT, MarketEventKind.CLOSED_BAR_LIVE}
            and self.is_closed
            and self.quality_status not in {MarketEventQuality.STALE, MarketEventQuality.INVALID}
        )

    def usable_for_valuation(self) -> bool:
        return bool(
            self.kind
            in {MarketEventKind.TICKER, MarketEventKind.BEST_BID_ASK, MarketEventKind.TRADE}
            and self.quality_status not in {MarketEventQuality.STALE, MarketEventQuality.INVALID}
        )

    def freshness_at(
        self,
        now: datetime,
        *,
        delayed_after: timedelta,
        stale_after: timedelta,
    ) -> dict[str, Any]:
        if now.tzinfo is None:
            raise ValueError("freshness evaluation time must be timezone-aware")
        age_ms = max(0, int((now - self.event_time).total_seconds() * 1000))
        quality = classify_market_event_quality(
            event_time=self.event_time,
            received_at=now,
            delayed_after=delayed_after,
            stale_after=stale_after,
        )
        if self.quality_status in {MarketEventQuality.INVALID, MarketEventQuality.GAP_RECOVERED}:
            quality = self.quality_status
        usable = quality not in {MarketEventQuality.STALE, MarketEventQuality.INVALID}
        return {
            "age_ms": age_ms,
            "quality_status": quality.value,
            "usable_for_research_signal": usable and self.usable_for_research_signal(),
            "usable_for_valuation": usable and self.usable_for_valuation(),
            "action": "allow" if usable else "block_new_risk",
        }


def classify_market_event_quality(
    *,
    event_time: datetime,
    received_at: datetime,
    delayed_after: timedelta,
    stale_after: timedelta,
) -> MarketEventQuality:
    age = received_at - event_time
    if age > stale_after:
        return MarketEventQuality.STALE
    if age > delayed_after:
        return MarketEventQuality.DELAYED
    return MarketEventQuality.FRESH


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
