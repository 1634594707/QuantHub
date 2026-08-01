"""Constrained AI review for deterministic factor research results."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from core.llm import LLMClient, get_llm

RiskLevel = Literal["低", "中", "高"]
AI_REVIEW_TIMEOUT_SECONDS = 120
RESTRICTED_AI_FIELD_FRAGMENTS = (
    "confirmation",
    "forward_return",
    "future_return",
    "return_rank",
    "profit_rank",
    "unpublished",
    "locked_label",
    "target_label",
    "hidden_rank",
)


class RiskReview(BaseModel):
    level: RiskLevel
    reasons: list[str] = Field(min_length=1, max_length=2)


class FactorReviewItem(BaseModel):
    factor_key: str
    assessment: str = Field(min_length=1, max_length=160)
    evidence: list[str] = Field(min_length=1, max_length=2)
    risks: list[str] = Field(default_factory=list, max_length=2)
    regime_fit: list[str] = Field(default_factory=list, max_length=2)
    next_test: str = Field(min_length=1, max_length=180)


class PortfolioReview(BaseModel):
    strengths: list[str] = Field(default_factory=list, max_length=2)
    risks: list[str] = Field(min_length=1, max_length=3)


class ResearchExperiment(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    hypothesis: str = Field(min_length=1, max_length=160)
    design: str = Field(min_length=1, max_length=200)
    success_criteria: str = Field(min_length=1, max_length=160)


class AiReviewPayload(BaseModel):
    verdict: Literal["支持继续研究", "谨慎复核", "证据不足"]
    confidence: int = Field(ge=0, le=100)
    statistical_alignment: Literal["一致", "部分一致", "冲突"]
    summary: str = Field(min_length=1, max_length=320)
    overfitting_risk: RiskReview
    regime_risk: RiskReview
    factor_reviews: list[FactorReviewItem] = Field(min_length=1, max_length=4)
    portfolio_review: PortfolioReview
    experiments: list[ResearchExperiment] = Field(min_length=1, max_length=3)
    uncertainties: list[str] = Field(min_length=1, max_length=3)

    @field_validator("factor_reviews")
    @classmethod
    def unique_factor_keys(cls, value: list[FactorReviewItem]) -> list[FactorReviewItem]:
        keys = [item.factor_key for item in value]
        if len(keys) != len(set(keys)):
            raise ValueError("factor_reviews.factor_key 不能重复")
        return value


def _strip_restricted_ai_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_restricted_ai_fields(item)
            for key, item in value.items()
            if not any(fragment in str(key).lower() for fragment in RESTRICTED_AI_FIELD_FRAGMENTS)
        }
    if isinstance(value, list):
        return [_strip_restricted_ai_fields(item) for item in value]
    return value


def _review_context(result: dict[str, Any], focus: str) -> dict[str, Any]:
    review_candidates = [
        item
        for item in result["factors"]
        if item.get("exploratory_candidate", item.get("selected", False))
    ]
    if not review_candidates:
        review_candidates = [
            item for item in result["factors"] if item["status"] in {"usable", "watch"}
        ][:1]
    review_factors = sorted(
        [
            {
                "key": item["key"],
                "label": item["label"],
                "category": item["category"],
                "statistical_status": item["status"],
                "exploratory_candidate": item.get(
                    "exploratory_candidate", item.get("selected", False)
                ),
                "weight": item["weight"],
                "train_ic": item["train_ic"],
                "test_ic": item["test_ic"],
                "icir": item["icir"],
                "positive_ic_ratio": item["positive_ic_ratio"],
                "hit_rate": item["hit_rate"],
                "p_value": item["p_value"],
                "adjusted_p_value": item.get("adjusted_p_value", item["p_value"]),
                "statistically_significant": item.get("statistically_significant"),
                "decay": item["decay"],
                "test_observations": item["test_observations"],
                "effective_observations": item.get(
                    "effective_observations", item["test_observations"]
                ),
                "p_value_method": item.get("p_value_method", "legacy_correlation_test"),
                "window_pass_rate": item.get("window_pass_rate"),
                "passed_windows": item.get("passed_windows"),
                "window_count": item.get("window_count"),
                "worst_window_ic": item.get("worst_window_ic"),
                "median_window_ic": item.get("median_window_ic"),
                "window_ic_iqr": item.get("window_ic_iqr"),
                "status_transitions": item.get("status_transitions"),
                "direction_flips": item.get("direction_flips"),
                "multi_window_consistent": item.get("multi_window_consistent"),
                "windows": item.get("windows", []),
            }
            for item in review_candidates[:4]
        ],
        key=lambda item: item["key"],
    )
    factor_screen = sorted(
        [
            {
                "key": item["key"],
                "status": item["status"],
                "exploratory_candidate": item.get(
                    "exploratory_candidate", item.get("selected", False)
                ),
                "train_ic": item["train_ic"],
                "test_ic": item["test_ic"],
                "p_value": item["p_value"],
                "adjusted_p_value": item.get("adjusted_p_value", item["p_value"]),
                "statistically_significant": item.get("statistically_significant"),
                "window_pass_rate": item.get("window_pass_rate"),
                "worst_window_ic": item.get("worst_window_ic"),
                "median_window_ic": item.get("median_window_ic"),
                "status_transitions": item.get("status_transitions"),
                "direction_flips": item.get("direction_flips"),
                "multi_window_consistent": item.get("multi_window_consistent"),
            }
            for item in result["factors"]
        ],
        key=lambda item: item["key"],
    )
    methods = sorted(
        [
            {
                "key": item["key"],
                "total_return": item["total_return"],
                "sharpe": item["sharpe"],
                "max_drawdown": item["max_drawdown"],
                "cvar_95": item["cvar_95"],
                "trades": item["trades"],
                "closed_trades": item.get("closed_trades"),
                "profit_factor": item.get("profit_factor"),
                "profit_factor_basis": item.get("profit_factor_basis", "legacy_period_returns"),
                "win_rate": item.get("win_rate"),
                "win_rate_basis": item.get("win_rate_basis", "legacy_period_returns"),
                "average_trade_return": item.get("average_trade_return"),
                "average_win": item.get("average_win"),
                "average_loss": item.get("average_loss"),
                "payoff_ratio": item.get("payoff_ratio"),
            }
            for item in result["methods"]
        ],
        key=lambda item: item["key"],
    )
    summary = result["summary"]
    published_summary = {
        key: summary[key]
        for key in (
            "rows",
            "train_rows",
            "purged_rows",
            "test_rows",
            "walk_forward_test_rows",
            "horizon",
            "transaction_cost_bps",
            "significance_level",
            "significance_method",
            "walk_forward_mode",
            "walk_forward_folds",
            "window_pass_requirement",
            "usable_factors",
            "effective_factor_hypotheses",
            "multifactor_constructed",
            "evaluation_scope",
            "engine_version",
            "factor_formula_version",
            "research_period",
            "thresholds",
        )
        if key in summary
    }
    context = {
        "research_focus": focus,
        "instrument": {
            "symbol": result["symbol"],
            "market": result["market"],
            "interval": result["interval"],
            "source": result["source"],
        },
        "quality": {
            "status": result["quality"]["status"],
            "row_count": result["quality"]["row_count"],
        },
        "summary": published_summary,
        "methodology": result["methodology"],
        "review_factors": review_factors,
        "factor_screen": factor_screen,
        "methods": methods,
        "cost_analysis": result.get("cost_analysis"),
        "information_boundary": {
            "scope": "published_exploratory_statistics_only",
            "ordering": "canonical_key_not_performance_rank",
            "locked_sample_data_access": False,
        },
    }
    return _strip_restricted_ai_fields(context)


def _extract_json(content: str) -> dict[str, Any] | None:
    text = (content or "").strip()
    if text.startswith("```"):
        first_line = text.find("\n")
        text = text[first_line + 1 :] if first_line >= 0 else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    start = text.find("{")
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _validate_payload(payload: dict[str, Any], allowed_keys: set[str]) -> AiReviewPayload:
    review = AiReviewPayload.model_validate(payload)
    unknown = sorted(
        item.factor_key for item in review.factor_reviews if item.factor_key not in allowed_keys
    )
    if unknown:
        raise ValueError(f"AI 引用了不存在的因子键: {', '.join(unknown)}")
    return review


def _system_prompt() -> str:
    return """你是量化研究审阅员。你只审阅程序已经计算出的结构化统计证据，不重新计算指标，不创造数据，也不替代样本外检验。

