from __future__ import annotations

from apps.api import store
from apps.api.domains.instrument import service as instrument_service


def list_presets() -> dict[str, list[dict]]:
    return store.list_presets()


def save_preset(strategy: str, name: str, params: dict) -> dict:
    return store.save_preset(strategy, name, params)


def delete_preset(strategy: str, preset_id: str) -> None:
    store.delete_preset(strategy, preset_id)


def list_runs() -> list[dict]:
    return store.list_runs()


def save_run(strategy: str, params: dict, result: dict) -> dict:
    return store.add_run(strategy, params, result)


def persist_signals(signals: list[dict]) -> list[dict]:
    rows = []
    for signal in signals:
        instrument = instrument_service.resolve_strict(
            str(signal["symbol"]),
            str(signal["market"]),
        )
        rows.append(
            store.add_signal(
                {
                    **signal,
                    "symbol": instrument.code,
                    "market": instrument.market,
                    "instrument_id": instrument.instrument_id,
                }
            )
        )
    if rows:
        store.prune_signals(keep=2000)
    return rows
