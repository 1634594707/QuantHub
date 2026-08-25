from __future__ import annotations

import sys
import types
from unittest.mock import Mock

import pandas as pd
import pytest

from strategies.mt5.alphamaster import strategy as alphamaster_strategy


class _PrimarySource:
    name = "local_parquet"

    def __init__(self, values: dict[str, pd.DataFrame | Exception]) -> None:
        self.values = values
        self.calls: list[str] = []

    def get_kline(self, symbol: str, timeframe: str, *, limit: int):
        self.calls.append(symbol)
        value = self.values[symbol]
        if isinstance(value, Exception):
            raise value
        return value


def _frame(rows: int = 50) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100.0] * rows,
            "high": [101.0] * rows,
            "low": [99.0] * rows,
            "close": [100.0] * rows,
            "volume": [10.0] * rows,
        }
    )


def _strategy() -> alphamaster_strategy.AlphaMasterStrategy:
    return alphamaster_strategy.AlphaMasterStrategy(config={"enabled": True})


def test_alphamaster_primary_kline_failure_rejects_whole_scan(monkeypatch) -> None:
    source = _PrimarySource(
        {
            "EURUSD": _frame(),
            "USDJPY": ConnectionError("primary unavailable"),
        }
    )
    monkeypatch.setattr("core.data_feed.factory.get_data_source", lambda market: source)
    monkeypatch.setattr(alphamaster_strategy, "validate_formulas", lambda formulas: formulas)
    strategy = _strategy()
    strategy.publish = Mock()

    signals = strategy.produce(symbols=list(source.values), formulas=[[0]])

    assert signals == []
    assert source.calls == ["EURUSD", "USDJPY"]
    strategy.publish.assert_not_called()
    assert strategy.last_signal_rejection["code"] == "market_data_incomplete"
    assert strategy.last_signal_rejection["details"]["source"] == "local_parquet"
    assert strategy.last_signal_rejection["details"]["failed_symbols"] == ["USDJPY"]
    assert strategy.last_report["execution_eligible"] is False


def test_alphamaster_provided_partial_kline_map_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(alphamaster_strategy, "validate_formulas", lambda formulas: formulas)
    strategy = _strategy()
    strategy.publish = Mock()

    signals = strategy.produce(
        symbols=["EURUSD", "USDJPY"],
        formulas=[[0]],
        klines_map={"EURUSD": _frame()},
    )

    assert signals == []
    strategy.publish.assert_not_called()
    assert strategy.last_signal_rejection["code"] == "market_data_incomplete"
    assert strategy.last_signal_rejection["details"]["source"] == "provided"
    assert strategy.last_signal_rejection["details"]["failed_symbols"] == ["USDJPY"]


def test_alphamaster_rejects_missing_ohlcv_before_feature_engine(monkeypatch) -> None:
    monkeypatch.setattr(alphamaster_strategy, "validate_formulas", lambda formulas: formulas)
    strategy = _strategy()
    strategy.publish = Mock()
    frame = _frame().drop(columns=["volume"])

    signals = strategy.produce(
        symbols=["EURUSD"],
        formulas=[[0]],
        klines_map={"EURUSD": frame},
    )

    assert signals == []
    strategy.publish.assert_not_called()
    assert "缺少 OHLCV 列" in strategy.last_signal_rejection["details"]["reason"]


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda frame: frame.assign(close=0.0), "非正价格"),
        (lambda frame: frame.assign(high=98.0), "高低价关系无效"),
        (lambda frame: frame.assign(volume=-1.0), "负成交量"),
    ],
)
def test_alphamaster_rejects_invalid_ohlcv_geometry_before_feature_engine(
    monkeypatch, mutate, expected
) -> None:
    monkeypatch.setattr(alphamaster_strategy, "validate_formulas", lambda formulas: formulas)
    strategy = _strategy()
    strategy.publish = Mock()

    signals = strategy.produce(
        symbols=["EURUSD"],
        formulas=[[0]],
        klines_map={"EURUSD": mutate(_frame())},
    )

    assert signals == []
    strategy.publish.assert_not_called()
    assert expected in strategy.last_signal_rejection["details"]["reason"]


def test_alphamaster_backtest_rejects_formula_failure_instead_of_partial_average(
    monkeypatch,
) -> None:
    torch = types.ModuleType("torch")
    factors = types.ModuleType("model_core.features")
    vm_module = types.ModuleType("model_core.vm")

    class _FeatureEngineer:
        @staticmethod
        def compute_features(raw_dict):
            return object()

    class _StackVM:
        def execute(self, formula, feat):
            raise RuntimeError("formula unavailable")

    factors.MT5FeatureEngineer = _FeatureEngineer
    vm_module.StackVM = _StackVM
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "model_core.features", factors)
    monkeypatch.setitem(sys.modules, "model_core.vm", vm_module)

    strategy = _strategy()
    monkeypatch.setattr(strategy, "_df_to_raw_dict", lambda df: {})
    frame = _frame()
    frame["datetime"] = pd.date_range("2026-01-01", periods=len(frame), freq="h")

    with pytest.raises(alphamaster_strategy.FormulaEvaluationError, match="公式执行失败"):
        strategy.backtest(frame, formulas=[[0]])


def test_alphamaster_stack_vm_rejects_nonfinite_intermediate_without_sentinel() -> None:
    """NaN/Inf must abort the vendored formula VM, not be coerced to a score."""
    torch = pytest.importorskip("torch")
    alphamaster_strategy._inject_alpha_master_root()
    from model_core.vm import StackVM
    from model_core.vocab import FORMULA_VOCAB

    features = torch.full((1, FORMULA_VOCAB.feature_count, 1), float("nan"))
    add_token = FORMULA_VOCAB.operator_offset

    assert StackVM().execute([0, 0, add_token], features) is None
