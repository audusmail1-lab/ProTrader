"""
Sentinel research: exit models, a 4h trend filter, and the synthetic families.

Runs the live ARIA 7.1 engine over one year of Deriv history ONCE per
market × timeframe, keeps every qualified / exec-ready signal, then replays
the same signals under several exit models, with and without a 4h trend
filter. Results are reported on the whole year and, separately, on the last
30% of it (a hold-out the models were not chosen on).

    python research_exits.py --out research.json          # full run
    python research_exits.py --market frxXAUUSD --tf 1h   # quick look

Gross R is stored per trade so the costs can be re-applied later with real
MT5 spreads without re-running the engine.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import sentinel_core as core
import sentinel_engine as eng

W = core.WINDOW

MARKETS_REAL = ["frxNAS100", "frxXAUUSD", "cryBTCUSD", "frxEURUSD", "frxGBPUSD", "frxUSDJPY"]
MARKETS_SYN = ["R_75", "1HZ75V", "BOOM1000", "CRASH1000", "BOOM500", "CRASH500", "JD50", "JD100", "stpRNG"]

# ── exit models ──────────────────────────────────────────────────────────────
# Every model: initial stop at -1R (ARIA's ATR stop). Within one bar the stop
# is checked before any target (conservative). "timeout" closes at that bar's
# close. Returns gross R (before cost).

EXIT_MODELS = {
    "fixed_2.5R":   dict(tp=2.5, timeout=48),                     # current Sentinel model
    "fixed_1.5R":   dict(tp=1.5, timeout=48),
    "partial_1.5":  dict(tp=2.5, partial=1.5, timeout=48),        # half off at 1.5R, stop to BE
    "be_at_1R":     dict(tp=2.5, be=1.0, timeout=48),             # stop to BE after +1R
    "trail_1R":     dict(tp=None, trail=1.0, arm=1.0, timeout=96),# after +1R, trail 1R behind best
    "time_12":      dict(tp=2.5, timeout=12),                     # give it 12 bars, then out
}


def simulate(bars, i0: int, d: str, entry: float, sd: float, model: dict) -> tuple[float, int]:
    """Gross R and exit bar index for one trade opened at the close of bar i0."""
    s = 1 if d == "buy" else -1
    stop = entry - s * sd
    tp = entry + s * sd * model["tp"] if model.get("tp") else None
    part = model.get("partial")
    part_px = entry + s * sd * part if part else None
    banked, size = 0.0, 1.0
    best = 0.0
    n = len(bars)
    for k in range(1, model["timeout"] + 1):
        j = i0 + k
        if j >= n:
            break
        b = bars[j]
        lo_r = s * ((b["low"] if s > 0 else b["high"]) - entry) / sd     # worst excursion this bar
        hi_r = s * ((b["high"] if s > 0 else b["low"]) - entry) / sd     # best excursion this bar
        stop_r = s * (stop - entry) / sd
        if lo_r <= stop_r:                                              # stop first
            return banked + size * stop_r, j
        if part_px is not None and size == 1.0 and hi_r >= part:
            banked += 0.5 * part
            size = 0.5
            stop = entry                                                # rest at breakeven
        if tp is not None and hi_r >= model["tp"]:
            return banked + size * model["tp"], j
        best = max(best, hi_r)
        if model.get("be") and best >= model["be"]:
            stop = entry if s > 0 and stop < entry or s < 0 and stop > entry else stop
        if model.get("trail") and best >= model.get("arm", 0):
            cand = entry + s * sd * (best - model["trail"])
            if (s > 0 and cand > stop) or (s < 0 and cand < stop):
                stop = cand
    j = min(i0 + model["timeout"], n - 1)
    close_r = s * (bars[j]["close"] - entry) / sd
    return banked + size * close_r, j


# ── 4h trend ─────────────────────────────────────────────────────────────────

def trend_4h(h4: list[dict]):
    """Per 4h bar: 'up' / 'down' / 'flat' from EMA20/EMA50 and close."""
    closes = [c["close"] for c in h4]
    if not closes:
        return [], []
    e20, e50 = eng.calc_ema(closes, 20), eng.calc_ema(closes, 50)
    out = []
    for i, c in enumerate(closes):
        if i < 60:
            out.append("flat")
        elif c > e20[i] > e50[i]:
            out.append("up")
        elif c < e20[i] < e50[i]:
            out.append("down")
        else:
            out.append("flat")
    close_times = [c["time"] + core.TF_SEC["4h"] for c in h4]
    return close_times, out


def trend_at(close_times, trends, t: int) -> str:
    """Trend of the last 4h bar that had CLOSED by time t (no look-ahead)."""
    lo, hi = 0, len(close_times) - 1
    ans = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if close_times[mid] <= t:
            ans, lo = mid, mid + 1
        else:
            hi = mid - 1
    return trends[ans] if ans >= 0 else "flat"


# ── per slice ────────────────────────────────────────────────────────────────

def signals_for(mid: str, tf: str, bars: list[dict], h4: list[dict]) -> dict:
    m = core.MARKET_BY_ID[mid]
    ct, tr = trend_4h(h4)
    sigs = []
    for i in range(W - 1, len(bars)):
        window = bars[i - W + 1:i + 1]
        r = eng.evaluate(window, mid, core.bar_close_hour(bars[i], tf), False)
        if not r or r["verdict"] not in ("EXEC_READY", "QUALIFIED") or not r["sl_dist"] > 0:
            continue
        t_close = bars[i]["time"] + core.TF_SEC[tf]
        t4 = trend_at(ct, tr, t_close)
        want = "up" if r["dir"] == "buy" else "down"
        sigs.append({
            "i": i, "t": t_close, "dir": r["dir"], "entry": r["entry"], "sd": r["sl_dist"],
            "score": r["score"], "tier": "exec" if r["verdict"] == "EXEC_READY" else "qualified",
            "mtf": "aligned" if t4 == want else ("flat" if t4 == "flat" else "against"),
            "ew": r["elliott"]["label"], "ew_dir": r["elliott"]["dir"],
            "cost": core.spread_for(m, r["entry"]) / r["sl_dist"],
        })
    return {"market": mid, "tf": tf, "mode": m.mode, "bars": len(bars),
            "t0": bars[0]["time"] if bars else 0, "t1": bars[-1]["time"] if bars else 0,
            "signals": sigs}


def trades_for(slice_: dict, bars: list[dict], model_name: str, filt) -> list[dict]:
    """One position at a time per slice, like Sentinel."""
    model = EXIT_MODELS[model_name]
    out, busy_until = [], -1
    for s in slice_["signals"]:
        if s["i"] <= busy_until or not filt(s):
            continue
        g, j = simulate(bars, s["i"], s["dir"], s["entry"], s["sd"], model)
        busy_until = j
        out.append({"market": slice_["market"], "tf": slice_["tf"], "mode": slice_["mode"],
                    "t": s["t"], "tier": s["tier"], "mtf": s["mtf"], "ew": s["ew"],
                    "gross": g, "cost": s["cost"], "r": g - s["cost"],
                    "entry": s["entry"], "sd": s["sd"],
                    "status": "win" if g > 0 else "loss", "closed_at": s["t"],
                    "cost_r": s["cost"]})
    return out


def _job(args):
    mid, tf, bars, h4 = args
    sl = signals_for(mid, tf, bars, h4)
    res = {}
    filters = {
        "all": lambda s: True,
        "mtf_aligned": lambda s: s["mtf"] == "aligned",
        "mtf_not_against": lambda s: s["mtf"] != "against",
    }
    for mname in EXIT_MODELS:
        for fname, f in filters.items():
            for tier in ("exec", "qualified+"):
                ff = (lambda s, f=f: f(s) and s["tier"] == "exec") if tier == "exec" else f
                res[f"{mname}|{fname}|{tier}"] = trades_for(sl, bars, mname, ff)
    return mid, tf, sl["t0"], sl["t1"], len(sl["signals"]), res


async def _load(mids, tfs, pages):
    data = {}
    for mid in mids:
        m = core.MARKET_BY_ID[mid]
        need = sorted(set(tfs) | {"4h"}, key=["15m", "1h", "4h"].index)
        got = {}
        for tf in need:
            try:
                got[tf] = await core.fetch_candles(m.deriv, tf, 5000, pages_back=pages)
            except Exception as e:
                print(f"  ! {mid} {tf}: {e}", file=sys.stderr)
        for tf in tfs:
            if tf in got and "4h" in got:
                data[(mid, tf)] = (got[tf], got["4h"])
        print(f"  loaded {mid:10s} " + " ".join(f"{k}:{len(v)}" for k, v in got.items()), file=sys.stderr)
    return data


def summarise_rows(trades):
    for t in trades:
        t["closed_at"] = t["t"]
    s = core.summarise([{**t, "status": "win" if t["gross"] >= 2.4 else ("loss" if t["gross"] < 0 else "timeout")}
                        for t in trades])
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=40)
    ap.add_argument("--market", action="append")
    ap.add_argument("--tf", action="append")
    ap.add_argument("--out", default="research.json")
    a = ap.parse_args()
    mids = a.market or (MARKETS_REAL + MARKETS_SYN)
    tfs = a.tf or ["15m", "1h"]
    t0 = time.time()
    data = asyncio.run(_load(mids, tfs, a.pages))
    jobs = [(mid, tf, b, h4) for (mid, tf), (b, h4) in data.items()]
    results = []
    with ProcessPoolExecutor() as ex:
        for mid, tf, a0, a1, nsig, res in ex.map(_job, jobs):
            print(f"  done {mid} {tf}: {nsig} signals", file=sys.stderr)
            results.append({"market": mid, "tf": tf, "t0": a0, "t1": a1, "signals": nsig, "res": res})
    with open(a.out, "w") as f:
        json.dump({"generated": int(time.time()), "models": EXIT_MODELS, "slices": results}, f)
    print(f"wrote {a.out} in {time.time()-t0:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
