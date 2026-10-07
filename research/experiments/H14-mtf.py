"""H14: ARIA multi-timeframe agreement as a filter on ARIA 7.2c trades."""
import json, sys, time, bisect
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, '/home/claude/pt')
import research_lab as lab, sentinel_core as core

REAL = ["frxNAS100", "frxXAUUSD", "cryBTCUSD"]
CTRL = ["R_75", "1HZ75V"]
TF_UP = {"15m": "1h", "1h": "4h"}

def job(args):
    mid, tf = args
    data = lab.load_history([mid], ["15m", "1h", "4h"])
    m = core.MARKET_BY_ID[mid]
    bars, h4 = data[(mid, tf)], data.get((mid, "4h"))
    reads = lab.reads_for(m, tf, bars)
    trades = lab.replay_slice({"gates": {"cost_cap": 1e9}}, m, tf, bars, h4, reads)     # cost_cap never binds: base + cost_r annotation
    up = {}
    for utf in ("1h", "4h"):
        ub = data.get((mid, utf))
        if not ub: continue
        ur = lab.reads_for(m, utf, ub)
        closes = [b["time"] + core.TF_SEC[utf] for b in ub]
        up[utf] = (closes, ur)
    def read_at(utf, t):
        if utf not in up: return None
        closes, ur = up[utf]
        i = bisect.bisect_right(closes, t) - 1
        return ur[i] if i >= 0 else None
    for t in trades:
        T = t["opened_at"]
        for utf in ("1h", "4h"):
            r = read_at(utf, T)
            t[f"up_{utf}"] = None if not r else {"dir": r["dir"], "verdict": r["verdict"], "score": r["score"]}
    return (mid, tf), trades

def agree(t, utf, strong=True):
    r = t.get(f"up_{utf}")
    if not r or r["dir"] != t["dir"]: return False
    return r["verdict"] in ("EXEC_READY", "QUALIFIED") if strong else r["score"] >= 7

FILTERS = {
    "F1_strong": ("15m", lambda t: agree(t, "1h", True)),
    "F1_loose": ("15m", lambda t: agree(t, "1h", False)),
    "F2_strong": ("1h", lambda t: agree(t, "4h", True)),
    "F3_stack": ("15m", lambda t: agree(t, "1h", True) and agree(t, "4h", False)),
}

def main():
    t0 = time.time()
    slices = [(m, tf) for m in REAL + CTRL for tf in ("15m", "1h")]
    with ProcessPoolExecutor(max_workers=2) as ex:
        res = dict(ex.map(job, slices))
    data = lab.load_history(REAL + CTRL, ["15m", "1h"])
    out = {"seconds": None, "groups": {}}
    for group, mkts in (("real", REAL), ("control", CTRL)):
        b = lab.split_bounds({k: v for k, v in data.items() if k[0] in mkts})
        for fname, (tf, fn) in FILTERS.items():
            base = [t for (m, tf2), ts in res.items() if m in mkts and tf2 == tf for t in ts]
            sp = lab.split(base, b)
            row = {"tf": tf, "agree_rate": round(sum(map(fn, base)) / max(1, len(base)), 3)}
            for w in ("dev", "val", "holdout"):
                mask = [fn(t) for t in sp[w]]
                acc = [t for t, a in zip(sp[w], mask) if a]
                rej = [t for t, a in zip(sp[w], mask) if not a]
                pl = lab.placebo_test(sp[w], mask)
                row[w] = {"base": lab.metrics(sp[w], boot=0).get("expectancy_r"), "n_base": len(sp[w]),
                          "acc": lab.metrics(acc, boot=0).get("expectancy_r"), "n_acc": len(acc),
                          "acc_x15": lab.metrics(acc, 1.5, boot=0).get("expectancy_r"),
                          "rej": lab.metrics(rej, boot=0).get("expectancy_r"), "p_net": pl.get("p_net"), "p_gross": pl.get("p_gross")}
            # carried by one market? drop the best market (by accepted total R, all windows)
            acc_all = [t for t in base if fn(t)]
            by = {}
            for t in acc_all: by.setdefault(t["market"], []).append(t)
            if by:
                best = max(by, key=lambda k: sum(lab.net_r(x) for x in by[k]))
                rest = [t for t in acc_all if t["market"] != best]
                row["without_best_market"] = {"dropped": best, "exp": lab.metrics(rest, boot=0).get("expectancy_r"), "n": len(rest)}
            row["by_market_acc"] = {k: (len(v), round(sum(lab.net_r(x) for x in v) / len(v), 3)) for k, v in by.items()}
            out["groups"].setdefault(group, {})[fname] = row
    out["seconds"] = round(time.time() - t0)
    json.dump(out, open('/tmp/claude-0/-home-claude/76d7836d-a469-5749-8e9e-0722ccff9b7a/scratchpad/mtf/h14.result.json', 'w'), indent=1)
    for g, fs in out["groups"].items():
        print(f"\n== {g}")
        for f, r in fs.items():
            print(f"{f:10s} tf {r['tf']} agree {r['agree_rate']:.2f}  " + "  ".join(
                f"{w}: base {r[w]['base']:+.3f} (n{r[w]['n_base']}) acc {r[w]['acc'] if r[w]['acc'] is not None else float('nan'):+.3f} (n{r[w]['n_acc']}) x1.5 {r[w]['acc_x15'] if r[w]['acc_x15'] is not None else float('nan'):+.3f} rej {r[w]['rej'] if r[w]['rej'] is not None else float('nan'):+.3f} p {r[w]['p_net']}"
                for w in ("dev", "val", "holdout")))
            print("           without best market:", r.get("without_best_market"), " by market:", r.get("by_market_acc"))
    print("seconds", out["seconds"])
if __name__ == "__main__":
    main()
