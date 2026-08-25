"""A股 FinBERT2 新闻情绪策略。

把原 ``市场情绪系统`` 的情绪分析下沉为 QuantHub 策略插件：

    - 行情/新闻统一走 ``core.data_feed``（不直接 import akshare）
    - 情绪推理走本模块 ``analyzer.SentimentAnalyzer``（FinBERT2 懒加载）
    - 仅在配置的 FinBERT2 成功推理后产出 ``Signal`` 并推入信号总线
    - 回测走 ``core.backtest.EventEngine``
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from core.backtest import BacktestResult, EventEngine
from core.data_feed import get_data_source
from core.signals import Signal
from strategies.a_shares.sentiment.analyzer import SentimentAnalyzer
from strategies.base import StrategyBase, StrategyInfo, register_strategy

logger = logging.getLogger(__name__)

# 情绪 → 方向阈值（源自原 backtest._align_sentiment_to_dates 的信号门槛）
_BUY_THRESHOLD = 0.65
_SELL_THRESHOLD = 0.35
_SOURCE = "sentiment"
_MARKET = "a_shares"


@register_strategy(
    StrategyInfo(
        name="sentiment",
        market="a_shares",
        live_capable=False,
        description="FinBERT2 中文新闻情绪系统",
    )
)
class SentimentStrategy(StrategyBase):
    """新闻情绪策略。

    通过 ``core.data_feed.get_data_source("a_shares")`` 获取新闻，经 FinBERT2
    分析后产出 buy/sell/hold 信号。
    """

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config=config)
        self._analyzer: SentimentAnalyzer | None = None

    # ------------------------------------------------------------------
    # 懒加载分析器
    # ------------------------------------------------------------------

    @property
    def analyzer(self) -> SentimentAnalyzer:
        if self._analyzer is None:
            self._analyzer = SentimentAnalyzer.from_config(_MARKET)
        return self._analyzer

    # ------------------------------------------------------------------
    # 信号产出
    # ------------------------------------------------------------------

    def produce(
        self,
        symbols: list[str] | None = None,
        news_limit: int = 50,
        timeframe: str = "daily",
    ) -> list[Signal]:
        """对给定股票列表抓取新闻并产出情绪信号。

        Args:
            symbols: 股票代码列表（如 ["000001", "600519"]）；为空时返回空列表
            news_limit: 每只股票最大新闻条数（默认 50）
            timeframe: 信号周期（默认 "daily"）
        Returns:
            信号列表（已推入总线）
        """
        symbols = list(symbols) if symbols else []
        if not symbols:
            logger.debug("sentiment.produce 未提供 symbols，跳过")
            return []

        news_limit = int(news_limit)
        timeframe = str(timeframe)
        ds = get_data_source(_MARKET)

        signals: list[Signal] = []
        for symbol in symbols:
            try:
                news_list = ds.get_news(symbol=symbol, limit=news_limit)
            except Exception:
                logger.exception("获取新闻失败: %s", symbol)
                continue
            if not news_list:
                logger.debug("无新闻: %s", symbol)
                continue
            sig = self._build_signal(symbol, news_list, timeframe)
            if sig is not None:
                self.publish(sig)
                signals.append(sig)
        return signals

    def _build_signal(self, symbol: str, news_list: list, timeframe: str) -> Signal | None:
        """聚合新闻情绪 → 单个 Signal。"""
        analyzer = self.analyzer
        scores: list[float] = []
        certainties: list[float] = []
        engines: set[str] = set()
        for n in news_list:
            text = (n.title or "") + "。" + (n.content or "")
            score, certainty, engine = analyzer.analyze(text)
            if score is None or engine != "transformers":
                self._record_unavailable(
                    symbol, len(news_list), getattr(analyzer, "unavailable_reason", None)
                )
                return None
            scores.append(score)
            certainties.append(certainty)
            engines.add(engine)
        if not scores:
            return None
        pos_prob = sum(scores) / len(scores)
        certainty = sum(certainties) / len(certainties) if certainties else 0.0
        engine = min(engines) if engines else "unknown"
        direction, score_field = self._map_direction(pos_prob)

        try:
            return Signal(
                symbol=symbol,
                market=_MARKET,
                timeframe=timeframe,
                direction=direction,
                score=score_field,
                confidence=max(0.0, min(1.0, certainty)),
                source=_SOURCE,
                tags=["news", "finbert2"],
                meta={
                    "pos_prob": round(pos_prob, 4),
                    "engine": engine,
                    "news_count": len(scores),
                    "label": self._label(pos_prob, certainty),
                },
            )
        except ValueError as e:
            logger.warning("信号构造失败 %s: %s", symbol, e)
            return None

    def _record_unavailable(
        self,
        symbol: str,
        news_count: int,
        reason: str | None,
    ) -> None:
        """保留展示级诊断，但不让缺失模型的结果成为信号。"""
        self.last_report = {
            "kind": "news_sentiment",
            "symbol": symbol,
            "news_count": news_count,
            "status": "unavailable",
            "degraded": True,
            "display_only": True,
            "execution_eligible": False,
            "reason": reason or "FinBERT2 不可用或未返回有效推理结果",
        }
        self.last_signal_rejection = {
            "code": "sentiment_model_unavailable",
            "message": "FinBERT2 不可用或推理失败，未发布新闻情绪信号。",
            "details": {"source": _SOURCE, "symbol": symbol, "reason": self.last_report["reason"]},
        }

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

    @staticmethod
    def _label(score: float, certainty: float) -> str:
        """分数转中文标签（源自原 _score_to_label）。"""
        if certainty < 0.4:
            return "中性"
        if score >= 0.85:
            return "极度看好"
        if score >= 0.65:
            return "看好"
        if score >= 0.35:
            return "中性"
        if score >= 0.15:
            return "看空"
        return "极度看空"

    # ------------------------------------------------------------------
    # 回测
    # ------------------------------------------------------------------

    def backtest(self, klines: pd.DataFrame, **kwargs: Any) -> BacktestResult:
        """用 ``core.backtest.EventEngine`` 跑情绪策略回测。

        Args:
            klines: K线 DataFrame（需含 datetime/close 列，可选 symbol 列）
            **kwargs:
                symbol: 标的代码（缺省取 klines['symbol'].iloc[0]）
                sentiment_score: 预计算的正向概率；未传则抓新闻现算
                news_limit: 抓新闻条数（默认 50）
                initial_capital: 初始资金（默认 100000）
                commission: 佣金费率（默认 0.0003）
        """
        if klines is None or klines.empty:
            return BacktestResult.empty(engine="event")

        symbol = kwargs.get("symbol") or (
            klines["symbol"].iloc[0] if "symbol" in klines.columns else "unknown"
        )

        # 情绪分数：优先用调用方传入，否则抓新闻现算
        sentiment_score = kwargs.get("sentiment_score")
        if sentiment_score is None:
            sentiment_score = self._fetch_symbol_score(symbol, int(kwargs.get("news_limit", 50)))
        if sentiment_score is None:
            self._record_unavailable(
                str(symbol), 0, getattr(self.analyzer, "unavailable_reason", None)
            )
            return BacktestResult.empty(engine="event")
        try:
            sentiment_score = float(sentiment_score)
        except (TypeError, ValueError):
            logger.warning("无效的 sentiment_score，拒绝使用替代中性分数")
            return BacktestResult.empty(engine="event")
        direction, _ = self._map_direction(sentiment_score)

        initial_capital = float(kwargs.get("initial_capital", 100000))
        commission = float(kwargs.get("commission", 0.0003))
        engine = EventEngine(initial_capital=initial_capital, commission=commission)

        def on_bar(bar: pd.Series, ctx) -> None:
            close = float(bar["close"])
            ts = bar.get("datetime")
            if direction == "buy" and ctx.position == 0:
                # A股整手（100 股）下单
                qty = int(ctx.cash / close / 100) * 100
                if qty > 0:
                    ctx.buy(close, qty, ts)
            elif direction == "sell" and ctx.position > 0:
                ctx.sell(close, ctx.position, ts)

        result = engine.run(klines, on_bar)
        # 直接返回类型化 BacktestResult（含逐根 equity_curve），由 API 负责序列化。
        return result

    def _fetch_symbol_score(self, symbol: str, news_limit: int) -> float | None:
        """抓取新闻并聚合出正向概率（回测用）。"""
        try:
            ds = get_data_source(_MARKET)
            news_list = ds.get_news(symbol=symbol, limit=news_limit)
        except Exception:
            logger.exception("回测取新闻失败: %s", symbol)
            return None
        if not news_list:
            return None
        analyzer = self.analyzer
        scores: list[float] = []
        for news in news_list:
            score, _, engine = analyzer.analyze((news.title or "") + "。" + (news.content or ""))
            if score is None or engine != "transformers":
                return None
            scores.append(score)
        return sum(scores) / len(scores) if scores else None
