from __future__ import annotations

from apps.api import store


def list_allocations() -> list[dict]:
    return store.list_allocs()


def create_allocation(
    *, strategy: str, weight: float, symbol: str | None, live: bool, note: str | None
) -> dict:
    return store.save_alloc(strategy, weight, symbol, live, note)


def delete_allocation(allocation_id: str) -> None:
    store.delete_alloc(allocation_id)


def update_live(allocation_id: str, live: bool) -> None:
    store.update_alloc_live(allocation_id, live)


def list_holdings() -> list[dict]:
    return store.list_holdings()


def add_holding(
    code: str, name: str, shares: float, cost: float, market: str, instrument_id: str | None = None
) -> dict:
    return store.add_holding(code, name, shares, cost, market, instrument_id)


def update_holding(holding_id: str, patch: dict) -> dict | None:
    return store.update_holding(holding_id, patch)


def delete_holding(holding_id: str) -> bool:
    return store.delete_holding(holding_id)


def list_watchlist() -> list[dict]:
    return store.list_watchlist()


def add_watchlist(symbol: str, name: str, market: str, instrument_id: str | None = None) -> dict:
    return store.add_watchlist(symbol, name, market, instrument_id)


def update_watchlist(watch_id: str, patch: dict) -> dict | None:
    return store.update_watchlist(watch_id, patch)


def delete_watchlist(watch_id: str) -> bool:
    return store.delete_watchlist(watch_id)
