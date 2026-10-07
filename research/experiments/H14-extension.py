import pickle, sys, statistics as st, random
sys.path.insert(0, '/home/claude/pt'); sys.path.insert(0, '/tmp/claude-0/-home-claude/76d7836d-a469-5749-8e9e-0722ccff9b7a/scratchpad/mtf')
import research_lab as lab, h14
res = pickle.load(open('/tmp/claude-0/-home-claude/76d7836d-a469-5749-8e9e-0722ccff9b7a/scratchpad/mtf/h14_trades.pkl', 'rb'))
data = lab.load_history(h14.REAL + h14.CTRL, ["15m", "1h"])
R = lab.net_r
rng = random.Random(3)
def slope_p(ts, key, n=3000):
    xs = [t[key] for t in ts]; ys = [R(t) for t in ts]
    mx, my = st.mean(xs), st.mean(ys)
    def b(xx): return sum((x - mx) * (y - my) for x, y in zip(xx, ys)) / sum((x - mx) ** 2 for x in xx)
    obs = b(xs); c = 0; xx = xs[:]
    for _ in range(n):
        rng.shuffle(xx)
        if abs(b(xx)) >= abs(obs): c += 1
    return obs, (c + 1) / (n + 1)
for group, mkts in (("REAL", h14.REAL), ("CONTROL", h14.CTRL)):
    b = lab.split_bounds({k: v for k, v in data.items() if k[0] in mkts})
    base = [t for (m, tf), ts in res.items() if m in mkts and tf == "15m" for t in ts if "ext_1h" in t]
    sp = lab.split(base, b); oos = sp["val"] + sp["holdout"]
    agree = lambda t: h14.agree(t, "1h", True)
    print(f"\n{group} 15m: mean extension (ATRs beyond the 1h EMA50 in the trade's direction): agreeing {st.mean(t['ext_1h'] for t in base if agree(t)):+.2f} vs not {st.mean(t['ext_1h'] for t in base if not agree(t)):+.2f}")
    for w, ts in (("dev", sp["dev"]), ("out-of-sample", oos)):
        s, p = slope_p(ts, "ext_1h")
        q = sorted(t["ext_1h"] for t in ts); c1, c2 = q[len(q)//3], q[2*len(q)//3]
        terc = [st.mean(R(t) for t in ts if lo <= t["ext_1h"] < hi) for lo, hi in ((-1e9, c1), (c1, c2), (c2, 1e9))]
        print(f"   {w:14s} R per extra ATR of extension {s:+.3f} (p {p:.3f}, n {len(ts)});  R by extension third (low/mid/high): " + " / ".join(f"{x:+.3f}" for x in terc))

print("\nper market and timeframe (REAL), low-extension third vs the other two, R per trade:")
b = lab.split_bounds({k: v for k, v in data.items() if k[0] in h14.REAL})
for tf in ("15m", "1h"):
    for m in h14.REAL:
        ts = [t for t in res[(m, tf)] if "ext_1h" in t]
        sp = lab.split(ts, b)
        row = []
        for w, xs in (("dev", sp["dev"]), ("oos", sp["val"] + sp["holdout"])):
            q = sorted(t["ext_1h"] for t in xs); c1 = q[len(q)//3] if q else 0
            lo = [R(t) for t in xs if t["ext_1h"] < c1]; hi = [R(t) for t in xs if t["ext_1h"] >= c1]
            row.append(f"{w}: low {st.mean(lo):+.2f} (n{len(lo)}) vs rest {st.mean(hi):+.2f} (n{len(hi)})" if lo and hi else f"{w}: n/a")
        print(f"   {m:10s} {tf}: " + " | ".join(row))
