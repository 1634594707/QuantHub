# -*- coding: utf-8 -*-
"""A股新闻情绪扫描策略。

把原 ``trading-master/01-News_Sentiment_Scanner`` 下沉为 QuantHub 策略插件：

    - 新闻获取统一走 ``core.data_feed.get_data_source("a_shares").get_news()``
      （不再直接依赖东方财富爬虫 / curl_cffi）
    - 情绪分析统一走 ``core.llm.get_llm()``（复用 DeepSeek/OpenAI 兼容客户端，
      不再重新实现 scanner/ai_client.py）
    - 按情绪分数产出 ``Signal`` 并推入信号总线
    - ``scan()`` 供 ``apps.scheduler`` 调度调用

原 ``scanner/sentiment.py`` 的 system prompt 与调用参数已提取为模块常量。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from core.config import get_config
from core.data_feed import News, get_data_source
from core.llm import get_llm
from core.signals import Signal
from strategies.base import StrategyBase, StrategyInfo, register_strategy

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# 常量（提取自原 scanner/sentiment.py 的 prompt 与调用参数）
# ----------------------------------------------------------------------
_SOURCE = "news_scanner"
_MARKET = "a_shares"

# 无标的维度时，市场全局情绪信号使用的占位标的
_MARKET_SYMBOL = "A股市场"

# 中文情绪标签 ↔ 英文枚举（源自原 sentiment.py 的 cn_to_en / CN_LABEL）
_CN_TO_EN = {"正面": "Positive", "负面": "Negative", "中性": "Neutral"}
_CN_LABEL = {"Positive": "正面", "Negative": "负面", "Neutral": "中性"}

# LLM system prompt（原样提取自 scanner/sentiment.py:analyze_sentiment）
_SENTIMENT_SYSTEM_PROMPT = (
    "你是专业的中国股市情感分析师。"
    "分析以下财经新闻对 A 股市场的情感倾向，"
    "仅返回 JSON（不要有其他文字）："
    '{"sentiment": "正面/负面/中性", "score": 浮点数, "reason": "简短理由"}'
    "score 范围：-1.0（极度负面）到 1.0（极度正面）。"
)
# 原 LLM 调用参数：temperature=0.1, max_tokens=150
_LLM_TEMPERATURE = 0.1
_LLM_MAX_TOKENS = 150

# 方向阈值（pos_prob 已归一化到 [0,1]；与 sentiment 策略对齐）
_BUY_THRESHOLD = 0.65
_SELL_THRESHOLD = 0.35


@register_strategy(StrategyInfo(
    name="news_scanner",
    market="a_shares",
    live_capable=False,
    description="新闻情绪扫描",
))
class NewsScannerStrategy(StrategyBase):
    """新闻情绪扫描策略。

    通过 ``core.data_feed`` 获取新闻，经 ``core.llm`` 统一客户端做情绪分析，
    按情绪分数产出 buy/sell/hold 信号。
    """

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config=config)
        self._llm = None  # 懒加载（首次 produce 时初始化）

    # ------------------------------------------------------------------
    # 信号产出
    # ------------------------------------------------------------------

    def produce(
        self,
        symbols: list[str] | None = None,
        limit: int = 50,
        **kwargs: Any,
    ) -> list[Signal]:
        """抓取新闻并产出情绪信号。

        Args:
            symbols: 股票代码列表（如 ["000001", "600519"]）；为空时扫描
                     市场全局新闻，并按新闻关联标的分组聚合。
            limit: 每个标的/全局抓取的最大新闻条数（默认 50）。
            **kwargs:
                timeframe: 信号周期（默认 "daily"）
        Returns:
            信号列表（已推入总线）
        """
        symbols = list(symbols) if symbols else []
        timeframe = str(kwargs.get("timeframe", "daily"))
        news_limit = int(limit)

        # 复用统一 LLM 客户端（不重新实现 ai_client）
        try:
            self._llm = get_llm()
        except Exception:  # noqa: BLE001
            logger.exception("LLM 客户端初始化失败，news_scanner 终止")
            return []

        ds = get_data_source(_MARKET)
        signals: list[Signal] = []

        if symbols:
            # 按标的逐个扫描
            for symbol in symbols:
                news_list = self._fetch_news(ds, symbol, news_limit)
                sig = self._build_signal(symbol, news_list, timeframe)
                if sig is not None:
                    self.publish(sig)
                    signals.append(sig)
        else:
            # 市场全局新闻：按新闻关联标的分组，无标的归入市场桶
            news_list = self._fetch_news(ds, None, news_limit)
            groups: dict[str, list[News]] = {}
            for n in news_list:
                keys = n.symbols or [_MARKET_SYMBOL]
                for k in keys:
                    groups.setdefault(k, []).append(n)
            for key, group in groups.items():
                sig = self._build_signal(key, group, timeframe)
                if sig is not None:
                    self.publish(sig)
                    signals.append(sig)

        return signals

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_news(ds, symbol: Optional[str], limit: int) -> list[News]:
        """安全抓取新闻，失败返回空列表。"""
        try:
            return ds.get_news(symbol=symbol, limit=limit)
        except Exception:  # noqa: BLE001
            logger.exception("获取新闻失败: %s", symbol)
            return []

    def _build_signal(
        self,
        symbol: str,
        news_list: list[News],
        timeframe: str,
    ) -> Optional[Signal]:
        """聚合单标的/分组的新闻情绪 → 单个 Signal。"""
        if not news_list:
            return None

        analyses: list[tuple[float, str, str]] = []
        for n in news_list:
            score, sentiment, reason = self._analyze(n.title or "")
            analyses.append((score, sentiment, reason))
        if not analyses:
            return None

        # 平均情绪分（[-1,1]）→ 归一化正向概率 [0,1]
        avg_score = sum(a[0] for a in analyses) / len(analyses)
        pos_prob = (avg_score + 1.0) / 2.0
        direction, score_field = self._map_direction(pos_prob)

        # 置信度：主导情绪占比
        dist = {"Positive": 0, "Negative": 0, "Neutral": 0}
        for a in analyses:
            dist[a[1]] += 1
        dominant = max(dist.values())
        confidence = dominant / len(analyses) if analyses else 0.0
        confidence = max(0.0, min(1.0, confidence))
        dominant_sentiment = max(dist, key=dist.get)

        try:
            return Signal(
                symbol=symbol,
                market=_MARKET,
                timeframe=timeframe,
                direction=direction,
                score=score_field,
                confidence=confidence,
                source=_SOURCE,
                tags=["news", "llm"],
                meta={
                    "avg_score": round(avg_score, 4),
                    "pos_prob": round(pos_prob, 4),
                    "news_count": len(analyses),
                    "sentiment_dist": dist,
                    "label": _CN_LABEL.get(dominant_sentiment, "中性"),
                },
            )
        except ValueError as e:
            logger.warning("信号构造失败 %s: %s", symbol, e)
            return None

    def _analyze(self, text: str) -> tuple[float, str, str]:
        """调用统一 LLM 客户端分析单条新闻标题。

        Returns:
            (score, sentiment, reason)，score ∈ [-1,1]，
            sentiment ∈ {"Positive","Negative","Neutral"}，
            失败时返回 (0.0, "Neutral", "")。
        """
        if not text or not text.strip():
            return 0.0, "Neutral", ""
        if self._llm is None:
            return 0.0, "Neutral", ""

        messages = [
            {"role": "system", "content": _SENTIMENT_SYSTEM_PROMPT},
            {"role": "user", "content": f"新闻：{text}"},
        ]
        try:
            resp = self._llm.chat(
                messages,
                temperature=_LLM_TEMPERATURE,
                max_tokens=_LLM_MAX_TOKENS,
            )
        except Exception:  # noqa: BLE001
            logger.exception("LLM 情绪分析失败")
            return 0.0, "Neutral", ""

        return self._parse_sentiment(resp.content)

    @staticmethod
    def _parse_sentiment(raw: str) -> tuple[float, str, str]:
        """解析 LLM 返回的 JSON（沿用原 sentiment.py 的正则提取方式）。"""
        if not raw:
            return 0.0, "Neutral", ""
        match = re.search(r"\{.*?\}", raw, re.DOTALL)
        if not match:
            return 0.0, "Neutral", ""
        try:
            obj = json.loads(match.group())
        except json.JSONDecodeError:
            return 0.0, "Neutral", ""

        try:
            score = float(obj.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        score = max(-1.0, min(1.0, score))

        sentiment = _CN_TO_EN.get(obj.get("sentiment", "中性"), "Neutral")
        reason = str(obj.get("reason", ""))[:200]
        return score, sentiment, reason

    @staticmethod
    def _map_direction(pos_prob: float) -> tuple[str, float]:
        """正向概率 → (direction, score)。

        score 表示「方向置信强度」：买入用正概率，卖出用 1-正概率，观望取 0.5。
        """
        if pos_prob >= _BUY_THRESHOLD:
            return "buy", pos_prob
        if pos_prob <= _SELL_THRESHOLD:
            return "sell", 1.0 - pos_prob
        return "hold", 0.5


def scan(
    symbols: list[str] | None = None,
    limit: int = 50,
    **kwargs: Any,
) -> list[Signal]:
    """scheduler 调用入口：实例化策略并执行新闻情绪扫描。

    Args:
        symbols: 股票代码列表；为空时扫描市场全局新闻。
        limit: 抓取新闻条数（默认 50）。
    Returns:
        当次扫描产出的信号列表。
    """
    cfg = get_config("a_shares").get("modules", {}).get("news_scanner", {})
    strategy = NewsScannerStrategy(config=cfg)
    return strategy.produce(symbols=symbols, limit=limit, **kwargs)
