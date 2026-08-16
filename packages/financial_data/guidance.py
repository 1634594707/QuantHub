"""Fail-closed action guidance derived from the unified research decision."""

from __future__ import annotations

from datetime import datetime

from core.research_decision import ResearchDecision

from .contracts import ActionGuidance, HoldingStatus


def build_action_guidance(
    decision: ResearchDecision,
    *,
    holding_status: HoldingStatus,
    evidence_coverage: dict[str, str],
    review_at: datetime,
) -> ActionGuidance:
    coverage = {
        key: value if value in {"covered", "partial", "missing", "stale"} else "missing"
        for key, value in evidence_coverage.items()
    }
    fully_covered = bool(coverage) and all(value == "covered" for value in coverage.values())
    if decision.direction == "insufficient":
        status = "insufficient_data"
    elif decision.direction == "conflicted":
        status = "wait_for_confirmation"
    elif decision.direction == "short":
        status = "reduce_risk" if holding_status == HoldingStatus.HELD else "exit_watch"
    elif decision.direction == "long":
        status = "review_holding" if holding_status == HoldingStatus.HELD else "research_further"
    else:
        status = "continue_observing"

    reasons = tuple(
        item.reason or f"{item.module}: {item.direction}"
        for item in decision.module_opinions
        if item.status == "available"
    ) or ("当前没有足够的有效模块证据",)
    risks = (
        tuple(item.reason for item in decision.conflicts)
        or tuple(
            f"{item.module} 证据状态为 {item.status}"
            for item in decision.module_opinions
            if item.status != "available"
        )
        or ("市场与公司条件变化可能使当前结论失效",)
    )
    triggers = tuple(decision.reevaluate_triggers) or ("获得新的关键证据后复核",)
    invalidation = tuple(decision.invalidation_conditions) or ("任一关键证据失效或过期",)
    return ActionGuidance(
        status=status,
        holding_status=holding_status,
        primary_reasons=reasons,
        primary_risks=risks,
        trigger_conditions=triggers,
        invalidation_conditions=invalidation,
        review_at=review_at,
        evidence_coverage=coverage,
        execution_eligible=decision.execution_eligible and fully_covered,
    )
