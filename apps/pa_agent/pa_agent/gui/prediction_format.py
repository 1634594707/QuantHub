"""Shared display helpers for next-bar and next-cycle prediction panels.

Extracted from decision_panel.py so that FutureTrendPanel can import them
without creating a circular dependency.
"""

from __future__ import annotations

# ── Colour constants ──────────────────────────────────────────────────────────

_PREDICTION_DOMINANT_COLOR: dict[str, str] = {
    "bullish": "#3fb950",
    "bearish": "#f85149",
    "neutral": "#e6b800",
}

_PREDICTION_UNPREDICTABLE_COLOR: str = "#8b949e"
_PREDICTION_UNPREDICTABLE_LABEL: str = "不可预测"


# ── Formatting helpers ────────────────────────────────────────────────────────


def _format_prediction_probs_line(probs: dict) -> str:
    """Format bullish/bearish/neutral probabilities as a single display line."""
    bull = probs.get("bullish", "?")
    bear = probs.get("bearish", "?")
    neut = probs.get("neutral", "?")
    return f"阳线的概率为{bull}%  ·  阴线的概率为{bear}%  ·  中性的概率为{neut}%"


def _dominant_prediction_direction(probs: dict) -> str | None:
    """Return bullish/bearish/neutral for styling by highest probability."""
    parsed: list[tuple[str, float]] = []
    for key in ("bullish", "bearish", "neutral"):
        raw = probs.get(key)
        if raw is None or raw == "":
            continue
        try:
            parsed.append((key, float(raw)))
        except (TypeError, ValueError):
            continue
    if not parsed:
        return None
    return max(parsed, key=lambda item: item[1])[0]
