"""
Trade-management research: does "move the stop to breakeven at +$100 and
trail from there" protect trades better than the alternatives?

Every trade is walked MINUTE BY MINUTE (Deriv 1m candles, ~1 year), so an
early breakeven trigger is judged on the real path price took, not on a
15-minute bar where the order of high and low is unknown.

Two entry sets are tested with identical management rules:
  * ARIA 7.2c  — the live Sentinel candidate: ARIA 7.1 signals 8+/10, taken
                 only with the 4h trend, no completed Wave 5 entries.
  * Random     — random time, random direction, stop 1.5 x ATR(14). A control:
                 management cannot create an edge that the entries lack, and
                 this shows what a rule does on its own.

A dollar trigger depends on the account: with the 1% rule, 1R = 1% of the
balance, so "+$100" is 0.27R on a $36,900 account, 1R on $10,000 and 2R on
$5,000. The rule is therefore tested at those account sizes and swept over
trigger sizes in R.

    python research_fetch_1m.py R_75 frxXAUUSD ...     # once: 1m history
    python research_management.py --out mgmt.json      # run
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
from numba import njit

import research_exits as rx
import sentinel_core as core
import sentinel_engine as eng

DATA = os.environ.get("RESEARCH_DATA", "/home/claude/data")
MARKETS = ["R_75", "1HZ75V", "frxXAUUSD", "frxNAS100", "cryBTCUSD", "frxEURUSD", "frxGBPUSD", "frxUSDJPY"]
TFS = ["15m", "1h"]
TIMEOUT_BARS = 96            # same horizon for every rule (the 7.2c time-out)
SPACING = 8                  # min bars between two entries of one slice (keeps trades independent-ish)
RANDOM_EVERY = 24            # control: one random entry per ~24 bars
HOLDOUT = 0.30
ACCOUNTS = [36_900, 10_000, 5_000]   # balances the $100 trigger is translated at (1% risk)
DOLLAR = 100.0

# ── management rules ─────────────────────────────────────────────────────────
# Every rule: initial stop -1R. Fields (R units; nan = off):
#   tp     take profit
#   trig   when best open profit reaches trig, stop -> entry + off
#   off    breakeven offset (0 = exactly entry)
#   mode   trailing: 0 none, 1 fixed distance `dist` behind the best price,
#          2 market structure (swing lows/highs on the trade's timeframe),
#          3 volatility: `dist` x ATR(14) behind the best price
#   arm    trailing starts once best profit reaches arm
NAN = float("nan")


def rule(tp=NAN, trig=NAN, off=0.0, mode=0, dist=NAN, arm=NAN):
    return (tp, trig, off, mode, dist, arm)


def dollar_rules(T: float, tag: str) -> dict:
    return {
        f"$100 → BE, trail $100 {tag}": rule(trig=T, mode=1, dist=T, arm=T),
        f"$100 → BE, trail 1R {tag}": rule(trig=T, mode=1, dist=1.0, arm=T),
        f"$100 → BE only, TP 2.5R {tag}": rule(tp=2.5, trig=T),
    }


def rule_book() -> dict:
    rules = {
        "Hold: stop & 2.5R target": rule(tp=2.5),
        "7.2c: BE at 1R, trail 1R": rule(trig=1.0, mode=1, dist=1.0, arm=1.0),
        "BE at 1R +0.1R, trail 1R": rule(trig=1.0, off=0.1, mode=1, dist=1.0, arm=1.0),
        "Structure: swing stop after 1R": rule(trig=NAN, mode=2, arm=1.0),
        "Volatility: 3×ATR trail after 1R": rule(trig=1.0, mode=3, dist=3.0, arm=1.0),
    }
    for bal in ACCOUNTS:
        T = DOLLAR / (0.01 * bal)
        rules.update(dollar_rules(T, f"(${bal/1000:g}k acct = {T:.2f}R)"))
    for T in (0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0):                 # sweep: BE at T, trail at distance T
        rules[f"sweep BE+trail at {T:g}R"] = rule(trig=T, mode=1, dist=T, arm=T)
    return rules


# ── minute-by-minute simulator ───────────────────────────────────────────────

@njit(cache=True)
def simulate(h, l, c, i0, i1, s, entry, sd, atr, tp, trig, off, mode, dist, arm, piv_t, piv_px):
    """Walk 1m bars i0..i1-1. Returns (gross R, MFE R, exit index, reason, protected).
    reason: 0 stop, 1 target, 2 time-out. Within a minute the stop is checked
    before any favourable move (conservative)."""
    stop = entry - s * sd
    best = 0.0
    prot = False
    pk = 0
    for j in range(i0, i1):
        adverse = (l[j] if s > 0 else h[j])
        favour = (h[j] if s > 0 else l[j])
        if s * (adverse - stop) <= 0.0:
            return s * (stop - entry) / sd, best, j, 0, prot
        fr = s * (favour - entry) / sd
        if tp == tp and fr >= tp:
            return tp, max(best, tp), j, 1, prot
        if fr > best:
            best = fr
        new = stop
        if trig == trig and best >= trig:
            be = entry + s * off * sd
            if s * (be - new) > 0:
                new = be
        if arm == arm and best >= arm:
            if mode == 1:
                cand = entry + s * (best - dist) * sd
                if s * (cand - new) > 0:
                    new = cand
            elif mode == 3:
                cand = entry + s * sd * best - s * dist * atr
                if s * (cand - new) > 0:
                    new = cand
            elif mode == 2:
                while pk < piv_t.shape[0] and piv_t[pk] <= j:     # swings confirmed by now
                    cand = piv_px[pk]
                    if s * (cand - new) > 0 and s * (cand - entry) > 0:
                        new = cand
                    pk += 1
        if s * (new - stop) > 0:
            stop = new
            if s * (stop - entry) >= -1e-12:
                prot = True
    j = i1 - 1
    return s * (c[j] - entry) / sd, best, j, 2, prot


# ── data ─────────────────────────────────────────────────────────────────────

def load_1m(mid: str):
    m = core.MARKET_BY_ID[mid]
    z = np.load(f"{DATA}/1m_{m.deriv}.npz")
    return z["time"], z["open"], z["high"], z["low"], z["close"]


def aggregate(t, o, h, l, c, sec: int) -> list[dict]:
    """1m candles -> `sec` candles aligned like Deriv's (epoch multiples)."""
    k = t // sec
    cut = np.flatnonzero(np.diff(k)) + 1
    starts = np.r_[0, cut]
    ends = np.r_[cut, len(t)]
    out = []
    for a, b in zip(starts, ends):
        out.append({"time": int(k[a] * sec), "open": float(o[a]), "high": float(h[a:b].max()),
                    "low": float(l[a:b].min()), "close": float(c[b - 1])})
    return out


