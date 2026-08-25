from __future__ import annotations

import pandas as pd

from apps.api.domains.market import service as market_service
from apps.api.domains.research.service import dataframe_snapshot


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "datetime": pd.date_range("2026-08-16", periods=1, freq="D"),
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [10.0],
        }
    )


def test_unattributed_market_frame_is_not_relabelled_as_local(monkeypatch) -> None:
    class _Source:
        def get_kline(self, *_args, **_kwargs):
            return _frame()

    monkeypatch.setattr(market_service, "get_data_source", lambda _market: _Source())

    response = market_service.fetch_kline("AAPL", market="us_stocks", interval="1d", limit=1)

    assert response["ok"] is True
    assert response["source"] == "unknown"
    assert response["source"] != "local"


def test_unattributed_research_snapshot_is_explicitly_unknown() -> None:
    snapshot = dataframe_snapshot(_frame())

    assert snapshot["source"] == "unknown"
