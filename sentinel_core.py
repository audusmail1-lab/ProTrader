"""
Sentinel core — shared by the live scanner (sentinel.py) and the historical
replay (sentinel_replay.py), so a replay measures exactly what goes live.

  * CATALOGUE    every instrument Sentinel can read (the focus list picks)
  * fetch_candles closed candles from Deriv's public feed (same venue the
                  terminal quotes)
  * PaperBook    turns ARIA verdicts into paper positions and scores them in R
  * summarise    honest statistics: expectancy after costs, break-even win
                 rate, and whether the sample is big enough to mean anything

Paper-trade model (conservative on purpose):
  entry  = close of the bar ARIA judged (Sentinel only judges closed bars)
  stop   = ARIA stop (1.5 / 2.0 / 2.5 × ATR by MCC)      → −1 R
  target = ARIA TP2 (2.5 × stop distance), the level the terminal applies → +2.5 R
  a bar that touches both stop and target counts as a LOSS
  a trade still open after MAX_BARS closes at that bar's close
  every trade pays one estimated spread, converted to R
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

import sentinel_engine as eng

DERIV_WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"

TF_SEC = {"15m": 900, "1h": 3600, "4h": 14400}
WINDOW = 300          # bars ARIA sees per evaluation (the terminal loads 300)
MAX_BARS = 48         # paper trade time-out, in bars of its own timeframe
TARGET_R = 2.5        # TP2
BREAKEVEN_WINRATE = 1 / (1 + TARGET_R)   # 28.6 % before costs

# Paper-trading models. "7.2c" is the ARIA 7.2 CANDIDATE chosen from the
# 27 Sep 2026 research (research_exits.py): same ARIA 7.1 gates, but
#   • entries only when the last CLOSED 4h bar trends the same way
#     (close vs EMA20 vs EMA50), and never on a completed Elliott Wave 5
#   • exit: stop at -1R; once +1R is reached the stop trails 1R behind the
#     best price; no fixed target; out after 96 bars
# "fixed" is the original model (stop -1R, target +2.5R, 48 bars).
MODELS = {
    "fixed": dict(tp=TARGET_R, timeout=MAX_BARS, trail=None, arm=None, mtf=False, wave5_veto=False),
    "7.2c":  dict(tp=None, timeout=96, trail=1.0, arm=1.0, mtf=True, wave5_veto=True),
}
SENTINEL_MODEL = "7.2c"


def trend_series(h4: list[dict]) -> tuple[list[int], list[str]]:
    """Per 4h bar: its close time and 'up' / 'down' / 'flat' (EMA20/50 + close)."""
    closes = [c["close"] for c in h4]
    if not closes:
        return [], []
    e20, e50 = eng.calc_ema(closes, 20), eng.calc_ema(closes, 50)
    tr = []
    for i, c in enumerate(closes):
        if i < 60:
            tr.append("flat")
        elif c > e20[i] > e50[i]:
            tr.append("up")
        elif c < e20[i] < e50[i]:
            tr.append("down")
        else:
            tr.append("flat")
    return [c["time"] + TF_SEC["4h"] for c in h4], tr


def trend_at(close_times: list[int], trends: list[str], t: int) -> str:
    """Trend of the last 4h bar that had closed by time t — never looks ahead."""
    import bisect
    k = bisect.bisect_right(close_times, t) - 1
    return trends[k] if k >= 0 else "flat"


@dataclass(frozen=True)
class Market:
    id: str            # terminal id (what the chart uses)
    deriv: str         # Deriv feed symbol
    label: str
    group: str         # the terminal's market group, e.g. "Forex Major", "Boom"
    mode: str          # "real" | "synthetic"
    spread: float      # estimated round-trip cost in price units (abs) …
    spread_pct: float = 0.0   # … or as a fraction of price


# Every instrument the terminal lists and Deriv's public feed serves (89,
# checked 27 Sep 2026). Sentinel reads only the trader's FOCUS list from
# these — see sentinel.py — capped so each 15-minute cycle stays fast.
#
# Spreads are ESTIMATES for Deriv MT5 and err on the wide side. Replace them
# with the real contract specs from the MT5 bridge ("spec" command) before
# trusting any small edge. Synthetic indices get full signals but carry a
# "Synthetic" label: earlier validation and the replay found ~0R on them.
CATALOGUE: list[Market] = [
    # Forex Major
    Market("frxEURUSD", "frxEURUSD", "EUR/USD", "Forex Major", "real", 0.00012),
    Market("frxGBPUSD", "frxGBPUSD", "GBP/USD", "Forex Major", "real", 0.00018),
    Market("frxUSDJPY", "frxUSDJPY", "USD/JPY", "Forex Major", "real", 0.018),
    Market("frxAUDUSD", "frxAUDUSD", "AUD/USD", "Forex Major", "real", 0.0, 0.00012),
    Market("frxUSDCAD", "frxUSDCAD", "USD/CAD", "Forex Major", "real", 0.0, 0.00012),
    Market("frxUSDCHF", "frxUSDCHF", "USD/CHF", "Forex Major", "real", 0.0, 0.00012),
    Market("frxEURGBP", "frxEURGBP", "EUR/GBP", "Forex Major", "real", 0.0, 0.00012),
    Market("frxEURJPY", "frxEURJPY", "EUR/JPY", "Forex Major", "real", 0.0, 0.00012),
    Market("frxGBPJPY", "frxGBPJPY", "GBP/JPY", "Forex Major", "real", 0.0, 0.00012),
    Market("frxAUDJPY", "frxAUDJPY", "AUD/JPY", "Forex Major", "real", 0.0, 0.00012),
    Market("frxEURAUD", "frxEURAUD", "EUR/AUD", "Forex Major", "real", 0.0, 0.00012),
    Market("frxEURCAD", "frxEURCAD", "EUR/CAD", "Forex Major", "real", 0.0, 0.00012),
    Market("frxEURCHF", "frxEURCHF", "EUR/CHF", "Forex Major", "real", 0.0, 0.00012),
    Market("frxGBPAUD", "frxGBPAUD", "GBP/AUD", "Forex Major", "real", 0.0, 0.00012),
    # Forex Minor
    Market("frxAUDCAD", "frxAUDCAD", "AUD/CAD", "Forex Minor", "real", 0.0, 0.0002),
    Market("frxAUDCHF", "frxAUDCHF", "AUD/CHF", "Forex Minor", "real", 0.0, 0.0002),
    Market("frxAUDNZD", "frxAUDNZD", "AUD/NZD", "Forex Minor", "real", 0.0, 0.0002),
    Market("frxEURNZD", "frxEURNZD", "EUR/NZD", "Forex Minor", "real", 0.0, 0.0002),
    Market("frxGBPCAD", "frxGBPCAD", "GBP/CAD", "Forex Minor", "real", 0.0, 0.0002),
    Market("frxGBPCHF", "frxGBPCHF", "GBP/CHF", "Forex Minor", "real", 0.0, 0.0002),
    Market("frxGBPNZD", "frxGBPNZD", "GBP/NZD", "Forex Minor", "real", 0.0, 0.0002),
    Market("frxNZDJPY", "frxNZDJPY", "NZD/JPY", "Forex Minor", "real", 0.0, 0.0002),
    Market("frxNZDUSD", "frxNZDUSD", "NZD/USD", "Forex Minor", "real", 0.0, 0.0002),
    Market("frxUSDMXN", "frxUSDMXN", "USD/MXN", "Forex Minor", "real", 0.0, 0.0003),
    Market("frxUSDPLN", "frxUSDPLN", "USD/PLN", "Forex Minor", "real", 0.0, 0.0003),
    # Metals
    Market("frxXAUUSD", "frxXAUUSD", "XAU/USD", "Metals", "real", 0.4),
    Market("frxXAGUSD", "frxXAGUSD", "XAG/USD", "Metals", "real", 0.0, 0.0005),
    Market("frxXPTUSD", "frxXPTUSD", "XPT/USD", "Metals", "real", 0.0, 0.0005),
    Market("frxXPDUSD", "frxXPDUSD", "XPD/USD", "Metals", "real", 0.0, 0.0005),
    # Crypto
    Market("cryBTCUSD", "cryBTCUSD", "BTC/USD", "Crypto", "real", 30.0),
    Market("cryETHUSD", "cryETHUSD", "ETH/USD", "Crypto", "real", 0.0, 0.0005),
    # Indices
    Market("frxNAS100", "OTC_NDX", "US Tech 100", "Indices", "real", 1.8),
    Market("frxSPX500", "OTC_SPC", "US 500", "Indices", "real", 0.0, 0.0001),
    Market("frxUS30", "OTC_DJI", "Wall Street 30", "Indices", "real", 0.0, 0.0001),
    Market("OTC_FTSE", "OTC_FTSE", "UK 100", "Indices", "real", 0.0, 0.0001),
    Market("OTC_GDAXI", "OTC_GDAXI", "Germany 40", "Indices", "real", 0.0, 0.0001),
    Market("OTC_FCHI", "OTC_FCHI", "France 40", "Indices", "real", 0.0, 0.0001),
    Market("OTC_SX5E", "OTC_SX5E", "Euro 50", "Indices", "real", 0.0, 0.0001),
    Market("OTC_AEX", "OTC_AEX", "Netherlands 25", "Indices", "real", 0.0, 0.0001),
    Market("OTC_SSMI", "OTC_SSMI", "Swiss 20", "Indices", "real", 0.0, 0.0001),
    Market("OTC_N225", "OTC_N225", "Japan 225", "Indices", "real", 0.0, 0.0001),
    Market("OTC_HSI", "OTC_HSI", "Hong Kong 50", "Indices", "real", 0.0, 0.0001),
    Market("OTC_AS51", "OTC_AS51", "Australia 200", "Indices", "real", 0.0, 0.0001),
    # Volatility
    Market("R_10", "R_10", "Vol 10", "Volatility", "synthetic", 0.0, 0.0002),
    Market("R_25", "R_25", "Vol 25", "Volatility", "synthetic", 0.0, 0.0002),
    Market("R_50", "R_50", "Vol 50", "Volatility", "synthetic", 0.0, 0.0002),
    Market("R_75", "R_75", "Vol 75", "Volatility", "synthetic", 0.0, 0.0002),
    Market("R_100", "R_100", "Vol 100", "Volatility", "synthetic", 0.0, 0.0002),
    # Volatility (1s)
    Market("1HZ10V", "1HZ10V", "Vol 10 (1s)", "Volatility (1s)", "synthetic", 0.0, 0.0002),
    Market("1HZ15V", "1HZ15V", "Vol 15 (1s)", "Volatility (1s)", "synthetic", 0.0, 0.0002),
    Market("1HZ25V", "1HZ25V", "Vol 25 (1s)", "Volatility (1s)", "synthetic", 0.0, 0.0002),
    Market("1HZ30V", "1HZ30V", "Vol 30 (1s)", "Volatility (1s)", "synthetic", 0.0, 0.0002),
    Market("1HZ50V", "1HZ50V", "Vol 50 (1s)", "Volatility (1s)", "synthetic", 0.0, 0.0002),
    Market("1HZ75V", "1HZ75V", "Vol 75 (1s)", "Volatility (1s)", "synthetic", 0.0, 0.0002),
    Market("1HZ90V", "1HZ90V", "Vol 90 (1s)", "Volatility (1s)", "synthetic", 0.0, 0.0002),
    Market("1HZ100V", "1HZ100V", "Vol 100 (1s)", "Volatility (1s)", "synthetic", 0.0, 0.0002),
    # Crash
    Market("CRASH50", "CRASH50", "Crash 50", "Crash", "synthetic", 0.0, 0.0003),
    Market("CRASH150N", "CRASH150N", "Crash 150", "Crash", "synthetic", 0.0, 0.0003),
    Market("CRASH300N", "CRASH300N", "Crash 300", "Crash", "synthetic", 0.0, 0.0003),
    Market("CRASH500", "CRASH500", "Crash 500", "Crash", "synthetic", 0.0, 0.0003),
    Market("CRASH600", "CRASH600", "Crash 600", "Crash", "synthetic", 0.0, 0.0003),
    Market("CRASH900", "CRASH900", "Crash 900", "Crash", "synthetic", 0.0, 0.0003),
    Market("CRASH1000", "CRASH1000", "Crash 1000", "Crash", "synthetic", 0.0, 0.0003),
    # Boom
    Market("BOOM50", "BOOM50", "Boom 50", "Boom", "synthetic", 0.0, 0.0003),
    Market("BOOM150N", "BOOM150N", "Boom 150", "Boom", "synthetic", 0.0, 0.0003),
    Market("BOOM300N", "BOOM300N", "Boom 300", "Boom", "synthetic", 0.0, 0.0003),
    Market("BOOM500", "BOOM500", "Boom 500", "Boom", "synthetic", 0.0, 0.0003),
    Market("BOOM600", "BOOM600", "Boom 600", "Boom", "synthetic", 0.0, 0.0003),
    Market("BOOM900", "BOOM900", "Boom 900", "Boom", "synthetic", 0.0, 0.0003),
    Market("BOOM1000", "BOOM1000", "Boom 1000", "Boom", "synthetic", 0.0, 0.0003),
    # Jump
    Market("JD10", "JD10", "Jump 10", "Jump", "synthetic", 0.0, 0.0002),
    Market("JD25", "JD25", "Jump 25", "Jump", "synthetic", 0.0, 0.0002),
    Market("JD50", "JD50", "Jump 50", "Jump", "synthetic", 0.0, 0.0002),
    Market("JD75", "JD75", "Jump 75", "Jump", "synthetic", 0.0, 0.0002),
    Market("JD100", "JD100", "Jump 100", "Jump", "synthetic", 0.0, 0.0002),
    # Step
    Market("stpRNG", "stpRNG", "Step 100", "Step", "synthetic", 0.0, 0.0002),
    Market("stpRNG2", "stpRNG2", "Step 200", "Step", "synthetic", 0.0, 0.0002),
    Market("stpRNG3", "stpRNG3", "Step 300", "Step", "synthetic", 0.0, 0.0002),
    Market("stpRNG4", "stpRNG4", "Step 400", "Step", "synthetic", 0.0, 0.0002),
    Market("stpRNG5", "stpRNG5", "Step 500", "Step", "synthetic", 0.0, 0.0002),
    # Range Break
    Market("RB100", "RB100", "Range Break 100", "Range Break", "synthetic", 0.0, 0.0002),
    Market("RB200", "RB200", "Range Break 200", "Range Break", "synthetic", 0.0, 0.0002),
    # Daily Reset
    Market("RDBULL", "RDBULL", "Bull Market", "Daily Reset", "synthetic", 0.0, 0.0002),
    Market("RDBEAR", "RDBEAR", "Bear Market", "Daily Reset", "synthetic", 0.0, 0.0002),
    # Baskets
    Market("WLDUSD", "WLDUSD", "USD Basket", "Baskets", "synthetic", 0.0, 0.0002),
    Market("WLDEUR", "WLDEUR", "EUR Basket", "Baskets", "synthetic", 0.0, 0.0002),
    Market("WLDGBP", "WLDGBP", "GBP Basket", "Baskets", "synthetic", 0.0, 0.0002),
    Market("WLDAUD", "WLDAUD", "AUD Basket", "Baskets", "synthetic", 0.0, 0.0002),
    Market("WLDXAU", "WLDXAU", "Gold Basket", "Baskets", "synthetic", 0.0, 0.0002),
]
MARKETS = CATALOGUE   # backwards-compatible name
DEFAULT_FOCUS = ["frxNAS100", "cryBTCUSD", "frxXAUUSD", "frxEURUSD", "frxGBPUSD", "frxUSDJPY", "R_75", "1HZ75V"]
MARKET_BY_ID = {m.id: m for m in MARKETS}


# Spreads measured on the trader's own MT5 account (via the bridge "spec"
# command), as a fraction of price: {market_id: pct}. When present they
# replace the estimates below. Filled by sentinel.py from its journal DB.
MEASURED_SPREAD_PCT: dict[str, float] = {}


def estimated_spread(m: Market, price: float) -> float:
    return m.spread if m.spread > 0 else price * m.spread_pct


def spread_for(m: Market, price: float) -> float:
    pct = MEASURED_SPREAD_PCT.get(m.id)
    return price * pct if pct else estimated_spread(m, price)


# ── Data ─────────────────────────────────────────────────────────────────────

async def fetch_candles(deriv_sym: str, tf: str, count: int = WINDOW, *,
                        now: Optional[float] = None, pages_back: int = 0) -> list[dict]:
    """
    Closed candles, oldest first. Deriv returns at most ~1000 per request, so
    `pages_back` > 0 walks further back for a replay. The forming bar is
    dropped: Sentinel judges closed candles only (Law 7).
    """
    import websockets  # imported here so the engine has no network dependency

    gran = TF_SEC[tf]
    now = now or time.time()
    out: list[dict] = []
    end: Any = "latest"
    async with websockets.connect(DERIV_WS_URL, max_size=2 ** 24, open_timeout=15) as ws:
        for _ in range(pages_back + 1):
            await ws.send(json.dumps({"ticks_history": deriv_sym, "adjust_start_time": 1,
                                      "count": min(count, 5000), "end": end,
                                      "granularity": gran, "style": "candles"}))
            msg = json.loads(await asyncio.wait_for(ws.recv(), 20))
            if msg.get("error"):
                raise RuntimeError(f"{deriv_sym}: {msg['error'].get('message')}")
            page = [{"time": int(c["epoch"]), "open": float(c["open"]), "high": float(c["high"]),
                     "low": float(c["low"]), "close": float(c["close"])} for c in msg.get("candles", [])]
            # Deriv serves about one year; past that it wraps back to the
            # newest bars. Stop as soon as a page is not strictly older.
            if not page or (out and page[-1]["time"] >= out[0]["time"]):
                break
            out = page + out
            end = str(page[0]["time"] - 1)
    # de-duplicate on time, keep order, drop the bar that has not closed yet
    seen, clean = set(), []
    for c in sorted(out, key=lambda x: x["time"]):
        if c["time"] in seen:
            continue
        seen.add(c["time"])
        clean.append(c)
    return [c for c in clean if c["time"] + gran <= now]


def bar_close_hour(c: dict, tf: str) -> int:
    return time.gmtime(c["time"] + TF_SEC[tf]).tm_hour


# ── Paper book ───────────────────────────────────────────────────────────────

@dataclass
class Trade:
    id: str
    market: str
    tf: str
    mode: str
    tier: str              # "exec" (≥9/10) | "qualified" (8/10) under ARIA 7.1
    dir: str
    opened_at: int         # epoch of the signal bar's close
    entry: float
    sl: float
    tp1: float
    tp2: float
    sl_dist: float
    cost_r: float
    score: int
    gates: list
    mcc: str
    wyckoff: str
    pattern: Optional[str]
    rsi: Optional[float]
    status: str = "open"   # open | win | loss | timeout
    closed_at: Optional[int] = None
    exit: Optional[float] = None
    r: Optional[float] = None         # net of cost
    bars: int = 0
    tp1_hit: bool = False
    mfe_r: float = 0.0
    mae_r: float = 0.0
    last_bar: int = 0
    engine: str = "7.0"            # ARIA rule version that produced the signal
    fib_r: Optional[float] = None  # Fibonacci retracement of the last swing (when the gate passed)
    atr_ratio: Optional[float] = None
    elliott: Optional[str] = None  # soft Elliott label, context only
    ew_aligned: Optional[bool] = None  # Elliott direction agrees with the trade
    model: str = "fixed"           # paper-trading model (see MODELS)
    stop: Optional[float] = None   # current stop (moves when trailing)
    best_r: float = 0.0            # best excursion used for trailing, in R
    trend_4h: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class PaperBook:
    """One open paper position per market × timeframe, like a disciplined trader."""

    def __init__(self, news_week: bool = False, model: str = "fixed"):
        self.news_week = news_week
        self.model = model
        self.open: dict[tuple[str, str], Trade] = {}
        self.closed: list[Trade] = []

    # Advance every open trade on (market, tf) through bars newer than it has seen.
    def update(self, market: str, tf: str, bars: list[dict]) -> list[Trade]:
        t = self.open.get((market, tf))
        if not t:
            return []
        if MODELS.get(t.model, {}).get("trail"):
            return self._update_trailing(t, tf, bars)
        sign = 1 if t.dir == "buy" else -1
        for b in bars:
            if b["time"] <= t.last_bar:
                continue
            t.last_bar = b["time"]
            t.bars += 1
            fav = (b["high"] - t.entry) if sign > 0 else (t.entry - b["low"])
            adv = (t.entry - b["low"]) if sign > 0 else (b["high"] - t.entry)
            t.mfe_r = max(t.mfe_r, fav / t.sl_dist)
            t.mae_r = max(t.mae_r, adv / t.sl_dist)
            hit_sl = b["low"] <= t.sl if sign > 0 else b["high"] >= t.sl
            hit_tp = b["high"] >= t.tp2 if sign > 0 else b["low"] <= t.tp2
            if (b["high"] >= t.tp1 if sign > 0 else b["low"] <= t.tp1):
                t.tp1_hit = True
            close_at = b["time"] + TF_SEC[tf]
            if hit_sl:                     # stop first when both touch
                self._close(t, "loss", t.sl, -1.0, close_at)
            elif hit_tp:
                self._close(t, "win", t.tp2, TARGET_R, close_at)
            elif t.bars >= MAX_BARS:
                gross = sign * (b["close"] - t.entry) / t.sl_dist
                self._close(t, "timeout", b["close"], gross, close_at)
            if t.status != "open":
                return [t]
        return []

    def _update_trailing(self, t: Trade, tf: str, bars: list[dict]) -> list[Trade]:
        """Trailing model — mirrors research_exits.simulate() bar for bar."""
        cfg = MODELS[t.model]
        s = 1 if t.dir == "buy" else -1
        if t.stop is None:
            t.stop = t.sl
        for b in bars:
            if b["time"] <= t.last_bar:
                continue
            t.last_bar = b["time"]
            t.bars += 1
            lo_r = s * ((b["low"] if s > 0 else b["high"]) - t.entry) / t.sl_dist
            hi_r = s * ((b["high"] if s > 0 else b["low"]) - t.entry) / t.sl_dist
            t.mfe_r = max(t.mfe_r, hi_r)
            t.mae_r = max(t.mae_r, -lo_r)
            if hi_r >= 1.5:
                t.tp1_hit = True
            close_at = b["time"] + TF_SEC[tf]
            stop_r = s * (t.stop - t.entry) / t.sl_dist
            if lo_r <= stop_r:                                  # stop first
                self._close(t, "win" if stop_r > 0 else "loss", t.stop, stop_r, close_at)
                return [t]
            t.best_r = max(t.best_r, hi_r)
            if t.best_r >= cfg["arm"]:
                cand = t.entry + s * t.sl_dist * (t.best_r - cfg["trail"])
                if (s > 0 and cand > t.stop) or (s < 0 and cand < t.stop):
                    t.stop = cand
            if t.bars >= cfg["timeout"]:
                gross = s * (b["close"] - t.entry) / t.sl_dist
                self._close(t, "timeout", b["close"], gross, close_at)
                return [t]
        return []

    def _close(self, t: Trade, status: str, px: float, gross_r: float, at: int) -> None:
        t.status, t.exit, t.closed_at = status, px, at
        t.r = round(gross_r - t.cost_r, 4)
        self.open.pop((t.market, t.tf), None)
        self.closed.append(t)

    # Judge the newest closed bar; open a paper trade if ARIA says so.
    def consider(self, m: Market, tf: str, window: list[dict],
                 allow_open: bool = True, trend_4h: Optional[str] = None) -> tuple[Optional[dict], Optional[Trade]]:
        last = window[-1]
        read = eng.evaluate(window, m.id, bar_close_hour(last, tf), self.news_week)
        if not read:
            return read, None
        cfg = MODELS[self.model]
        want = "up" if read["dir"] == "buy" else "down"
        read["trend_4h"] = trend_4h
        read["block"] = None
        if cfg["mtf"] and trend_4h != want:
            read["block"] = "4h trend " + ("flat" if trend_4h in (None, "flat") else "against")
        elif cfg["wave5_veto"] and (read["elliott"]["label"] or "").startswith("Wave 5"):
            read["block"] = "Wave 5 exhaustion"
        if not allow_open or (m.id, tf) in self.open or read["block"]:
            return read, None
        tier = {"EXEC_READY": "exec", "QUALIFIED": "qualified"}.get(read["verdict"])
        if not tier or not (read["sl_dist"] > 0):
            return read, None
        cost = spread_for(m, read["entry"]) / read["sl_dist"]
        t = Trade(
            id=f"{m.id}-{tf}-{last['time']}", market=m.id, tf=tf, mode=m.mode, tier=tier,
            dir=read["dir"], opened_at=last["time"] + TF_SEC[tf], entry=read["entry"],
            sl=read["sl"], tp1=read["tp1"], tp2=read["tp2"], sl_dist=read["sl_dist"],
            cost_r=round(cost, 4), score=read["score"], gates=read["gates"], mcc=read["mcc"],
            wyckoff=read["wyckoff"], pattern=read["pattern"], rsi=read["rsi"], last_bar=last["time"],
            engine=read["engine"], fib_r=read["fib_r"], atr_ratio=round(read["atr_ratio"], 3),
            elliott=read["elliott"]["label"],
            ew_aligned=(None if not read["elliott"]["dir"]
                        else read["elliott"]["dir"] == ("up" if read["dir"] == "buy" else "down")),
            model=self.model, stop=read["sl"], trend_4h=trend_4h,
        )
        self.open[(m.id, tf)] = t
        return read, t


# ── Statistics ───────────────────────────────────────────────────────────────

def _binom_p_at_least(k: int, n: int, p: float) -> float:
    """P(X ≥ k) for X ~ Binomial(n, p). Exact, via log-space terms."""
    if n == 0:
        return 1.0
    tot = 0.0
    for i in range(k, n + 1):
        lg = math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
        tot += math.exp(lg + i * math.log(p) + (n - i) * math.log(1 - p))
    return min(1.0, tot)


def summarise(trades: list[dict]) -> dict[str, Any]:
    """Win rate, expectancy (net R/trade), and how much to believe it."""
    done = [t for t in trades if t.get("status") in ("win", "loss", "timeout")]
    n = len(done)
    if not n:
        return {"n": 0}
    rs = [t["r"] for t in done]
    wins = sum(1 for t in done if t["status"] == "win")
    exp = sum(rs) / n
    sd = (sum((r - exp) ** 2 for r in rs) / (n - 1)) ** 0.5 if n > 1 else 0.0
    se = sd / n ** 0.5 if n > 1 else float("inf")
    # Profit factor and max drawdown in R, in time order.
    gains = sum(r for r in rs if r > 0)
    losses = -sum(r for r in rs if r < 0)
    eq = peak = dd = 0.0
    for t in sorted(done, key=lambda x: x["closed_at"] or 0):
        eq += t["r"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    decided = [t for t in done if t["status"] in ("win", "loss")]
    k = sum(1 for t in decided if t["status"] == "win")
    return {
        "n": n, "wins": wins, "win_rate": round(wins / n, 4),
        "breakeven_win_rate": round(BREAKEVEN_WINRATE, 4),
        "expectancy_r": round(exp, 4), "ci95_r": [round(exp - 1.96 * se, 4), round(exp + 1.96 * se, 4)] if n > 1 else None,
        "se_r": round(se, 5) if n > 1 else None,
        "total_r": round(sum(rs), 2), "profit_factor": round(gains / losses, 3) if losses else None,
        "max_drawdown_r": round(dd, 2), "avg_cost_r": round(sum(t["cost_r"] for t in done) / n, 4),
        "timeouts": sum(1 for t in done if t["status"] == "timeout"),
        # Chance of this many wins or more if the real hit rate were break-even.
        "p_vs_breakeven": round(_binom_p_at_least(k, len(decided), BREAKEVEN_WINRATE), 4) if decided else None,
        "verdict": _verdict(n, exp, se),
    }


def _verdict(n: int, exp: float, se: float) -> str:
    if n < 30:
        return "too few trades to judge"
    lo = exp - 1.96 * se
    if lo > 0:
        return "positive edge (95% interval above zero)"
    if exp + 1.96 * se < 0:
        return "negative edge (95% interval below zero)"
    return "no proven edge yet (interval includes zero)"


def group_stats(trades: list[dict], key) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for t in trades:
        groups.setdefault(str(key(t)), []).append(t)
    return {k: summarise(v) for k, v in sorted(groups.items())}


def z_for(tests: int, alpha: float = 0.05) -> float:
    """Two-sided critical value with a Bonferroni correction for `tests` slices.
    1 slice → 1.96; 12 → 2.87; 24 → 3.08. Testing many markets at once makes
    a lucky streak likely somewhere, so each one must clear a higher bar."""
    from statistics import NormalDist
    return NormalDist().inv_cdf(1 - alpha / (2 * max(1, tests)))


def edge_status(s: dict, tests: int, min_n: int) -> str:
    """proven / negative / unproven for one slice, corrected for `tests` slices."""
    n, se = s.get("n", 0), s.get("se_r")
    if n < min_n or not se:
        return "unproven"
    z = z_for(tests)
    if s["expectancy_r"] - z * se > 0:
        return "proven"
    if s["expectancy_r"] + z * se < 0:
        return "negative"
    return "unproven"
