"""策略实验室领域模型。"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class StrategyDefinition:
    """命名化的策略定义（绑定到 strategies 注册表中的 strategy_key）。"""

    id: str
    name: str
    strategy_key: str
    market: str = "a_shares"
    description: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0
    archived_at: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StrategyVersion:
    """策略版本：参数集 + 代码哈希 + 变更日志。"""

    id: str
    definition_id: str
    version: str
    params: dict[str, Any] = field(default_factory=dict)
    code_hash: str = ""
    changelog: str = ""
    created_at: float = 0.0
    archived_at: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Experiment:
    """实验：定义 + 版本 + 标的 + 周期。"""

    id: str
    definition_id: str
    instrument_id: str
    symbol: str
    market: str
    timeframe: str = "1d"
    version_id: str | None = None
    research_run_id: str | None = None
    status: str = "pending"
    params: dict[str, Any] = field(default_factory=dict)
    note: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    archived_at: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BacktestRun:
    """回测运行：完整结果（权益曲线 / 成交 / 指标 / 数据快照 / 种子）。"""

    id: str
    experiment_id: str
    symbol: str
    market: str
    timeframe: str = "1d"
    params: dict[str, Any] = field(default_factory=dict)
    data_snapshot: dict[str, Any] = field(default_factory=dict)
    initial_capital: float = 100_000.0
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    seed: str | None = None
    status: str = "succeeded"
    error: str = ""
    started_at: float = 0.0
    finished_at: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def code_hash_of(source: str) -> str:
    """计算策略源码哈希（用于版本追踪可复现性）。"""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
