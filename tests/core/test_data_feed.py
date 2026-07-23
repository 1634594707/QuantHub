# -*- coding: utf-8 -*-
"""core.data_feed 单测（不依赖网络）。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from core.data_feed.base import (
    Announcement,
    DataSource,
    Interval,
    Kline,
    Market,
    News,
    klines_to_df,
)


def test_interval_enum():
    assert Interval.DAILY.value == "1d"
    assert Interval.M1.value == "1m"


def test_market_enum():
    assert Market.A_SHARES.value == "a_shares"
    assert Market.CRYPTO.value == "crypto"


def test_kline_to_row():
    k = Kline(symbol="000001", market="a_shares", interval="1d",
              open=10, high=11, low=9.5, close=10.5, volume=1000, ts=datetime.now())
    row = k.to_row()
    assert row["symbol"] == "000001"
    assert row["open"] == 10
    assert "datetime" in row


def test_klines_to_df_empty():
    df = klines_to_df([])
    assert df.empty
    assert "symbol" in df.columns


def test_klines_to_df_sorted():
    now = datetime.now()
    k1 = Kline(symbol="x", market="a_shares", interval="1d",
               open=1, high=2, low=0.5, close=1.5, volume=10, ts=now)
    k2 = Kline(symbol="x", market="a_shares", interval="1d",
               open=1, high=2, low=0.5, close=1.5, volume=10, ts=now - timedelta(days=1))
    df = klines_to_df([k1, k2])
    assert len(df) == 2
    # 升序
    assert df.iloc[0]["datetime"] <= df.iloc[1]["datetime"]


def test_datasource_default_news_empty():
    """未实现 get_news 的数据源返回空列表。"""

    class Stub(DataSource):
        name = "stub"
        market = "a_shares"
        def get_kline(self, symbol, interval, start=None, end=None, limit=500):
            return pd.DataFrame()

    s = Stub()
    assert s.get_news("x") == []
    assert s.get_announcements("x") == []


def test_news_dataclass():
    n = News(title="t", content="c", ts=datetime.now(), source="eastmoney")
    assert n.symbols == []


def test_announcement_dataclass():
    a = Announcement(symbol="000001", title="t", ts=datetime.now())
    assert a.content is None
    assert a.ann_type is None
