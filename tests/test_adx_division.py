"""Offline ADX numeric regressions; no market requests or account access."""
import ast
import inspect
import unittest
import warnings

import numpy as np
import pandas as pd

import dashboard


def chart_adx_function():
    # Execute the actual nested chart calculator without invoking its HTTP route
    # or unrelated indicators. Keep the production function nested as before.
    tree = ast.parse(inspect.getsource(dashboard.chart_data))
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_adx_series")
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    namespace = {"np": np, "pd": pd}
    exec(compile(module, "<actual chart ADX calculator>", "exec"), namespace)
    return namespace["_adx_series"]


def frame(close, width=0.0):
    close = np.asarray(close, dtype=float)
    index = pd.date_range("2026-10-01", periods=len(close), freq="15min",
                          tz="UTC", name="candle_time")
    return pd.DataFrame({"High": close + width, "Low": close - width,
                         "Close": close}, index=index)


def scalar_reference(data, period):
    """Independent scalar recurrence with explicit zero-denominator handling."""
    tr_s = plus_s = minus_s = adx = None
    previous_high = previous_low = previous_close = None
    result = []
    for high, low, close in data[["High", "Low", "Close"]].itertuples(index=False, name=None):
        if previous_close is None:
            true_range, plus_dm, minus_dm = high - low, 0.0, 0.0
        else:
            true_range = max(high - low, abs(high - previous_close), abs(low - previous_close))
            up, down = high - previous_high, previous_low - low
            plus_dm = up if up > down and up > 0 else 0.0
            minus_dm = down if down > up and down > 0 else 0.0
        alpha = 1.0 / period
        def smooth(previous, value):
            return value if previous is None else (1 - alpha) * previous + alpha * value
        tr_s, plus_s, minus_s = (smooth(tr_s, true_range), smooth(plus_s, plus_dm),
                                 smooth(minus_s, minus_dm))
        plus = 100 * plus_s / tr_s if tr_s > 0 else 0.0
        minus = 100 * minus_s / tr_s if tr_s > 0 else 0.0
        dx = 100 * abs(plus - minus) / (plus + minus) if plus + minus > 0 else 0.0
        adx = smooth(adx, dx)
        result.append(adx)
        previous_high, previous_low, previous_close = high, low, close
    return np.asarray(result), (round(adx, 1), round(plus, 1), round(minus, 1))


class AdxDivisionTests(unittest.TestCase):
    def check_case(self, data, period=14):
        expected_series, expected_last = scalar_reference(data, period)
        with warnings.catch_warnings(), np.errstate(divide="warn", invalid="warn"):
            warnings.simplefilter("error", RuntimeWarning)
            actual_last = dashboard._calc_adx(data, period)
            actual_series = chart_adx_function()(data, period)
        self.assertEqual(actual_last, expected_last)
        self.assertEqual(actual_series.shape, (len(data),))
        pd.testing.assert_index_equal(actual_series.index, data.index)
        np.testing.assert_allclose(actual_series.to_numpy(), expected_series, rtol=1e-13, atol=1e-13)
        self.assertTrue(np.isfinite(actual_series.to_numpy()).all())
        return actual_series, actual_last

    def test_flat_zero_true_range_returns_zero_without_division_warning(self):
        series, last = self.check_case(frame([100] * 80))
        np.testing.assert_array_equal(series.to_numpy(), np.zeros(80))
        self.assertEqual(last, (0.0, 0.0, 0.0))

    def test_flat_direction_with_nonzero_true_range_returns_zero(self):
        series, last = self.check_case(frame([100] * 80, width=1))
        np.testing.assert_array_equal(series.to_numpy(), np.zeros(80))
        self.assertEqual(last, (0.0, 0.0, 0.0))

    def test_flat_prefix_then_trend_keeps_the_full_series_and_scalar_result(self):
        for direction in (-1, 1):
            with self.subTest(direction=direction):
                prices = [100] * 30 + [100 + direction * i * .2 for i in range(1, 51)]
                series, last = self.check_case(frame(prices))
                np.testing.assert_array_equal(series.iloc[:30].to_numpy(), np.zeros(30))
                self.assertGreater(last[0], 0)

    def test_ordinary_mixed_movement_matches_independent_recurrence(self):
        prices = 100 + np.cumsum(np.sin(np.arange(100) / 3) * .7 + .08)
        for period in (1, 7, 14, 20):
            with self.subTest(period=period):
                self.check_case(frame(prices, width=.4), period)


if __name__ == "__main__":
    unittest.main()
