"""Execution-boundary regression tests for the signal dispatcher."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

import pytest

from apps.dispatcher.main import Dispatcher
from apps.dispatcher.router import (
    EXECUTION_CANCELLED,
    EXECUTION_FAILED,
    EXECUTION_UNAVAILABLE,
    ORDER_VALUES_INVALID,
    SOURCE_NOT_AUTHORIZED,
    OrderRouter,
    OrderRoutingError,
)
from core.signals import Signal


def _signal(
    *,
    symbol: str = "600000",
    market: str = "a_shares",
    direction: str = "buy",
    score: float = 1.0,
    confidence: float = 1.0,
    source: str = "sentiment",
    meta: dict | None = None,
) -> Signal:
    return Signal(
        symbol=symbol,
        market=market,
        timeframe="1d",
        direction=direction,
        score=score,
        confidence=confidence,
        source=source,
        meta=meta or {},
    )


def _bare_dispatcher(*, weights: dict[str, float], dry_run: bool = True) -> Dispatcher:
    """Build a dispatcher without subscribing another global-bus handler."""

    dispatcher = Dispatcher.__new__(Dispatcher)
    dispatcher.weights = weights
    dispatcher.window = timedelta(minutes=5)
    dispatcher.score_threshold = 0.6
    dispatcher._buffer = defaultdict(list)
    dispatcher._router = OrderRouter(dry_run=dry_run)
    dispatcher._risk_checkers = {}
    return dispatcher


def test_hold_signal_is_not_converted_to_buy(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(OrderRoutingError, match="hold_signal_not_orderable"):
        OrderRouter(dry_run=True).route(_signal(direction="hold"), qty=1.0)

    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("dry_run", [True, False])
def test_unknown_crypto_source_is_rejected_instead_of_dry_run(dry_run: bool) -> None:
    signal = _signal(symbol="DOGE/USDT", market="crypto", source="unreviewed", direction="sell")
    with pytest.raises(OrderRoutingError, match="crypto_source_not_authorized"):
        OrderRouter(dry_run=dry_run).route(signal, qty=1.0)


@pytest.mark.parametrize(
    "meta",
    [
        {"display_only": True},
        {"degraded": True},
        {"execution_eligible": False},
        {"realtime_only": True, "with_kline": False},
        {"realtime_only": True},
        {"display_only": True, "degraded": True, "execution_eligible": False},
    ],
)
def test_display_or_degraded_signal_cannot_be_ordered(meta: dict) -> None:
    signal = _signal(meta=meta)
    with pytest.raises(OrderRoutingError, match="signal_not_execution_eligible"):
        OrderRouter(dry_run=True).route(signal, qty=1.0)


def test_hold_only_aggregate_is_observable_and_not_routed() -> None:
    dispatcher = _bare_dispatcher(weights={"sentiment": 1.0})
    dispatcher._buffer["600000"] = [
        (_signal(direction="hold", score=1.0, confidence=1.0), datetime.now(UTC))
    ]

    result = dispatcher.flush("600000")

    assert len(result) == 1
    assert result[0]["rejected"] == "hold_signal_not_orderable"
    assert result[0]["direction"] == "hold"
    assert "side" not in result[0]


def test_unconfigured_source_is_not_given_implicit_point_one_weight() -> None:
    dispatcher = _bare_dispatcher(weights={"sentiment": 1.0})
    unknown = _signal(source="morning_brief", score=1.0, confidence=1.0)

    aggregate = dispatcher._aggregate([(unknown, datetime.now(UTC))])

    assert aggregate["score"] == 0.0
    assert aggregate["direction"] == "hold"
    assert aggregate["rejected"] == "signal_source_unconfigured"
    assert aggregate["unconfigured_sources"] == ["morning_brief"]
    assert aggregate["sources"] == []


def test_mixed_configured_and_unconfigured_sources_reject_whole_aggregate() -> None:
    dispatcher = _bare_dispatcher(weights={"sentiment": 1.0})
    known = _signal(score=0.4, confidence=0.8)
    unknown = _signal(source="morning_brief", score=1.0, confidence=1.0)

    aggregate = dispatcher._aggregate([(known, datetime.now(UTC)), (unknown, datetime.now(UTC))])

    # Dropping the unknown source and routing the configured remainder would
    # silently change the decision.  The entire symbol window is rejected.
    assert aggregate["score"] == pytest.approx(0.4)
    assert aggregate["direction"] == "buy"
    assert aggregate["sources"] == ["sentiment"]
    assert aggregate["unconfigured_sources"] == ["morning_brief"]
    assert aggregate["rejected"] == "signal_source_unconfigured"


def test_same_symbol_mixed_markets_are_rejected() -> None:
    dispatcher = _bare_dispatcher(weights={"sentiment": 1.0, "supertrend": 1.0})
    pending = [
        (_signal(symbol="BTCUSDT", market="crypto", source="sentiment"), datetime.now(UTC)),
        (_signal(symbol="BTCUSDT", market="a_shares", source="supertrend"), datetime.now(UTC)),
    ]

    aggregate = dispatcher._aggregate(pending)

    assert aggregate["rejected"] == "signal_market_mismatch"
    assert aggregate["observed_markets"] == ["a_shares", "crypto"]
    assert dispatcher._route(aggregate, account_ctx=None)["rejected"] == "signal_market_mismatch"


def test_equal_buy_sell_votes_hold_and_are_rejected() -> None:
    dispatcher = _bare_dispatcher(weights={"sentiment": 0.5, "supertrend": 0.5})
    pending = [
        (_signal(source="sentiment", direction="buy"), datetime.now(UTC)),
        (_signal(source="supertrend", direction="sell"), datetime.now(UTC)),
    ]

    aggregate = dispatcher._aggregate(pending)

    assert aggregate["direction"] == "hold"
    assert aggregate["direction_tie"] is True
    assert aggregate["rejected"] == "direction_tie"
    assert dispatcher._route(aggregate, account_ctx=None)["rejected"] == "direction_tie"

    dispatcher._buffer["600000"] = pending
    assert dispatcher.flush("600000")[0]["rejected"] == "direction_tie"


def test_ineligible_realtime_signal_is_rejected_before_aggregation() -> None:
    dispatcher = _bare_dispatcher(weights={"realtime_analyzer": 1.0})
    realtime_only = _signal(
        source="realtime_analyzer",
        meta={
            "realtime_only": True,
            "with_kline": False,
            "display_only": True,
            "degraded": True,
            "execution_eligible": False,
        },
    )

    aggregate = dispatcher._aggregate([(realtime_only, datetime.now(UTC))])

    assert aggregate["rejected"] == "signal_not_execution_eligible"
    assert aggregate["ineligible_sources"] == ["realtime_analyzer"]


def test_crypto_aggregate_keeps_one_execution_source() -> None:
    dispatcher = _bare_dispatcher(weights={"okx_grid": 1.0})
    signal = _signal(
        symbol="BTC/USDT",
        market="crypto",
        source="okx_grid",
        direction="buy",
    )
    aggregate = dispatcher._aggregate([(signal, datetime.now(UTC))])

    result = dispatcher._route(aggregate, account_ctx=None)

    assert result is not None
    assert result["source"] == "okx_grid"
    assert result["side"] == "buy"


def test_crypto_mixed_execution_sources_are_rejected() -> None:
    dispatcher = _bare_dispatcher(weights={"okx_grid": 0.5, "alphagpt": 0.5})
    pending = [
        (
            _signal(
                symbol="BTC/USDT",
                market="crypto",
                source="okx_grid",
                direction="buy",
            ),
            datetime.now(UTC),
        ),
        (
            _signal(
                symbol="BTC/USDT",
                market="crypto",
                source="alphagpt",
                direction="buy",
            ),
            datetime.now(UTC),
        ),
    ]

    aggregate = dispatcher._aggregate(pending)

    assert dispatcher._route(aggregate, account_ctx=None) == {
        "symbol": "BTC/USDT",
        "market": "crypto",
        "rejected": "crypto_execution_source_ambiguous",
        "direction": "buy",
        "score": 1.0,
        "sources": ["alphagpt", "okx_grid"],
        "observed_sources": ["alphagpt", "okx_grid"],
        "observed_markets": ["crypto"],
    }


def test_live_okx_failure_is_not_returned_as_success_intent(monkeypatch) -> None:
    class _Exchange:
        def create_limit_order(self, *args, **kwargs):
            raise RuntimeError("venue unavailable")

    class _Source:
        def __init__(self, **kwargs):
            self._exchange = _Exchange()

    monkeypatch.setattr("apps.dispatcher.confirm.cli_confirm", lambda summary: True)
    monkeypatch.setattr("core.data_feed.okx_source.OkxSource", _Source)

    signal = _signal(
        symbol="BTC/USDT",
        market="crypto",
        source="okx_grid",
        direction="buy",
    )
    with pytest.raises(OrderRoutingError) as exc_info:
        OrderRouter(dry_run=False).route(signal, qty=1.0, price=100.0)

    assert exc_info.value.code == EXECUTION_FAILED


def test_live_okx_cancellation_is_not_returned_as_success_intent(monkeypatch) -> None:
    monkeypatch.setattr("apps.dispatcher.confirm.cli_confirm", lambda summary: False)
    signal = _signal(
        symbol="BTC/USDT",
        market="crypto",
        source="okx_grid",
        direction="buy",
    )

    with pytest.raises(OrderRoutingError) as exc_info:
        OrderRouter(dry_run=False).route(signal, qty=1.0, price=100.0)

    assert exc_info.value.code == EXECUTION_CANCELLED


def test_live_okx_missing_receipt_is_not_returned_as_success_intent(monkeypatch) -> None:
    class _Exchange:
        def create_limit_order(self, *args, **kwargs):
            return None

    class _Source:
        def __init__(self, **kwargs):
            self._exchange = _Exchange()

    monkeypatch.setattr("apps.dispatcher.confirm.cli_confirm", lambda summary: True)
    monkeypatch.setattr("core.data_feed.okx_source.OkxSource", _Source)
    signal = _signal(symbol="BTC/USDT", market="crypto", source="okx_grid")

    with pytest.raises(OrderRoutingError) as exc_info:
        OrderRouter(dry_run=False).route(signal, qty=1.0, price=100.0)

    assert exc_info.value.code == EXECUTION_FAILED


def test_live_solana_without_executor_is_explicit_failure(monkeypatch) -> None:
    monkeypatch.setattr("apps.dispatcher.confirm.cli_confirm", lambda summary: True)
    signal = _signal(
        symbol="BONK/USDT",
        market="crypto",
        source="alphagpt",
        direction="buy",
    )

    with pytest.raises(OrderRoutingError) as exc_info:
        OrderRouter(dry_run=False).route(signal, qty=1.0, price=1.0)

    assert exc_info.value.code == EXECUTION_UNAVAILABLE


def test_live_a_shares_without_broker_is_explicit_failure() -> None:
    signal = _signal(market="a_shares", source="sentiment", direction="buy")

    with pytest.raises(OrderRoutingError) as exc_info:
        OrderRouter(dry_run=False).route(signal, qty=1.0, price=10.0)

    assert exc_info.value.code == EXECUTION_UNAVAILABLE


def test_non_crypto_unknown_source_is_not_authorized() -> None:
    signal = _signal(market="a_shares", source="unreviewed", direction="buy")

    with pytest.raises(OrderRoutingError) as exc_info:
        OrderRouter(dry_run=True).route(signal, qty=1.0)

    assert exc_info.value.code == SOURCE_NOT_AUTHORIZED


@pytest.mark.parametrize("qty", [0, -1, float("nan"), float("inf"), float("-inf")])
def test_order_quantity_must_be_finite_and_positive(qty: float) -> None:
    signal = _signal(market="a_shares", source="sentiment")

    with pytest.raises(OrderRoutingError) as exc_info:
        OrderRouter(dry_run=True).route(signal, qty=qty)

    assert exc_info.value.code == ORDER_VALUES_INVALID


@pytest.mark.parametrize("price", [0, -1, float("nan"), float("inf"), float("-inf")])
def test_supplied_order_price_must_be_finite_and_positive(price: float) -> None:
    signal = _signal(market="a_shares", source="sentiment")

    with pytest.raises(OrderRoutingError) as exc_info:
        OrderRouter(dry_run=True).route(signal, qty=1.0, price=price)

    assert exc_info.value.code == ORDER_VALUES_INVALID
