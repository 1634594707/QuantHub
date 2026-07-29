"""Instrument 请求 schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class InstrumentRegister(BaseModel):
    """手动注册/更新 Instrument（POST /instruments）。"""

    code: str = Field(..., min_length=1, description="标的代码")
    market: str | None = Field(default=None, description="市场；缺省按代码推断")
    name: str = Field(default="", description="名称")
    exchange: str = Field(default="", description="交易所；缺省按代码推断")
    currency: str = Field(default="", description="计价币种；缺省按市场推断")
    asset_class: str = Field(default="", description="资产类别：stock/etf/crypto/forex/index")

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("标的代码不能为空")
        return normalized
