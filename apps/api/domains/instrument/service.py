"""Instrument 服务：解析、搜索、注册。

解析优先级：
    1. 本地 instruments 表（已缓存的标的元数据）
    2. 腾讯实时报价接口（A 股 / 美股）回填名称
    3. 兜底：按代码推断市场/交易所/币种，名称留空
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime
from pathlib import Path
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
_OKX_MARKET_SOURCE = "unavailable"
_OKX_MARKET_LOCK = threading.Lock()
_OKX_MARKET_TTL_SECONDS = 15 * 60
_OKX_MARKET_RETRY_SECONDS = 60
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_OKX_CATALOG_SNAPSHOT_PATH = _PROJECT_ROOT / "data" / "market_cache" / "okx_swap_catalog.json"
_OKX_LOCAL_INDEX_PATH = _PROJECT_ROOT / "data" / "market_cache" / "okx_local_index.json"


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


def _contract_from_row(row: dict[str, Any], *, source: str) -> dict[str, Any] | None:
    code = str(row.get("code") or row.get("instId") or "").upper()
    if not code.endswith("-USDT-SWAP"):
        return None
    base = str(row.get("base") or code.split("-", 1)[0]).upper()
    name = str(row.get("name") or f"{base} / USDT 永续")
    live = source == "okx_public"
    return {
        "instrument": build_instrument(code, "crypto", name),
        "base": base,
        "quote": "USDT",
        "settle": str(row.get("settle") or row.get("settleCcy") or "USDT").upper(),
        "contract_size": _optional_float(row.get("contract_size", row.get("ctVal"))),
        "price_precision": _optional_float(row.get("price_precision", row.get("tickSz"))),
        "amount_precision": _optional_float(row.get("amount_precision", row.get("lotSz"))),
        "minimum_amount": _optional_float(row.get("minimum_amount", row.get("minSz"))),
        "linear": bool(row.get("linear", row.get("ctType") == "linear")),
        "verified": live,
        "research_ready": True,
        "trading_ready": live,
        "available_intervals": list(row.get("available_intervals") or []),
        "last_market_time": row.get("last_market_time"),
        "_catalog_source": source,
    }


def _reclassify_okx_catalog(
    contracts: list[dict[str, Any]], *, source: str
) -> list[dict[str, Any]]:
    reclassified: list[dict[str, Any]] = []
    for contract in contracts:
        instrument: Instrument = contract["instrument"]
        row = {
            **contract,
            "code": instrument.code,
            "name": instrument.name,
        }
        converted = _contract_from_row(row, source=source)
        if converted is not None:
            reclassified.append(converted)
    return reclassified


def _persist_okx_catalog(contracts: list[dict[str, Any]]) -> None:
    path = _OKX_CATALOG_SNAPSHOT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for contract in contracts:
        instrument: Instrument = contract["instrument"]
        rows.append(
            {
                "code": instrument.code,
                "name": instrument.name,
                "base": contract["base"],
                "settle": contract["settle"],
                "contract_size": contract["contract_size"],
                "price_precision": contract["price_precision"],
                "amount_precision": contract["amount_precision"],
                "minimum_amount": contract["minimum_amount"],
                "linear": contract["linear"],
            }
        )
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"fetched_at": time.time(), "instruments": rows}, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_persisted_okx_catalog() -> tuple[list[dict[str, Any]], float]:
    try:
        payload = json.loads(_OKX_CATALOG_SNAPSHOT_PATH.read_text(encoding="utf-8"))
        fetched_at = float(payload.get("fetched_at") or 0)
        contracts = [
            contract
            for row in payload.get("instruments") or []
            if (contract := _contract_from_row(row, source="okx_public_cache")) is not None
        ]
        return contracts, fetched_at
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return [], 0.0


def _load_local_okx_research_catalog() -> tuple[list[dict[str, Any]], float]:
    try:
        payload = json.loads(_OKX_LOCAL_INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return [], 0.0
    rows: list[dict[str, Any]] = []
    aliases_by_code = {code: name for code, name in CRYPTO_ALIASES.values()}
    for raw_symbol, intervals in (payload.get("symbols") or {}).items():
        normalized = str(raw_symbol).upper()
        if not normalized.endswith("USDT"):
            continue
        base = normalized[:-4]
        code = f"{base}-USDT-SWAP"
        last_market_time = max(
            (str(item.get("last")) for item in intervals.values() if item.get("last")),
            default=None,
        )
        contract = _contract_from_row(
            {
                "code": code,
                "name": aliases_by_code.get(code, f"{base} / USDT 离线研究"),
                "linear": True,
                "available_intervals": sorted(intervals),
                "last_market_time": last_market_time,
            },
            source="okx_local_cache",
        )
        if contract is not None:
            rows.append(contract)
    rows.sort(key=lambda item: item["instrument"].code)
    try:
        built_at = datetime.fromisoformat(str(payload.get("built_at"))).timestamp()
    except (TypeError, ValueError):
        built_at = _OKX_LOCAL_INDEX_PATH.stat().st_mtime
    return rows, built_at


def _load_okx_swap_contracts(*, refresh: bool = False) -> list[dict[str, Any]]:
    """Load public OKX USDT swap metadata with a short-lived process cache."""
    global _OKX_MARKET_CACHE, _OKX_MARKET_FETCHED_AT, _OKX_MARKET_LAST_ERROR
    global _OKX_MARKET_SOURCE
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
                timeout=(3, 10),
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
                contract = _contract_from_row(
                    {**market_data, "code": code, "base": base, "name": name}, source="okx_public"
                )
                if contract is not None:
                    discovered.append(contract)
            discovered.sort(key=lambda item: item["instrument"].code)
            try:
                _persist_okx_catalog(discovered)
            except OSError:
                logger.warning(
                    "OKX public catalogue snapshot could not be persisted", exc_info=True
                )
            _OKX_MARKET_CACHE = (now, discovered)
            _OKX_MARKET_RETRY_AT = 0.0
            _OKX_MARKET_FETCHED_AT = time.time()
            _OKX_MARKET_LAST_ERROR = ""
            _OKX_MARKET_SOURCE = "okx_public"
            return discovered
        except Exception as exc:  # noqa: BLE001 - search must degrade to cached metadata
            logger.info("OKX public market discovery unavailable", exc_info=True)
            _OKX_MARKET_RETRY_AT = now + _OKX_MARKET_RETRY_SECONDS
            _OKX_MARKET_LAST_ERROR = _public_okx_catalog_error(exc)
            fallback = _reclassify_okx_catalog(cached, source="okx_public_cache")
            fetched_at = _OKX_MARKET_FETCHED_AT
            source = "okx_public_cache" if cached else "unavailable"
            if not fallback:
                fallback, fetched_at = _load_persisted_okx_catalog()
                source = "okx_public_cache" if fallback else "unavailable"
            if not fallback:
                fallback, fetched_at = _load_local_okx_research_catalog()
                source = "okx_local_cache" if fallback else "unavailable"
            if fallback:
                _OKX_MARKET_CACHE = (now, fallback)
                _OKX_MARKET_FETCHED_AT = fetched_at
            _OKX_MARKET_SOURCE = source
            return fallback


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
                "verified": bool(contract.get("verified", True)),
                "research_ready": bool(contract.get("research_ready", True)),
                "trading_ready": bool(contract.get("trading_ready", True)),
                "available_intervals": list(contract.get("available_intervals") or []),
                "last_market_time": contract.get("last_market_time"),
            }
        )
        if len(rows) >= limit:
            break
    cached_at, _ = _OKX_MARKET_CACHE
    age_seconds = max(0, int(time.monotonic() - cached_at)) if contracts else None
    source = _OKX_MARKET_SOURCE
    if contracts and source == "unavailable":
        source = str(contracts[0].get("_catalog_source") or "okx_public")
    return {
        "ok": bool(contracts),
        "source": source if contracts else "unavailable",
        "degraded": bool(contracts) and source != "okx_public",
        "warning": _OKX_MARKET_LAST_ERROR or None,
        "query": raw_query,
        "count": len(rows),
        "total": len(contracts),
        "cache_age_seconds": age_seconds,
        "cache_ttl_seconds": _OKX_MARKET_TTL_SECONDS,
        "fetched_at": _OKX_MARKET_FETCHED_AT or None,
        "error": _OKX_MARKET_LAST_ERROR or None,
        "trading_ready_count": sum(1 for item in contracts if item.get("trading_ready", True)),
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
