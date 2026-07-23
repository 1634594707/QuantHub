"""Resolve which trade prices the chart should draw (including continuity wait)."""

from __future__ import annotations

from typing import Any

from pa_agent.ai.decision_continuity import (
    DEFAULT_STRUCTURE_FLIP_COOLDOWN_BARS,
    build_continuity_context,
    is_order_plan,
)


def _parse_price(raw: object) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        v = float(raw)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def has_trade_prices(decision: dict | None) -> bool:
    if not decision:
        return False
    return all(
        _parse_price(decision.get(key)) is not None
        for key in ("entry_price", "take_profit_price", "stop_loss_price")
    )


def enrich_decision_for_chart_overlay(
    decision: dict,
    *,
    stage2_full: dict | None = None,
    frame: Any = None,
    stage1_json: dict | None = None,
    previous_record: Any = None,
    cooldown_bars: int = DEFAULT_STRUCTURE_FLIP_COOLDOWN_BARS,
) -> dict:
    """Return a decision dict for ChartWidget, preserving prior plan levels on continuity wait.

    The decision panel should use the raw *decision*; the chart uses this enriched copy
    so entry/TP/SL lines stay visible while ``order_type=不下单`` and the previous plan
    is still valid.
    """
    out = dict(decision)
    out.pop("chart_overlay_active", None)

    if is_order_plan(decision) and has_trade_prices(decision):
        return out

    if str(decision.get("order_type") or "").strip() != "不下单":
        return out

    terminal = (stage2_full or {}).get("terminal")
    if isinstance(terminal, dict):
        outcome = str(terminal.get("outcome") or "").strip().lower()
        if outcome and outcome not in ("wait", "watch"):
            return out

    if frame is None or not isinstance(stage1_json, dict):
        return out

    ctx = build_continuity_context(
        frame=frame,
        stage1_json=stage1_json,
        previous_record=previous_record,
        cooldown_bars=cooldown_bars,
    )
    if not ctx.get("has_previous_plan") or ctx.get("invalidated"):
        return out

    prev = ctx.get("previous_decision") or {}
    if not has_trade_prices(prev):
        return out

    out["chart_overlay_active"] = True
    for key in (
        "order_direction",
        "entry_price",
        "take_profit_price",
        "take_profit_price_2",
        "stop_loss_price",
    ):
        if prev.get(key) is not None:
            out[key] = prev.get(key)
    return out
