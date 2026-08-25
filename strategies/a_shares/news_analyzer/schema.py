"""新闻结构化分析数据模型。

定义本地 LLM 分析输出的统一结构，供 analyzer / strategy / API / 评估脚本共享。
字段语义与 ``news_scanner`` 已有 ``avg_score`` 对齐（sentiment.score ∈ [-1, 1]）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class SentimentLabel(str, Enum):
    """情绪三分类。"""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class NewsTopic(str, Enum):
    """A 股新闻主题分类（8 类 + unknown 兜底）。

    与前端 ``NEWS_TOPICS`` 常量 1:1 对齐，改动需同步。
    """

    MACRO = "macro"  # 宏观经济
    MONETARY = "monetary"  # 货币政策
    INDUSTRY = "industry"  # 行业动态
    COMPANY = "company"  # 公司经营
    CAPITAL_ACTION = "capital_action"  # 资本运作
    REGULATION = "regulation"  # 监管政策
    MARKET_MOOD = "market_mood"  # 市场情绪
    INTERNATIONAL = "international"  # 国际财经
    UNKNOWN = "unknown"  # 兜底


# 实体类型受控词表（与前端 entity-chip 配色 1:1）
ENTITY_TYPES = ("person", "org", "location")


@dataclass
class NewsEntity:
    """提取出的命名实体。

    ``start``/``end`` 为可选字符偏移（LLM 不稳定时缺省），主要依赖 ``text``+``type``。
    """

    text: str
    type: str  # "person" | "org" | "location"
    start: int | None = None
    end: int | None = None

    def to_dict(self) -> dict:
        return {"text": self.text, "type": self.type, "start": self.start, "end": self.end}


@dataclass
class NewsSentiment:
    """情绪结果。

    ``score`` 范围 [-1.0, 1.0]，与 ``news_scanner.avg_score`` 语义一致；
    ``confidence`` ∈ [0, 1]。
    """

    label: str  # SentimentLabel 枚举值
    score: float
    confidence: float

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "score": round(self.score, 4),
            "confidence": round(self.confidence, 4),
        }


@dataclass
class NewsEventImpact:
    """Financial event impact, independent from textual sentiment."""

    label: str
    confidence: float
    reason: str
    rule_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "rule_id": self.rule_id,
        }


@dataclass
class NewsPriceDirection:
    """Price-direction assessment; headline-only results remain uncertain."""

    label: str
    confidence: float
    reason: str

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
        }


@dataclass
class NewsEventExtraction:
    """Fixed-taxonomy event extraction for research, never a price forecast."""

    event_type: str
    direction: str
    strength: float
    confidence: float
    evidence_excerpt: str
    taxonomy_version: str
    extraction_method: str
    price_prediction_allowed: bool = False

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "direction": self.direction,
            "strength": round(self.strength, 4),
            "confidence": round(self.confidence, 4),
            "evidence_excerpt": self.evidence_excerpt,
            "taxonomy_version": self.taxonomy_version,
            "extraction_method": self.extraction_method,
            "price_prediction_allowed": False,
        }


@dataclass
class NewsAnalysis:
    """单条新闻的结构化分析结果。"""

    title: str
    source: str
    url: str | None
    ts: datetime
    symbols: list[str]
    entities: list[NewsEntity]
    sentiment: NewsSentiment
    topic: str  # NewsTopic 枚举值（str 形式，序列化友好）
    summary: str
    engine: str  # "semantic+api" | "semantic" (display-only) | "unavailable"
    model: str | None
    latency_ms: int
    event_impact: NewsEventImpact = field(
        default_factory=lambda: NewsEventImpact(
            label="uncertain",
            confidence=0.0,
            reason="标题未命中明确的金融事件规则",
        )
    )
    price_direction: NewsPriceDirection = field(
        default_factory=lambda: NewsPriceDirection(
            label="uncertain",
            confidence=0.0,
            reason="单条新闻标题不足以推断未来价格方向",
        )
    )
    research_event: NewsEventExtraction = field(
        default_factory=lambda: NewsEventExtraction(
            event_type="unclassified",
            direction="uncertain",
            strength=0.0,
            confidence=0.0,
            evidence_excerpt="",
            taxonomy_version="news-event-taxonomy-1.0.0",
            extraction_method="deterministic_rules",
        )
    )
    error: str | None = None

    def to_dict(self) -> dict:
        """扁平化，API 序列化用。"""
        # ts 可能是 datetime 或字符串（取决于数据源），统一处理
        if self.ts is None:
            ts_str = None
        elif isinstance(self.ts, str):
            ts_str = self.ts
        else:
            ts_str = self.ts.isoformat(timespec="seconds")
        return {
            "title": self.title,
            "source": self.source,
            "url": self.url,
            "ts": ts_str,
            "symbols": list(self.symbols),
            "entities": [e.to_dict() for e in self.entities],
            "sentiment": self.sentiment.to_dict(),
            "event_impact": self.event_impact.to_dict(),
            "price_direction": self.price_direction.to_dict(),
            "research_event": self.research_event.to_dict(),
            "topic": self.topic,
            "summary": self.summary,
            "engine": self.engine,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass
class NewsBatchResult:
    """批量分析聚合结果。"""

    items: list[NewsAnalysis]
    engine: str  # 批次实际引擎（semantic+api / display_only / unavailable）
    model: str | None
    total: int
    ok: bool  # 仅完整通过配置模型与 LLM 路径时为 True
    degraded_reason: str | None = None
    display_only: bool = False

    def to_dict(self) -> dict:
        return {
            "items": [it.to_dict() for it in self.items],
            "engine": self.engine,
            "model": self.model,
            "total": self.total,
            "ok": self.ok,
            "degraded_reason": self.degraded_reason,
            "display_only": self.display_only,
        }


# ---------------------------------------------------------------------------
# 主题受控词表（供降级与校验共用）
# ---------------------------------------------------------------------------
VALID_TOPICS: frozenset[str] = frozenset(t.value for t in NewsTopic)


def coerce_topic(raw: str | None) -> str:
    """把 LLM 输出的主题字符串规范到 NewsTopic 枚举值，非法值归 unknown。"""
    if not raw:
        return NewsTopic.UNKNOWN.value
    s = str(raw).strip().lower()
    if s in VALID_TOPICS:
        return s
    # 常见同义词兜底
    synonyms = {
        "宏观经济": NewsTopic.MACRO.value,
        "macro_economy": NewsTopic.MACRO.value,
        "货币": NewsTopic.MONETARY.value,
        "央行": NewsTopic.MONETARY.value,
        "行业": NewsTopic.INDUSTRY.value,
        "公司": NewsTopic.COMPANY.value,
        "经营": NewsTopic.COMPANY.value,
        "资本": NewsTopic.CAPITAL_ACTION.value,
        "并购": NewsTopic.CAPITAL_ACTION.value,
        "监管": NewsTopic.REGULATION.value,
        "政策": NewsTopic.REGULATION.value,
        "市场": NewsTopic.MARKET_MOOD.value,
        "情绪": NewsTopic.MARKET_MOOD.value,
        "国际": NewsTopic.INTERNATIONAL.value,
        "海外": NewsTopic.INTERNATIONAL.value,
    }
    return synonyms.get(s, NewsTopic.UNKNOWN.value)


def coerce_sentiment_label(raw: str | None) -> str:
    """规范情绪标签到 SentimentLabel 枚举值，非法值归 neutral。"""
    if not raw:
        return SentimentLabel.NEUTRAL.value
    s = str(raw).strip().lower()
    mapping = {
        "positive": SentimentLabel.POSITIVE.value,
        "pos": SentimentLabel.POSITIVE.value,
        "正面": SentimentLabel.POSITIVE.value,
        "利好": SentimentLabel.POSITIVE.value,
        "negative": SentimentLabel.NEGATIVE.value,
        "neg": SentimentLabel.NEGATIVE.value,
        "负面": SentimentLabel.NEGATIVE.value,
        "利空": SentimentLabel.NEGATIVE.value,
        "neutral": SentimentLabel.NEUTRAL.value,
        "neu": SentimentLabel.NEUTRAL.value,
        "中性": SentimentLabel.NEUTRAL.value,
    }
    return mapping.get(s, SentimentLabel.NEUTRAL.value)
