"""
ARIA v7.1 engine — Python port for Sentinel.

This is a line-for-line port of the ARIA functions in protrader_mobile.html
(calcEMA/RSI/MACD/Stoch/ATR, ariaMCC, ariaWyckoff, ariaGates, ariaVerdict,
ariaEntry and the pattern scanner). The server-side scanner must reach the
same verdict the terminal shows, so any change to the JS engine has to be
mirrored here. tests/test_sentinel_parity.py runs the original JS and this
module on the same candles and fails if they disagree.

Deliberate differences from the terminal (documented, not accidental):
  * The caller decides which candles to pass. Sentinel passes CLOSED candles
    only (Law 7 — Confirmation Law); the terminal evaluates the forming one.
  * ariaMCC takes the UTC hour as an argument instead of reading the clock,
    so a historical replay classifies the dead zone by the bar's own time.

Candles are dicts: {"time", "open", "high", "low", "close"}.
"""

from __future__ import annotations

import math
from typing import Any, Optional

Candle = dict[str, float]

# ARIA v7.1 gate settings — identical to the constants in protrader_mobile.html.
ENGINE_VERSION = "7.1"
GATE_COUNT = 10
EXEC_MIN, QUAL_MIN, WAIT_MIN = 9, 8, 6
ATR_BAND = (0.6, 1.8)
PATTERN_RECENT = 3
FIB_ZONE = (0.45, 0.668)
FIB_RECENT = 5
FIB_MIN_LEG_ATR = 3
FIB_WINDOW = 60


def js_round(x: float) -> int:
    """JavaScript Math.round: halves round toward +infinity."""
    return math.floor(x + 0.5)


def _gt(a: Optional[float], b: float) -> bool:
    return a is not None and a > b


def _lt(a: Optional[float], b: float) -> bool:
    return a is not None and a < b


# ── Indicators (mirror calcEMA … calcATR) ────────────────────────────────────

def calc_ema(arr: list[float], p: int) -> list[float]:
    k = 2 / (p + 1)
    e = arr[0]
    out = []
    for v in arr:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def calc_sma(arr: list[Optional[float]], p: int) -> list[Optional[float]]:
    out: list[Optional[float]] = []
    for i, v in enumerate(arr):
        if i < p - 1:
            out.append(None)
            continue
        out.append(sum(arr[i - p + 1:i + 1]) / p)
    return out


def calc_rsi(closes: list[float], p: int = 14) -> list[Optional[float]]:
    chg = [c - closes[i] for i, c in enumerate(closes[1:])]
    out: list[Optional[float]] = [None] * p
    ag = sum(x for x in chg[:p] if x > 0) / p
    al = sum(abs(x) for x in chg[:p] if x < 0) / p
    out.append(100 if al == 0 else 100 - 100 / (1 + ag / al))
    for i in range(p, len(chg)):
        g = chg[i] if chg[i] > 0 else 0
        l = abs(chg[i]) if chg[i] < 0 else 0
        ag = (ag * (p - 1) + g) / p
        al = (al * (p - 1) + l) / p
        out.append(100 if al == 0 else 100 - 100 / (1 + ag / al))
    return out


def calc_macd(closes: list[float]) -> dict[str, list[float]]:
    e12, e26 = calc_ema(closes, 12), calc_ema(closes, 26)
    line = [a - b for a, b in zip(e12, e26)]
    sig = calc_ema(line, 9)
    return {"line": line, "sig": sig}


def calc_stoch(cdles: list[Candle], k: int = 14, d: int = 3) -> dict[str, list[Optional[float]]]:
    k_arr: list[Optional[float]] = []
    for i in range(len(cdles)):
        if i < k - 1:
            k_arr.append(None)
            continue
        sl = cdles[i - k + 1:i + 1]
        hi = max(c["high"] for c in sl)
        lo = min(c["low"] for c in sl)
        k_arr.append(50 if hi == lo else (cdles[i]["close"] - lo) / (hi - lo) * 100)
    d_arr: list[Optional[float]] = []
    for i in range(len(k_arr)):
        sl = [v for v in k_arr[max(0, i - d + 1):i + 1] if v is not None]
        d_arr.append(sum(sl) / d if len(sl) == d else None)
    return {"k": k_arr, "d": d_arr}


