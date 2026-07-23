"""Shared view-model layer for PA Agent analysis results.

This module extracts the data-binding logic that the PyQt6 GUI panels
(``gui/decision_panel.py``, ``gui/future_trend_panel.py``,
``gui/decision_tree_panel.py``) perform, and exposes it as **pure-Python**
functions returning plain ``dict`` / ``list`` structures.

Why a shared layer
-------------------
The desktop GUI and the Streamlit web workbench (``apps/dashboard``) need the
same structured view of an ``AnalysisRecord``. Instead of duplicating the
field-extraction logic (which is the real "rendering" work), both front-ends
call these functions. This module must **never** import PyQt — it only depends
on the pure-Python helpers in ``pa_agent.util`` / ``pa_agent.ai``.

Each ``build_*_view`` accepts the raw record dict (``AnalysisRecord.model_dump()``)
so it works identically on desktop and web.
"""

from __future__ import annotations

from typing import Any

from pa_agent.ai.cycle_enums import (
    format_cycle_position,
    format_cycle_with_direction,
    format_trend_label,
)
from pa_agent.ai.decision_tree import (
    format_bar_basis_suffix,
    format_trace_answer,
    load_decision_tree,
    merge_traces,
    normalize_bar_range,
    plain_trace_question,
)
from pa_agent.util.trade_metrics import (
    compute_risk_reward,
    format_estimated_win_rate,
    max_risk_reward_ratio,
    min_risk_reward_ratio,
    passes_trader_equation,
)

# ── Local pure helpers (mirrors gui/*_panel private helpers) ──────────────────
# Copied here (not imported from the GUI) so this module stays PyQt-free.

_NO_ORDER = "不下单"

_MARKET_PHASE_ZH: dict[str, str] = {"stable": "稳定", "transitioning": "过渡"}

_PREDICTION_DOMINANT_COLOR: dict[str, str] = {
    "bullish": "#3fb950",
    "bearish": "#f85149",
    "neutral": "#e6b800",
}

_DIRECTION_ZH: dict[str, str] = {
    "bullish": "看涨",
    "bearish": "看跌",
    "neutral": "中性",
    "up": "上涨",
    "down": "下跌",
}

_PREDICTION_UNPREDICTABLE_LABEL = "不可预测"


