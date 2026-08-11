"""Instrument 服务：解析、搜索、注册。

解析优先级：
    1. 本地 instruments 表（已缓存的标的元数据）
    2. 腾讯实时报价接口（A 股 / 美股）回填名称
    3. 兜底：按代码推断市场/交易所/币种，名称留空
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

import requests

from . import repository
from .domain import Instrument, build_instrument, infer_market

logger = logging.getLogger(__name__)

SUPPORTED_MARKETS = frozenset({"a_shares", "crypto", "us_stocks", "mt5"})

# These aliases cover instruments whose exchange symbol is not discoverable from a
# Chinese name alone.  The OKX market catalogue below remains the source of truth
# for availability; aliases only make common research inputs ergonomic.
CRYPTO_ALIASES: dict[str, tuple[str, str]] = {
    "比特币": ("BTC-USDT-SWAP", "比特币 / Bitcoin 永续"),
    "bitcoin": ("BTC-USDT-SWAP", "比特币 / Bitcoin 永续"),
    "以太坊": ("ETH-USDT-SWAP", "以太坊 / Ethereum 永续"),
    "ethereum": ("ETH-USDT-SWAP", "以太坊 / Ethereum 永续"),
    "solana": ("SOL-USDT-SWAP", "Solana 永续"),
    "英伟达": ("NVDA-USDT-SWAP", "英伟达 / NVIDIA 永续"),
    "nvidia": ("NVDA-USDT-SWAP", "英伟达 / NVIDIA 永续"),
    "博通": ("AVGO-USDT-SWAP", "博通 / Broadcom 永续"),
    "broadcom": ("AVGO-USDT-SWAP", "博通 / Broadcom 永续"),
}

OKX_CATALOG_SEARCH_TERMS: dict[str, tuple[str, ...]] = {
    "黄金": ("XAUT", "PAXG", "GOLD"),
    "gold": ("XAUT", "PAXG", "GOLD"),
    "石油": ("OIL", "WTI", "BRENT"),
    "原油": ("OIL", "WTI", "BRENT"),
    "oil": ("OIL", "WTI", "BRENT"),
}

_OKX_MARKET_CACHE: tuple[float, list[dict[str, Any]]] = (0.0, [])
_OKX_MARKET_RETRY_AT = 0.0
_OKX_MARKET_FETCHED_AT = 0.0
_OKX_MARKET_LAST_ERROR = ""
_OKX_MARKET_LOCK = threading.Lock()
_OKX_MARKET_TTL_SECONDS = 15 * 60
_OKX_MARKET_RETRY_SECONDS = 60


class InstrumentResolutionError(ValueError):
    pass


def resolve_strict(code: str, market: str, name_hint: str = "") -> Instrument:
    """按已定义市场和代码规则解析并持久化 Instrument。"""
    normalized = (code or "").strip().upper()
    if not normalized:
        raise InstrumentResolutionError("标的代码不能为空")
    if market not in SUPPORTED_MARKETS:
        raise InstrumentResolutionError(f"不支持的市场: {market}")
    if market == "a_shares" and (not normalized.isdigit() or len(normalized) != 6):
        raise InstrumentResolutionError("A股标的代码必须是 6 位数字")
    instrument = resolve(normalized, market=market, name_hint=name_hint)
    if instrument.instrument_id != f"{market}:{normalized}":
        raise InstrumentResolutionError("Instrument 解析结果与请求上下文不一致")
    return instrument


def resolve(code: str, market: str | None = None, name_hint: str = "") -> Instrument:
    """解析标的：本地缓存 → 腾讯报价 → 推断兜底。"""
    normalized = (code or "").strip().upper()
    actual_market = market or infer_market(normalized)

    # 1. 本地缓存
    cached = repository.get(normalized, actual_market)
    if cached and cached.name:
        return cached

    # 2. 腾讯报价回填名称（A 股 / 美股）
    resolved_name = (name_hint or "").strip()
    if not resolved_name and actual_market in ("a_shares", "us_stocks"):
        try:
            from apps.api.domains.portfolio.service import tencent_quote_detail

            detail_name, _, _ = tencent_quote_detail(normalized, actual_market)
            if detail_name:
                resolved_name = detail_name
        except Exception:  # noqa: BLE001 - 名称回填失败必须降级到本地标的元数据
            logger.debug("腾讯报价解析名称失败 %s/%s", actual_market, normalized)

    # 3. 构建 + 持久化
    instrument = build_instrument(normalized, actual_market, resolved_name)
    if cached and cached.name and not resolved_name:
        instrument = Instrument(
            code=cached.code,
            market=cached.market,
            exchange=cached.exchange,
            name=cached.name,
            currency=cached.currency,
            asset_class=cached.asset_class,
        )
    repository.upsert(instrument)
    return instrument


def _looks_like_exact_code(query: str, market: str) -> bool:
    normalized = query.strip().upper()
    if market == "a_shares":
        return bool(re.fullmatch(r"\d{6}", normalized))
    if market == "us_stocks":
        return bool(re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", normalized))
    if market == "crypto":
        return bool(re.fullmatch(r"[A-Z0-9]{2,15}(?:[-/][A-Z0-9]{2,15})?", normalized))
    return False


def normalize_crypto_swap_code(value: str) -> str:
    """Normalize a base, USDT pair, or OKX instId to a USDT swap code."""
    normalized = (value or "").strip().upper().replace("/", "-").replace(" ", "")
    if normalized.endswith("-SWAP") and normalized.endswith("-USDT-SWAP"):
        return normalized if re.fullmatch(r"[A-Z0-9]{2,15}-USDT-SWAP", normalized) else ""
    if re.fullmatch(r"[A-Z0-9]{2,15}-USDT", normalized):
        return f"{normalized}-SWAP"
    if re.fullmatch(r"[A-Z0-9]{2,15}USDT", normalized):
        return f"{normalized[:-4]}-USDT-SWAP"
    if re.fullmatch(r"[A-Z][A-Z0-9]{1,14}", normalized):
        return f"{normalized}-USDT-SWAP"
    return ""


def _alias_instrument(query: str) -> Instrument | None:
    normalized = query.strip().lower()
    for alias, (code, name) in CRYPTO_ALIASES.items():
        if normalized and normalized in alias.lower():
            return build_instrument(code, "crypto", name)
    return None


def _public_okx_catalog_error(exc: Exception) -> str:
    """Return a stable user-facing category without leaking transport details."""
    if isinstance(exc, requests.Timeout):
        return "OKX 公共合约目录连接超时"
    if isinstance(exc, requests.ConnectionError):
        return "OKX 公共合约目录暂时无法连接"
    if isinstance(exc, requests.HTTPError):
        return "OKX 公共合约目录服务异常"
    if isinstance(exc, (TypeError, ValueError)):
        return "OKX 公共合约目录响应格式异常"
    return "OKX 公共合约目录暂不可用"


def _load_okx_swap_contracts(*, refresh: bool = False) -> list[dict[str, Any]]:
    """Load public OKX USDT swap metadata with a short-lived process cache."""
    global _OKX_MARKET_CACHE, _OKX_MARKET_FETCHED_AT, _OKX_MARKET_LAST_ERROR
    global _OKX_MARKET_RETRY_AT
    now = time.monotonic()
    cached_at, cached = _OKX_MARKET_CACHE
    if not refresh and cached and now - cached_at < _OKX_MARKET_TTL_SECONDS:
        return cached
    with _OKX_MARKET_LOCK:
        now = time.monotonic()
        cached_at, cached = _OKX_MARKET_CACHE
        if not refresh and cached and now - cached_at < _OKX_MARKET_TTL_SECONDS:
            return cached
        if not refresh and now < _OKX_MARKET_RETRY_AT:
            return cached
        try:
            response = requests.get(
                "https://www.okx.com/api/v5/public/instruments",
                params={"instType": "SWAP"},
                timeout=(5, 15),
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != "0":
                raise RuntimeError(payload.get("msg") or "OKX instrument request failed")
            discovered: list[dict[str, Any]] = []
            for market_data in payload.get("data") or []:
                code = str(market_data.get("instId") or "").upper()
                if not code.endswith("-USDT-SWAP"):
                    continue
                if market_data.get("state") != "live":
                    continue
                base = str(market_data.get("base") or code.split("-", 1)[0]).upper()
                name = f"{base} / USDT 永续"
                discovered.append(
                    {
                        "instrument": build_instrument(code, "crypto", name),
                        "base": base,
                        "quote": "USDT",
                        "settle": str(market_data.get("settleCcy") or "USDT").upper(),
                        "contract_size": float(market_data.get("ctVal") or 1),
                        "price_precision": _optional_float(market_data.get("tickSz")),
                        "amount_precision": _optional_float(market_data.get("lotSz")),
                        "minimum_amount": _optional_float(market_data.get("minSz")),
                        "linear": market_data.get("ctType") == "linear",
                    }
                )
            discovered.sort(key=lambda item: item["instrument"].code)
            _OKX_MARKET_CACHE = (now, discovered)
            _OKX_MARKET_RETRY_AT = 0.0
            _OKX_MARKET_FETCHED_AT = time.time()
            _OKX_MARKET_LAST_ERROR = ""
            return discovered
        except Exception as exc:  # noqa: BLE001 - search must degrade to cached metadata
            logger.info("OKX public market discovery unavailable", exc_info=True)
            _OKX_MARKET_RETRY_AT = now + _OKX_MARKET_RETRY_SECONDS
            _OKX_MARKET_LAST_ERROR = _public_okx_catalog_error(exc)
            return cached


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _load_okx_swap_markets() -> list[Instrument]:
    return [item["instrument"] for item in _load_okx_swap_contracts()]


def okx_swap_catalog(query: str = "", limit: int = 100, *, refresh: bool = False) -> dict[str, Any]:
    """Return verified active OKX linear USDT swaps and contract parameters."""
    contracts = _load_okx_swap_contracts(refresh=refresh)
    raw_query = query.strip()
    alias = _alias_instrument(raw_query) if raw_query else None
    canonical = alias.code if alias else normalize_crypto_swap_code(raw_query)
    special_terms = OKX_CATALOG_SEARCH_TERMS.get(raw_query.lower(), ())
    needles = tuple(term.lower() for term in special_terms) or ((canonical or raw_query).lower(),)
    aliases_by_code = {code: name for code, name in CRYPTO_ALIASES.values()}
    rows: list[dict[str, Any]] = []
    for contract in contracts:
        instrument: Instrument = contract["instrument"]
        display_name = aliases_by_code.get(instrument.code, instrument.name)
        if any(needles) and not any(
            needle in instrument.code.lower() or needle in display_name.lower()
            for needle in needles
        ):
            continue
        rows.append(
            {
                **instrument.to_dict(),
                "name": display_name,
                "base": contract["base"],
                "quote": contract["quote"],
                "settle": contract["settle"],
                "contract_size": contract["contract_size"],
                "price_precision": contract["price_precision"],
                "amount_precision": contract["amount_precision"],
                "minimum_amount": contract["minimum_amount"],
                "linear": contract["linear"],
                "verified": True,
            }
        )
        if len(rows) >= limit:
            break
    cached_at, _ = _OKX_MARKET_CACHE
    age_seconds = max(0, int(time.monotonic() - cached_at)) if contracts else None
    return {
        "ok": bool(contracts),
        "source": "okx_public" if contracts else "unavailable",
        "query": raw_query,
        "count": len(rows),
        "total": len(contracts),
        "cache_age_seconds": age_seconds,
        "cache_ttl_seconds": _OKX_MARKET_TTL_SECONDS,
        "fetched_at": _OKX_MARKET_FETCHED_AT or None,
        "error": _OKX_MARKET_LAST_ERROR or None,
        "instruments": rows,
    }


def search(query: str, limit: int = 20, market: str | None = None) -> list[Instrument]:
    """按市场搜索本地标的；精确代码未登记时自动解析并缓存。"""
    if market is not None and market not in SUPPORTED_MARKETS:
        raise InstrumentResolutionError(f"不支持的市场: {market}")
    if not query or not query.strip():
        return repository.list_all(limit=limit, market=market)
    raw_query = query.strip()
    normalized = raw_query.upper()
    matches = repository.search(normalized, limit=limit, market=market)
    if market == "crypto":
        explicit_pair = re.fullmatch(r"[A-Z0-9]{2,15}(?:[-/][A-Z0-9]{2,15})", normalized)
        if explicit_pair:
            exact = next((item for item in matches if item.code == normalized), None)
            return [exact or resolve_strict(normalized, "crypto")]

        alias = _alias_instrument(raw_query)
        if alias and not any(item.code == alias.code for item in matches):
            matches = [alias, *matches]
        canonical = normalize_crypto_swap_code(raw_query)
        if canonical:
            canonical_match = next(
                (item for item in matches if item.code == canonical), None
            ) or build_instrument(canonical, "crypto")
            matches = [
                canonical_match,
                *(
                    item
                    for item in matches
                    if item.code != canonical and normalize_crypto_swap_code(item.code) != canonical
                ),
            ]
        if alias or canonical:
            return matches[:limit]
        remote = _load_okx_swap_markets()
        needle = raw_query.lower()
        remote_matches = [
            item for item in remote if needle in item.code.lower() or needle in item.name.lower()
        ]
        for item in remote_matches:
            if not any(existing.code == item.code for existing in matches):
                matches.append(item)
        return matches[:limit]
    if matches or market is None or not _looks_like_exact_code(normalized, market):
        return matches
    return [resolve_strict(normalized, market)]


def register(
    code: str,
    market: str | None = None,
    name: str = "",
    exchange: str = "",
    currency: str = "",
    asset_class: str = "",
) -> Instrument:
    """手动注册/更新 Instrument 元数据。"""
    instrument = build_instrument(code, market, name)
    # 允许手动覆盖推断值
    if exchange:
        instrument = Instrument(
            code=instrument.code,
            market=instrument.market,
            exchange=exchange,
            name=instrument.name or name,
            currency=currency or instrument.currency,
            asset_class=asset_class or instrument.asset_class,
        )
    elif currency or asset_class:
        instrument = Instrument(
            code=instrument.code,
            market=instrument.market,
            exchange=instrument.exchange,
            name=instrument.name,
            currency=currency or instrument.currency,
            asset_class=asset_class or instrument.asset_class,
        )
    repository.upsert(instrument)
    return instrument
