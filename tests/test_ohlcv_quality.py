from __future__ import annotations

import pandas as pd

from core.data_feed.quality import assess_ohlcv, ohlcv_rejection_reason


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


def test_execution_ohlcv_rejects_nonpositive_and_impossible_bars() -> None:
    assert ohlcv_rejection_reason(_frame().assign(close=0.0)) == "OHLCV 含非正价格"
    assert ohlcv_rejection_reason(_frame().assign(high=98.0)) == "OHLCV 高低价关系无效"
    assert ohlcv_rejection_reason(_frame().assign(volume=-1.0)) == "OHLCV 含负成交量"


def test_assess_ohlcv_marks_nonfinite_prices_unusable() -> None:
    report = assess_ohlcv(_frame().assign(close=float("inf")))

    assert report.usable is False
    assert report.status == "invalid"
    assert report.invalid_rows == 1
