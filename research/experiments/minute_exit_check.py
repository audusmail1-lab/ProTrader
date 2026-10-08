"""Is Joel's $100 rule's forward advantage real, or an artefact of checking exits on 15m/1h bars?
Re-run the model exit (7.2c: trail 1R after +1R) and the usd100 shadow (BE then trail 0.27R after +0.27R)
on 1-minute candles for the same forward trades. Read-only public data."""
import asyncio, json, sys, os, math
sys.path.insert(0, '/home/claude/pt')
import sentinel_core as core, websockets
D = 'research/data/forward'
T = round(core.SHADOW_USD / (core.SHADOW_BALANCE * 0.01), 4)
trades = [t for t in json.load(open(f'{D}/feed.json'))["closed"] if t.get("status") in ("win", "loss", "timeout")]
async def fetch(ws, sym, start, end):
    out = []; e = end
    while True:
        await ws.send(json.dumps({"ticks_history": sym, "start": start, "end": e, "count": 5000, "style": "candles", "granularity": 60}))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 30))
            if m.get("msg_type") == "candles" or m.get("error"): break
        if m.get("error"): print(sym, m["error"]["message"]); break
        c = m.get("candles") or []
        if not c: break
        if out and c[-1]["epoch"] >= out[0]["epoch"]: c = [x for x in c if x["epoch"] < out[0]["epoch"]]
        if not c: break
        out = c + out
        if c[0]["epoch"] <= start: break
        e = c[0]["epoch"] - 1
        await asyncio.sleep(0.25)
    return out
def walk(t, bars, arm, dist, trig, timeout_s):
    s = 1 if t["dir"] == "buy" else -1; e0, d = t["entry"], t["sl_dist"]
    stop = t["sl"]; best = 0.0
    for b in bars:
        if b["epoch"] < t["opened_at"]: continue
        if b["epoch"] >= t["opened_at"] + timeout_s:
            return s * (b["open"] - e0) / d, "timeout"
        lo = s * ((b["low"] if s > 0 else b["high"]) - e0) / d
        hi = s * ((b["high"] if s > 0 else b["low"]) - e0) / d
        op = s * (b["open"] - e0) / d
        st = s * (stop - e0) / d
        if op <= st: return op, "gap"
        if lo <= st: return st, "stop"
        best = max(best, hi)
        new = stop
        if trig is not None and best >= trig and s * (e0 - new) > 0: new = e0
        if best >= arm:
            cand = e0 + s * (best - dist) * d
            if s * (cand - new) > 0: new = cand
        stop = new
    return None, "open"
async def main():
    by = {}
    for t in trades: by.setdefault(t["market"], []).append(t)
    rows = []
    async with websockets.connect(core.DERIV_WS_URL, open_timeout=15, max_size=2**25) as ws:
        for mk, ts in by.items():
            f = f'{D}/m1/{mk}.json'
            start = min(t["opened_at"] for t in ts) - 60
            end = max(t["opened_at"] + 96 * core.TF_SEC[t["tf"]] for t in ts) + 60
            if os.path.exists(f): bars = json.load(open(f))
            else:
                bars = await fetch(ws, mk, start, end); json.dump(bars, open(f, "w"))
            got = bars[0]["epoch"] if bars else None
            for t in ts:
                tb = [b for b in bars if t["opened_at"] - 60 <= b["epoch"] <= t["opened_at"] + 96 * core.TF_SEC[t["tf"]] + 60]
                if not tb or tb[0]["epoch"] > t["opened_at"] + 60: continue
                to = 96 * core.TF_SEC[t["tf"]]
                m_r, m_how = walk(t, tb, 1.0, 1.0, None, to)
                u_r, u_how = walk(t, tb, T, T, T, to)
                if m_r is None or u_r is None: continue
                sh = (t.get("shadow") or {}).get("usd100") or {}
                bar_u = sh.get("gross") if sh.get("state") == "closed" else None
                bar_m = (t.get("r") or 0) + (t.get("cost_r") or 0)
                rows.append(dict(id=t["id"], mode=t["mode"], tf=t["tf"], bar_m=bar_m, bar_u=bar_u, min_m=m_r, min_u=u_r))
            print(mk, len(ts), "trades,", len([r for r in rows if r["id"].startswith(mk)]), "covered by 1m data from", got)
    json.dump(rows, open(f'{D}/minute_rows.json', "w"))
    def ci(xs):
        n = len(xs); m = sum(xs) / n; sd = (sum((x - m) ** 2 for x in xs) / (n - 1)) ** .5
        return m, 1.96 * sd / n ** .5, n
    for label, sel in (("all", lambda r: True), ("synthetic", lambda r: r["mode"] == "synthetic"), ("real", lambda r: r["mode"] == "real")):
        rr = [r for r in rows if sel(r) and r["bar_u"] is not None]
        if len(rr) < 3: continue
        a = ci([r["bar_u"] - r["bar_m"] for r in rr]); b = ci([r["min_u"] - r["min_m"] for r in rr])
        c = ci([r["min_m"] - r["bar_m"] for r in rr]); dd = ci([r["min_u"] - r["bar_u"] for r in rr])
        print(f"{label:9s} n {a[2]:3d} | usd100 − model on 15m/1h bars {a[0]:+.3f} ±{a[1]:.3f} | on 1-minute bars {b[0]:+.3f} ±{b[1]:.3f} | minute vs bar: model {c[0]:+.3f}, usd100 {dd[0]:+.3f}")
asyncio.run(main())
