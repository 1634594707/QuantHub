from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from apps.api import database, store
from apps.api.domains.factor_factory import service as factor_factory_service
from apps.api.domains.simulation import service as simulation_service
from apps.api.domains.simulation.schemas import SimulationFillCreate, SimulationOrderCreate
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


def test_factor_follow_requires_an_explicit_factor() -> None:
    with pytest.raises(ValueError, match="必须提供已登记因子"):
        run_strategy("factor_follow", _frame())


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


def test_backtest_rejects_nonfinite_signal_after_warmup() -> None:
    frame = _frame()
    signal = pd.Series([float("nan")] * 20 + [0.5] * (len(frame) - 21) + [float("nan")])

    with pytest.raises(ValueError, match="预热区之后包含缺失或非有限值"):
        from core.backtest.strategies_demo import run_signal_backtest

        run_signal_backtest(frame, signal)


def test_backtest_allows_only_leading_warmup_nan() -> None:
    frame = _frame()
    signal = pd.Series([float("nan")] * 20 + [0.5] * (len(frame) - 20))
    from core.backtest.strategies_demo import run_signal_backtest

    result = run_signal_backtest(frame, signal)
    assert result["engine"] == "event-signal"


def test_factor_factory_signal_gate_rejects_nonfinite_tail_without_zero_fallback() -> None:
    with pytest.raises(ValueError, match="预热区之后包含缺失或非有限信号"):
        factor_factory_service._validated_factor_signal(
            pd.Series([float("nan"), 0.2, float("nan")]),
            context="测试因子信号",
        )


def test_factor_factory_signal_gate_allows_leading_warmup_only() -> None:
    signal = factor_factory_service._validated_factor_signal(
        pd.Series([float("nan"), float("nan"), 0.2, 0.1]),
        context="测试因子信号",
    )
    assert pd.isna(signal.iloc[0]) and float(signal.iloc[-1]) == 0.1


def test_isolated_factor_account_fill_does_not_write_shared_ledger(tmp_path, monkeypatch) -> None:
    database.dispose_engines()
    monkeypatch.setattr(store, "_DB", tmp_path / "store.db")
    store._init()
    monkeypatch.setattr(
        simulation_service.portfolio_service,
        "latest_close_snapshot",
        lambda *_: {
            "price": 60_000.0,
            "source": "okx",
            "primary_source": "okx",
            "source_role": "primary",
            "cache_status": "miss",
            "transport": "online",
            "data_semantics": "bar_snapshot",
            "bar_at": datetime.now(UTC).isoformat(),
            "observed_at": datetime.now(UTC).isoformat(),
            "quality_status": "closed_bar",
            "error": None,
        },
    )
    closed_bar_at = datetime.now(UTC).isoformat()
    order = simulation_service.create_order(
        SimulationOrderCreate(
            symbol="BTCUSDT",
            market="crypto",
            side="buy",
            quantity=0.01,
            account_id="factor-factory:test-run",
            factor_key="volatility_adjusted_momentum",
            factor_version="1.0.0",
            theoretical_price=60_000,
        ),
        trusted_market_snapshot={
            "price": 60_000.0,
            "event_time": closed_bar_at,
            "observed_at": closed_bar_at,
            "source": "factor_factory.closed_bar",
            "quality_status": "closed_bar",
        },
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
