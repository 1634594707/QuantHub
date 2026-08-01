"""Point-in-time news-event contracts and deterministic event-factor research."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import numpy as np
import pandas as pd

EVENT_TAXONOMY = (
    "earnings_guidance",
    "earnings_revision",
    "share_repurchase",
    "shareholder_change",
    "dividend",
    "regulatory_penalty",
    "major_contract",
    "trading_status",
)
EVENT_DIRECTIONS = ("positive", "negative", "neutral", "uncertain")
EVENT_HORIZONS = (1, 3, 5, 10, 20)
EVENT_TAXONOMY_VERSION = "news-event-taxonomy-1.0.0"
EVENT_CLUSTER_RULE_VERSION = "entity-type-content-jaccard-1.0.0"

_EVENT_RULES = (
    ("earnings_revision", ("盈利修正", "业绩修正", "上修", "下修", "修正公告")),
    ("earnings_guidance", ("业绩预告", "业绩预增", "业绩预亏", "预计扭亏", "预告亏损")),
    ("share_repurchase", ("股份回购", "回购股份", "拟回购", "回购方案")),
    ("shareholder_change", ("股东增持", "拟增持", "股东减持", "拟减持", "减持计划")),
    ("dividend", ("现金分红", "利润分配", "派息", "分红方案", "现金红利")),
    ("regulatory_penalty", ("监管处罚", "行政处罚", "处罚决定书", "立案调查")),
    ("major_contract", ("重大合同", "中标项目", "签署合同", "框架协议")),
    ("trading_status", ("停牌", "复牌", "暂停上市", "终止上市")),
)
_NEGATIVE_PHRASES = (
    "下修",
    "预亏",
    "亏损",
    "减持",
    "处罚",
    "调查",
    "终止上市",
    "暂停上市",
)
_POSITIVE_PHRASES = (
    "上修",
    "预增",
    "扭亏",
    "回购",
    "增持",
    "分红",
    "派息",
    "中标",
    "复牌",
)
_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|token|secret|authorization)\s*[:=]\s*[^\s,;]+"
)


def _clamp(value: Any, lower: float = 0.0, upper: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return lower
    return max(lower, min(upper, number))


def extract_event_semantics(text: str, llm_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize LLM extraction into a fixed taxonomy without a price forecast."""
    normalized = (text or "").strip()
    payload = llm_payload or {}
    event_type = str(payload.get("event_type", "")).strip().lower()
    matched_phrase = ""
    if event_type not in EVENT_TAXONOMY:
        event_type = ""
        for candidate_type, phrases in _EVENT_RULES:
            matched_phrase = next((phrase for phrase in phrases if phrase in normalized), "")
            if matched_phrase:
                event_type = candidate_type
                break
    direction = str(payload.get("event_direction", "")).strip().lower()
    if direction not in EVENT_DIRECTIONS:
        if any(phrase in normalized for phrase in _NEGATIVE_PHRASES):
            direction = "negative"
        elif any(phrase in normalized for phrase in _POSITIVE_PHRASES):
            direction = "positive"
        else:
            direction = "uncertain"
    evidence = str(payload.get("event_evidence", "") or "").strip()
    if not evidence:
        evidence = matched_phrase or normalized[:120]
    llm_classified = str(payload.get("event_type", "")).strip().lower() in EVENT_TAXONOMY
    confidence = _clamp(payload.get("event_confidence"), 0.0, 1.0)
    strength = _clamp(payload.get("event_strength"), 0.0, 1.0)
    if event_type and confidence == 0:
        confidence = 0.9 if matched_phrase else 0.7
    if event_type and strength == 0:
        strength = 0.7
    return {
        "event_type": event_type or "unclassified",
        "direction": direction,
        "strength": round(strength, 6),
        "confidence": round(confidence, 6),
        "evidence_excerpt": evidence[:500],
        "taxonomy_version": EVENT_TAXONOMY_VERSION,
        "extraction_method": "llm_fixed_taxonomy" if llm_classified else "deterministic_rules",
        "price_prediction_allowed": False,
    }


def _normalized_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in sorted(event.items())
        if key != "source_url"
    }


