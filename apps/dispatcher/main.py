# -*- coding: utf-8 -*-
"""dispatcher 主循环：信号汇聚 → 加权聚合 → 风控 → 路由。

可被 apps/scheduler 定时调用，或作为常驻进程订阅信号总线。
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from apps.dispatcher.risk import RiskChecker, RiskContext, RiskError
from apps.dispatcher.router import OrderRouter
from core.config import get_config
from core.signals import Signal, get_bus

logger = logging.getLogger(__name__)


class Dispatcher:
    """信号中枢。

    工作流:
        1. 订阅信号总线，按 symbol 缓存近期信号
        2. 聚合窗口到期或显式 flush 时，按 source 权重加权打分
        3. 综合分数超阈值 → 生成订单意图
        4. 风控校验 → 路由（dry-run 或实盘 CLI 确认）
    """

    def __init__(self, aggregation_window_seconds: int = 300,
                 score_threshold: float = 0.6) -> None:
        cfg = get_config()
        self.weights: dict[str, float] = cfg.get("signals", {}).get("weights", {})
        self.window = timedelta(seconds=aggregation_window_seconds)
        self.score_threshold = score_threshold
        self._buffer: dict[str, list[tuple[Signal, datetime]]] = defaultdict(list)
        self._router = OrderRouter()
        self._risk_checkers: dict[str, RiskChecker] = {}

        # 订阅总线
        get_bus().subscribe(self._on_signal)

    def _on_signal(self, signal: Signal) -> None:
        """信号到达回调：缓存。"""
        self._buffer[signal.symbol].append((signal, datetime.now()))

    def flush(self, symbol: str | None = None, account_ctx: RiskContext | None = None) -> list[dict]:
        """聚合并路由。

        Args:
            symbol: 指定标的；None 则处理所有缓冲
            account_ctx: 当前账户风控上下文（实盘时必填）
        Returns:
            路由结果列表（各订单意图）
        """
        results: list[dict] = []
        symbols = [symbol] if symbol else list(self._buffer.keys())
        now = datetime.now()
        for sym in symbols:
            pending = self._buffer.get(sym, [])
            # 过滤过期
            pending = [(s, t) for s, t in pending if now - t <= self.window]
            if not pending:
                self._buffer.pop(sym, None)
                continue
            agg = self._aggregate(pending)
            if agg["score"] >= self.score_threshold:
                intent = self._route(agg, account_ctx)
                if intent:
                    results.append(intent)
            self._buffer[sym] = []
        return results

    def _aggregate(self, pending: list[tuple[Signal, datetime]]) -> dict:
        """按 source 权重加权聚合。"""
        weight_sum = 0.0
        weighted_score = 0.0
        direction_votes: dict[str, float] = defaultdict(float)
        for sig, _ in pending:
            w = self.weights.get(sig.source, 0.1)
            weight_sum += w
            weighted_score += sig.score * w
            # 方向投票（buy +score, sell -score）
            if sig.direction == "buy":
                direction_votes["buy"] += sig.confidence * w
            elif sig.direction == "sell":
                direction_votes["sell"] += sig.confidence * w

        score = weighted_score / weight_sum if weight_sum > 0 else 0.0
        direction = "buy" if direction_votes.get("buy", 0) > direction_votes.get("sell", 0) else "sell"
        if max(direction_votes.values(), default=0) == 0:
            direction = "hold"

        return {
            "symbol": pending[0][0].symbol,
            "market": pending[0][0].market,
            "direction": direction,
            "score": score,
            "sources": list({s.source for s, _ in pending}),
            "ts": datetime.now(),
        }

    def _route(self, agg: dict, account_ctx: RiskContext | None) -> dict | None:
        from core.signals import Signal
        # 构造聚合 Signal
        sig = Signal(
            symbol=agg["symbol"], market=agg["market"],
            timeframe="agg", direction=agg["direction"],
            score=agg["score"], confidence=agg["score"],
            source="dispatcher", tags=agg["sources"], ts=agg["ts"],
        )
        # 风控（实盘时）
        if not self._router.dry_run and account_ctx is not None:
            checker = self._risk_checkers.setdefault(
                agg["market"], RiskChecker(market=agg["market"])
            )
            try:
                checker.check({"symbol": agg["symbol"], "notional": 100.0}, account_ctx)
            except RiskError as e:
                logger.warning("风控拒绝: %s (%s)", agg["symbol"], e)
                return {"symbol": agg["symbol"], "rejected": str(e)}

        intent = self._router.route(sig, qty=1.0)
        return intent.to_dict()


def main() -> None:
    """CLI 入口：常驻订阅 + 定时 flush。"""
    import time
    logging.basicConfig(level=logging.INFO)
    logger.info("启动 dispatcher（dry_run=%s）", get_config().get("live_trading", False) is False)
    d = Dispatcher()
    while True:
        time.sleep(60)
        results = d.flush()
        if results:
            logger.info("本轮路由 %d 条", len(results))


if __name__ == "__main__":
    main()
