"""Instrument 服务：解析、搜索、注册。

解析优先级：
    1. 本地 instruments 表（已缓存的标的元数据）
    2. 腾讯实时报价接口（A 股 / 美股）回填名称
    3. 兜底：按代码推断市场/交易所/币种，名称留空
"""

from __future__ import annotations

import logging
import re

from . import repository
from .domain import Instrument, build_instrument, infer_market

logger = logging.getLogger(__name__)

SUPPORTED_MARKETS = frozenset({"a_shares", "crypto", "us_stocks", "mt5"})


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


def search(query: str, limit: int = 20, market: str | None = None) -> list[Instrument]:
    """按市场搜索本地标的；精确代码未登记时自动解析并缓存。"""
    if market is not None and market not in SUPPORTED_MARKETS:
        raise InstrumentResolutionError(f"不支持的市场: {market}")
    if not query or not query.strip():
        return repository.list_all(limit=limit, market=market)
    normalized = query.strip().upper()
    matches = repository.search(normalized, limit=limit, market=market)
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
