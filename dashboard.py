"""
FastAPI dashboard for the Trading Bot.
Run: uvicorn dashboard:app --reload --port 8000
"""

import os
import sys
import json
import time
import asyncio
import threading
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response
import hashlib
from starlette.middleware.gzip import GZipMiddleware
from collections import OrderedDict
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grok_quantum_bot import TradingBot

app = FastAPI(title="Trading Bot Dashboard")
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.middleware("http")
async def _security_headers(request, call_next):
    """The app must not be framed by other sites; nothing here needs to be."""
    resp = await call_next(request)
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return resp
bot = TradingBot()

# In-memory store
history: deque = deque(maxlen=50)
cache:   dict[str, dict] = {}
_quote_cache: dict[str, dict] = {}   # ticker → last quote (see /api/quotes)
QUOTE_TTL_S = 5.0                    # batch-quote cache lifetime
MOBILE_HTML_FILE = "protrader_mobile.html"
alerts:  dict[str, dict] = {}   # id → alert dict
fired_alerts: list[dict]  = []  # triggered alerts log (newest first, max 50)


class AlertCreate(BaseModel):
    ticker:    str
    condition: str   # "price_above" | "price_below" | "rsi_above" | "rsi_below" | "signal_is"
    value:     float | None = None   # price / RSI threshold
    signal_val: str | None = None    # for condition == "signal_is"
    note:      str = ""

POPULAR_TICKERS  = ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "AAPL", "TSLA", "NVDA", "SPY", "NAS100", "XAU"]
WATCHLIST_DEFAULT = ["BTC-USD", "ETH-USD", "SOL-USD", "AAPL", "NVDA", "SPY", "NAS100", "XAU"]

# Alias map: user-facing label → Yahoo Finance symbol
TICKER_MAP: dict[str, str] = {
    "NAS100":  "^NDX",
    "NASDAQ":  "^NDX",
    "XAU":     "GC=F",
    "XAUUSD":  "GC=F",
    "GOLD":    "GC=F",
    # ── Forex majors (used by the mobile terminal) ──
    "EURUSD":  "EURUSD=X",
    "GBPUSD":  "GBPUSD=X",
    "USDJPY":  "USDJPY=X",
    "GBPJPY":  "GBPJPY=X",
    "EURGBP":  "EURGBP=X",
    "USDCAD":  "USDCAD=X",
    "AUDUSD":  "AUDUSD=X",
    # ── Metals / indices / crypto aliases ──
    "XAG":     "SI=F",
    "XAGUSD":  "SI=F",
    "SILVER":  "SI=F",
    "SPX500":  "^GSPC",
    "US30":    "^DJI",
    "BTCUSD":  "BTC-USD",
    "ETHUSD":  "ETH-USD",
}

# Fetch window per chart interval. yfinance caps intraday history:
# 1m ≤ 7d, 5m/15m ≤ 60d. 4h is synthesised by resampling 1h bars.
PERIOD_MAP: dict[str, str] = {
    "1m":  "7d",
    "5m":  "30d",
    "15m": "30d",   # 5d gave index charts ~80 bars; indices trade 6.5h/day
    "1h":  "60d",
    "4h":  "180d",
    "1d":  "2y",
}


# Deep-history windows for scrolling back (backtesting). Yahoo caps intraday
# history hard: 1m is ~30 days total and 7 per request, 5m/15m/30m are 60 days,
# 1h is 730 days, daily is effectively unlimited.
MAX_PERIOD_MAP: dict[str, str] = {
    "1m":  "7d",
    "5m":  "60d",
    "15m": "60d",
    "1h":  "730d",
    "4h":  "730d",     # resampled from 1h
    "1d":  "10y",
}

_hist_cache: "OrderedDict[tuple, tuple]" = OrderedDict()   # (symbol, interval) -> (fetched_at, DataFrame)
_hist_lock = threading.Lock()
HISTORY_TTL_S = 180.0
HISTORY_CACHE_MAX = 40   # ~3 MB each for a deep 1h frame; bounded so strangers cannot fill RAM


def _load_history(sym: str, interval: str) -> pd.DataFrame:
    """
    Full available history for an instrument, enriched with indicators and
    cached — paging back through a chart must not re-download 60 days of bars
    on every scroll.
    """
    key = (sym, interval)
    with _hist_lock:
        hit = _hist_cache.get(key)
        if hit and time.time() - hit[0] < HISTORY_TTL_S:
            _hist_cache.move_to_end(key)
            return hit[1]

    period = MAX_PERIOD_MAP.get(interval, "60d")
    full = bot.fetch_data(sym, period=period, interval=interval)
    full = bot.calculate_indicators(full)
    full["EMA_200"] = full["Close"].ewm(span=200, adjust=False).mean()
    full["VWAP"] = _vwap_series(full)
    with _hist_lock:
        _hist_cache[key] = (time.time(), full)
        _hist_cache.move_to_end(key)
        while len(_hist_cache) > HISTORY_CACHE_MAX:
            _hist_cache.popitem(last=False)
    return full


def _cut_before(full: pd.DataFrame, before_epoch: int) -> pd.DataFrame:
    """Bars strictly older than an epoch, tz-aware or naive index."""
    cutoff = pd.Timestamp(before_epoch, unit="s", tz="UTC")
    if getattr(full.index, "tz", None) is None:
        cutoff = cutoff.tz_localize(None)
    else:
        cutoff = cutoff.tz_convert(full.index.tz)
    return full[full.index < cutoff]


def _vwap_series(df: pd.DataFrame) -> pd.Series:
    """
    Cumulative VWAP. Falls back to the cumulative mean of the typical price
    when volume is missing or all-zero (Yahoo reports zero volume for spot
    forex and metals), which would otherwise divide by zero and leak NaN
    into the JSON response.
    """
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    if "Volume" not in df.columns:
        return typical.expanding().mean()
    vol = df["Volume"].fillna(0)
    cum_vol = vol.cumsum()
    if float(cum_vol.iloc[-1]) <= 0:
        return typical.expanding().mean()
    vwap = (typical * vol).cumsum() / cum_vol.replace(0, float("nan"))
    return vwap.fillna(typical.expanding().mean())

# Deriv.com synthetic volatility indices — not on Yahoo Finance
DERIV_SYNTHETICS: set[str] = {
    "VOL251S", "VOL501S", "VOL751S", "VOL901S", "VOL1001S",
    "VOL10S",  "VOL25S",  "VOL50S",  "VOL75S",  "VOL100S",
    "BOOM500", "BOOM1000","CRASH500","CRASH1000",
}


def _resolve_ticker(ticker: str) -> str:
    """Normalise user input to a Yahoo Finance symbol."""
    t = ticker.upper().strip()
    return TICKER_MAP.get(t, t)


def _is_deriv_synthetic(ticker: str) -> bool:
    return ticker.upper().strip() in DERIV_SYNTHETICS


_executor = ThreadPoolExecutor(max_workers=10)
_yf_lock  = threading.Lock()   # yfinance download is not thread-safe


def _quick_snapshot(ticker: str) -> dict:
    """Lightweight per-ticker snapshot for the watchlist strip."""
    label = ticker.upper().strip()
    if _is_deriv_synthetic(label):
        return {"ticker": label, "price": None, "change": None,
                "signal": "N/A", "ok": False,
                "error": "Deriv synthetic — not on Yahoo Finance"}
    sym = _resolve_ticker(label)
    try:
        with _yf_lock:
            df = bot.fetch_data(sym, period="30d", interval="1h")
        df = bot.calculate_indicators(df)
        latest = df.iloc[-1]
        price    = float(latest["Close"])
        momentum = bot.momentum_signal(df)
        signal   = bot.generate_signal(latest, momentum)
        change   = None
        if len(df) >= 25:
            prev   = float(df["Close"].iloc[-25])
            change = round((price - prev) / prev * 100, 2)
        return {"ticker": label, "price": price, "change": change,
                "signal": signal, "ok": True}
    except Exception as e:
        return {"ticker": label, "price": None, "change": None,
                "signal": "—", "ok": False, "error": str(e)}


# ── API ────────────────────────────────────────────────────────────────────────

def score_directional(latest, signal: str, adx: float = 0.0) -> tuple[int, str]:
    """
    Confidence score (0-100) that reflects the STRENGTH of the current signal
    direction, not just bullish conditions.
    ADX bonus: trending market (ADX≥25) boosts directional signals by up to +10.
    Returns (score, strength_label).
    """
    score = 0
    if "BUY" in signal:
        if latest["Close"] > latest["SMA_20"] > latest["SMA_50"]: score += 35
        if   latest["RSI"] < 30: score += 25
        elif latest["RSI"] < 50: score += 10
        if latest["MACD"] > latest["Signal_Line"]:                 score += 25
        if latest["Close"] < latest["BB_Lower"]:                   score += 15
        # ADX trend bonus: strong trend amplifies the signal
        if   adx >= 40: score += 10
        elif adx >= 25: score += 5
    elif "SELL" in signal:
        if latest["Close"] < latest["SMA_20"] < latest["SMA_50"]: score += 35
        if   latest["RSI"] > 70: score += 25
        elif latest["RSI"] > 50: score += 10
        if latest["MACD"] < latest["Signal_Line"]:                 score += 25
        if latest["Close"] > latest["BB_Upper"]:                   score += 15
        if   adx >= 40: score += 10
        elif adx >= 25: score += 5
    else:  # HOLD — score proximity to neutral
        rsi_dist = abs(float(latest["RSI"]) - 50)
        score = max(0, int(30 - rsi_dist))   # max 30 for pure HOLD

    score = min(score, 100)
    if   score >= 75: label = "Strong"
    elif score >= 50: label = "Moderate"
    elif score >= 25: label = "Weak"
    else:             label = "Neutral"
    return score, label


def _stoch_k(df, price: float) -> float:
    """Fast, version-safe 14-period Stochastic %K."""
    tail = df.tail(14)
    hh = float(tail["High"].max()) if "High" in tail.columns else price
    ll = float(tail["Low"].min())  if "Low"  in tail.columns else price
    return round((price - ll) / (hh - ll) * 100, 1) if hh != ll else 50.0


def _calc_adx(df: pd.DataFrame, period: int = 14) -> tuple[float, float, float]:
    """
    Wilder's Average Directional Index.
    Returns (adx, plus_di, minus_di) for the latest bar.
    adx >= 25 → trending market; adx < 25 → ranging/weak trend.
    """
    if len(df) < period * 2 + 1:
        return 0.0, 0.0, 0.0
    try:
        high  = df["High"].values.astype(float)
        low   = df["Low"].values.astype(float)
        close = df["Close"].values.astype(float)

        # True Range
        prev_close = np.roll(close, 1); prev_close[0] = close[0]
        tr = np.maximum.reduce([high - low,
                                 np.abs(high - prev_close),
                                 np.abs(low  - prev_close)])

        # Directional Movement
        up   = np.diff(high, prepend=high[0])
        down = -np.diff(low,  prepend=low[0])
        plus_dm  = np.where((up > down) & (up > 0),   up,   0.0)
        minus_dm = np.where((down > up) & (down > 0), down, 0.0)

        # Wilder EMA (alpha = 1/period)
        alpha = 1.0 / period
        def wilder(arr):
            s = pd.Series(arr)
            return s.ewm(alpha=alpha, adjust=False).mean().values

        tr_s  = wilder(tr)
        pdi_s = wilder(plus_dm)
        mdi_s = wilder(minus_dm)

        plus_di  = np.where(tr_s > 0, 100 * pdi_s / tr_s, 0.0)
        minus_di = np.where(tr_s > 0, 100 * mdi_s / tr_s, 0.0)

        denom = plus_di + minus_di
        dx = np.where(denom > 0, 100 * np.abs(plus_di - minus_di) / denom, 0.0)
        adx = wilder(dx)

        return (
            round(float(adx[-1]),     1),
            round(float(plus_di[-1]), 1),
            round(float(minus_di[-1]),1),
        )
    except Exception:
        return 0.0, 0.0, 0.0


def _detect_divergence(df: pd.DataFrame) -> Optional[str]:
    """
    Detect classic RSI divergence over the last 30 bars.
    Bearish: price makes a higher high while RSI makes a lower high → reversal warning.
    Bullish: price makes a lower low  while RSI makes a higher low → reversal warning.
    Returns "BEARISH_DIV", "BULLISH_DIV", or None.
    """
    if len(df) < 10 or "RSI" not in df.columns:
        return None
    try:
        prices = df["Close"].values.astype(float)
        rsi    = df["RSI"].values.astype(float)
        n      = len(prices)
        half   = n // 2

        rec_ph = float(prices[half:].max());  pri_ph = float(prices[:half].max())
        rec_rh = float(rsi[half:].max());     pri_rh = float(rsi[:half].max())
        rec_pl = float(prices[half:].min());  pri_pl = float(prices[:half].min())
        rec_rl = float(rsi[half:].min());     pri_rl = float(rsi[:half].min())

        # Bearish divergence: price higher high, RSI lower high (> 0.1% price diff, > 2pt RSI diff)
        if rec_ph > pri_ph * 1.001 and rec_rh < pri_rh - 2.0:
            return "BEARISH_DIV"
        # Bullish divergence: price lower low, RSI higher low
        if rec_pl < pri_pl * 0.999 and rec_rl > pri_rl + 2.0:
            return "BULLISH_DIV"
        return None
    except Exception:
        return None


