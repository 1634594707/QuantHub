"""腾讯财经数据源（A股）。

提供 A股日线 K 线与实时行情，作为 akshare/东财失败时的 fallback。
接口无需认证，稳定性较好。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timedelta

import pandas as pd
import requests

from core.data_feed.base import DataSource, Interval

logger = logging.getLogger(__name__)

_TENCENT_CODE_MAP = {
    "sh": "sh",
    "sz": "sz",
    "bj": "bj",
}


def _to_tencent_code(symbol: str) -> str:
    """把 600519 / 000001 等转换为 sh600519 / sz000001。"""
    s = symbol.strip().upper()
    if s.startswith(("SH", "SZ", "BJ")):
        return s.lower()
    # 主板/科创板/北交所简单规则
    if s.startswith(("60", "68", "69", "51", "50")):
        return f"sh{s}"
    return f"sz{s}"


class TencentSource(DataSource):
    """腾讯财经 A股数据源。"""

    name = "tencent"
    market = "a_shares"

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

        code = _to_tencent_code(symbol)
        end = end or datetime.now()
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
        except Exception:
            logger.exception("腾讯 K线请求失败 %s", symbol)
            return pd.DataFrame()

        data = payload.get("data", {}).get(code, {})
        key = "qfqday" if "qfqday" in data else ("day" if "day" in data else "week")
        rows = data.get(key, [])
        if not rows:
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
        if start:
            df = df[df["datetime"] >= pd.to_datetime(start)]
        if end:
            df = df[df["datetime"] <= pd.to_datetime(end)]
        if limit and len(df) > limit:
            df = df.tail(limit).reset_index(drop=True)
        return df.reset_index(drop=True)
