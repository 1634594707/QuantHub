from __future__ import annotations

import inspect
import logging
from typing import Any

import pandas as pd
from pa_agent.view_models import (
    build_decision_tree_view,
    build_decision_view,
    build_future_trend_view,
)

from apps.api.domains.research.service import (
    ResearchContextMismatchError,
    add_evidence,
    complete_module,
    dataframe_snapshot,
    fail_module,
    start_module,
)
from core.data_feed.factory import get_data_source
from core.data_feed.quality import assess_ohlcv
from core.signals import Signal
from strategies import discover_and_register, get_strategy, list_strategies
from strategies.ai_analysis.pa_agent.two_stage import (
    PA_PIPELINE_VERSION,
    PA_PROMPT_VERSION,
    run_two_stage,
)

from . import repository
from .schemas import BacktestRequest

logger = logging.getLogger(__name__)


class UnknownStrategyError(ValueError):
    pass


def catalog() -> list[dict]:
    discover_and_register()
    return [
        {
            "name": name,
            "market": info.market,
            "live_capable": info.live_capable,
            "description": info.description or "",
        }
        for name, info in list_strategies().items()
    ]


def strategy_info(name: str) -> dict:
    discover_and_register()
    info = list_strategies().get(name)
    if info is None:
        raise UnknownStrategyError(name)
    return {
        "name": name,
        "market": info.market,
        "live_capable": info.live_capable,
        "description": info.description or "",
    }


def alphamaster_engine_info() -> dict:
    """返回 AlphaMaster 词表/回退公式信息，不加载任何交易数据。"""
    from strategies.mt5.alphamaster import engine_info

    return engine_info()


def call_produce(strategy: Any, params: dict[str, Any]) -> list[Any]:
    try:
        signature = inspect.signature(strategy.produce)
        accepted = set(signature.parameters)
        accepts_kwargs = any(
            item.kind == inspect.Parameter.VAR_KEYWORD for item in signature.parameters.values()
        )
    except (TypeError, ValueError):
        accepted, accepts_kwargs = set(), False
    kwargs = (
        dict(params)
        if accepts_kwargs
        else (
            {key: value for key, value in params.items() if key in accepted}
            if accepted
            else dict(params)
        )
    )
    try:
        result = strategy.produce(**kwargs)
    except TypeError:
        result = strategy.produce()
    if result is None:
        return []
    return list(result) if isinstance(result, (list, tuple)) else [result]


def signal_to_dict(signal: Any) -> dict:
    if hasattr(signal, "to_dict"):
        try:
            return signal.to_dict()
        except Exception:  # noqa: BLE001 - tolerate third-party signal serializers
            logger.debug("signal.to_dict() failed", exc_info=True)
    if isinstance(signal, Signal):
        return {
            "symbol": signal.symbol,
            "market": signal.market,
            "timeframe": signal.timeframe,
            "direction": signal.direction,
            "score": signal.score,
            "confidence": signal.confidence,
            "source": signal.source,
            "tags": list(signal.tags or []),
            "meta": signal.meta or {},
            "ts": getattr(signal, "ts", None),
        }
    return dict(signal)


def run(name: str, params: dict[str, Any]) -> dict:
    strategy_info(name)
    try:
        strategy = get_strategy(name, config={"enabled": True})
        raw = call_produce(strategy, params)
        signals = repository.persist_signals([signal_to_dict(item) for item in raw])
        result = {"ok": True, "name": name, "count": len(signals), "signals": signals}
        report = getattr(strategy, "last_report", None)
        if isinstance(report, dict):
            result["report"] = report
        rejection = getattr(strategy, "last_signal_rejection", None)
        if isinstance(rejection, dict):
            result["signal_rejection"] = rejection
    except Exception as exc:  # noqa: BLE001 - normalize data adapter failures for the API
        logger.exception("策略 %s 运行失败", name)
        result = {"ok": False, "name": name, "error": str(exc), "signals": []}
    repository.save_run(name, params, result)
    return result


