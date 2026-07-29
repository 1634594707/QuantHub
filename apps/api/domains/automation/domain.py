"""自动化领域模型：调度任务视图。"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class ScheduledJob:
    """调度任务视图（只读）。"""

    name: str
    market: str
    cron: str
    func_name: str
    custom: bool
    next_run: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)
