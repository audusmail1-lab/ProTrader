"""
Does being more selective pay? The same year of ARIA signals, filtered by
a fixed ladder of stricter rules, each level managed with Sentinel's live
exit (7.2c) and with the hybrid. Every trade walked on 1-minute candles.

Ladder (defined before the run):
  L0  ARIA 8+/10
  L1  + 4h trend aligned
  L2  + no completed Wave 5          (= Sentinel 7.2c entries)
  L3  + 9+/10 (execution-ready)
  L4  + 10/10
Scopes: all 8 markets · real markets · the 4 candidate slices
(NAS100 15m, XAU 15m, XAU 1h, BTC 1h — chosen on this same year, so that
scope is in-sample and flatters itself).

    python research_selectivity.py --out selectivity.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np

import research_exits as rx
import research_management as rm
import sentinel_core as core
import sentinel_engine as eng

SLICES = {("frxNAS100", "15m"), ("frxXAUUSD", "15m"), ("frxXAUUSD", "1h"), ("cryBTCUSD", "1h")}
EXITS = {
    "7.2c exit": rm.rule(trig=1.0, mode=1, dist=1.0, arm=1.0),
    "Hybrid exit": rm.rule(mode=4, arm=1.0),
}
LEVELS = [
    ("L0", "ARIA 8+/10", lambda g: True),
    ("L1", "+ 4h trend aligned", lambda g: g["mtf"] == "aligned"),
    ("L2", "+ no completed Wave 5 (Sentinel 7.2c)", lambda g: g["mtf"] == "aligned" and not (g["ew"] or "").startswith("Wave 5")),
    ("L3", "+ 9+/10", lambda g: g["mtf"] == "aligned" and not (g["ew"] or "").startswith("Wave 5") and g["score"] >= 9),
    ("L4", "+ 10/10", lambda g: g["mtf"] == "aligned" and not (g["ew"] or "").startswith("Wave 5") and g["score"] >= 10),
]
SCOPES = {
    "All 8 markets": lambda r: True,
    "Real markets": lambda r: r["mode"] == "real",
    "4 candidate slices": lambda r: (r["market"], r["tf"]) in SLICES,
}


def run_slice(args):
    mid, tf = args
    t1, o1, h1, l1, c1 = rm.load_1m(mid)
    sec = core.TF_SEC[tf]
    bars = rm.aggregate(t1, o1, h1, l1, c1, sec)[:-1]
    h4 = rm.aggregate(t1, o1, h1, l1, c1, core.TF_SEC["4h"])[:-1]
    sl = rx.signals_for(mid, tf, bars, h4)
    atr = eng.calc_atr(bars, 14)
    m = core.MARKET_BY_ID[mid]
    rows = []
    for g in sl["signals"]:
        s = 1 if g["dir"] == "buy" else -1
        i0 = int(np.searchsorted(t1, g["t"]))
        i1 = int(np.searchsorted(t1, g["t"] + rm.TIMEOUT_BARS * sec))
        if i1 - i0 < 10:
            continue
        pt, pp = rm.swings(bars, s, atr, g["i"], g["i"] + rm.TIMEOUT_BARS, sec)
        piv_t = np.searchsorted(t1, np.array(pt, dtype=np.int64)).astype(np.int64) if pt else np.zeros(0, np.int64)
        piv_px = np.array(pp, dtype=np.float64)
        a = float(atr[g["i"]] or 0.0)
        res = {}
        for name, (tp, trig, off, mode, dist, arm) in EXITS.items():
            gr, mfe, j, why, prot = rm.simulate(h1, l1, c1, i0, i1, s, g["entry"], g["sd"], a, tp, trig, off, mode,
                                                dist, arm, piv_t, piv_px, t1, rm.HYBRID_FALLBACK_BARS * sec,
                                                rm.HYBRID_RETRACE_R)
            res[name] = round(gr - g["cost"], 4)
        rows.append({"market": mid, "tf": tf, "mode": m.mode, "i": g["i"], "t": g["t"], "score": g["score"],
                     "mtf": g["mtf"], "ew": g["ew"], "res": res})
    return mid, tf, rows


def spaced(rows):
    """One entry at a time per market x timeframe: at least SPACING bars apart."""
    out, last = [], {}
    for r in sorted(rows, key=lambda x: x["t"]):
        k = (r["market"], r["tf"])
        if r["i"] - last.get(k, -10 ** 9) >= rm.SPACING:
            out.append(r)
            last[k] = r["i"]
    return out


def stats(rs, weeks):
    n = len(rs)
    if n < 2:
        return {"n": n}
    x = np.array(rs)
    m, sd = x.mean(), x.std(ddof=1)
    eq = np.cumsum(x)
    streak = worst = 0
    for v in x:
        streak = streak + 1 if v < 0 else 0
        worst = max(worst, streak)
    return {"n": n, "per_week": round(n / weeks, 2), "exp": round(float(m), 4),
            "lo": round(float(m - 1.96 * sd / math.sqrt(n)), 4), "hi": round(float(m + 1.96 * sd / math.sqrt(n)), 4),
            "total": round(float(x.sum()), 1), "win": round(float((x > 0).mean()), 4),
            "dd": round(float(np.max(np.maximum.accumulate(eq) - eq)), 1), "streak": int(worst)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="selectivity.json")
    a = ap.parse_args()
    jobs = [(m, tf) for m in rm.MARKETS for tf in rm.TFS]
    t0 = time.time()
    rows = []
    with ProcessPoolExecutor() as ex:
        for mid, tf, rs in ex.map(run_slice, jobs):
            print(f"  {mid:10s} {tf:3s} {len(rs):5d} signals · {time.time()-t0:.0f}s", file=sys.stderr)
            rows += rs
    t_lo, t_hi = min(r["t"] for r in rows), max(r["t"] for r in rows)
    cut = t_lo + 0.7 * (t_hi - t_lo)
    weeks = (t_hi - t_lo) / (7 * 86400)
    out = {"period": [t_lo, t_hi], "holdout_from": cut, "weeks": weeks, "table": []}
    for scope, sf in SCOPES.items():
        for code, label, lf in LEVELS:
            picked = spaced([r for r in rows if sf(r) and lf(r)])
            for ex_name in EXITS:
                full = stats([r["res"][ex_name] for r in picked], weeks)
                ho = stats([r["res"][ex_name] for r in picked if r["t"] >= cut], weeks * 0.3)
                out["table"].append({"scope": scope, "level": code, "label": label, "exit": ex_name, "all": full, "holdout": ho})
                print(f"{scope:20s} {code} {label:40s} {ex_name:11s} n{full.get('n',0):5d} "
                      f"{full.get('per_week',0):5.1f}/wk exp {full.get('exp',float('nan')):+.3f} "
                      f"[{full.get('lo',float('nan')):+.2f},{full.get('hi',float('nan')):+.2f}] "
                      f"total {full.get('total',0):+7.1f}R dd {full.get('dd',0):5.1f} streak {full.get('streak',0):3d} "
                      f"| hold-out {ho.get('exp',float('nan')):+.3f} n{ho.get('n',0)}")
    with open(a.out, "w") as f:
        json.dump(out, f)
    print(f"wrote {a.out} in {time.time()-t0:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
