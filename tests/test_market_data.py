"""Offline regression checks for independent, concurrent candle downloads."""
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pandas as pd

from grok_quantum_bot import TradingBot


def history(interval, count=12):
    index = pd.date_range("2026-10-01 01:00", periods=count,
                          freq={"15m": "15min", "1h": "1h"}[interval], tz="UTC")
    prices = [100.0 + i for i in range(count)]
    return pd.DataFrame({
        "Open": prices, "High": [p + 1 for p in prices],
        "Low": [p - .5 for p in prices], "Close": [p + .5 for p in prices],
        "Volume": [10] * count,
    }, index=index)


class MarketDataTests(unittest.TestCase):
    def test_concurrent_same_symbol_downloads_keep_their_own_intervals(self):
        # Model the provider's shared per-symbol result slot. Hold the first
        # call open while a second engine instance requests another interval.
        first_entered = threading.Event()
        release_first = threading.Event()
        second_attempted = threading.Event()
        second_entered = threading.Event()
        shared = {}
        calls = []
        frames = {interval: history(interval) for interval in ("15m", "1h")}

        def download(**kwargs):
            calls.append(kwargs)
            shared[kwargs["tickers"]] = frames[kwargs["interval"]]
            if kwargs["interval"] == "15m":
                first_entered.set()
                if not release_first.wait(2):
                    raise TimeoutError("First download was not released")
            else:
                second_entered.set()
            return shared[kwargs["tickers"]]

        def second_request():
            second_attempted.set()
            return TradingBot().fetch_data("EURUSD=X", period="60d", interval="1h")

        with patch("grok_quantum_bot.yf.download", side_effect=download):
            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(TradingBot().fetch_data, "EURUSD=X", "60d", "15m")
                try:
                    self.assertTrue(first_entered.wait(2))
                    second = executor.submit(second_request)
                    self.assertTrue(second_attempted.wait(2))
                    # A queued engine call must not enter the provider while
                    # the first holds its shared result. Events control the
                    # schedule; no network response timing is involved.
                    self.assertFalse(second_entered.wait(.1))
                finally:
                    release_first.set()
                first_result, second_result = first.result(timeout=2), second.result(timeout=2)

        self.assertTrue(second_entered.is_set())
        for interval, result in (("15m", first_result), ("1h", second_result)):
            pd.testing.assert_frame_equal(result.drop(columns="Returns"), frames[interval])
        self.assertEqual([call["interval"] for call in calls], ["15m", "1h"])
        for call in calls:
            self.assertEqual(call, {
                "tickers": "EURUSD=X", "period": "60d", "interval": call["interval"],
                "auto_adjust": False, "progress": False, "multi_level_index": False,
            })

    def test_four_hour_history_keeps_hourly_download_and_utc_bucket_aggregation(self):
        with patch("grok_quantum_bot.yf.download", return_value=history("1h")) as download:
            result = TradingBot().fetch_data("EURUSD=X", period="60d", interval="4h")
        download.assert_called_once_with(
            tickers="EURUSD=X", period="60d", interval="1h",
            auto_adjust=False, progress=False, multi_level_index=False,
        )
        self.assertEqual(result.index.hour.tolist(), [0, 4, 8, 12])
        self.assertEqual(str(result.index.tz), "UTC")
        self.assertEqual(result["Open"].tolist(), [100, 103, 107, 111])
        self.assertEqual(result["High"].tolist(), [103, 107, 111, 112])
        self.assertEqual(result["Low"].tolist(), [99.5, 102.5, 106.5, 110.5])
        self.assertEqual(result["Close"].tolist(), [102.5, 106.5, 110.5, 111.5])
        self.assertEqual(result["Volume"].tolist(), [30, 40, 40, 10])

    def test_failed_download_releases_the_process_lock(self):
        with patch("grok_quantum_bot.yf.download", side_effect=[RuntimeError("Feed down"), history("1h")]):
            with self.assertRaisesRegex(RuntimeError, "Feed down"):
                TradingBot().fetch_data()
            with ThreadPoolExecutor(max_workers=1) as executor:
                result = executor.submit(TradingBot().fetch_data).result(timeout=2)
        self.assertEqual(len(result), 12)


if __name__ == "__main__":
    unittest.main()
