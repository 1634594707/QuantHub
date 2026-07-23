# -*- coding: utf-8 -*-
"""A股影响评分与置信度计算（固定公式）。

从原 ``trading-master/03-daily_news/daily-news/scripts/scoring.py`` 下沉而来，
所有公式严格对齐 ``rules/scoring.md``，仅剥离 CLI/打印逻辑，并补充：
    - ``ScoringInput`` / ``ScoreBreakdown`` 数据类
    - ``score_environment`` 一站式打分入口
    - ``execution_pace`` 综合环境分+置信度 → 执行节奏映射（scoring.md §9）

所有公式保持与原脚本一致，禁止主观拍分。
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ─────────────────────────────────────────────
# Core formula helpers（与原 scoring.py 完全一致）
# ─────────────────────────────────────────────

def clamp(value: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, value))


def calc_technical_strength(
    above_ma20: bool,
    above_ma50: bool,
    above_ma200: bool,
    rsi: float,
    macd_positive: bool,
    above_pivot: bool,
) -> float:
    """技术结构强度 (0–100, before penalties)."""
    ma_score = (10 if above_ma20 else 0) + (10 if above_ma50 else 0) + (10 if above_ma200 else 0)

    if rsi < 40:
        rsi_score = 8
    elif rsi <= 60:
        rsi_score = 15
    else:
        rsi_score = 25

    macd_score = 25 if macd_positive else 10
    pivot_score = 20 if above_pivot else 8

    return float(ma_score + rsi_score + macd_score + pivot_score)


def calc_risk_appetite(
    breadth_available: bool,
    breadth_score_raw: float,
    etf_change_pct: float,
    news_risk_adj: float,
) -> tuple[float, str]:
    """风险偏好温度 (0–100, before penalties), (label)."""
    if breadth_available:
        base = clamp(breadth_score_raw, 0, 60)
        label = "广度口径"
    else:
        # Map ETF daily % change: -3% → 0, 0% → 20, +3% → 40
        base = clamp(20.0 + (etf_change_pct / 3.0) * 20.0, 0, 40)
        label = "代理口径"

    return clamp(base + news_risk_adj, 0, 100), label


def calc_signal_dim(base: float, bullish: int, bearish: int) -> float:
    """宏观/商品/事件 三项维度 (0–100, before penalties)."""
    return clamp(base + 10 * bullish - 10 * bearish)


def apply_penalties(raw: float, gap_count: int, div_count: int) -> float:
    """缺口与分歧惩罚后的最终分."""
    penalty = min(25, 5 * gap_count) + min(20, 5 * div_count)
    return clamp(raw - penalty)


def calc_composite_env(tech: float, risk: float, macro: float, commodity: float, event: float) -> float:
    """综合环境分."""
    return round(0.30 * tech + 0.20 * risk + 0.20 * macro + 0.15 * commodity + 0.15 * event, 1)


def calc_confidence(
    data_completeness: float,
    source_consistency: float,
    tech_clarity: float,
    event_explain: float,
) -> float:
    """置信度总分."""
    return round(
        0.35 * data_completeness
        + 0.25 * source_consistency
        + 0.25 * tech_clarity
        + 0.15 * event_explain,
        1,
    )


def confidence_level(score: float) -> str:
    """置信度等级（scoring.md §7）。"""
    if score >= 75:
        return "High"
    elif score >= 55:
        return "Medium"
    return "Low"


# ─────────────────────────────────────────────
# 结构化打分入口
# ─────────────────────────────────────────────

@dataclass
class ScoringInput:
    """打分所需全部原始输入（对应 scoring.md §2 必填字段）。"""
    # 技术面
    above_ma20: bool = False
    above_ma50: bool = False
    above_ma200: bool = False
    rsi: float = 50.0
    macd_positive: bool = False
    above_pivot: bool = False
    # 风险偏好
    breadth_available: bool = False
    breadth_score: float = 30.0        # 广度原始分 0–60
    etf_change: float = 0.0            # 300ETF 日涨跌 %（代理口径）
    news_risk_adj: float = 0.0         # 新闻风险修正 -20 到 +20
    # 宏观/商品/事件 证据计数
    macro_bull: int = 0
    macro_bear: int = 0
    commodity_bull: int = 0
    commodity_bear: int = 0
    event_bull: int = 0
    event_bear: int = 0
    # 数据质量
    available: int = 0                 # 可用数据项数量
    total: int = 0                     # 应有数据项总数
    consistent: int = 0                # 双源一致项数量
    verifiable: int = 0                # 可校验（双源）项数量
    gaps: int = 0                      # 关键缺口项数
    divergences: int = 0               # 明显分歧项数


@dataclass
class ScoreBreakdown:
    """打分结果。所有分数均为惩罚后的最终分（0–100）。"""
    tech: float                        # 技术结构强度
    risk: float                        # 风险偏好温度
    risk_label: str                    # 风险偏好口径
    macro: float                       # 宏观与流动性支持
    commodity: float                   # 商品与通胀扰动
    event: float                       # 事件冲击可控度
    composite: float                   # 综合环境分
    data_completeness: float           # 数据完整性
    source_consistency: float          # 多源一致性
    tech_clarity: float                # 技术信号清晰度
    confidence: float                  # 置信度总分
    confidence_level: str              # 置信度等级 High/Medium/Low
    pace: str                          # 执行节奏（进攻/均衡/防守/观望）
    is_proxy: bool = field(default=False)   # 风险偏好是否使用代理口径

    def to_dict(self) -> dict:
        return {
            "tech": self.tech,
            "risk": self.risk,
            "risk_label": self.risk_label,
            "macro": self.macro,
            "commodity": self.commodity,
            "event": self.event,
            "composite": self.composite,
            "data_completeness": self.data_completeness,
            "source_consistency": self.source_consistency,
            "tech_clarity": self.tech_clarity,
            "confidence": self.confidence,
            "confidence_level": self.confidence_level,
            "pace": self.pace,
            "is_proxy": self.is_proxy,
        }


def execution_pace(composite: float, level: str) -> str:
    """综合环境分 + 置信度等级 → 执行节奏（scoring.md §9）。

    | 综合环境分 | 置信度        | 执行节奏 |
    | ≥ 70      | High/Medium  | 进攻 |
    | 55–69     | High/Medium  | 均衡 |
    | 40–54     | 任意         | 防守 |
    | < 40      | 任意         | 观望 |
    | 任意      | Low          | 观望（覆盖上表） |
    """
    if level == "Low":
        return "观望"
    if composite >= 70:
        return "进攻"
    if composite >= 55:
        return "均衡"
    if composite >= 40:
        return "防守"
    return "观望"


def score_environment(inp: ScoringInput) -> ScoreBreakdown:
    """一站式打分：按 scoring.md 全套固定公式计算并返回结构化结果。

    流程与原 ``scoring.py::print_results`` 的计算部分完全一致，仅去掉打印。
    """
    # ── 技术结构强度 ──────────────────────
    tech_raw = calc_technical_strength(
        inp.above_ma20, inp.above_ma50, inp.above_ma200,
        inp.rsi, inp.macd_positive, inp.above_pivot,
    )
    tech = apply_penalties(tech_raw, inp.gaps, inp.divergences)

    # ── 风险偏好温度 ──────────────────────
    risk_raw, risk_label = calc_risk_appetite(
        inp.breadth_available, inp.breadth_score, inp.etf_change, inp.news_risk_adj,
    )
    risk = apply_penalties(risk_raw, inp.gaps, inp.divergences)

    # ── 信号维度（宏观/商品/事件）──────────
    macro_raw = calc_signal_dim(50, inp.macro_bull, inp.macro_bear)
    macro = apply_penalties(macro_raw, inp.gaps, inp.divergences)

    commodity_raw = calc_signal_dim(50, inp.commodity_bull, inp.commodity_bear)
    commodity = apply_penalties(commodity_raw, inp.gaps, inp.divergences)

    event_raw = calc_signal_dim(50, inp.event_bull, inp.event_bear)
    event = apply_penalties(event_raw, inp.gaps, inp.divergences)

    # ── 数据质量 ──────────────────────────
    data_completeness = round(100 * inp.available / inp.total) if inp.total else 0
    source_consistency = round(100 * inp.consistent / inp.verifiable) if inp.verifiable else 0

    # ── 综合 / 置信度 ─────────────────────
    composite = calc_composite_env(tech, risk, macro, commodity, event)
    tech_clarity = round(0.5 * tech + 0.5 * risk)
    confidence = calc_confidence(data_completeness, source_consistency, tech_clarity, event)
    level = confidence_level(confidence)
    pace = execution_pace(composite, level)

    return ScoreBreakdown(
        tech=tech,
        risk=risk,
        risk_label=risk_label,
        macro=macro,
        commodity=commodity,
        event=event,
        composite=composite,
        data_completeness=float(data_completeness),
        source_consistency=float(source_consistency),
        tech_clarity=float(tech_clarity),
        confidence=confidence,
        confidence_level=level,
        pace=pace,
        is_proxy=(risk_label == "代理口径"),
    )
