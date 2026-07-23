"""策略插件基类。

所有策略模块通过实现 StrategyBase 挂载到 QuantHub，互不污染。
策略生命周期:
    1. init()      : 加载配置、依赖
    2. produce()   : 产出 Signal（推入信号总线）
    3. backtest()  : 回测（可选）
    4. live_tick() : 实盘 tick（默认 no-op，需 live 模式）

策略注册:
    通过 @register_strategy 装饰器注册到 REGISTRY，由 dispatcher/scheduler 调用。
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from core.signals import Signal, get_bus

logger = logging.getLogger(__name__)


@dataclass
class StrategyInfo:
    """策略元信息。"""

    name: str  # 唯一名（如 sentiment）
    market: str  # a_shares | crypto | ai_analysis
    version: str = "0.1.0"
    live_capable: bool = False  # 是否支持实盘
    description: str = ""


class StrategyBase(abc.ABC):
    """策略插件抽象基类。"""

    info: StrategyInfo

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}
        self._bus = get_bus()

    @abc.abstractmethod
    def produce(self, **kwargs: Any) -> list[Signal]:
        """产出信号并推入总线，返回信号列表。"""
        raise NotImplementedError

    def backtest(self, klines: pd.DataFrame, **kwargs: Any) -> BacktestResult:
        """可选回测。默认返回「未实现」空结果（统一 BacktestResult 契约）。

        子类若支持回测，应返回 ``core.backtest.BacktestResult``；
        不支持时务必返回 ``BacktestResult.empty()``，禁止 ``raise NotImplementedError``
        （否则统一的回测调用器会因单个策略崩溃）。
        """
        from core.backtest.engine import BacktestResult

        return BacktestResult.empty(engine="none")

    def live_tick(self, **kwargs: Any) -> dict | None:
        """实盘 tick 回调。默认 no-op。"""
        return None

    def is_enabled(self) -> bool:
        """是否启用（读取 config.modules.<name>.enabled）。"""
        return bool(self.config.get("enabled", False))

    def is_live(self) -> bool:
        """是否实盘模式（需 enable + live 双开关 + 全局 live_trading）。"""
        from core.config import get_config

        global_live = get_config().get("live_trading", False)
        return global_live and bool(self.config.get("live", False))

    def publish(self, signal: Signal) -> None:
        """便捷方法：发布信号到总线。"""
        self._bus.publish(signal)


# 策略注册表
_REGISTRY: dict[str, type[StrategyBase]] = {}


def register_strategy(info: StrategyInfo):
    """装饰器：注册策略类。

    用法:
        @register_strategy(StrategyInfo(name="sentiment", market="a_shares"))
        class SentimentStrategy(StrategyBase): ...
    """

    def decorator(cls: type[StrategyBase]) -> type[StrategyBase]:
        cls.info = info
        _REGISTRY[info.name] = cls
        logger.debug("注册策略: %s", info.name)
        return cls

    return decorator


def get_strategy(name: str, config: dict | None = None) -> StrategyBase:
    """按名实例化策略。"""
    if name not in _REGISTRY:
        raise KeyError(f"未注册的策略: {name}（已注册: {list(_REGISTRY)}）")
    return _REGISTRY[name](config=config)


def list_strategies() -> dict[str, StrategyInfo]:
    """列出所有已注册策略。"""
    return {name: cls.info for name, cls in _REGISTRY.items()}
