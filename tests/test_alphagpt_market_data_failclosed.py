from __future__ import annotations

import sys
import types
from unittest.mock import Mock

import pandas as pd
import pytest

from strategies.crypto.alphagpt.strategy import AlphaGptStrategy, FormulaEvaluationError


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.0],
            "volume": [10.0],
        }
    )


def test_alphagpt_rejects_missing_symbol_klines_without_publishing() -> None:
    strategy = AlphaGptStrategy(config={"enabled": True})
    strategy.publish = Mock()

    signals = strategy.produce(
        symbols=["SOL/USDT", "BONK/USDT"],
        formulas=[[0]],
        klines_map={"SOL/USDT": _frame()},
    )

    assert signals == []
    strategy.publish.assert_not_called()
    assert strategy.last_signal_rejection["code"] == "market_data_incomplete"
    assert strategy.last_signal_rejection["details"]["failed_symbols"] == ["BONK/USDT"]
    assert strategy.last_report["execution_eligible"] is False


def test_alphagpt_rejects_empty_klines_without_publishing() -> None:
    strategy = AlphaGptStrategy(config={"enabled": True})
    strategy.publish = Mock()

    signals = strategy.produce(
        symbols=["SOL/USDT"],
        formulas=[[0]],
        klines_map={"SOL/USDT": pd.DataFrame()},
    )

    assert signals == []
    strategy.publish.assert_not_called()
    assert strategy.last_signal_rejection["code"] == "market_data_incomplete"
    assert strategy.last_signal_rejection["details"]["failed_symbols"] == ["SOL/USDT"]


def test_alphagpt_missing_kline_map_is_explicitly_rejected() -> None:
    strategy = AlphaGptStrategy(config={"enabled": True})
    strategy.publish = Mock()

    signals = strategy.produce(symbols=["SOL/USDT"], formulas=[[0]])

    assert signals == []
    strategy.publish.assert_not_called()
    assert strategy.last_signal_rejection["code"] == "market_data_incomplete"
    assert strategy.last_signal_rejection["details"]["reason"] == "未提供 K 线数据"


def test_alphagpt_produce_rejects_missing_ohlcv_columns() -> None:
    strategy = AlphaGptStrategy(config={"enabled": True})
    strategy.publish = Mock()

    signals = strategy.produce(
        symbols=["SOL/USDT"],
        formulas=[[0]],
        klines_map={"SOL/USDT": pd.DataFrame({"close": [100.0]})},
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
def test_alphagpt_rejects_invalid_ohlcv_geometry_before_model_load(mutate, expected) -> None:
    strategy = AlphaGptStrategy(config={"enabled": True})
    strategy.publish = Mock()

    signals = strategy.produce(
        symbols=["SOL/USDT"],
        formulas=[[0]],
        klines_map={"SOL/USDT": mutate(_frame())},
    )

    assert signals == []
    strategy.publish.assert_not_called()
    assert expected in strategy.last_signal_rejection["details"]["reason"]


def test_alphagpt_backtest_rejects_nonfinite_or_missing_ohlcv_before_model_load() -> None:
    strategy = AlphaGptStrategy(config={"enabled": True})

    with pytest.raises(ValueError, match="缺少 OHLCV 列"):
        strategy.backtest(pd.DataFrame({"close": [100.0]}), formulas=[[0]])

    frame = pd.DataFrame(
        {
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [float("inf")],
            "volume": [10.0],
        }
    )
    with pytest.raises(ValueError, match="非有限"):
        strategy.backtest(frame, formulas=[[0]])


def test_alphagpt_backtest_does_not_replace_formula_failure_with_zero(monkeypatch) -> None:
    torch = types.ModuleType("torch")
    factors = types.ModuleType("strategies.crypto.alphagpt.factors")
    stack_vm = types.ModuleType("strategies.crypto.alphagpt.stack_vm")

    class _FeatureEngineer:
        @staticmethod
        def compute_features(raw_dict):
            return object()

    class _StackVM:
        def execute(self, formula, feat):
            raise RuntimeError("formula unavailable")

    factors.FeatureEngineer = _FeatureEngineer
    stack_vm.StackVM = _StackVM
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "strategies.crypto.alphagpt.factors", factors)
    monkeypatch.setitem(sys.modules, "strategies.crypto.alphagpt.stack_vm", stack_vm)

    strategy = AlphaGptStrategy(config={"enabled": True})
    monkeypatch.setattr(strategy, "_build_feat_tensor", lambda *args, **kwargs: object())
    frame = _frame()
    frame["datetime"] = pd.date_range("2026-01-01", periods=len(frame), freq="h")

    with pytest.raises(FormulaEvaluationError, match="公式执行失败"):
        strategy.backtest(frame, formulas=[[0]])


def test_alphagpt_stack_vm_rejects_nonfinite_intermediate_without_sentinel() -> None:
    """NaN/Inf must abort a formula instead of becoming a zero/one score."""
    torch = pytest.importorskip("torch")
    from strategies.crypto.alphagpt.stack_vm import FORMULA_VOCAB, StackVM

    features = torch.full((1, FORMULA_VOCAB.feature_count, 1), float("nan"))
    add_token = FORMULA_VOCAB.operator_offset

    assert StackVM().execute([0, 0, add_token], features) is None
