from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from core.data_feed.base import DataSource, RealtimeQuote
from core.data_feed.factory import DataSourceProxy
from core.data_feed.tencent_source import TencentSource
from strategies.a_shares.realtime_analyzer import fetchers as a_share_fetchers
from strategies.a_shares.realtime_analyzer.strategy import RealtimeAnalyzerStrategy
from strategies.us_stocks.realtime_analyzer.strategy import RealtimeAnalyzerUsStrategy
from strategies.us_stocks.realtime_analyzer.strategy import fetch_kline as fetch_us_kline
from strategies.us_stocks.realtime_analyzer.strategy import parse_codes as parse_us_codes


class _QuoteSource(DataSource):
    name = "primary"
    market = "a_shares"

    def __init__(self, quote: RealtimeQuote | None) -> None:
        self.quote = quote
        self.quote_calls: list[str] = []

    def get_kline(self, symbol, interval, start=None, end=None, limit=500):
        return pd.DataFrame()

    def get_realtime_quote(self, symbol: str) -> RealtimeQuote | None:
        self.quote_calls.append(symbol)
        return self.quote


class _QuoteResponse:
    content = b""
    text = 'v_sh600519="51~贵州茅台~600519~100.50~99.50~~~~20260824150000~";'

    def raise_for_status(self) -> None:
        return None


def _trusted_quote(
    symbol: str,
    market: str,
    *,
    source: str = "tencent",
    observed_at: datetime | None = None,
    last: float = 100.0,
) -> dict:
    return {
        "code": symbol,
        "name": symbol,
        "last": last,
        "pct": 0.5,
        "prev_close": 99.5,
        "source": source,
        "market": market,
        "observed_at": (observed_at or datetime.now(UTC)).isoformat(),
        "verified": True,
    }


def test_tencent_realtime_quote_has_price_source_and_observation_time() -> None:
    with patch("core.data_feed.tencent_source.requests.get", return_value=_QuoteResponse()):
        quote = TencentSource().get_realtime_quote("600519")

    assert quote is not None
    assert quote.symbol == "600519"
    assert quote.source == "tencent"
    assert quote.market == "a_shares"
    assert quote.price == 100.5
    assert quote.observed_at.tzinfo is not None


def test_realtime_quote_proxy_exposes_only_the_primary() -> None:
    quote = RealtimeQuote(
        symbol="600519",
        market="a_shares",
        price=100.0,
        observed_at=datetime.now(UTC),
        source="primary",
    )
    source = _QuoteSource(quote)
    proxy = DataSourceProxy(source, cache=Mock())

    assert [item["name"] for item in proxy.source_plan("get_realtime_quote")] == ["primary"]
    assert proxy.get_realtime_quote("600519") is quote
    assert source.quote_calls == ["600519"]


def test_a_share_fetcher_uses_configured_primary_quote_not_direct_http() -> None:
    quote = RealtimeQuote(
        symbol="600519",
        market="a_shares",
        price=100.0,
        observed_at=datetime.now(UTC),
        source="tencent",
    )
    source = _QuoteSource(quote)
    source.name = "tencent"
    with patch.object(a_share_fetchers, "get_data_source", return_value=source):
        rows = a_share_fetchers.fetch_quotes(["600519"])

    assert source.quote_calls == ["600519"]
    assert rows == [
        {
            "code": "600519",
            "name": None,
            "last": 100.0,
            "pct": None,
            "prev_close": None,
            "source": "tencent",
            "market": "a_shares",
            "observed_at": quote.observed_at.isoformat(),
            "verified": True,
        }
    ]


@pytest.mark.parametrize(
    ("strategy", "codes", "quotes", "expected_code"),
    [
        (
            RealtimeAnalyzerStrategy(config={"max_quote_age_minutes": 10}),
            ["600519"],
            [],
            "market_data_unavailable",
        ),
        (
            RealtimeAnalyzerStrategy(config={"max_quote_age_minutes": 10}),
            ["600519"],
            [
                _trusted_quote(
                    "600519",
                    "a_shares",
                    observed_at=datetime.now(UTC) - timedelta(minutes=11),
                )
            ],
            "market_quote_stale",
        ),
        (
            RealtimeAnalyzerUsStrategy(config={"max_quote_age_minutes": 10}),
            ["NVDA"],
            [_trusted_quote("NVDA", "crypto")],
            "market_data_unavailable",
        ),
        (
            RealtimeAnalyzerUsStrategy(config={"max_quote_age_minutes": 10}),
            ["NVDA"],
            [_trusted_quote("NVDA", "us_stocks", source="other_primary")],
            "market_data_unavailable",
        ),
    ],
)
def test_quote_validation_rejects_untrusted_or_stale_market_data(
    strategy, codes, quotes, expected_code
) -> None:
    expected_market = strategy.info.market
    rejection = strategy._validate_quotes(codes, quotes, "tencent")

    assert rejection is not None
    assert rejection["code"] == expected_code
    assert expected_market in {"a_shares", "us_stocks"}


def test_missing_quote_stops_before_the_a_share_llm_is_called() -> None:
    source = Mock(name="tencent")
    source.name = "tencent"
    strategy = RealtimeAnalyzerStrategy(config={})
    with (
        patch(
            "strategies.a_shares.realtime_analyzer.strategy.get_data_source",
            return_value=source,
        ),
        patch("strategies.a_shares.realtime_analyzer.strategy.fetch_quotes", return_value=[]),
        patch.object(strategy, "_build_report") as build_report,
    ):
        produced = strategy.produce(codes=["600519"], with_kline=False, with_indices=False)

    assert produced == []
    assert strategy.last_signal_rejection["code"] == "market_data_unavailable"
    build_report.assert_not_called()


