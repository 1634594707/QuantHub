# -*- coding: utf-8 -*-
"""价格行为两阶段 LLM 分析策略 — QuantHub 迁移版。

把原 ``PA_Agent`` 下沉为 QuantHub 的 strategies/ai_analysis/pa_agent 策略模块:

    - 行情统一走 ``core.data_feed.get_data_source()``（A股 / 加密均支持）
    - 指标（ATR/EMA）走本模块 ``indicators.py``（算法保持原样）
    - 两阶段 LLM 编排走本模块 ``two_stage.py``，LLM 客户端复用 ``core.llm.get_llm()``
    - 按阶段二决策产出 ``Signal``（direction/score/confidence 从 stage2 输出解析）

注意: ``StrategyInfo.market`` 用 "ai_analysis"（策略分类归属），但产出的
``Signal.market`` 根据实际分析标的决定（"a_shares" 或 "crypto"）。
"""
from __future__ import annotations

import logging
import math
from typing import Any, Optional

from core.config import get_config
from core.data_feed import Interval, get_data_source
from core.signals import Signal
from strategies.ai_analysis.pa_agent.two_stage import TwoStageResult, run_two_stage
from strategies.base import StrategyBase, StrategyInfo, register_strategy

logger = logging.getLogger(__name__)

# timeframe 字符串 → Interval 枚举（与 supertrend 策略保持一致）
_TIMEFRAME_TO_INTERVAL: dict[str, Interval] = {
    "daily": Interval.DAILY,
    "1d": Interval.DAILY,
    "weekly": Interval.WEEKLY,
    "1w": Interval.WEEKLY,
    "1h": Interval.H1,
    "60m": Interval.H1,
    "4h": Interval.H4,
    "30m": Interval.M30,
    "15m": Interval.M15,
    "5m": Interval.M5,
    "1m": Interval.M1,
}

_SOURCE = "pa_agent"


def _resolve_interval(timeframe: str) -> Interval:
    """把对外 timeframe 字符串映射为 data_feed 的 Interval 枚举。"""
    tf = str(timeframe).lower()
    if tf not in _TIMEFRAME_TO_INTERVAL:
        raise ValueError(
            f"不支持的时间周期: {timeframe}（支持: {sorted(_TIMEFRAME_TO_INTERVAL)}）"
        )
    return _TIMEFRAME_TO_INTERVAL[tf]


def _resolve_market(symbol: str, market: str | None) -> str:
    """确定分析标的所属市场。

    优先用调用方显式传入的 market；未传时按 symbol 形态启发式判断:
        - 6 位纯数字（如 000001/600519）→ a_shares
        - 含字母与 '-'（如 BTC-USDT）→ crypto
        - 其余默认 a_shares
    """
    if market:
        return market
    s = (symbol or "").strip().upper()
    if s.isdigit() and len(s) == 6:
        return "a_shares"
    if any(ch.isalpha() for ch in s) and ("-" in s or "/" in s or len(s) >= 6):
        return "crypto"
    return "a_shares"


