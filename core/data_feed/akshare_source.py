# -*- coding: utf-8 -*-
"""akshare 数据源（A股）。

依赖 akshare，按需安装: pip install akshare
统一返回 core.data_feed.base 中定义的结构。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Iterable

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config import get_config
from core.data_feed.base import (
    Announcement,
    DataSource,
    Interval,
    Kline,
    News,
    klines_to_df,
)

logger = logging.getLogger(__name__)

# akshare 周期映射
_INTERVAL_MAP = {
    Interval.DAILY: "daily",
    Interval.WEEKLY: "weekly",
    Interval.M1: "1",
    Interval.M5: "5",
    Interval.M15: "15",
    Interval.M30: "30",
    Interval.H1: "60",
}


class AkshareSource(DataSource):
    """akshare A股数据源。"""

    name = "akshare"
    market = "a_shares"

    def __init__(self) -> None:
        try:
            import akshare as ak  # noqa: F401
            self._ak = ak
        except ImportError as e:
            raise ImportError(
                "akshare 未安装，请运行: pip install akshare"
            ) from e
        retry_cfg = get_config().get("data_feed", {}).get("retry", {})
        self._max_attempts = retry_cfg.get("max_attempts", 4)
        self._backoff_base = retry_cfg.get("backoff_base", 1.5)
        self._backoff_cap = retry_cfg.get("backoff_cap", 30)

    def _retryer(self):
        return retry(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential(
                multiplier=self._backoff_base, max=self._backoff_cap
            ),
            retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
            reraise=True,
        )

    def supported_intervals(self) -> Iterable[Interval]:
        return tuple(_INTERVAL_MAP.keys())

    def get_kline(
        self,
        symbol: str,
        interval: Interval | str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> pd.DataFrame:
        interval = Interval(interval) if isinstance(interval, str) else interval
        if interval not in _INTERVAL_MAP:
            raise ValueError(f"akshare 不支持周期: {interval}")
        ak_period = _INTERVAL_MAP[interval]
        end = end or datetime.now()
        start = start or (end - timedelta(days=limit))

        @self._retryer()
        def _fetch():
            if interval in (Interval.DAILY, Interval.WEEKLY):
                df = self._ak.stock_zh_a_hist(
                    symbol=symbol, period=ak_period,
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust="qfq",
                )
            else:
                df = self._ak.stock_zh_a_hist_min_em(
                    symbol=symbol, period=ak_period,
                    start_date=start.strftime("%Y-%m-%d %H:%M:%S"),
                    end_date=end.strftime("%Y-%m-%d %H:%M:%S"),
                )
            return df

        try:
            df = _fetch()
        except Exception:
            logger.exception("akshare get_kline 失败: %s %s", symbol, interval)
            return pd.DataFrame()

        if df is None or df.empty:
            return pd.DataFrame()

        # 标准化列名（akshare 中文列 -> 统一英文）
        col_map = {
            "日期": "datetime", "时间": "datetime",
            "开盘": "open", "最高": "high", "最低": "low",
            "收盘": "close", "成交量": "volume", "成交额": "amount",
            "换手率": "turnover",
        }
        df = df.rename(columns=col_map)
        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
        df["symbol"] = symbol
        df["market"] = self.market
        df["interval"] = interval.value
        keep = ["symbol", "market", "interval", "datetime",
                "open", "high", "low", "close", "volume", "amount", "turnover"]
        return df[[c for c in keep if c in df.columns]].reset_index(drop=True)

    def get_news(self, symbol: str | None = None, limit: int = 50) -> list[News]:
        """获取财经新闻（akshare 财联社快讯）。"""
        @self._retryer()
        def _fetch():
            return self._ak.stock_info_global_em()

        try:
            df = _fetch()
        except Exception:
            logger.exception("akshare get_news 失败")
            return []
        if df is None or df.empty:
            return []
        news: list[News] = []
        for _, row in df.head(limit).iterrows():
            ts = pd.to_datetime(row.get("发布时间", row.get("datetime", datetime.now())))
            news.append(News(
                title=str(row.get("标题", row.get("title", ""))),
                content=str(row.get("内容", row.get("content", ""))),
                ts=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                source="eastmoney",
                url=row.get("链接") or row.get("url"),
            ))
        return news

    def get_announcements(self, symbol: str, limit: int = 50) -> list[Announcement]:
        """获取个股公告（akshare 上市公司公告）。"""
        @self._retryer()
        def _fetch():
            return self._ak.stock_notice_report(symbol=symbol)

        try:
            df = _fetch()
        except Exception:
            logger.exception("akshare get_announcements 失败: %s", symbol)
            return []
        if df is None or df.empty:
            return []
        anns: list[Announcement] = []
        for _, row in df.head(limit).iterrows():
            ts = pd.to_datetime(row.get("公告日期", datetime.now()))
            anns.append(Announcement(
                symbol=symbol,
                title=str(row.get("公告标题", row.get("title", ""))),
                ts=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                ann_type=str(row.get("公告类型", "")) or None,
            ))
        return anns
