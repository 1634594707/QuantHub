"""Versioned server-side trading cost profile registry."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from core.trading_costs import (
    TradingCostComponent,
    TradingCostProfile,
    TradingExecutionConstraint,
)


def _component(
    market: str,
    key: str,
    bps: float,
    source_url: str,
    *,
    charge_basis: str = "per_fill",
) -> TradingCostComponent:
    captured = datetime(2026, 8, 16, tzinfo=UTC)
    return TradingCostComponent(
        key=key,
        label=key.replace("_", " ").title(),
        value=bps,
        unit="bps",
        normalized_bps=bps,
        source_url=source_url,
        source_captured_at=captured,
        effective_from=date(2026, 1, 1),
        market=market,
        charge_basis=charge_basis,
    )


def _constraint(
    key: str, value: str | float | bool, source_url: str, unit: str
) -> TradingExecutionConstraint:
    captured = datetime(2026, 8, 16, tzinfo=UTC)
    return TradingExecutionConstraint(
        key=key,
        label=key.replace("_", " ").title(),
        value=value,
        unit=unit,
        source_url=source_url,
        source_captured_at=captured,
        effective_from=date(2026, 1, 1),
    )


REFERENCE_PROFILES: tuple[TradingCostProfile, ...] = (
    TradingCostProfile(
        profile_id="a-shares-reference",
        version="1.0.0",
        name="A 股研究参考成本",
        market="a_shares",
        source="exchange_and_clearing_reference",
        effective_from=date(2026, 1, 1),
        participation_rate=0.1,
        components=[
            _component(
                "a_shares",
                "commission",
                3.0,
                "https://www.sse.com.cn/services/tradingservice/charge/",
            ),
            _component("a_shares", "stamp_tax", 5.0, "https://www.chinatax.gov.cn/"),
            _component(
                "a_shares", "transfer_fee", 0.1, "https://www.chinaclear.cn/zdjs/fbzx/fee.shtml"
            ),
        ],
        execution_constraints=[
            _constraint(
                "limit_up", True, "https://www.sse.com.cn/assortment/stock/trading/", "boolean"
            ),
            _constraint(
                "limit_down", True, "https://www.sse.com.cn/assortment/stock/trading/", "boolean"
            ),
            _constraint(
                "suspended", False, "https://www.sse.com.cn/assortment/stock/trading/", "boolean"
            ),
            _constraint(
                "lot_size", 100, "https://www.sse.com.cn/assortment/stock/trading/", "shares"
            ),
        ],
    ),
    TradingCostProfile(
        profile_id="us-stocks-reference",
        version="1.0.0",
        name="美股研究参考成本",
        market="us_stocks",
        source="regulator_and_broker_reference",
        effective_from=date(2026, 1, 1),
        participation_rate=0.05,
        components=[
            _component("us_stocks", "spread", 2.0, "https://www.sec.gov/marketstructure"),
            _component(
                "us_stocks",
                "commission",
                0.5,
                "https://www.finra.org/rules-guidance/key-topics/trading-fees",
            ),
            _component(
                "us_stocks",
                "sec_fee",
                0.3,
                "https://www.sec.gov/rules-regulations/fee-rate-advisories",
            ),
            _component(
                "us_stocks",
                "finra_taf",
                0.2,
                "https://www.finra.org/rules-guidance/rulebooks/corporate-organization/section-1-member-regulatory-fees",
            ),
        ],
        execution_constraints=[
            _constraint(
                "corporate_action_adjusted", True, "https://www.nasdaqtrader.com/", "boolean"
            ),
        ],
    ),
    TradingCostProfile(
        profile_id="okx-reference",
        version="1.0.0",
        name="OKX 研究参考成本",
        market="crypto",
        source="okx_public_reference",
        effective_from=date(2026, 1, 1),
        participation_rate=0.05,
        components=[
            _component("crypto", "fee_tier", 5.0, "https://www.okx.com/fees"),
            _component(
                "crypto",
                "funding_rate",
                1.0,
                "https://www.okx.com/docs-v5/en/#public-data-rest-api-get-funding-rate",
                charge_basis="per_bar",
            ),
            _component(
                "crypto",
                "spread",
                1.0,
                "https://www.okx.com/docs-v5/en/#order-book-trading-market-data",
            ),
            _component("crypto", "slippage", 2.0, "https://www.okx.com/docs-v5/en/"),
        ],
        execution_constraints=[
            _constraint(
                "quantity_step",
                0.001,
                "https://www.okx.com/docs-v5/en/#public-data-rest-api-get-instruments",
                "contracts",
            ),
            _constraint(
                "price_tick",
                0.1,
                "https://www.okx.com/docs-v5/en/#public-data-rest-api-get-instruments",
                "quote_currency",
            ),
        ],
    ),
)


def list_reference_profiles(market: str | None = None) -> list[TradingCostProfile]:
    return [profile for profile in REFERENCE_PROFILES if market is None or profile.market == market]


def select_reference_profile(
    market: str,
    *,
    profile_id: str | None = None,
    version: str | None = None,
    account_scope: str | None = None,
    effective_on: date | None = None,
) -> TradingCostProfile:
    target_date = effective_on or datetime.now(UTC).date()
    matches = [
        item
        for item in REFERENCE_PROFILES
        if item.market == market
        and (profile_id is None or item.profile_id == profile_id)
        and (version is None or item.version == version)
        and (item.account_scope is None or item.account_scope == account_scope)
        and (item.effective_from is None or item.effective_from <= target_date)
        and (item.effective_to is None or item.effective_to >= target_date)
    ]
    if not matches:
        raise LookupError(f"没有适用于 {market} 的成本档案")
    return max(matches, key=lambda item: (item.version, item.profile_id))


def legacy_profile(market: str, commission_bps: float) -> dict[str, Any]:
    """Represent old scalar costs without pretending they are execution complete."""
    return {
        "profile_id": "legacy-commission-bps",
        "version": "0",
        "market": market,
        "total_transaction_cost_bps": float(commission_bps),
        "content_hash": None,
        "complete": False,
        "compatibility_status": "legacy_incomplete",
        "gaps": {"components": ["full_cost_components"], "constraints": ["execution_rules"]},
    }
