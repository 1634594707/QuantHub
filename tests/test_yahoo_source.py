from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import Mock, patch

import requests

from core.data_feed.base import Interval
from core.data_feed.factory import _build_source
from core.data_feed.yahoo_source import YahooSource


class YahooSourceTests(unittest.TestCase):
    def test_parses_chart_response_and_drops_incomplete_rows(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "chart": {
                "error": None,
                "result": [
                    {
                        "timestamp": [1_750_032_000, 1_750_118_400, 1_750_204_800],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [130.0, None, 132.0],
                                    "high": [133.0, None, 135.0],
                                    "low": [129.0, None, 131.0],
                                    "close": [132.0, None, 134.0],
                                    "volume": [1000, None, 1200],
                                }
                            ]
                        },
                    }
                ],
            }
        }

        with patch("core.data_feed.yahoo_source.requests.get", return_value=response) as get:
            frame = YahooSource().get_kline(
                "nvda",
                Interval.DAILY,
                start=datetime(2025, 6, 1, tzinfo=UTC),
                end=datetime(2025, 7, 1, tzinfo=UTC),
                limit=2,
            )

        self.assertEqual(len(frame), 2)
        self.assertEqual(frame["symbol"].tolist(), ["NVDA", "NVDA"])
        self.assertEqual(frame["market"].tolist(), ["us_stocks", "us_stocks"])
        self.assertEqual(frame["close"].tolist(), [132.0, 134.0])
        self.assertEqual(get.call_args.kwargs["params"]["interval"], "1d")
        self.assertGreater(
            get.call_args.kwargs["params"]["period2"],
            get.call_args.kwargs["params"]["period1"],
        )

    def test_retries_the_secondary_chart_host(self) -> None:
        failed = Mock()
        failed.raise_for_status.side_effect = requests.RequestException("primary unavailable")
        succeeded = Mock()
        succeeded.raise_for_status.return_value = None
        succeeded.json.return_value = {
            "chart": {
                "error": None,
                "result": [
                    {
                        "timestamp": [1_750_032_000],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [130.0],
                                    "high": [133.0],
                                    "low": [129.0],
                                    "close": [132.0],
                                    "volume": [1000],
                                }
                            ]
                        },
                    }
                ],
            }
        }

        with patch(
            "core.data_feed.yahoo_source.requests.get",
            side_effect=[failed, succeeded],
        ) as get:
            frame = YahooSource().get_kline("NVDA", Interval.WEEKLY, limit=10)

        self.assertEqual(len(frame), 1)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args.kwargs["params"]["interval"], "1wk")

    def test_factory_builds_yahoo_for_us_stocks(self) -> None:
        source = _build_source("yahoo", cfg={}, market="us_stocks")

        self.assertIsInstance(source, YahooSource)
        self.assertEqual(source.name, "yahoo")


if __name__ == "__main__":
    unittest.main()
