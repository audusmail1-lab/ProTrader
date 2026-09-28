"""
Summarise research.json (from research_exits.py) into plain tables.

    python research_report.py research.json [--costs costs.json]

--costs takes {market: spread_pct} measured on MT5 and re-prices every trade
with it (gross R minus spread / stop distance), replacing the estimates.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict

import sentinel_core as core

HOLDOUT = 0.30   # last 30% of the year is reported separately


def stats(rs: list[float]) -> dict:
    n = len(rs)
    if not n:
        return {"n": 0}
    m = sum(rs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in rs) / (n - 1)) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n > 1 else float("inf")
    g = sum(x for x in rs if x > 0)
    l = -sum(x for x in rs if x < 0)
    eq = pk = dd = 0.0
    for x in rs:
        eq += x; pk = max(pk, eq); dd = max(dd, pk - eq)
    return {"n": n, "exp": m, "se": se, "lo": m - 1.96 * se, "hi": m + 1.96 * se,
            "pf": g / l if l else float("inf"), "win": sum(1 for x in rs if x > 0) / n,
            "total": sum(rs), "dd": dd}


def fmt(s: dict) -> str:
    if not s.get("n"):
        return "    —"
    return (f"{s['n']:5d}  {s['exp']:+.3f}R  [{s['lo']:+.2f},{s['hi']:+.2f}]  win {s['win']*100:4.1f}%  "
            f"PF {min(s['pf'], 99):4.2f}  total {s['total']:+7.1f}R  maxDD {s['dd']:5.1f}R")


def load(path, costs=None):
    d = json.load(open(path))
    rows = []
    t0 = min(s["t0"] for s in d["slices"])
    t1 = max(s["t1"] for s in d["slices"])
    cut = t0 + (1 - HOLDOUT) * (t1 - t0)
    for sl in d["slices"]:
        for key, trades in sl["res"].items():
            model, filt, tier = key.split("|")
            for t in trades:
                r = t["r"]
                if costs and t["market"] in costs and t.get("sd"):
                    r = t["gross"] - costs[t["market"]] * t["entry"] / t["sd"]
                rows.append({**t, "model": model, "filt": filt, "tier_sel": tier, "r": r,
                             "holdout": t["t"] >= cut})
    rows.sort(key=lambda x: x["t"])
    return d, rows, (t0, cut, t1)


def table(rows, title, key, where=lambda t: True):
    g = defaultdict(list)
    for t in rows:
        if where(t):
            g[key(t)].append(t["r"])
    print(f"\n{title}")
    for k in sorted(g, key=str):
        print(f"  {str(k):42s} {fmt(stats(g[k]))}")
    return {k: stats(v) for k, v in g.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--costs")
    a = ap.parse_args()
    costs = json.load(open(a.costs)) if a.costs else None
    d, rows, (t0, cut, t1) = load(a.path, costs)
    import time as _t
    day = lambda x: _t.strftime("%Y-%m-%d", _t.gmtime(x))
    print(f"Period {day(t0)} → {day(t1)} · hold-out from {day(cut)} · costs: {'MT5 measured' if costs else 'estimates'}")
    real = lambda t: t["mode"] == "real"
    syn = lambda t: t["mode"] == "synthetic"

    out = {}
    out["exit_exec"] = table(rows, "1. EXIT MODELS — real markets, exec-ready (9+/10), no filter",
                             lambda t: t["model"], lambda t: real(t) and t["tier_sel"] == "exec" and t["filt"] == "all")
    out["exit_qual"] = table(rows, "1b. EXIT MODELS — real markets, qualified or better (8+/10), no filter",
                             lambda t: t["model"], lambda t: real(t) and t["tier_sel"] == "qualified+" and t["filt"] == "all")
    table(rows, "1c. same, HOLD-OUT only (last 30%)",
          lambda t: t["model"], lambda t: real(t) and t["tier_sel"] == "qualified+" and t["filt"] == "all" and t["holdout"])

    out["mtf"] = table(rows, "2. 4h TREND FILTER — real markets, 8+/10, by exit model × filter",
                       lambda t: f"{t['model']} · {t['filt']}", lambda t: real(t) and t["tier_sel"] == "qualified+")
    table(rows, "2b. 4h TREND FILTER — HOLD-OUT only",
          lambda t: f"{t['model']} · {t['filt']}", lambda t: real(t) and t["tier_sel"] == "qualified+" and t["holdout"])

    table(rows, "3. PER MARKET — real, 8+/10, fixed 2.5R, all vs 4h-aligned",
          lambda t: f"{t['market']} {t['tf']} · {t['filt']}",
          lambda t: real(t) and t["tier_sel"] == "qualified+" and t["model"] == "fixed_2.5R" and t["filt"] in ("all", "mtf_aligned"))

    table(rows, "4. SYNTHETIC FAMILIES — 8+/10, fixed 2.5R, all vs 4h-aligned",
          lambda t: f"{t['market']} {t['tf']} · {t['filt']}",
          lambda t: syn(t) and t["tier_sel"] == "qualified+" and t["model"] == "fixed_2.5R" and t["filt"] in ("all", "mtf_aligned"))
    table(rows, "4b. SYNTHETICS — exit models, 8+/10, no filter",
          lambda t: t["model"], lambda t: syn(t) and t["tier_sel"] == "qualified+" and t["filt"] == "all")

    def ew(t):
        if not t.get("ew"):
            return "no count"
        return f"{t['ew']} · 4h {t['mtf']}"
    table(rows, "5. ELLIOTT (soft) × 4h trend — real, 8+/10, fixed 2.5R",
          ew, lambda t: real(t) and t["tier_sel"] == "qualified+" and t["model"] == "fixed_2.5R" and t["filt"] == "all")

    json.dump({k: {str(kk): vv for kk, vv in v.items()} for k, v in out.items()},
              open(a.path.replace(".json", "_summary.json"), "w"), default=str)


if __name__ == "__main__":
    main()
