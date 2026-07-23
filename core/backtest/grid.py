# -*- coding: utf-8 -*-
"""网格回测引擎。

源自 OKX Grid Master 的 simulate_grid_trading，统一接口。
适用于震荡行情的网格策略回测。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from core.backtest.metrics import compute_metrics


@dataclass
class GridConfig:
    """网格参数。"""
    upper: float = 1.2           # 上限价格系数（相对基准价）
    lower: float = 0.8           # 下限价格系数
    grids: int = 20              # 网格数量
    amount_per_grid: float = 100.0   # 每格投入金额（USDT）
    base_price: float | None = None  # 基准价；None 则用首根 K 线收盘
    fee_rate: float = 0.0006     # 单边手续费率
    slippage: float = 0.0005     # 滑点


@dataclass
class GridResult:
    """网格回测结果。"""
    equity_curve: pd.DataFrame   # 列: datetime, equity
    trades: list[dict]           # 交易记录
    final_equity: float
    total_return: float
    max_drawdown: float
    metrics: dict[str, float] = field(default_factory=dict)
    extra: dict = field(default_factory=dict)

    def to_backtest_result(self) -> "BacktestResult":
        """转换为统一 BacktestResult（供策略 backtest() 统一返回）。"""
        from core.backtest.engine import BacktestResult
        return BacktestResult(
            equity_curve=self.equity_curve,
            trades=self.trades,
            final_equity=self.final_equity,
            total_return=self.total_return,
            max_drawdown=self.max_drawdown,
            metrics=self.metrics,
            engine="grid",
            extra=self.extra,
        )


class GridBacktester:
    """网格策略回测器。

    策略逻辑:
        1. 以基准价 P 为中心，在 [P*lower, P*upper] 区间均分 grids 个网格
        2. 价格下穿某格线 -> 买入 amount_per_grid
        3. 价格上穿某格线 -> 卖出 amount_per_grid
        4. 记录权益曲线与交易明细
    """

    def __init__(self, config: GridConfig | None = None) -> None:
        self.config = config or GridConfig()

    def run(self, klines: pd.DataFrame, config: GridConfig | None = None) -> GridResult:
        cfg = config or self.config
        if klines.empty or len(klines) < 2:
            return GridResult(
                equity_curve=pd.DataFrame(columns=["datetime", "equity"]),
                trades=[], final_equity=0.0, total_return=0.0, max_drawdown=0.0,
            )

        df = klines.sort_values("datetime").reset_index(drop=True)
        base = cfg.base_price or float(df.iloc[0]["close"])
        upper_p = base * cfg.upper
        lower_p = base * cfg.lower
        grid_lines = np.linspace(lower_p, upper_p, cfg.grids + 1)

        cash = 0.0
        position = 0.0
        equity_curve: list[dict] = []
        trades: list[dict] = []

        prev_close = float(df.iloc[0]["close"])
        for _, row in df.iterrows():
            price = float(row["close"])
            ts = row["datetime"]

            # 下穿买入
            for gl in grid_lines:
                if prev_close > gl >= price:
                    buy_price = gl * (1 + cfg.slippage)
                    qty = cfg.amount_per_grid / buy_price
                    cost = qty * buy_price * (1 + cfg.fee_rate)
                    if cash >= cost or (cash + position * price) >= cost:
                        cash -= cost
                        position += qty
                        trades.append({
                            "datetime": ts, "side": "buy", "price": buy_price,
                            "qty": qty, "grid": gl,
                        })

            # 上穿卖出
            for gl in grid_lines:
                if prev_close < gl <= price:
                    if position > 0:
                        sell_price = gl * (1 - cfg.slippage)
                        qty = min(cfg.amount_per_grid / sell_price, position)
                        if qty > 0:
                            proceeds = qty * sell_price * (1 - cfg.fee_rate)
                            cash += proceeds
                            position -= qty
                            trades.append({
                                "datetime": ts, "side": "sell", "price": sell_price,
                                "qty": qty, "grid": gl,
                            })

            equity = cash + position * price
            equity_curve.append({"datetime": ts, "equity": equity})
            prev_close = price

        # 期末结算
        final_equity = cash + position * float(df.iloc[-1]["close"])
        total_invested = cfg.amount_per_grid * cfg.grids
        total_return = (final_equity - total_invested) / total_invested if total_invested > 0 else 0.0

        eq_df = pd.DataFrame(equity_curve)
        peak = eq_df["equity"].cummax()
        drawdown = (eq_df["equity"] - peak) / peak
        max_dd = float(drawdown.min()) if not drawdown.empty else 0.0

        returns = eq_df["equity"].pct_change().dropna()
        metrics = compute_metrics(returns, final_equity, max_dd)

        return GridResult(
            equity_curve=eq_df, trades=trades,
            final_equity=final_equity, total_return=total_return,
            max_drawdown=max_dd, metrics=metrics,
        )