def calc_atr(cdles: list[Candle], p: int = 14) -> list[Optional[float]]:
    trs = []
    for i, c in enumerate(cdles):
        if i == 0:
            trs.append(c["high"] - c["low"])
            continue
        prev = cdles[i - 1]["close"]
        trs.append(max(c["high"] - c["low"], abs(c["high"] - prev), abs(c["low"] - prev)))
    return calc_sma(trs, p)


# ── ARIA layers ──────────────────────────────────────────────────────────────

def aria_mcc(cdles, closes, ema20v, ema50v, atrv, utc_hour: int) -> dict[str, str]:
    n = len(closes)
    last, e20, e50 = closes[n - 1], ema20v[n - 1], ema50v[n - 1]
    atr = atrv[n - 1] or last * 0.002
    if 2 <= utc_hour < 6:
        return {"code": "DEAD_ZONE", "label": "Dead Zone"}
    is_up = last > e20 and last > e50 and e20 > e50
    is_dn = last < e20 and last < e50 and e20 < e50
    r_atr = [v for v in atrv[-20:] if v]
    avg_atr = sum(r_atr) / len(r_atr) if r_atr else atr
    is_vol = atr > avg_atr * 2
    prev_hi, prev_lo = max(closes[-15:-1]), min(closes[-15:-1])
    lc = cdles[n - 1]
    is_fk = (lc["high"] > prev_hi and lc["close"] < prev_hi) or (lc["low"] < prev_lo and lc["close"] > prev_lo)
    hi20, lo20 = max(closes[-20:]), min(closes[-20:])
    is_rng = (hi20 - lo20) < atr * 3.5 and not is_up and not is_dn
    if is_fk:
        return {"code": "FAKE_BREAK", "label": "Fake Break"}
    if is_vol:
        return {"code": "VOLATILE", "label": "Volatile"}
    if is_up:
        return {"code": "TREND_UP", "label": "Trend ↑"}
    if is_dn:
        return {"code": "TREND_DOWN", "label": "Trend ↓"}
    if is_rng:
        return {"code": "RANGING", "label": "Ranging"}
    return {"code": "TRANSITION", "label": "Transition"}


def aria_wyckoff(cdles, closes, ema20v, ema50v) -> str:
    n = len(closes)
    last, e20, e50 = closes[n - 1], ema20v[n - 1], ema50v[n - 1]
    w = closes[-min(50, n):]
    hi50, lo50 = max(w), min(w)
    pos = (last - lo50) / ((hi50 - lo50) or 1)
    bod = [abs(c["close"] - c["open"]) for c in cdles[-10:]]
    avg_b = (sum(bod) / len(bod)) or 1
    lc = cdles[n - 1]
    lst_b = abs(lc["close"] - lc["open"])
    if lc["low"] < lo50 and lc["close"] > lo50 * 0.9995:
        return "SPRING"
    if pos > 0.8 and e20 > e50 and last > e20:
        return "DISTRIBUTION" if lst_b < avg_b * 0.6 else "MARKUP"
    if pos < 0.2 and e20 < e50 and last < e20:
        return "ACCUMULATION" if lst_b < avg_b * 0.6 else "MARKDOWN"
    if 0.35 < pos < 0.65:
        return "CAUSE"
    return "TRANSITION"


GATE_NAMES = ["EMA Stack", "RSI Momentum", "MACD Direction", "Market Structure",
              "Live Candle", "ATR Band", "Macro Align", "Stochastic", "Pattern Gate",
              "Fibonacci Zone"]


def atr_ratio(atrv) -> float:
    """Current ATR over its 100-bar average (non-empty values only)."""
    hist = [v for v in atrv[-100:] if v]
    mean = sum(hist) / len(hist) if hist else 0
    now = atrv[-1]
    return now / mean if mean > 0 and now else 0.0


