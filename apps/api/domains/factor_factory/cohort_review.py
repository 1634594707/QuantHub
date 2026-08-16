"""Read-only AI review of immutable cohort evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from core.llm import LLMClient, get_llm

COHORT_REVIEW_PROMPT_VERSION = "cohort-evidence-review-v1"


class CohortReviewPayload(BaseModel):
    recommendation: Literal["continue_observation", "retire", "request_small_live"]
    summary: str = Field(min_length=1, max_length=500)
    primary_return_source: str = Field(min_length=1, max_length=300)
    weaker_than_benchmarks: list[str] = Field(default_factory=list, max_length=12)
    applicable_regimes: list[str] = Field(default_factory=list, max_length=8)
    failure_regimes: list[str] = Field(default_factory=list, max_length=8)
    remaining_risks: list[str] = Field(min_length=1, max_length=12)
    evidence: list[str] = Field(min_length=1, max_length=12)


def _extract_json(content: str) -> dict[str, Any] | None:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    start = text.find("{")
    if start < 0:
        return None
    try:
        payload, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _system_prompt() -> str:
    return """你是量化策略同期证据审阅员。你只能读取程序给出的结构化 cohort 证据，不能修改指标、账本、程序门禁、风险阈值或交易开关。

输出一个裸 JSON 对象：
{
  "recommendation": "continue_observation | retire | request_small_live",
  "summary": "结论",
  "primary_return_source": "收益主要来源",
  "weaker_than_benchmarks": ["候选弱于的基准 key"],
  "applicable_regimes": ["适用状态"],
  "failure_regimes": ["失效状态"],
  "remaining_risks": ["剩余风险"],
  "evidence": ["引用输入中的具体指标"]
}

硬约束：
1. program_gate.passed=false 时不得建议 request_small_live。
2. 市场顺风、杠杆、敞口、换手、尾部风险或资金占用是主要收益来源时不得建议 request_small_live。
3. 必须指出候选弱于哪些基准、随机分位数和风险调整后超额表现。
4. 不输出交易指令、金额、仓位或开关操作。"""


def run_cohort_ai_review(
    evidence: dict[str, Any],
    *,
    llm: LLMClient | None = None,
) -> dict[str, Any]:
    encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    evidence_hash = hashlib.sha256(encoded.encode()).hexdigest()
    client = llm or get_llm()
    response = client.chat(
        [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": encoded},
        ],
        temperature=0,
        max_tokens=1200,
        response_format={"type": "json_object"},
    )
    payload = _extract_json(response.content)
    try:
        if payload is None:
            raise ValueError("AI response is not a JSON object")
        review = CohortReviewPayload.model_validate(payload)
    except (ValidationError, ValueError) as exc:
        return {
            "ok": False,
            "error": str(exc),
            "audit": {
                "prompt_version": COHORT_REVIEW_PROMPT_VERSION,
                "evidence_hash": evidence_hash,
                "output_hash": hashlib.sha256(response.content.encode()).hexdigest(),
                "output_raw": response.content,
            },
        }
    program_gate = evidence.get("program_gate") or {}
    conflict_reasons: list[str] = []
    if review.recommendation == "request_small_live" and not program_gate.get("passed"):
        conflict_reasons.append("program_gate_not_passed")
    effective = "continue_observation" if conflict_reasons else review.recommendation
    rendered = review.model_dump()
    return {
        "ok": True,
        "review": rendered,
        "effective_recommendation": effective,
        "conflict_reasons": conflict_reasons,
        "application_draft": (
            {
                "status": "draft",
                "created_by": "ai",
                "submission_allowed": False,
                "live_trading_enabled": False,
            }
            if review.recommendation == "request_small_live"
            else None
        ),
        "audit": {
            "recorded_at": datetime.now(UTC).isoformat(),
            "provider": getattr(client, "_provider", "unknown"),
            "model": response.model,
            "prompt_version": COHORT_REVIEW_PROMPT_VERSION,
            "evidence_hash": evidence_hash,
            "output_hash": hashlib.sha256(response.content.encode()).hexdigest(),
            "output_raw": response.content,
            "metrics_locked": True,
            "ledger_write_access": False,
            "live_trading_enabled": False,
        },
    }