def _pair_round_trips(fills: list[Any], commission: float = 0.0003) -> list[dict]:
    open_lots, trips = [], []
    for fill in fills:
        if not isinstance(fill, dict):
            continue
        side = str(fill.get("side", "")).lower()
        try:
            price, quantity = float(fill.get("price") or 0), float(fill.get("qty") or 0)
        except (TypeError, ValueError):
            continue
        timestamp = fill.get("datetime")
        if side in ("buy", "long", "open"):
            open_lots.append({"price": price, "qty": quantity, "time": timestamp})
        elif side in ("sell", "short", "close") and quantity > 0:
            remaining = quantity
            while remaining > 1e-9 and open_lots:
                lot = open_lots[0]
                matched = min(lot["qty"], remaining)
                pnl = matched * price * (1 - commission) - matched * lot["price"] * (1 + commission)
                trips.append(
                    {
                        "entry_time": str(lot["time"]) if lot["time"] is not None else None,
                        "exit_time": str(timestamp) if timestamp is not None else None,
                        "pnl": round(pnl, 2),
                        "return_pct": round((price / lot["price"] - 1) * 100, 2)
                        if lot["price"]
                        else 0,
                        "qty": round(matched, 4),
                    }
                )
                lot["qty"] -= matched
                remaining -= matched
                if lot["qty"] <= 1e-9:
                    open_lots.pop(0)
    return trips


