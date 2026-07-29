"""OKX 永续多因子轮动网格策略。

把原 ``OKX Grid Master`` 下沉为 QuantHub 策略插件：

    - 行情统一走 ``core.data_feed.okx_source.OkxSource``（不重新封装 ccxt）
    - 选币走本模块 ``selector.run_select``（多因子截面排名，因子公式保持原样）
    - 回测走 ``core.backtest.GridBacktester``（已有网格回测）
    - 实盘下单走 ``okx_executor.OkxExecutor``（复用 OkxSource._exchange）
    - 实盘默认关闭：``is_live()`` 需全局 ``live_trading=true`` 且
      ``modules.okx_grid.live=true`` 双开
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from core.backtest import BacktestResult, GridBacktester, GridConfig
from core.config import get_config
from core.data_feed.okx_source import OkxSource
from core.signals import Signal
from strategies.base import StrategyBase, StrategyInfo, register_strategy
from strategies.crypto.okx_grid.okx_executor import OkxExecutor
from strategies.crypto.okx_grid.selector import run_select

logger = logging.getLogger(__name__)

_SOURCE = "okx_grid"
_MARKET = "crypto"

# 默认因子配置（动量 / 波动率 / 流动性），与 selector.DEFAULT_FACTOR_CONFIG 一致
# True=升序(选小的), False=降序(选大的)
_DEFAULT_FACTOR_CONFIG = {
    "波动率": False,  # 高波动（网格收益空间大）
    "momentum_12": False,  # 高动量
    "vol_ratio_24": False,  # 高成交活跃（流动性）
}


@register_strategy(
    StrategyInfo(
        name="okx_grid",
        market="crypto",
        live_capable=True,
        description="OKX永续多因子轮动网格(实盘默认关)",
    )
)
class OkxGridStrategy(StrategyBase):
    """OKX 永续多因子轮动网格策略。

    工作流：
        1. ``produce`` : 对候选币种拉 K线 → 多因子选币 → 基于网格区间位置产出 Signal
        2. ``backtest``: 用 ``core.backtest.GridBacktester`` 跑网格回测
        3. ``live_tick``: 实盘 tick（``is_live()`` 为 false 时 no-op）

    实盘开关继承基类 ``is_live``：需 ``live_trading=true`` 且 ``modules.okx_grid.live=true``。
    """

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config=config)
        self._source: OkxSource | None = None
        self._executor: OkxExecutor | None = None

    # ------------------------------------------------------------------
    # 数据源 / 执行器懒加载
    # ------------------------------------------------------------------

    @property
    def source(self) -> OkxSource:
        """OKX 数据源（懒加载，复用其 ccxt.okx 实例）。"""
        if self._source is None:
            cfg = get_config("crypto")
            api_cfg = cfg.get("modules", {}).get("okx_grid", {}).get("api", {})
            self._source = OkxSource(
                api_key=api_cfg.get("api_key"),
                secret=api_cfg.get("api_secret"),
                passphrase=api_cfg.get("api_passphrase"),
            )
        return self._source

    @property
    def executor(self) -> OkxExecutor:
        """实盘执行器（懒加载，live 跟随 is_live()）。"""
        if self._executor is None:
            self._executor = OkxExecutor(self.source, live=self.is_live())
        return self._executor

    # ------------------------------------------------------------------
    # 信号产出
    # ------------------------------------------------------------------

    def produce(
        self,
        symbols: list[str] | None = None,
        top_n: int = 10,
        **kwargs: Any,
    ) -> list[Signal]:
        """多因子选币 + 产出网格信号。

        Args:
            symbols: 候选币种列表（如 ``["BTC/USDT:USDT", "ETH/USDT:USDT"]``）；
                     为空时返回空列表
            top_n: 选取前 N 名（默认 10）
            **kwargs:
                interval  : K线周期（默认 "1h"）
                limit     : K线数量（默认 100）
                timeframe : 信号周期（默认 "1h"）
                factor_config: 因子配置（覆盖默认）
        Returns:
            信号列表（已推入总线）。direction 基于当前价在网格区间的位置：
                - 下半区（pos<0.4）→ buy
                - 上半区（pos>0.6）→ sell
                - 中间区域       → hold
        """
        symbols = symbols or []
        if not symbols:
            logger.debug("okx_grid.produce 未提供 symbols，跳过")
            return []

        interval = kwargs.get("interval", "1h")
        limit = int(kwargs.get("limit", 100))
        timeframe = str(kwargs.get("timeframe", "1h"))
        factor_config = kwargs.get("factor_config", _DEFAULT_FACTOR_CONFIG)

        # 1. 拉取 K线（OkxSource，不重新封装 ccxt）
        klines_dict: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                df = self.source.get_kline(sym, interval=interval, limit=limit)
            except Exception:
                logger.exception("okx 取 K线失败: %s", sym)
                continue
            if df is not None and not df.empty:
                klines_dict[sym] = df

        if not klines_dict:
            logger.warning("okx_grid.produce 无可用 K线")
            return []

        # 2. 多因子选币（因子公式保持原样）
        selected = run_select(klines_dict, top_n=top_n, factor_config=factor_config)
        if not selected:
            logger.warning("okx_grid 选币结果为空")
            return []

        # 3. 网格参数（从 config 读取，回退到默认）
        grid_cfg = self.config.get("grid", {})
        upper_coef = float(grid_cfg.get("upper", 1.2))
        lower_coef = float(grid_cfg.get("lower", 0.8))

        # 4. 对选中币种产出 Signal（direction 基于网格区间位置）
        signals: list[Signal] = []
        for sym in selected:
            df = klines_dict.get(sym)
            if df is None or df.empty:
                continue
            last_close = float(df.iloc[-1]["close"])
            upper_p = last_close * upper_coef
            lower_p = last_close * lower_coef
            # 价格在区间的相对位置: 0=下限, 1=上限
            pos = (last_close - lower_p) / (upper_p - lower_p) if upper_p > lower_p else 0.5
            pos = max(0.0, min(1.0, pos))

            if pos < 0.4:
                direction = "buy"
                score = 1.0 - pos  # 越接近下限，买入置信越强
            elif pos > 0.6:
                direction = "sell"
                score = pos  # 越接近上限，卖出置信越强
            else:
                direction = "hold"
                score = 0.5

            try:
                sig = Signal(
                    symbol=sym,
                    market=_MARKET,
                    timeframe=timeframe,
                    direction=direction,
                    score=score,
                    confidence=0.7,
                    source=_SOURCE,
                    tags=["grid", "momentum", "volatility"],
                    meta={
                        "close": last_close,
                        "grid_upper": upper_p,
                        "grid_lower": lower_p,
                        "grid_pos": round(pos, 4),
                        "top_n": top_n,
                    },
                )
                self.publish(sig)
                signals.append(sig)
            except ValueError as e:
                logger.warning("信号构造失败 %s: %s", sym, e)

        return signals

    # ------------------------------------------------------------------
    # 回测
    # ------------------------------------------------------------------

    def backtest(self, klines: pd.DataFrame, **kwargs: Any) -> BacktestResult:
        """用 ``core.backtest.GridBacktester`` 跑网格回测。

        Args:
            klines: K线 DataFrame（需含 ``datetime``/``close`` 列）
            **kwargs:
                upper/lower/grids/amount_per_grid/base_price/fee_rate/slippage:
                    覆盖默认 ``GridConfig``（缺省从 ``config.grid`` 读）
        Returns:
            回测结果（core.backtest.BacktestResult）
        """
        if klines is None or klines.empty:
            return BacktestResult.empty(engine="grid")

        grid_cfg = self.config.get("grid", {})
        cfg = GridConfig(
            upper=float(kwargs.get("upper", grid_cfg.get("upper", 1.2))),
            lower=float(kwargs.get("lower", grid_cfg.get("lower", 0.8))),
            grids=int(kwargs.get("grids", grid_cfg.get("grids", 20))),
            amount_per_grid=float(
                kwargs.get("amount_per_grid", grid_cfg.get("amount_per_grid", 100.0))
            ),
            base_price=kwargs.get("base_price"),
            fee_rate=float(kwargs.get("fee_rate", 0.0006)),
            slippage=float(kwargs.get("slippage", 0.0005)),
        )
        engine = GridBacktester(config=cfg)
        result = engine.run(klines, periods_per_year=365)
        return result.to_backtest_result()

    # ------------------------------------------------------------------
    # 实盘 tick
    # ------------------------------------------------------------------

    def live_tick(self, **kwargs: Any) -> dict | None:
        """实盘 tick 回调。

        ``is_live()`` 为 false 时 no-op（返回 None），保证实盘默认关闭。
        实盘开启时通过 ``OkxExecutor`` 检查/调整网格。

        Args:
            **kwargs:
                action: "check"(默认) | "place" | "close"
                symbols: 候选币种列表（place 时使用）
                params: 下单参数 dict（place 时使用，见 OkxExecutor.place_grid_order）
                algo_id: 网格 algoId（close 时使用）
        """
        if not self.is_live():
            logger.debug("okx_grid 非实盘模式，live_tick no-op")
            return None

        action = kwargs.get("action", "check")
        try:
            if action == "place":
                symbols = kwargs.get("symbols") or []
                params = kwargs.get("params", {})
                results = [
                    {"symbol": sym, "result": self.executor.place_grid_order(params)}
                    for sym in symbols
                ]
                return {"action": "place", "results": results}
            if action == "close":
                algo_id = kwargs.get("algo_id")
                return {"action": "close", "result": self.executor.close_grid_order(algo_id)}
            # 默认: 查询运行中的网格
            return {"action": "query", "result": self.executor.query_grid_orders()}
        except Exception:
            logger.exception("okx_grid.live_tick 执行失败")
            return None
