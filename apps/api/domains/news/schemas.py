"""News analysis request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class NewsAnalyzeRequest(BaseModel):
    """新闻分析请求（POST /news/analyze）。"""

    symbol: str = Field(
        ..., min_length=1, description="股票代码（必填，禁止空输入回退到全市场扫描）"
    )
    market: str = Field(default="a_shares")
    timeframe: str = Field(default="1d")
    limit: int = Field(default=20, ge=1, le=100)
    use_api: bool = Field(default=True, description="是否启用 API 结构化增强")
    research_run_id: str | None = Field(default=None, description="复用已有研究运行 ID")

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("股票代码不能为空")
        return normalized

    @field_validator("market", "timeframe")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("字段不能为空")
        return normalized