def test_multi_symbol_quote_coverage_is_fail_closed() -> None:
    strategy = RealtimeAnalyzerStrategy(config={})
    rejection = strategy._validate_quotes(
        ["600519", "000001"],
        [_trusted_quote("600519", "a_shares")],
        "tencent",
    )

    assert rejection is not None
    assert rejection["details"]["reason"] == "quote_missing"
    assert rejection["details"]["symbol"] == "000001"


def test_us_realtime_analyzer_rejects_crypto_and_hyphenated_inputs_before_routing() -> None:
    assert parse_us_codes("BTC-USDT, ETH-USDT, AAPL-USD") == []
    assert parse_us_codes("BRK.B") == ["BRK-B"]

    strategy = RealtimeAnalyzerUsStrategy(config={})
    with patch("strategies.us_stocks.realtime_analyzer.strategy.get_data_source") as source:
        assert strategy.produce(codes="BTC-USDT", with_kline=False) == []

    source.assert_not_called()


def test_us_kline_request_stays_on_us_stocks_primary() -> None:
    source = Mock()
    source.name = "tencent"
    source.get_kline.return_value = pd.DataFrame()
    with patch(
        "strategies.us_stocks.realtime_analyzer.strategy.get_data_source",
        return_value=source,
    ) as get_data_source:
        result = fetch_us_kline("AAPL", days=5)

    assert result["available"] is False
    assert result["source"] == "tencent"
    assert result["semantics"] == "bar_snapshot"
    get_data_source.assert_called_once_with("us_stocks")
    source.get_kline.assert_called_once_with("AAPL", "1d", limit=5)


def test_a_share_kline_empty_primary_is_explicitly_unavailable() -> None:
    source = Mock()
    source.name = "tencent"
    source.get_kline.return_value = pd.DataFrame()
    with patch.object(a_share_fetchers, "get_data_source", return_value=source):
        result = a_share_fetchers.fetch_kline("600519", days=5)

    assert result["available"] is False
    assert result["source"] == "tencent"
    assert result["semantics"] == "bar_snapshot"
    source.get_kline.assert_called_once_with("600519", a_share_fetchers.Interval.DAILY, limit=5)


@pytest.mark.parametrize(
    ("strategy_cls", "module", "symbol", "market"),
    [
        (
            RealtimeAnalyzerStrategy,
            "strategies.a_shares.realtime_analyzer.strategy",
            "600519",
            "a_shares",
        ),
        (
            RealtimeAnalyzerUsStrategy,
            "strategies.us_stocks.realtime_analyzer.strategy",
            "NVDA",
            "us_stocks",
        ),
    ],
)
def test_default_kline_failure_does_not_publish_quote_only_structured_signal(
    strategy_cls, module: str, symbol: str, market: str
) -> None:
    source = Mock()
    source.name = "tencent"
    strategy = strategy_cls(config={})
    report = 'QUANTHUB_SIGNAL_JSON:{"direction":"buy","score":0.7,"confidence":0.8}'
    with (
        patch(f"{module}.get_data_source", return_value=source),
        patch(f"{module}.fetch_quotes", return_value=[_trusted_quote(symbol, market)]),
        patch(
            f"{module}.fetch_kline",
            return_value={
                "metrics": {},
                "klines": [],
                "available": False,
                "source": "tencent",
                "semantics": "bar_snapshot",
            },
        ),
        patch.object(strategy, "_build_report", return_value=report) as build_report,
        patch.object(strategy, "publish") as publish,
    ):
        produced = strategy.produce(codes=[symbol], with_indices=False)

    assert produced == []
    assert strategy.last_signal_rejection["code"] == "market_data_incomplete"
    assert strategy.last_signal_rejection["details"]["reason"] == "kline_unavailable"
    assert strategy.last_report["display_only"] is True
    assert strategy.last_report["degraded"] is True
    assert strategy.last_report["execution_eligible"] is False
    assert strategy.last_report["market_data"]["kline_requested"] is True
    build_report.assert_not_called()
    publish.assert_not_called()


@pytest.mark.parametrize(
    ("strategy_cls", "module", "symbol", "market"),
    [
        (
            RealtimeAnalyzerStrategy,
            "strategies.a_shares.realtime_analyzer.strategy",
            "600519",
            "a_shares",
        ),
        (
            RealtimeAnalyzerUsStrategy,
            "strategies.us_stocks.realtime_analyzer.strategy",
            "NVDA",
            "us_stocks",
        ),
    ],
)
def test_explicit_realtime_only_is_marked_display_only(
    strategy_cls, module: str, symbol: str, market: str
) -> None:
    source = Mock()
    source.name = "tencent"
    strategy = strategy_cls(config={})
    report = 'QUANTHUB_SIGNAL_JSON:{"direction":"buy","score":0.7,"confidence":0.8}'
    with (
        patch(f"{module}.get_data_source", return_value=source),
        patch(f"{module}.fetch_quotes", return_value=[_trusted_quote(symbol, market)]),
        patch(f"{module}.fetch_kline") as fetch_kline,
        patch.object(strategy, "_build_report", return_value=report),
        patch.object(strategy, "publish") as publish,
    ):
        produced = strategy.produce(codes=[symbol], with_kline=False, with_indices=False)

    assert len(produced) == 1
    assert strategy.last_report["realtime_only"] is True
    assert strategy.last_report["display_only"] is True
    assert strategy.last_report["degraded"] is True
    assert strategy.last_report["execution_eligible"] is False
    assert strategy.last_report["market_data"]["realtime_only"] is True
    assert strategy.last_report["market_data"]["execution_eligible"] is False
    fetch_kline.assert_not_called()
    assert produced[0].meta["execution_eligible"] is False
    publish.assert_called_once_with(produced[0])