def event_snapshot_fingerprint(events: list[dict[str, Any]]) -> str:
    payload = [
        _normalized_event(event) for event in sorted(events, key=lambda row: row["event_id"])
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _ngrams(value: str) -> set[str]:
    normalized = re.sub(r"\s+", "", value.lower())
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[index : index + 2] for index in range(len(normalized) - 1)}


def _jaccard(left: str, right: str) -> float:
    left_set = _ngrams(left)
    right_set = _ngrams(right)
    union = left_set | right_set
    return len(left_set & right_set) / len(union) if union else 0.0


def validate_and_cluster_events(
    events: list[dict[str, Any]],
    *,
    target_entity_id: str,
    minimum_confidence: float = 0.75,
    duplicate_similarity: float = 0.8,
    duplicate_window_hours: int = 72,
) -> dict[str, Any]:
    gate_rows = []
    eligible = []
    for event in events:
        reasons = []
        if event["entity_id"] != target_entity_id or event.get("entity_matches_target") is not True:
            reasons.append("entity_mismatch")
        if event.get("publication_time_verified") is not True:
            reasons.append("publication_time_unverified")
        if float(event["confidence"]) < minimum_confidence:
            reasons.append("low_confidence")
        if event["event_type"] not in EVENT_TAXONOMY:
            reasons.append("unclassified_event_type")
        if not str(event.get("evidence_excerpt", "")).strip():
            reasons.append("missing_evidence")
        row = {"event_id": event["event_id"], "eligible": not reasons, "reasons": reasons}
        gate_rows.append(row)
        if not reasons:
            eligible.append(event)

    ordered = sorted(eligible, key=lambda row: (row["available_time"], row["event_id"]))
    clusters: list[dict[str, Any]] = []
    canonical_events: list[dict[str, Any]] = []
    for event in ordered:
        assigned = False
        for cluster in clusters:
            canonical = cluster["canonical_event"]
            hours = (
                abs((event["published_time"] - canonical["published_time"]).total_seconds()) / 3600
            )
            same_identity = (
                event["entity_id"] == canonical["entity_id"]
                and event["event_type"] == canonical["event_type"]
            )
            exact_content = event["content_fingerprint"] == canonical["content_fingerprint"]
            similarity = _jaccard(event["evidence_excerpt"], canonical["evidence_excerpt"])
            if (
                same_identity
                and hours <= duplicate_window_hours
                and (exact_content or similarity >= duplicate_similarity)
            ):
                cluster["member_event_ids"].append(event["event_id"])
                cluster["maximum_similarity"] = max(cluster["maximum_similarity"], similarity)
                assigned = True
                break
        if assigned:
            continue
        clusters.append(
            {
                "cluster_id": hashlib.sha256(
                    f"{event['entity_id']}|{event['event_type']}|{event['content_fingerprint']}".encode()
                ).hexdigest()[:24],
                "canonical_event": event,
                "member_event_ids": [event["event_id"]],
                "maximum_similarity": 1.0,
            }
        )
        canonical_events.append(event)

    cluster_rows = [
        {
            "cluster_id": cluster["cluster_id"],
            "canonical_event_id": cluster["canonical_event"]["event_id"],
            "member_event_ids": cluster["member_event_ids"],
            "duplicate_count": len(cluster["member_event_ids"]) - 1,
            "maximum_similarity": round(cluster["maximum_similarity"], 6),
        }
        for cluster in clusters
    ]
    return {
        "input_events": len(events),
        "eligible_events_before_deduplication": len(eligible),
        "canonical_events": canonical_events,
        "canonical_event_count": len(canonical_events),
        "rejected_event_count": len(events) - len(eligible),
        "duplicate_event_count": len(eligible) - len(canonical_events),
        "quality_gate": gate_rows,
        "clusters": cluster_rows,
        "cluster_rule_version": EVENT_CLUSTER_RULE_VERSION,
        "minimum_confidence": minimum_confidence,
        "snapshot_fingerprint": event_snapshot_fingerprint(canonical_events),
    }


def _safe_text(value: str) -> str:
    return _SECRET_PATTERN.sub(r"\1=[REDACTED]", value)