def swings(bars: list[dict], s: int, atr: list, i_entry: int, i_end: int, sec: int):
    """Swing lows (buy) / highs (sell) confirmed after entry: a 2-bar fractal,
    usable from the close of the bar that confirms it. Stop goes 0.1 ATR
    beyond the swing."""
    ts, px = [], []
    for j in range(i_entry + 3, min(i_end, len(bars))):
        p = j - 2
        if p - 2 < 0:
            continue
        if s > 0:
            v = bars[p]["low"]
            ok = v < bars[p - 1]["low"] and v < bars[p - 2]["low"] and v <= bars[p + 1]["low"] and v <= bars[p + 2]["low"]
        else:
            v = bars[p]["high"]
            ok = v > bars[p - 1]["high"] and v > bars[p - 2]["high"] and v >= bars[p + 1]["high"] and v >= bars[p + 2]["high"]
        if ok:
            a = atr[j] or 0.0
            ts.append(bars[j]["time"] + sec)            # confirmed when bar j closes
            px.append(v - s * 0.1 * a)
    return ts, px


# ── per slice ────────────────────────────────────────────────────────────────

def entries_for(mid: str, tf: str, bars: list[dict], h4: list[dict], rng) -> list[dict]:
    out = []
    sl = rx.signals_for(mid, tf, bars, h4)
    last = -10 ** 9
    for g in sl["signals"]:
        if g["mtf"] != "aligned" or (g["ew"] or "").startswith("Wave 5"):
            continue                                      # the 7.2c entry filter
        if g["i"] - last < SPACING:
            continue
        last = g["i"]
        out.append({"set": "ARIA 7.2c", **g})
    atr = eng.calc_atr(bars, 14)
    m = core.MARKET_BY_ID[mid]
    i = core.WINDOW
    while i < len(bars) - 1:
        a = atr[i]
        if a:
            d = "buy" if rng.random() < 0.5 else "sell"
            e = bars[i]["close"]
            out.append({"set": "Random", "i": i, "t": bars[i]["time"] + core.TF_SEC[tf], "dir": d, "entry": e,
                        "sd": 1.5 * a, "tier": "random", "mtf": "", "ew": "",
                        "cost": core.spread_for(m, e) / (1.5 * a)})
        i += RANDOM_EVERY + int(rng.integers(0, RANDOM_EVERY // 2))
    return out


def run_slice(args):
    mid, tf, seed = args
    rules = rule_book()
    t1, o1, h1, l1, c1 = load_1m(mid)
    sec = core.TF_SEC[tf]
    bars = aggregate(t1, o1, h1, l1, c1, sec)
    h4 = aggregate(t1, o1, h1, l1, c1, core.TF_SEC["4h"])
    bars, h4 = bars[:-1], h4[:-1]                          # drop the forming bars
    rng = np.random.default_rng(seed)
    ents = entries_for(mid, tf, bars, h4, rng)
    atr = eng.calc_atr(bars, 14)
    m = core.MARKET_BY_ID[mid]
    rows = []
    for e in ents:
        s = 1 if e["dir"] == "buy" else -1
        t_in = e["t"]
        i0 = int(np.searchsorted(t1, t_in))                # first minute after the signal bar closed
        i1 = int(np.searchsorted(t1, t_in + TIMEOUT_BARS * sec))
        if i1 - i0 < 10:
            continue
        pt, pp = swings(bars, s, atr, e["i"], e["i"] + TIMEOUT_BARS, sec)
        piv_t = np.searchsorted(t1, np.array(pt, dtype=np.int64)).astype(np.int64) if pt else np.zeros(0, np.int64)
        piv_px = np.array(pp, dtype=np.float64)
        a = float(atr[e["i"]] or 0.0)
        res = {}
        for name, (tp, trig, off, mode, dist, arm) in rules.items():
            g, mfe, j, why, prot = simulate(h1, l1, c1, i0, i1, s, e["entry"], e["sd"], a,
                                            tp, trig, off, mode, dist, arm, piv_t, piv_px)
            res[name] = (round(g, 4), round(mfe, 4), int(j - i0), int(why), bool(prot))
        rows.append({"set": e["set"], "market": mid, "tf": tf, "mode": m.mode, "t": t_in, "dir": e["dir"],
                     "cost": round(e["cost"], 5), "res": res})
    return mid, tf, len(bars), rows


# ── statistics ───────────────────────────────────────────────────────────────

def describe(rows, name, hold="Hold: stop & 2.5R target"):
    net = np.array([r["res"][name][0] - r["cost"] for r in rows])
    gross = np.array([r["res"][name][0] for r in rows])
    mfe = np.array([r["res"][name][1] for r in rows])
    why = np.array([r["res"][name][3] for r in rows])
    prot = np.array([r["res"][name][4] for r in rows])
    held = np.array([r["res"][name][2] for r in rows])
    hold_g = np.array([r["res"][hold][0] for r in rows])
    hold_mfe = np.array([r["res"][hold][1] for r in rows])
    n = len(net)
    if not n:
        return {"n": 0}
    sd = net.std(ddof=1) if n > 1 else 0.0
    eq = np.cumsum(net)
    dd = float(np.max(np.maximum.accumulate(eq) - eq)) if n else 0.0
    pos, neg = net[net > 0].sum(), -net[net < 0].sum()
    big = mfe >= 1.0
    capture = float(np.mean(np.clip(gross[big], -1, None) / mfe[big])) if big.any() else None
    # Decompose the difference with the unmanaged trade: where holding would
    # have LOST (the rule saved money) vs where holding would have WON (the
    # rule cut a winner short).
    diff = gross - hold_g
    hold_lost = hold_g < 0
    hold_won = hold_g >= 2.5 - 1e-9
    stopped_flat = (why == 0) & prot & (gross <= 0.25)
    premature = stopped_flat & hold_won
    streak = worst = 0
    for x in net:
        streak = streak + 1 if x < 0 else 0
        worst = max(worst, streak)
    return {
        "n": n, "exp": float(net.mean()), "sd": float(sd), "worst_streak": int(worst), "lo": float(net.mean() - 1.96 * sd / math.sqrt(n)),
        "hi": float(net.mean() + 1.96 * sd / math.sqrt(n)), "total": float(net.sum()),
        "win": float((net > 0).mean()), "pf": float(pos / neg) if neg else None, "dd": dd,
        "full_loss": float((gross <= -0.999).mean()),
        "protected": float(prot.mean()),
        "scratch": float((np.abs(gross) <= 0.25).mean()),
        "capture": capture,
        "giveback": float(np.mean(mfe[big] - gross[big])) if big.any() else None,
        "big_winners": float((gross >= 2.5 - 1e-9).mean()),
        "saved_r": float(diff[hold_lost].sum()),
        "cut_r": float(diff[hold_won].sum()),
        "premature": int(premature.sum()),
        "premature_pct_of_protected": float(premature.sum() / max(1, prot.sum())),
        "avg_bars_1m": float(held.mean()),
    }


def paired(rows, a, b, iters=2000, seed=7):
    """Bootstrap 95% interval of mean(net_a - net_b) on the same trades."""
    d = np.array([r["res"][a][0] - r["res"][b][0] for r in rows])
    if len(d) < 5:
        return None
    rng = np.random.default_rng(seed)
    bs = rng.choice(d, size=(iters, len(d)), replace=True).mean(axis=1)
    return {"mean": float(d.mean()), "lo": float(np.percentile(bs, 2.5)), "hi": float(np.percentile(bs, 97.5)),
            "better": float((d > 1e-9).mean()), "worse": float((d < -1e-9).mean())}


def report(rows: list[dict]) -> dict:
    rules = list(rule_book())
    t0, t1 = min(r["t"] for r in rows), max(r["t"] for r in rows)
    cut = t0 + (1 - HOLDOUT) * (t1 - t0)
    out = {"period": [t0, t1], "holdout_from": cut, "rules": {k: list(v) for k, v in rule_book().items()},
           "sets": {}}
    for st in ("ARIA 7.2c", "Random"):
        rs = [r for r in rows if r["set"] == st]
        blk = {"all": {}, "holdout": {}, "real": {}, "synthetic": {}, "vs_hold": {}, "vs_72c": {}, "by_market": {}}
        for k in rules:
            blk["all"][k] = describe(rs, k)
            blk["holdout"][k] = describe([r for r in rs if r["t"] >= cut], k)
            blk["real"][k] = describe([r for r in rs if r["mode"] == "real"], k)
            blk["synthetic"][k] = describe([r for r in rs if r["mode"] == "synthetic"], k)
            blk["vs_hold"][k] = paired(rs, k, "Hold: stop & 2.5R target")
            blk["vs_72c"][k] = paired(rs, k, "7.2c: BE at 1R, trail 1R")
        focus = [k for k in rules if not k.startswith("sweep")]
        curves = {}
        for k in focus + [k for k in rules if k.startswith("sweep")]:
            eq = np.cumsum([r["res"][k][0] - r["cost"] for r in rs])
            idx = np.linspace(0, len(eq) - 1, min(240, len(eq))).astype(int) if len(eq) else []
            curves[k] = [round(float(eq[i]), 2) for i in idx]
        blk["curves"] = curves
        # outcome distribution (net R buckets) for every rule
        edges = [-1.5, -0.95, -0.25, 0.25, 1.0, 2.0, 3.0, 99]
        blk["dist"] = {k: np.histogram([r["res"][k][0] - r["cost"] for r in rs], bins=edges)[0].tolist() for k in rules}
        blk["dist_edges"] = edges
        for mk in sorted({r["market"] for r in rs}):
            blk["by_market"][mk] = {k: describe([r for r in rs if r["market"] == mk], k) for k in focus}
        out["sets"][st] = blk
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", action="append")
    ap.add_argument("--tf", action="append")
    ap.add_argument("--out", default="mgmt.json")
    ap.add_argument("--trades", default=None, help="also keep every simulated trade here")
    a = ap.parse_args()
    mids = [m for m in (a.market or MARKETS) if os.path.exists(f"{DATA}/1m_{core.MARKET_BY_ID[m].deriv}.npz")]
    jobs = [(m, tf, 1000 + i) for i, (m, tf) in enumerate((m, tf) for m in mids for tf in (a.tf or TFS))]
    t0 = time.time()
    rows = []
    with ProcessPoolExecutor() as ex:
        for mid, tf, nb, rs in ex.map(run_slice, jobs):
            print(f"  {mid:10s} {tf:3s} {nb:6d} bars · {sum(r['set'] == 'ARIA 7.2c' for r in rs):4d} ARIA · "
                  f"{sum(r['set'] == 'Random' for r in rs):5d} random · {time.time()-t0:.0f}s", file=sys.stderr)
            rows += rs
    rows.sort(key=lambda r: r["t"])
    rep = report(rows)
    rep["markets"] = mids
    rep["generated"] = int(time.time())
    with open(a.out, "w") as f:
        json.dump(rep, f)
    if a.trades:
        with open(a.trades, "w") as f:
            json.dump(rows, f)
    for st, blk in rep["sets"].items():
        print(f"\n== {st} ==")
        for k, d in blk["all"].items():
            if not d.get("n"):
                continue
            v = blk["vs_hold"][k]
            print(f"  {k:44s} n{d['n']:5d} exp {d['exp']:+.3f}R [{d['lo']:+.2f},{d['hi']:+.2f}] win {d['win']*100:4.1f}% "
                  f"full-loss {d['full_loss']*100:4.1f}% prot {d['protected']*100:4.1f}% "
                  f"capture {d['capture'] if d['capture'] is None else round(d['capture']*100)}% "
                  f"saved {d['saved_r']:+7.1f}R cut {d['cut_r']:+7.1f}R premature {d['premature']:4d} "
                  f"hold-out {blk['holdout'][k].get('exp', float('nan')):+.3f}R "
                  f"Δhold {v['mean'] if v else float('nan'):+.3f}")
    print(f"\nwrote {a.out} in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
