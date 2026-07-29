from __future__ import annotations

from apps.api.domains.instrument import service as instrument_service
from core.signals import Signal, get_bus

from . import repository
from .domain import ReviewStatus, SignalStatus, can_transition
from .schemas import PublishSignalRequest


class SignalNotFoundError(LookupError):
    pass


class InvalidSignalTransitionError(ValueError):
    pass


def publish(req: PublishSignalRequest) -> dict:
    instrument = instrument_service.resolve_strict(req.symbol, req.market)
    signal = Signal(
        symbol=instrument.code,
        market=instrument.market,
        timeframe=req.timeframe,
        direction=req.direction,
        score=req.score,
        confidence=req.confidence,
        source=req.source,
        tags=req.tags,
        meta=req.meta,
    )
    persisted = repository.add_signal(
        {
            **signal.to_dict(),
            "instrument_id": instrument.instrument_id,
        }
    )
    if not persisted.get("deduplicated", False):
        get_bus().publish(signal)
    repository.prune_signals(keep=2000)
    return persisted


def review(signal_id: str, *, target: ReviewStatus, note: str | None) -> dict:
    current = repository.get_signal(signal_id)
    if current is None:
        raise SignalNotFoundError(signal_id)
    current_status: SignalStatus = current["status"]
    if not can_transition(current_status, target):
        raise InvalidSignalTransitionError(f"不允许从 {current_status} 转为 {target}")
    updated = repository.update_status(signal_id, status=target, note=note)
    if updated is None:
        raise SignalNotFoundError(signal_id)
    return updated