def aria_fib(cdles, atrv, d: str) -> dict[str, Any]:
    """Fibonacci Zone gate — see ariaFib() in the terminal for the rules."""
    n = len(cdles)
    atr = atrv[n - 1] or 0
    fail = lambda why: {"pass": False, "detail": why, "r": None}
    if n < 30 or not atr > 0:
        return fail("not enough data")
    buy = d == "buy"
    start = max(0, n - FIB_WINDOW)
    last = cdles[n - 1]["close"]
    hi = lambda i: cdles[i]["high"]
    lo = lambda i: cdles[i]["low"]
    ext = start
    for i in range(start, n):
        if (hi(i) > hi(ext)) if buy else (lo(i) < lo(ext)):
            ext = i
    if ext > n - 2:
        return fail("no pullback yet")
    orig = -1
    for i in range(max(0, ext - FIB_WINDOW), ext):
        if orig < 0 or ((lo(i) < lo(orig)) if buy else (hi(i) > hi(orig))):
            orig = i
    if orig < 0:
        return fail("no swing found")
    pb = ext + 1
    for i in range(ext + 1, n):
        if (lo(i) <= lo(pb)) if buy else (hi(i) >= hi(pb)):
            pb = i
    H = hi(ext) if buy else hi(orig)
    L = lo(orig) if buy else lo(ext)
    leg = H - L
    if not leg >= FIB_MIN_LEG_ATR * atr:
        return fail("last swing too small")
    r = (H - lo(pb)) / leg if buy else (hi(pb) - L) / leg
    if r < FIB_ZONE[0]:
        return fail("pullback too shallow")
    if r > FIB_ZONE[1]:
        return fail("pullback past 61.8%")
    if n - 1 - pb > FIB_RECENT:
        return fail("zone touch too old")
    turned = (lo(pb) < last < H) if buy else (L < last < hi(pb))
    if not turned:
        return fail("no reaction from the zone yet")
    return {"pass": True, "detail": f"{r*100:.0f}% retrace", "r": r}


def aria_gates(cdles, closes, ema20v, ema50v, ema200v, rsiv, macdv, stochv, atrv, pattern_aligned) -> dict[str, Any]:
    n = len(closes)
    last, e20, e50 = closes[n - 1], ema20v[n - 1], ema50v[n - 1]
    rsi = rsiv[n - 1]
    atr = atrv[n - 1] or 1
    buy = last > e20 and e20 > e50
    d = "buy" if buy else "sell"
    g = []
    g.append((last > e20 and e20 > e50) if buy else (last < e20 and e20 < e50))
    g.append((_gt(rsi, 50) and _lt(rsi, 75)) if buy else (_lt(rsi, 50) and _gt(rsi, 25)))
    ml, ms = macdv["line"][n - 1], macdv["sig"][n - 1]
    g.append(ml > ms if buy else ml < ms)
    sl2 = cdles[-10:]
    hhll = 0
    for i in range(2, len(sl2)):
        if buy and sl2[i]["high"] > sl2[i - 2]["high"] and sl2[i]["low"] > sl2[i - 2]["low"]:
            hhll += 1
        if not buy and sl2[i]["low"] < sl2[i - 2]["low"] and sl2[i]["high"] < sl2[i - 2]["high"]:
            hhll += 1
    g.append(hhll >= 2)
    lc, pc = cdles[n - 1], cdles[n - 2]
    mid = (lc["high"] + lc["low"]) / 2
    if buy:
        eng = lc["close"] > lc["open"] and lc["close"] > pc["high"]
        pin = lc["low"] < pc["low"] and lc["close"] > mid
        bdy = lc["close"] > lc["open"]
    else:
        eng = lc["close"] < lc["open"] and lc["close"] < pc["low"]
        pin = lc["high"] > pc["high"] and lc["close"] < mid
        bdy = lc["close"] < lc["open"]
    g.append(eng or pin or bdy)
    ratio = atr_ratio(atrv)
    g.append(ATR_BAND[0] <= ratio <= ATR_BAND[1])
    e200 = ema200v[n - 1] if ema200v else None
    if e200:
        g.append(last > e200 if buy else last < e200)
    else:
        w = closes[-min(100, n):]
        m = (max(w) + min(w)) / 2
        g.append(last > m if buy else last < m)
    kv = stochv["k"][n - 1]
    g.append(kv is not None and (kv < 50 if buy else kv > 50))
    g.append(bool(pattern_aligned))
    fib = aria_fib(cdles, atrv, d)
    g.append(fib["pass"])
    return {"gates": [bool(x) for x in g], "score": sum(1 for x in g if x), "dir": d, "fib": fib}