def _parse_score_100(value: object) -> int | None:
    """Parse a 0-100 confidence score from heterogeneous input."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return max(0, min(100, int(value)))
    try:
        return max(0, min(100, int(float(str(value).strip()))))
    except (ValueError, TypeError):
        return None


def _score_color(score: int) -> str:
    if score >= 70:
        return "#3fb950"
    if score >= 50:
        return "#e6b800"
    return "#f85149"


def _trend_color(label: str) -> str:
    if label in ("上涨", "震荡偏多"):
        return "#3fb950"
    if label in ("下跌", "震荡偏空"):
        return "#f85149"
    if label in ("震荡", "趋势运行中"):
        return "#e6b800"
    return "#8b949e"


def _format_market_phase(raw: str) -> str:
    key = (raw or "").strip().lower()
    return _MARKET_PHASE_ZH.get(key, raw or "—")


def _format_prediction_probs_line(probs: dict) -> str:
    bull = probs.get("bullish", "?")
    bear = probs.get("bearish", "?")
    neut = probs.get("neutral", "?")
    return f"阳线的概率为{bull}%  ·  阴线的概率为{bear}%  ·  中性的概率为{neut}%"


def _dominant_prediction_direction(probs: dict) -> str | None:
    """Return bullish/bearish/neutral for the highest probability key."""
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


# ── Decision view ─────────────────────────────────────────────────────────────


def build_decision_view(
    stage2_decision: dict | None,
    *,
    stage1_diagnosis: dict | None = None,
    decision_stance: str | None = None,
    confidence_threshold: int | None = None,
) -> dict[str, Any]:
    """Build the structured view for the 交易决策 panel.

    Returns a flat dict consumable by any front-end:
      trend, cycle, phase, diagnosis_confidence{score,reasoning},
      order_type, direction, entry, tp1, tp2, sl,
      risk_reward{ratio_text,risk,reward,metrics_ok},
      estimated_win_rate, trade_confidence{score,reasoning}, reasoning
    """
    decision = stage2_decision or {}
    diagnosis_summary: dict[str, Any] = dict(decision.get("diagnosis_summary") or {})

    # Merge stage1 fallback (stage1 wins only when summary lacks the key).
    src: dict[str, Any] = {}
    if stage1_diagnosis:
        src.update(stage1_diagnosis)
    src.update(diagnosis_summary)

    direction = str(src.get("direction", "") or "")
    cycle_position = str(src.get("cycle_position", "") or "")
    alt_cycle = src.get("alternative_cycle_position")
    market_phase = str(src.get("market_phase", "") or "")

    trend = format_trend_label(direction, cycle_position)
    cycle_zh = format_cycle_with_direction(cycle_position, direction)
    if alt_cycle:
        cycle_zh += f"（备选 {format_cycle_position(str(alt_cycle))}）"
    phase_zh = ""
    phase_risk = ""
    if market_phase:
        phase_zh = _format_market_phase(market_phase)
        risk = src.get("transition_risk")
        if market_phase == "transitioning" and risk:
            phase_risk = f" · 风险 {risk}"

    diag_conf_score = _parse_score_100(decision.get("diagnosis_confidence"))
    diag_conf_reasoning = str(decision.get("diagnosis_confidence_reasoning") or "").strip()

    # Confidence gate (mirrors gui decision_panel logic).
    order_type = decision.get("order_type", _NO_ORDER)
    reasoning = decision.get("reasoning", decision.get("brief_reasoning", ""))
    if confidence_threshold is not None and confidence_threshold > 0 and order_type != _NO_ORDER:
        raw_conf = decision.get("trade_confidence")
        try:
            conf_val = int(float(str(raw_conf).strip())) if raw_conf not in (None, "") else -1
        except (ValueError, TypeError):
            conf_val = -1
        if conf_val < confidence_threshold:
            order_type = _NO_ORDER
            prefix = "有入场机会，但置信度未通过"
            reasoning = f"{prefix}\n\n{reasoning}" if reasoning else prefix

    view: dict[str, Any] = {
        "trend": trend,
        "trend_color": _trend_color(trend),
        "cycle": cycle_zh,
        "phase": f"{phase_zh}{phase_risk}" if phase_zh else "—",
        "diagnosis_confidence": {
            "score": diag_conf_score,
            "color": _score_color(diag_conf_score) if diag_conf_score is not None else None,
            "reasoning": diag_conf_reasoning,
        },
        "order_type": order_type,
        "direction": str(decision.get("order_direction", "—")) if order_type != _NO_ORDER else "—",
        "entry": decision.get("entry_price"),
        "tp1": decision.get("take_profit_price"),
        "tp2": decision.get("take_profit_price_2"),
        "sl": decision.get("stop_loss_price"),
        "risk_reward": None,
        "estimated_win_rate": format_estimated_win_rate(decision),
        "trade_confidence": {
            "score": _parse_score_100(decision.get("trade_confidence")),
            "color": None,
            "reasoning": str(decision.get("trade_confidence_reasoning") or "").strip(),
        },
        "reasoning": str(reasoning) if reasoning else "",
    }
    if view["trade_confidence"]["score"] is not None:
        view["trade_confidence"]["color"] = _score_color(view["trade_confidence"]["score"])

    if order_type != _NO_ORDER:
        entry = view["entry"]
        tp = view["tp1"]
        sl = view["sl"]
        rr = compute_risk_reward(entry, tp, sl, view["direction"])
        if rr is not None:
            ratio = float(rr["ratio"])
            risk = float(rr["risk"])
            reward = float(rr["reward"])
            win_pct = _parse_score_100(decision.get("estimated_win_rate"))
            eq_ok = win_pct is not None and passes_trader_equation(win_pct, risk, reward)
            min_rr = min_risk_reward_ratio(decision_stance)
            max_rr = max_risk_reward_ratio()
            metrics_ok = (
                ratio >= min_rr
                and (max_rr is None or ratio <= max_rr)
                and (eq_ok if win_pct is not None else True)
            )
            eq_note = (
                " · 方程通过"
                if (win_pct is not None and eq_ok)
                else (" · 方程不通过" if win_pct is not None else "")
            )
            view["risk_reward"] = {
                "ratio_text": rr["ratio_text"],
                "risk": risk,
                "reward": reward,
                "metrics_ok": metrics_ok,
                "note": eq_note,
            }

    return view


# ── Future-trend view ──────────────────────────────────────────────────────────


def build_future_trend_view(stage2_decision: dict | None) -> dict[str, Any]:
    """Build the structured view for the 未来走势预期 panel.

    Returns next_bar and next_cycle modules, each with direction / probabilities
    / reasoning, plus an ``unpredictable`` flag for next_cycle.
    """
    decision = stage2_decision or {}
    view: dict[str, Any] = {"next_bar": None, "next_cycle": None}

    # Module 1: next_bar_prediction
    bar = decision.get("next_bar_prediction")
    if isinstance(bar, dict):
        probs = bar.get("probabilities") or {}
        dominant = _dominant_prediction_direction(probs) or "neutral"
        view["next_bar"] = {
            "direction": str(bar.get("direction", "") or "—"),
            "direction_zh": _DIRECTION_ZH.get(str(bar.get("direction", "")).strip().lower(), "—"),
            "color": _PREDICTION_DOMINANT_COLOR.get(dominant, "#8b949e"),
            "probabilities": {
                "bullish": int(probs.get("bullish", 0) or 0),
                "bearish": int(probs.get("bearish", 0) or 0),
                "neutral": int(probs.get("neutral", 0) or 0),
            },
            "reasoning": str(bar.get("reasoning", "") or "").strip(),
        }

    # Module 2: next_cycle_prediction
    cyc = decision.get("next_cycle_prediction")
    if isinstance(cyc, dict):
        unpredictable = bool(cyc.get("unpredictable", False))
        direction = cyc.get("direction")
        dir_key = str(direction or "").strip().lower()
        if dir_key == "bullish":
            cyc_color = "#3fb950"
        elif dir_key == "bearish":
            cyc_color = "#f85149"
        else:
            cyc_color = "#e6b800"
        probs = cyc.get("probabilities") or {}
        from pa_agent.ai.cycle_enums import CYCLE_ORDER, CYCLE_POSITION_ZH

        sorted_probs: list[tuple[str, int]] = []
        for key in CYCLE_ORDER:
            try:
                pct = int(probs.get(key, 0) or 0)
            except (TypeError, ValueError):
                pct = 0
            sorted_probs.append((key, pct))
        sorted_probs.sort(key=lambda x: x[1], reverse=True)
        top3 = [
            {"label": format_cycle_with_direction(k, direction), "pct": p}
            for k, p in sorted_probs[:3]
        ]
        rest = [{"label": CYCLE_POSITION_ZH.get(k, k), "pct": p} for k, p in sorted_probs[3:]]
        view["next_cycle"] = {
            "unpredictable": unpredictable,
            "direction": str(direction or "—"),
            "direction_zh": _DIRECTION_ZH.get(dir_key, str(direction or "—")),
            "color": cyc_color,
            "top3": top3,
            "rest": rest,
            "reasoning": str(cyc.get("reasoning", "") or "").strip(),
        }

    return view


# ── Decision-tree view ─────────────────────────────────────────────────────────


def build_decision_tree_view(
    *,
    gate_trace: list[dict[str, Any]] | None = None,
    decision_trace: list[dict[str, Any]] | None = None,
    terminal: dict[str, Any] | None = None,
    gate_result: str | None = None,
    gate_shortcircuited: bool = False,
) -> dict[str, Any]:
    """Build the structured view for the 决策树 / 决策树可视化 panels.

    Returns the merged path table (each step with phase/node/answer/basis/reason)
    and a simplified list of static tree sections for the visualization tab.
    """
    _PHASE_ZH = {"gate": "闸门", "decision": "策略"}
    merged = merge_traces(gate_trace, decision_trace)
    path: list[dict[str, Any]] = []
    for i, item in enumerate(merged):
        phase = str(item.get("phase", ""))
        nid = str(item.get("node_id", "?"))
        question = plain_trace_question(item)
        basis = normalize_bar_range(item)
        answer = format_trace_answer(item) or str(item.get("answer", "—"))
        reason = str(item.get("reason", "") or "").strip()
        skipped = item.get("skipped")
        answer_display = f"{answer}（跳过）" if skipped else answer
        if not format_bar_basis_suffix(item) and not skipped:
            reason_display = (reason + " [K线依据未标注]") if reason else "—"
        else:
            reason_display = reason or "—"
        path.append(
            {
                "step": i + 1,
                "phase": _PHASE_ZH.get(phase, phase),
                "node": nid,
                "question": question,
                "answer": answer_display,
                "basis": basis or "—",
                "reason": reason_display,
            }
        )

    tree_data = {}
    try:
        tree_data = load_decision_tree()
    except (FileNotFoundError, OSError):
        # prompt_engineering/二元决策.txt 缺失时优雅降级，Web 端不崩。
        tree_data = {}
    sections: list[dict[str, Any]] = []
    for sec in tree_data.get("sections", []):
        sections.append(
            {
                "id": sec.get("id"),
                "title": sec.get("title", ""),
                "nodes": [
                    {"id": n.get("id"), "question": n.get("question", "")}
                    for n in sec.get("nodes", [])
                ],
            }
        )

    return {
        "path": path,
        "sections": sections,
        "terminal": terminal,
        "gate_result": gate_result,
        "gate_shortcircuited": gate_shortcircuited,
    }
