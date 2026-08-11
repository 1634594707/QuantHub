from __future__ import annotations

import requests

from apps.api.domains.factor_factory.alpha_mining import alpha_expression_catalog
from apps.api.domains.instrument import service


def test_normalize_crypto_base_and_usdt_pair_to_okx_swap() -> None:
    assert service.normalize_crypto_swap_code("AVGO") == "AVGO-USDT-SWAP"
    assert service.normalize_crypto_swap_code("avgoUSDT") == "AVGO-USDT-SWAP"
    assert service.normalize_crypto_swap_code("AVGO/USDT") == "AVGO-USDT-SWAP"
    assert service.normalize_crypto_swap_code("AVGO-USDT-SWAP") == "AVGO-USDT-SWAP"


def test_crypto_search_resolves_broadcom_chinese_alias(monkeypatch) -> None:
    monkeypatch.setattr(service.repository, "search", lambda *args, **kwargs: [])
    remote_calls = 0

    def remote_markets():
        nonlocal remote_calls
        remote_calls += 1
        return []

    monkeypatch.setattr(service, "_load_okx_swap_markets", remote_markets)

    matches = service.search("博通", market="crypto")

    assert matches[0].code == "AVGO-USDT-SWAP"
    assert "博通" in matches[0].name
    assert matches[0].exchange == "okx"
    assert remote_calls == 0


def test_crypto_search_deduplicates_legacy_bare_codes(monkeypatch) -> None:
    legacy = service.build_instrument("AVGO", "crypto")
    monkeypatch.setattr(service.repository, "search", lambda *args, **kwargs: [legacy])
    monkeypatch.setattr(service, "_load_okx_swap_markets", list)

    matches = service.search("AVGO", market="crypto")

    assert [item.code for item in matches] == ["AVGO-USDT-SWAP"]


def test_manual_alpha_catalog_tracks_parser_limits_and_whitelist() -> None:
    catalog = alpha_expression_catalog()
    operator_names = {item["name"] for item in catalog["operators"]}
    field_names = {item["name"] for item in catalog["fields"]}

    assert field_names == {"open", "high", "low", "close", "volume"}
    assert {"pct_change", "rolling_zscore", "rank", "where"} <= operator_names
    assert catalog["limits"]["window_max"] == 500
    assert catalog["limits"]["periods_max"] == 500
    assert catalog["limits"]["max_operators"] == 30
    assert any(item["name"] == "lower / upper" for item in catalog["parameters"])


def test_okx_catalog_search_returns_only_verified_exchange_contracts(monkeypatch) -> None:
    instrument = service.build_instrument("XAUT-USDT-SWAP", "crypto", "XAUT / USDT 永续")
    contract = {
        "instrument": instrument,
        "base": "XAUT",
        "quote": "USDT",
        "settle": "USDT",
        "contract_size": 0.001,
        "price_precision": 0.1,
        "amount_precision": 0.01,
        "minimum_amount": 0.01,
        "linear": True,
    }
    monkeypatch.setattr(
        service,
        "_load_okx_swap_contracts",
        lambda *, refresh=False: [contract],
    )

    result = service.okx_swap_catalog("黄金")

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["instruments"][0]["code"] == "XAUT-USDT-SWAP"
    assert result["instruments"][0]["verified"] is True
    assert result["instruments"][0]["contract_size"] == 0.001


def test_okx_catalog_timeout_returns_sanitized_public_error(monkeypatch) -> None:
    monkeypatch.setattr(service, "_OKX_MARKET_CACHE", (0.0, []))
    monkeypatch.setattr(service, "_OKX_MARKET_RETRY_AT", 0.0)
    monkeypatch.setattr(service, "_OKX_MARKET_LAST_ERROR", "")

    def raise_timeout(*args, **kwargs):
        del args, kwargs
        raise requests.ConnectTimeout(
            "HTTPSConnectionPool(host='www.okx.com', port=443): connect timed out"
        )

    monkeypatch.setattr(service.requests, "get", raise_timeout)

    result = service.okx_swap_catalog("BTC", refresh=True)

    assert result["ok"] is False
    assert result["error"] == "OKX 公共合约目录连接超时"
    assert "HTTPSConnectionPool" not in result["error"]
    assert "www.okx.com" not in result["error"]