def aria_entry(closes, atrv, d: str, mcc: dict) -> dict[str, float]:
    n = len(closes)
    last = closes[n - 1]
    atr = atrv[n - 1] or last * 0.002
    sl_m = 2.5 if mcc["code"] == "VOLATILE" else 2.0 if mcc["code"] == "FAKE_BREAK" else 1.5
    sl = atr * sl_m
    sign = 1 if d == "buy" else -1
    return {
        "entry": last, "sl_dist": sl, "sl": last - sign * sl,
        "tp1": last + sign * sl * 1.5, "tp2": last + sign * sl * 2.5, "tp3": last + sign * sl * 4.0,
    }


def aria_verdict(score: int, mcc: dict, sym: str, d: str, news_week: bool) -> str:
    if mcc["code"] in ("DEAD_ZONE", "FAKE_BREAK"):
        return "OBSERVER"
    if sym == "frxNAS100" and news_week and d == "sell":
        return "BLOCKED"
    if score >= EXEC_MIN:
        return "EXEC_READY"
    if score >= QUAL_MIN:
        return "QUALIFIED"
    if score >= WAIT_MIN:
        return "WAITING"
    return "OBSERVER"


# ── Pattern scanner (mirror PATTERNS / runPatternScanSilent) ─────────────────

def _p_bull_engulf(c, i):
    if i < 1:
        return None
    cur, pr = c[i], c[i - 1]
    if not (cur["close"] > cur["open"] and pr["close"] < pr["open"] and cur["close"] > pr["open"] and cur["open"] < pr["close"]):
        return None
    cb, pb = cur["close"] - cur["open"], pr["open"] - pr["close"]
    ratio = cb / pb if pb > 0 else 1
    return min(95, 55 + js_round(ratio * 20))


def _p_bear_engulf(c, i):
    if i < 1:
        return None
    cur, pr = c[i], c[i - 1]
    if not (cur["close"] < cur["open"] and pr["close"] > pr["open"] and cur["close"] < pr["open"] and cur["open"] > pr["close"]):
        return None
    cb, pb = cur["open"] - cur["close"], pr["close"] - pr["open"]
    ratio = cb / pb if pb > 0 else 1
    return min(95, 55 + js_round(ratio * 20))


def _p_hammer(c, i):
    x = c[i]
    body = abs(x["close"] - x["open"])
    lo = min(x["close"], x["open"]) - x["low"]
    hi = x["high"] - max(x["close"], x["open"])
    if not (body > 0 and lo > body * 2 and hi < body * 0.5):
        return None
    ratio = lo / body if body > 0 else 0
    return min(92, 55 + js_round((ratio - 2) * 8))


def _p_star(c, i):
    x = c[i]
    body = abs(x["close"] - x["open"])
    hi = x["high"] - max(x["close"], x["open"])
    lo = min(x["close"], x["open"]) - x["low"]
    if not (body > 0 and hi > body * 2 and lo < body * 0.5):
        return None
    ratio = hi / body if body > 0 else 0
    return min(92, 55 + js_round((ratio - 2) * 8))


def _p_doji(c, i):
    x = c[i]
    body, rng = abs(x["close"] - x["open"]), x["high"] - x["low"]
    if not (rng > 0 and body / rng < 0.1):
        return None
    return js_round(60 + (1 - body / (rng or 1)) * 30)


