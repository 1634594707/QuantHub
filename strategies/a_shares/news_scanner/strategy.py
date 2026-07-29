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
from typing import Any

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

# LLM system prompt（批量分析：一次调用分析多条新闻标题，避免 N 条新闻 N 次调用的延迟）
_BATCH_SENTIMENT_SYSTEM_PROMPT = (
    "你是专业的中国股市情感分析师。"
    "分析给定的一组财经新闻标题对相关 A 股标的的综合情感倾向，"
    "仅返回 JSON（不要有其他文字）："
    '{"sentiment": "正面/负面/中性", "score": 浮点数, '
    '"positive": 整数, "negative": 整数, "neutral": 整数, "reason": "简短理由"}'
    "score 为综合情绪分，范围 -1.0（极度负面）到 1.0（极度正面）。"
    "positive/negative/neutral 为各条新闻的情绪计数，三者之和必须等于新闻总数。"
)
# 原 LLM 调用参数：temperature=0.1；批量分析需更多 token（含计数+理由）
_LLM_TEMPERATURE = 0.1
_LLM_MAX_TOKENS = 400

# 方向阈值（pos_prob 已归一化到 [0,1]；与 sentiment 策略对齐）
_BUY_THRESHOLD = 0.65
_SELL_THRESHOLD = 0.35


@register_strategy(
    StrategyInfo(
        name="news_scanner",
        market="a_shares",
        live_capable=False,
        description="新闻情绪扫描",
    )
)
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
        except Exception:
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
    def _fetch_news(ds, symbol: str | None, limit: int) -> list[News]:
        """安全抓取新闻，失败返回空列表。"""
        try:
            return ds.get_news(symbol=symbol, limit=limit)
        except Exception:
            logger.exception("获取新闻失败: %s", symbol)
            return []

    def _build_signal(
        self,
        symbol: str,
        news_list: list[News],
        timeframe: str,
    ) -> Signal | None:
        """聚合单标的/分组的新闻情绪 → 单个 Signal（单次 LLM 批量调用）。"""
        if not news_list:
            return None

        titles = [n.title or "" for n in news_list if (n.title or "").strip()]
        if not titles:
            return None

        avg_score, dist, dominant_sentiment, reason = self._analyze_batch(titles)
        pos_prob = (avg_score + 1.0) / 2.0
        direction, score_field = self._map_direction(pos_prob)

        # 置信度：主导情绪占比
        dominant = dist.get(dominant_sentiment, 0)
        confidence = dominant / len(titles) if titles else 0.0
        confidence = max(0.0, min(1.0, confidence))

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
                    "news_count": len(titles),
                    "sentiment_dist": dist,
                    "label": _CN_LABEL.get(dominant_sentiment, "中性"),
                    "reason": reason,
                },
            )
        except ValueError as e:
            logger.warning("信号构造失败 %s: %s", symbol, e)
            return None

    def _analyze_batch(self, titles: list[str]) -> tuple[float, dict[str, int], str, str]:
        """批量分析新闻标题（单次 LLM 调用，避免 N 条新闻 N 次调用的延迟）。

        Returns:
            (avg_score, sentiment_dist, dominant_sentiment, reason)
            avg_score ∈ [-1,1]，sentiment_dist 形如 {"Positive": n, ...}，
            dominant_sentiment ∈ {"Positive","Negative","Neutral"}，
            失败时返回 (0.0, 全 0 计数, "Neutral", "")。
        """
        neutral_dist = {"Positive": 0, "Negative": 0, "Neutral": 0}
        if not titles or self._llm is None:
            return 0.0, neutral_dist, "Neutral", ""

        content = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
        messages = [
            {"role": "system", "content": _BATCH_SENTIMENT_SYSTEM_PROMPT},
            {"role": "user", "content": f"共 {len(titles)} 条新闻标题：\n{content}"},
        ]
        try:
            resp = self._llm.chat(
                messages,
                temperature=_LLM_TEMPERATURE,
                max_tokens=_LLM_MAX_TOKENS,
            )
        except Exception:
            logger.exception("LLM 批量情绪分析失败")
            return 0.0, neutral_dist, "Neutral", ""

        return self._parse_batch_sentiment(resp.content, len(titles))

    @staticmethod
    def _parse_batch_sentiment(raw: str, total: int) -> tuple[float, dict[str, int], str, str]:
        """解析 LLM 批量返回的 JSON。

        若 positive/negative/neutral 计数之和不等于 total，退化为「全部归入主导情绪」。
        """
        neutral_dist = {"Positive": 0, "Negative": 0, "Neutral": 0}
        if not raw:
            return 0.0, neutral_dist, "Neutral", ""
        match = re.search(r"\{.*?\}", raw, re.DOTALL)
        if not match:
            return 0.0, neutral_dist, "Neutral", ""
        try:
            obj = json.loads(match.group())
        except json.JSONDecodeError:
            return 0.0, neutral_dist, "Neutral", ""

        try:
            score = max(-1.0, min(1.0, float(obj.get("score", 0.0))))
        except (TypeError, ValueError):
            score = 0.0

        dist = {
            "Positive": max(0, int(obj.get("positive", 0) or 0)),
            "Negative": max(0, int(obj.get("negative", 0) or 0)),
            "Neutral": max(0, int(obj.get("neutral", 0) or 0)),
        }
        # 计数校正：LLM 返回的计数之和与实际新闻数不符时，退化为全部归主导情绪
        if total <= 0 or sum(dist.values()) != total:
            sentiment = _CN_TO_EN.get(obj.get("sentiment", "中性"), "Neutral")
            dist = {"Positive": 0, "Negative": 0, "Neutral": 0}
            dist[sentiment] = max(0, total)

        dominant = max(dist, key=dist.get) if any(dist.values()) else "Neutral"
        reason = str(obj.get("reason", ""))[:200]
        return score, dist, dominant, reason

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
