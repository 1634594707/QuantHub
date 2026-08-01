"""NewsAnalyzer：语义情绪分析 + 可选 API 结构化增强。

设计原则（从 LM Studio 改造为语义模型优先）：

    1. **本地兜底**：始终先用 ``SentimentAnalyzer``（资金流向规则 → FinBERT2 → snownlp →
       关键词）生成可离线工作的基础情绪
    2. **API 可选增强**：当 DeepSeek API Key 已配置时，调用 API 做财经情绪、NER、主题与
       摘要增强；API 成功返回的情绪优先，本地结果仅在字段缺失或调用失败时兜底
    3. **批量调用**：API 增强一次 prompt 分析 N 条标题，避免 N 条 N 次的延迟
    4. **容错解析**：剥 markdown fence → json.loads → 提取数组 → 单条缺字段降级
    5. **优雅降级**：API 调用失败时仅丢结构化字段，情绪分析不受影响

不改动 ``news_scanner`` 的 DeepSeek 路径，两模块独立。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from core.config import get_config
from core.data_feed.base import News
from core.llm import get_llm
from core.news_event_research import extract_event_semantics
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
    NewsAnalysis,
    NewsBatchResult,
    NewsEntity,
    NewsEventExtraction,
    NewsEventImpact,
    NewsPriceDirection,
    NewsSentiment,
    coerce_sentiment_label,
    coerce_topic,
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
    """新闻结构化分析器（语义情绪 + 可选 API 增强）。

    优先级链：
        1. SentimentAnalyzer.analyze(title) → 本地兜底情绪  [始终执行]
        2. 若 DeepSeek API 可用 → 调用 API 对批次做财经情绪/NER/主题/摘要增强  [可选]
        3. API 不可用/失败 → entities=[], topic=unknown, summary=title[:60]
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
        """始终可用（SentimentAnalyzer 至少有关键词降级）。"""
        return True

    def reset_availability(self) -> None:
        """清除 API 客户端缓存（前端「刷新」按钮调用）。"""
        self._api_llm = None
        self._api_checked = False

    def health(self) -> dict[str, Any]:
        """返回健康状态字典（供 ``/news/health`` 端点）。"""
        sa = self._get_sentiment_analyzer()
        # 触发一次 analyze 以确定实际引擎（transformers/snownlp/keyword）
        sa._ensure_loaded()  # noqa: SLF001 触发懒加载以读取 _engine
        sentiment_engine = sa._engine or "keyword"  # noqa: SLF001

        api_ok = self._check_api_available()
        api_cfg = get_config().get("llm", {}).get(self._api_provider, {})
        return {
            "ok": True,
            "engine": sentiment_engine,
            "api_enhancement": api_ok,
            "api_provider": self._api_provider,
            "model": api_cfg.get("model") if api_ok else None,
        }

    # ------------------------------------------------------------------
    # 单条 / 批量分析
    # ------------------------------------------------------------------
    def analyze_one(self, news: News) -> NewsAnalysis:
        """分析单条新闻（内部走批量 1 条路径，便于复用解析与降级）。"""
        result = self.analyze_batch([news])
        return result.items[0]

    def analyze_batch(self, news_list: list[News], use_api: bool = True) -> NewsBatchResult:
        """批量分析新闻。

        Args:
            use_api: 是否启用 API 结构化增强（False 时仅做语义情绪分析，不消耗 API 额度）。
                即使 API Key 已配置，用户也可经此开关关闭增强。

        Returns:
            ``NewsBatchResult``，始终包含情绪分析；API 可用且 ``use_api=True`` 时附带结构化字段。
        """
        if not news_list:
            return NewsBatchResult(
                items=[],
                engine="keyword",
                model=None,
                total=0,
                ok=False,
                degraded_reason="empty_input",
            )

        sa = self._get_sentiment_analyzer()
        api_ok = self._check_api_available() if use_api else False
        if use_api and not api_ok:
            logger.info("API 增强已启用但 Key 未配置/不可用，仅返回情绪分析")
        items: list[NewsAnalysis] = []
        any_enhanced = False
        degraded_reason = "api_disabled" if not use_api else "api_unavailable"

        # 1. 本地兜底情绪（始终执行）：API 失败或缺字段时仍可返回结果
        sentiment_results: list[tuple[float, float, str]] = []
        for news in news_list:
            try:
                pos_prob, certainty, eng = sa.analyze(news.title or "")
            except Exception as exc:  # noqa: BLE001 - optional analyzer failures degrade to neutral
                logger.warning("SentimentAnalyzer 异常，降级为中性: %s", exc)
                pos_prob, certainty, eng = 0.5, 0.0, "keyword"
            sentiment_results.append((pos_prob, certainty, eng))

        # 2. API 结构化增强（可选）：批量调用 DeepSeek 做财经情绪/NER/主题/摘要
        api_objs: list[dict | None] = [None] * len(news_list)
        if api_ok:
            try:
                api_objs, model_name = self._api_enhance_batch(news_list)
                any_enhanced = any(o is not None for o in api_objs)
                if not any_enhanced:
                    degraded_reason = "api_invalid_response"
            except Exception as exc:  # noqa: BLE001 - optional API failures use local analysis
                logger.warning("API 增强失败，仅返回情绪分析: %s", exc)
                api_objs = [None] * len(news_list)
                model_name = None
                degraded_reason = "api_call_failed"
        else:
            model_name = None

        # 3. 合并：API 情绪优先，SentimentAnalyzer 兜底
        for i, news in enumerate(news_list):
            pos_prob, certainty, eng = sentiment_results[i]
            obj = api_objs[i] if i < len(api_objs) else None
            items.append(
                self._build_analysis(
                    news=news,
                    pos_prob=pos_prob,
                    certainty=certainty,
                    sentiment_engine=eng,
                    obj=obj,
                    enhanced=obj is not None,
                    model=model_name if obj is not None else None,
                )
            )

        engine = "semantic+api" if any_enhanced else "semantic"
        return NewsBatchResult(
            items=items,
            engine=engine,
            model=model_name,
            total=len(news_list),
            ok=True,
            degraded_reason=None if any_enhanced else degraded_reason,
        )

    # ------------------------------------------------------------------
    # API 增强调用
    # ------------------------------------------------------------------
    def _api_enhance_batch(self, news_list: list[News]) -> tuple[list[dict | None], str | None]:
        """调用 DeepSeek API 批量分析 NER/主题/摘要，返回 dict 列表与模型名。

        失败抛异常，由调用方降级为纯情绪分析。
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
        """容错解析 LLM 输出为 dict 列表。

        步骤：剥 markdown fence → json.loads → 提取数组片段 → 长度对齐。
        对齐策略：多于 expected_n 截断；少于则补 None。
        """
        if not raw:
            return [None] * expected_n

        text = raw.strip()
        # 剥 ```json ... ``` / ``` ... ``` fence
        fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()

        # 尝试直接解析
        parsed: Any = None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # 提取首个 JSON 数组片段
            arr_match = re.search(r"\[.*\]", text, re.DOTALL)
            if arr_match:
                try:
                    parsed = json.loads(arr_match.group())
                except json.JSONDecodeError:
                    parsed = None

        if not isinstance(parsed, list):
            # 单对象兜底（LLM 偶尔只返回一条）
            if isinstance(parsed, dict):
                parsed = [parsed]
            else:
                return [None] * expected_n

        # 长度对齐
        if len(parsed) > expected_n:
            parsed = parsed[:expected_n]
        elif len(parsed) < expected_n:
            parsed = parsed + [None] * (expected_n - len(parsed))
        # 元素类型校验
        return [p if isinstance(p, dict) else None for p in parsed]

    @staticmethod
    def _align(batch: list[News], objs: list[dict]) -> list[tuple[News, dict | None]]:
        """按位置对齐 news 与解析结果。"""
        return list(zip(batch, objs, strict=False))

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
            sentiment_engine: SentimentAnalyzer 实际引擎（transformers/snownlp/keyword）
            obj: API 增强返回的 dict（None 表示未增强）
            enhanced: 是否成功获得 API 增强
        """
        # 本地兜底情绪
        score = pos_prob * 2.0 - 1.0  # [0,1] -> [-1,1]
        if pos_prob >= _POS_THRESHOLD:
            label = "positive"
        elif pos_prob <= _NEG_THRESHOLD:
            label = "negative"
        else:
            label = "neutral"
        sentiment = NewsSentiment(label=label, score=score, confidence=certainty)

        # API 增强成功时与本地财经引擎融合。明确资金规则优先；FinBERT2 与
        # DeepSeek 等权融合；SnowNLP/关键词属于弱兜底，由 API 结果覆盖。
        if obj is not None and obj.get("sentiment"):
            api_sentiment = self._parse_api_sentiment(obj)
            sentiment = self._merge_sentiments(
                local=sentiment,
                api=api_sentiment,
                local_engine=sentiment_engine,
            )

        # 结构化字段（API 增强时来自 LLM；否则空/unknown/title）
        if obj is not None:
            topic = coerce_topic(obj.get("topic"))
            entities = self._parse_entities(obj.get("entities"))
            summary = str(obj.get("summary", "") or "").strip()
            if len(summary) > _MAX_SUMMARY_CHARS:
                summary = summary[:_MAX_SUMMARY_CHARS]
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
        """解析并校准 API 情绪，保证标签与分数方向一致。"""
        label = coerce_sentiment_label(obj.get("sentiment"))
        default_score = {"positive": 0.5, "negative": -0.5, "neutral": 0.0}[label]
        try:
            score = float(obj.get("sentiment_score", default_score))
        except (TypeError, ValueError):
            score = default_score
        score = max(-1.0, min(1.0, score))

        if label == "positive" and score <= 0:
            score = max(0.35, abs(score))
        elif label == "negative" and score >= 0:
            score = -max(0.35, abs(score))
        elif label == "neutral":
            score = max(-0.34, min(0.34, score))

        confidence = abs(score) if label != "neutral" else 1.0 - abs(score)
        return NewsSentiment(label=label, score=score, confidence=confidence)

    @staticmethod
    def _merge_sentiments(
        local: NewsSentiment,
        api: NewsSentiment,
        local_engine: str,
    ) -> NewsSentiment:
        """融合本地与 API 情绪，按引擎可靠度选择策略。"""
        if local_engine == "financial_rules":
            return local
        if local_engine != "transformers":
            return api

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
            if isinstance(item, dict):
                text = str(item.get("text", "") or "").strip()
                etype = str(item.get("type", "") or "").strip().lower()
                if etype not in ("person", "org", "location"):
                    etype = "org"  # 兜底为 org（最常见的财经实体）
                if text:
                    out.append(NewsEntity(text=text, type=etype))
            elif isinstance(item, str) and item.strip():
                # 退化：纯字符串实体，默认 org
                out.append(NewsEntity(text=item.strip(), type="org"))
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
        """SentimentAnalyzer 单例（懒加载，始终可用）。"""
        if self._sentiment_analyzer is None:
            from strategies.a_shares.sentiment.analyzer import SentimentAnalyzer

            self._sentiment_analyzer = SentimentAnalyzer.from_config("a_shares")
        return self._sentiment_analyzer

    def _check_api_available(self) -> bool:
        """检查 DeepSeek API 是否已配置（Key 环境变量存在）。

        缓存结果避免重复检查。Key 未配置时返回 False，不抛异常。
        """
        if self._api_checked:
            return self._api_llm is not None
        self._api_checked = True

        cfg = get_config().get("llm", {}).get(self._api_provider, {})
        api_key = cfg.get("api_key")
        if not api_key:
            logger.info("DeepSeek API Key 未配置，跳过结构化增强（仅情绪分析）")
            return False
        try:
            self._api_llm = get_llm(self._api_provider)
            return True
        except (RuntimeError, ImportError) as exc:
            logger.info("DeepSeek API 客户端初始化失败，跳过增强: %s", exc)
            self._api_llm = None
            return False

    def _get_api_llm(self) -> Any:
        """获取 DeepSeek API 客户端（需先 _check_api_available 通过）。"""
        assert self._api_llm is not None, "API LLM 未初始化，请先调用 _check_api_available"
        return self._api_llm
