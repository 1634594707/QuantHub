"""dispatcher 主循环：信号汇聚 → 加权聚合 → 风控 → 路由。

可被 apps/scheduler 定时调用，或作为常驻进程订阅信号总线。
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from apps.dispatcher.risk import RiskChecker, RiskContext, RiskError
from apps.dispatcher.router import (
    CRYPTO_EXECUTION_SOURCE_AMBIGUOUS,
    CRYPTO_EXECUTION_SOURCES,
    CRYPTO_SOURCE_NOT_AUTHORIZED,
    HOLD_SIGNAL_NOT_ORDERABLE,
    SIGNAL_NOT_EXECUTION_ELIGIBLE,
    OrderRouter,
    OrderRoutingError,
    signal_execution_rejection,
)
from core.config import get_config
from core.signals import Signal, get_bus

logger = logging.getLogger(__name__)

DIRECTION_TIE = "direction_tie"
SIGNAL_MARKET_MISMATCH = "signal_market_mismatch"


def _rejection_result(agg: dict, reason: str) -> dict:
    """Build a small, serializable result for a fail-closed aggregate.

    Rejections are returned from ``flush`` just like order intents so callers
    can show the source/reason to an operator without mistaking a rejected
    signal for a successful order.
    """

    result = {
        "symbol": agg.get("symbol"),
        "market": agg.get("market"),
        "rejected": reason,
        "direction": agg.get("direction"),
        "score": agg.get("score", 0.0),
        "sources": list(agg.get("sources") or []),
    }
    if agg.get("direction_tie"):
        result["direction_tie"] = True
    for key in (
        "observed_sources",
        "observed_markets",
        "unconfigured_sources",
        "invalid_weight_sources",
        "ineligible_sources",
    ):
        if agg.get(key):
            result[key] = list(agg[key])
    return result


def build_ledger_risk_context(symbol: str, market: str) -> RiskContext:
    from apps.api.domains.ledger import service as ledger_service

    summary = ledger_service.portfolio_summary()["summary"]
    positions = ledger_service.get_positions(refresh_prices=False)["positions"]
    instrument_id = f"{market}:{symbol.strip().upper()}"
    symbol_position = next(
        (position for position in positions if position["instrument_id"] == instrument_id),
        None,
    )
    return RiskContext(
        total_equity=float(summary["nav"]),
        position_value=sum(abs(float(position["market_value"])) for position in positions),
        symbol_position_value=abs(float(symbol_position["market_value"]))
        if symbol_position
        else 0.0,
    )


def allocation_notional(symbol: str, sources: list[str], total_equity: float) -> float:
    from apps.api import store

    matching = [
        allocation
        for allocation in store.list_allocs()
        if allocation["strategy"] in sources
        and (allocation["symbol"] is None or allocation["symbol"] == symbol)
    ]
    if not matching:
        raise RiskError("没有匹配当前标的与信号来源的策略分配")
    return total_equity * sum(float(allocation["weight"]) for allocation in matching)


class Dispatcher:
    """信号中枢。

    工作流:
        1. 订阅信号总线，按 symbol 缓存近期信号
        2. 聚合窗口到期或显式 flush 时，按 source 权重加权打分
        3. 综合分数超阈值 → 生成订单意图
        4. 风控校验 → 路由（dry-run 或实盘 CLI 确认）
    """

    def __init__(self, aggregation_window_seconds: int = 300, score_threshold: float = 0.6) -> None:
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
        self._buffer[signal.symbol].append((signal, datetime.now(UTC)))

    def flush(
        self, symbol: str | None = None, account_ctx: RiskContext | None = None
    ) -> list[dict]:
        """聚合并路由。

        Args:
            symbol: 指定标的；None 则处理所有缓冲
            account_ctx: 当前账户风控上下文（实盘时必填）
        Returns:
            路由结果列表（各订单意图）
        """
        results: list[dict] = []
        symbols = [symbol] if symbol else list(self._buffer.keys())
        now = datetime.now(UTC)
        for sym in symbols:
            pending = self._buffer.get(sym, [])
            # 过滤过期
            pending = [(s, t) for s, t in pending if now - t <= self.window]
            if not pending:
                self._buffer.pop(sym, None)
                continue
            agg = self._aggregate(pending)
            self._buffer[sym] = []

            # A source/configuration rejection is observable, but never
            # allowed to proceed to risk or order routing.
            if agg.get("rejected"):
                logger.warning(
                    "信号聚合拒绝: %s (%s; sources=%s)",
                    agg["symbol"],
                    agg["rejected"],
                    agg.get("observed_sources", agg.get("sources", [])),
                )
                results.append(_rejection_result(agg, agg["rejected"]))
                continue

            # ``hold`` is a valid display outcome.  It is intentionally
            # handled before the score threshold so a high-confidence hold
            # cannot become an order through a hidden side default.
            if agg["direction"] == "hold":
                logger.info("信号仅供展示，不生成订单: %s", agg["symbol"])
                results.append(_rejection_result(agg, HOLD_SIGNAL_NOT_ORDERABLE))
                continue

            if agg["score"] >= self.score_threshold:
                intent = self._route(agg, account_ctx)
                if intent:
                    results.append(intent)
        return results

    def _aggregate(self, pending: list[tuple[Signal, datetime]]) -> dict:
        """按 source 权重加权聚合。"""
        weight_sum = 0.0
        weighted_score = 0.0
        direction_votes: dict[str, float] = defaultdict(float)
        observed_sources = {str(sig.source or "<empty>") for sig, _ in pending}
        observed_markets = {str(sig.market or "<empty>") for sig, _ in pending}
        weighted_sources: set[str] = set()
        unconfigured_sources: set[str] = set()
        invalid_weight_sources: set[str] = set()
        ineligible_sources: set[str] = set()
        for sig, _ in pending:
            # Display/degraded/realtime-only signals may carry a buy/sell
            # direction for explanation, but they are never valid dispatcher
            # inputs for an executable aggregate.
            if signal_execution_rejection(sig) is not None:
                ineligible_sources.add(str(sig.source or "<empty>"))
                continue

            # There is no safe universal weight for a source that has not
            # been configured.  Skip it explicitly and preserve provenance so
            # an operator can fix configuration instead of receiving a
            # silently diluted/boosted trade signal.
            if sig.source not in self.weights:
                unconfigured_sources.add(str(sig.source or "<empty>"))
                continue
            try:
                w = float(self.weights[sig.source])
            except (TypeError, ValueError):
                w = 0.0
            if not math.isfinite(w) or w <= 0:
                invalid_weight_sources.add(str(sig.source or "<empty>"))
                continue

            weighted_sources.add(sig.source)
            weight_sum += w
            weighted_score += sig.score * w
            # 方向投票（buy +score, sell -score）
            if sig.direction == "buy":
                direction_votes["buy"] += sig.confidence * w
            elif sig.direction == "sell":
                direction_votes["sell"] += sig.confidence * w

        score = weighted_score / weight_sum if weight_sum > 0 else 0.0
        buy_votes = direction_votes.get("buy", 0.0)
        sell_votes = direction_votes.get("sell", 0.0)
        direction_tie = (
            buy_votes > 0
            and sell_votes > 0
            and math.isclose(buy_votes, sell_votes, rel_tol=1e-12, abs_tol=1e-12)
        )
        if direction_tie or max(direction_votes.values(), default=0) == 0:
            direction = "hold"
        elif buy_votes > sell_votes:
            direction = "buy"
        else:
            direction = "sell"

        rejected: str | None = None
        if len(observed_markets) > 1:
            # The buffer is keyed by symbol for historical reasons.  A symbol
            # can nevertheless be emitted by more than one market (for
            # example ``BTCUSDT`` in a crypto and a synthetic research feed).
            # Picking the first market would silently route the other signal
            # through the wrong risk/venue boundary, so reject the whole
            # aggregate and retain both markets for diagnosis.
            rejected = SIGNAL_MARKET_MISMATCH
        elif ineligible_sources:
            # Even when another source is configured, mixing a non-executable
            # display result into an order decision is ambiguous.  Reject the
            # batch and expose the offending source instead of guessing.
            rejected = SIGNAL_NOT_EXECUTION_ELIGIBLE
        elif direction_tie:
            # A tie has no principled execution side.  Do not preserve the
            # historical implicit ``sell`` default.
            rejected = DIRECTION_TIE
        elif unconfigured_sources:
            # A mixed configured/unknown batch is not safe to partially
            # aggregate: dropping the unknown source changes the score and
            # direction while looking like a successful signal.  Require the
            # producer/configuration to be fixed before routing any part of
            # this symbol's window.
            rejected = "signal_source_unconfigured"
        elif invalid_weight_sources:
            # Invalid configured weights are equally ambiguous when another
            # source has a valid weight.  Do not silently dilute the result.
            rejected = "signal_source_weight_invalid"

        if unconfigured_sources or invalid_weight_sources or ineligible_sources:
            logger.warning(
                "忽略未启用/无效/非执行信号来源: %s (unconfigured=%s invalid_weight=%s ineligible=%s)",
                pending[0][0].symbol,
                sorted(unconfigured_sources),
                sorted(invalid_weight_sources),
                sorted(ineligible_sources),
            )

        return {
            "symbol": pending[0][0].symbol,
            "market": pending[0][0].market,
            "direction": direction,
            "score": score,
            # ``sources`` contains only signals that actually participated in
            # the aggregate.  ``observed_sources`` retains the full input
            # provenance for diagnostics and audit logs.
            "sources": sorted(weighted_sources),
            "weighted_sources": sorted(weighted_sources),
            "observed_sources": sorted(observed_sources),
            "observed_markets": sorted(observed_markets),
            "unconfigured_sources": sorted(unconfigured_sources),
            "invalid_weight_sources": sorted(invalid_weight_sources),
            "ineligible_sources": sorted(ineligible_sources),
            "direction_tie": direction_tie,
            "rejected": rejected,
            "ts": datetime.now(UTC),
        }

    def _route(self, agg: dict, account_ctx: RiskContext | None) -> dict | None:
        from core.signals import Signal

        # Keep direct callers fail-closed as well as ``flush``.  This protects
        # future schedulers/HTTP adapters that may bypass the normal loop.
        if agg.get("rejected"):
            return _rejection_result(agg, agg["rejected"])
        if agg.get("direction") == "hold":
            return _rejection_result(agg, HOLD_SIGNAL_NOT_ORDERABLE)

        # Aggregates supplied by another caller may carry the original
        # metadata directly; preserve the same execution gate used by the
        # normal ``_aggregate`` path.
        agg_meta = dict(agg.get("meta") or {})
        if agg_meta:
            probe = Signal(
                symbol=agg["symbol"],
                market=agg["market"],
                timeframe="agg",
                direction=agg["direction"],
                score=agg["score"],
                confidence=agg.get("confidence", agg["score"]),
                source=str((agg.get("sources") or ["dispatcher"])[0]),
                meta=agg_meta,
            )
            execution_rejection = signal_execution_rejection(probe)
            if execution_rejection is not None:
                return _rejection_result(agg, execution_rejection[0])

        weighted_sources = list(agg.get("weighted_sources") or agg.get("sources") or [])
        execution_source = "dispatcher"
        if agg.get("market") == "crypto":
            unauthorized = sorted(set(weighted_sources) - CRYPTO_EXECUTION_SOURCES)
            authorized = sorted(set(weighted_sources) & CRYPTO_EXECUTION_SOURCES)
            if unauthorized:
                return _rejection_result(agg, CRYPTO_SOURCE_NOT_AUTHORIZED)
            if len(authorized) != 1:
                # Selecting one venue/wallet when several contributed would
                # be an implicit routing policy.  Require an explicit split
                # upstream instead.
                return _rejection_result(agg, CRYPTO_EXECUTION_SOURCE_AMBIGUOUS)
            execution_source = authorized[0]

        # 构造聚合 Signal
        sig = Signal(
            symbol=agg["symbol"],
            market=agg["market"],
            timeframe="agg",
            direction=agg["direction"],
            score=agg["score"],
            confidence=agg["score"],
            source=execution_source,
            tags=list(agg.get("observed_sources") or weighted_sources),
            ts=agg["ts"],
            meta=agg_meta,
        )
        price: float | None = None
        quantity = 1.0
        # 风控（实盘时）
        if not self._router.dry_run:
            from apps.api.domains.portfolio.service import latest_close

            context = account_ctx or build_ledger_risk_context(agg["symbol"], agg["market"])
            price = latest_close(agg["symbol"], agg["market"])
            if price is None or price <= 0:
                return {"symbol": agg["symbol"], "rejected": "无法取得下单价格"}
            checker = self._risk_checkers.setdefault(
                agg["market"], RiskChecker(market=agg["market"])
            )
            try:
                notional = allocation_notional(
                    agg["symbol"], weighted_sources, context.total_equity
                )
                quantity = notional / price
                checker.check(
                    {"symbol": agg["symbol"], "side": agg["direction"], "notional": notional},
                    context,
                )
            except RiskError as e:
                logger.warning("风控拒绝: %s (%s)", agg["symbol"], e)
                return {"symbol": agg["symbol"], "rejected": str(e)}

        try:
            intent = self._router.route(sig, qty=quantity, price=price)
        except OrderRoutingError as exc:
            logger.warning("订单路由拒绝: %s (%s)", agg["symbol"], exc)
            return _rejection_result(agg, exc.code)
        result = intent.to_dict()
        # Keep ignored/ineligible provenance attached to the operator-facing
        # result even when the remaining configured sources produced a valid
        # order intent.
        for key in ("observed_sources", "unconfigured_sources", "ineligible_sources"):
            if agg.get(key):
                result[key] = list(agg[key])
        return result


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
