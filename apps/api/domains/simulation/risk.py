"""Fail-closed risk evaluation for paper order intents."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.config import get_config

RISK_RULE_VERSION = "simulation-risk-v2"
MARKET_MAX_AGE_SECONDS = 300
ACCOUNT_MAX_AGE_SECONDS = 90
_ONLINE_PRIMARY_SOURCES: dict[str, frozenset[str]] = {
    "a_shares": frozenset({"akshare", "eastmoney", "tencent"}),
    "us_stocks": frozenset({"tencent", "yahoo"}),
    "crypto": frozenset({"okx"}),
}
_EXECUTABLE_MARKET_QUALITIES = {"live", "closed_bar", "verified"}
_HISTORICAL_EXCEPTION = {
    "kind": "factor_factory_isolated_closed_bar",
    "scope": "isolated",
    "authorized_by": "simulation_service",
    "realtime_executable": False,
}


class PaperOrderIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    intent_id: str
    account_id: str
    symbol: str
    market: str
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit"]
    quantity: float = Field(gt=0)
    limit_price: float | None = Field(default=None, gt=0)
    signal_id: str | None = None
    research_run_id: str | None = None
    reduce_only: bool = False

    @field_validator("quantity", "limit_price")
    @classmethod
    def reject_non_finite_numbers(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("订单数值必须是有限数")
        return value


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(float(value), UTC)
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _age_seconds(value: Any, now: datetime) -> float | None:
    parsed = _parse_time(value)
    return max(0.0, (now - parsed).total_seconds()) if parsed else None


def _constraint(cost_profile: dict[str, Any], key: str) -> Any:
    for item in cost_profile.get("execution_constraints", []):
        if item.get("key") == key:
            return item.get("value")
    return None


def _multiple(value: float, step: float) -> bool:
    if step <= 0:
        return False
    ratio = value / step
    return math.isclose(ratio, round(ratio), rel_tol=0, abs_tol=1e-8)


def _source_name(value: Any) -> str:
    return str(value or "").strip().lower()


def _configured_primary_source(market: str) -> str:
    try:
        primary = get_config(market).get("data_sources", {}).get("primary")
    except Exception:  # noqa: BLE001 - configuration failures must fail closed
        return ""
    return _source_name(primary)


def _is_factor_factory_account(account_id: str) -> bool:
    prefix = "factor-factory:"
    suffix = account_id.removeprefix(prefix)
    return (
        account_id.startswith(prefix)
        and bool(suffix)
        and all(char.isalnum() or char in {"-", "_", "."} for char in suffix)
    )


def _is_historical_simulation_exception(
    intent: PaperOrderIntent, market_snapshot: dict[str, Any]
) -> bool:
    """Allow exactly the internal factor-factory isolated closed-bar workflow.

    This is not a price-quality upgrade. It is an audit-labelled historical
    simulation exception, created only by ``simulation.service`` after it has
    validated the internal call boundary.
    """
    exception = market_snapshot.get("execution_exception")
    return (
        _is_factor_factory_account(intent.account_id)
        and market_snapshot.get("snapshot_kind") == "historical_closed_bar"
        and _source_name(market_snapshot.get("source")) == "factor_factory.closed_bar"
        and _source_name(market_snapshot.get("quality_status")) == "closed_bar"
        and isinstance(exception, dict)
        and all(exception.get(key) == value for key, value in _HISTORICAL_EXCEPTION.items())
    )


def evaluate_risk(
    intent: PaperOrderIntent,
    *,
    market_snapshot: dict[str, Any],
    account_snapshot: dict[str, Any],
    open_orders: list[dict[str, Any]],
    cost_profile: dict[str, Any],
    research_decision: dict[str, Any] | None = None,
    limits: dict[str, float] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    evaluated_at = (now or datetime.now(UTC)).astimezone(UTC)
    configured_limits = {
        "max_position_per_symbol": 0.15,
        "max_total_exposure": 0.8,
        **(limits or {}),
    }
    checks: list[dict[str, Any]] = []

    def check(
        code: str, passed: bool, *, actual: Any = None, limit: Any = None, action: str
    ) -> None:
        checks.append(
            {
                "code": code,
                "status": "passed" if passed else "failed",
                "actual": actual,
                "limit": limit,
                "reevaluate_action": action,
            }
        )

    def excepted(code: str, *, actual: Any = None, action: str) -> None:
        checks.append(
            {
                "code": code,
                "status": "excepted",
                "actual": actual,
                "limit": None,
                "reevaluate_action": action,
            }
        )

    price = market_snapshot.get("price")
    price_ok = isinstance(price, (int, float)) and math.isfinite(float(price)) and float(price) > 0
    bar_at = market_snapshot.get("bar_at") or market_snapshot.get("observed_at")
    market_age = _age_seconds(bar_at, evaluated_at)
    source = _source_name(market_snapshot.get("source"))
    primary_source = _source_name(market_snapshot.get("primary_source"))
    configured_primary = _configured_primary_source(intent.market)
    source_role = _source_name(market_snapshot.get("source_role"))
    cache_status = _source_name(market_snapshot.get("cache_status"))
    transport = _source_name(market_snapshot.get("transport"))
    quality = _source_name(market_snapshot.get("quality_status"))
    historical_exception = _is_historical_simulation_exception(intent, market_snapshot)
    source_is_online_primary = (
        bool(configured_primary)
        and source == primary_source == configured_primary
        and source in _ONLINE_PRIMARY_SOURCES.get(intent.market, frozenset())
        and source_role == "primary"
        and transport == "online"
        and cache_status == "miss"
    )
    check(
        "MARKET_PRICE_MISSING",
        price_ok,
        actual=price,
        action="刷新行情后重新预览",
    )
    if historical_exception:
        excepted(
            "MARKET_HISTORICAL_SIMULATION_EXCEPTION",
            actual={
                "source": source,
                "bar_at": bar_at,
                "execution_exception": market_snapshot.get("execution_exception"),
                "realtime_executable": False,
            },
            action="该订单仅可在 factor-factory 隔离历史模拟中成交，不可转为实时或账本执行",
        )
    else:
        check(
            "MARKET_BAR_TIME_MISSING",
            _parse_time(bar_at) is not None,
            actual=bar_at,
            action="获取带行情 bar 时间的可执行行情",
        )
        check(
            "MARKET_PRICE_STALE",
            market_age is not None and market_age <= MARKET_MAX_AGE_SECONDS,
            actual=market_age,
            limit=MARKET_MAX_AGE_SECONDS,
            action="等待新的可执行行情",
        )
        check(
            "MARKET_PRICE_SOURCE",
            source_is_online_primary,
            actual={
                "source": source,
                "primary_source": primary_source,
                "configured_primary": configured_primary,
                "source_role": source_role,
                "transport": transport,
            },
            action="使用明确的在线 primary 行情",
        )
        check(
            "MARKET_PRICE_CACHE",
            cache_status == "miss",
            actual=cache_status,
            limit="miss",
            action="绕过缓存并取得同源 online primary 行情",
        )
        check(
            "MARKET_PRICE_QUALITY",
            quality in _EXECUTABLE_MARKET_QUALITIES,
            actual=quality,
            action="修复行情质量问题",
        )

    account_age = _age_seconds(account_snapshot.get("observed_at"), evaluated_at)
    check(
        "ACCOUNT_SNAPSHOT_STALE",
        account_age is not None and account_age <= ACCOUNT_MAX_AGE_SECONDS,
        actual=account_age,
        limit=ACCOUNT_MAX_AGE_SECONDS,
        action="刷新账户快照",
    )
    check(
        "ACCOUNT_RECONCILIATION_FAILED",
        account_snapshot.get("reconciled") is True,
        actual=account_snapshot.get("reconciliation_issues", []),
        action="完成账户对账",
    )
    check(
        "COST_PROFILE_INCOMPLETE",
        cost_profile.get("complete") is True,
        actual=cost_profile.get("gaps"),
        action="补全适用成本档案",
    )
    check(
        "COST_PROFILE_MARKET_MISMATCH",
        cost_profile.get("market") == intent.market,
        actual=cost_profile.get("market"),
        limit=intent.market,
        action="选择同市场成本档案",
    )
    if intent.research_run_id:
        check(
            "RESEARCH_DECISION_BLOCKED",
            bool(research_decision and research_decision.get("execution_eligible") is True),
            actual=(research_decision or {}).get("direction"),
            action="补充研究证据并重新评估",
        )
        expected_direction = "long" if intent.side == "buy" else "short"
        check(
            "RESEARCH_DIRECTION_MISMATCH",
            bool(
                research_decision
                and research_decision.get("execution_eligible") is True
                and research_decision.get("direction") == expected_direction
            ),
            actual=(research_decision or {}).get("direction"),
            limit=expected_direction,
            action="按统一研究决策修正订单方向",
        )

    equity = float(account_snapshot.get("equity") or 0)
    cash = float(account_snapshot.get("cash") or 0)
    positions = account_snapshot.get("positions") or []
    position = next(
        (
            item
            for item in positions
            if item.get("symbol") == intent.symbol and item.get("market") == intent.market
        ),
        None,
    )
    current_quantity = float((position or {}).get("quantity") or 0)
    signed_quantity = intent.quantity if intent.side == "buy" else -intent.quantity
    projected_quantity = current_quantity + signed_quantity
    if intent.reduce_only:
        reduces = (
            current_quantity > 0 and intent.side == "sell" and intent.quantity <= current_quantity
        ) or (
            current_quantity < 0
            and intent.side == "buy"
            and intent.quantity <= abs(current_quantity)
        )
        check(
            "REDUCE_ONLY_VIOLATION",
            reduces,
            actual={"current_quantity": current_quantity, "requested": intent.quantity},
            action="将数量限制在现有持仓内",
        )

    execution_price = (
        max(float(price), float(intent.limit_price))
        if price_ok and intent.limit_price is not None
        else float(price)
        if price_ok
        else 0.0
    )
    order_notional = intent.quantity * execution_price
    cost_bps = float(cost_profile.get("total_transaction_cost_bps") or 0)
    estimated_cost = order_notional * cost_bps / 10_000
    current_value = current_quantity * execution_price
    projected_value = projected_quantity * execution_price
    recorded_gross = sum(abs(float(item.get("market_value") or 0)) for item in positions)
    gross_before = (
        recorded_gross - abs(float((position or {}).get("market_value") or 0)) + abs(current_value)
    )
    open_exposure = 0.0
    open_cash = 0.0
    for order in open_orders:
        remaining = max(
            0.0, float(order.get("quantity") or 0) - float(order.get("filled_quantity") or 0)
        )
        reference = float(order.get("limit_price") or execution_price)
        open_exposure += abs(remaining * reference)
        if order.get("side") == "buy":
            open_cash += remaining * reference
    gross_after = gross_before + open_exposure - abs(current_value) + abs(projected_value)
    cash_after = (
        cash - open_cash - order_notional - estimated_cost
        if intent.side == "buy"
        else cash - open_cash
    )

    check(
        "POSITIVE_EQUITY_REQUIRED",
        equity > 0,
        actual=equity,
        action="修复账户权益后重试",
    )
    symbol_weight = abs(projected_value) / equity if equity > 0 else math.inf
    total_weight = gross_after / equity if equity > 0 else math.inf
    check(
        "SYMBOL_EXPOSURE_LIMIT",
        intent.reduce_only or symbol_weight <= configured_limits["max_position_per_symbol"],
        actual=symbol_weight,
        limit=configured_limits["max_position_per_symbol"],
        action="降低订单数量",
    )
    check(
        "TOTAL_EXPOSURE_LIMIT",
        intent.reduce_only or total_weight <= configured_limits["max_total_exposure"],
        actual=total_weight,
        limit=configured_limits["max_total_exposure"],
        action="降低组合敞口",
    )
    if intent.side == "buy" and not intent.reduce_only:
        check(
            "INSUFFICIENT_CASH",
            cash_after >= 0,
            actual=cash - open_cash,
            limit=order_notional + estimated_cost,
            action="降低数量或补充现金",
        )

    lot_size = _constraint(cost_profile, "lot_size")
    if lot_size is not None:
        check(
            "LOT_SIZE_INVALID",
            _multiple(intent.quantity, float(lot_size)),
            actual=intent.quantity,
            limit=lot_size,
            action="按整手调整数量",
        )
    quantity_step = _constraint(cost_profile, "quantity_step")
    if quantity_step is not None:
        check(
            "QUANTITY_STEP_INVALID",
            _multiple(intent.quantity, float(quantity_step)),
            actual=intent.quantity,
            limit=quantity_step,
            action="按数量步长调整",
        )
    price_tick = _constraint(cost_profile, "price_tick")
    if intent.limit_price is not None and price_tick is not None:
        check(
            "PRICE_TICK_INVALID",
            _multiple(intent.limit_price, float(price_tick)),
            actual=intent.limit_price,
            limit=price_tick,
            action="按价格步长调整",
        )

    failed = [item for item in checks if item["status"] == "failed"]
    snapshot = {
        "market": market_snapshot,
        "account": account_snapshot,
        "open_order_count": len(open_orders),
        "cost_profile": cost_profile,
        "research_decision": research_decision,
    }
    calculation = {
        "current_quantity": current_quantity,
        "projected_quantity": projected_quantity,
        "execution_price": execution_price or None,
        "order_notional": order_notional if execution_price else None,
        "estimated_cost": estimated_cost if execution_price else None,
        "cash_before": cash,
        "cash_after": cash_after if execution_price else None,
        "gross_exposure_before": gross_before,
        "gross_exposure_after": gross_after if execution_price else None,
        "symbol_weight_after": symbol_weight if math.isfinite(symbol_weight) else None,
        "total_weight_after": total_weight if math.isfinite(total_weight) else None,
    }
    fingerprint_payload = {
        "intent": intent.model_dump(mode="json"),
        "snapshot": snapshot,
        "calculation": calculation,
        "rule_version": RISK_RULE_VERSION,
    }
    canonical = json.dumps(
        fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return {
        "risk_evaluated": True,
        "can_submit": not failed,
        "outcome": "approved" if not failed else "rejected",
        "reason_codes": [item["code"] for item in failed],
        "checks": checks,
        "snapshot": snapshot,
        "market_execution_class": (
            "historical_closed_bar_simulation"
            if historical_exception
            else "online_primary"
            if source_is_online_primary and quality in _EXECUTABLE_MARKET_QUALITIES
            else "unavailable"
        ),
        "calculation": calculation,
        "evaluated_at": evaluated_at.isoformat(),
        "rule_version": RISK_RULE_VERSION,
        "input_fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }
