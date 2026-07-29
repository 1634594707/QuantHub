"""Deterministic financial-event semantics for Chinese news headlines.

This module deliberately separates an event's business impact from textual
sentiment and from any prediction of the security's future price.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EventRule:
    rule_id: str
    label: str
    phrases: tuple[str, ...]
    reason: str


_NEGATIONS = (
    "不存在",
    "不涉及",
    "不构成",
    "并未",
    "没有",
    "尚未",
    "未发生",
    "否认",
    "澄清",
    "未",
    "无",
)

_RULES = (
    EventRule(
        "capital_outflow",
        "negative",
        (
            "主力资金净流出",
            "主力资金流出",
            "主力资金今日撤离",
            "资金净流出",
            "资金撤离",
            "主力出逃",
            "主力卖出",
            "净流出",
            "撤离",
        ),
        "明确的资金流出或卖出事件",
    ),
    EventRule(
        "shareholder_reduction",
        "negative",
        ("拟减持", "计划减持", "减持股份", "股东减持", "减持计划"),
        "股东减持可能增加供给并削弱市场信心",
    ),
    EventRule(
        "regulatory_investigation",
        "negative",
        ("立案调查", "立案侦查", "被立案", "接受调查"),
        "监管或司法调查增加经营与合规不确定性",
    ),
    EventRule(
        "administrative_penalty",
        "negative",
        ("行政处罚", "监管处罚", "收到处罚", "处罚决定书"),
        "行政或监管处罚属于明确的负面公司事件",
    ),
    EventRule(
        "profit_warning",
        "negative",
        ("业绩预亏", "预计亏损", "预告亏损", "净利润亏损", "由盈转亏"),
        "亏损或预亏反映盈利能力恶化",
    ),
    EventRule(
        "debt_default",
        "negative",
        ("债务违约", "未能按期兑付", "逾期未兑付", "兑付违约"),
        "债务违约或未按期兑付反映偿付风险",
    ),
    EventRule(
        "delisting_risk",
        "negative",
        ("退市风险警示", "终止上市", "强制退市", "触及退市", "*ST"),
        "退市风险会显著影响证券的持续交易资格",
    ),
    EventRule(
        "capital_inflow",
        "positive",
        ("主力资金净流入", "主力资金流入", "资金净流入", "主力买入", "净流入"),
        "明确的资金流入或买入事件",
    ),
    EventRule(
        "shareholder_support",
        "positive",
        ("拟增持", "计划增持", "股东增持", "回购股份", "股份回购"),
        "增持或回购通常体现股东或公司的支持意愿",
    ),
    EventRule(
        "profit_upgrade",
        "positive",
        ("业绩预增", "预计扭亏", "扭亏为盈", "净利润大增", "业绩超预期"),
        "盈利预期改善属于正面经营事件",
    ),
)


def classify_event_impact(text: str) -> dict[str, str | float | None]:
    """Classify explicit event impact without making a price prediction."""
    normalized = (text or "").strip()
    for rule in _RULES:
        for phrase in rule.phrases:
            idx = normalized.find(phrase)
            if idx == -1:
                continue
            prefix = normalized[max(0, idx - 12) : idx]
            negated = any(word in prefix for word in _NEGATIONS)
            if negated:
                return {
                    "label": "neutral",
                    "confidence": 0.9,
                    "reason": f"标题否定了“{phrase}”事件，不能按原事件方向判断",
                    "rule_id": f"{rule.rule_id}_negated",
                }
            return {
                "label": rule.label,
                "confidence": 0.95,
                "reason": rule.reason,
                "rule_id": rule.rule_id,
            }

    return {
        "label": "uncertain",
        "confidence": 0.0,
        "reason": "标题未命中明确的金融事件规则",
        "rule_id": None,
    }


def uncertain_price_direction() -> dict[str, str | float]:
    """Return the conservative price view used for headline-only analysis."""
    return {
        "label": "uncertain",
        "confidence": 0.0,
        "reason": "单条新闻标题不足以推断未来价格方向，需结合估值、预期差与市场反应",
    }
