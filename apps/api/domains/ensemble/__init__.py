"""Ensemble 领域：多算法协同预测（/predict/ensemble）。

把技术指标、PA 两阶段 LLM 分析、新闻情绪三类贡献者同屏聚合为加权共识，
并把结果写入 ResearchRun 作为 ``ensemble_output`` 证据。
"""

from __future__ import annotations

from .router import router

__all__ = ["router"]
