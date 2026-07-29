from __future__ import annotations

from typing import Literal

SignalStatus = Literal["new", "accepted", "rejected", "expired", "converted"]
ReviewStatus = Literal["accepted", "rejected"]

TRANSITIONS: dict[SignalStatus, frozenset[SignalStatus]] = {
    "new": frozenset({"accepted", "rejected"}),
    "accepted": frozenset({"rejected", "converted"}),
    "rejected": frozenset(),
    "expired": frozenset(),
    "converted": frozenset(),
}


def can_transition(current: SignalStatus, target: SignalStatus) -> bool:
    return target in TRANSITIONS[current]
