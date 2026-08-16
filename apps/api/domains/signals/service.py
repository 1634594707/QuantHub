from __future__ import annotations

import time

from apps.api import store
from apps.api.domains.instrument import service as instrument_service
from core.signals import Signal, get_bus

from . import repository
from .domain import ReviewStatus, SignalStatus, can_transition
from .schemas import PublishSignalRequest


class SignalNotFoundError(LookupError):
    pass


class InvalidSignalTransitionError(ValueError):
    pass


_RADAR_PAGE_SIZE = 2000
_RADAR_STATUSES = frozenset({"new", "accepted", "expired"})


def radar_snapshot() -> dict:
    """Return one current signal, or the newest expired fallback, per instrument.

    The list endpoint is intentionally paginated. Radar selection is a server-side
    operation so a growing ledger cannot make the browser select an older record.
    """
    cursor: str | None = None
    current: dict[tuple[str, str], dict] = {}
    expired: dict[tuple[str, str], dict] = {}
    scanned = 0
    now = time.time()

    while True:
        page = repository.list_signals_page(
            limit=_RADAR_PAGE_SIZE,
            source=None,
            market=None,
            status=None,
            cursor=cursor,
        )
        items = page["items"]
        scanned += len(items)
        for signal in items:
            status = str(signal.get("status") or "new")
            if status not in _RADAR_STATUSES:
                continue
            key = (
                str(signal.get("market") or "").strip().lower(),
                str(signal.get("symbol") or "").strip().upper(),
            )
            if not all(key):
                continue
            expires_at = signal.get("expires_at")
            is_expired = status == "expired" or (
                isinstance(expires_at, (int, float)) and expires_at <= now
            )
            target = expired if is_expired else current
            if key not in target:
                target[key] = {
                    **signal,
                    "radar_state": "expired" if is_expired else "current",
                }
        cursor = page.get("next_cursor")
        if not cursor:
            break

    selected = list(current.values())
    selected.extend(signal for key, signal in expired.items() if key not in current)
    selected.sort(key=lambda signal: str(signal.get("ts") or ""), reverse=True)
    return {
        "count": len(selected),
        "current_count": len(current),
        "expired_count": sum(1 for signal in selected if signal["radar_state"] == "expired"),
        "scanned": scanned,
        "generated_at": now,
        "signals": selected,
    }


def publish(req: PublishSignalRequest) -> dict:
    research_run_id = req.meta.get("research_run_id")
    if research_run_id and req.direction in {"buy", "sell"}:
        run = store.get_research_run(str(research_run_id))
        decision = (run.get("summary") or {}).get("research_decision") if run else None
        expected = "long" if req.direction == "buy" else "short"
        if not decision or decision.get("execution_eligible") is not True:
            raise ValueError("RESEARCH_DECISION_BLOCKED: 研究结论不具备执行资格")
        if decision.get("direction") != expected:
            raise ValueError("RESEARCH_DIRECTION_MISMATCH: 信号方向与统一研究决策不一致")
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
