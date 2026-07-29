"""Instrument 领域：统一标的元数据（代码 / 市场 / 交易所 / 名称 / 币种）。

为行情查询、关注列表、持仓、回测提供统一的标的标识与解析入口，
消除各域自行维护 symbol→{market, name, currency} 映射的散落。
"""

from __future__ import annotations

from .router import router

__all__ = ["router"]