@app.get("/api/analyze/{ticker}")
def analyze(ticker: str, interval: str = "1h") -> dict:
    """Run full analysis for a ticker and return signal + indicators."""
    label = ticker.upper().strip()
    if _is_deriv_synthetic(label):
        raise HTTPException(status_code=422,
            detail=f"{label} is a Deriv synthetic index and is not available on Yahoo Finance.")
    sym = _resolve_ticker(label)
    try:
        period = PERIOD_MAP.get(interval, "60d")
        df = bot.fetch_data(sym, period=period, interval=interval)
        df = bot.calculate_indicators(df)
        df["EMA_200"] = df["Close"].ewm(span=200, adjust=False).mean()
        latest = df.iloc[-1]

        price    = float(latest["Close"])
        momentum = bot.momentum_signal(df)
        signal   = bot.generate_signal(latest, momentum)
        adx_val, plus_di, minus_di = _calc_adx(df)
        regime   = "TRENDING" if adx_val >= 25 else "RANGING"
        confidence, strength = score_directional(latest, signal, adx=adx_val)
        stop_loss, take_profit = bot.calculate_stops(price, float(latest["ATR"]), signal)

        # VWAP (cumulative over the fetched period)
        _vwap_val = float(_vwap_series(df).iloc[-1])

        # Volume spike detection (current bar vs 20-bar average)
        vol_now   = float(df["Volume"].iloc[-1]) if "Volume" in df.columns else 0.0
        vol_avg20 = float(df["Volume"].tail(20).mean()) if "Volume" in df.columns else 1.0
        vol_ratio = round(vol_now / vol_avg20, 2) if vol_avg20 > 0 else 1.0
        vol_spike = bool(vol_ratio >= 1.5)

        # RSI divergence detection (last 30 bars)
        divergence = _detect_divergence(df.tail(30))

        # 24h price change (safe: only if we have enough rows)
        change_pct: Optional[float] = None
        if len(df) >= 25:
            prev = float(df["Close"].iloc[-25])
            change_pct = round((price - prev) / prev * 100, 2)

        result = {
            "ticker":      label,
            "signal":      signal,
            "price":       price,
            "confidence":  confidence,
            "strength":    strength,
            "stop_loss":   stop_loss,
            "take_profit": take_profit,
            "change_pct":  change_pct,
            "atr":         round(float(latest["ATR"]), 4),
            "timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M"),
            "indicators": {
                "rsi":         round(float(latest["RSI"]), 1),
                "macd":        round(float(latest["MACD"]), 4),
                "signal_line": round(float(latest["Signal_Line"]), 4),
                "sma_20":      round(float(latest["SMA_20"]), 2),
                "sma_50":      round(float(latest["SMA_50"]), 2),
                "bb_upper":    round(float(latest["BB_Upper"]), 2),
                "bb_lower":    round(float(latest["BB_Lower"]), 2),
                "atr":         round(float(latest["ATR"]), 2),
                "momentum":    round(float(latest["Momentum"]) * 100, 2),
                "stoch_k":     _stoch_k(df, price),
                "ema_200":     round(float(latest["EMA_200"]), 2),
                "vwap":        round(_vwap_val, 2),
                "adx":         adx_val,
                "plus_di":     plus_di,
                "minus_di":    minus_di,
                "regime":      regime,
                "vol_ratio":   vol_ratio,
                "vol_spike":   vol_spike,
                "divergence":  divergence,
            },
            # Which individual conditions fired — shown as checklist in UI
            "conditions": {
                "price_above_sma20":    bool(latest["Close"] > latest["SMA_20"]),
                "sma20_above_sma50":    bool(latest["SMA_20"] > latest["SMA_50"]),
                "rsi_oversold":         bool(float(latest["RSI"]) < 30),
                "rsi_below_50":         bool(float(latest["RSI"]) < 50),
                "rsi_overbought":       bool(float(latest["RSI"]) > 70),
                "rsi_above_50":         bool(float(latest["RSI"]) > 50),
                "macd_above_signal":    bool(latest["MACD"] > latest["Signal_Line"]),
                "price_below_bb_lower": bool(latest["Close"] < latest["BB_Lower"]),
                "price_above_bb_upper": bool(latest["Close"] > latest["BB_Upper"]),
                "momentum_positive":    bool(float(latest["Momentum"]) > 0.02),
                "momentum_negative":    bool(float(latest["Momentum"]) < -0.02),
                "price_above_ema200":   bool(latest["Close"] > latest["EMA_200"]),
                "adx_trending":         bool(adx_val >= 25),
                "adx_strong":           bool(adx_val >= 40),
                "volume_spike":         vol_spike,
                "bullish_divergence":   divergence == "BULLISH_DIV",
                "bearish_divergence":   divergence == "BEARISH_DIV",
            },
        }

        # Check and fire any matching alerts
        triggered = _check_alerts(
            label, price,
            round(float(latest["RSI"]), 1),
            signal,
        )
        result["triggered_alerts"] = triggered

        cache[label] = result
        history.appendleft({k: v for k, v in result.items() if k != "indicators"})
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chart/{ticker}")
def chart_data(ticker: str,
               candles: int = Query(120, ge=1, le=5000),
               interval: str = Query("1h", pattern="^(1m|5m|15m|1h|4h|1d)$"),
               before: int = Query(0, ge=0)) -> dict:
    """
    OHLCV + indicator series for charting.

    `before` (unix seconds) returns the window of bars ending just before that
    time, which is how the chart pages backwards through history. Omitted, it
    returns the latest bars as before — so first paint stays fast and only
    scrolling back pays for the deep fetch.
    """
    label = ticker.upper().strip()
    if _is_deriv_synthetic(label):
        raise HTTPException(status_code=422,
            detail=f"{label} is a Deriv synthetic index and is not available on Yahoo Finance.")
    sym = _resolve_ticker(label)
    try:
        if before:
            full = _cut_before(_load_history(sym, interval), before)
            if full.empty:
                # Nothing older exists — tell the client to stop asking.
                return {"labels": [], "time": [], "open": [], "high": [], "low": [],
                        "price": [], "volume": [], "has_more": False}
        else:
            period = PERIOD_MAP.get(interval, "60d")
            # Fetch once — compute EMA 200 on full history, then tail for display
            full = bot.fetch_data(sym, period=period, interval=interval)
            full = bot.calculate_indicators(full)
            full["EMA_200"] = full["Close"].ewm(span=200, adjust=False).mean()
            # VWAP (cumulative over full fetch)
            full["VWAP"] = _vwap_series(full)

        df  = full.tail(candles).copy()
        idx = df.index
        labels = [str(i.strftime("%m/%d %H:%M")) if hasattr(i, "strftime") else str(i) for i in idx]
        # Epoch seconds per bar — mobile terminal plots on a real time axis
        epochs = [int(pd.Timestamp(i).timestamp()) if hasattr(i, "timestamp") else 0 for i in idx]
        def col(c): return [round(float(v), 4) for v in df[c]]

        # Stochastic %K / %D (14-period) — use full history for accuracy
        low14   = full["Low"].rolling(14).min().tail(candles)
        high14  = full["High"].rolling(14).max().tail(candles)
        denom   = (high14 - low14).replace(0, float("nan"))
        stoch_k = ((df["Close"].values - low14.values) / denom.values * 100).round(2)
        stoch_d_series = (
            full["Close"].rolling(14).apply(
                lambda x: (x[-1] - x.min()) / (x.max() - x.min()) * 100
                          if x.max() != x.min() else 50, raw=True
            ).rolling(3).mean().tail(candles)
        )

        # ADX series (compute on full history for accuracy, tail for display)
        _adx_full, _, _ = _calc_adx(full)   # scalar for latest bar
        # Compute per-bar ADX using rolling windows for the chart series
        def _adx_series(src: pd.DataFrame, period: int = 14):
            high  = src["High"].values.astype(float)
            low   = src["Low"].values.astype(float)
            close = src["Close"].values.astype(float)
            prev_c = np.roll(close, 1); prev_c[0] = close[0]
            tr = np.maximum.reduce([high - low, np.abs(high - prev_c), np.abs(low - prev_c)])
            up   = np.diff(high, prepend=high[0])
            down = -np.diff(low, prepend=low[0])
            pdm  = np.where((up > down) & (up > 0), up, 0.0)
            mdm  = np.where((down > up) & (down > 0), down, 0.0)
            alpha = 1.0 / period
            def ew(a): return pd.Series(a).ewm(alpha=alpha, adjust=False).mean().values
            tr_s = ew(tr); pdi = np.where(tr_s > 0, 100*ew(pdm)/tr_s, 0.0)
            mdi  = np.where(tr_s > 0, 100*ew(mdm)/tr_s, 0.0)
            denom = pdi + mdi
            dx = np.where(denom > 0, 100*np.abs(pdi - mdi)/denom, 0.0)
            return pd.Series(ew(dx), index=src.index)

        adx_full_series = _adx_series(full)
        adx_display = adx_full_series.tail(candles).round(1)

        # MACD histogram  (MACD − Signal Line)
        macd_hist = (df["MACD"] - df["Signal_Line"]).round(4)

        # ── Volume relative strength (vs 20-bar rolling average) ───────
        vol_ma20 = full["Volume"].rolling(20).mean()
        vol_ratio_full = (full["Volume"] / vol_ma20.replace(0, float("nan"))).round(2)
        vol_ratio_display = vol_ratio_full.tail(candles)
        vol_spike_now_flag = bool(float(vol_ratio_display.iloc[-1]) >= 1.5) \
            if not pd.isna(vol_ratio_display.iloc[-1]) else False

        # ── Bollinger Band Width & Squeeze ──────────────────────────────
        # BB Width = (Upper - Lower) / Mid  — normalised bandwidth
        full["BB_Width"] = (full["BB_Upper"] - full["BB_Lower"]) / full["BB_Mid"]
        bb_width_display = full["BB_Width"].tail(candles).round(4)
        # Squeeze = current BB Width is at a 20-bar low (lowest bandwidth recently)
        bb_width_min20 = full["BB_Width"].rolling(20).min().tail(candles)
        squeeze_flags  = (full["BB_Width"].tail(candles) <= bb_width_min20 * 1.02).tolist()
        # Latest squeeze state for API consumers
        bb_squeeze_now = bool(squeeze_flags[-1]) if squeeze_flags else False
        bb_width_now   = round(float(bb_width_display.iloc[-1]), 4)

        def safe_list(arr):
            return [round(float(v), 4) if v == v and v is not None else None for v in arr]

        return {
            "labels":        labels,
            "time":          epochs,
            "open":          col("Open"),
            "high":          col("High"),
            "low":           col("Low"),
            "price":         col("Close"),
            "sma20":         col("SMA_20"),
            "sma50":         col("SMA_50"),
            "bb_upper":      col("BB_Upper"),
            "bb_lower":      col("BB_Lower"),
            "ema200":        [round(float(v), 2) if v == v else None for v in df["EMA_200"]],
            "rsi":           col("RSI"),
            "macd":          col("MACD"),
            "signal_line":   col("Signal_Line"),
            "macd_hist":     [round(float(v), 4) for v in macd_hist],
            "stoch_k":       safe_list(stoch_k),
            "stoch_d":       safe_list(stoch_d_series),
            "volume":        [float(v) if v == v else 0.0 for v in df["Volume"]] if "Volume" in df.columns else [],
            "vwap":          [round(float(v), 2) if v == v else None for v in df["VWAP"]],
            "adx":           safe_list(adx_display),
            "bb_width":      safe_list(bb_width_display),
            "bb_squeeze":     [bool(v) for v in squeeze_flags],
            "bb_squeeze_now": bb_squeeze_now,
            "bb_width_now":   bb_width_now,
            "vol_ratio":      safe_list(vol_ratio_display),
            "vol_spike_now":  vol_spike_now_flag,
            # more history available before the first returned bar?
            "has_more":       bool(len(full) > len(df)),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sr/{ticker}")
def support_resistance(ticker: str, interval: str = "1h", candles: int = 120) -> dict:
    """
    Auto-detect key Support/Resistance levels from recent swing highs and lows.
    Returns up to 5 resistance levels and 5 support levels, sorted by proximity
    to the current price, plus the nearest support and resistance.
    """
    label = ticker.upper().strip()
    if _is_deriv_synthetic(label):
        raise HTTPException(status_code=422,
            detail=f"{label} is a Deriv synthetic index and is not available on Yahoo Finance.")
    sym = _resolve_ticker(label)
    try:
        period = PERIOD_MAP.get(interval, "60d")
        df = bot.fetch_data(sym, period=period, interval=interval)
        df = bot.calculate_indicators(df)
        df = df.tail(candles).copy()

        price = float(df["Close"].iloc[-1])

        # ── Swing detection: a bar is a swing high if it's the highest
        #    in a window of `w` bars on each side; swing low is the lowest.
        w = 5
        highs_list: list[float] = []
        lows_list:  list[float] = []

        closes = df["Close"].values.tolist()
        high_col = df["High"].values.tolist()  if "High" in df.columns else closes
        low_col  = df["Low"].values.tolist()   if "Low"  in df.columns else closes

        n = len(df)
        for i in range(w, n - w):
            window_h = high_col[i - w: i + w + 1]
            window_l = low_col [i - w: i + w + 1]
            if high_col[i] == max(window_h):
                highs_list.append(round(float(high_col[i]), 4))
            if low_col[i]  == min(window_l):
                lows_list.append(round(float(low_col[i]), 4))

        # ── Cluster nearby levels (within 0.5 % of each other) to avoid
        #    duplicates that differ by a few ticks.
        def cluster(vals: list[float], pct_tol: float = 0.005) -> list[float]:
            if not vals:
                return []
            vals = sorted(set(vals))
            clusters: list[list[float]] = [[vals[0]]]
            for v in vals[1:]:
                if abs(v - clusters[-1][-1]) / clusters[-1][-1] <= pct_tol:
                    clusters[-1].append(v)
                else:
                    clusters.append([v])
            return [round(sum(c) / len(c), 4) for c in clusters]

        resistances = sorted([v for v in cluster(highs_list) if v > price])
        supports    = sorted([v for v in cluster(lows_list)  if v < price], reverse=True)

        # Keep top 5 closest levels on each side
        resistances = resistances[:5]
        supports    = supports[:5]

        nearest_res = resistances[0] if resistances else None
        nearest_sup = supports[0]    if supports    else None

        def dist_pct(level: float) -> float:
            return round((level - price) / price * 100, 2)

        return {
            "ticker":       label,
            "price":        price,
            "resistances":  [{"level": v, "dist_pct": dist_pct(v)} for v in resistances],
            "supports":     [{"level": v, "dist_pct": dist_pct(v)} for v in supports],
            "nearest_resistance": nearest_res,
            "nearest_support":    nearest_sup,
            "nearest_res_pct":    dist_pct(nearest_res) if nearest_res else None,
            "nearest_sup_pct":    dist_pct(nearest_sup) if nearest_sup else None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/mtf/{ticker}")
def multi_timeframe(ticker: str) -> dict:
    """Run analysis across all 4 timeframes in parallel for MTF confluence."""
    label = ticker.upper().strip()
    if _is_deriv_synthetic(label):
        raise HTTPException(status_code=422,
            detail=f"{label} is a Deriv synthetic index and is not available on Yahoo Finance.")
    sym = _resolve_ticker(label)
    timeframes   = ["15m", "1h", "4h", "1d"]
    _tf_labels   = {"15m": "15 Min", "1h": "1 Hour", "4h": "4 Hour", "1d": "Daily"}

    def _analyze_tf(interval: str) -> dict:
        try:
            period = PERIOD_MAP[interval]
            with _yf_lock:
                df = bot.fetch_data(sym, period=period, interval=interval)
            df = bot.calculate_indicators(df)
            latest   = df.iloc[-1]
            price    = float(latest["Close"])
            momentum = bot.momentum_signal(df)
            signal   = bot.generate_signal(latest, momentum)
            adx_v, pdi, mdi = _calc_adx(df)
            confidence, strength = score_directional(latest, signal, adx=adx_v)
            return {
                "interval":    interval,
                "label":       _tf_labels[interval],
                "signal":      signal,
                "confidence":  confidence,
                "strength":    strength,
                "rsi":         round(float(latest["RSI"]), 1),
                "macd_bull":   bool(latest["MACD"] > latest["Signal_Line"]),
                "above_sma20": bool(latest["Close"] > latest["SMA_20"]),
                "above_sma50": bool(latest["SMA_20"] > latest["SMA_50"]),
                "adx":         adx_v,
                "plus_di":     pdi,
                "minus_di":    mdi,
                "regime":      "TRENDING" if adx_v >= 25 else "RANGING",
                "ok": True,
            }
        except Exception as e:
            return {"interval": interval, "label": _tf_labels[interval],
                    "signal": "ERROR", "confidence": 0, "ok": False, "error": str(e)}

    results = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(_analyze_tf, tf): tf for tf in timeframes}
        for fut in as_completed(futs, timeout=120):
            r = fut.result()
            results[r["interval"]] = r

    ordered    = [results.get(tf, {"interval": tf, "label": _tf_labels[tf], "signal": "—", "ok": False})
                  for tf in timeframes]
    buy_count  = sum(1 for r in ordered if "BUY"  in r.get("signal", ""))
    sell_count = sum(1 for r in ordered if "SELL" in r.get("signal", ""))
    hold_count = sum(1 for r in ordered if r.get("signal") == "HOLD")

    if buy_count > sell_count and buy_count >= hold_count:
        direction, aligned = "BULLISH", buy_count
    elif sell_count > buy_count and sell_count >= hold_count:
        direction, aligned = "BEARISH", sell_count
    else:
        direction, aligned = "NEUTRAL", hold_count

    return {
        "ticker":     label,
        "timeframes": ordered,
        "confluence": {
            "direction":   direction,
            "aligned":     aligned,
            "total":       len(timeframes),
            "buy_count":   buy_count,
            "sell_count":  sell_count,
            "hold_count":  hold_count,
        },
    }


@app.post("/api/alerts")
def create_alert(body: AlertCreate) -> dict:
    aid = str(uuid.uuid4())[:8]
    a = {
        "id":         aid,
        "ticker":     body.ticker.upper(),
        "condition":  body.condition,
        "value":      body.value,
        "signal_val": body.signal_val,
        "note":       body.note,
        "active":     True,
        "created_at": datetime.now().strftime("%H:%M:%S"),
    }
    alerts[aid] = a
    return a


@app.get("/api/alerts")
def list_alerts() -> dict:
    return {"active": [a for a in alerts.values() if a["active"]],
            "fired":  fired_alerts[:50]}


@app.delete("/api/alerts/{aid}")
def delete_alert(aid: str) -> dict:
    if aid not in alerts:
        raise HTTPException(status_code=404, detail="Alert not found")
    alerts.pop(aid)
    return {"deleted": aid}


def _check_alerts(ticker: str, price: float, rsi: float, signal: str) -> list[dict]:
    """Check active alerts for the given ticker; fire and return any that triggered."""
    triggered = []
    for aid, a in list(alerts.items()):
        if not a["active"] or a["ticker"] != ticker:
            continue
        cond = a["condition"]
        val  = a["value"]
        fired = False
        if   cond == "price_above" and val is not None and price >= val:
            fired = True
        elif cond == "price_below" and val is not None and price <= val:
            fired = True
        elif cond == "rsi_above"   and val is not None and rsi   >= val:
            fired = True
        elif cond == "rsi_below"   and val is not None and rsi   <= val:
            fired = True
        elif cond == "signal_is"   and a.get("signal_val") and signal == a["signal_val"]:
            fired = True

        if fired:
            a["active"]    = False
            a["fired_at"]  = datetime.now().strftime("%H:%M:%S")
            a["fired_price"] = price
            record = {**a, "rsi": rsi, "signal": signal}
            fired_alerts.insert(0, record)
            if len(fired_alerts) > 50:
                fired_alerts.pop()
            triggered.append(record)
    return triggered


@app.get("/api/backtest/{ticker}")
def backtest(ticker: str, interval: str = "1h", period: str = "90d") -> dict:
    """
    Walk-forward backtest of the bot's signal strategy over historical data.
    Simulates BUY/SELL entries with 2×ATR stop-loss and 3×ATR take-profit,
    one position at a time, and returns performance statistics + equity curve.
    """
    label = ticker.upper().strip()
    if _is_deriv_synthetic(label):
        raise HTTPException(status_code=422,
            detail=f"{label} is a Deriv synthetic index and is not available on Yahoo Finance.")
    sym = _resolve_ticker(label)
    _period_map = {"15m": "5d", "1h": "90d", "4h": "180d", "1d": "5y"}
    try:
        fetch_period = _period_map.get(interval, period)
        df = bot.fetch_data(sym, period=fetch_period, interval=interval)
        df = bot.calculate_indicators(df)
        df["EMA_200"] = df["Close"].ewm(span=200, adjust=False).mean()
        df = df.reset_index(drop=False)   # keep datetime as column

        trades      = []
        equity      = [1.0]          # normalised equity curve (starts at 1)
        equity_dates= []
        in_trade    = False
        entry_price = entry_signal = stop = target = None
        entry_idx   = 0

        for i in range(len(df)):
            row = df.iloc[i]
            close = float(row["Close"])
            ts    = str(row.iloc[0]) if hasattr(row.iloc[0], "__str__") else str(i)

            if in_trade:
                # Check stop / target hit (using close-price approximation)
                hit_stop   = (entry_signal == "STRONG BUY"  and close <= stop)  or \
                             (entry_signal == "STRONG SELL" and close >= stop)
                hit_target = (entry_signal == "STRONG BUY"  and close >= target) or \
                             (entry_signal == "STRONG SELL" and close <= target)

                if hit_stop or hit_target:
                    exit_price = target if hit_target else stop
                    if entry_signal == "STRONG BUY":
                        pnl_pct = (exit_price - entry_price) / entry_price
                    else:
                        pnl_pct = (entry_price - exit_price) / entry_price

                    last_eq = equity[-1]
                    new_eq  = last_eq * (1 + pnl_pct)
                    equity.append(round(new_eq, 6))
                    equity_dates.append(ts)

                    trades.append({
                        "entry_idx":    entry_idx,
                        "exit_idx":     i,
                        "signal":       entry_signal,
                        "entry":        round(entry_price, 4),
                        "exit":         round(exit_price,  4),
                        "pnl_pct":      round(pnl_pct * 100, 3),
                        "outcome":      "win" if pnl_pct > 0 else "loss",
                        "exit_reason":  "target" if hit_target else "stop",
                        "date":         ts,
                    })
                    in_trade = False

            else:
                # Look for new signal
                momentum = bot.momentum_signal(df.iloc[:i+1])
                sig      = bot.generate_signal(row, momentum)

                if sig in ("STRONG BUY", "STRONG SELL"):
                    atr   = float(row["ATR"])
                    sl, tp = bot.calculate_stops(close, atr, sig)
                    if sl is not None and tp is not None:
                        in_trade    = True
                        entry_price = close
                        entry_signal= sig
                        stop        = sl
                        target      = tp
                        entry_idx   = i
                        # Note: equity_dates tracks exit timestamps only, matching equity[] length

        # ── Stats ──────────────────────────────────────────────────────
        n       = len(trades)
        wins    = [t for t in trades if t["outcome"] == "win"]
        losses  = [t for t in trades if t["outcome"] == "loss"]
        win_rate = round(len(wins) / n * 100, 1) if n else 0.0

        avg_win  = round(sum(t["pnl_pct"] for t in wins)   / len(wins),   2) if wins   else 0.0
        avg_loss = round(sum(t["pnl_pct"] for t in losses) / len(losses), 2) if losses else 0.0

        gross_profit = sum(t["pnl_pct"] for t in wins)
        gross_loss   = abs(sum(t["pnl_pct"] for t in losses))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss else None

        # Max drawdown on equity curve
        peak = 1.0
        max_dd = 0.0
        for e in equity:
            if e > peak:
                peak = e
            dd = (peak - e) / peak
            if dd > max_dd:
                max_dd = dd
        max_dd = round(max_dd * 100, 2)

        final_return = round((equity[-1] - 1.0) * 100, 2) if equity else 0.0

        # Thin equity curve for chart (max 300 points)
        # equity has N+1 elements (initial 1.0 + N exits); equity_dates has N elements (exits only)
        step     = max(1, len(equity) // 300)
        thin_eq  = equity[::step]
        # Align dates to equity exits (equity[1:] corresponds to equity_dates)
        thin_dates = equity_dates[::step] if equity_dates else []

        return {
            "ticker":         label,
            "interval":       interval,
            "period":         fetch_period,
            "total_trades":   n,
            "wins":           len(wins),
            "losses":         len(losses),
            "win_rate":       win_rate,
            "avg_win_pct":    avg_win,
            "avg_loss_pct":   avg_loss,
            "profit_factor":  profit_factor,
            "max_drawdown_pct": max_dd,
            "total_return_pct": final_return,
            "equity_curve":   thin_eq,
            "equity_dates":   [str(d) for d in thin_dates],
            "trade_log":      trades[-20:],   # last 20 trades for table
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stream/{ticker}")
async def stream_ticker(ticker: str, interval_s: int = 15):
    interval_s = max(5, min(int(interval_s or 15), 120))   # the app asks for 10; never let a client spin the pool
    """
    Server-Sent Events: pushes latest price + day stats every interval_s seconds.
    Tries fast_info first; falls back to history() if the price looks wrong
    (e.g. outside 50%–200% of the day's high/low range — a known yfinance glitch).
    """
    label = ticker.upper().strip()
    if _is_deriv_synthetic(label):
        async def _deriv_error():
            yield f"data: {json.dumps({'error': f'{label} is a Deriv synthetic — not on Yahoo Finance', 'tick': 0})}\n\n"
        return StreamingResponse(_deriv_error(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    sym = _resolve_ticker(label)

    def _fetch_stream_price(sym: str) -> tuple:
        """Returns (price, prev, day_h, day_l, volume). Falls back to history if needed."""
        fi     = yf.Ticker(sym).fast_info
        price  = fi.last_price
        prev   = fi.previous_close
        day_h  = fi.day_high
        day_l  = fi.day_low
        volume = fi.last_volume

        if price is not None:
            price = float(price)
            # Sanity-check: last_price must sit within a reasonable band of the day range.
            # fast_info occasionally returns a stale/wrong value for crypto tickers.
            if day_h is not None and day_l is not None:
                lo_bound = float(day_l) * 0.5
                hi_bound = float(day_h) * 2.0
                if not (lo_bound <= price <= hi_bound):
                    price = None   # force fallback

        if price is None:
            # Fallback: download last few minutes of data for a reliable close
            hist = yf.Ticker(sym).history(period="1d", interval="5m")
            if hist.empty:
                raise ValueError(f"No price data available for {sym}")
            price  = float(hist["Close"].iloc[-1])
            prev   = float(hist["Close"].iloc[0])   # approximate open as prev
            day_h  = float(hist["High"].max())
            day_l  = float(hist["Low"].min())
            volume = int(hist["Volume"].sum())
            return price, prev, day_h, day_l, volume

        return (
            price,
            float(prev)   if prev   is not None else price,
            float(day_h)  if day_h  is not None else price,
            float(day_l)  if day_l  is not None else price,
            int(volume)   if volume is not None else None,
        )

    async def generate():
        tick = 0
        while True:
            try:
                loop = asyncio.get_event_loop()
                price, prev, day_h, day_l, volume = await loop.run_in_executor(
                    _executor, _fetch_stream_price, sym
                )

                change_pct  = round((price - prev) / prev * 100, 2) if prev else 0.0
                day_range   = round(day_h - day_l, 4)
                pos_in_range = round((price - day_l) / day_range * 100, 1) if day_range else 50.0

                payload = {
                    "ticker":       label,
                    "price":        round(price, 4),
                    "prev_close":   round(prev, 4),
                    "change_pct":   change_pct,
                    "day_high":     round(day_h, 4),
                    "day_low":      round(day_l, 4),
                    "pos_in_range": pos_in_range,
                    "volume":       int(volume) if volume else None,
                    "tick":         tick,
                    "ts":           datetime.now().strftime("%H:%M:%S"),
                }
                yield f"data: {json.dumps(payload)}\n\n"
                tick += 1
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e), 'tick': tick})}\n\n"
                tick += 1

            await asyncio.sleep(interval_s)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


@app.get("/api/watchlist")
def watchlist() -> list:
    """Return quick snapshots for all watchlist tickers in parallel."""
    futures = {_executor.submit(_quick_snapshot, t): t for t in WATCHLIST_DEFAULT}
    results = {}
    for fut in as_completed(futures, timeout=90):
        data = fut.result()
        results[data["ticker"]] = data
    # Return in original order
    return [results[t] for t in WATCHLIST_DEFAULT if t in results]


@app.get("/api/history")
def get_history() -> list:
    return list(history)


@app.get("/api/tickers")
def get_tickers() -> list:
    return POPULAR_TICKERS


@app.get("/api/quotes")
def quotes(tickers: str = "") -> list:
    """
    Lightweight batch quote endpoint for the mobile ticker strip.

    ?tickers=EURUSD,GBPUSD,BTCUSD — comma separated. Results are cached for
    QUOTE_TTL_S seconds so a 10-symbol strip polling every few seconds does
    not hammer Yahoo.
    """
    labels = [t.upper().strip() for t in tickers.split(",") if t.strip()]
    if not labels:
        labels = list(WATCHLIST_DEFAULT)

    now = time.time()

    def _one(label: str) -> dict:
        cached = _quote_cache.get(label)
        if cached and now - cached["_ts"] < QUOTE_TTL_S:
            return cached

        if _is_deriv_synthetic(label):
            row = {"ticker": label, "price": None, "change_pct": None, "ok": False,
                   "error": "Deriv synthetic — not on Yahoo Finance"}
        else:
            try:
                fi = yf.Ticker(_resolve_ticker(label)).fast_info
                price = fi.last_price
                prev = fi.previous_close
                if price is None:
                    raise ValueError("no price")
                price = float(price)
                change = round((price - float(prev)) / float(prev) * 100, 3) if prev else 0.0
                row = {"ticker": label, "price": round(price, 5),
                       "change_pct": change, "ok": True}
            except Exception as e:
                row = {"ticker": label, "price": None, "change_pct": None,
                       "ok": False, "error": str(e)}

        row["_ts"] = now
        _quote_cache[label] = row
        return row

    futures = {_executor.submit(_one, t): t for t in labels}
    results = {}
    for fut in as_completed(futures, timeout=30):
        row = fut.result()
        results[row["ticker"]] = row
    return [{k: v for k, v in results[t].items() if k != "_ts"}
            for t in labels if t in results]


_STATIC_TYPES = {
    ".png": "image/png", ".webmanifest": "application/manifest+json",
    ".js": "application/javascript", ".svg": "image/svg+xml", ".ico": "image/x-icon",
}


def _file_or_304(request: Request, path: str, media_type: str, cache_control: str) -> Response:
    """FileResponse sets ETag/Last-Modified but never answers a conditional
    request, so every reopen re-downloaded ~500 KB. Compare the client's
    validator ourselves and return 304 when nothing changed."""
    st = os.stat(path)
    etag = '"' + hashlib.md5(f"{st.st_mtime_ns}-{st.st_size}".encode()).hexdigest() + '"'
    inm = request.headers.get("if-none-match", "")
    if etag in [t.strip() for t in inm.split(",")]:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": cache_control})
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": cache_control, "ETag": etag})


@app.get("/static/{filename}")
def static_asset(filename: str, request: Request):
    """PWA assets: manifest, service worker, icons."""
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid asset name")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"{filename} not found")
    ext = os.path.splitext(filename)[1].lower()
    headers = {"Cache-Control": "public, max-age=86400"}
    if filename.endswith(".webmanifest"):
        headers = {"Cache-Control": "no-cache"}
    # The service worker itself must never be cached, or updates can't roll out.
    if filename == "sw.js":
        headers = {"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"}
    return _file_or_304(request, path, _STATIC_TYPES.get(ext, "application/octet-stream"), headers["Cache-Control"])


@app.get("/sw.js")
def service_worker():
    """
    Served from the root so its default scope covers /mobile and / — a worker
    under /static/ could only control /static/*.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "sw.js")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="sw.js not found")
    return FileResponse(path, media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.get("/lab", response_class=HTMLResponse)
def chart_lab() -> str:
    """Standalone Lightweight Charts reference page (chart_lab.html)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chart_lab.html")
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="chart_lab.html not found next to dashboard.py")


