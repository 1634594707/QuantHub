# -*- coding: utf-8 -*-
"""OKX 永续多因子轮动网格 策略模块。

导出:
    - OkxGridStrategy : 策略类（继承 StrategyBase，已 @register_strategy）
    - run_select      : 选币入口（供调度器/上游调用，从配置读 top_n）
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from core.config import get_config
from core.signals import Signal
from strategies.crypto.okx_grid.selector import run_select as _run_select
from strategies.crypto.okx_grid.strategy import OkxGridStrategy

__all__ = ["OkxGridStrategy", "run_select"]


def run_select(
    klines_dict: Optional[dict[str, pd.DataFrame]] = None,
    top_n: Optional[int] = None,
) -> list[str]:
    """选币入口（供调度器/上游调用）。

    从 ``configs/crypto.yaml`` 的 ``modules.okx_grid.selector`` 读取
    ``top_n`` 默认值（缺省 10），转发到 ``selector.run_select``。

    Args:
        klines_dict: ``{symbol: klines_df}``，为空时返回空列表
        top_n: 选取前 N 名（None 则从配置读取）
    Returns:
        选中币种 symbol 列表
    """
    if not klines_dict:
        return []
    if top_n is None:
        cfg = get_config("crypto").get("modules", {}).get("okx_grid", {}).get("selector", {})
        top_n = int(cfg.get("top_n", 10))
    return _run_select(klines_dict, top_n=top_n)