@register_strategy(StrategyInfo(
    name="pa_agent",
    market="ai_analysis",
    live_capable=False,
    description="价格行为两阶段LLM分析(Al Brooks)",
))
class PaAgentStrategy(StrategyBase):
    """价格行为两阶段 LLM 分析策略。

    通过 ``core.data_feed.get_data_source(market)`` 获取 K 线，计算 ATR/EMA 后
    走两阶段 LLM 编排（阶段一市场诊断 → 阶段二决策评估），解析为 buy/sell/hold 信号。
    """

    def produce(
        self,
        symbol: str | None = None,
        timeframe: str = "1h",
        *,
        market: str | None = None,
        limit: int = 300,
        atr_period: int = 14,
        ema_period: int = 20,
        tail_bars: int = 60,
        **kwargs: Any,
    ) -> list[Signal]:
        """对单个标的执行两阶段 PA 分析并产出信号。

        Args:
            symbol: 标的代码（如 "000001" / "BTC-USDT"）
            timeframe: K 线周期（默认 "1h"）
            market: 显式指定市场（"a_shares" | "crypto"）；None 时按 symbol 启发式判断
            limit: 拉取 K 线根数（默认 300，确保 ATR/EMA 暖机完成）
            atr_period / ema_period: 指标周期
            tail_bars: 送入 LLM 的最近 K 线根数
        Returns:
            信号列表（已推入总线）；分析失败或不下单时返回 hold 信号或空列表
        """
        if not symbol:
            logger.debug("pa_agent.produce 未提供 symbol，跳过")
            return []

        actual_market = _resolve_market(symbol, market)
        interval = _resolve_interval(timeframe)

        try:
            ds = get_data_source(actual_market)
            klines = ds.get_kline(symbol, interval, limit=limit)
        except Exception:  # noqa: BLE001
            logger.exception("获取 K 线失败: %s %s", symbol, interval)
            return []
        if klines is None or klines.empty:
            logger.warning("K 线为空: %s %s", symbol, interval)
            return []

        # 两阶段 LLM 分析
        result = run_two_stage(
            symbol=symbol,
            timeframe=timeframe,
            klines=klines,
            atr_period=atr_period,
            ema_period=ema_period,
            tail_bars=tail_bars,
        )

        sig = self._signal_from_result(result, symbol, actual_market, timeframe)
        if sig is not None:
            self.publish(sig)
            return [sig]
        return []

    @staticmethod
    def _signal_from_result(
        result: TwoStageResult,
        symbol: str,
        market: str,
        timeframe: str,
    ) -> Optional[Signal]:
        """从两阶段分析结果解析为 Signal。

        解析规则（基于原 PA Agent 阶段二 schema）:
            - direction: terminal.outcome=trade 且 order_direction=做多 → buy；
                         terminal.outcome=trade 且 order_direction=做空 → sell；
                         其余（wait/reject/不下单/闸门短路）→ hold
            - score: next_bar_prediction.probabilities 归一化（buy 用 bullish,
                     sell 用 bearish, hold 用 0.5）；unpredictable 时取 0.5
            - confidence: decision.trade_confidence（0-100）→ /100；缺失时用
                          diagnosis_confidence；仍缺失取 0.3 兜底
        """
        if result.error and result.stage2_json is None:
            logger.warning("pa_agent 分析失败 %s: %s", symbol, result.error)
            return None

        s2 = result.stage2_json or {}
        decision = s2.get("decision") or {}
        terminal = s2.get("terminal") or {}
        nbp = s2.get("next_bar_prediction") or {}

        order_type = str(decision.get("order_type", "不下单"))
        order_direction = decision.get("order_direction")
        outcome = str(terminal.get("outcome", "wait")).lower()

        # 方向判定
        is_trade = outcome == "trade" or order_type in ("限价单", "突破单", "市价单")
        if is_trade and order_direction == "做多":
            direction = "buy"
        elif is_trade and order_direction == "做空":
            direction = "sell"
        else:
            direction = "hold"

        # score：来自下一根预测概率
        probs = nbp.get("probabilities")
        unpredictable = bool(nbp.get("unpredictable", False))
        if unpredictable or not isinstance(probs, dict):
            score = 0.5
        elif direction == "buy":
            score = _clamp_01(float(probs.get("bullish", 0)) / 100.0)
        elif direction == "sell":
            score = _clamp_01(float(probs.get("bearish", 0)) / 100.0)
        else:
            # hold：取中性概率反映「方向置信强度」低
            score = _clamp_01(float(probs.get("neutral", 50)) / 100.0)

        # confidence：trade_confidence 优先，回退 diagnosis_confidence
        tc = decision.get("trade_confidence")
        dc = decision.get("diagnosis_confidence")
        if isinstance(tc, (int, float)):
            confidence = _clamp_01(float(tc) / 100.0)
        elif isinstance(dc, (int, float)):
            confidence = _clamp_01(float(dc) / 100.0)
        else:
            confidence = 0.3

        # meta：携带阶段一诊断摘要与决策计划
        s1 = result.stage1_json or {}
        meta: dict[str, Any] = {
            "cycle_position": s1.get("cycle_position"),
            "pa_direction": s1.get("direction") or (s2.get("diagnosis_summary") or {}).get("direction"),
            "trend_stage": s1.get("trend_stage"),
            "gate_result": s1.get("gate_result"),
            "order_type": order_type,
            "terminal_outcome": outcome,
            "unpredictable": unpredictable,
            "error": result.error,
        }
        # 下单计划字段（仅在有单时填充）
        for fld in ("entry_price", "stop_loss_price", "take_profit_price", "estimated_win_rate"):
            val = decision.get(fld)
            if val is not None:
                meta[fld] = val
        if result.usage:
            meta["usage"] = result.usage

        tags = ["pa_agent", "two_stage", f"timeframe={timeframe}"]
        if is_trade:
            tags.append(order_type)

        try:
            return Signal(
                symbol=symbol,
                market=market,
                timeframe=timeframe,
                direction=direction,
                score=score,
                confidence=confidence,
                source=_SOURCE,
                tags=tags,
                meta=meta,
            )
        except ValueError as e:
            logger.warning("信号构造失败 %s: %s", symbol, e)
            return None


def _clamp_01(x: float) -> float:
    """把数值钳制到 [0, 1]。"""
    if math.isnan(x):
        return 0.0
    return max(0.0, min(1.0, x))


def run_analysis(
    symbol: str,
    timeframe: str = "1h",
    *,
    market: str | None = None,
    limit: int = 300,
    **kwargs: Any,
) -> list[Signal]:
    """便捷分析入口：实例化 PaAgentStrategy 并产出信号。

    供 apps.scheduler 或 CLI 调用。
    """
    strategy = PaAgentStrategy(config={"enabled": True})
    return strategy.produce(
        symbol=symbol,
        timeframe=timeframe,
        market=market,
        limit=limit,
        **kwargs,
    )


def run_scheduled() -> None:
    """供 apps.scheduler 定时调用：遍历配置中的标的批量跑 PA 分析。

    配置 ``configs/ai_analysis.yaml`` 的 ``modules.pa_agent.symbols``
    （缺省回退到 A股+加密各一个示例标的）。单标的失败不影响其余。
    """
    try:
        cfg = get_config("ai_analysis").get("modules", {}).get("pa_agent", {})
    except Exception:  # noqa: BLE001 - 配置缺失时走默认
        cfg = {}
    symbols: list[str] = list(cfg.get("symbols", []) or [])
    if not symbols:
        symbols = ["000001", "BTC-USDT"]
    timeframe = cfg.get("timeframe", "1h")
    for sym in symbols:
        try:
            run_analysis(symbol=sym, timeframe=timeframe)
        except Exception:  # noqa: BLE001
            logger.exception("PA 定时分析失败: %s", sym)
