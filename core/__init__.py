"""QuantHub 统一底座 (core)

子模块:
    - data_feed : 多源行情/公告接入 (akshare/东财/OKX-ccxt) + SQLite 缓存
    - signals   : 统一 Signal 数据类 + 轻量总线
    - alert     : 企微 / Webhook / Telegram 通知
    - llm       : DeepSeek/OpenAI 兼容客户端，支持本地模型
    - backtest  : 网格回测 + backtrader 集成 + 通用事件驱动框架
    - config    : YAML 配置合并、环境变量注入与 schema 迁移
"""

from __future__ import annotations

__version__ = "0.2.0"

__all__ = ["__version__"]
