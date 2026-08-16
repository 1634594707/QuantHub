"""AkShare adapter for A-share valuation reference populations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, time
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from threading import Lock
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from requests import ConnectionError as RequestsConnectionError
from requests import RequestException
from requests import Timeout as RequestsTimeout
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .akshare_provider import _akshare_client
from .contracts import ComparableGroup, PointInTimeProvenance
from .normalization import canonical_content_hash
from .provider import ValuationReferenceData

_HISTORY_COLUMNS = {
    "pe_ttm": ("pe_ttm", "PE_TTM"),
    "pb": ("pb", "PB"),
    "ps": ("ps_ttm", "PS_TTM"),
    "dividend_yield": ("dv_ttm", "DV_TTM"),
}

_INDUSTRY_COLUMNS = {
    "pb": ("市净率", "PB"),
    "ps": ("市销率", "PS"),
}

_BAIDU_INDICATORS = {
    "pe_ttm": "市盈率(TTM)",
    "pb": "市净率",
}

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_CIRCUIT_FAILURE_THRESHOLD = 2
_CIRCUIT_OPEN_SECONDS = 600.0
_circuit_lock = Lock()
_circuit_failures: dict[str, tuple[int, float]] = {}


class EndpointCircuitOpen(RuntimeError):
    pass


@retry(
    retry=retry_if_exception_type((RequestsConnectionError, RequestsTimeout)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.25, max=1),
    reraise=True,
)
def _call_with_retry(endpoint: Callable[..., pd.DataFrame], **kwargs: str) -> pd.DataFrame:
    return endpoint(**kwargs)


def _endpoint_key(endpoint: Callable[..., pd.DataFrame]) -> str:
    owner = getattr(endpoint, "__self__", None)
    owner_type = type(owner) if owner is not None else None
    prefix = (
        f"{owner_type.__module__}.{owner_type.__qualname__}"
        if owner_type is not None
        else getattr(endpoint, "__module__", "unknown")
    )
    return f"{prefix}.{getattr(endpoint, '__name__', type(endpoint).__name__)}"


def _call_with_circuit(endpoint: Callable[..., pd.DataFrame], **kwargs: str) -> pd.DataFrame:
    key = _endpoint_key(endpoint)
    now = monotonic()
    with _circuit_lock:
        failures, opened_until = _circuit_failures.get(key, (0, 0.0))
        if opened_until > now:
            raise EndpointCircuitOpen(f"valuation endpoint circuit open: {key}")
        if opened_until:
            _circuit_failures.pop(key, None)
            failures = 0
    try:
        result = _call_with_retry(endpoint, **kwargs)
    except RequestException:
        with _circuit_lock:
            failures += 1
            opened_until = (
                now + _CIRCUIT_OPEN_SECONDS if failures >= _CIRCUIT_FAILURE_THRESHOLD else 0.0
            )
            _circuit_failures[key] = (failures, opened_until)
        raise
    with _circuit_lock:
        _circuit_failures.pop(key, None)
    return result


def _decimal(value: Any, *, percent: bool = False) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite():
        return None
    return result / Decimal(100) if percent else result


def _first(row: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    return next((row[name] for name in names if name in row and not pd.isna(row[name])), None)


def _date_available_at(value: Any) -> datetime | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return datetime.combine(parsed.date(), time(23, 59, 59), tzinfo=_SHANGHAI)


class AkshareValuationReferenceProvider:
    name = "akshare-valuation-references"

    def __init__(
        self,
        client: Any | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._clock = clock or (lambda: datetime.now(UTC))

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = _akshare_client()
        return self._client

    def fetch_references(self, *, instrument_id: str, as_of: datetime) -> ValuationReferenceData:
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        symbol = instrument_id.rsplit(":", 1)[-1]
        if not symbol.isdigit() or len(symbol) != 6:
            raise ValueError("A 股估值参照要求 6 位证券代码")
        client = self._get_client()
        fetched_at = self._clock()
        quality_reasons: list[str] = []
        shares_at = fetched_at
        industry = ""
        try:
            info_endpoint = client.stock_individual_info_em
            info = _call_with_circuit(info_endpoint, symbol=symbol)
            info_map = {
                str(row.get("item") or row.get("项目")): row.get("value", row.get("值"))
                for row in info.to_dict(orient="records")
            }
            shares = _decimal(info_map.get("总股本"))
            industry = str(info_map.get("行业") or "").strip()
        except (RequestException, EndpointCircuitOpen, AttributeError, KeyError, IndexError):
            profile = _call_with_retry(client.stock_profile_cninfo, symbol=symbol)
            changes = _call_with_retry(
                client.stock_share_change_cninfo,
                symbol=symbol,
                start_date="19900101",
                end_date=as_of.astimezone(_SHANGHAI).strftime("%Y%m%d"),
            )
            profile_row = profile.iloc[0].to_dict() if not profile.empty else {}
            industry = str(profile_row.get("所属行业") or "").strip()
            candidates: list[tuple[datetime, Mapping[str, Any]]] = []
            for row in changes.to_dict(orient="records"):
                available_at = _date_available_at(row.get("公告日期"))
                if available_at is not None and available_at <= as_of:
                    candidates.append((available_at, row))
            if not candidates:
                raise RuntimeError("没有获取到公告时点有效的股本数据")
            shares_at, share_row = max(candidates, key=lambda item: item[0])
            raw_shares = _decimal(share_row.get("总股本"))
            shares = raw_shares * Decimal(10000) if raw_shares is not None else None
            quality_reasons.append("FALLBACK_CNINFO_SHARE_PROFILE")
        if shares is None or shares <= 0:
            raise RuntimeError("股本数据缺失或无效")

        historical_values: dict[str, tuple[Decimal, ...]] = {key: () for key in _HISTORY_COLUMNS}
        history_endpoint = getattr(client, "stock_a_indicator_lg", None)
        if history_endpoint is not None:
            try:
                history = _call_with_circuit(history_endpoint, symbol=symbol).copy()
                date_column = next(
                    (name for name in ("trade_date", "date", "日期") if name in history), None
                )
                if date_column:
                    history[date_column] = pd.to_datetime(history[date_column], errors="coerce")
                    history = history[history[date_column].dt.date <= as_of.date()]
                for key, aliases in _HISTORY_COLUMNS.items():
                    column = next((name for name in aliases if name in history), None)
                    if column is None:
                        continue
                    historical_values[key] = tuple(
                        value
                        for raw in history[column].tolist()
                        if (value := _decimal(raw, percent=key == "dividend_yield")) is not None
                        and value > 0
                    )
            except (RequestException, EndpointCircuitOpen, KeyError, IndexError):
                history_endpoint = None
        if history_endpoint is None:
            baidu_endpoint = getattr(client, "stock_zh_valuation_baidu", None)
            if baidu_endpoint is None:
                quality_reasons.append("HISTORICAL_VALUATION_UNAVAILABLE")
            else:
                for key, indicator in _BAIDU_INDICATORS.items():
                    try:
                        frame = _call_with_retry(
                            baidu_endpoint,
                            symbol=symbol,
                            indicator=indicator,
                            period="全部",
                        ).copy()
                        date_column = next(
                            (name for name in ("date", "日期") if name in frame), None
                        )
                        value_column = next(
                            (name for name in ("value", "数值") if name in frame), None
                        )
                        if date_column is None or value_column is None:
                            continue
                        frame[date_column] = pd.to_datetime(frame[date_column], errors="coerce")
                        frame = frame[frame[date_column].dt.date <= as_of.date()]
                        historical_values[key] = tuple(
                            value
                            for raw in frame[value_column].tolist()
                            if (value := _decimal(raw)) is not None and value > 0
                        )
                    except (RequestException, KeyError, IndexError):
                        quality_reasons.append(f"HISTORICAL_{key.upper()}_UNAVAILABLE")
                quality_reasons.append("FALLBACK_BAIDU_VALUATION_HISTORY")

        members: tuple[str, ...] = ()
        industry_values: dict[str, tuple[Decimal, ...]] = {}
        if industry:
            try:
                industry_endpoint = client.stock_board_industry_cons_em
                industry_frame = _call_with_circuit(industry_endpoint, symbol=industry)
                records = industry_frame.to_dict(orient="records")
                members = tuple(
                    str(code)
                    for row in records
                    if (code := _first(row, ("代码", "symbol", "SECURITY_CODE"))) is not None
                )
                for key, aliases in _INDUSTRY_COLUMNS.items():
                    industry_values[key] = tuple(
                        value
                        for row in records
                        if (value := _decimal(_first(row, aliases))) is not None and value > 0
                    )
            except (RequestException, EndpointCircuitOpen, AttributeError, KeyError, IndexError):
                quality_reasons.append("INDUSTRY_CROSS_SECTION_UNAVAILABLE")
        payload = {
            "instrument_id": instrument_id,
            "shares": str(shares),
            "industry": industry,
            "members": members,
            "historical_counts": {key: len(values) for key, values in historical_values.items()},
            "industry_counts": {key: len(values) for key, values in industry_values.items()},
            "quality_reasons": sorted(set(quality_reasons)),
        }
        content_hash = canonical_content_hash(payload)
        group = None
        if industry:
            group_version = sha256(
                f"{industry}|{as_of.date()}|{'|'.join(members)}".encode()
            ).hexdigest()[:16]
            group = ComparableGroup(
                group_id=f"a-share-industry:{industry}",
                version=group_version,
                industry=industry,
                members=members,
                selection_method="eastmoney_industry"
                if members
                else "cninfo_industry_without_peer_snapshot",
            )
        provenance = PointInTimeProvenance(
            source=self.name,
            source_url="https://webapi.cninfo.com.cn/;https://gushitong.baidu.com/stock/",
            published_at=shares_at,
            available_at=fetched_at,
            fetched_at=fetched_at,
            revision=as_of.date().isoformat(),
            content_hash=content_hash,
            quality_status="degraded" if quality_reasons else "single_source",
            quality_reasons=tuple(sorted(set(quality_reasons))) or ("SINGLE_SOURCE",),
        )
        return ValuationReferenceData(
            instrument_id=instrument_id,
            shares_outstanding=shares,
            shares_at=shares_at,
            historical_values=historical_values,
            industry_values=industry_values,
            comparable_values=industry_values,
            comparable_group=group,
            provenance=provenance,
        )
