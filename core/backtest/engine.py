"""回测引擎: backtrader 集成 + 通用事件驱动框架。

提供:
    - BacktraderEngine: 把 K线 DataFrame 喂入 backtrader，挂载策略
    - EventEngine: 轻量事件驱动回测（不依赖 backtrader）
    - BacktestResult: 统一结果封装
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from core.backtest.metrics import compute_metrics

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """统一回测结果。"""

    equity_curve: pd.DataFrame
    trades: list[dict]
    final_equity: float
    total_return: float
    max_drawdown: float
    metrics: dict[str, float] = field(default_factory=dict)
    engine: str = "backtrader"
    extra: dict = field(default_factory=dict)

    # ---- 统一契约辅助方法（资深开发约定：所有策略 backtest() 必返此类型）----
    @classmethod
    def empty(cls, engine: str = "none", initial_capital: float = 0.0) -> BacktestResult:
        """构造一个合法的「空」回测结果（无数据/未实现时使用）。"""
        return cls(
            equity_curve=pd.DataFrame(columns=["datetime", "equity"]),
            trades=[],
            final_equity=initial_capital,
            total_return=0.0,
            max_drawdown=0.0,
            engine=engine,
        )

    @classmethod
    def from_dict(cls, d: dict) -> BacktestResult:
        """从 dict 容错构造（接纳历史裸 dict，字段缺失时给安全默认）。"""
        eq = d.get("equity_curve")
        if not isinstance(eq, pd.DataFrame):
            eq = pd.DataFrame(columns=["datetime", "equity"])
        return cls(
            equity_curve=eq,
            trades=list(d.get("trades", []) or []),
            final_equity=float(d.get("final_equity", 0.0)),
            total_return=float(d.get("total_return", 0.0)),
            max_drawdown=float(d.get("max_drawdown", 0.0)),
            metrics=dict(d.get("metrics", {}) or {}),
            engine=str(d.get("engine", "unknown")),
            extra=dict(d.get("extra", {}) or {}),
        )

    def to_summary(self) -> dict:
        """扁平化摘要，供 API / 看板直接序列化。"""
        return {
            "engine": self.engine,
            "final_equity": self.final_equity,
            "total_return": self.total_return,
            "max_drawdown": self.max_drawdown,
            "metrics": self.metrics,
            "n_trades": len(self.trades),
        }


class BacktraderEngine:
    """backtrader 集成回测引擎。

    用法:
        engine = BacktraderEngine(initial_capital=100000)
        result = engine.run(klines_df, strategy_cls=MyStrategy, strategy_params={...})
    """

    def __init__(
        self, initial_capital: float = 100000, commission: float = 0.0003, slippage: float = 0.0002
    ) -> None:
        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage

    def run(
        self,
        klines: pd.DataFrame,
        strategy_cls: Any,
        strategy_params: dict | None = None,
        periods_per_year: int = 252,
    ) -> BacktestResult:
        try:
            import backtrader as bt
        except ImportError as e:
            raise ImportError("backtrader 未安装，请运行: pip install backtrader") from e

        if klines.empty:
            return BacktestResult(
                equity_curve=pd.DataFrame(columns=["datetime", "equity"]),
                trades=[],
                final_equity=self.initial_capital,
                total_return=0.0,
                max_drawdown=0.0,
                engine="backtrader",
            )

        cerebro = bt.Cerebro()
        cerebro.broker.setcash(self.initial_capital)
        cerebro.broker.setcommission(commission=self.commission)
        cerebro.broker.set_slippage_perc(self.slippage)

        # 准备 backtrader 数据
        df = klines.copy()
        if "datetime" in df.columns:
            df = df.set_index("datetime")
        for col in ["open", "high", "low", "close", "volume"]:
            if col not in df.columns:
                df[col] = 0.0
        df = df[["open", "high", "low", "close", "volume"]].copy()
        df.index = pd.to_datetime(df.index)

        data = bt.feeds.PandasData(dataname=df)
        cerebro.adddata(data)
        cerebro.addstrategy(strategy_cls, **(strategy_params or {}))
        cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

        results = cerebro.run()
        strat = results[0]
        final_equity = cerebro.broker.getvalue()
        total_return = (final_equity - self.initial_capital) / self.initial_capital

        # 提取权益曲线（简化：用 broker value 序列）
        eq = pd.DataFrame(
            {
                "datetime": [datetime.now()],
                "equity": [final_equity],
            }
        )

        # 回撤
        try:
            dd = strat.analyzers.drawdown.get_analysis()
            max_dd = -float(getattr(dd, "max", {}).get("drawdown", 0)) / 100
        except Exception:
            max_dd = 0.0

        # 交易
        trades_list: list[dict] = []
        try:
            ta = strat.analyzers.trades.get_analysis()
            for t in ta.get("closed", []):
                trades_list.append({"pnl": t.pnl, "bar": t.barclose})
        except Exception:
            pass

        returns = eq["equity"].pct_change().dropna()
        metrics = compute_metrics(returns, final_equity, max_dd, periods_per_year=periods_per_year)

        return BacktestResult(
            equity_curve=eq,
            trades=trades_list,
            final_equity=final_equity,
            total_return=total_return,
            max_drawdown=max_dd,
            metrics=metrics,
            engine="backtrader",
        )


class EventEngine:
    """通用事件驱动回测框架。

    不依赖 backtrader，适合接入 SuperTrend / 情绪 / 因子等自定义策略。
    策略通过 on_bar(bar, context) 回调接收行情，调用 context.buy/sell 下单。
    """

    def __init__(self, initial_capital: float = 100000, commission: float = 0.0003) -> None:
        self.initial_capital = initial_capital
        self.commission = commission

    def run(
        self,
        klines: pd.DataFrame,
        on_bar: Callable[[pd.Series, EventContext], None],
        periods_per_year: int = 252,
    ) -> BacktestResult:
        if klines.empty:
            return BacktestResult(
                equity_curve=pd.DataFrame(columns=["datetime", "equity"]),
                trades=[],
                final_equity=self.initial_capital,
                total_return=0.0,
                max_drawdown=0.0,
                engine="event",
            )

        ctx = EventContext(self.initial_capital, self.commission)
        equity_records: list[dict] = []
        df = klines.sort_values("datetime").reset_index(drop=True)

        for _, bar in df.iterrows():
            on_bar(bar, ctx)
            eq = ctx.cash + ctx.position * float(bar["close"])
            equity_records.append({"datetime": bar["datetime"], "equity": eq})

        eq_df = pd.DataFrame(equity_records)
        final_equity = ctx.cash + ctx.position * float(df.iloc[-1]["close"])
        total_return = (final_equity - self.initial_capital) / self.initial_capital
        peak = eq_df["equity"].cummax()
        drawdown = (eq_df["equity"] - peak) / peak
        max_dd = float(drawdown.min()) if not drawdown.empty else 0.0

        returns = eq_df["equity"].pct_change().dropna()
        metrics = compute_metrics(returns, final_equity, max_dd, periods_per_year=periods_per_year)
        return BacktestResult(
            equity_curve=eq_df,
            trades=ctx.trades,
            final_equity=final_equity,
            total_return=total_return,
            max_drawdown=max_dd,
            metrics=metrics,
            engine="event",
        )


class EventContext:
    """事件驱动回测上下文。"""

    def __init__(self, initial_capital: float, commission: float) -> None:
        self.cash = initial_capital
        self.position = 0.0
        self.commission = commission
        self.trades: list[dict] = []

    def buy(self, price: float, qty: float, ts: Any) -> None:
        cost = qty * price * (1 + self.commission)
        if self.cash >= cost:
            self.cash -= cost
            self.position += qty
            self.trades.append({"datetime": ts, "side": "buy", "price": price, "qty": qty})

    def sell(self, price: float, qty: float, ts: Any) -> None:
        qty = min(qty, self.position)
        if qty > 0:
            self.cash += qty * price * (1 - self.commission)
            self.position -= qty
            self.trades.append({"datetime": ts, "side": "sell", "price": price, "qty": qty})
