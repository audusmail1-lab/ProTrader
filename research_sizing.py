"""
Should "Size from risk" also shrink the lot on volatile instruments (ATR)?
   python3 research_sizing.py        (uses the 1-minute data in /home/claude/data)

The lot from risk is  lot = risk$ / (stop distance x value per point), so the
loss AT THE STOP is the risk budget whatever the instrument. Volatility can
only add loss beyond that in two ways, and this measures both on real 1m data:

  1. Stop too tight for the instrument's noise: a stop inside the normal
     15-minute range gets touched even when the idea was right.
     -> P(stop touched within 4 h) for stops at k x ATR(14, 15m).
  2. Fill worse than the stop (gaps / fast moves): the real loss is > 1R.
     -> overshoot in R when the stop is hit, per instrument, and in calm vs
        volatile regimes (ATR now vs its own 4-day median).

If overshoot in R is small and does not grow with volatility, an extra ATR
cut on top of stop-based sizing would only make the trader risk less than
the 1% they chose, with no protection gained.
"""
import json
import os

import numpy as np

DATA = os.environ.get("RESEARCH_DATA", "/home/claude/data")
MARKETS = {"R_75": "Volatility 75", "1HZ75V": "Volatility 75 (1s)", "cryBTCUSD": "BTC/USD",
           "OTC_NDX": "NAS100", "frxXAUUSD": "Gold", "frxEURUSD": "EUR/USD",
           "frxGBPUSD": "GBP/USD", "frxUSDJPY": "USD/JPY"}
KS = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
HORIZON = 240          # minutes after entry
STEP = 2               # every 2nd 15m bar as an entry
GAPS_ONLY = os.environ.get("GAPS_ONLY") == "1"   # 1: only windows that span a market close


def bars15(t, o, h, l, c):
    key = (t // 900).astype(np.int64)
    edges = np.flatnonzero(np.diff(key)) + 1
    starts = np.r_[0, edges]; ends = np.r_[edges, len(t)]
    H = np.maximum.reduceat(h, starts); L = np.minimum.reduceat(l, starts)
    C = c[ends - 1]
    return starts, ends, H, L, C


def atr(H, L, C, n=14):
    pc = np.r_[C[0], C[:-1]]
    tr = np.maximum(H - L, np.maximum(abs(H - pc), abs(L - pc)))
    a = np.empty_like(tr); a[:n] = tr[:n].mean()
    for i in range(n, len(tr)):
        a[i] = a[i - 1] + (tr[i] - a[i - 1]) / n
    return a


def study(sym):
    z = np.load(f"{DATA}/1m_{sym}.npz")
    t, o, h, l, c = (z[k].astype(float) for k in ("time", "open", "high", "low", "close"))
    starts, ends, H, L, C = bars15(t, o, h, l, c)
    A = atr(H, L, C)
    med = np.array([np.median(A[max(0, i - 384):i + 1]) for i in range(len(A))])   # 4 days of 15m bars
    idx = np.arange(100, len(ends) - 1, STEP)
    j = ends[idx]                                   # first 1m bar after the 15m close
    ok = j + HORIZON < len(t)
    idx, j = idx[ok], j[ok]
    ok = (t[j + HORIZON - 1] - t[j]) < (HORIZON + 30) * 60    # skip windows across a closed market
    if GAPS_ONLY:
        ok = ~ok
    idx, j = idx[ok], j[ok]
    entry = c[j - 1]; a = A[idx]; ratio = A[idx] / med[idx]
    W = np.lib.stride_tricks.sliding_window_view
    lo, hi, op = W(l, HORIZON)[j], W(h, HORIZON)[j], W(o, HORIZON)[j]
    out = {"name": MARKETS[sym], "entries": int(len(idx)), "k": {}}
    for k in KS:
        d = k * a
        res = {}
        for side in ("long", "short"):
            stop = entry - d if side == "long" else entry + d
            hit = (lo <= stop[:, None]) if side == "long" else (hi >= stop[:, None])
            any_hit = hit.any(1)
            first = hit.argmax(1)
            rows = np.flatnonzero(any_hit)
            fo = op[rows, first[rows]]
            if side == "long":
                fill = np.minimum(fo, stop[rows])
                over = (stop[rows] - fill) / d[rows]
            else:
                fill = np.maximum(fo, stop[rows])
                over = (fill - stop[rows]) / d[rows]
            res[side] = (any_hit, rows, over, first)
        hit_all = np.r_[res["long"][0], res["short"][0]]
        over_all = np.r_[res["long"][2], res["short"][2]]
        rr = np.r_[ratio[res["long"][1]], ratio[res["short"][1]]]
        first_all = np.r_[res["long"][3][res["long"][1]], res["short"][3][res["short"][1]]]
        hot = rr >= 1.5
        out["k"][str(k)] = {
            "p_touch_4h": float(hit_all.mean()),
            "p_touch_60m": float(np.r_[(res["long"][0]) & (res["long"][3] < 60), (res["short"][0]) & (res["short"][3] < 60)].mean()),
            "overshoot_mean_R": float(over_all.mean()) if len(over_all) else 0.0,
            "overshoot_p99_R": float(np.quantile(over_all, .99)) if len(over_all) else 0.0,
            "overshoot_max_R": float(over_all.max()) if len(over_all) else 0.0,
            "share_gt_0_25R": float((over_all > 0.25).mean()) if len(over_all) else 0.0,
            "calm_mean_R": float(over_all[~hot].mean()) if (~hot).any() else None,
            "hot_mean_R": float(over_all[hot].mean()) if hot.any() else None,
            "hot_p99_R": float(np.quantile(over_all[hot], .99)) if hot.sum() > 20 else None,
            "hot_share": float(hot.mean()),
        }
    out["atr_pct_of_price"] = float(np.median(a / entry) * 100)
    return out


def main():
    results = {}
    for sym in MARKETS:
        if os.path.exists(f"{DATA}/1m_{sym}.npz"):
            results[sym] = study(sym)
            r = results[sym]
            print(f"\n{r['name']}  ({r['entries']} entries, ATR ≈ {r['atr_pct_of_price']:.3f}% of price)")
            print("  stop   touched≤1h  touched≤4h   overshoot mean / p99 / max (R)   >0.25R   calm vs volatile mean")
            for k, v in r["k"].items():
                print(f"  {float(k):>4}×ATR   {v['p_touch_60m']*100:5.1f}%     {v['p_touch_4h']*100:5.1f}%      "
                      f"{v['overshoot_mean_R']:.3f} / {v['overshoot_p99_R']:.3f} / {v['overshoot_max_R']:.2f}"
                      f"      {v['share_gt_0_25R']*100:4.1f}%    {v['calm_mean_R'] or 0:.3f} vs {v['hot_mean_R'] or 0:.3f}")
    json.dump(results, open(f"{DATA}/sizing{'_gaps' if GAPS_ONLY else ''}.json", "w"), indent=1)


if __name__ == "__main__":
    main()
