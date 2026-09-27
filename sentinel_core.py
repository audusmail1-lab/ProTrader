"""
Sentinel core — shared by the live scanner (sentinel.py) and the historical
replay (sentinel_replay.py), so a replay measures exactly what goes live.

  * MARKETS      which instruments Sentinel watches, and in which mode
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


@dataclass(frozen=True)
class Market:
    id: str            # terminal id (what the chart uses)
    deriv: str         # Deriv feed symbol
    label: str
    mode: str          # "live-eligible" | "research"
    spread: float      # estimated round-trip cost in price units (abs) …
    spread_pct: float = 0.0   # … or as a fraction of price (synthetics)


# Spreads are ESTIMATES for Deriv MT5 and err on the wide side. Replace them
# with the real contract specs from the MT5 bridge ("spec" command) before
# trusting any small edge.
MARKETS: list[Market] = [
    Market("frxNAS100", "OTC_NDX",   "US Tech 100", "live-eligible", 1.8),
    Market("cryBTCUSD", "cryBTCUSD", "BTC/USD",     "live-eligible", 30.0),
    Market("frxXAUUSD", "frxXAUUSD", "XAU/USD",     "live-eligible", 0.40),
    Market("frxEURUSD", "frxEURUSD", "EUR/USD",     "live-eligible", 0.00012),
    Market("frxGBPUSD", "frxGBPUSD", "GBP/USD",     "live-eligible", 0.00018),
    Market("frxUSDJPY", "frxUSDJPY", "USD/JPY",     "live-eligible", 0.018),
    # Synthetics: earlier validation found no directional edge on these, so
    # Sentinel only collects evidence on them. They never alert as tradeable.
    Market("R_75",   "R_75",   "Vol 75",      "research", 0.0, 0.0002),
    Market("1HZ75V", "1HZ75V", "Vol 75 (1s)", "research", 0.0, 0.0002),
]
MARKET_BY_ID = {m.id: m for m in MARKETS}


def spread_for(m: Market, price: float) -> float:
    return m.spread if m.spread > 0 else price * m.spread_pct


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
    tier: str              # "exec" (≥8/9) | "qualified" (7/9)
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

    def to_dict(self) -> dict:
        return asdict(self)


class PaperBook:
    """One open paper position per market × timeframe, like a disciplined trader."""

    def __init__(self, news_week: bool = False):
        self.news_week = news_week
        self.open: dict[tuple[str, str], Trade] = {}
        self.closed: list[Trade] = []

    # Advance every open trade on (market, tf) through bars newer than it has seen.
    def update(self, market: str, tf: str, bars: list[dict]) -> list[Trade]:
        t = self.open.get((market, tf))
        if not t:
            return []
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

    def _close(self, t: Trade, status: str, px: float, gross_r: float, at: int) -> None:
        t.status, t.exit, t.closed_at = status, px, at
        t.r = round(gross_r - t.cost_r, 4)
        self.open.pop((t.market, t.tf), None)
        self.closed.append(t)

    # Judge the newest closed bar; open a paper trade if ARIA says so.
    def consider(self, m: Market, tf: str, window: list[dict],
                 allow_open: bool = True) -> tuple[Optional[dict], Optional[Trade]]:
        last = window[-1]
        read = eng.evaluate(window, m.id, bar_close_hour(last, tf), self.news_week)
        if not read or not allow_open or (m.id, tf) in self.open:
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
