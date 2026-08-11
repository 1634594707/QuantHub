from __future__ import annotations

import pandas as pd
import pytest

from apps.api import database, store
from apps.api.domains.simulation import service as simulation_service
from apps.api.domains.simulation.schemas import (
    DemoRunRequest,
    SimulationFillCreate,
    SimulationOrderCreate,
)
from core.backtest.strategies_demo import run_strategy
from core.factor_dsl import FactorDslError


def _frame() -> pd.DataFrame:
    closes = [100 + index + (index % 5) * 0.4 for index in range(120)]
    return pd.DataFrame(
        {
            "datetime": pd.date_range("2025-01-01", periods=len(closes), freq="D"),
            "open": closes,
            "high": [value * 1.01 for value in closes],
            "low": [value * 0.99 for value in closes],
            "close": closes,
            "volume": [1_000 + index * 10 for index in range(len(closes))],
        }
    )


def test_demo_request_accepts_registered_dsl_metadata() -> None:
    request = DemoRunRequest(
        source="synthetic",
        factor="volatility_adjusted_momentum",
        factor_ast={
            "op": "div",
            "left": {"op": "pct_change", "value": {"op": "field", "name": "close"}, "periods": 20},
            "right": {
                "op": "rolling_std",
                "value": {
                    "op": "pct_change",
                    "value": {"op": "field", "name": "close"},
                    "periods": 1,
                },
                "window": 20,
            },
        },
        factor_label="波动率调整动量",
        factor_version="1.0.0",
    )

    assert request.factor == "volatility_adjusted_momentum"
    assert request.factor_label == "波动率调整动量"
    assert request.factor_version == "1.0.0"


def test_factor_follow_runs_safe_custom_dsl() -> None:
    result = run_strategy(
        "factor_follow",
        _frame(),
        factor_name="volatility_adjusted_momentum",
        factor_ast={
            "op": "rolling_zscore",
            "value": {
                "op": "div",
                "left": {
                    "op": "pct_change",
                    "value": {"op": "field", "name": "close"},
                    "periods": 20,
                },
                "right": {
                    "op": "rolling_std",
                    "value": {
                        "op": "pct_change",
                        "value": {"op": "field", "name": "close"},
                        "periods": 1,
                    },
                    "window": 20,
                },
            },
            "window": 40,
        },
        initial_capital=100_000,
    )

    assert result["engine"] == "event-signal"
    assert len(result["equity_curve"]) == 120
    assert result["final_equity"] > 0


def test_custom_dsl_rejects_unapproved_operator() -> None:
    with pytest.raises(FactorDslError, match="不允许的因子算子"):
        run_strategy(
            "factor_follow",
            _frame(),
            factor_name="unsafe",
            factor_ast={"op": "python_eval", "source": "future_return"},
        )


def test_isolated_factor_account_fill_does_not_write_shared_ledger(tmp_path, monkeypatch) -> None:
    database.dispose_engines()
    monkeypatch.setattr(store, "_DB", tmp_path / "store.db")
    store._init()
    order = simulation_service.create_order(
        SimulationOrderCreate(
            symbol="BTCUSDT",
            market="crypto",
            side="buy",
            quantity=0.01,
            account_id="factor-factory:test-run",
            factor_key="volatility_adjusted_momentum",
            factor_version="1.0.0",
            research_run_id="test-run",
            theoretical_price=60_000,
        )
    )

    filled = simulation_service.fill_isolated_order(
        order["id"],
        SimulationFillCreate(quantity=0.01, price=60_000, fee_rate=0.0003),
    )

    execution = filled["executions"][0]
    assert execution["ledger_sync_status"] == "isolated"
    assert execution["ledger_trade_id"] is None
    assert (
        store.list_simulation_orders(account_id="factor-factory:test-run")[0]["id"] == order["id"]
    )
    database.dispose_engines()
