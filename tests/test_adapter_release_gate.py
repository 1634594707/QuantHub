import unittest
from datetime import UTC, datetime
from unittest.mock import patch

import pandas as pd

from core.data_feed.akshare_source import AkshareSource
from core.data_feed.eastmoney_source import EastmoneySource
from core.data_feed.okx_source import OkxSource
from core.data_feed.tencent_source import TencentSource
from core.data_feed.yahoo_source import YahooSource


class _Response:
    def __init__(self, payload):
        self.payload = payload
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _assert_ordered_unique(test: unittest.TestCase, frame: pd.DataFrame) -> None:
    test.assertFalse(frame.empty)
    test.assertTrue(frame["datetime"].is_monotonic_increasing)
    test.assertEqual(frame["datetime"].nunique(), len(frame))
    test.assertTrue(frame[["open", "high", "low", "close"]].notna().all().all())


class AdapterReleaseGateTests(unittest.TestCase):
    def test_a_share_adapters_normalize_missing_duplicates_and_qfq_metadata(self):
        ak = AkshareSource.__new__(AkshareSource)
        ak._max_attempts, ak._backoff_base, ak._backoff_cap = 1, 0, 0
        ak._ak = type(
            "Ak",
            (),
            {
                "stock_zh_a_hist": lambda *_args, **_kwargs: pd.DataFrame(
                    {
                        "日期": ["2024-01-02", "2024-01-01", "2024-01-02"],
                        "开盘": [None, 9, 10],
                        "最高": [11, 10, 11],
                        "最低": [9, 8, 9],
                        "收盘": [10, 9, 10.5],
                        "成交量": [1, 2, 3],
                    }
                )
            },
        )()
        frame = ak.get_kline("600519", "1d", limit=10)
        _assert_ordered_unique(self, frame)
        self.assertEqual(frame.attrs["corporate_action_adjustment"], "qfq")

        east = EastmoneySource.__new__(EastmoneySource)
        east._max_attempts, east._backoff_base, east._backoff_cap = 1, 0, 0
        east._session = type(
            "Session",
            (),
            {
                "get": lambda *_args, **_kwargs: _Response(
                    {
                        "data": {
                            "klines": [
                                "2024-01-02,10,10.5,11,9,3,100",
                                "2024-01-01,9,9.5,10,8,2,90",
                                "2024-01-02,10,10.6,11,9,4,110",
                            ]
                        }
                    }
                )
            },
        )()
        frame = east.get_kline("600519", "1d", limit=10)
        _assert_ordered_unique(self, frame)
        self.assertEqual(frame.attrs["corporate_action_adjustment"], "qfq")

    def test_tencent_yahoo_and_okx_gate_company_actions_and_order(self):
        tencent_payload = {
            "data": {
                "sh600519": {
                    "qfqday": [
                        ["2024-01-02", "10", "10.5", "11", "9", "3"],
                        ["2024-01-01", "9", "9.5", "10", "8", "2"],
                        ["2024-01-02", "10", "10.6", "11", "9", "4"],
                    ]
                }
            }
        }
        with patch(
            "core.data_feed.tencent_source.requests.get", return_value=_Response(tencent_payload)
        ):
            frame = TencentSource().get_kline(
                "600519",
                "1d",
                start=datetime(2024, 1, 1),  # noqa: DTZ001 - adapter contract accepts local dates
                end=datetime(2024, 1, 3),  # noqa: DTZ001 - adapter contract accepts local dates
                limit=10,
            )
        _assert_ordered_unique(self, frame)
        self.assertEqual(frame.attrs["corporate_action_adjustment"], "qfq")

        yahoo_payload = {
            "chart": {
                "result": [
                    {
                        "timestamp": [
                            int(datetime(2024, 1, 2, tzinfo=UTC).timestamp()),
                            int(datetime(2024, 1, 1, tzinfo=UTC).timestamp()),
                            int(datetime(2024, 1, 2, tzinfo=UTC).timestamp()),
                        ],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [10, 18, 10],
                                    "high": [11, 20, 11],
                                    "low": [9, 16, 9],
                                    "close": [10, 18, 10],
                                    "volume": [3, 2, 4],
                                }
                            ],
                            "adjclose": [{"adjclose": [5, 9, 5]}],
                        },
                    }
                ],
                "error": None,
            }
        }
        with patch(
            "core.data_feed.yahoo_source.requests.get", return_value=_Response(yahoo_payload)
        ):
            frame = YahooSource().get_kline("AAPL", "1d", limit=10)
        _assert_ordered_unique(self, frame)
        self.assertEqual(frame.attrs["corporate_action_adjustment"], "adjclose_ratio")
        self.assertAlmostEqual(float(frame.iloc[-1]["close"]), 5.0)

        okx = OkxSource.__new__(OkxSource)
        okx._max_attempts, okx._backoff_base, okx._backoff_cap = 1, 0, 0
        okx._exchange = type(
            "Exchange",
            (),
            {
                "fetch_ohlcv": lambda *_args, **_kwargs: [
                    [1704153600000, 10, 11, 9, 10, 3],
                    [1704067200000, 9, 10, 8, 9, 2],
                    [1704153600000, 10, 11, 9, 10.5, 4],
                ]
            },
        )()
        frame = okx.get_kline("BTC-USDT", "1d", limit=10)
        _assert_ordered_unique(self, frame)
        self.assertEqual(frame.attrs["corporate_action_adjustment"], "not_applicable")


if __name__ == "__main__":
    unittest.main()