def _safe_url(value: str | None, restricted: bool) -> str | None:
    if not value or restricted:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"}:
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _rank_ic(left: list[float], right: list[float]) -> float | None:
    frame = pd.DataFrame({"left": left, "right": right}).dropna()
    if len(frame) < 3 or frame["left"].nunique() < 2 or frame["right"].nunique() < 2:
        return None
    return float(frame["left"].rank().corr(frame["right"].rank()))


def analyze_event_factor_research(
    events: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    *,
    target_entity_id: str,
    minimum_confidence: float = 0.75,
    duplicate_similarity: float = 0.8,
) -> dict[str, Any]:
    validation = validate_and_cluster_events(
        events,
        target_entity_id=target_entity_id,
        minimum_confidence=minimum_confidence,
        duplicate_similarity=duplicate_similarity,
    )
    outcome_by_event = {row["event_id"]: row for row in outcomes}
    rows = []
    for event in validation["canonical_events"]:
        outcome = outcome_by_event.get(event["event_id"])
        if outcome is None:
            continue
        direction_sign = {"positive": 1.0, "negative": -1.0}.get(event["direction"], 0.0)
        signed_strength = direction_sign * float(event["strength"])
        for horizon in EVENT_HORIZONS:
            key = str(horizon)
            residual_return = (
                float(outcome["forward_returns"][key])
                - float(outcome["market_returns"][key])
                - float(outcome["industry_returns"][key])
            )
            rows.append(
                {
                    "event_id": event["event_id"],
                    "event_type": event["event_type"],
                    "direction": event["direction"],
                    "signed_strength": signed_strength,
                    "horizon": horizon,
                    "residual_return": residual_return,
                    "raw_return": float(outcome["forward_returns"][key]),
                    "price_state": outcome["price_state"],
                    "volume_state": outcome["volume_state"],
                    "liquidity_state": outcome["liquidity_state"],
                }
            )

    horizon_reports = []
    for horizon in EVENT_HORIZONS:
        horizon_rows = [row for row in rows if row["horizon"] == horizon]
        residuals = [row["residual_return"] for row in horizon_rows]
        strengths = [row["signed_strength"] for row in horizon_rows]
        horizon_reports.append(
            {
                "horizon": horizon,
                "observations": len(horizon_rows),
                "mean_residual_return": round(float(np.mean(residuals)), 8) if residuals else None,
                "median_residual_return": round(float(np.median(residuals)), 8)
                if residuals
                else None,
                "positive_residual_ratio": round(
                    sum(value > 0 for value in residuals) / len(residuals), 6
                )
                if residuals
                else None,
                "signed_strength_rank_ic": (
                    None
                    if (rank_ic := _rank_ic(strengths, residuals)) is None
                    else round(rank_ic, 6)
                ),
                "label": "market_industry_neutral_residual_return",
            }
        )

    grouped: dict[tuple[str, str, str, str, int], list[float]] = defaultdict(list)
    for row in rows:
        grouped[
            (
                row["event_type"],
                row["price_state"],
                row["volume_state"],
                row["liquidity_state"],
                row["horizon"],
            )
        ].append(row["residual_return"])
    conditional_effects = [
        {
            "event_type": key[0],
            "price_state": key[1],
            "volume_state": key[2],
            "liquidity_state": key[3],
            "horizon": key[4],
            "observations": len(values),
            "mean_residual_return": round(float(np.mean(values)), 8),
        }
        for key, values in sorted(grouped.items())
    ]
    evidence_index = [
        {
            "event_id": event["event_id"],
            "source_document_id": event["source_document_id"],
            "source_url": _safe_url(event.get("source_url"), bool(event.get("restricted_data"))),
            "content_fingerprint": event["content_fingerprint"],
            "evidence_excerpt": _safe_text(event["evidence_excerpt"]),
            "available_time": event["available_time"].isoformat(),
        }
        for event in validation["canonical_events"]
    ]
    return {
        "validation": {
            key: value for key, value in validation.items() if key != "canonical_events"
        },
        "horizons": horizon_reports,
        "conditional_effects": conditional_effects,
        "evidence_index": evidence_index,
        "matched_outcomes": len({row["event_id"] for row in rows}),
        "residual_label": "forward_return_minus_market_return_minus_industry_return",
        "prediction_generated": False,
        "dynamic_code_execution": False,
        "method_version": "news-event-research-1.0.0",
    }
