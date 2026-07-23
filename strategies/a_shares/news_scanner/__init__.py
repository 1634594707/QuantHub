"""A股新闻情绪扫描 策略模块。

把原 ``trading-master/01-News_Sentiment_Scanner`` 下沉为 QuantHub 策略插件：
    - 新闻获取走 ``core.data_feed``（不直接依赖东方财富爬虫）
    - 情绪分析走 ``core.llm`` 统一客户端（不重新实现 ai_client）
    - 按情绪产出 ``Signal`` 并推入信号总线

导出:
    - NewsScannerStrategy : 策略类（继承 StrategyBase，已 @register_strategy）
    - scan                : 供 apps.scheduler 调用的扫描入口
"""

from __future__ import annotations

from strategies.a_shares.news_scanner.strategy import NewsScannerStrategy, scan

__all__ = ["NewsScannerStrategy", "scan"]
