# -*- coding: utf-8 -*-
"""统一 Signal 数据类与轻量总线。

各策略 ``produce Signal``；dashboard / dispatcher ``consume``。
"""
from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Callable, Iterable


@dataclass
class Signal:
    """统一信号对象。

    所有策略产出的信号都封装为 Signal，供 dispatcher 聚合与路由。
    """
    symbol: str
    market: str                         # "a_shares" | "crypto"
    timeframe: str                      # "daily" / "1h" / "4h" ...
    direction: str                      # "buy" | "sell" | "hold"
    score: float                        # 0~1，方向置信强度
    confidence: float                   # 0~1，模型/规则置信度
    source: str                         # 模块名（sentiment/supertrend/...）
    tags: list[str] = field(default_factory=list)
    ts: datetime = field(default_factory=datetime.now)
    meta: dict = field(default_factory=dict)   # 模块特有附加信息

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score 必须在 [0,1]，得到 {self.score}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence 必须在 [0,1]，得到 {self.confidence}")
        if self.direction not in ("buy", "sell", "hold"):
            raise ValueError(f"direction 必须是 buy/sell/hold，得到 {self.direction}")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        return d


# 订阅者签名: (signal) -> None
SignalHandler = Callable[[Signal], None]


class SignalBus:
    """进程内轻量信号总线（线程安全）。

    高级特性：
        - 按 source / market / direction 过滤订阅
        - 同步派发（生产者线程内调用订阅者）；如需异步，订阅者可自行入队
    """

    def __init__(self) -> None:
        self._handlers: list[tuple[SignalHandler, dict]] = []
        self._lock = threading.RLock()
        self._history: list[Signal] = []
        self._history_limit = 1000

    def subscribe(
        self,
        handler: SignalHandler,
        *,
        source: str | None = None,
        market: str | None = None,
        direction: str | None = None,
    ) -> None:
        """订阅信号，可按 source/market/direction 过滤。"""
        with self._lock:
            self._handlers.append((handler, {
                "source": source, "market": market, "direction": direction,
            }))

    def publish(self, signal: Signal) -> None:
        """发布信号，匹配的订阅者被同步调用。"""
        with self._lock:
            self._history.append(signal)
            if len(self._history) > self._history_limit:
                self._history = self._history[-self._history_limit:]
            handlers = list(self._handlers)
        for handler, flt in handlers:
            if flt["source"] and signal.source != flt["source"]:
                continue
            if flt["market"] and signal.market != flt["market"]:
                continue
            if flt["direction"] and signal.direction != flt["direction"]:
                continue
            try:
                handler(signal)
            except Exception:  # noqa: BLE001 - 订阅者异常不阻断总线
                import logging
                logging.getLogger(__name__).exception("信号订阅者执行失败: %s", handler)

    def history(
        self,
        *,
        source: str | None = None,
        market: str | None = None,
        limit: int | None = None,
    ) -> list[Signal]:
        """读取历史信号（按过滤条件）。"""
        with self._lock:
            sigs = list(self._history)
        if source:
            sigs = [s for s in sigs if s.source == source]
        if market:
            sigs = [s for s in sigs if s.market == market]
        if limit:
            sigs = sigs[-limit:]
        return sigs

    def clear_history(self) -> None:
        with self._lock:
            self._history.clear()


# 默认全局总线（单例）
_default_bus: SignalBus | None = None
_default_bus_lock = threading.Lock()


def get_bus() -> SignalBus:
    """获取全局信号总线单例。"""
    global _default_bus
    if _default_bus is None:
        with _default_bus_lock:
            if _default_bus is None:
                _default_bus = SignalBus()
    return _default_bus
