"""新闻结构化分析模块（本地 LM Studio，离线隐私）。

策略层入口：
    - ``NewsAnalyzerStrategy`` 通过 ``@register_strategy`` 注册到全局 REGISTRY
    - ``scan()`` 供 ``apps.scheduler`` 调度调用

核心引擎：
    - ``NewsAnalyzer`` 封装 LM Studio 批量调用与降级链
    - ``NewsAnalysis`` / ``NewsBatchResult`` 为统一数据结构

与 ``news_scanner`` 的边界：
    - ``news_scanner`` 走 DeepSeek 远程 API，仅做情绪聚合
    - ``news_analyzer`` 走本地 LM Studio，做 NER/情绪/主题/摘要四维结构化
    - 两者独立，不互相依赖；ensemble 集成时建议二选一（保留 news_analyzer）
"""

from __future__ import annotations

from strategies.a_shares.news_analyzer.analyzer import NewsAnalyzer
from strategies.a_shares.news_analyzer.schema import (
    NewsAnalysis,
    NewsBatchResult,
    NewsEntity,
    NewsEventImpact,
    NewsPriceDirection,
    NewsSentiment,
    NewsTopic,
    SentimentLabel,
)
from strategies.a_shares.news_analyzer.strategy import NewsAnalyzerStrategy, scan

__all__ = [
    "NewsAnalysis",
    "NewsAnalyzer",
    "NewsAnalyzerStrategy",
    "NewsBatchResult",
    "NewsEntity",
    "NewsEventImpact",
    "NewsPriceDirection",
    "NewsSentiment",
    "NewsTopic",
    "SentimentLabel",
    "scan",
]
