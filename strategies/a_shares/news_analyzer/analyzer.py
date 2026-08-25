"""NewsAnalyzer：FinBERT2 + 配置 LLM 结构化分析。

设计原则：

    1. 仅使用配置的 FinBERT2 本地模型作为情绪基础；不切换 SnowNLP、关键词或规则模型。
    2. 配置的 LLM 必须完整返回批次结构化结果，才允许 ``ok=True`` 的研究/信号输入。
    3. 模型或 LLM 不可用时可返回 ``display_only`` 诊断，但不得作为信号或研究证据。
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

from core.config import get_config
from core.data_feed.base import News
from core.llm import get_llm
from core.news_event_research import EVENT_DIRECTIONS, EVENT_TAXONOMY, extract_event_semantics
from strategies.a_shares.news_analyzer.event_semantics import (
    classify_event_impact,
    uncertain_price_direction,
)
from strategies.a_shares.news_analyzer.prompts import (
    BATCH_ANALYSIS_SYSTEM_PROMPT,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    build_user_prompt,
)
from strategies.a_shares.news_analyzer.schema import (
    VALID_TOPICS,
    NewsAnalysis,
    NewsBatchResult,
    NewsEntity,
    NewsEventExtraction,
    NewsEventImpact,
    NewsPriceDirection,
    NewsSentiment,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 模块常量
# ---------------------------------------------------------------------------
_DEFAULT_BATCH_SIZE = 5
_DEFAULT_MAX_TITLE_CHARS = 200
_MAX_ENTITIES_PER_ITEM = 5
_MAX_SUMMARY_CHARS = 60
# 情绪阈值（pos_prob ∈ [0,1]，与 news_scanner / SentimentAnalyzer 对齐）
_POS_THRESHOLD = 0.65
_NEG_THRESHOLD = 0.35
_FUSION_API_WEIGHT = 0.5


class NewsAnalyzer:
    """新闻结构化分析器（FinBERT2 情绪 + 配置 LLM 结构化分析）。

    可用路径必须同时满足：
        1. 每条新闻均由配置的 FinBERT2 成功推理；
        2. 配置的 LLM 对整个批次返回有效的结构化 JSON。

    任一步失败仅返回明确标记的 display-only 结果，禁止下游将其作为信号或证据。
    """

    def __init__(
        self,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        max_title_chars: int = _DEFAULT_MAX_TITLE_CHARS,
        api_provider: str = "deepseek",
    ) -> None:
        self._batch_size = max(1, int(batch_size))
        self._max_title_chars = max(20, int(max_title_chars))
        self._api_provider = api_provider
        self._sentiment_analyzer: Any | None = None  # 懒加载
        self._api_llm: Any | None = None  # 懒加载（None 也表示未配置）
        self._api_checked: bool = False  # 是否已检查 API 可用性

    @classmethod
    def from_config(cls, market: str = "a_shares") -> NewsAnalyzer:
        """按 ``modules.news_analyzer`` 配置构造。"""
        cfg = get_config(market).get("modules", {}).get("news_analyzer", {})
        return cls(
            batch_size=int(cfg.get("batch_size", _DEFAULT_BATCH_SIZE)),
            max_title_chars=int(cfg.get("max_title_chars", _DEFAULT_MAX_TITLE_CHARS)),
            api_provider=cfg.get("api_provider", "deepseek"),
        )

    # ------------------------------------------------------------------
    # 健康状态
    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        """完整模型和 LLM 路径均可用时，才允许生成可用分析。"""
        return self._get_sentiment_analyzer().is_available() and self._check_api_available()

    def reset_availability(self) -> None:
        """清除 API 客户端缓存（前端「刷新」按钮调用）。"""
        self._api_llm = None
        self._api_checked = False

    def health(self) -> dict[str, Any]:
        """返回健康状态字典（供 ``/news/health`` 端点）。"""
        sa = self._get_sentiment_analyzer()
        sentiment_ok = sa.is_available()
        api_ok = self._check_api_available()
        api_cfg = get_config().get("llm", {}).get(self._api_provider, {})
        return {
            "ok": sentiment_ok and api_ok,
            "engine": sa.engine,
            "sentiment_model_available": sentiment_ok,
            "sentiment_model_reason": sa.unavailable_reason,
            "api_enhancement": api_ok,
            "api_provider": self._api_provider,
            "model": api_cfg.get("model") if api_ok else None,
        }

    # ------------------------------------------------------------------
    # 单条 / 批量分析
    # ------------------------------------------------------------------
    def analyze_one(self, news: News) -> NewsAnalysis | None:
        """分析单条新闻；不可用时返回 None，而不是伪造中性结果。"""
        result = self.analyze_batch([news])
        return result.items[0] if result.ok and result.items else None

    def analyze_batch(self, news_list: list[News]) -> NewsBatchResult:
        """批量分析新闻。

        Returns:
            仅配置模型和 LLM 全部成功时返回 ``ok=True``；其他结果明确标为
            ``display_only``，不得用于信号或研究证据。
        """
        if not news_list:
            return NewsBatchResult(
                items=[],
                engine="unavailable",
                model=None,
                total=0,
                ok=False,
                degraded_reason="empty_input",
                display_only=True,
            )

        sa = self._get_sentiment_analyzer()
        # 1. 所有输入必须由配置的 FinBERT2 成功推理，不能改用其他算法。
        sentiment_results: list[tuple[float, float, str]] = []
        for news in news_list:
            try:
                pos_prob, certainty, eng = sa.analyze(news.title or "")
            except Exception as exc:  # noqa: BLE001 - model boundary is converted to unavailable output
                logger.warning("FinBERT2 情绪推理异常，不生成替代结论: %s", exc)
                return self._unavailable_batch(
                    news_list,
                    "sentiment_model_failed",
                    reason=str(exc),
                )
            if pos_prob is None or eng != "transformers":
                return self._unavailable_batch(
                    news_list,
                    "sentiment_model_unavailable",
                    reason=sa.unavailable_reason or f"unexpected_engine:{eng}",
                )
            sentiment_results.append((pos_prob, certainty, eng))

        # 2. 配置 LLM 必须完整返回整个批次的结构化输出。
        if not self._check_api_available():
            return self._display_only_batch(news_list, sentiment_results, "api_unavailable")
        try:
            api_objs, model_name = self._api_enhance_batch(news_list)
        except Exception as exc:  # noqa: BLE001 - API boundary is converted to display-only output
            logger.warning("配置 LLM 结构化分析失败，不生成可用新闻结论: %s", exc)
            return self._display_only_batch(
                news_list,
                sentiment_results,
                "api_call_failed",
            )
        if len(api_objs) != len(news_list) or not all(
            self._is_complete_api_object(item) for item in api_objs
        ):
            return self._display_only_batch(
                news_list,
                sentiment_results,
                "api_invalid_response",
            )

        # 3. 两个配置路径均成功后才构造可用结果。
        items: list[NewsAnalysis] = []
        for i, news in enumerate(news_list):
            pos_prob, certainty, eng = sentiment_results[i]
            obj = api_objs[i]
            items.append(
                self._build_analysis(
                    news=news,
                    pos_prob=pos_prob,
                    certainty=certainty,
                    sentiment_engine=eng,
                    obj=obj,
                    enhanced=True,
                    model=model_name,
                )
            )

        return NewsBatchResult(
            items=items,
            engine="semantic+api",
            model=model_name,
            total=len(news_list),
            ok=True,
            degraded_reason=None,
            display_only=False,
        )

    def _unavailable_batch(
        self,
        news_list: list[News],
        code: str,
        *,
        reason: str | None = None,
    ) -> NewsBatchResult:
        """返回无可用模型结论的诊断，避免虚构中性新闻分析。"""
        detail = f"{code}: {reason}" if reason else code
        return NewsBatchResult(
            items=[],
            engine="unavailable",
            model=None,
            total=len(news_list),
            ok=False,
            degraded_reason=detail,
            display_only=True,
        )

    def _display_only_batch(
        self,
        news_list: list[News],
        sentiment_results: list[tuple[float, float, str]],
        reason: str,
    ) -> NewsBatchResult:
        """保留已验证本地模型的展示结果，但明确禁止其进入信号或证据路径。"""
        items: list[NewsAnalysis] = []
        for news, (pos_prob, certainty, eng) in zip(news_list, sentiment_results, strict=True):
            item = self._build_analysis(
                news=news,
                pos_prob=pos_prob,
                certainty=certainty,
                sentiment_engine=eng,
                obj=None,
                enhanced=False,
                model=None,
            )
            item.error = reason
            items.append(item)
        return NewsBatchResult(
            items=items,
            engine="display_only",
            model=None,
            total=len(news_list),
            ok=False,
            degraded_reason=reason,
            display_only=True,
        )

    @staticmethod
    def _is_complete_api_object(value: object) -> bool:
        """仅接受足以支持结构化研究的完整 LLM 条目，不补默认字段。"""
        if not isinstance(value, dict):
            return False
        required = (
            "sentiment",
            "sentiment_score",
            "topic",
            "entities",
            "summary",
            "event_type",
            "event_direction",
            "event_strength",
            "event_confidence",
            "event_evidence",
        )
        if any(value.get(field) is None for field in required):
            return False
        sentiment = str(value["sentiment"]).strip().lower()
        if sentiment not in {"positive", "negative", "neutral"}:
            return False
        topic = str(value["topic"]).strip().lower()
        if topic not in VALID_TOPICS - {"unknown"}:
            return False
        event_type = str(value["event_type"]).strip().lower()
        if event_type not in {*EVENT_TAXONOMY, "unclassified"}:
            return False
        if str(value["event_direction"]).strip().lower() not in EVENT_DIRECTIONS:
            return False
        if (
            not isinstance(value["summary"], str)
            or not value["summary"].strip()
            or len(value["summary"].strip()) > _MAX_SUMMARY_CHARS
        ):
            return False
        if not isinstance(value["event_evidence"], str) or not value["event_evidence"].strip():
            return False
        entities = value["entities"]
        if not isinstance(entities, list) or len(entities) > _MAX_ENTITIES_PER_ITEM:
            return False
        for entity in entities:
            if not isinstance(entity, dict):
                return False
            if not isinstance(entity.get("text"), str) or not entity["text"].strip():
                return False
            if str(entity.get("type", "")).strip().lower() not in {"person", "org", "location"}:
                return False
        try:
            sentiment_score = float(value["sentiment_score"])
            event_strength = float(value["event_strength"])
            event_confidence = float(value["event_confidence"])
        except (TypeError, ValueError):
            return False
        if not all(
            math.isfinite(item) for item in (sentiment_score, event_strength, event_confidence)
        ):
            return False
        if not (-1.0 <= sentiment_score <= 1.0):
            return False
        if sentiment == "positive" and sentiment_score <= 0:
            return False
        if sentiment == "negative" and sentiment_score >= 0:
            return False
        if sentiment == "neutral" and abs(sentiment_score) > 0.34:
            return False
        if not (0.0 <= event_strength <= 1.0 and 0.0 <= event_confidence <= 1.0):
            return False
        return True

    # ------------------------------------------------------------------
    # API 增强调用
    # ------------------------------------------------------------------
    def _api_enhance_batch(self, news_list: list[News]) -> tuple[list[dict], str | None]:
        """调用 DeepSeek API 批量分析 NER/主题/摘要，返回 dict 列表与模型名。

        失败由调用方转为 display-only 结果，不生成可用分析。
        """
        llm = self._get_api_llm()
        assert llm is not None  # 由 _check_api_available 保证

        titles = [self._normalize_title(n.title) for n in news_list]
        messages = [
            {"role": "system", "content": BATCH_ANALYSIS_SYSTEM_PROMPT.format(n=len(titles))},
            {"role": "user", "content": build_user_prompt(titles)},
        ]
        chat_kwargs: dict[str, Any] = {}
        if self._api_provider == "deepseek":
            # DeepSeek v4 默认先生成 reasoning_content。结构化抽取无需推理，
            # 显式关闭可避免 max_tokens 被推理耗尽后 content 为空。
            chat_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        resp = llm.chat(
            messages,
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
            **chat_kwargs,
        )
        if not resp.content or not resp.content.strip():
            raise ValueError("API 模型返回空内容")
        objs = self._parse_batch_json(resp.content, expected_n=len(news_list))
        return objs, resp.model

    def _parse_batch_json(self, raw: str, expected_n: int) -> list[dict]:
        """严格解析与输入一一对应的 LLM JSON 数组，不重建缺失条目。"""
        if not raw:
            return []
        try:
            parsed: Any = json.loads(raw.strip())
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list) or len(parsed) != expected_n:
            return []
        if not all(isinstance(item, dict) for item in parsed):
            return []
        return parsed

    # ------------------------------------------------------------------
    # 构建分析结果
    # ------------------------------------------------------------------
    def _build_analysis(
        self,
        news: News,
        pos_prob: float,
        certainty: float,
        sentiment_engine: str,
        obj: dict | None,
        enhanced: bool,
        model: str | None,
    ) -> NewsAnalysis:
        """合并 SentimentAnalyzer 情绪 + API 结构化字段构造 ``NewsAnalysis``。

        Args:
            pos_prob: SentimentAnalyzer 返回的正向概率 [0,1]
            certainty: SentimentAnalyzer 返回的确定性 [0,1]
            sentiment_engine: SentimentAnalyzer 实际引擎（仅允许 transformers）
            obj: API 增强返回的 dict（None 表示未增强）
            enhanced: 是否成功获得 API 增强
        """
        # FinBERT2 情绪
        score = pos_prob * 2.0 - 1.0  # [0,1] -> [-1,1]
        if pos_prob >= _POS_THRESHOLD:
            label = "positive"
        elif pos_prob <= _NEG_THRESHOLD:
            label = "negative"
        else:
            label = "neutral"
        sentiment = NewsSentiment(label=label, score=score, confidence=certainty)

        # API 成功时与 FinBERT2 结果等权融合。
        if obj is not None and obj.get("sentiment"):
            api_sentiment = self._parse_api_sentiment(obj)
            sentiment = self._merge_sentiments(
                local=sentiment,
                api=api_sentiment,
                local_engine=sentiment_engine,
            )

        # LLM 字段已在完整性检查中验证，无需再修正或补默认值。
        if obj is not None:
            topic = str(obj["topic"]).strip().lower()
            entities = self._parse_entities(obj.get("entities"))
            summary = str(obj["summary"]).strip()
        else:
            topic = "unknown"
            entities = []
            summary = (news.title or "")[:_MAX_SUMMARY_CHARS]

        engine = "semantic+api" if enhanced else "semantic"
        event_impact = NewsEventImpact(**classify_event_impact(news.title or ""))
        price_direction = NewsPriceDirection(**uncertain_price_direction())
        research_event = NewsEventExtraction(**extract_event_semantics(news.title or "", obj))

        return NewsAnalysis(
            title=news.title,
            source=news.source,
            url=news.url,
            ts=news.ts,
            symbols=list(news.symbols),
            entities=entities,
            sentiment=sentiment,
            topic=topic,
            summary=summary,
            engine=engine,
            model=model,
            latency_ms=0,
            event_impact=event_impact,
            price_direction=price_direction,
            research_event=research_event,
        )

    @staticmethod
    def _parse_api_sentiment(obj: dict) -> NewsSentiment:
        """解析已通过完整性校验的 API 情绪，不补默认标签或分数。"""
        label = str(obj["sentiment"]).strip().lower()
        score = float(obj["sentiment_score"])
        confidence = abs(score) if label != "neutral" else 1.0 - abs(score)
        return NewsSentiment(label=label, score=score, confidence=confidence)

    @staticmethod
    def _merge_sentiments(
        local: NewsSentiment,
        api: NewsSentiment,
        local_engine: str,
    ) -> NewsSentiment:
        """融合两个已验证模型的情绪，不接受替代引擎。"""
        if local_engine != "transformers":
            raise ValueError(f"不允许将 {local_engine} 作为可用新闻情绪来源")

        local_weight = 1.0 - _FUSION_API_WEIGHT
        score = local.score * local_weight + api.score * _FUSION_API_WEIGHT
        if score >= 0.3:
            label = "positive"
        elif score <= -0.3:
            label = "negative"
        else:
            label = "neutral"

        if local.label == api.label:
            confidence = local.confidence * local_weight + api.confidence * _FUSION_API_WEIGHT
        else:
            confidence = abs(score) if label != "neutral" else 1.0 - abs(score)
        return NewsSentiment(label=label, score=score, confidence=confidence)

    @staticmethod
    def _parse_entities(raw: Any) -> list[NewsEntity]:
        """解析 entities 字段，受控 type + 最多 5 个。"""
        if not isinstance(raw, list):
            return []
        out: list[NewsEntity] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "") or "").strip()
            etype = str(item.get("type", "") or "").strip().lower()
            if text and etype in ("person", "org", "location"):
                out.append(NewsEntity(text=text, type=etype))
            if len(out) >= _MAX_ENTITIES_PER_ITEM:
                break
        return out

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    def _normalize_title(self, title: str) -> str:
        """截断过长标题，控制 prompt 长度。"""
        t = (title or "").strip()
        if len(t) > self._max_title_chars:
            t = t[: self._max_title_chars] + "…"
        return t

    def _get_sentiment_analyzer(self) -> Any:
        """SentimentAnalyzer 单例（懒加载；模型不可用时由调用方 fail closed）。"""
        if self._sentiment_analyzer is None:
            from strategies.a_shares.sentiment.analyzer import SentimentAnalyzer

            self._sentiment_analyzer = SentimentAnalyzer.from_config("a_shares")
        return self._sentiment_analyzer

    def _check_api_available(self) -> bool:
        """检查 DeepSeek API 是否已配置（Key 环境变量存在）。

        缓存结果避免重复检查。Key 未配置时返回 False，由调用方返回 display-only 结果。
        """
        if self._api_checked:
            return self._api_llm is not None
        self._api_checked = True

        cfg = get_config().get("llm", {}).get(self._api_provider, {})
        api_key = cfg.get("api_key")
        if not api_key:
            logger.info("DeepSeek API Key 未配置，新闻结构化分析不可用")
            return False
        try:
            self._api_llm = get_llm(self._api_provider)
            return True
        except (RuntimeError, ImportError) as exc:
            logger.info("DeepSeek API 客户端初始化失败，新闻结构化分析不可用: %s", exc)
            self._api_llm = None
            return False

    def _get_api_llm(self) -> Any:
        """获取 DeepSeek API 客户端（需先 _check_api_available 通过）。"""
        assert self._api_llm is not None, "API LLM 未初始化，请先调用 _check_api_available"
        return self._api_llm
