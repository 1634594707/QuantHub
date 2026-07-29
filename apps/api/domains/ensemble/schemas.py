"""Ensemble 请求/响应 schema。

与前端 ``web/src/api/types.ts`` 的 ``EnsembleResp / EnsembleContributor /
EnsembleConsensus`` 1:1 对齐；后端用 dict 返回，pydantic 仅校验请求体。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class EnsembleRequest(BaseModel):
    """协同预测请求（POST /predict/ensemble）。"""

    symbol: str = Field(..., min_length=1, description="标的代码（必填）")
    market: str = Field(default="a_shares")
    timeframe: str = Field(default="1d")
    limit: int = Field(default=200, ge=10, le=1000, description="K 线根数")
    research_run_id: str | None = Field(default=None, description="复用已有研究运行 ID")

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("标的代码不能为空")
        return normalized
