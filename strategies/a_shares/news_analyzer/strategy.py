"""NewsAnalyzerStrategy：把结构化新闻分析接入 QuantHub 信号总线。

与 ``news_scanner`` 的差异：
    - ``news_scanner`` 走 DeepSeek，仅产出「单标的聚合情绪信号」
    - ``news_analyzer`` 走 FinBERT2 + 配置的 DeepSeek API 结构化分析，
      产出「单标的结构化信号 + 主题/实体分布」

信号 meta 携带：
    - ``topic_dist``：8 主题计数
    - ``sentiment_dist``：{positive, negative, neutral} 计数
    - ``top_entities``：高频实体 [{text, type, count}]
    - ``degraded``：仅完整模型与 LLM 路径成功时为 False
    - ``model`` / ``engine``
    - ``items``：原始结构化分析（前端展开用）
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from core.config import get_config
from core.data_feed import get_data_source
from core.signals import Signal
from strategies.a_shares.news_analyzer.analyzer import NewsAnalyzer
from strategies.a_shares.news_analyzer.schema import NewsBatchResult
from strategies.base import StrategyBase, StrategyInfo, register_strategy

logger = logging.getLogger(__name__)

_SOURCE = "news_analyzer"
_MARKET = "a_shares"
_MARKET_SYMBOL = "A股市场"

# 方向阈值（pos_prob ∈ [0,1]，与 news_scanner 对齐）
_BUY_THRESHOLD = 0.65
_SELL_THRESHOLD = 0.35

# 前端展示用的高频实体上限
_TOP_ENTERS_LIMIT = 10


@register_strategy(
    StrategyInfo(
        name="news_analyzer",
        market="a_shares",
        live_capable=False,
        description="新闻结构化分析（FinBERT2 + 配置 LLM）",
    )
)
class NewsAnalyzerStrategy(StrategyBase):
    """新闻结构化分析策略。

    通过 ``core.data_feed`` 获取新闻，经 ``NewsAnalyzer`` 做四维结构化分析。
    只有模型与 LLM 均完整成功时才产出信号。
    """

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config=config)
        self._analyzer: NewsAnalyzer | None = None  # 懒加载

    # ------------------------------------------------------------------
    # 信号产出
    # ------------------------------------------------------------------
    def produce(
        self,
        symbols: list[str] | None = None,
        limit: int = 20,
        **kwargs: Any,
    ) -> list[Signal]:
        """抓取新闻并产出结构化分析信号。

        Args:
            symbols: 股票代码列表；为空时扫描市场全局新闻，按新闻关联标的分组聚合。
            limit: 每个标的/全局抓取的最大新闻条数（默认 20）。
            **kwargs:
                timeframe: 信号周期（默认 "daily"）
        Returns:
            信号列表（已推入总线）
        """
        symbols = list(symbols) if symbols else []
        timeframe = str(kwargs.get("timeframe", "daily"))
        news_limit = max(1, int(limit))

        analyzer = self._get_analyzer()
        ds = get_data_source(_MARKET)
        signals: list[Signal] = []

        if symbols:
            for symbol in symbols:
                news_list = self._fetch_news(ds, symbol, news_limit)
                sig = self._build_signal(symbol, news_list, analyzer, timeframe)
                if sig is not None:
                    self.publish(sig)
                    signals.append(sig)
        else:
            # 市场全局：按新闻关联标的分组，无标的归入市场桶
            news_list = self._fetch_news(ds, None, news_limit)
            groups: dict[str, list[Any]] = {}
            for n in news_list:
                keys = n.symbols or [_MARKET_SYMBOL]
                for k in keys:
                    groups.setdefault(k, []).append(n)
            for key, group in groups.items():
                sig = self._build_signal(key, group, analyzer, timeframe)
                if sig is not None:
                    self.publish(sig)
                    signals.append(sig)

        return signals

    # ------------------------------------------------------------------
    # 直接暴露批量分析（供 API 端点复用，不走信号总线）
    # ------------------------------------------------------------------
    def analyze(self, symbol: str | None, limit: int) -> NewsBatchResult:
        """供 ``/news/analyze`` 端点调用：抓取新闻 + 结构化分析，返回原始批次结果。"""
        analyzer = self._get_analyzer()
        ds = get_data_source(_MARKET)
        news_list = self._fetch_news(ds, symbol, max(1, int(limit)))
        if not news_list:
            return NewsBatchResult(
                items=[],
                engine="unavailable",
                model=None,
                total=0,
                ok=False,
                degraded_reason="no_news",
                display_only=True,
            )
        return analyzer.analyze_batch(news_list)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _get_analyzer(self) -> NewsAnalyzer:
        if self._analyzer is None:
            self._analyzer = NewsAnalyzer.from_config(_MARKET)
        return self._analyzer

    @staticmethod
    def _fetch_news(ds, symbol: str | None, limit: int) -> list:
        """安全抓取新闻，失败返回空列表。"""
        try:
            return ds.get_news(symbol=symbol, limit=limit)
        except Exception:
            logger.exception("获取新闻失败: %s", symbol)
            return []

    def _build_signal(
        self,
        symbol: str,
        news_list: list,
        analyzer: NewsAnalyzer,
        timeframe: str,
    ) -> Signal | None:
        """聚合单标的/分组的新闻分析 → 单个 Signal。"""
        if not news_list:
            return None
        titles = [n.title or "" for n in news_list if (n.title or "").strip()]
        if not titles:
            return None

        batch = analyzer.analyze_batch(news_list)
        if not batch.ok:
            self._record_unavailable(symbol, batch)
            return None

        # 情绪聚合
        sent_dist = {"positive": 0, "negative": 0, "neutral": 0}
        score_sum = 0.0
        confidence_sum = 0.0
        topic_dist: Counter = Counter()
        entity_counter: Counter = Counter()
        for it in batch.items:
            sent_dist[it.sentiment.label] = sent_dist.get(it.sentiment.label, 0) + 1
            score_sum += it.sentiment.score
            confidence_sum += it.sentiment.confidence
            topic_dist[it.topic] += 1
            for e in it.entities:
                entity_counter[f"{e.text}|{e.type}"] += 1

        n = len(batch.items)
        if n == 0:
            self._record_unavailable(symbol, batch, reason="empty_model_output")
            return None
        avg_score = score_sum / n  # [-1, 1]
        avg_conf = confidence_sum / n  # [0, 1]
        pos_prob = (avg_score + 1.0) / 2.0  # [0, 1]
        direction, score_field = self._map_direction(pos_prob)

        # 主题分布序列化（dict 而非 Counter，JSON 友好）
        topic_dist_dict = dict(topic_dist)
        top_entities = self._top_entities(entity_counter)

        try:
            return Signal(
                symbol=symbol,
                market=_MARKET,
                timeframe=timeframe,
                direction=direction,
                score=score_field,
                confidence=max(0.0, min(1.0, avg_conf)),
                source=_SOURCE,
                tags=["news", batch.engine],
                meta={
                    "news_count": n,
                    "engine": batch.engine,
                    "model": batch.model,
                    "degraded": batch.engine != "semantic+api",
                    "degraded_reason": batch.degraded_reason,
                    "display_only": batch.display_only,
                    "avg_score": round(avg_score, 4),
                    "pos_prob": round(pos_prob, 4),
                    "sentiment_dist": sent_dist,
                    "topic_dist": topic_dist_dict,
                    "top_entities": top_entities,
                    "items": [it.to_dict() for it in batch.items],
                },
            )
        except ValueError as e:
            logger.warning("信号构造失败 %s: %s", symbol, e)
            return None

    def _record_unavailable(
        self,
        symbol: str,
        batch: NewsBatchResult,
        *,
        reason: str | None = None,
    ) -> None:
        """仅保存展示级失败诊断，禁止降级批次进入信号总线。"""
        detail = reason or batch.degraded_reason or "news_model_or_llm_unavailable"
        self.last_report = {
            "kind": "news_analysis",
            "symbol": symbol,
            "status": "unavailable",
            "degraded": True,
            "display_only": True,
            "execution_eligible": False,
            "engine": batch.engine,
            "model": batch.model,
            "news_count": batch.total,
            "reason": detail,
        }
        self.last_signal_rejection = {
            "code": "news_analysis_unavailable",
            "message": "新闻模型或 LLM 不可用/输出不完整，未发布结构化新闻信号。",
            "details": {"source": _SOURCE, "symbol": symbol, "reason": detail},
        }

    @staticmethod
    def _top_entities(counter: Counter) -> list[dict]:
        """取 Top N 高频实体，按 text|type 拆分回字段。"""
        out: list[dict] = []
        for key, cnt in counter.most_common(_TOP_ENTERS_LIMIT):
            text, _, etype = key.partition("|")
            out.append({"text": text, "type": etype or "org", "count": int(cnt)})
        return out

    @staticmethod
    def _map_direction(pos_prob: float) -> tuple[str, float]:
        """正向概率 → (direction, score)。score ∈ [0,1]。"""
        if pos_prob >= _BUY_THRESHOLD:
            return "buy", pos_prob
        if pos_prob <= _SELL_THRESHOLD:
            return "sell", 1.0 - pos_prob
        return "hold", 0.5


def scan(
    symbols: list[str] | None = None,
    limit: int = 20,
    **kwargs: Any,
) -> list[Signal]:
    """scheduler 调用入口：实例化策略并执行新闻结构化分析。"""
    cfg = get_config("a_shares").get("modules", {}).get("news_analyzer", {})
    strategy = NewsAnalyzerStrategy(config=cfg)
    return strategy.produce(symbols=symbols, limit=limit, **kwargs)
