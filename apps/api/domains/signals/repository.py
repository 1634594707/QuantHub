from __future__ import annotations

from apps.api import store


def list_signals(
    *, limit: int, source: str | None, market: str | None, status: str | None
) -> list[dict]:
    return store.list_signals(limit=limit, source=source, market=market, status=status)


def list_signals_page(
    *,
    limit: int,
    source: str | None,
    market: str | None,
    status: str | None,
    cursor: str | None,
) -> dict:
    return store.list_signals_page(
        limit=limit,
        source=source,
        market=market,
        status=status,
        cursor=cursor,
    )


def get_signal(signal_id: str) -> dict | None:
    return store.get_signal(signal_id)


def add_signal(payload: dict) -> dict:
    return store.add_signal(payload)


def prune_signals(keep: int) -> None:
    store.prune_signals(keep=keep)


def delete_signal(signal_id: str) -> None:
    store.delete_signal(signal_id)


def update_status(
    signal_id: str, *, status: str, note: str | None = None, order_id: str | None = None
) -> dict | None:
    return store.update_signal_status(
        signal_id,
        status=status,
        note=note,
        order_id=order_id,
    )