def _p_double_top(c, i):
    if i < 10:
        return None
    highs = [x["high"] for x in c[i - 10:i + 1]]
    m = max(highs)
    peaks = [k for k, h in enumerate(highs) if h > m * 0.999]
    if len(peaks) < 2 or peaks[-1] - peaks[0] < 3:
        return None
    return min(88, 65 + len(peaks) * 4)


def _p_double_bottom(c, i):
    if i < 10:
        return None
    lows = [x["low"] for x in c[i - 10:i + 1]]
    m = min(lows)
    tr = [k for k, l in enumerate(lows) if l < m * 1.001]
    if len(tr) < 2 or tr[-1] - tr[0] < 3:
        return None
    return min(88, 65 + len(tr) * 4)


def _p_hs(c, i):
    if i < 15:
        return None
    highs = [x["high"] for x in c[i - 15:i + 1]]
    m = max(highs)
    mi = highs.index(m)
    if not (mi > 3 and mi < len(highs) - 3 and highs[mi - 3] < m * 0.97 and highs[mi + 3] < m * 0.97):
        return None
    sym = abs(highs[mi - 3] - highs[mi + 3]) / m
    return min(86, 62 + js_round((0.05 - sym) * 400))


def _p_asc_tri(c, i):
    if i < 8:
        return None
    s = c[i - 8:i + 1]
    highs, lows = [x["high"] for x in s], [x["low"] for x in s]
    hr = max(highs) - min(highs)
    if not (hr < highs[0] * 0.01 and lows[-1] > lows[0]):
        return None
    return min(80, 60 + js_round((1 - hr / (highs[0] * 0.01)) * 20))


def _p_desc_tri(c, i):
    if i < 8:
        return None
    s = c[i - 8:i + 1]
    highs, lows = [x["high"] for x in s], [x["low"] for x in s]
    lr = max(lows) - min(lows)
    if not (lr < lows[0] * 0.01 and highs[-1] < highs[0]):
        return None
    return min(80, 60 + js_round((1 - lr / (lows[0] * 0.01)) * 20))


def _p_bull_flag(c, i):
    if i < 8:
        return None
    f, p = c[i - 4:i + 1], c[i - 8:i - 4]
    if not (p[-1]["close"] > p[0]["open"] * 1.005 and f[-1]["close"] < f[0]["open"]):
        return None
    pole = (p[-1]["close"] - p[0]["open"]) / p[0]["open"]
    return min(82, 60 + js_round(pole * 1500))


def _p_bear_flag(c, i):
    if i < 8:
        return None
    f, p = c[i - 4:i + 1], c[i - 8:i - 4]
    if not (p[-1]["close"] < p[0]["open"] * 0.995 and f[-1]["close"] > f[0]["open"]):
        return None
    pole = abs(p[-1]["close"] - p[0]["open"]) / p[0]["open"]
    return min(82, 60 + js_round(pole * 1500))


def _wedge(c, i, rising):
    if i < 10:
        return None
    s = c[i - 10:i + 1]
    highs, lows = [x["high"] for x in s], [x["low"] for x in s]
    if rising:
        ok = highs[-1] > highs[0] and lows[-1] > lows[0]
    else:
        ok = highs[-1] < highs[0] and lows[-1] < lows[0]
    if not (ok and (highs[-1] - lows[-1]) < (highs[0] - lows[0])):
        return None
    comp = 1 - (highs[-1] - lows[-1]) / (highs[0] - lows[0])
    return min(80, 58 + js_round(comp * 40))