@app.get("/vendor/{filename}")
def vendor_asset(filename: str, request: Request):
    """
    Serve vendored third-party assets (TradingView Lightweight Charts).
    Kept local rather than on a CDN so the terminal still loads when the
    network or unpkg is down.
    """
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid asset name")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"{filename} not found")
    media = "application/javascript" if filename.endswith(".js") else "text/plain"
    # The HTML references this with ?v=<version>, so a long max-age is safe:
    # a new library version is a new URL.
    return _file_or_304(request, path, media, "public, max-age=604800, immutable")


@app.get("/mobile")
def mobile_terminal(request: Request):
    """
    Serve the PROTrader Nexus mobile terminal from the same origin as the API,
    so its fetch/EventSource calls to /api/* need no CORS handling.
    Read from disk per request so edits show up on refresh.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), MOBILE_HTML_FILE)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"{MOBILE_HTML_FILE} not found next to dashboard.py")
    # FileResponse emits ETag/Last-Modified, so a reopen is a 304 unless the
    # file changed; no-cache means "revalidate", not "don't cache".
    return _file_or_304(request, path, "text/html; charset=utf-8", "no-cache")


@app.get("/")
def home(request: Request):
    """PROTrader is the front door; the legacy desktop dashboard moved to /dashboard."""
    return mobile_terminal(request)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> str:
    return DASHBOARD_HTML


# ── HTML ───────────────────────────────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Trading Bot Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-chart-financial@0.2.1/dist/chartjs-chart-financial.min.js"></script>
<style>
  :root {
    --bg:        #1E1E2E;
    --surface:   #181825;
    --surface1:  #1E1E2E;
    --overlay:   #313244;
    --muted:     #6C7086;
    --subtle:    #9399B2;
    --text:      #CDD6F4;
    --subtext:   #BAC2DE;
    --mauve:     #CBA6F7;
    --blue:      #89B4FA;
    --teal:      #94E2D5;
    --green:     #A6E3A1;
    --yellow:    #F9E2AF;
    --peach:     #FAB387;
    --red:       #F38BA8;
    --sky:       #89DCEB;
    --radius:    12px;
    --radius-sm: 8px;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    min-height: 100vh;
    padding: 24px;
  }

  /* ── Header ── */
  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 28px;
    flex-wrap: wrap;
    gap: 12px;
  }
  .header-left { display: flex; align-items: center; gap: 12px; }
  .header-logo {
    width: 38px; height: 38px;
    background: linear-gradient(135deg, var(--mauve), var(--blue));
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-size: 20px;
  }
  .header-title { font-size: 1.3rem; font-weight: 700; color: var(--text); }
  .header-subtitle { font-size: 0.75rem; color: var(--muted); margin-top: 1px; }
  .header-right { display: flex; align-items: center; gap: 10px; }

  select {
    background: var(--surface);
    color: var(--text);
    border: 1px solid var(--overlay);
    border-radius: var(--radius-sm);
    padding: 8px 14px;
    font-size: 0.88rem;
    cursor: pointer;
    outline: none;
    transition: border-color .2s;
  }
  select:hover { border-color: var(--mauve); }

  .btn {
    background: var(--mauve);
    color: var(--bg);
    border: none;
    border-radius: var(--radius-sm);
    padding: 8px 16px;
    font-size: 0.88rem;
    font-weight: 600;
    cursor: pointer;
    display: flex; align-items: center; gap: 6px;
    transition: opacity .2s, transform .1s;
  }
  .btn:hover { opacity: .88; }
  .btn:active { transform: scale(0.97); }
  .btn:disabled { opacity: .45; cursor: not-allowed; }
  .btn-outline {
    background: transparent;
    color: var(--mauve);
    border: 1px solid var(--mauve);
  }

  /* ── Status bar ── */
  .status-bar {
    display: flex; align-items: center; gap: 8px;
    font-size: 0.75rem; color: var(--muted);
    margin-bottom: 20px;
  }
  .status-dot {
    width: 7px; height: 7px;
    border-radius: 50%;
    background: var(--green);
    animation: pulse 2s infinite;
  }
  .status-dot.loading { background: var(--yellow); animation: none; }
  .status-dot.error   { background: var(--red);    animation: none; }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50%       { opacity: .4; }
  }

  /* ── Grid ── */
  .grid-top {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-bottom: 16px;
  }
  .grid-bottom {
    display: grid;
    grid-template-columns: 1fr;
    gap: 16px;
  }
  @media (max-width: 700px) {
    .grid-top { grid-template-columns: 1fr; }
    body { padding: 14px; }
  }

  /* ── Cards ── */
  .card {
    background: var(--surface);
    border: 1px solid var(--overlay);
    border-radius: var(--radius);
    padding: 22px;
    position: relative;
    overflow: hidden;
  }
  .card-label {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: var(--muted);
    margin-bottom: 14px;
  }

  /* ── Price card ── */
  .price-card { border-left: 3px solid var(--mauve); }
  .price-value {
    font-size: 2.4rem;
    font-weight: 800;
    letter-spacing: -.02em;
    color: var(--text);
    line-height: 1;
    margin-bottom: 6px;
  }
  .price-change {
    font-size: 0.85rem;
    font-weight: 600;
    margin-bottom: 18px;
  }
  .price-change.up   { color: var(--green); }
  .price-change.down { color: var(--red); }
  .price-change.flat { color: var(--muted); }

  /* ── Signal badge ── */
  .signal-badge {
    display: inline-flex; align-items: center; gap: 7px;
    padding: 6px 14px;
    border-radius: 999px;
    font-size: 0.85rem;
    font-weight: 700;
    letter-spacing: .03em;
  }
  .signal-badge.buy  { background: rgba(166,227,161,.15); color: var(--green); border: 1px solid rgba(166,227,161,.35); }
  .signal-badge.sell { background: rgba(243,139,168,.15); color: var(--red);   border: 1px solid rgba(243,139,168,.35); }
  .signal-badge.hold { background: rgba(249,226,175,.15); color: var(--yellow);border: 1px solid rgba(249,226,175,.35); }

  .signal-dot { width: 8px; height: 8px; border-radius: 50%; }
  .buy  .signal-dot { background: var(--green); }
  .sell .signal-dot { background: var(--red); }
  .hold .signal-dot { background: var(--yellow); }

  /* ── Confidence card ── */
  .conf-value {
    font-size: 2rem;
    font-weight: 800;
    color: var(--text);
    line-height: 1;
    margin-bottom: 4px;
  }
  .conf-denom { font-size: 1rem; color: var(--muted); font-weight: 400; }
  .conf-bar-track {
    height: 6px;
    background: var(--overlay);
    border-radius: 999px;
    margin: 14px 0 18px;
    overflow: hidden;
  }
  .conf-bar-fill {
    height: 100%;
    border-radius: 999px;
    transition: width .6s ease;
    background: linear-gradient(90deg, var(--blue), var(--mauve));
  }

  /* ── Level cards ── */
  .levels-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    margin-top: 4px;
  }
  .level-item {
    background: var(--surface1);
    border: 1px solid var(--overlay);
    border-radius: var(--radius-sm);
    padding: 12px 14px;
  }
  .level-label { font-size: 0.68rem; text-transform: uppercase; letter-spacing: .07em; color: var(--muted); margin-bottom: 5px; }
  .level-value { font-size: 1.05rem; font-weight: 700; }
  .level-value.stop   { color: var(--red); }
  .level-value.target { color: var(--green); }
  .level-value.empty  { color: var(--muted); font-weight: 400; font-size: 0.85rem; }

  /* ── Indicators ── */
  .indicators-row {
    display: flex; flex-wrap: wrap; gap: 10px;
    margin-top: 4px;
  }
  .ind-chip {
    background: var(--surface1);
    border: 1px solid var(--overlay);
    border-radius: var(--radius-sm);
    padding: 8px 12px;
    display: flex; flex-direction: column; gap: 2px;
    min-width: 80px;
  }
  .ind-chip-label { font-size: 0.65rem; text-transform: uppercase; letter-spacing: .07em; color: var(--muted); }
  .ind-chip-value { font-size: 0.92rem; font-weight: 700; }
  .ind-chip-value.neutral { color: var(--text); }
  .ind-chip-value.bull    { color: var(--green); }
  .ind-chip-value.bear    { color: var(--red); }
  .ind-chip-value.warm    { color: var(--yellow); }

  /* ── History table ── */
  .history-table { width: 100%; border-collapse: collapse; font-size: 0.83rem; }
  .history-table th {
    text-align: left;
    padding: 8px 12px;
    color: var(--muted);
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: .07em;
    border-bottom: 1px solid var(--overlay);
  }
  .history-table td {
    padding: 10px 12px;
    border-bottom: 1px solid rgba(49,50,68,.5);
    color: var(--subtext);
    vertical-align: middle;
  }
  .history-table tr:last-child td { border-bottom: none; }
  .history-table tr:hover td { background: rgba(49,50,68,.3); }
  .empty-history { text-align: center; padding: 28px; color: var(--muted); font-size: 0.85rem; }

  /* ── Loading overlay ── */
  .loading-overlay {
    position: absolute; inset: 0;
    background: rgba(24,24,37,.75);
    display: none;
    align-items: center;
    justify-content: center;
    border-radius: var(--radius);
    z-index: 10;
    backdrop-filter: blur(2px);
  }
  .loading-overlay.active { display: flex; }
  .spinner {
    width: 28px; height: 28px;
    border: 3px solid var(--overlay);
    border-top-color: var(--mauve);
    border-radius: 50%;
    animation: spin .7s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Refresh countdown ── */
  .countdown {
    font-size: 0.75rem;
    color: var(--muted);
    padding: 4px 10px;
    background: var(--surface);
    border: 1px solid var(--overlay);
    border-radius: 999px;
  }

  .timestamp { font-size: 0.72rem; color: var(--muted); margin-top: 10px; }

  /* ── Watchlist strip ── */
  .watchlist-strip {
    display: flex; gap: 10px; margin-bottom: 20px;
    overflow-x: auto; padding-bottom: 4px;
    scrollbar-width: thin; scrollbar-color: var(--overlay) transparent;
  }
  .watchlist-strip::-webkit-scrollbar { height: 4px; }
  .watchlist-strip::-webkit-scrollbar-thumb { background: var(--overlay); border-radius: 2px; }

  .wl-card {
    background: var(--surface);
    border: 1px solid var(--overlay);
    border-radius: var(--radius-sm);
    padding: 10px 14px;
    min-width: 130px; cursor: pointer;
    transition: border-color .15s, transform .1s;
    flex-shrink: 0;
  }
  .wl-card:hover  { border-color: var(--mauve); transform: translateY(-1px); }
  .wl-card.active { border-color: var(--mauve); background: rgba(203,166,247,.08); }
  .wl-card.buy    { border-left: 3px solid var(--green); }
  .wl-card.sell   { border-left: 3px solid var(--red); }
  .wl-card.hold   { border-left: 3px solid var(--yellow); }

  .wl-ticker { font-size: 0.7rem; font-weight: 700; color: var(--muted);
               text-transform: uppercase; letter-spacing: .05em; margin-bottom: 3px; }
  .wl-price  { font-size: 1rem; font-weight: 800; color: var(--text); margin-bottom: 2px; }
  .wl-change { font-size: 0.7rem; font-weight: 600; }
  .wl-signal { font-size: 0.65rem; font-weight: 700; margin-top: 4px;
               text-transform: uppercase; letter-spacing: .04em; }
  .wl-spinner { display: inline-block; width: 12px; height: 12px;
                border: 2px solid var(--overlay); border-top-color: var(--mauve);
                border-radius: 50%; animation: spin .6s linear infinite; }

  /* ── Conditions checklist ── */
  .cond-item {
    display: flex; align-items: center; gap: 9px;
    padding: 8px 12px;
    background: var(--surface1);
    border: 1px solid var(--overlay);
    border-radius: var(--radius-sm);
    font-size: 0.8rem;
  }
  .cond-icon { font-size: 0.85rem; flex-shrink: 0; }
  .cond-text { color: var(--subtext); }
  .cond-item.met   { border-color: rgba(166,227,161,.3); background: rgba(166,227,161,.06); }
  .cond-item.unmet { border-color: rgba(49,50,68,.8);    opacity: .55; }

  /* ── Toast ── */
  #toast {
    position: fixed; bottom: 28px; right: 28px;
    background: var(--surface); border: 1px solid var(--overlay);
    border-radius: var(--radius); padding: 14px 18px;
    font-size: 0.85rem; color: var(--text);
    box-shadow: 0 8px 32px rgba(0,0,0,.4);
    display: flex; align-items: center; gap: 10px;
    opacity: 0; transform: translateY(16px);
    transition: opacity .3s, transform .3s;
    pointer-events: none; z-index: 999;
    max-width: 320px;
  }
  #toast.show { opacity: 1; transform: translateY(0); pointer-events: auto; }
  #toast-icon { font-size: 1.1rem; }

  /* ── Charts ── */
  .chart-card { margin-bottom: 16px; }
  .chart-wrap { position: relative; }
  .chart-wrap canvas { display: block; }
  .chart-legend {
    display: flex; flex-wrap: wrap; gap: 14px;
    margin-bottom: 14px;
  }
  .chart-legend-item {
    display: flex; align-items: center; gap: 5px;
    font-size: 0.72rem; color: var(--subtext);
  }
  .legend-dot {
    width: 10px; height: 3px; border-radius: 2px;
  }
  .chart-tabs {
    display: flex; gap: 6px; margin-bottom: 14px;
  }
  .chart-tab {
    padding: 4px 12px;
    border-radius: 6px;
    font-size: 0.75rem;
    font-weight: 600;
    cursor: pointer;
    border: 1px solid var(--overlay);
    background: transparent;
    color: var(--muted);
    transition: all .15s;
  }
  .chart-tab.active {
    background: var(--mauve);
    color: var(--bg);
    border-color: var(--mauve);
  }

  /* ── MTF Confluence card ── */
  .mtf-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
    margin-top: 4px;
  }
  @media (max-width: 700px) { .mtf-grid { grid-template-columns: repeat(2, 1fr); } }

  .mtf-row {
    background: var(--surface1);
    border: 1px solid var(--overlay);
    border-radius: var(--radius-sm);
    padding: 14px 16px;
    display: flex; flex-direction: column; gap: 6px;
    transition: border-color .2s;
  }
  .mtf-row.buy  { border-left: 3px solid var(--green); }
  .mtf-row.sell { border-left: 3px solid var(--red); }
  .mtf-row.hold { border-left: 3px solid var(--yellow); }
  .mtf-row.err  { border-left: 3px solid var(--muted); opacity: .5; }

  .mtf-tf-label {
    font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: .08em; color: var(--muted);
  }
  .mtf-signal {
    font-size: 0.88rem; font-weight: 800; letter-spacing: .02em;
  }
  .mtf-signal.buy  { color: var(--green); }
  .mtf-signal.sell { color: var(--red); }
  .mtf-signal.hold { color: var(--yellow); }
  .mtf-signal.err  { color: var(--muted); }

  .mtf-chips {
    display: flex; gap: 5px; flex-wrap: wrap; margin-top: 2px;
  }
  .mtf-chip {
    font-size: 0.6rem; font-weight: 700; padding: 1px 6px;
    border-radius: 4px; letter-spacing: .04em;
  }
  .mtf-chip.on  { background: rgba(166,227,161,.15); color: var(--green); border: 1px solid rgba(166,227,161,.3); }
  .mtf-chip.off { background: rgba(49,50,68,.6);     color: var(--muted);  border: 1px solid var(--overlay); }

  .mtf-conf-bar-track {
    height: 4px; background: var(--overlay); border-radius: 999px; overflow: hidden; margin-top: 4px;
  }
  .mtf-conf-bar-fill { height: 100%; border-radius: 999px; transition: width .5s ease; }

  /* Confluence badge strip */
  .confluence-strip {
    display: flex; align-items: center; gap: 12px;
    margin-bottom: 16px; flex-wrap: wrap;
  }
  .conf-direction-badge {
    font-size: 1rem; font-weight: 800; letter-spacing: .03em;
    padding: 6px 16px; border-radius: 999px;
  }
  .conf-direction-badge.BULLISH {
    background: rgba(166,227,161,.15); color: var(--green);
    border: 1px solid rgba(166,227,161,.35);
  }
  .conf-direction-badge.BEARISH {
    background: rgba(243,139,168,.15); color: var(--red);
    border: 1px solid rgba(243,139,168,.35);
  }
  .conf-direction-badge.NEUTRAL {
    background: rgba(249,226,175,.12); color: var(--yellow);
    border: 1px solid rgba(249,226,175,.3);
  }
  .conf-score-text {
    font-size: 0.78rem; color: var(--muted);
  }
  .conf-score-text strong { color: var(--text); }

  /* ── Price Alert Panel ── */
  .alert-form-row {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr auto auto;
    gap: 8px; align-items: end; margin-bottom: 14px;
  }
  @media (max-width: 700px) { .alert-form-row { grid-template-columns: 1fr 1fr; } }

  .alert-input {
    width: 100%;
    background: var(--surface1); color: var(--text);
    border: 1px solid var(--overlay); border-radius: 8px;
    padding: 7px 11px; font-size: 0.85rem; outline: none;
    transition: border-color .2s;
  }
  .alert-input:focus { border-color: var(--mauve); }
  .alert-select {
    width: 100%;
    background: var(--surface1); color: var(--text);
    border: 1px solid var(--overlay); border-radius: 8px;
    padding: 7px 11px; font-size: 0.85rem; outline: none; cursor: pointer;
    transition: border-color .2s;
  }
  .alert-select:focus { border-color: var(--mauve); }

  .alert-label {
    font-size: 0.65rem; text-transform: uppercase; letter-spacing: .07em;
    color: var(--muted); margin-bottom: 5px; display: block;
  }
  .alert-list { display: flex; flex-direction: column; gap: 7px; }
  .alert-item {
    display: flex; align-items: center; gap: 10px;
    background: var(--surface1); border: 1px solid var(--overlay);
    border-radius: var(--radius-sm); padding: 10px 14px;
    font-size: 0.82rem;
  }
  .alert-item.fired {
    border-color: rgba(250,179,135,.35);
    background: rgba(250,179,135,.06);
  }
  .alert-item-icon { font-size: 1rem; flex-shrink: 0; }
  .alert-item-body { flex: 1; min-width: 0; }
  .alert-item-title { font-weight: 700; color: var(--text); margin-bottom: 2px; }
  .alert-item-sub   { font-size: 0.72rem; color: var(--muted); }
  .alert-item-del {
    background: transparent; border: none; color: var(--muted);
    cursor: pointer; font-size: 1rem; padding: 2px 6px;
    border-radius: 4px; transition: color .15s, background .15s; flex-shrink: 0;
  }
  .alert-item-del:hover { color: var(--red); background: rgba(243,139,168,.1); }
  .alert-empty { text-align: center; color: var(--muted); font-size: 0.82rem; padding: 16px; }

  /* notification bell pulse */
  #alertBell { cursor: pointer; font-size: 1.1rem; transition: transform .2s; }
  #alertBell:hover { transform: rotate(-15deg); }
  .bell-badge {
    position: relative; display: inline-flex; align-items: center;
  }
  .bell-count {
    position: absolute; top: -6px; right: -8px;
    background: var(--red); color: var(--bg);
    font-size: 0.55rem; font-weight: 800;
    border-radius: 999px; padding: 1px 4px; line-height: 1.4;
    display: none;
  }

  /* ── Live stream badge + day range ── */
  .live-badge {
    display: inline-flex; align-items: center; gap: 5px;
    font-size: 0.68rem; font-weight: 800; letter-spacing: .06em;
    padding: 2px 9px; border-radius: 999px;
    background: rgba(166,227,161,.12);
    color: var(--green);
    border: 1px solid rgba(166,227,161,.35);
    transition: color .3s, background .3s, border-color .3s;
  }
  .live-badge.disconnected {
    background: rgba(249,226,175,.1);
    color: var(--yellow);
    border-color: rgba(249,226,175,.3);
  }
  .live-dot {
    width: 6px; height: 6px; border-radius: 50%;
    background: currentColor;
    animation: pulse 1.4s infinite;
  }
  .live-badge.disconnected .live-dot { animation: none; }

  .stream-meta {
    font-size: 0.65rem; color: var(--muted); margin-top: 6px;
  }

  /* Day range bar */
  .day-range-wrap {
    margin-top: 14px;
  }
  .day-range-labels {
    display: flex; justify-content: space-between;
    font-size: 0.65rem; color: var(--muted); margin-bottom: 4px;
  }
  .day-range-track {
    height: 6px; background: var(--overlay);
    border-radius: 999px; position: relative; overflow: visible;
  }
  .day-range-fill {
    height: 100%; border-radius: 999px;
    background: linear-gradient(90deg, var(--red), var(--yellow), var(--green));
    transition: width .6s ease;
  }
  .day-range-thumb {
    position: absolute; top: 50%; transform: translate(-50%, -50%);
    width: 10px; height: 10px; border-radius: 50%;
    background: var(--text); border: 2px solid var(--bg);
    transition: left .6s ease;
    box-shadow: 0 0 0 2px rgba(203,166,247,.4);
  }
  .day-range-center-label {
    text-align: center; font-size: 0.65rem; color: var(--muted); margin-top: 5px;
  }

  /* Price flash animation */
  @keyframes priceFlashUp   { 0%,100%{color:var(--text)} 30%{color:var(--green)} }
  @keyframes priceFlashDown { 0%,100%{color:var(--text)} 30%{color:var(--red)} }
  .price-flash-up   { animation: priceFlashUp   .8s ease; }
  .price-flash-down { animation: priceFlashDown .8s ease; }

  /* ── Backtest card ── */
  .bt-stat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
    gap: 10px;
    margin-bottom: 18px;
  }
  .bt-stat {
    background: var(--surface1);
    border: 1px solid var(--overlay);
    border-radius: var(--radius-sm);
    padding: 12px 14px;
  }
  .bt-stat-label { font-size: 0.65rem; text-transform: uppercase; letter-spacing: .07em; color: var(--muted); margin-bottom: 5px; }
  .bt-stat-value { font-size: 1.1rem; font-weight: 800; }
  .bt-stat-value.pos  { color: var(--green); }
  .bt-stat-value.neg  { color: var(--red); }
  .bt-stat-value.neut { color: var(--text); }
  .bt-stat-value.warn { color: var(--yellow); }

  .bt-trade-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; margin-top: 14px; }
  .bt-trade-table th {
    text-align: left; padding: 7px 10px;
    color: var(--muted); font-size: 0.67rem;
    text-transform: uppercase; letter-spacing: .07em;
    border-bottom: 1px solid var(--overlay);
  }
  .bt-trade-table td { padding: 8px 10px; border-bottom: 1px solid rgba(49,50,68,.4); color: var(--subtext); }
  .bt-trade-table tr:last-child td { border-bottom: none; }
  .bt-trade-table tr:hover td { background: rgba(49,50,68,.25); }
  .bt-win  { color: var(--green); font-weight: 700; }
  .bt-loss { color: var(--red);   font-weight: 700; }

  .bt-period-bar { display: flex; gap: 5px; margin-bottom: 14px; }
  .bt-period-btn {
    padding: 4px 11px; border-radius: 6px; font-size: 0.75rem; font-weight: 600;
    cursor: pointer; border: 1px solid var(--overlay);
    background: transparent; color: var(--muted); transition: all .15s;
  }
  .bt-period-btn:hover { color: var(--text); border-color: var(--subtle); }
  .bt-period-btn.active { background: rgba(148,226,213,.15); color: var(--teal); border-color: var(--teal); }

  /* ── Timeframe selector ── */
  .tf-bar {
    display: flex; gap: 4px;
  }
  .tf-btn {
    background: transparent;
    color: var(--muted);
    border: 1px solid var(--overlay);
    border-radius: 6px;
    padding: 6px 11px;
    font-size: 0.78rem;
    font-weight: 700;
    cursor: pointer;
    letter-spacing: .03em;
    transition: all .15s;
  }
  .tf-btn:hover { color: var(--text); border-color: var(--subtle); }
  .tf-btn.active {
    background: rgba(137,180,250,.15);
    color: var(--blue);
    border-color: var(--blue);
  }

  /* ── Support / Resistance card ── */
  .sr-card { margin-bottom: 16px; }

  .sr-columns {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
    margin-top: 4px;
  }
  @media (max-width: 700px) { .sr-columns { grid-template-columns: 1fr; } }

  .sr-col-label {
    font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: .08em; margin-bottom: 8px;
  }
  .sr-col-label.res { color: var(--red); }
  .sr-col-label.sup { color: var(--green); }

  .sr-level-row {
    display: flex; align-items: center; justify-content: space-between;
    background: var(--surface1);
    border: 1px solid var(--overlay);
    border-radius: var(--radius-sm);
    padding: 8px 12px;
    margin-bottom: 6px;
    font-size: 0.82rem;
  }
  .sr-level-row.nearest-res {
    border-color: rgba(243,139,168,.45);
    background: rgba(243,139,168,.07);
  }
  .sr-level-row.nearest-sup {
    border-color: rgba(166,227,161,.45);
    background: rgba(166,227,161,.07);
  }

  .sr-level-price { font-weight: 700; color: var(--text); }
  .sr-level-dist  { font-size: 0.72rem; font-weight: 600; }
  .sr-level-dist.res { color: var(--red); }
  .sr-level-dist.sup { color: var(--green); }

  .sr-nearest-strip {
    display: flex; gap: 10px; flex-wrap: wrap;
    margin-bottom: 14px;
  }
  .sr-nearest-item {
    flex: 1; min-width: 140px;
    background: var(--surface1);
    border: 1px solid var(--overlay);
    border-radius: var(--radius-sm);
    padding: 10px 14px;
  }
  .sr-nearest-item.res { border-left: 3px solid var(--red); }
  .sr-nearest-item.sup { border-left: 3px solid var(--green); }
  .sr-nearest-label { font-size: 0.65rem; text-transform: uppercase; letter-spacing: .07em; color: var(--muted); margin-bottom: 4px; }
  .sr-nearest-value { font-size: 1.1rem; font-weight: 800; }
  .sr-nearest-value.res { color: var(--red); }
  .sr-nearest-value.sup { color: var(--green); }
  .sr-nearest-dist  { font-size: 0.72rem; font-weight: 600; margin-top: 2px; color: var(--muted); }

  .sr-empty { font-size: 0.82rem; color: var(--muted); padding: 12px 0; }
</style>
</head>
<body>

<!-- ── Toast notification ─────────────────────────────────────────── -->
<div id="toast"><span id="toast-icon">🔔</span><span id="toast-msg"></span></div>

<!-- ── Header ────────────────────────────────────────────────────── -->
<div class="header">
  <div class="header-left">
    <div class="header-logo">📈</div>
    <div>
      <div class="header-title">Trading Bot Dashboard</div>
      <div class="header-subtitle">Technical Analysis · Live Data · Press R to refresh · 1–8 to switch ticker</div>
    </div>
  </div>
  <div class="header-right">
    <div class="tf-bar">
      <button class="tf-btn" onclick="setTimeframe('15m',this)">15m</button>
      <button class="tf-btn active" onclick="setTimeframe('1h',this)">1H</button>
      <button class="tf-btn" onclick="setTimeframe('4h',this)">4H</button>
      <button class="tf-btn" onclick="setTimeframe('1d',this)">1D</button>
    </div>
    <select id="tickerSelect" onchange="onTickerChange()">
      <optgroup label="Crypto">
        <option value="BTC-USD">BTC-USD</option>
        <option value="ETH-USD">ETH-USD</option>
        <option value="SOL-USD">SOL-USD</option>
        <option value="BNB-USD">BNB-USD</option>
      </optgroup>
      <optgroup label="Stocks &amp; ETFs">
        <option value="AAPL">AAPL</option>
        <option value="TSLA">TSLA</option>
        <option value="NVDA">NVDA</option>
        <option value="SPY">SPY</option>
      </optgroup>
      <optgroup label="Indices &amp; Commodities">
        <option value="NAS100">NAS100 (Nasdaq 100)</option>
        <option value="XAU">XAU (Gold)</option>
      </optgroup>
      <optgroup label="Deriv Synthetics (info only)">
        <option value="VOL251S" disabled>Vol 25 1s — Deriv only</option>
        <option value="VOL501S" disabled>Vol 50 1s — Deriv only</option>
        <option value="VOL751S" disabled>Vol 75 1s — Deriv only</option>
        <option value="VOL901S" disabled>Vol 90 1s — Deriv only</option>
        <option value="VOL1001S" disabled>Vol 100 1s — Deriv only</option>
      </optgroup>
    </select>
    <span class="countdown" id="countdown">--</span>
    <span class="bell-badge" onclick="scrollToAlerts()" title="Price Alerts">
      <span id="alertBell">🔔</span>
      <span class="bell-count" id="bellCount">0</span>
    </span>
    <button class="btn" id="refreshBtn" onclick="runAnalysis()">↻ Refresh</button>
  </div>
</div>

<!-- ── Status bar ─────────────────────────────────────────────────── -->
<div class="status-bar">
  <div class="status-dot" id="statusDot"></div>
  <span id="statusText">Ready</span>
</div>

<!-- ── Watchlist strip ───────────────────────────────────────────── -->
<div class="watchlist-strip" id="watchlistStrip">
  <!-- populated by JS -->
</div>

<!-- ── Top grid ───────────────────────────────────────────────────── -->
<div class="grid-top">

  <!-- Price + Signal -->
  <div class="card price-card">
    <div class="loading-overlay" id="priceLoader"><div class="spinner"></div></div>
    <div class="card-label" id="priceCardLabel">Price</div>
    <div class="price-value" id="priceValue">—</div>
    <div class="price-change flat" id="priceChange">—</div>
    <div id="signalBadge" class="signal-badge hold">
      <span class="signal-dot"></span>
      <span id="signalText">—</span>
    </div>
    <div style="display:flex;align-items:center;gap:10px;margin-top:10px;flex-wrap:wrap">
      <div class="timestamp" id="lastUpdated">—</div>
      <span class="live-badge disconnected" id="liveBadge">
        <span class="live-dot"></span><span id="liveBadgeText">connecting…</span>
      </span>
    </div>
    <div class="stream-meta" id="streamMeta">—</div>

    <!-- Day High/Low range bar -->
    <div class="day-range-wrap" id="dayRangeWrap" style="display:none">
      <div class="day-range-labels">
        <span>L: <strong id="dayLow">—</strong></span>
        <span style="color:var(--muted);font-size:0.62rem">Day Range</span>
        <span>H: <strong id="dayHigh">—</strong></span>
      </div>
      <div class="day-range-track">
        <div class="day-range-fill" id="dayRangeFill" style="width:100%"></div>
        <div class="day-range-thumb" id="dayRangeThumb" style="left:50%"></div>
      </div>
      <div class="day-range-center-label" id="dayRangeLabel">Price position within day range</div>
    </div>
  </div>

  <!-- Confidence + Levels -->
  <div class="card">
    <div class="loading-overlay" id="confLoader"><div class="spinner"></div></div>
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
      <div class="card-label" style="margin-bottom:0">Confidence Score</div>
      <span id="strengthLabel" style="font-size:0.72rem;font-weight:700;padding:2px 9px;border-radius:999px;background:rgba(203,166,247,.15);color:var(--mauve);border:1px solid rgba(203,166,247,.35)">—</span>
    </div>
    <div>
      <span class="conf-value" id="confValue">—</span>
      <span class="conf-denom"> / 100</span>
    </div>
    <div class="conf-bar-track">
      <div class="conf-bar-fill" id="confBar" style="width:0%"></div>
    </div>

    <div class="card-label">Trade Levels</div>
    <div class="levels-grid">
      <div class="level-item">
        <div class="level-label">Stop-Loss</div>
        <div class="level-value stop" id="stopLoss">—</div>
      </div>
      <div class="level-item">
        <div class="level-label">Take-Profit</div>
        <div class="level-value target" id="takeProfit">—</div>
      </div>
      <div class="level-item">
        <div class="level-label">Risk (2×ATR)</div>
        <div class="level-value" id="riskAmt" style="color:var(--peach)">—</div>
      </div>
      <div class="level-item">
        <div class="level-label">R:R Ratio</div>
        <div class="level-value" id="rrRatio" style="color:var(--teal)">—</div>
      </div>
    </div>
  </div>
</div>

<!-- ── Multi-Timeframe Confluence ────────────────────────────────── -->
<div class="card" style="margin-bottom:16px" id="mtfCard">
  <div class="loading-overlay" id="mtfLoader"><div class="spinner"></div></div>
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;flex-wrap:wrap;gap:8px">
    <div class="card-label" style="margin-bottom:0">Multi-Timeframe Confluence</div>
    <button class="btn btn-outline" onclick="loadMTF()" style="padding:4px 12px;font-size:0.75rem">↻ Refresh MTF</button>
  </div>
  <div class="confluence-strip" id="confluenceStrip">
    <span class="conf-direction-badge NEUTRAL" id="confDirBadge">—</span>
    <span class="conf-score-text" id="confScoreText">Analysing…</span>
  </div>
  <div class="mtf-grid" id="mtfGrid">
    <!-- populated by JS -->
  </div>
</div>

<!-- ── Charts ──────────────────────────────────────────────────────── -->
<div class="card chart-card">
  <div class="loading-overlay" id="chartLoader"><div class="spinner"></div></div>
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;flex-wrap:wrap;gap:8px">
    <div class="card-label" style="margin-bottom:0">Price Chart</div>
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
      <div class="chart-tabs">
        <button class="chart-tab active" onclick="switchChart('price',this)">Price</button>
        <button class="chart-tab" onclick="switchChart('rsi',this)">RSI</button>
        <button class="chart-tab" onclick="switchChart('macd',this)">MACD</button>
        <button class="chart-tab" onclick="switchChart('stoch',this)">Stoch</button>
        <button class="chart-tab" onclick="switchChart('adx',this)">ADX</button>
      </div>
      <button class="chart-tab" id="candleToggle" onclick="toggleChartMode()" title="Switch between line and candlestick chart" style="border-color:var(--peach);color:var(--peach)">🕯 Candle</button>
    </div>
  </div>
  <div class="chart-legend" id="chartLegend">
    <span class="chart-legend-item" id="legend-line"><span class="legend-dot" style="background:#CBA6F7"></span>Price</span>
    <span class="chart-legend-item" id="legend-candle" style="display:none">
      <span style="display:inline-flex;gap:4px;align-items:center">
        <span style="width:8px;height:12px;background:#A6E3A1;border-radius:1px;display:inline-block"></span>
        <span style="width:8px;height:12px;background:#F38BA8;border-radius:1px;display:inline-block"></span>
      </span>Candles
    </span>
    <span class="chart-legend-item"><span class="legend-dot" style="background:#89B4FA"></span>SMA 20</span>
    <span class="chart-legend-item"><span class="legend-dot" style="background:#F9E2AF"></span>SMA 50</span>
    <span class="chart-legend-item"><span class="legend-dot" style="background:rgba(148,226,213,.5)"></span>Bollinger Bands</span>
    <span class="chart-legend-item"><span class="legend-dot" style="background:#F38BA8;border-top:2px dashed #F38BA8;height:0"></span>EMA 200</span>
    <span class="chart-legend-item"><span class="legend-dot" style="background:#89DCEB"></span>VWAP</span>
    <span class="chart-legend-item"><span class="legend-dot" style="background:rgba(166,227,161,.6);height:6px"></span>Volume</span>
  </div>
  <div class="chart-wrap" id="priceChartWrap">
    <canvas id="priceChart" height="260"></canvas>
  </div>
  <div class="chart-wrap" id="rsiChartWrap" style="display:none">
    <canvas id="rsiChart" height="200"></canvas>
  </div>
  <div class="chart-wrap" id="macdChartWrap" style="display:none">
    <canvas id="macdChart" height="200"></canvas>
  </div>
  <div class="chart-wrap" id="stochChartWrap" style="display:none">
    <canvas id="stochChart" height="200"></canvas>
  </div>
  <div class="chart-wrap" id="adxChartWrap" style="display:none">
    <canvas id="adxChart" height="200"></canvas>
  </div>
</div>

<!-- ── Support / Resistance ───────────────────────────────────────── -->
<div class="card sr-card" id="srCard">
  <div class="loading-overlay" id="srLoader"><div class="spinner"></div></div>
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;flex-wrap:wrap;gap:8px">
    <div class="card-label" style="margin-bottom:0">Support &amp; Resistance Levels</div>
    <span style="font-size:0.7rem;color:var(--muted)">Swing highs/lows · last 120 bars · clustered within 0.5%</span>
  </div>

  <!-- Nearest levels strip -->
  <div class="sr-nearest-strip" id="srNearestStrip">
    <div class="sr-nearest-item res">
      <div class="sr-nearest-label">Nearest Resistance</div>
      <div class="sr-nearest-value res" id="sr-near-res">—</div>
      <div class="sr-nearest-dist"  id="sr-near-res-pct">—</div>
    </div>
    <div class="sr-nearest-item sup">
      <div class="sr-nearest-label">Nearest Support</div>
      <div class="sr-nearest-value sup" id="sr-near-sup">—</div>
      <div class="sr-nearest-dist"  id="sr-near-sup-pct">—</div>
    </div>
  </div>

  <!-- Full level lists -->
  <div class="sr-columns">
    <div>
      <div class="sr-col-label res">Resistance Levels</div>
      <div id="srResistanceList"><div class="sr-empty">Loading…</div></div>
    </div>
    <div>
      <div class="sr-col-label sup">Support Levels</div>
      <div id="srSupportList"><div class="sr-empty">Loading…</div></div>
    </div>
  </div>
</div>

<!-- ── Indicators ─────────────────────────────────────────────────── -->
<div class="card grid-bottom" style="margin-bottom:16px">
  <div class="loading-overlay" id="indLoader"><div class="spinner"></div></div>
  <div class="card-label">Indicators</div>
  <div class="indicators-row" id="indicatorsRow">
    <div class="ind-chip"><span class="ind-chip-label">RSI</span><span class="ind-chip-value neutral" id="ind-rsi">—</span></div>
    <div class="ind-chip"><span class="ind-chip-label">MACD</span><span class="ind-chip-value neutral" id="ind-macd">—</span></div>
    <div class="ind-chip"><span class="ind-chip-label">Signal Line</span><span class="ind-chip-value neutral" id="ind-sig">—</span></div>
    <div class="ind-chip"><span class="ind-chip-label">SMA 20</span><span class="ind-chip-value neutral" id="ind-sma20">—</span></div>
    <div class="ind-chip"><span class="ind-chip-label">SMA 50</span><span class="ind-chip-value neutral" id="ind-sma50">—</span></div>
    <div class="ind-chip"><span class="ind-chip-label">BB Upper</span><span class="ind-chip-value neutral" id="ind-bbu">—</span></div>
    <div class="ind-chip"><span class="ind-chip-label">BB Lower</span><span class="ind-chip-value neutral" id="ind-bbl">—</span></div>
    <div class="ind-chip"><span class="ind-chip-label">BB Width</span><span class="ind-chip-value neutral" id="ind-bbw">—</span></div>
    <div class="ind-chip"><span class="ind-chip-label">ATR</span><span class="ind-chip-value neutral" id="ind-atr">—</span></div>
    <div class="ind-chip"><span class="ind-chip-label">Momentum 5p</span><span class="ind-chip-value neutral" id="ind-mom">—</span></div>
    <div class="ind-chip"><span class="ind-chip-label">Stoch %K</span><span class="ind-chip-value neutral" id="ind-stk">—</span></div>
    <div class="ind-chip"><span class="ind-chip-label">EMA 200</span><span class="ind-chip-value neutral" id="ind-ema200">—</span></div>
    <div class="ind-chip"><span class="ind-chip-label">VWAP</span><span class="ind-chip-value neutral" id="ind-vwap">—</span></div>
    <div class="ind-chip"><span class="ind-chip-label">ADX (14)</span><span class="ind-chip-value neutral" id="ind-adx">—</span></div>
    <div class="ind-chip"><span class="ind-chip-label">+DI</span><span class="ind-chip-value neutral" id="ind-pdi">—</span></div>
    <div class="ind-chip"><span class="ind-chip-label">-DI</span><span class="ind-chip-value neutral" id="ind-mdi">—</span></div>
    <div class="ind-chip"><span class="ind-chip-label">Rel Volume</span><span class="ind-chip-value neutral" id="ind-vol-ratio">—</span></div>
  </div>
</div>

<!-- ── Position Sizing Calculator ────────────────────────────────── -->
<div class="card grid-bottom" style="margin-bottom:16px" id="posCard">
  <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:16px">
    <div class="card-label" style="margin-bottom:0">Position Sizing Calculator</div>
    <span style="font-size:0.7rem;color:var(--muted)">Based on 2×ATR risk</span>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px">
    <div>
      <label style="font-size:0.68rem;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);display:block;margin-bottom:5px">Portfolio Size ($)</label>
      <input id="portfolioInput" type="number" value="10000" min="100" step="100"
        style="width:100%;background:var(--surface1);color:var(--text);border:1px solid var(--overlay);border-radius:8px;padding:8px 12px;font-size:0.9rem;outline:none"
        oninput="calcPosition()">
    </div>
    <div>
      <label style="font-size:0.68rem;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);display:block;margin-bottom:5px">Risk Per Trade (%)</label>
      <input id="riskPctInput" type="number" value="1" min="0.1" max="10" step="0.1"
        style="width:100%;background:var(--surface1);color:var(--text);border:1px solid var(--overlay);border-radius:8px;padding:8px 12px;font-size:0.9rem;outline:none"
        oninput="calcPosition()">
    </div>
  </div>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px" id="posResults">
    <div class="level-item"><div class="level-label">Max Risk ($)</div><div class="level-value" id="pos-maxrisk" style="color:var(--red)">—</div></div>
    <div class="level-item"><div class="level-label">Units to Buy</div><div class="level-value" id="pos-units"   style="color:var(--blue)">—</div></div>
    <div class="level-item"><div class="level-label">Position Value</div><div class="level-value" id="pos-value"  style="color:var(--mauve)">—</div></div>
    <div class="level-item"><div class="level-label">% of Portfolio</div><div class="level-value" id="pos-pct"    style="color:var(--teal)">—</div></div>
  </div>
</div>

<!-- ── Signal Conditions ──────────────────────────────────────────── -->
<div class="card grid-bottom" style="margin-bottom:16px" id="conditionsCard">
  <div class="card-label">Signal Conditions</div>
  <div id="conditionsGrid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:8px"></div>
</div>

<!-- ── Backtest ───────────────────────────────────────────────────── -->
<div class="card grid-bottom" id="backtestCard" style="margin-bottom:16px">
  <div class="loading-overlay" id="btLoader"><div class="spinner"></div></div>
  <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:14px">
    <div>
      <div class="card-label" style="margin-bottom:2px">📊 Strategy Backtest</div>
      <div style="font-size:0.7rem;color:var(--muted)">Walk-forward sim · 2×ATR stop · 3×ATR target · one trade at a time</div>
    </div>
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
      <div class="bt-period-bar" id="btPeriodBar">
        <button class="bt-period-btn" onclick="setBtPeriod('5d',this)">5D</button>
        <button class="bt-period-btn active" onclick="setBtPeriod('90d',this)">3M</button>
        <button class="bt-period-btn" onclick="setBtPeriod('180d',this)">6M</button>
        <button class="bt-period-btn" onclick="setBtPeriod('1y',this)">1Y</button>
        <button class="bt-period-btn" onclick="setBtPeriod('2y',this)">2Y</button>
      </div>
      <button class="btn btn-outline" onclick="loadBacktest()" style="padding:4px 12px;font-size:0.75rem">↻ Run</button>
    </div>
  </div>

  <!-- Stat chips -->
  <div class="bt-stat-grid" id="btStatGrid">
    <div class="bt-stat"><div class="bt-stat-label">Total Trades</div><div class="bt-stat-value neut" id="bt-trades">—</div></div>
    <div class="bt-stat"><div class="bt-stat-label">Win Rate</div><div class="bt-stat-value neut" id="bt-winrate">—</div></div>
    <div class="bt-stat"><div class="bt-stat-label">Profit Factor</div><div class="bt-stat-value neut" id="bt-pf">—</div></div>
    <div class="bt-stat"><div class="bt-stat-label">Total Return</div><div class="bt-stat-value neut" id="bt-return">—</div></div>
    <div class="bt-stat"><div class="bt-stat-label">Max Drawdown</div><div class="bt-stat-value neut" id="bt-dd">—</div></div>
    <div class="bt-stat"><div class="bt-stat-label">Avg Win</div><div class="bt-stat-value neut" id="bt-avgwin">—</div></div>
    <div class="bt-stat"><div class="bt-stat-label">Avg Loss</div><div class="bt-stat-value neut" id="bt-avgloss">—</div></div>
    <div class="bt-stat"><div class="bt-stat-label">W / L</div><div class="bt-stat-value neut" id="bt-wl">—</div></div>
  </div>

  <!-- Equity curve mini-chart -->
  <div style="position:relative;margin-bottom:16px">
    <canvas id="equityChart" height="140"></canvas>
  </div>

  <!-- Trade log table -->
  <div style="font-size:0.68rem;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);margin-bottom:8px">Last 20 Trades</div>
  <div style="overflow-x:auto">
    <table class="bt-trade-table" id="btTradeTable">
      <thead><tr>
        <th>#</th><th>Date</th><th>Signal</th>
        <th>Entry</th><th>Exit</th><th>P&amp;L %</th><th>Exit Reason</th>
      </tr></thead>
      <tbody id="btTradeBody">
        <tr><td colspan="7" style="text-align:center;padding:20px;color:var(--muted)">Click ↻ Run to load backtest</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- ── Price Alerts ───────────────────────────────────────────────── -->
<div class="card grid-bottom" id="alertsCard" style="margin-bottom:16px">
  <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:16px">
    <div class="card-label" style="margin-bottom:0">🔔 Price Alerts</div>
    <span style="font-size:0.7rem;color:var(--muted)">Fires on next analysis refresh</span>
  </div>

  <!-- Create form -->
  <div class="alert-form-row">
    <div>
      <label class="alert-label">Ticker</label>
      <input class="alert-input" id="al-ticker" placeholder="BTC-USD" value="">
    </div>
    <div>
      <label class="alert-label">Condition</label>
      <select class="alert-select" id="al-condition" onchange="onAlertCondChange()">
        <option value="price_above">Price rises above</option>
        <option value="price_below">Price falls below</option>
        <option value="rsi_above">RSI rises above</option>
        <option value="rsi_below">RSI falls below</option>
        <option value="signal_is">Signal becomes</option>
      </select>
    </div>
    <div id="al-val-wrap">
      <label class="alert-label" id="al-val-label">Value</label>
      <input class="alert-input" id="al-value" type="number" placeholder="e.g. 70000" step="any">
    </div>
    <div id="al-sig-wrap" style="display:none">
      <label class="alert-label">Signal</label>
      <select class="alert-select" id="al-signal-val">
        <option value="STRONG BUY">STRONG BUY</option>
        <option value="STRONG SELL">STRONG SELL</option>
        <option value="HOLD">HOLD</option>
      </select>
    </div>
    <div>
      <label class="alert-label">Note (optional)</label>
      <input class="alert-input" id="al-note" placeholder="My note…">
    </div>
    <div style="padding-bottom:0">
      <label class="alert-label">&nbsp;</label>
      <button class="btn" onclick="createAlert()" style="width:100%;justify-content:center">+ Add Alert</button>
    </div>
  </div>

  <!-- Notification permission -->
  <div id="notifBanner" style="display:none;margin-bottom:12px;padding:8px 12px;background:rgba(203,166,247,.1);border:1px solid rgba(203,166,247,.3);border-radius:8px;font-size:0.78rem;color:var(--subtext);align-items:center;gap:10px">
    <span>🔔 Enable desktop notifications to get instant alerts even when the tab is in the background.</span>
    <button class="btn" onclick="requestNotifPermission()" style="padding:4px 12px;font-size:0.75rem;white-space:nowrap">Enable</button>
  </div>

  <!-- Active alerts -->
  <div style="margin-bottom:10px">
    <div style="font-size:0.68rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:8px">Active Alerts <span id="activeAlertCount" style="color:var(--mauve)"></span></div>
    <div class="alert-list" id="activeAlertList">
      <div class="alert-empty">No active alerts — create one above.</div>
    </div>
  </div>

  <!-- Fired alerts -->
  <div id="firedSection" style="display:none">
    <div style="font-size:0.68rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:8px">Recently Fired</div>
    <div class="alert-list" id="firedAlertList"></div>
  </div>
</div>

<!-- ── History ────────────────────────────────────────────────────── -->
<div class="card grid-bottom">
  <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:14px">
    <div class="card-label" style="margin-bottom:0">Signal History</div>
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
      <span id="session-stats" style="font-size:0.72rem;color:var(--muted)"></span>
      <button class="btn btn-outline" onclick="exportCSV()" style="padding:4px 12px;font-size:0.75rem">⬇ Export CSV</button>
    </div>
  </div>
  <table class="history-table">
    <thead>
      <tr>
        <th>Time</th>
        <th>Ticker</th>
        <th>Signal</th>
        <th>Price</th>
        <th>Confidence</th>
        <th>Stop-Loss</th>
        <th>Take-Profit</th>
      </tr>
    </thead>
    <tbody id="historyBody">
      <tr><td colspan="7" class="empty-history">No history yet — run an analysis above.</td></tr>
    </tbody>
  </table>
</div>

<script>
  const REFRESH_INTERVAL = 300; // seconds
  let countdown = REFRESH_INTERVAL;
  let timer = null;
  let lastSignal = {};   // ticker → last known signal
  let currentInterval = '1h';  // timeframe: 15m | 1h | 4h | 1d

  function setTimeframe(interval, btn) {
    currentInterval = interval;
    document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    runAnalysis();
    loadChart();
    loadSR();
    loadBacktest();
    // MTF always fetches all 4 timeframes regardless of selected TF
  }

  let toastTimer = null;
  function showToast(icon, msg, duration = 5000) {
    const t = document.getElementById('toast');
    document.getElementById('toast-icon').textContent = icon;
    document.getElementById('toast-msg').textContent  = msg;
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), duration);
  }

  function fmt(n, decimals = 2) {
    if (n == null) return '—';
    return Number(n).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  }

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function signalClass(signal) {
    if (signal.includes('BUY'))  return 'buy';
    if (signal.includes('SELL')) return 'sell';
    return 'hold';
  }

  function signalBadgeHTML(signal) {
    const cls = signalClass(signal);
    return `<span class="signal-dot"></span><span id="signalText">${signal}</span>`;
  }

  function setLoading(on) {
    const loaders = ['priceLoader', 'confLoader', 'indLoader'];
    loaders.forEach(id => {
      document.getElementById(id).classList.toggle('active', on);
    });
    document.getElementById('refreshBtn').disabled = on;
    const dot = document.getElementById('statusDot');
    dot.className = 'status-dot' + (on ? ' loading' : '');
    document.getElementById('statusText').textContent = on ? 'Fetching data…' : 'Live';
  }

  function setError(msg) {
    setLoading(false);
    document.getElementById('statusDot').className = 'status-dot error';
    document.getElementById('statusText').textContent = 'Error: ' + msg;
  }

  function updateUI(data) {
    const ind = data.indicators || {};

    // Price
    const ticker = data.ticker;
    document.getElementById('priceCardLabel').textContent = ticker;
    document.getElementById('priceValue').textContent = '$' + fmt(data.price);

    const cp = document.getElementById('priceChange');
    if (data.change_pct != null) {
      const up = data.change_pct >= 0;
      cp.textContent = (up ? '▲ +' : '▼ ') + fmt(data.change_pct, 2) + '% (24h approx)';
      cp.className = 'price-change ' + (up ? 'up' : 'down');
    } else {
      cp.textContent = '24h change unavailable';
      cp.className = 'price-change flat';
    }

    // Signal
    const badge = document.getElementById('signalBadge');
    badge.className = 'signal-badge ' + signalClass(data.signal);
    badge.innerHTML = signalBadgeHTML(data.signal);

    document.getElementById('lastUpdated').textContent = 'Updated: ' + data.timestamp;

    // Confidence + strength label + colour-coded bar
    document.getElementById('confValue').textContent = data.confidence;
    const bar = document.getElementById('confBar');
    bar.style.width = data.confidence + '%';
    const barGradients = {
      Strong:   'linear-gradient(90deg,#A6E3A1,#94E2D5)',
      Moderate: 'linear-gradient(90deg,#89B4FA,#CBA6F7)',
      Weak:     'linear-gradient(90deg,#F9E2AF,#FAB387)',
      Neutral:  'linear-gradient(90deg,#6C7086,#9399B2)',
    };
    bar.style.background = barGradients[data.strength] || barGradients.Neutral;
    const sl = document.getElementById('strengthLabel');
    sl.textContent = data.strength || '—';
    const strengthColors = { Strong: '#A6E3A1', Moderate: '#89B4FA', Weak: '#F9E2AF', Neutral: '#6C7086' };
    const sc = strengthColors[data.strength] || '#CBA6F7';
    sl.style.color = sc;
    sl.style.background = sc + '26';   // 15% opacity hex
    sl.style.borderColor = sc + '59';  // 35% opacity border

    // Levels
    const hasLevels = data.stop_loss != null;
    document.getElementById('stopLoss').textContent   = hasLevels ? '$' + fmt(data.stop_loss)   : 'N/A — HOLD';
    document.getElementById('takeProfit').textContent = hasLevels ? '$' + fmt(data.take_profit) : 'N/A — HOLD';
    document.getElementById('stopLoss').className   = 'level-value ' + (hasLevels ? 'stop'   : 'empty');
    document.getElementById('takeProfit').className = 'level-value ' + (hasLevels ? 'target' : 'empty');
    // Feed position calculator
    _lastAtr   = data.atr   || null;
    _lastPrice = data.price || null;
    calcPosition();

    if (hasLevels) {
      const risk   = Math.abs(data.price - data.stop_loss);
      const reward = Math.abs(data.take_profit - data.price);
      document.getElementById('riskAmt').textContent = '$' + fmt(risk);
      document.getElementById('rrRatio').textContent = '1 : ' + (reward / risk).toFixed(2);
    } else {
      document.getElementById('riskAmt').textContent = '—';
      document.getElementById('rrRatio').textContent = '—';
    }

    // Indicators
    function rsiClass(v) { return v < 30 ? 'bull' : v > 70 ? 'bear' : 'warm'; }
    function macdClass(m, s) { return m > s ? 'bull' : 'bear'; }
    function momClass(v) { return v > 2 ? 'bull' : v < -2 ? 'bear' : 'neutral'; }

    document.getElementById('ind-rsi').textContent   = fmt(ind.rsi, 1);
    document.getElementById('ind-rsi').className     = 'ind-chip-value ' + rsiClass(ind.rsi);
    document.getElementById('ind-macd').textContent  = fmt(ind.macd, 4);
    document.getElementById('ind-macd').className    = 'ind-chip-value ' + macdClass(ind.macd, ind.signal_line);
    document.getElementById('ind-sig').textContent   = fmt(ind.signal_line, 4);
    document.getElementById('ind-sig').className     = 'ind-chip-value neutral';
    document.getElementById('ind-sma20').textContent = '$' + fmt(ind.sma_20);
    document.getElementById('ind-sma20').className   = 'ind-chip-value ' + (data.price > ind.sma_20 ? 'bull' : 'bear');
    document.getElementById('ind-sma50').textContent = '$' + fmt(ind.sma_50);
    document.getElementById('ind-sma50').className   = 'ind-chip-value ' + (data.price > ind.sma_50 ? 'bull' : 'bear');
    document.getElementById('ind-bbu').textContent   = '$' + fmt(ind.bb_upper);
    document.getElementById('ind-bbu').className     = 'ind-chip-value neutral';
    document.getElementById('ind-bbl').textContent   = '$' + fmt(ind.bb_lower);
    document.getElementById('ind-bbl').className     = 'ind-chip-value neutral';
    document.getElementById('ind-atr').textContent   = fmt(ind.atr, 2);
    document.getElementById('ind-atr').className     = 'ind-chip-value neutral';
    document.getElementById('ind-mom').textContent   = (ind.momentum >= 0 ? '+' : '') + fmt(ind.momentum, 2) + '%';
    document.getElementById('ind-mom').className     = 'ind-chip-value ' + momClass(ind.momentum);
    if (ind.stoch_k != null) {
      document.getElementById('ind-stk').textContent = fmt(ind.stoch_k, 1);
      document.getElementById('ind-stk').className   = 'ind-chip-value ' + rsiClass(ind.stoch_k);
    }
    if (ind.ema_200 != null) {
      const aboveEma = data.price > ind.ema_200;
      document.getElementById('ind-ema200').textContent = '$' + fmt(ind.ema_200);
      document.getElementById('ind-ema200').className   = 'ind-chip-value ' + (aboveEma ? 'bull' : 'bear');
      // Long-term trend badge on price card
      let ltBadge = document.getElementById('lt-trend');
      if (!ltBadge) {
        ltBadge = document.createElement('span');
        ltBadge.id = 'lt-trend';
        ltBadge.style.cssText = 'font-size:.7rem;font-weight:700;padding:2px 8px;border-radius:999px;margin-left:8px;vertical-align:middle';
        document.getElementById('signalBadge').after(ltBadge);
      }
      const pct = ((data.price - ind.ema_200) / ind.ema_200 * 100).toFixed(1);
      ltBadge.textContent = (aboveEma ? '▲' : '▼') + ' ' + Math.abs(pct) + '% vs EMA 200';
      ltBadge.style.color      = aboveEma ? '#A6E3A1' : '#F38BA8';
      ltBadge.style.background = aboveEma ? 'rgba(166,227,161,.12)' : 'rgba(243,139,168,.12)';
      ltBadge.style.border     = `1px solid ${aboveEma ? 'rgba(166,227,161,.3)' : 'rgba(243,139,168,.3)'}`;
    }
    if (ind.vwap != null) {
      const aboveVwap = data.price > ind.vwap;
      const vwapEl = document.getElementById('ind-vwap');
      vwapEl.textContent = '$' + fmt(ind.vwap);
      vwapEl.className   = 'ind-chip-value ' + (aboveVwap ? 'bull' : 'bear');
    }

    // ── ADX / Market Regime ──────────────────────────────────────────
    if (ind.adx != null) {
      const adxEl  = document.getElementById('ind-adx');
      const pdiEl  = document.getElementById('ind-pdi');
      const mdiEl  = document.getElementById('ind-mdi');
      const adxVal = ind.adx;
      const adxCls = adxVal >= 40 ? 'bull' : adxVal >= 25 ? 'warm' : 'neutral';
      adxEl.textContent = adxVal.toFixed(1);
      adxEl.className   = 'ind-chip-value ' + adxCls;
      pdiEl.textContent = (ind.plus_di  || 0).toFixed(1);
      pdiEl.className   = 'ind-chip-value ' + (ind.plus_di > ind.minus_di ? 'bull' : 'neutral');
      mdiEl.textContent = (ind.minus_di || 0).toFixed(1);
      mdiEl.className   = 'ind-chip-value ' + (ind.minus_di > ind.plus_di  ? 'bear' : 'neutral');

      // Regime badge near signal
      let regimeBadge = document.getElementById('regime-badge');
      if (!regimeBadge) {
        regimeBadge = document.createElement('span');
        regimeBadge.id = 'regime-badge';
        regimeBadge.style.cssText = 'font-size:.68rem;font-weight:700;padding:2px 8px;border-radius:999px;margin-left:8px;vertical-align:middle;letter-spacing:.04em';
        document.getElementById('signalBadge').after(regimeBadge);
      }
      const trending = ind.regime === 'TRENDING';
      regimeBadge.textContent  = trending ? '📈 TRENDING' : '↔ RANGING';
      regimeBadge.style.color      = trending ? 'var(--teal)'   : 'var(--yellow)';
      regimeBadge.style.background = trending ? 'rgba(148,226,213,.12)' : 'rgba(249,226,175,.1)';
      regimeBadge.style.border     = trending ? '1px solid rgba(148,226,213,.35)' : '1px solid rgba(249,226,175,.25)';
    }

    // ── Volume spike badge ────────────────────────────────────────────
    if (ind.vol_ratio != null) {
      const volEl = document.getElementById('ind-vol-ratio');
      if (volEl) {
        volEl.textContent = ind.vol_ratio.toFixed(2) + 'x avg';
        volEl.className   = 'ind-chip-value ' + (ind.vol_spike ? 'bull' : 'neutral');
      }
      let volBadge = document.getElementById('vol-spike-badge');
      if (ind.vol_spike) {
        if (!volBadge) {
          volBadge = document.createElement('span');
          volBadge.id = 'vol-spike-badge';
          volBadge.style.cssText = 'font-size:.68rem;font-weight:700;padding:2px 9px;border-radius:999px;letter-spacing:.04em;display:inline-block;margin-left:6px';
          const anchor = document.getElementById('regime-badge') || document.getElementById('signalBadge');
          if (anchor) anchor.after(volBadge);
        }
        volBadge.textContent       = '\\u26a1 VOL SPIKE ' + ind.vol_ratio.toFixed(1) + 'x';
        volBadge.style.color       = '#A6E3A1';
        volBadge.style.background  = 'rgba(166,227,161,.12)';
        volBadge.style.border      = '1px solid rgba(166,227,161,.3)';
        volBadge.style.display     = 'inline-block';
        volBadge.title = 'Volume is ' + ind.vol_ratio.toFixed(1) + 'x the 20-bar average — confirms the move';
      } else if (volBadge) {
        volBadge.style.display = 'none';
      }
    }

    // ── RSI Divergence badge ──────────────────────────────────────────
    if (ind.divergence) {
      let divBadge = document.getElementById('div-badge');
      if (!divBadge) {
        divBadge = document.createElement('span');
        divBadge.id = 'div-badge';
        divBadge.style.cssText = 'font-size:.68rem;font-weight:700;padding:2px 9px;border-radius:999px;letter-spacing:.04em;display:inline-block;margin-left:6px';
        const anchor = document.getElementById('vol-spike-badge') || document.getElementById('regime-badge') || document.getElementById('signalBadge');
        if (anchor) anchor.after(divBadge);
      }
      const isBull = ind.divergence === 'BULLISH_DIV';
      divBadge.textContent      = isBull ? '\\u21d1 BULL DIV' : '\\u21d3 BEAR DIV';
      divBadge.style.color      = isBull ? '#A6E3A1' : '#F38BA8';
      divBadge.style.background = isBull ? 'rgba(166,227,161,.12)' : 'rgba(243,139,168,.12)';
      divBadge.style.border     = isBull ? '1px solid rgba(166,227,161,.3)' : '1px solid rgba(243,139,168,.3)';
      divBadge.style.display    = 'inline-block';
      divBadge.title = isBull
        ? 'Bullish RSI divergence: price made a lower low but RSI did not — potential reversal up'
        : 'Bearish RSI divergence: price made a higher high but RSI did not — potential reversal down';
    } else {
      const divBadge = document.getElementById('div-badge');
      if (divBadge) divBadge.style.display = 'none';
    }
  }

  // ── Position sizing ───────────────────────────────────────────────
  let _lastAtr = null, _lastPrice = null;

  function calcPosition() {
    const portfolio = parseFloat(document.getElementById('portfolioInput').value) || 0;
    const riskPct   = parseFloat(document.getElementById('riskPctInput').value)   || 1;
    const atr   = _lastAtr;
    const price = _lastPrice;
    if (!atr || !price || portfolio <= 0) return;

    const maxRisk  = portfolio * (riskPct / 100);       // $ at risk
    const riskPerUnit = 2 * atr;                         // stop distance = 2×ATR
    const units    = maxRisk / riskPerUnit;              // how many coins/shares
    const posValue = units * price;                      // total $ exposure
    const posShare = (posValue / portfolio) * 100;       // % of portfolio

    document.getElementById('pos-maxrisk').textContent = '$' + fmt(maxRisk);
    document.getElementById('pos-units').textContent   = units < 1 ? units.toFixed(6) : fmt(units, 4);
    document.getElementById('pos-value').textContent   = '$' + fmt(posValue);
    const pctEl = document.getElementById('pos-pct');
    pctEl.textContent = fmt(posShare, 1) + '%';
    pctEl.style.color = posShare > 100 ? 'var(--red)' : posShare > 50 ? 'var(--yellow)' : 'var(--teal)';
    // Show leverage warning
    let warn = document.getElementById('pos-warn');
    if (posShare > 100) {
      if (!warn) {
        warn = document.createElement('p');
        warn.id = 'pos-warn';
        warn.style.cssText = 'font-size:.75rem;color:var(--red);margin-top:10px;padding:6px 10px;background:rgba(243,139,168,.1);border-radius:6px;border:1px solid rgba(243,139,168,.25)';
        document.getElementById('posResults').after(warn);
      }
      warn.textContent = `⚠️ Position is ${fmt(posShare,1)}% of portfolio — consider reducing size or risk %.`;
    } else if (warn) { warn.remove(); }
  }

  function updateConditions(data) {
    const c = data.conditions || {};
    const sig = data.signal || '';
    const isBuy  = sig.includes('BUY');
    const isSell = sig.includes('SELL');

    // Define which conditions are relevant to the current signal direction
    const items = isBuy ? [
      { key: 'price_above_sma20',    label: 'Price > SMA 20'          },
      { key: 'sma20_above_sma50',    label: 'SMA 20 > SMA 50'         },
      { key: 'rsi_oversold',         label: 'RSI Oversold (< 30)'     },
      { key: 'rsi_below_50',         label: 'RSI Below 50'            },
      { key: 'macd_above_signal',    label: 'MACD > Signal Line'      },
      { key: 'price_below_bb_lower', label: 'Price Below BB Lower'    },
      { key: 'momentum_positive',    label: 'Momentum Bullish (>2%)'  },
      { key: 'price_above_ema200',   label: 'Price Above EMA 200'     },
      { key: 'adx_trending',         label: 'ADX ≥ 25 (Trending)'    },
      { key: 'volume_spike',         label: 'Volume Spike (≥1.5x avg)'},
      { key: 'bullish_divergence',   label: 'Bullish RSI Divergence'  },
    ] : isSell ? [
      { key: 'price_above_sma20',    label: 'Price < SMA 20',    invert: true },
      { key: 'sma20_above_sma50',    label: 'SMA 20 < SMA 50',   invert: true },
      { key: 'rsi_overbought',       label: 'RSI Overbought (> 70)'   },
      { key: 'rsi_above_50',         label: 'RSI Above 50'            },
      { key: 'macd_above_signal',    label: 'MACD < Signal Line', invert: true },
      { key: 'price_above_bb_upper', label: 'Price Above BB Upper'    },
      { key: 'momentum_negative',    label: 'Momentum Bearish (<-2%)' },
      { key: 'price_above_ema200',   label: 'Price Below EMA 200', invert: true },
      { key: 'adx_trending',         label: 'ADX ≥ 25 (Trending)'    },
      { key: 'volume_spike',         label: 'Volume Spike (≥1.5x avg)'},
      { key: 'bearish_divergence',   label: 'Bearish RSI Divergence'  },
    ] : [
      { key: 'price_above_sma20',    label: 'Price vs SMA 20'         },
      { key: 'macd_above_signal',    label: 'MACD vs Signal Line'     },
      { key: 'rsi_below_50',         label: 'RSI Below 50'            },
      { key: 'momentum_positive',    label: 'Momentum Positive'       },
      { key: 'adx_trending',         label: 'ADX ≥ 25 (Trending)'    },
    ];

    const grid = document.getElementById('conditionsGrid');
    grid.innerHTML = items.map(item => {
      const raw  = !!c[item.key];
      const met  = item.invert ? !raw : raw;
      return `<div class="cond-item ${met ? 'met' : 'unmet'}">
        <span class="cond-icon">${met ? '✅' : '○'}</span>
        <span class="cond-text">${item.label}</span>
      </div>`;
    }).join('');
  }

  // ── Session stats + CSV export ───────────────────────────────────
  const sessionRows = [];  // full history for CSV

  function updateSessionStats() {
    const buys  = sessionRows.filter(r => r.signal.includes('BUY')).length;
    const sells = sessionRows.filter(r => r.signal.includes('SELL')).length;
    const holds = sessionRows.filter(r => r.signal === 'HOLD').length;
    const el = document.getElementById('session-stats');
    if (sessionRows.length === 0) { el.textContent = ''; return; }
    el.innerHTML =
      `<span style="color:var(--green)">${buys}B</span> · ` +
      `<span style="color:var(--red)">${sells}S</span> · ` +
      `<span style="color:var(--yellow)">${holds}H</span> · ` +
      `${sessionRows.length} total`;
  }

  function exportCSV() {
    if (sessionRows.length === 0) { showToast('ℹ️', 'No history to export yet.', 3000); return; }
    const headers = ['Time','Ticker','Signal','Price','Confidence','Stop-Loss','Take-Profit'];
    const rows = sessionRows.map(r => [
      r.timestamp, r.ticker, r.signal,
      r.price, r.confidence,
      r.stop_loss ?? '', r.take_profit ?? ''
    ]);
    const csv = [headers, ...rows].map(r => r.join(',')).join('\\n');
    const a = document.createElement('a');
    a.href = 'data:text/csv;charset=utf-8,' + encodeURIComponent(csv);
    a.download = `signals_${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
    showToast('✅', `Exported ${rows.length} signals as CSV.`, 3000);
  }

  function addHistoryRow(data) {
    const body = document.getElementById('historyBody');
    sessionRows.unshift(data);
    updateSessionStats();
    // Remove placeholder
    if (body.querySelector('.empty-history')) body.innerHTML = '';

    const cls = signalClass(data.signal);
    const colors = { buy: '#A6E3A1', sell: '#F38BA8', hold: '#F9E2AF' };
    const color = colors[cls];

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${data.timestamp}</td>
      <td style="font-weight:600;color:var(--subtext)">${data.ticker}</td>
      <td><span style="color:${color};font-weight:700">${data.signal}</span></td>
      <td>$${fmt(data.price)}</td>
      <td>${data.confidence}/100</td>
      <td style="color:var(--red)">${data.stop_loss != null ? '$' + fmt(data.stop_loss) : '—'}</td>
      <td style="color:var(--green)">${data.take_profit != null ? '$' + fmt(data.take_profit) : '—'}</td>
    `;
    body.insertBefore(tr, body.firstChild);
    // Keep max 20 rows
    while (body.children.length > 20) body.removeChild(body.lastChild);
  }

  async function runAnalysis() {
    const ticker = document.getElementById('tickerSelect').value;
    setLoading(true);
    resetCountdown();

    try {
      const res = await fetch('/api/analyze/' + ticker + '?interval=' + currentInterval);
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || res.statusText);
      }
      const data = await res.json();
      updateUI(data);
      updateConditions(data);
      addHistoryRow(data);
      updateChartLevels(data);   // draw stop/target/entry on price chart
      setLoading(false);
      // Fire toast if signal changed since last check
      const prev = lastSignal[data.ticker];
      if (prev && prev !== data.signal) {
        const icons = { 'STRONG BUY': '🟢', 'STRONG SELL': '🔴', 'HOLD': '🟡' };
        showToast(icons[data.signal] || '🔔', `${data.ticker} signal changed: ${prev} → ${data.signal}`);
      }
      lastSignal[data.ticker] = data.signal;
      checkTriggeredAlerts(data);
    } catch (e) {
      setError(e.message);
    }
  }

  function resetCountdown() {
    countdown = REFRESH_INTERVAL;
    clearInterval(timer);
    timer = setInterval(() => {
      countdown--;
      document.getElementById('countdown').textContent = 'Auto ↻ ' + countdown + 's';
      if (countdown <= 0) { runAnalysis(); loadChart(); loadSR(); loadWatchlist(); loadMTF(); }
    }, 1000);
  }

  function onTickerChange() {
    const ticker = document.getElementById('tickerSelect').value;
    runAnalysis(); loadChart(); loadSR(); loadMTF(); highlightWatchlist(); loadBacktest();
    connectPriceStream(ticker);
    document.getElementById('al-ticker').value = ticker;
    // Hide day range until next stream tick
    document.getElementById('dayRangeWrap').style.display = 'none';
    document.getElementById('streamMeta').textContent = '—';
  }

  // ── Watchlist strip ───────────────────────────────────────────────
  function signalColorClass(sig) {
    if (!sig) return 'hold';
    if (sig.includes('BUY'))  return 'buy';
    if (sig.includes('SELL')) return 'sell';
    return 'hold';
  }

  function highlightWatchlist() {
    const cur = document.getElementById('tickerSelect').value;
    document.querySelectorAll('.wl-card').forEach(c => {
      c.classList.toggle('active', c.dataset.ticker === cur);
    });
  }

  function renderWatchlist(items) {
    const strip = document.getElementById('watchlistStrip');
    const cur   = document.getElementById('tickerSelect').value;
    strip.innerHTML = items.map(item => {
      const cls    = signalColorClass(item.signal);
      const chg    = item.change;
      const chgStr = chg != null
        ? `<span class="wl-change" style="color:${chg >= 0 ? 'var(--green)' : 'var(--red)'}">${chg >= 0 ? '▲' : '▼'} ${Math.abs(chg).toFixed(2)}%</span>`
        : `<span class="wl-change" style="color:var(--muted)">—</span>`;
      const sigColor = {buy:'var(--green)', sell:'var(--red)', hold:'var(--yellow)'}[cls];
      const priceStr = item.price != null ? '$' + Number(item.price).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}) : '—';
      return `<div class="wl-card ${cls}${item.ticker===cur?' active':''}" data-ticker="${item.ticker}"
                   onclick="switchToTicker('${item.ticker}')">
        <div class="wl-ticker">${item.ticker}</div>
        <div class="wl-price">${priceStr}</div>
        ${chgStr}
        <div class="wl-signal" style="color:${sigColor}">${item.signal}</div>
      </div>`;
    }).join('');
  }

  function switchToTicker(t) {
    document.getElementById('tickerSelect').value = t;
    onTickerChange();
  }

  async function loadWatchlist() {
    // Show spinners first
    const strip = document.getElementById('watchlistStrip');
    if (!strip.children.length) {
      const WATCHLIST = ['BTC-USD','ETH-USD','SOL-USD','AAPL','NVDA','SPY'];
      strip.innerHTML = WATCHLIST.map(t =>
        `<div class="wl-card hold" data-ticker="${t}" onclick="switchToTicker('${t}')">
           <div class="wl-ticker">${t}</div>
           <div class="wl-price"><span class="wl-spinner"></span></div>
         </div>`
      ).join('');
    }
    try {
      const res  = await fetch('/api/watchlist');
      if (!res.ok) return;
      const data = await res.json();
      renderWatchlist(data);
    } catch(e) { /* silently skip on error */ }
  }

  // ── Multi-Timeframe Confluence ────────────────────────────────────
  async function loadMTF() {
    const ticker = document.getElementById('tickerSelect').value;
    document.getElementById('mtfLoader').classList.add('active');
    document.getElementById('confScoreText').textContent = 'Analysing all timeframes…';

    try {
      const res = await fetch('/api/mtf/' + ticker);
      if (!res.ok) { document.getElementById('confScoreText').textContent = 'Error loading MTF data'; return; }
      const data = await res.json();
      renderMTF(data);
    } catch(e) {
      document.getElementById('confScoreText').textContent = 'Network error: ' + e.message;
    } finally {
      document.getElementById('mtfLoader').classList.remove('active');
    }
  }

  function renderMTF(data) {
    const c = data.confluence;
    const dir = c.direction;

    // Confluence badge
    const badge = document.getElementById('confDirBadge');
    badge.textContent = dir === 'BULLISH' ? '▲ BULLISH' : dir === 'BEARISH' ? '▼ BEARISH' : '◆ NEUTRAL';
    badge.className = 'conf-direction-badge ' + dir;

    // Score text
    const icons = { BULLISH: '🟢', BEARISH: '🔴', NEUTRAL: '🟡' };
    const scoreEl = document.getElementById('confScoreText');
    scoreEl.innerHTML =
      `<strong>${c.aligned} / ${c.total}</strong> timeframes ${dir.toLowerCase()} &nbsp;·&nbsp; ` +
      `<span style="color:var(--green)">${c.buy_count} Buy</span> &nbsp;` +
      `<span style="color:var(--red)">${c.sell_count} Sell</span> &nbsp;` +
      `<span style="color:var(--yellow)">${c.hold_count} Hold</span>`;

    // Timeframe rows
    const grid = document.getElementById('mtfGrid');
    grid.innerHTML = data.timeframes.map(tf => {
      if (!tf.ok && tf.signal === 'ERROR') {
        return `<div class="mtf-row err">
          <div class="mtf-tf-label">${tf.label}</div>
          <div class="mtf-signal err">Error</div>
        </div>`;
      }
      const cls   = signalClass(tf.signal);
      const rsiCls = tf.rsi < 30 ? 'on' : tf.rsi > 70 ? 'on' : 'off';
      const rsiLbl = tf.rsi < 30 ? 'RSI OS' : tf.rsi > 70 ? 'RSI OB' : 'RSI ' + (tf.rsi != null ? tf.rsi.toFixed(0) : '—');

      // Confidence bar colour
      const barColors = { Strong:'#A6E3A1', Moderate:'#89B4FA', Weak:'#F9E2AF', Neutral:'#6C7086' };
      const barCol = barColors[tf.strength] || '#6C7086';

      const adxVal   = tf.adx != null ? tf.adx : 0;
      const adxCls   = adxVal >= 40 ? 'on' : adxVal >= 25 ? 'on' : 'off';
      const adxLabel = adxVal >= 40 ? 'ADX▲▲' : adxVal >= 25 ? 'ADX▲' : 'ADX—';
      const regimeLbl = tf.regime === 'TRENDING' ? '📈' : '↔';

      return `<div class="mtf-row ${cls}">
        <div class="mtf-tf-label">${tf.label} <span style="font-weight:400;opacity:.7">${regimeLbl}</span></div>
        <div class="mtf-signal ${cls}">${tf.signal}</div>
        <div class="mtf-chips">
          <span class="mtf-chip ${tf.macd_bull ? 'on' : 'off'}">${tf.macd_bull ? 'MACD▲' : 'MACD▼'}</span>
          <span class="mtf-chip ${tf.above_sma20 ? 'on' : 'off'}">SMA20</span>
          <span class="mtf-chip ${tf.above_sma50 ? 'on' : 'off'}">TREND</span>
          <span class="mtf-chip ${rsiCls}">${rsiLbl}</span>
          <span class="mtf-chip ${adxCls}" title="+DI ${tf.plus_di||0} / -DI ${tf.minus_di||0}">${adxLabel}</span>
        </div>
        <div class="mtf-conf-bar-track">
          <div class="mtf-conf-bar-fill" style="width:${tf.confidence}%;background:${barCol}"></div>
        </div>
      </div>`;
    }).join('');
  }

  // ── Chart.js setup ────────────────────────────────────────────────
  const CHART_DEFAULTS = {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 400 },
    interaction: { mode: 'index', intersect: false },
    plugins: { legend: { display: false }, tooltip: { backgroundColor: '#313244', titleColor: '#CDD6F4', bodyColor: '#BAC2DE', borderColor: '#45475A', borderWidth: 1 } },
    scales: {
      x: { ticks: { color: '#6C7086', maxTicksLimit: 10, font: { size: 10 } }, grid: { color: 'rgba(49,50,68,.5)' } },
      y: { ticks: { color: '#6C7086', font: { size: 10 } }, grid: { color: 'rgba(49,50,68,.5)' } }
    }
  };

  let priceChart = null, rsiChart = null, macdChart = null;
  let activeChartTab = 'price';
  let _lastSrData      = null;
  let _lastChartData   = null;
  let _lastAnalysisData = null;  // stop/target/entry levels for chart overlay
  let chartMode        = 'line';

  function toggleChartMode() {
    chartMode = (chartMode === 'line') ? 'candle' : 'line';
    const btn = document.getElementById('candleToggle');
    if (chartMode === 'candle') {
      btn.textContent = '📈 Line';
      btn.style.borderColor = 'var(--green)';
      btn.style.color = 'var(--green)';
      document.getElementById('legend-line').style.display   = 'none';
      document.getElementById('legend-candle').style.display = '';
    } else {
      btn.textContent = '🕯 Candle';
      btn.style.borderColor = 'var(--peach)';
      btn.style.color = 'var(--peach)';
      document.getElementById('legend-line').style.display   = '';
      document.getElementById('legend-candle').style.display = 'none';
    }
    if (_lastChartData) buildPriceChart(_lastChartData, _lastSrData);
  }

  // ── Trade level annotations (stop / target / entry) ─────────────────
  function _tradeLevelAnnotations(analysisData) {
    const lvl = {};
    if (!analysisData) return lvl;
    const { stop_loss, take_profit, price, signal } = analysisData;
    const isBuy = signal && signal.includes('BUY');
    if (price != null) {
      lvl['trade_entry'] = {
        type: 'line', scaleID: 'y', value: price,
        borderColor: 'rgba(203,166,247,.7)', borderWidth: 1.5, borderDash: [6,3],
        label: { display: true, content: 'Entry $' + fmt(price),
          position: 'start', backgroundColor: 'rgba(203,166,247,.18)',
          color: '#CBA6F7', font: { size: 9, weight: '700' },
          padding: { x: 4, y: 2 }, borderRadius: 3 }
      };
    }
    if (stop_loss != null) {
      lvl['trade_stop'] = {
        type: 'line', scaleID: 'y', value: stop_loss,
        borderColor: 'rgba(243,139,168,.85)', borderWidth: 2, borderDash: [5,4],
        label: { display: true,
          content: 'Stop $' + fmt(stop_loss) + '  (' + (isBuy ? '-' : '+') + fmt(Math.abs((stop_loss-price)/price*100),2) + '%)',
          position: 'start', backgroundColor: 'rgba(243,139,168,.2)',
          color: '#F38BA8', font: { size: 9, weight: '700' },
          padding: { x: 4, y: 2 }, borderRadius: 3 }
      };
    }
    if (take_profit != null) {
      lvl['trade_target'] = {
        type: 'line', scaleID: 'y', value: take_profit,
        borderColor: 'rgba(166,227,161,.85)', borderWidth: 2, borderDash: [5,4],
        label: { display: true,
          content: 'Target $' + fmt(take_profit) + '  (' + (isBuy ? '+' : '-') + fmt(Math.abs((take_profit-price)/price*100),2) + '%)',
          position: 'start', backgroundColor: 'rgba(166,227,161,.2)',
          color: '#A6E3A1', font: { size: 9, weight: '700' },
          padding: { x: 4, y: 2 }, borderRadius: 3 }
      };
    }
    return lvl;
  }

  function updateChartLevels(analysisData) {
    _lastAnalysisData = analysisData;
    if (!priceChart) return;
    const annots = priceChart.options.plugins.annotation.annotations || {};
    // Remove old trade annotations
    ['trade_entry','trade_stop','trade_target'].forEach(k => delete annots[k]);
    // Add new ones
    Object.assign(annots, _tradeLevelAnnotations(analysisData));
    priceChart.options.plugins.annotation.annotations = annots;
    priceChart.update('none');
  }

  function buildPriceChart(d, srData) {
    const ctx = document.getElementById('priceChart').getContext('2d');
    if (priceChart) priceChart.destroy();

    // ── S/R annotation objects (shared by both modes) ──────────────
    const annotations = {};
    if (srData) {
      (srData.resistances || []).forEach((r, i) => {
        annotations['res_' + i] = {
          type: 'line', scaleID: 'y', value: r.level,
          borderColor: i === 0 ? 'rgba(243,139,168,.9)' : 'rgba(243,139,168,.45)',
          borderWidth: i === 0 ? 1.5 : 1,
          borderDash: i === 0 ? [] : [4, 3],
          label: {
            display: true,
            content: '$' + Number(r.level).toLocaleString('en-US', {minimumFractionDigits:2,maximumFractionDigits:2}) + ' R' + (i === 0 ? ' \\u2605' : ''),
            position: 'end',
            backgroundColor: 'rgba(243,139,168,.18)',
            color: '#F38BA8',
            font: { size: 9, weight: '700' },
            padding: { x: 4, y: 2 },
            borderRadius: 3,
          }
        };
      });
      (srData.supports || []).forEach((s, i) => {
        annotations['sup_' + i] = {
          type: 'line', scaleID: 'y', value: s.level,
          borderColor: i === 0 ? 'rgba(166,227,161,.9)' : 'rgba(166,227,161,.45)',
          borderWidth: i === 0 ? 1.5 : 1,
          borderDash: i === 0 ? [] : [4, 3],
          label: {
            display: true,
            content: '$' + Number(s.level).toLocaleString('en-US', {minimumFractionDigits:2,maximumFractionDigits:2}) + ' S' + (i === 0 ? ' \\u2605' : ''),
            position: 'end',
            backgroundColor: 'rgba(166,227,161,.18)',
            color: '#A6E3A1',
            font: { size: 9, weight: '700' },
            padding: { x: 4, y: 2 },
            borderRadius: 3,
          }
        };
      });
    }

    // Merge trade-level annotations (stop/target/entry)
    Object.assign(annotations, _tradeLevelAnnotations(_lastAnalysisData));

    const sharedOptions = {
      ...CHART_DEFAULTS,
      plugins: { ...CHART_DEFAULTS.plugins, annotation: { annotations } },
    };

    // Volume colours: spike bars (vol_ratio >= 1.5) get full opacity, others are faded
    const volRatio = d.vol_ratio || [];
    const volColors = d.price.map((p, i) => {
      const spike = volRatio[i] != null && volRatio[i] >= 1.5;
      const up    = i === 0 || p >= d.price[i-1];
      if (spike) return up ? 'rgba(166,227,161,.85)' : 'rgba(243,139,168,.85)';
      return           up ? 'rgba(166,227,161,.3)'  : 'rgba(243,139,168,.3)';
    });
    const yScale = { ...CHART_DEFAULTS.scales.y, ticks: { ...CHART_DEFAULTS.scales.y.ticks, callback: v => '$' + v.toLocaleString() } };
    const yVol   = { display: false, grid: { display: false }, max: d.volume.length ? Math.max(...d.volume) * 5 : 1 };

    // ── CANDLESTICK MODE ───────────────────────────────────────────
    if (chartMode === 'candle' && d.open && d.high && d.low) {
      const n = d.price.length;
      // Numeric x = index; overlays also indexed
      const idx = i => i;
      const ohlcData = d.price.map((c, i) => ({ x: i, o: d.open[i], h: d.high[i], l: d.low[i], c }));
      const mapXY    = (arr) => arr.map((v, i) => ({ x: i, y: v }));
      const volData  = d.volume.map((v, i) => ({ x: i, y: v }));

      priceChart = new Chart(ctx, {
        type: 'candlestick',
        data: {
          datasets: [
            { type: 'bar',         label: 'Volume',   data: volData,         backgroundColor: volColors, borderWidth: 0, yAxisID: 'yVol', order: 4 },
            { type: 'line',        label: 'BB Upper', data: mapXY(d.bb_upper), borderColor: 'rgba(148,226,213,.35)', borderWidth: 1, borderDash: [3,3], pointRadius: 0, fill: false, yAxisID: 'y', order: 2 },
            { type: 'line',        label: 'BB Lower', data: mapXY(d.bb_lower), borderColor: 'rgba(148,226,213,.35)', borderWidth: 1, borderDash: [3,3], pointRadius: 0, fill: false, yAxisID: 'y', order: 2 },
            { type: 'line',        label: 'SMA 50',   data: mapXY(d.sma50),    borderColor: '#F9E2AF', borderWidth: 1.5, pointRadius: 0, fill: false, yAxisID: 'y', order: 2 },
            { type: 'line',        label: 'SMA 20',   data: mapXY(d.sma20),    borderColor: '#89B4FA', borderWidth: 1.5, pointRadius: 0, fill: false, yAxisID: 'y', order: 2 },
            { type: 'line',        label: 'EMA 200',  data: mapXY(d.ema200),   borderColor: '#F38BA8', borderWidth: 1.5, borderDash: [6,3], pointRadius: 0, fill: false, yAxisID: 'y', order: 2 },
            { type: 'line',        label: 'VWAP',     data: mapXY(d.vwap),     borderColor: '#89DCEB', borderWidth: 1.5, borderDash: [4,2], pointRadius: 0, fill: false, yAxisID: 'y', order: 2 },
            { type: 'candlestick', label: 'Candles',  data: ohlcData,
              color: { up: '#A6E3A1', down: '#F38BA8', unchanged: '#CDD6F4' },
              borderColor: { up: '#A6E3A1', down: '#F38BA8', unchanged: '#CDD6F4' },
              yAxisID: 'y', order: 1 },
          ]
        },
        options: {
          ...sharedOptions,
          scales: {
            x: {
              type: 'linear',
              min: 0, max: n - 1,
              ticks: {
                color: '#6C7086', maxTicksLimit: 10, font: { size: 10 },
                callback: function(v) {
                  const i = Math.round(v);
                  return (i >= 0 && i < d.labels.length) ? d.labels[i] : '';
                }
              },
              grid: { color: 'rgba(49,50,68,.5)' }
            },
            y:    yScale,
            yVol: yVol,
          }
        }
      });

    // ── LINE MODE (default) ────────────────────────────────────────
    } else {
      priceChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels: d.labels,
          datasets: [
            { type: 'bar',  label: 'Volume',   data: d.volume,   backgroundColor: volColors, borderWidth: 0, yAxisID: 'yVol', order: 2 },
            { label: 'BB Upper', data: d.bb_upper, borderColor: 'rgba(148,226,213,.35)', borderWidth: 1, borderDash: [3,3], pointRadius: 0, fill: '+1', backgroundColor: 'rgba(148,226,213,.07)', yAxisID: 'y', order: 1 },
            { label: 'BB Lower', data: d.bb_lower, borderColor: 'rgba(148,226,213,.35)', borderWidth: 1, borderDash: [3,3], pointRadius: 0, fill: false, yAxisID: 'y', order: 1 },
            { label: 'SMA 50',   data: d.sma50,    borderColor: '#F9E2AF', borderWidth: 1.5, pointRadius: 0, fill: false, yAxisID: 'y', order: 1 },
            { label: 'SMA 20',   data: d.sma20,    borderColor: '#89B4FA', borderWidth: 1.5, pointRadius: 0, fill: false, yAxisID: 'y', order: 1 },
            { label: 'EMA 200',  data: d.ema200,   borderColor: '#F38BA8', borderWidth: 1.5, borderDash: [6,3], pointRadius: 0, fill: false, yAxisID: 'y', order: 1 },
            { label: 'VWAP',     data: d.vwap,     borderColor: '#89DCEB', borderWidth: 1.5, borderDash: [4,2], pointRadius: 0, fill: false, yAxisID: 'y', order: 1 },
            { label: 'Price',    data: d.price,    borderColor: '#CBA6F7', borderWidth: 2,   pointRadius: 0, fill: false, tension: 0.1, yAxisID: 'y', order: 0 },
          ]
        },
        options: {
          ...sharedOptions,
          scales: {
            x:    CHART_DEFAULTS.scales.x,
            y:    yScale,
            yVol: yVol,
          }
        }
      });
    }
  }

  function buildRsiChart(d) {
    const ctx = document.getElementById('rsiChart').getContext('2d');
    if (rsiChart) rsiChart.destroy();
    // Overbought/oversold bands
    const ob = new Array(d.labels.length).fill(70);
    const os = new Array(d.labels.length).fill(30);
    rsiChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: d.labels,
        datasets: [
          { label: 'Overbought', data: ob, borderColor: 'rgba(243,139,168,.3)', borderWidth: 1, borderDash: [4,4], pointRadius: 0, fill: false },
          { label: 'Oversold',   data: os, borderColor: 'rgba(166,227,161,.3)', borderWidth: 1, borderDash: [4,4], pointRadius: 0, fill: false },
          { label: 'RSI',        data: d.rsi, borderColor: '#FAB387', borderWidth: 2, pointRadius: 0, fill: false, tension: 0.1 },
        ]
      },
      options: { ...CHART_DEFAULTS, scales: { ...CHART_DEFAULTS.scales, y: { ...CHART_DEFAULTS.scales.y, min: 0, max: 100 } } }
    });
  }

  function buildMacdChart(d) {
    const ctx = document.getElementById('macdChart').getContext('2d');
    if (macdChart) macdChart.destroy();
    // Histogram bars: green when MACD > Signal, red when below
    const histColors = (d.macd_hist || []).map(v => v >= 0 ? 'rgba(166,227,161,.6)' : 'rgba(243,139,168,.6)');
    macdChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: d.labels,
        datasets: [
          { type: 'bar',  label: 'Histogram',   data: d.macd_hist,   backgroundColor: histColors, borderWidth: 0, yAxisID: 'y' },
          { type: 'line', label: 'MACD',         data: d.macd,        borderColor: '#89B4FA', borderWidth: 2, pointRadius: 0, fill: false, tension: 0.1, yAxisID: 'y' },
          { type: 'line', label: 'Signal Line',  data: d.signal_line, borderColor: '#F38BA8', borderWidth: 1.5, borderDash: [4,3], pointRadius: 0, fill: false, tension: 0.1, yAxisID: 'y' },
        ]
      },
      options: CHART_DEFAULTS
    });
  }

  let stochChart = null;
  function buildStochChart(d) {
    const ctx = document.getElementById('stochChart').getContext('2d');
    if (stochChart) stochChart.destroy();
    const ob = new Array(d.labels.length).fill(80);
    const os = new Array(d.labels.length).fill(20);
    stochChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: d.labels,
        datasets: [
          { label: 'Overbought', data: ob,       borderColor: 'rgba(243,139,168,.3)', borderWidth: 1, borderDash: [4,4], pointRadius: 0, fill: false },
          { label: 'Oversold',   data: os,       borderColor: 'rgba(166,227,161,.3)', borderWidth: 1, borderDash: [4,4], pointRadius: 0, fill: false },
          { label: '%K',         data: d.stoch_k, borderColor: '#CBA6F7', borderWidth: 2,   pointRadius: 0, fill: false, tension: 0.1 },
          { label: '%D',         data: d.stoch_d, borderColor: '#F9E2AF', borderWidth: 1.5, borderDash: [3,3], pointRadius: 0, fill: false, tension: 0.1 },
        ]
      },
      options: { ...CHART_DEFAULTS, scales: { ...CHART_DEFAULTS.scales, y: { ...CHART_DEFAULTS.scales.y, min: 0, max: 100 } } }
    });
  }

  let adxChart = null;
  function buildAdxChart(d) {
    const ctx = document.getElementById('adxChart').getContext('2d');
    if (adxChart) adxChart.destroy();
    if (!d.adx || !d.adx.length) return;
    const threshold25 = new Array(d.labels.length).fill(25);
    const threshold40 = new Array(d.labels.length).fill(40);
    // Colour ADX line: strong (≥40) green, trending (≥25) teal, ranging yellow
    const adxColors = d.adx.map(v => v == null ? 'rgba(108,112,134,.5)' : v >= 40 ? '#A6E3A1' : v >= 25 ? '#94E2D5' : '#F9E2AF');
    adxChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: d.labels,
        datasets: [
          { label: 'Strong (40)', data: threshold40, borderColor: 'rgba(166,227,161,.25)', borderWidth: 1, borderDash: [4,4], pointRadius: 0, fill: false },
          { label: 'Trending (25)', data: threshold25, borderColor: 'rgba(148,226,213,.35)', borderWidth: 1, borderDash: [4,3], pointRadius: 0, fill: false },
          { label: 'ADX', data: d.adx, borderColor: '#94E2D5', borderWidth: 2.5, pointRadius: 0, fill: false, tension: 0.2,
            segment: { borderColor: ctx2 => {
              const v = ctx2.p1.parsed.y;
              return v >= 40 ? '#A6E3A1' : v >= 25 ? '#94E2D5' : '#F9E2AF';
            }}
          },
        ]
      },
      options: {
        ...CHART_DEFAULTS,
        plugins: { ...CHART_DEFAULTS.plugins,
          tooltip: { ...CHART_DEFAULTS.plugins.tooltip,
            callbacks: { label: ctx2 => {
              const v = ctx2.raw;
              if (v == null) return 'ADX: —';
              return 'ADX: ' + v.toFixed(1) + (v >= 40 ? ' (Strong trend)' : v >= 25 ? ' (Trending)' : ' (Ranging)');
            }}
          }
        },
        scales: { ...CHART_DEFAULTS.scales, y: { ...CHART_DEFAULTS.scales.y, min: 0, suggestedMax: 60,
          ticks: { ...CHART_DEFAULTS.scales.y.ticks, callback: v => v.toFixed(0) }
        }}
      }
    });
  }

  async function loadChart() {
    const ticker = document.getElementById('tickerSelect').value;
    document.getElementById('chartLoader').classList.add('active');
    const candleMap = {'15m': 200, '1h': 120, '4h': 90, '1d': 180};
    const candles = candleMap[currentInterval] || 120;
    try {
      const res = await fetch('/api/chart/' + ticker + '?interval=' + currentInterval + '&candles=' + candles);
      if (!res.ok) return;
      const d = await res.json();
      _lastChartData = d;
      buildPriceChart(d, _lastSrData);
      buildRsiChart(d);
      buildMacdChart(d);
      buildStochChart(d);
      buildAdxChart(d);

      // ── BB Squeeze badge ────────────────────────────────────────────
      if (d.bb_squeeze_now != null) {
        let sqBadge = document.getElementById('bb-squeeze-badge');
        if (!sqBadge) {
          sqBadge = document.createElement('span');
          sqBadge.id = 'bb-squeeze-badge';
          sqBadge.style.cssText = 'font-size:.68rem;font-weight:700;padding:2px 9px;border-radius:999px;letter-spacing:.04em;display:inline-block;margin-left:6px';
          const indBbw = document.getElementById('ind-bbw');
          if (indBbw) indBbw.parentElement.after(sqBadge);
        }
        if (d.bb_squeeze_now) {
          sqBadge.textContent  = '⚡ BB SQUEEZE';
          sqBadge.style.color      = 'var(--yellow)';
          sqBadge.style.background = 'rgba(249,226,175,.12)';
          sqBadge.style.border     = '1px solid rgba(249,226,175,.35)';
          sqBadge.title = 'Bollinger Bands are at a 20-bar low — a big move may be imminent';
        } else {
          sqBadge.textContent  = 'BB Normal';
          sqBadge.style.color      = 'var(--muted)';
          sqBadge.style.background = 'transparent';
          sqBadge.style.border     = '1px solid var(--overlay)';
          sqBadge.title = 'Bollinger Bands bandwidth is normal';
        }
      }
      // Update BB Width chip
      const bbwEl = document.getElementById('ind-bbw');
      if (bbwEl && d.bb_width_now != null) {
        bbwEl.textContent = (d.bb_width_now * 100).toFixed(1) + '%';
        bbwEl.className   = d.bb_squeeze_now ? 'ind-chip-value warm' : 'ind-chip-value neutral';
      }
    } finally {
      document.getElementById('chartLoader').classList.remove('active');
    }
  }

  // ── Support / Resistance ─────────────────────────────────────────
  function renderSR(data) {
    _lastSrData = data;
    const fmt2 = n => n != null ? '$' + Number(n).toLocaleString('en-US', {minimumFractionDigits:2,maximumFractionDigits:2}) : '—';
    const fmtPct = p => p != null ? (p >= 0 ? '+' : '') + p.toFixed(2) + '%' : '—';

    // Nearest strip
    document.getElementById('sr-near-res').textContent = fmt2(data.nearest_resistance);
    document.getElementById('sr-near-res-pct').textContent = data.nearest_res_pct != null ? fmtPct(data.nearest_res_pct) + ' away' : '—';
    document.getElementById('sr-near-sup').textContent = fmt2(data.nearest_support);
    document.getElementById('sr-near-sup-pct').textContent = data.nearest_sup_pct != null ? fmtPct(data.nearest_sup_pct) + ' away' : '—';

    // Full lists
    const resList = document.getElementById('srResistanceList');
    const supList = document.getElementById('srSupportList');

    if (!data.resistances || data.resistances.length === 0) {
      resList.innerHTML = '<div class="sr-empty">No resistance levels detected</div>';
    } else {
      resList.innerHTML = data.resistances.map((r, i) =>
        `<div class="sr-level-row ${i === 0 ? 'nearest-res' : ''}">
          <span class="sr-level-price">${fmt2(r.level)}</span>
          <span class="sr-level-dist res">${fmtPct(r.dist_pct)}</span>
        </div>`
      ).join('');
    }

    if (!data.supports || data.supports.length === 0) {
      supList.innerHTML = '<div class="sr-empty">No support levels detected</div>';
    } else {
      supList.innerHTML = data.supports.map((s, i) =>
        `<div class="sr-level-row ${i === 0 ? 'nearest-sup' : ''}">
          <span class="sr-level-price">${fmt2(s.level)}</span>
          <span class="sr-level-dist sup">${fmtPct(s.dist_pct)}</span>
        </div>`
      ).join('');
    }

    // Redraw price chart with new S/R lines if it exists
    if (priceChart) {
      const annots = {};
      (data.resistances || []).forEach((r, i) => {
        annots['res_' + i] = {
          type: 'line', scaleID: 'y', value: r.level,
          borderColor: i === 0 ? 'rgba(243,139,168,.9)' : 'rgba(243,139,168,.45)',
          borderWidth: i === 0 ? 1.5 : 1,
          borderDash: i === 0 ? [] : [4, 3],
          label: {
            display: true,
            content: '$' + Number(r.level).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}) + ' R' + (i === 0 ? ' \u2605' : ''),
            position: 'end',
            backgroundColor: 'rgba(243,139,168,.18)',
            color: '#F38BA8',
            font: { size: 9, weight: '700' },
            padding: { x: 4, y: 2 },
            borderRadius: 3,
          }
        };
      });
      (data.supports || []).forEach((s, i) => {
        annots['sup_' + i] = {
          type: 'line', scaleID: 'y', value: s.level,
          borderColor: i === 0 ? 'rgba(166,227,161,.9)' : 'rgba(166,227,161,.45)',
          borderWidth: i === 0 ? 1.5 : 1,
          borderDash: i === 0 ? [] : [4, 3],
          label: {
            display: true,
            content: '$' + Number(s.level).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}) + ' S' + (i === 0 ? ' \u2605' : ''),
            position: 'end',
            backgroundColor: 'rgba(166,227,161,.18)',
            color: '#A6E3A1',
            font: { size: 9, weight: '700' },
            padding: { x: 4, y: 2 },
            borderRadius: 3,
          }
        };
      });
      priceChart.options.plugins.annotation.annotations = annots;
      priceChart.update('none');
    }
  }

  async function loadSR() {
    const ticker = document.getElementById('tickerSelect').value;
    document.getElementById('srLoader').classList.add('active');
    const candleMap = {'15m': 200, '1h': 120, '4h': 90, '1d': 180};
    const candles = candleMap[currentInterval] || 120;
    try {
      const res = await fetch('/api/sr/' + ticker + '?interval=' + currentInterval + '&candles=' + candles);
      if (!res.ok) return;
      const data = await res.json();
      renderSR(data);
    } catch(e) { /* silently skip */ }
    finally {
      document.getElementById('srLoader').classList.remove('active');
    }
  }

  function switchChart(name, btn) {
    activeChartTab = name;
    document.querySelectorAll('.chart-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const wraps = { price: 'priceChartWrap', rsi: 'rsiChartWrap', macd: 'macdChartWrap', stoch: 'stochChartWrap', adx: 'adxChartWrap' };
    const legends = { price: true, rsi: false, macd: false, stoch: false, adx: false };
    Object.entries(wraps).forEach(([k, id]) => {
      document.getElementById(id).style.display = k === name ? 'block' : 'none';
    });
    document.getElementById('chartLegend').style.display = legends[name] ? 'flex' : 'none';
  }

  // ── Keyboard shortcuts ───────────────────────────────────────────
  document.addEventListener('keydown', e => {
    if (e.target.tagName === 'INPUT') return;
    if (e.key === 'r' || e.key === 'R') { runAnalysis(); loadChart(); }
    const tickerKeys = {'1':'BTC-USD','2':'ETH-USD','3':'SOL-USD','4':'BNB-USD','5':'AAPL','6':'TSLA','7':'NVDA','8':'SPY'};
    if (tickerKeys[e.key]) {
      document.getElementById('tickerSelect').value = tickerKeys[e.key];
      onTickerChange();
    }
  });

  // ── Price Alert System ────────────────────────────────────────────
  let _notifGranted = (typeof Notification !== 'undefined' && Notification.permission === 'granted');

  function scrollToAlerts() {
    document.getElementById('alertsCard').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function onAlertCondChange() {
    const cond = document.getElementById('al-condition').value;
    const isSignal = cond === 'signal_is';
    document.getElementById('al-val-wrap').style.display  = isSignal ? 'none' : '';
    document.getElementById('al-sig-wrap').style.display  = isSignal ? '' : 'none';
    if (!isSignal) {
      const labels = { price_above:'Price Target ($)', price_below:'Price Target ($)', rsi_above:'RSI Level (0-100)', rsi_below:'RSI Level (0-100)' };
      document.getElementById('al-val-label').textContent = labels[cond] || 'Value';
    }
  }

  async function requestNotifPermission() {
    if (typeof Notification === 'undefined') { showToast('⚠️','Browser does not support notifications',4000); return; }
    const perm = await Notification.requestPermission();
    _notifGranted = (perm === 'granted');
    if (_notifGranted) {
      document.getElementById('notifBanner').style.display = 'none';
      showToast('🔔', 'Desktop notifications enabled!', 3000);
    } else {
      showToast('⚠️', 'Notification permission denied.', 3000);
    }
  }

  function _fireDesktopNotif(title, body) {
    if (!_notifGranted) return;
    try {
      const n = new Notification(title, { body, icon: '/favicon.ico', tag: 'trading-alert' });
      setTimeout(() => n.close(), 8000);
    } catch(e) { /* ignore */ }
  }

  async function createAlert() {
    const ticker = (document.getElementById('al-ticker').value || '').trim().toUpperCase();
    const cond   = document.getElementById('al-condition').value;
    if (!ticker) { showToast('⚠️', 'Enter a ticker symbol.', 3000); return; }

    const isSignal = cond === 'signal_is';
    const valueRaw = document.getElementById('al-value').value;
    const value    = isSignal ? null : (valueRaw !== '' ? parseFloat(valueRaw) : null);
    const sigVal   = isSignal ? document.getElementById('al-signal-val').value : null;

    if (!isSignal && value === null) { showToast('⚠️', 'Enter a value for this condition.', 3000); return; }

    const payload = { ticker, condition: cond, value, signal_val: sigVal, note: document.getElementById('al-note').value };
    try {
      const res = await fetch('/api/alerts', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
      if (!res.ok) throw new Error('Server error');
      showToast('✅', `Alert set: ${ticker} ${cond.replace(/_/g,' ')} ${isSignal ? sigVal : '$'+fmt(value)}`, 4000);
      document.getElementById('al-ticker').value = '';
      document.getElementById('al-value').value  = '';
      document.getElementById('al-note').value   = '';
      await loadAlerts();
      // Show notif banner if not yet granted
      if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
        document.getElementById('notifBanner').style.display = 'flex';
      }
    } catch(e) { showToast('❌', 'Failed to create alert: ' + e.message, 4000); }
  }

  async function deleteAlert(id) {
    try {
      await fetch('/api/alerts/' + id, { method: 'DELETE' });
      await loadAlerts();
    } catch(e) { showToast('❌', 'Delete failed', 3000); }
  }

  function condLabel(a) {
    if (a.condition === 'price_above') return `Price ≥ $${fmt(a.value)}`;
    if (a.condition === 'price_below') return `Price ≤ $${fmt(a.value)}`;
    if (a.condition === 'rsi_above')   return `RSI ≥ ${fmt(a.value, 1)}`;
    if (a.condition === 'rsi_below')   return `RSI ≤ ${fmt(a.value, 1)}`;
    if (a.condition === 'signal_is')   return `Signal = ${esc(a.signal_val)}`;
    return a.condition;
  }

  async function loadAlerts() {
    try {
      const res  = await fetch('/api/alerts');
      if (!res.ok) return;
      const data = await res.json();
      renderActiveAlerts(data.active || []);
      renderFiredAlerts(data.fired  || []);
      updateBellBadge(data.active.length);
    } catch(e) { /* silently skip */ }
  }

  function updateBellBadge(n) {
    const el = document.getElementById('bellCount');
    el.textContent = n;
    el.style.display = n > 0 ? 'block' : 'none';
  }

  function renderActiveAlerts(items) {
    const list = document.getElementById('activeAlertList');
    document.getElementById('activeAlertCount').textContent = items.length ? `(${items.length})` : '';
    if (!items.length) {
      list.innerHTML = '<div class="alert-empty">No active alerts — create one above.</div>';
      return;
    }
    list.innerHTML = items.map(a => `
      <div class="alert-item">
        <span class="alert-item-icon">🎯</span>
        <div class="alert-item-body">
          <div class="alert-item-title">${esc(a.ticker)} — ${condLabel(a)}</div>
          <div class="alert-item-sub">${a.note ? esc(a.note) + ' · ' : ''}Added ${a.created_at} · ID: ${a.id}</div>
        </div>
        <button class="alert-item-del" onclick="deleteAlert('${a.id}')" title="Delete alert">✕</button>
      </div>`).join('');
  }

  function renderFiredAlerts(items) {
    const sec  = document.getElementById('firedSection');
    const list = document.getElementById('firedAlertList');
    if (!items.length) { sec.style.display = 'none'; return; }
    sec.style.display = '';
    list.innerHTML = items.slice(0, 10).map(a => `
      <div class="alert-item fired">
        <span class="alert-item-icon">🔥</span>
        <div class="alert-item-body">
          <div class="alert-item-title">${esc(a.ticker)} — ${condLabel(a)}</div>
          <div class="alert-item-sub">Fired ${a.fired_at} @ $${fmt(a.fired_price)} · Signal: ${esc(a.signal) || '—'} · RSI: ${a.rsi || '—'}</div>
        </div>
      </div>`).join('');
  }

  function checkTriggeredAlerts(data) {
    const triggered = data.triggered_alerts || [];
    triggered.forEach(a => {
      const msg = `${a.ticker}: ${condLabel(a)} @ $${fmt(a.fired_price)}`;
      showToast('🔥', msg, 8000);
      _fireDesktopNotif(`🔥 Alert Fired — ${a.ticker}`, msg + (a.note ? `\\n${a.note}` : ''));
    });
    if (triggered.length) loadAlerts();
  }

  // ── Live price streaming (SSE) ───────────────────────────────────
  let _priceStream    = null;
  let _streamTicker   = null;
  let _streamTicks    = 0;
  let _lastStreamPrice = null;

  function connectPriceStream(ticker) {
    // Close any existing stream first
    if (_priceStream) {
      _priceStream.close();
      _priceStream = null;
    }
    _streamTicker    = ticker;
    _streamTicks     = 0;
    _lastStreamPrice = null;

    if (typeof EventSource === 'undefined') return;   // browser doesn't support SSE

    setLiveBadge('connecting');
    _priceStream = new EventSource('/api/stream/' + ticker + '?interval_s=15');

    _priceStream.onopen = () => setLiveBadge('live');

    _priceStream.onmessage = (evt) => {
      try {
        const d = JSON.parse(evt.data);
        if (d.error || d.ticker !== _streamTicker) return;
        _streamTicks++;
        updatePriceFromStream(d);
      } catch(e) { /* ignore parse errors */ }
    };

    _priceStream.onerror = () => {
      // EventSource auto-reconnects; just show the state
      setLiveBadge('reconnecting');
    };
  }

  function disconnectPriceStream() {
    if (_priceStream) { _priceStream.close(); _priceStream = null; }
    setLiveBadge('off');
  }

  function setLiveBadge(state) {
    const badge   = document.getElementById('liveBadge');
    const label   = document.getElementById('liveBadgeText');
    if (!badge) return;
    badge.className = 'live-badge' + (state === 'live' ? '' : ' disconnected');
    if      (state === 'live')        { label.textContent = 'LIVE'; }
    else if (state === 'connecting')  { label.textContent = 'connecting…'; }
    else if (state === 'reconnecting'){ label.textContent = 'reconnecting…'; }
    else                              { label.textContent = 'offline'; }
  }

  function updatePriceFromStream(d) {
    const priceEl = document.getElementById('priceValue');

    // Flash animation on price change
    const prev = _lastStreamPrice;
    if (prev !== null && d.price !== prev) {
      const cls = d.price > prev ? 'price-flash-up' : 'price-flash-down';
      priceEl.classList.remove('price-flash-up', 'price-flash-down');
      void priceEl.offsetWidth;   // force reflow to restart animation
      priceEl.classList.add(cls);
      setTimeout(() => priceEl.classList.remove(cls), 900);
    }
    _lastStreamPrice = d.price;

    // Update price display
    priceEl.textContent = '$' + Number(d.price).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 4});

    // Update day change % (this is day change, not period change from analysis)
    if (d.change_pct != null) {
      const cp = document.getElementById('priceChange');
      const up = d.change_pct >= 0;
      cp.textContent = (up ? '\\u25b2 +' : '\\u25bc ') + Math.abs(d.change_pct).toFixed(2) + '% (day)';
      cp.className   = 'price-change ' + (up ? 'up' : 'down');
    }

    // Update stream meta line
    document.getElementById('streamMeta').textContent =
      '\\u2022 Tick #' + _streamTicks + '  ·  Last: ' + d.ts + '  ·  Vol: ' +
      (d.volume ? Number(d.volume).toLocaleString() : '—');

    // Update day range bar
    if (d.day_high != null && d.day_low != null) {
      const wrap = document.getElementById('dayRangeWrap');
      wrap.style.display = '';
      document.getElementById('dayLow').textContent  = '$' + fmt(d.day_low);
      document.getElementById('dayHigh').textContent = '$' + fmt(d.day_high);
      const pct = Math.max(0, Math.min(100, d.pos_in_range));
      document.getElementById('dayRangeThumb').style.left = pct + '%';
      document.getElementById('dayRangeLabel').textContent =
        'Price is in the ' + pct.toFixed(0) + 'th percentile of today\\u2019s range';
    }
  }

  // ── Backtest ──────────────────────────────────────────────────────
  let _btPeriod   = '90d';
  let equityChart = null;

  function setBtPeriod(p, btn) {
    _btPeriod = p;
    document.querySelectorAll('.bt-period-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    loadBacktest();
  }

  async function loadBacktest() {
    const ticker = document.getElementById('tickerSelect').value;
    document.getElementById('btLoader').classList.add('active');
    try {
      const res = await fetch(`/api/backtest/${ticker}?interval=${currentInterval}&period=${_btPeriod}`);
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Error'); }
      const d = await res.json();
      renderBacktest(d);
    } catch(e) {
      showToast('❌', 'Backtest error: ' + e.message, 5000);
    } finally {
      document.getElementById('btLoader').classList.remove('active');
    }
  }

  function renderBacktest(d) {
    // ── Stat chips ────────────────────────────────────────────────
    const set = (id, val, cls) => {
      const el = document.getElementById(id);
      el.textContent = val;
      el.className   = 'bt-stat-value ' + cls;
    };

    const wr = d.win_rate;
    set('bt-trades',  d.total_trades,                     'neut');
    set('bt-winrate', wr + '%',                            wr >= 55 ? 'pos' : wr >= 45 ? 'warn' : 'neg');
    set('bt-pf',      d.profit_factor != null ? d.profit_factor.toFixed(2) : '—',
        d.profit_factor >= 1.5 ? 'pos' : d.profit_factor >= 1.0 ? 'warn' : 'neg');
    const ret = d.total_return_pct;
    set('bt-return',  (ret >= 0 ? '+' : '') + ret + '%',  ret >= 0 ? 'pos' : 'neg');
    set('bt-dd',      '-' + d.max_drawdown_pct + '%',     d.max_drawdown_pct > 20 ? 'neg' : d.max_drawdown_pct > 10 ? 'warn' : 'pos');
    set('bt-avgwin',  '+' + d.avg_win_pct + '%',          'pos');
    set('bt-avgloss', d.avg_loss_pct + '%',                'neg');
    set('bt-wl',      d.wins + ' / ' + d.losses,          d.wins >= d.losses ? 'pos' : 'neg');

    // ── Equity curve ──────────────────────────────────────────────
    const ctx = document.getElementById('equityChart').getContext('2d');
    if (equityChart) equityChart.destroy();

    const eq    = d.equity_curve || [1];
    const final = eq[eq.length - 1];
    const lineCol = final >= 1 ? '#A6E3A1' : '#F38BA8';
    const fillCol = final >= 1 ? 'rgba(166,227,161,.1)' : 'rgba(243,139,168,.1)';

    // Draw 1.0 baseline
    const baseline = new Array(eq.length).fill(1.0);

    equityChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: eq.map((_, i) => i),
        datasets: [
          { label: 'Baseline', data: baseline, borderColor: 'rgba(99,100,112,.4)', borderWidth: 1,
            borderDash: [4,3], pointRadius: 0, fill: false },
          { label: 'Equity', data: eq, borderColor: lineCol, borderWidth: 2,
            pointRadius: 0, fill: true, backgroundColor: fillCol, tension: 0.1 },
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: { duration: 500 },
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#313244', titleColor: '#CDD6F4', bodyColor: '#BAC2DE',
            borderColor: '#45475A', borderWidth: 1,
            callbacks: {
              title: () => '',
              label: ctx => {
                const v = ctx.raw;
                const pct = ((v - 1) * 100).toFixed(2);
                return 'Equity: ' + v.toFixed(4) + ' (' + (pct >= 0 ? '+' : '') + pct + '%)';
              }
            }
          }
        },
        scales: {
          x: { display: false },
          y: {
            ticks: { color: '#6C7086', font: { size: 10 },
                     callback: v => ((v - 1) * 100).toFixed(0) + '%' },
            grid: { color: 'rgba(49,50,68,.5)' }
          }
        }
      }
    });

    // ── Trade log ─────────────────────────────────────────────────
    const body = document.getElementById('btTradeBody');
    const log  = d.trade_log || [];
    if (!log.length) {
      body.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:16px;color:var(--muted)">No trades generated in this period</td></tr>';
      return;
    }
    body.innerHTML = [...log].reverse().map((t, idx) => {
      const cls = t.outcome === 'win' ? 'bt-win' : 'bt-loss';
      const sig = t.signal === 'STRONG BUY'
        ? '<span style="color:var(--green);font-weight:700">▲ BUY</span>'
        : '<span style="color:var(--red);font-weight:700">▼ SELL</span>';
      const dateShort = (t.date || '').slice(0, 16).replace('T', ' ');
      return `<tr>
        <td style="color:var(--muted)">${log.length - idx}</td>
        <td>${dateShort}</td>
        <td>${sig}</td>
        <td>$${fmt(t.entry)}</td>
        <td>$${fmt(t.exit)}</td>
        <td class="${cls}">${t.pnl_pct >= 0 ? '+' : ''}${t.pnl_pct}%</td>
        <td style="color:var(--muted)">${t.exit_reason}</td>
      </tr>`;
    }).join('');
  }

  // ── Kick off on load
  window.addEventListener('load', () => {
    const ticker = document.getElementById('tickerSelect').value;
    runAnalysis();
    loadChart();
    loadSR();
    loadWatchlist();
    loadMTF();
    loadAlerts();
    loadBacktest();
    connectPriceStream(ticker);
    // pre-fill ticker from selector
    document.getElementById('al-ticker').value = ticker;
    resetCountdown();
  });

  // Reconnect stream when tab becomes visible again
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && _streamTicker) {
      connectPriceStream(_streamTicker);
    }
  });
</script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("dashboard:app", host="0.0.0.0", port=8000, reload=True)
