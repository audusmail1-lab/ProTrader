"""
ARIA v7 engine — Python port for Sentinel.

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
              "Live Candle", "ATR Valid", "Macro Align", "Stochastic", "Pattern Gate"]


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
    g.append(atr > 0)
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
    return {"gates": [bool(x) for x in g], "score": sum(1 for x in g if x), "dir": d}


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
    if score >= 8:
        return "EXEC_READY"
    if score >= 7:
        return "QUALIFIED"
    if score >= 5:
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
    want = "bull" if d == "buy" else "bear"
    for r in pattern_scan(cdles):
        if r["dir"] == want and r["conf"] >= 75:
            return r["name"]
    return None


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
        "rsi": rsiv[n - 1], **entry,
    }
