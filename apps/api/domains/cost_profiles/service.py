from __future__ import annotations

from apps.api import store
from core.cost_profiles import list_reference_profiles
from core.trading_costs import TradingCostProfile


def _seed_reference_profiles() -> None:
    for profile in list_reference_profiles():
        store.save_trading_cost_profile(profile.immutable_snapshot())


def register_profile(profile: TradingCostProfile) -> dict:
    return store.save_trading_cost_profile(profile.immutable_snapshot())


def list_profiles(*, market: str | None = None, account_scope: str | None = None) -> list[dict]:
    _seed_reference_profiles()
    return store.list_trading_cost_profiles(market=market, account_scope=account_scope)


def get_profile(profile_id: str, version: str | None = None) -> dict | None:
    _seed_reference_profiles()
    return store.get_trading_cost_profile(profile_id, version)
