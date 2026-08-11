"""内置回测策略（demo 用，零外部依赖，可复现）。

设计：
- 每根 bar 由 ``signal``（目标权重，[-1,1]）决定目标仓位，按 ``position_fraction`` 占权益比例建仓。
- 复用 ``core.backtest.metrics.compute_metrics`` 计算周期级指标；
  另补充**交易级**胜率 / 盈亏比等用户明确要求的 KPI。
- 不依赖 backtrader，纯 pandas / numpy 实现，确保离线可跑、结果可复现。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from core.backtest.factors import compute_factor
from core.backtest.metrics import compute_metrics
from core.factor_dsl import evaluate_factor_ast


def run_signal_backtest(
    df: pd.DataFrame,
    signal: pd.Series,
    *,
    initial_capital: float = 1_000_000.0,
    commission: float = 0.0003,
    position_fraction: float = 1.0,
    periods_per_year: int = 252,
) -> dict[str, Any]:
    """按目标权重信号回测。

    Args:
        df: 含 datetime / close 的 K 线。
        signal: 与 df 等长的目标权重序列（[-1,1]）。
        initial_capital: 初始资金。
        commission: 单边手续费率。
        position_fraction: 单标的仓位上限占权益比例（<=1）。
        periods_per_year: 年化周期数（A股日线 252，加密 365）。

    Returns:
        含 equity_curve / trades / 各类 KPI 的 dict。
    """
    closes = df["close"].astype(float).reset_index(drop=True)
    opens = (
        df["open"].astype(float).reset_index(drop=True) if "open" in df.columns else closes.copy()
    )
    times = pd.to_datetime(df["datetime"]).reset_index(drop=True)
    sig = pd.Series(signal).reset_index(drop=True).fillna(0.0).clip(-1.0, 1.0)
    n = len(closes)
    if n == 0:
        raise ValueError("回测数据不能为空")
    if len(sig) != n:
        raise ValueError("信号长度必须与行情数据一致")

    cash = float(initial_capital)
    position = 0.0
    avg_cost = 0.0
    equity_records: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    realized_pnls: list[float] = []

    # Signals are known after the prior close and execute at the next bar open.
    executable_signal = sig.shift(1).fillna(0.0)
    for i in range(n):
        mark_price = max(float(closes[i]), 1e-9)
        price = max(float(opens[i]), 1e-9)
        equity = cash + position * price
        target_weight = max(0.0, float(executable_signal[i])) * position_fraction
        buy_price = price * (1 + commission)
        target_shares = int((target_weight * equity) / buy_price) if equity > 0 else 0
        delta = target_shares - position

        if delta > 0:  # 买入
            cost = delta * price * (1 + commission)
            if cost <= cash:
                new_qty = position + delta
                avg_cost = (position * avg_cost + delta * buy_price) / new_qty if new_qty else 0.0
                cash -= cost
                position = new_qty
                trades.append(
                    {
                        "datetime": times[i].isoformat(),
                        "side": "buy",
                        "price": round(price, 4),
                        "qty": delta,
                        "realized_pnl": 0.0,
                    }
                )
        elif delta < 0:  # 卖出
            qty = -delta
            qty = min(qty, position)
            if qty > 0:
                proceeds = qty * price * (1 - commission)
                pnl = (price * (1 - commission) - avg_cost) * qty
                cash += proceeds
                position -= qty
                if position <= 1e-9:
                    position = 0.0
                    avg_cost = 0.0
                realized_pnls.append(round(pnl, 4))
                trades.append(
                    {
                        "datetime": times[i].isoformat(),
                        "side": "sell",
                        "price": round(price, 4),
                        "qty": qty,
                        "realized_pnl": round(pnl, 4),
                    }
                )

        equity_records.append(
            {"datetime": times[i].isoformat(), "equity": round(cash + position * mark_price, 4)}
        )

    final_equity = float(equity_records[-1]["equity"])
    total_return = (final_equity - initial_capital) / initial_capital if initial_capital else 0.0

    eq_series = pd.Series([rec["equity"] for rec in equity_records])
    peak = eq_series.cummax()
    drawdown = (eq_series - peak) / peak
    max_dd = float(drawdown.min()) if not drawdown.empty else 0.0
    returns = eq_series.pct_change().dropna()

    metrics = compute_metrics(returns, final_equity, max_dd, periods_per_year=periods_per_year)

    # 交易级 KPI（用户明确要求的胜率/盈亏比）
    wins = [p for p in realized_pnls if p > 0]
    losses = [p for p in realized_pnls if p <= 0]
    win_rate = len(wins) / len(realized_pnls) if realized_pnls else 0.0
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

    metrics.update(
        {
            "trade_win_rate": win_rate,
            "trade_count": len(realized_pnls),
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
        }
    )

    return {
        "engine": "event-signal",
        "final_equity": round(final_equity, 2),
        "total_return": round(total_return, 6),
        "max_drawdown": round(max_dd, 6),
        "metrics": {k: (round(v, 6) if isinstance(v, float) else v) for k, v in metrics.items()},
        "equity_curve": equity_records,
        "trades": trades,
        "n_trades": len(trades),
    }


class StrategyDef:
    """策略定义：负责把 (K线, 可选因子) 编译为信号序列。"""

    def __init__(
        self,
        key: str,
        label: str,
        description: str,
        uses_factor: bool,
        build: Callable[[pd.DataFrame, str | None, dict[str, Any]], pd.Series],
    ) -> None:
        self.key = key
        self.label = label
        self.description = description
        self.uses_factor = uses_factor
        self.build = build

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "uses_factor": self.uses_factor,
        }


def _signal_buy_hold(df: pd.DataFrame, _factor: str | None, _params: dict[str, Any]) -> pd.Series:
    return pd.Series(1.0, index=range(len(df)))


def _signal_ma_cross(df: pd.DataFrame, _factor: str | None, _params: dict[str, Any]) -> pd.Series:
    # 自带均线交叉信号，忽略用户因子选择
    return compute_factor("ma_cross", df)


def _signal_factor_follow(
    df: pd.DataFrame, factor: str | None, params: dict[str, Any]
) -> pd.Series:
    name = factor or "momentum"
    return compute_factor(name, df, **params)


STRATEGIES: dict[str, StrategyDef] = {
    "buy_hold": StrategyDef(
        "buy_hold", "买入持有", "开盘建仓并持有至结束，作为基准参照", False, _signal_buy_hold
    ),
    "ma_cross": StrategyDef(
        "ma_cross", "均线交叉", "快/慢均线金叉做多、死叉平仓，自带信号", False, _signal_ma_cross
    ),
    "factor_follow": StrategyDef(
        "factor_follow",
        "因子跟随",
        "按所选因子信号建仓，因子决定方向与强度",
        True,
        _signal_factor_follow,
    ),
}


def list_strategies() -> list[dict[str, Any]]:
    """返回所有策略定义（供 API / 前端下拉）。"""
    return [s.to_dict() for s in STRATEGIES.values()]


def run_strategy(
    name: str,
    df: pd.DataFrame,
    *,
    factor_name: str | None = None,
    factor_params: dict[str, Any] | None = None,
    factor_ast: dict[str, Any] | None = None,
    initial_capital: float = 1_000_000.0,
    commission: float = 0.0003,
    position_fraction: float = 1.0,
    periods_per_year: int = 252,
) -> dict[str, Any]:
    """运行指定策略（可选叠加因子），返回回测结果。"""
    strategy = STRATEGIES.get(name)
    if strategy is None:
        raise KeyError(f"未知策略: {name}")
    if strategy.uses_factor and factor_name is None:
        factor_name = "momentum"  # 因子策略缺省回退到动量，保证可跑
    if factor_ast is not None:
        if not strategy.uses_factor:
            raise ValueError("只有因子策略可以执行自定义 DSL 因子")
        raw_signal = evaluate_factor_ast(factor_ast, df)
        signal = pd.Series(np.tanh(raw_signal.astype(float) / 2.0), index=df.index)
    else:
        signal = strategy.build(df, factor_name, factor_params or {})
    return run_signal_backtest(
        df,
        signal,
        initial_capital=initial_capital,
        commission=commission,
        position_fraction=position_fraction,
        periods_per_year=periods_per_year,
    )