硬约束：
1. statistical_status 是程序结论，不得修改、升级或降级。
2. 明确区分统计证据、合理推断和未知信息；单标的时间序列不能冒充跨标的普适证据。
3. 重点检查过拟合、样本量、IC 衰减、训练/样本外偏移、交易次数、成本敏感度、因子共线性和市场状态依赖。
4. 不给出买卖指令、目标价或仓位比例，只提出可证伪的后续实验。
5. 只输出一个裸 JSON 对象，不要 markdown。字段必须严格符合下面 schema：
{
  "verdict": "支持继续研究 | 谨慎复核 | 证据不足",
  "confidence": 0到100整数,
  "statistical_alignment": "一致 | 部分一致 | 冲突",
  "summary": "总体审阅摘要",
  "overfitting_risk": {"level": "低 | 中 | 高", "reasons": ["依据"]},
  "regime_risk": {"level": "低 | 中 | 高", "reasons": ["依据"]},
  "factor_reviews": [{
    "factor_key": "必须来自输入 review_factors.key，且每个 review_factors 都审阅一次",
    "assessment": "审阅结论",
    "evidence": ["引用输入中的具体统计量"],
    "risks": ["风险"],
    "regime_fit": ["可能适用或失效的市场状态"],
    "next_test": "可证伪的下一项测试"
  }],
  "portfolio_review": {"strengths": ["组合优点"], "risks": ["组合风险"]},
  "experiments": [{
    "title": "实验名", "hypothesis": "假设", "design": "实验设计", "success_criteria": "通过标准"
  }],
  "uncertainties": ["当前证据无法回答的问题"]
}
保持精炼：每个证据、风险或状态数组最多 2 条，实验最多 3 项。"""


def run_ai_review(
    result: dict[str, Any],
    *,
    focus: str,
    llm: LLMClient | None = None,
    max_validation_retries: int = 1,
) -> dict[str, Any]:
    context = _review_context(result, focus)
    encoded_context = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    fingerprint = hashlib.sha256(encoded_context.encode("utf-8")).hexdigest()[:16]
    allowed_keys = {item["key"] for item in context["review_factors"]}
    client = llm or get_llm()
    messages = [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": f"审阅以下确定性研究快照：\n{encoded_context}"},
    ]
    total_usage: dict[str, int] = {}
    last_error = "AI 未返回有效 JSON"
    attempts = 0
    for attempt in range(max(0, max_validation_retries) + 1):
        attempts += 1
        kwargs: dict[str, Any] = {}
        if getattr(client, "_provider", "") == "deepseek":
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        response = client.chat(
            messages,
            temperature=0.2 if attempt == 0 else 0.0,
            max_tokens=1200,
            response_format={"type": "json_object"},
            request_timeout=AI_REVIEW_TIMEOUT_SECONDS,
            transport_max_retries=0,
            **kwargs,
        )
        for key, value in (response.usage or {}).items():
            total_usage[key] = total_usage.get(key, 0) + int(value)
        payload = _extract_json(response.content)
        try:
            if payload is None:
                raise ValueError("正文不是可解析的 JSON 对象")
            review = _validate_payload(payload, allowed_keys)
            factor_status = {
                item["key"]: {"label": item["label"], "statistical_status": item["status"]}
                for item in result["factors"]
            }
            rendered = review.model_dump()
            for item in rendered["factor_reviews"]:
                item.update(factor_status[item["factor_key"]])
            return {
                "ok": True,
                "review": rendered,
                "meta": {
                    "provider": getattr(client, "_provider", "unknown"),
                    "model": response.model,
                    "generated_at": datetime.now(UTC).isoformat(),
                    "input_fingerprint": fingerprint,
                    "attempts": attempts,
                    "usage": total_usage,
                    "statistical_conclusions_locked": True,
                    "confirmation_labels_excluded": True,
                    "trading_signal_excluded": True,
                    "dynamic_code_execution": False,
                },
            }
        except (ValidationError, ValueError) as exc:
            last_error = str(exc)
            if attempt >= max_validation_retries:
                break
            messages.extend(
                [
                    {"role": "assistant", "content": response.content[:12_000]},
                    {
                        "role": "user",
                        "content": (
                            "上一个 JSON 未通过程序校验。保持研究事实不变，只修正结构或字段并输出完整裸 JSON。"
                            f"\n错误：{last_error[:2000]}"
                        ),
                    },
                ]
            )
    return {
        "ok": False,
        "error": f"AI 科研复核未通过输出校验: {last_error[:500]}",
        "meta": {"attempts": attempts, "input_fingerprint": fingerprint, "usage": total_usage},
    }
