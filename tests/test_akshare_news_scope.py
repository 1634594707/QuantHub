from __future__ import annotations

from unittest.mock import Mock

from core.data_feed.akshare_source import AkshareSource


def test_symbol_scoped_news_does_not_fall_back_to_global_news() -> None:
    source = AkshareSource.__new__(AkshareSource)
    source._fetch_stock_news_em = Mock(side_effect=RuntimeError("symbol endpoint unavailable"))
    source._ak = Mock()

    result = source.get_news("600519", limit=10)

    assert result == []
    source._ak.stock_info_global_em.assert_not_called()
