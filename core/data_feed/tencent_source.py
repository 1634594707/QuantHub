"""腾讯财经数据源（A股）。

提供 A股日线 K 线与实时行情，作为 akshare/东财失败时的 fallback。
接口无需认证，稳定性较好。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

import pandas as pd
import requests

from core.data_feed.base import DataSource, Interval
from core.data_feed.quality import normalize_ohlcv_rows

logger = logging.getLogger(__name__)

_TENCENT_CODE_MAP = {
    "sh": "sh",
    "sz": "sz",
    "bj": "bj",
}


def _to_tencent_code(symbol: str, market: str = "a_shares") -> str:
    """把标的转换为腾讯代码。

    - A股: 600519 -> sh600519（60/68/69/51/50 开头用 sh，其余 sz）
    - 美股: NVDA -> usNVDA
    - 港股: 00700 -> hk00700
    """
    s = symbol.strip().upper()
    if market == "us_stocks":
        return f"us{s}"
    if market == "hk":
        return f"hk{s}"
    if s.startswith(("SH", "SZ", "BJ")):
        return s.lower()
    # 主板/科创板/北交所简单规则
    if s.startswith(("60", "68", "69", "51", "50")):
        return f"sh{s}"
    return f"sz{s}"


class TencentSource(DataSource):
    """腾讯财经数据源（A股/美股/港股日线，无需认证，可穿透本机代理）。"""

    name = "tencent"

    def __init__(self, market: str = "a_shares") -> None:
        self.market = market

    def supported_intervals(self) -> Iterable[Interval]:
        return (Interval.DAILY, Interval.WEEKLY)

    def get_kline(
        self,
        symbol: str,
        interval: Interval | str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> pd.DataFrame:
        interval = Interval(interval) if isinstance(interval, str) else interval
        if interval not in (Interval.DAILY, Interval.WEEKLY):
            raise ValueError(f"腾讯数据源仅支持日线/周线: {interval}")

        code = _to_tencent_code(symbol, self.market)
        end = end or datetime.now(UTC)
        start = start or (end - timedelta(days=limit * 2))
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")
        tencent_interval = "day" if interval == Interval.DAILY else "week"
        url = (
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            f"?param={code},{tencent_interval},{start_str},{end_str},{limit * 2},qfq"
        )

        try:
            r = requests.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://quote.eastmoney.com/",
                },
                timeout=20,
            )
            r.raise_for_status()
            payload = r.json()
        except Exception as exc:  # noqa: BLE001 - normalize transport and payload failures
            logger.warning(
                "腾讯 K线请求失败 %s (proxies=%s): %s",
                symbol,
                {
                    k: v
                    for k, v in requests.utils.defaults().items()
                    if k in ("HTTPS_PROXY", "HTTP_PROXY")
                },
                exc,
            )
            return pd.DataFrame()

        data = payload.get("data", {}).get(code, {})
        key = "qfqday" if "qfqday" in data else ("day" if "day" in data else "week")
        rows = data.get(key, [])
        if not rows:
            logger.warning(
                "腾讯 K线 %s 拿空: code=%s data_keys=%s",
                symbol,
                code,
                list(data.keys()),
            )
            return pd.DataFrame()
        if self.market == "us_stocks" and len(rows) < min(limit, 20):
            logger.warning(
                "腾讯美股历史数据不足 %s: 期望至少 %d 条，实际 %d 条，转入 fallback",
                symbol,
                min(limit, 20),
                len(rows),
            )
            return pd.DataFrame()

        # 腾讯返回：[date, open, close, high, low, volume]；除权日可能带第 7 列分红信息，只取前 6 列
        trimmed = [r[:6] for r in rows]
        df = pd.DataFrame(trimmed, columns=["datetime", "open", "close", "high", "low", "volume"])
        df["datetime"] = pd.to_datetime(df["datetime"])
        for col in ["open", "close", "low", "high", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["symbol"] = symbol
        df["market"] = self.market
        df["interval"] = interval.value
        df["amount"] = pd.NA
        df["turnover"] = pd.NA
        df = df[
            [
                "symbol",
                "market",
                "interval",
                "datetime",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "turnover",
            ]
        ]
        # tencent 内部 datacol: datetime 列无 tzinfo；外部 start/end 可能带 tz，
        # 比较前必须 strip tzinfo，否则 pandas 抛 "Invalid comparison between dtype=datetime64[us] and Timestamp"
        start_dt = pd.to_datetime(start).tz_localize(None) if start is not None else None
        end_dt = pd.to_datetime(end).tz_localize(None) if end is not None else None
        df = normalize_ohlcv_rows(df)
        if start_dt is not None:
            df = df[df["datetime"] >= start_dt]
        if end_dt is not None:
            df = df[df["datetime"] <= end_dt]  # type: ignore[operator]
        if limit and len(df) > limit:
            df = df.tail(limit).reset_index(drop=True)
        df = df.reset_index(drop=True)
        df.attrs["corporate_action_adjustment"] = "qfq"
        return df