PATTERNS = [
    ("Bullish Engulfing", "bull", _p_bull_engulf),
    ("Bearish Engulfing", "bear", _p_bear_engulf),
    ("Hammer", "bull", _p_hammer),
    ("Shooting Star", "bear", _p_star),
    ("Doji", "neut", _p_doji),
    ("Double Top", "bear", _p_double_top),
    ("Double Bottom", "bull", _p_double_bottom),
    ("Head & Shoulders", "bear", _p_hs),
    ("Asc Triangle", "bull", _p_asc_tri),
    ("Desc Triangle", "bear", _p_desc_tri),
    ("Bull Flag", "bull", _p_bull_flag),
    ("Bear Flag", "bear", _p_bear_flag),
    ("Rising Wedge", "bear", lambda c, i: _wedge(c, i, True)),
    ("Falling Wedge", "bull", lambda c, i: _wedge(c, i, False)),
]


def pattern_scan(cdles: list[Candle]) -> list[dict]:
    n = len(cdles)
    if n < 20:
        return []
    lookback = min(30, n)
    results = []
    for name, d, fn in PATTERNS:
        best = None
        for i in range(n - lookback, n):
            if i < 15:
                continue
            try:
                conf = fn(cdles, i)
            except (ZeroDivisionError, ValueError, IndexError):
                conf = None
            if conf is not None and (best is None or conf > best):
                best = conf
        if best is not None:
            results.append({"name": name, "dir": d, "conf": best})
    results.sort(key=lambda r: -r["conf"])
    return results


def pattern_alignment(cdles: list[Candle], d: str) -> Optional[str]:
    """Best same-direction pattern (conf ≥ 75) completed on the last PATTERN_RECENT bars."""
    n = len(cdles)
    if n < 20:
        return None
    want = "bull" if d == "buy" else "bear"
    best = None
    for name, pdir, fn in PATTERNS:
        if pdir != want:
            continue
        for i in range(max(15, n - PATTERN_RECENT), n):
            try:
                conf = fn(cdles, i)
            except (ZeroDivisionError, ValueError, IndexError):
                conf = None
            if conf is not None and conf >= 75 and (best is None or conf > best[1]):
                best = (name, conf)
    return best[0] if best else None


# ── One-call evaluation ──────────────────────────────────────────────────────

def evaluate(cdles: list[Candle], sym: str, utc_hour: int, news_week: bool = False) -> Optional[dict[str, Any]]:
    """Full ARIA read on the given candles (last one = the bar being judged)."""
    if len(cdles) < 30:
        return None
    closes = [c["close"] for c in cdles]
    n = len(closes)
    ema20v, ema50v, ema200v = calc_ema(closes, 20), calc_ema(closes, 50), calc_ema(closes, 200)
    rsiv, atrv = calc_rsi(closes), calc_atr(cdles, 14)
    macdv, stochv = calc_macd(closes), calc_stoch(cdles)
    mcc = aria_mcc(cdles, closes, ema20v, ema50v, atrv, utc_hour)
    wyck = aria_wyckoff(cdles, closes, ema20v, ema50v)
    d = "buy" if (closes[n - 1] > ema20v[n - 1] and ema20v[n - 1] > ema50v[n - 1]) else "sell"
    pat = pattern_alignment(cdles, d)
    gates = aria_gates(cdles, closes, ema20v, ema50v, ema200v, rsiv, macdv, stochv, atrv, pat)
    verdict = aria_verdict(gates["score"], mcc, sym, gates["dir"], news_week)
    entry = aria_entry(closes, atrv, gates["dir"], mcc)
    return {
        "dir": gates["dir"], "score": gates["score"], "gates": gates["gates"],
        "mcc": mcc["code"], "wyckoff": wyck, "pattern": pat, "verdict": verdict,
        "rsi": rsiv[n - 1], "fib_r": gates["fib"]["r"], "atr_ratio": atr_ratio(atrv),
        "engine": ENGINE_VERSION, "elliott": elliott_read(cdles, atrv, rsiv), **entry,
    }


# ── Elliott Wave — SOFT context layer (not a gate) ───────────────────────────
#
# Deliberately cautious: it never changes the score or the verdict. It labels
# the structure only when the hard Elliott rules hold on objective ATR swings,
# says whether the Fibonacci proportions fit, and flags RSI divergence on a
# fifth wave. The journal records the label so its value can be measured
# before it is ever promoted to a gate. Multi-timeframe confirmation is not
# part of this version, which is one more reason it stays soft.

