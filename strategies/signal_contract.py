"""Structured signal extraction for narrative analysis strategies."""

from __future__ import annotations

import json
from typing import Any

SIGNAL_MARKER = "QUANTHUB_SIGNAL_JSON:"


def parse_report_signal(report: str) -> dict[str, Any] | None:
    """Parse a validated signal footer without guessing values from prose."""
    for line in reversed(report.splitlines()):
        stripped = line.strip()
        if not stripped.startswith(SIGNAL_MARKER):
            continue
        try:
            payload = json.loads(stripped[len(SIGNAL_MARKER) :].strip())
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        direction = payload.get("direction")
        score = payload.get("score")
        confidence = payload.get("confidence")
        if direction not in {"buy", "sell", "hold"}:
            return None
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            return None
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            return None
        if not 0 <= float(score) <= 1 or not 0 <= float(confidence) <= 1:
            return None
        return {
            "direction": direction,
            "score": float(score),
            "confidence": float(confidence),
        }
    return None
