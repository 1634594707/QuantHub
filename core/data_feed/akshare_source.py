"""akshare 数据源（A股）。

依赖 akshare，按需安装: pip install akshare
统一返回 core.data_feed.base 中定义的结构。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import datetime, timedelta

import pandas as pd
import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from core.config import get_config
from core.data_feed.base import (
    Announcement,
    DataSource,
    Interval,
    News,
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
            import akshare as ak

            self._ak = ak
        except ImportError as e:
            raise ImportError("akshare 未安装，请运行: pip install akshare") from e
        retry_cfg = get_config().get("data_feed", {}).get("retry", {})
        self._max_attempts = retry_cfg.get("max_attempts", 4)
        self._backoff_base = retry_cfg.get("backoff_base", 1.5)
        self._backoff_cap = retry_cfg.get("backoff_cap", 30)

    def _retryer(self):
        return retry(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential(multiplier=self._backoff_base, max=self._backoff_cap),
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
                    symbol=symbol,
                    period=ak_period,
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust="qfq",
                )
            else:
                df = self._ak.stock_zh_a_hist_min_em(
                    symbol=symbol,
                    period=ak_period,
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
            "日期": "datetime",
            "时间": "datetime",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
            "换手率": "turnover",
        }
        df = df.rename(columns=col_map)
        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
        df["symbol"] = symbol
        df["market"] = self.market
        df["interval"] = interval.value
        keep = [
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
        return df[[c for c in keep if c in df.columns]].reset_index(drop=True)

    def get_news(self, symbol: str | None = None, limit: int = 50) -> list[News]:
        """获取财经新闻（优先按股票代码查东财个股新闻，否则回退全球快讯）。"""
        if symbol:
            try:
                return self._fetch_stock_news_em(symbol, limit)
            except Exception:
                logger.warning(
                    "akshare 个股新闻获取失败 %s，尝试 global 新闻", symbol, exc_info=True
                )

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
            news.append(
                News(
                    title=str(row.get("标题", row.get("title", ""))),
                    content=str(row.get("内容", row.get("content", ""))),
                    ts=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                    source="eastmoney",
                    url=row.get("链接") or row.get("url"),
                )
            )
        return news

    def _fetch_stock_news_em(self, symbol: str, limit: int) -> list[News]:
        """调用东方财富 search-api-web 获取个股新闻（绕过 akshare 的 pandas/arrow bug）。"""
        url = "https://search-api-web.eastmoney.com/search/jsonp"
        inner_param = {
            "uid": "",
            "keyword": symbol,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "param": {
                "cmsArticleWebOld": {
                    "searchScope": "default",
                    "sort": "default",
                    "pageIndex": 1,
                    "pageSize": min(limit, 100),
                    "preTag": "<em>",
                    "postTag": "</em>",
                }
            },
        }
        cb = "jQuery35101792940631092459_1764599530165"
        params = {
            "cb": cb,
            "param": json.dumps(inner_param, ensure_ascii=False),
            "_": "1764599530176",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": f"https://so.eastmoney.com/news/s?keyword={symbol}",
        }

        @self._retryer()
        def _fetch():
            r = requests.get(url, params=params, headers=headers, timeout=15)
            r.raise_for_status()
            return r.text

        data_text = _fetch()
        prefix = cb + "("
        if data_text.startswith(prefix):
            data_json = json.loads(data_text[len(prefix) : -1])
        else:
            data_json = json.loads(data_text)
        items = data_json.get("result", {}).get("cmsArticleWebOld", [])

        def _clean(text: str) -> str:
            return (
                str(text or "")
                .replace("<em>", "")
                .replace("</em>", "")
                .replace("\u3000", "")
                .replace("\r\n", " ")
                .replace("\r", " ")
                .replace("\n", " ")
                .strip()
            )

        news: list[News] = []
        for it in items[:limit]:
            ts_raw = it.get("date", datetime.now().isoformat())
            try:
                ts = pd.to_datetime(ts_raw).to_pydatetime()
            except Exception:
                ts = datetime.now()
            news.append(
                News(
                    title=_clean(it.get("title", "")),
                    content=_clean(it.get("content", "")),
                    ts=ts,
                    source=str(it.get("mediaName", "eastmoney")),
                    url=f"http://finance.eastmoney.com/a/{it.get('code', '')}.html"
                    if it.get("code")
                    else None,
                )
            )
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
            anns.append(
                Announcement(
                    symbol=symbol,
                    title=str(row.get("公告标题", row.get("title", ""))),
                    ts=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                    ann_type=str(row.get("公告类型", "")) or None,
                )
            )
        return anns