EW_SWING_ATR = 2.0


def zigzag(cdles: list[Candle], atrv, k: float = EW_SWING_ATR) -> tuple[list[tuple], tuple]:
    """Swing points: a swing is confirmed once price reverses k×ATR from it.
    Returns (confirmed pivots [(index, 'H'|'L', price)], current unconfirmed extreme)."""
    piv: list[tuple] = []
    if not cdles:
        return piv, None
    trend, ext = "up", 0
    for i, c in enumerate(cdles):
        a = atrv[i] or (c["high"] - c["low"]) or 1e-9
        if trend == "up":
            if c["high"] >= cdles[ext]["high"]:
                ext = i
            elif cdles[ext]["high"] - c["low"] >= k * a:
                piv.append((ext, "H", cdles[ext]["high"]))
                trend, ext = "down", i
        else:
            if c["low"] <= cdles[ext]["low"]:
                ext = i
            elif c["high"] - cdles[ext]["low"] >= k * a:
                piv.append((ext, "L", cdles[ext]["low"]))
                trend, ext = "up", i
    cur = (ext, "H" if trend == "up" else "L",
           cdles[ext]["high"] if trend == "up" else cdles[ext]["low"])
    return piv, cur


def _impulse(pts: list[tuple], up: bool) -> Optional[dict]:
    """Check hard Elliott rules on alternating points p0..pk (k = 3 or 5)."""
    s = 1 if up else -1
    v = [p[2] * s for p in pts]          # flip a down-move so the maths is one-sided
    w1 = v[1] - v[0]
    if w1 <= 0 or v[2] <= v[0]:          # wave 2 may not retrace all of wave 1
        return None
    r2 = (v[1] - v[2]) / w1
    if v[3] <= v[1]:                     # wave 3 must go beyond wave 1
        return None
    w3 = v[3] - v[2]
    out = {"waves": 3, "fib_ok": 0.382 <= r2 <= 0.786}
    if len(pts) >= 5:
        if v[4] <= v[1]:                 # wave 4 may not overlap wave 1
            return None
        r4 = (v[3] - v[4]) / w3
        out.update(waves=4, fib_ok=out["fib_ok"] and 0.236 <= r4 <= 0.5)
    if len(pts) >= 6:
        w5 = v[5] - v[4]
        if v[5] <= v[3] or w3 < min(w1, w5):   # wave 3 is never the shortest
            return None
        out["waves"] = 5
    return out


def elliott_read(cdles: list[Candle], atrv, rsiv) -> dict[str, Any]:
    """Soft Elliott context for the latest bar. label None = no valid count."""
    piv, cur = zigzag(cdles, atrv)
    pts = piv + ([cur] if cur else [])
    best = {"label": None, "dir": None, "fib_ok": False, "divergence": False}
    # Try the longest valid count ending at the latest point: 5, then 4, then 3 waves.
    for k in (6, 5, 4):
        if len(pts) < k:
            continue
        seq = pts[-k:]
        up = seq[0][1] == "L"
        info = _impulse(seq, up)
        if not info:
            continue
        d = "up" if up else "down"
        if info["waves"] == 5:
            i3, i5 = seq[3][0], seq[5][0]
            r3, r5 = rsiv[i3], rsiv[i5]
            div = r3 is not None and r5 is not None and ((r5 < r3) if up else (r5 > r3))
            return {"label": f"Wave 5 {d}" + (" · divergence" if div else ""), "dir": d,
                    "fib_ok": info["fib_ok"], "divergence": div}
        if info["waves"] == 4:
            return {"label": f"Wave 4 pullback in {d}trend", "dir": d, "fib_ok": info["fib_ok"], "divergence": False}
        return {"label": f"Wave 3 {d}", "dir": d, "fib_ok": info["fib_ok"], "divergence": False}
    return best
