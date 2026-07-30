"""Deterministic quality gates for PA model output.

The LLM proposes a diagnosis and trade plan. This module independently checks
the machine-verifiable parts before QuantHub exposes or publishes that plan.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

Stage = Literal["stage1", "stage2"]
Severity = Literal["error", "warning"]

CYCLE_VALUES = (
    "spike",
    "micro_channel",
    "tight_channel",
    "normal_channel",
    "broad_channel",
    "trending_tr",
    "trading_range",
    "extreme_tr",
)
ORDER_TYPES = ("限价单", "突破单", "市价单", "不下单")
TRADE_ORDER_TYPES = ORDER_TYPES[:3]


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    field: str
    message: str
    severity: Severity = "error"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationReport:
    stage: Stage
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        errors = sum(issue.severity == "error" for issue in self.issues)
        return {
            "stage": self.stage,
            "valid": self.valid,
            "error_count": errors,
            "warning_count": len(self.issues) - errors,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def merge_reports(*reports: ValidationReport) -> ValidationReport:
    """Combine independent reports while preserving the stage label."""
    if not reports:
        raise ValueError("至少需要一个校验报告")
    stage = reports[0].stage
    if any(report.stage != stage for report in reports):
        raise ValueError("不能合并不同阶段的校验报告")
    return ValidationReport(stage, tuple(issue for report in reports for issue in report.issues))


def invalid_json_report(stage: Stage) -> ValidationReport:
    return ValidationReport(
        stage,
        (ValidationIssue("invalid_json", "$", "正文必须是可解析的单个 JSON 对象"),),
    )


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _required(obj: dict[str, Any], fields: tuple[str, ...]) -> list[ValidationIssue]:
    return [
        ValidationIssue("required", field, "缺少必填字段") for field in fields if field not in obj
    ]


def _enum_issue(field: str, value: object, allowed: tuple[str, ...]) -> ValidationIssue | None:
    if value in allowed:
        return None
    return ValidationIssue("enum", field, f"必须是以下枚举之一：{', '.join(allowed)}")


def _score_issues(obj: dict[str, Any], field: str) -> list[ValidationIssue]:
    value = obj.get(field)
    if value is None:
        return []
    if not _is_number(value) or not 0 <= float(value) <= 100:
        return [ValidationIssue("range", field, "必须是 0 到 100 的有限数值")]
    return []


def validate_stage1(obj: dict[str, Any]) -> ValidationReport:
    issues = _required(obj, ("cycle_position", "direction", "gate_result"))
    for field, allowed in (
        ("cycle_position", CYCLE_VALUES),
        ("direction", ("bullish", "bearish", "neutral")),
        ("gate_result", ("proceed", "wait", "unknown")),
    ):
        if field in obj:
            issue = _enum_issue(field, obj.get(field), allowed)
            if issue:
                issues.append(issue)
    alternative = obj.get("alternative_cycle_position")
    if alternative is not None:
        issue = _enum_issue("alternative_cycle_position", alternative, CYCLE_VALUES)
        if issue:
            issues.append(issue)
    issues.extend(_score_issues(obj, "diagnosis_confidence"))

    levels = obj.get("key_levels")
    if levels is not None:
        if not isinstance(levels, dict):
            issues.append(ValidationIssue("type", "key_levels", "必须是对象"))
        else:
            for name in ("support", "resistance"):
                values = levels.get(name, [])
                if not isinstance(values, list) or any(not _is_number(value) for value in values):
                    issues.append(
                        ValidationIssue("type", f"key_levels.{name}", "必须是有限数值数组")
                    )

    trace = obj.get("gate_trace")
    if trace is not None and not isinstance(trace, list):
        issues.append(ValidationIssue("type", "gate_trace", "必须是数组"))
    elif obj.get("gate_result") == "proceed" and not trace:
        issues.append(
            ValidationIssue(
                "missing_evidence",
                "gate_trace",
                "闸门通过但没有提供可审计路径",
                "warning",
            )
        )
    return ValidationReport("stage1", tuple(issues))


_BAR_REF_RE = re.compile(r"K\s*(\d+)(?:\s*[-~至到]\s*K?\s*(\d+))?", re.IGNORECASE)


def validate_bar_references(obj: dict[str, Any], *, stage: Stage, max_bar: int) -> ValidationReport:
    """Check trace bar ranges against the K-line window sent to the model.

    K numbering is reverse chronological (K1 is the latest closed bar). The
    check is deliberately limited to explicit trace ranges; prose such as a
    pattern description is not treated as a machine-verifiable citation.
    """
    issues: list[ValidationIssue] = []
    trace_fields = ("gate_trace",) if stage == "stage1" else ("decision_trace",)
    for trace_field in trace_fields:
        trace = obj.get(trace_field)
        if trace is None:
            continue
        if not isinstance(trace, list):
            continue  # structural validator owns the type error
        for index, item in enumerate(trace):
            if not isinstance(item, dict):
                continue
            field = f"{trace_field}[{index}].bar_range"
            if "bar_range" not in item:
                issues.append(
                    ValidationIssue("bar_reference", field, "审计节点缺少 K 线范围", "warning")
                )
                continue
            value = item.get("bar_range")
            if value in (None, ""):
                issues.append(
                    ValidationIssue("bar_reference", field, "审计节点必须提供 K 线范围", "warning")
                )
                continue
            if not isinstance(value, str):
                issues.append(ValidationIssue("bar_reference", field, "K 线范围必须是文本"))
                continue
            matches = list(_BAR_REF_RE.finditer(value))
            if not matches or "K" not in value.upper():
                issues.append(
                    ValidationIssue("bar_reference", field, "格式应为 K1 或 K8-K1 等 K 线范围")
                )
                continue
            # Any non-whitespace text outside a simple range is accepted as
            # surrounding prose, but every explicit K number must be in range.
            for match in matches:
                numbers = [int(group) for group in match.groups() if group is not None]
                for number in numbers:
                    if number < 1 or number > max_bar:
                        issues.append(
                            ValidationIssue(
                                "bar_reference_range",
                                field,
                                f"K{number} 超出本次分析窗口 K1-K{max_bar}",
                            )
                        )
    return ValidationReport(stage, tuple(issues))


def _prediction_issues(
    prediction: object,
    *,
    field: str,
    probability_keys: tuple[str, ...],
    direction_keys: tuple[str, ...] | None = None,
) -> list[ValidationIssue]:
    if not isinstance(prediction, dict):
        return [ValidationIssue("type", field, "必须是对象")]
    issues: list[ValidationIssue] = []
    unpredictable = prediction.get("unpredictable")
    if not isinstance(unpredictable, bool):
        return [ValidationIssue("type", f"{field}.unpredictable", "必须是布尔值")]

    probabilities = prediction.get("probabilities")
    if unpredictable:
        if prediction.get("direction") is not None:
            issues.append(
                ValidationIssue(
                    "null_invariant",
                    f"{field}.direction",
                    "unpredictable=true 时方向必须为空",
                )
            )
        if isinstance(probabilities, dict) and any(
            _is_number(value) and float(value) != 0 for value in probabilities.values()
        ):
            issues.append(
                ValidationIssue(
                    "probability_invariant",
                    f"{field}.probabilities",
                    "不可预测状态不应给出非零概率",
                    "warning",
                )
            )
        return issues

    if not isinstance(probabilities, dict):
        return issues + [
            ValidationIssue("type", f"{field}.probabilities", "可预测状态必须提供概率对象")
        ]
    values: list[float] = []
    for key in probability_keys:
        value = probabilities.get(key)
        if not _is_number(value) or not 0 <= float(value) <= 100:
            issues.append(
                ValidationIssue(
                    "range",
                    f"{field}.probabilities.{key}",
                    "必须是 0 到 100 的有限数值",
                )
            )
        else:
            values.append(float(value))
    if len(values) == len(probability_keys) and not 99 <= sum(values) <= 101:
        issues.append(
            ValidationIssue(
                "probability_sum",
                f"{field}.probabilities",
                f"概率总和必须位于 99 到 101，当前为 {sum(values):.2f}",
            )
        )
    if direction_keys and len(values) == len(probability_keys):
        direction = prediction.get("direction")
        if direction not in direction_keys:
            issues.append(
                ValidationIssue("enum", f"{field}.direction", "方向必须与概率键使用同一枚举")
            )
        else:
            maximum = max(values)
            winners = {
                key for key, value in zip(probability_keys, values, strict=True) if value == maximum
            }
            if direction not in winners:
                issues.append(
                    ValidationIssue(
                        "argmax",
                        f"{field}.direction",
                        "方向必须对应最高概率（并列最高可任选其一）",
                    )
                )
    return issues


def _trade_geometry_issues(decision: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    direction = decision.get("order_direction")
    entry = decision.get("entry_price")
    stop = decision.get("stop_loss_price")
    target = decision.get("take_profit_price")
    for field, value in (
        ("decision.entry_price", entry),
        ("decision.stop_loss_price", stop),
        ("decision.take_profit_price", target),
    ):
        if not _is_number(value):
            issues.append(ValidationIssue("type", field, "下单时必须是有限数值"))
    if issues:
        return issues
    entry_f, stop_f, target_f = float(entry), float(stop), float(target)
    if direction == "做多":
        geometry_ok = stop_f < entry_f < target_f
        risk, reward = entry_f - stop_f, target_f - entry_f
    elif direction == "做空":
        geometry_ok = target_f < entry_f < stop_f
        risk, reward = stop_f - entry_f, entry_f - target_f
    else:
        return [ValidationIssue("enum", "decision.order_direction", "下单方向必须是做多或做空")]
    if not geometry_ok:
        return [
            ValidationIssue(
                "price_geometry",
                "decision",
                "做多要求止损 < 入场 < 目标；做空要求目标 < 入场 < 止损",
            )
        ]
    ratio = reward / risk
    if ratio < 1:
        issues.append(
            ValidationIssue(
                "risk_reward",
                "decision.take_profit_price",
                f"计划盈亏比必须至少为 1:1，当前为 {ratio:.2f}:1",
            )
        )
    win_rate = decision.get("estimated_win_rate")
    if _is_number(win_rate):
        probability = float(win_rate) / 100
        if probability * reward <= (1 - probability) * risk:
            issues.append(
                ValidationIssue(
                    "negative_expectancy",
                    "decision.estimated_win_rate",
                    "模型胜率与盈亏比组合不满足正期望约束",
                )
            )
    target2 = decision.get("take_profit_price_2")
    if target2 is not None:
        if not _is_number(target2):
            issues.append(
                ValidationIssue("type", "decision.take_profit_price_2", "必须是有限数值或空")
            )
        elif direction == "做多" and float(target2) <= target_f:
            issues.append(
                ValidationIssue(
                    "price_geometry", "decision.take_profit_price_2", "做多第二目标必须高于第一目标"
                )
            )
        elif direction == "做空" and float(target2) >= target_f:
            issues.append(
                ValidationIssue(
                    "price_geometry", "decision.take_profit_price_2", "做空第二目标必须低于第一目标"
                )
            )
    return issues


def validate_stage2(obj: dict[str, Any], stage1: dict[str, Any]) -> ValidationReport:
    issues = _required(obj, ("decision", "terminal", "next_bar_prediction"))
    decision = obj.get("decision")
    terminal = obj.get("terminal")
    if not isinstance(decision, dict):
        issues.append(ValidationIssue("type", "decision", "必须是对象"))
        decision = {}
    if not isinstance(terminal, dict):
        issues.append(ValidationIssue("type", "terminal", "必须是对象"))
        terminal = {}

    order_type = decision.get("order_type")
    issue = _enum_issue("decision.order_type", order_type, ORDER_TYPES)
    if issue:
        issues.append(issue)
    issues.extend(_score_issues(decision, "diagnosis_confidence"))
    issues.extend(_score_issues(decision, "trade_confidence"))
    issues.extend(_score_issues(decision, "estimated_win_rate"))

    outcome = terminal.get("outcome")
    if outcome not in ("wait", "reject", "trade", "proceed"):
        issues.append(ValidationIssue("enum", "terminal.outcome", "终局枚举无效"))
    price_fields = (
        "order_direction",
        "entry_price",
        "stop_loss_price",
        "take_profit_price",
        "take_profit_price_2",
        "estimated_win_rate",
    )
    if order_type == "不下单":
        for field in price_fields:
            if decision.get(field) is not None:
                issues.append(
                    ValidationIssue(
                        "no_order_invariant",
                        f"decision.{field}",
                        "order_type=不下单 时该字段必须为空",
                    )
                )
        if outcome not in ("wait", "reject"):
            issues.append(
                ValidationIssue(
                    "terminal_mismatch", "terminal.outcome", "不下单必须以 wait 或 reject 结束"
                )
            )
    elif order_type in TRADE_ORDER_TYPES:
        issues.extend(_trade_geometry_issues(decision))
        if outcome != "trade":
            issues.append(
                ValidationIssue(
                    "terminal_mismatch", "terminal.outcome", "下单计划必须以 trade 结束"
                )
            )

    issues.extend(
        _prediction_issues(
            obj.get("next_bar_prediction"),
            field="next_bar_prediction",
            probability_keys=("bullish", "bearish", "neutral"),
            direction_keys=("bullish", "bearish", "neutral"),
        )
    )
    if "next_cycle_prediction" in obj:
        issues.extend(
            _prediction_issues(
                obj.get("next_cycle_prediction"),
                field="next_cycle_prediction",
                probability_keys=CYCLE_VALUES,
            )
        )

    summary = obj.get("diagnosis_summary")
    if isinstance(summary, dict):
        for field in ("cycle_position", "direction"):
            expected = stage1.get(field)
            actual = summary.get(field)
            if expected is not None and actual is not None and expected != actual:
                issues.append(
                    ValidationIssue(
                        "stage_mismatch",
                        f"diagnosis_summary.{field}",
                        f"与阶段一不一致（阶段一为 {expected}）",
                        "warning",
                    )
                )
    if not str(decision.get("reasoning") or "").strip():
        issues.append(
            ValidationIssue("missing_evidence", "decision.reasoning", "缺少决策依据", "warning")
        )
    return ValidationReport("stage2", tuple(issues))


def retry_feedback(report: ValidationReport) -> str:
    errors = [issue for issue in report.issues if issue.severity == "error"]
    details = "\n".join(
        f"- {issue.field}: {issue.message}（{issue.code}）" for issue in errors[:12]
    )
    return (
        "上一个 JSON 未通过程序质量闸门。只修正以下字段，不要改变行情事实，"
        "并重新输出一个完整的裸 JSON 对象：\n"
        f"{details}"
    )
