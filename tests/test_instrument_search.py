from __future__ import annotations

import pytest
import requests

from apps.api.domains.factor_factory.alpha_mining import alpha_expression_catalog
from apps.api.domains.instrument import service


def _okx_contract(code: str, *, source: str = "okx_public") -> dict:
    contract = service._contract_from_row(
        {
            "code": code,
            "name": f"{code.split('-', 1)[0]} / USDT 永续",
            "available_intervals": ["1h", "1d"],
        },
        source=source,
    )
    assert contract is not None
    return contract


def test_normalize_crypto_base_and_usdt_pair_to_okx_swap() -> None:
    assert service.normalize_crypto_swap_code("AVGO") == "AVGO-USDT-SWAP"
    assert service.normalize_crypto_swap_code("avgoUSDT") == "AVGO-USDT-SWAP"
    assert service.normalize_crypto_swap_code("AVGO/USDT") == "AVGO-USDT-SWAP"
    assert service.normalize_crypto_swap_code("AVGO-USDT-SWAP") == "AVGO-USDT-SWAP"


def test_crypto_search_resolves_broadcom_chinese_alias(monkeypatch) -> None:
    contract = _okx_contract("AVGO-USDT-SWAP")
    catalog_calls = 0

    def catalog(*, refresh: bool = False):
        del refresh
        nonlocal catalog_calls
        catalog_calls += 1
        return [contract]

    monkeypatch.setattr(service, "_load_okx_swap_contracts", catalog)

    matches = service.search("博通", market="crypto")

    assert matches[0].code == "AVGO-USDT-SWAP"
    assert "博通" in matches[0].name
    assert matches[0].exchange == "okx"
    assert catalog_calls == 1


def test_crypto_search_deduplicates_legacy_bare_codes(monkeypatch) -> None:
    legacy = service.build_instrument("AVGO", "crypto")
    contract = _okx_contract("AVGO-USDT-SWAP")
    monkeypatch.setattr(service.repository, "search", lambda *args, **kwargs: [legacy])
    monkeypatch.setattr(service, "_load_okx_swap_contracts", lambda *, refresh=False: [contract])

    matches = service.search("AVGO", market="crypto")

    assert [item.code for item in matches] == ["AVGO-USDT-SWAP"]


def test_crypto_strict_resolution_requires_current_verified_public_contract(monkeypatch) -> None:
    contract = _okx_contract("BTC-USDT-SWAP")
    saved = []
    monkeypatch.setattr(service, "_load_okx_swap_contracts", lambda *, refresh=False: [contract])
    monkeypatch.setattr(service.repository, "upsert", saved.append)

    resolved = service.resolve_strict("btc-usdt", "crypto", name_hint="untrusted name")

    assert resolved.code == "BTC-USDT-SWAP"
    assert resolved.name == "BTC / USDT 永续"
    assert saved == [resolved]


def test_crypto_strict_and_search_reject_manual_or_cached_contract_metadata(monkeypatch) -> None:
    manual = service.build_instrument("FAKE-USDT-SWAP", "crypto", "manual metadata")
    cached = _okx_contract("BTC-USDT-SWAP", source="okx_public_cache")
    monkeypatch.setattr(service.repository, "get", lambda *args, **kwargs: manual)
    monkeypatch.setattr(service, "_load_okx_swap_contracts", lambda *, refresh=False: [cached])

    assert service.search("BTC-USDT", market="crypto") == []
    assert service.search("FAKE-USDT-SWAP", market="crypto") == []
    with pytest.raises(service.InstrumentResolutionError, match="当前 OKX 公共目录验证"):
        service.resolve_strict("BTC-USDT", "crypto")
    with pytest.raises(service.InstrumentResolutionError, match="当前 OKX 公共目录验证"):
        service.resolve_strict("FAKE-USDT-SWAP", "crypto")


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
    contract = service._contract_from_row(
        {
            "code": "XAUT-USDT-SWAP",
            "name": "XAUT / USDT 永续",
            "contract_size": 0.001,
            "price_precision": 0.1,
            "amount_precision": 0.01,
            "minimum_amount": 0.01,
            "linear": True,
        },
        source="okx_public",
    )
    assert contract is not None
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
    assert result["instruments"][0]["trading_ready"] is True
    assert result["degraded"] is False
    assert result["trading_ready"] is True
    assert result["instruments"][0]["contract_size"] == 0.001


def test_okx_catalog_timeout_uses_same_source_cache_as_non_trading(monkeypatch) -> None:
    monkeypatch.setattr(service, "_OKX_MARKET_CACHE", (0.0, []))
    monkeypatch.setattr(service, "_OKX_MARKET_RETRY_AT", 0.0)
    monkeypatch.setattr(service, "_OKX_MARKET_LAST_ERROR", "")
    monkeypatch.setattr(service, "_OKX_MARKET_SOURCE", "unavailable")
    monkeypatch.setattr(service, "_OKX_MARKET_FETCHED_AT", 0.0)
    cached_contract = service._contract_from_row(
        {
            "code": "BTC-USDT-SWAP",
            "name": "比特币 / Bitcoin 永续",
            "available_intervals": ["1h", "1d"],
        },
        source="okx_public_cache",
    )
    assert cached_contract is not None
    monkeypatch.setattr(
        service, "_load_persisted_okx_catalog", lambda: ([cached_contract], 1_786_800_000.0)
    )

    def raise_timeout(*args, **kwargs):
        del args, kwargs
        raise requests.ConnectTimeout(
            "HTTPSConnectionPool(host='www.okx.com', port=443): connect timed out"
        )

    monkeypatch.setattr(service.requests, "get", raise_timeout)

    result = service.okx_swap_catalog("BTC", refresh=True)

    assert result["ok"] is True
    assert result["source"] == "okx_public_cache"
    assert result["degraded"] is True
    assert result["trading_ready"] is False
    assert result["trading_ready_count"] == 0
    assert result["instruments"][0]["verified"] is False
    assert result["instruments"][0]["research_ready"] is True
    assert result["instruments"][0]["trading_ready"] is False
    assert result["error"] == "OKX 公共合约目录连接超时"
    assert "HTTPSConnectionPool" not in result["error"]
    assert "www.okx.com" not in result["error"]


def test_okx_catalog_timeout_does_not_fallback_to_local_index(monkeypatch) -> None:
    monkeypatch.setattr(service, "_OKX_MARKET_CACHE", (0.0, []))
    monkeypatch.setattr(service, "_OKX_MARKET_RETRY_AT", 0.0)
    monkeypatch.setattr(service, "_OKX_MARKET_LAST_ERROR", "")
    monkeypatch.setattr(service, "_OKX_MARKET_SOURCE", "unavailable")
    monkeypatch.setattr(service, "_OKX_MARKET_FETCHED_AT", 0.0)
    monkeypatch.setattr(service, "_load_persisted_okx_catalog", lambda: ([], 0.0))

    def raise_timeout(*args, **kwargs):
        del args, kwargs
        raise requests.ConnectTimeout(
            "HTTPSConnectionPool(host='www.okx.com', port=443): connect timed out"
        )

    monkeypatch.setattr(service.requests, "get", raise_timeout)

    result = service.okx_swap_catalog("BTC", refresh=True)

    assert result["ok"] is False
    assert result["source"] == "unavailable"
    assert result["degraded"] is False
    assert result["trading_ready"] is False
    assert result["trading_ready_count"] == 0
    assert result["instruments"] == []
    assert result["error"] == "OKX 公共合约目录连接超时"
    assert result["warning"] == "OKX 公共合约目录连接超时"