def _equity(raw: Any, initial: float) -> list[dict]:
    curve = (
        raw.equity_curve
        if hasattr(raw, "equity_curve")
        else raw.get("equity_curve")
        if isinstance(raw, dict)
        else None
    )
    if isinstance(curve, pd.DataFrame) and not curve.empty and "equity" in curve:
        frame, points = curve.reset_index(drop=True), []
        step = max(1, len(frame) // 600)
        for index in list(range(0, len(frame), step)) + (
            [len(frame) - 1] if (len(frame) - 1) % step else []
        ):
            row = frame.iloc[index]
            points.append(
                {
                    "t": str(row.get("datetime")) if row.get("datetime") is not None else None,
                    "equity": round(float(row["equity"]), 2),
                }
            )
        return points
    trades = [
        item if isinstance(item, dict) else vars(item)
        for item in (getattr(raw, "trades", []) or [])
    ]
    equity, points = initial, []
    for trade in trades:
        if trade.get("pnl") is not None:
            equity += float(trade["pnl"])
            points.append(
                {
                    "t": str(trade.get("exit_time") or trade.get("time") or trade.get("ts")),
                    "equity": round(equity, 2),
                }
            )
    return points


def backtest(
    name: str,
    req: BacktestRequest,
    *,
    klines: pd.DataFrame | None = None,
) -> dict:
    strategy_info(name)
    strategy = get_strategy(name, config={"enabled": True})
    if klines is None:
        try:
            klines = get_data_source(req.market).get_kline(
                req.symbol,
                req.interval,
                limit=req.limit,
            )
        except Exception as exc:  # noqa: BLE001 - normalize strategy plugin failures for the API
            return {"ok": False, "error": f"取 K 线失败: {exc}", "symbol": req.symbol}
    if klines is None or klines.empty:
        return {"ok": False, "error": "K 线为空（回测需要历史数据）", "symbol": req.symbol}
    quality = assess_ohlcv(klines)
    if not quality.usable:
        return {
            "ok": False,
            "error": f"K线质量不合格，已拒绝回测: {quality.reason or quality.status}",
            "symbol": req.symbol,
            "quality": quality.to_dict(),
        }
    # 按市场和周期换算年化 bar 数；AlphaMaster H1 与上游统一为 24*5*52。
    market = (req.market or "").lower()
    interval = (req.interval or "").lower()
    if market == "mt5":
        periods_per_year = {"1h": 6240, "4h": 1560}.get(interval, 252)
    elif market == "crypto":
        periods_per_year = {"1h": 8760, "4h": 2190}.get(interval, 365)
    else:
        periods_per_year = 252
    try:
        raw = strategy.backtest(
            klines,
            initial_capital=req.initial_capital,
            periods_per_year=periods_per_year,
            **req.params,
        )
    except Exception as exc:  # noqa: BLE001 - normalize strategy plugin failures for the API
        return {"ok": False, "error": str(exc), "symbol": req.symbol}
    if hasattr(raw, "to_summary"):
        summary = raw.to_summary()
        trades = [item if isinstance(item, dict) else vars(item) for item in raw.trades]
    else:
        trades = raw.get("trades", []) or []
        summary = {
            "engine": raw.get("engine", "unknown"),
            "final_equity": raw.get("final_equity", 0),
            "total_return": raw.get("total_return", 0),
            "max_drawdown": raw.get("max_drawdown", 0),
            "metrics": raw.get("metrics", {}),
            "n_trades": len(trades),
        }
    if trades and all(isinstance(item, dict) and "side" in item for item in trades):
        trades = _pair_round_trips(trades)
        summary = {**summary, "n_trades": len(trades)}
    return {
        "ok": True,
        "name": name,
        "symbol": req.symbol,
        "market": req.market,
        "summary": summary,
        "trades": trades,
        "equity": _equity(raw, req.initial_capital),
        "engine": raw.get("engine") if isinstance(raw, dict) else summary.get("engine"),
        "formulas": raw.get("formulas", []) if isinstance(raw, dict) else [],
    }


def live_status(name: str) -> dict:
    info = strategy_info(name)
    return {
        **info,
        "is_live": False,
        "note": "实盘需要交易所/券商 API 配置；未配置时为模拟态，不产生真实成交。",
    }


def live_tick(name: str) -> dict:
    info = strategy_info(name)
    try:
        state = get_strategy(name, config={"enabled": True}).live_tick()
    except Exception as exc:  # noqa: BLE001 - live strategy adapters are third-party code
        return {"ok": False, "mode": "paper", "error": str(exc)}
    return {
        "ok": True,
        "mode": "paper",
        "live_capable": info["live_capable"],
        "state": state,
        "note": "模拟态：未连接 broker，不产生真实成交。",
    }


def _resolve_pa_market(symbol: str, market: str | None = None) -> str:
    """为 PA 分析确定标的所属市场（与 PaAgentStrategy 逻辑一致）。"""
    if market:
        return market
    normalized = (symbol or "").strip().upper()
    if normalized.isdigit() and len(normalized) == 6:
        return "a_shares"
    if any(character.isalpha() for character in normalized) and (
        "-" in normalized or "/" in normalized or len(normalized) >= 6
    ):
        return "crypto"
    return "a_shares"


def pa_analyze(
    symbol: str,
    timeframe: str = "1h",
    market: str | None = None,
    research_run_id: str | None = None,
) -> dict:
    """对单个标的执行完整 PA 两阶段分析，返回 view-model 渲染数据。

    - 行情统一走 ``core.data_feed``
    - 分析复用 ``strategies.ai_analysis.pa_agent.two_stage.run_two_stage``
    - 视图渲染复用 ``pa_agent.view_models`` 共享层
    - 成功后把行情快照与模型输出写入 ``ResearchRun`` 证据，支持传入 ``research_run_id`` 复用同一运行
    - 失败时 ``ok=false`` 并附带错误信息，前端必须渲染空态/错误态，禁止填充替代数据
    """
    actual_market = _resolve_pa_market(symbol, market)

    def _fail(error: str) -> dict:
        if research_run_id:
            try:
                fail_module(research_run_id, "pa", error)
            except Exception:  # noqa: BLE001 - preserve the original analysis error
                logger.warning("PA 失败时写 ResearchRun 失败: %s", error)
        return {
            "ok": False,
            "error": error,
            "symbol": symbol,
            "timeframe": timeframe,
            "market": actual_market,
            "research_run_id": research_run_id,
        }

    try:
        source = get_data_source(actual_market)
        frame = source.get_kline(symbol, timeframe, limit=300)
    except Exception as exc:  # noqa: BLE001 - research persistence must not discard analysis
        logger.exception("PA 分析取 K 线失败 %s/%s", actual_market, symbol)
        return _fail(f"取 K 线失败: {exc}")

    if frame is None or frame.empty:
        return _fail("K 线为空")

    result = run_two_stage(symbol=symbol, timeframe=timeframe, klines=frame)
    if result.error and not result.stage2_json:
        return _fail(result.error)

    stage1 = result.stage1_json or {}
    stage2 = result.stage2_json or {}
    decision = stage2.get("decision") or {}
    terminal = stage2.get("terminal") or {}
    gate_trace = stage1.get("gate_trace", [])
    decision_trace = stage2.get("decision_trace", [])
    gate_result = str(stage1.get("gate_result", "proceed")).lower()
    gate_shortcircuited = gate_result in ("wait", "unknown")

    try:
        decision_view = build_decision_view(stage2_decision=decision, stage1_diagnosis=stage1)
        future_view = build_future_trend_view(stage2_decision=stage2)
        tree_view = build_decision_tree_view(
            gate_trace=gate_trace,
            decision_trace=decision_trace,
            terminal=terminal,
            gate_result=stage1.get("gate_result"),
            gate_shortcircuited=gate_shortcircuited,
        )
    except Exception as exc:
        logger.exception("PA view-model 渲染失败 %s", symbol)
        return _fail(f"分析成功但视图渲染失败: {exc}")

    # 持久化到研究运行：market_snapshot + model_output 证据
    run_id = research_run_id
    try:
        snapshot = dataframe_snapshot(frame)
        try:
            run_id = start_module(
                symbol=symbol,
                market=actual_market,
                timeframe=timeframe,
                module="pa",
                input_data={"kline_limit": 300, "timeframe": timeframe},
                run_id=research_run_id,
            )
        except ResearchContextMismatchError as exc:
            logger.warning("PA 研究上下文不一致，回退到新建 run: %s", exc)
            run_id = start_module(
                symbol=symbol,
                market=actual_market,
                timeframe=timeframe,
                module="pa",
                input_data={"kline_limit": 300, "timeframe": timeframe},
                run_id=None,
            )
        add_evidence(
            run_id,
            kind="market_snapshot",
            source=snapshot["source"],
            title=f"PA 输入 K 线 {symbol}",
            payload=snapshot,
        )
        add_evidence(
            run_id,
            kind="model_output",
            source=PA_PIPELINE_VERSION,
            title=f"PA 两阶段分析 {symbol}",
            payload={
                "stage1": stage1,
                "stage2": stage2,
                "pipeline_version": PA_PIPELINE_VERSION,
                "prompt_version": PA_PROMPT_VERSION,
                "usage": result.usage,
                "validation": result.validation,
            },
        )
        complete_module(
            run_id,
            "pa",
            {
                "pipeline_version": PA_PIPELINE_VERSION,
                "prompt_version": PA_PROMPT_VERSION,
                "stage1_complete": bool(stage1),
                "stage2_complete": bool(stage2),
                "validation": result.validation,
            },
        )
    except Exception as exc:  # noqa: BLE001 - research persistence must not discard analysis
        logger.warning("PA 结果持久化失败 %s: %s", symbol, exc)
        run_id = research_run_id

    return {
        "ok": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "market": actual_market,
        "decision": decision_view,
        "future": future_view,
        "tree": tree_view,
        "stage1": stage1,
        "stage2": stage2,
        "error": result.error,
        "research_run_id": run_id,
        "meta": {
            "kline_count": len(frame),
            "stage1_complete": bool(stage1),
            "stage2_complete": bool(stage2),
            "gate_shortcircuited": gate_shortcircuited,
            "usage": result.usage,
            "validation": result.validation,
            "validation_retries": sum(
                max(0, int(report.get("attempts", 0)) - 1) for report in result.validation.values()
            ),
        },
    }
