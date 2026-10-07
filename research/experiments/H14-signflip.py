import pickle, sys, random, statistics as st, time, calendar
sys.path.insert(0, '/home/claude/pt'); sys.path.insert(0, '/tmp/claude-0/-home-claude/76d7836d-a469-5749-8e9e-0722ccff9b7a/scratchpad/mtf')
import research_lab as lab, h14
res = pickle.load(open('/tmp/claude-0/-home-claude/76d7836d-a469-5749-8e9e-0722ccff9b7a/scratchpad/mtf/h14_trades.pkl', 'rb'))
data = lab.load_history(h14.REAL + h14.CTRL, ["15m", "1h"])
R = lambda t: lab.net_r(t)
rng = random.Random(7)

def diff(acc, rej):
    return (st.mean(map(R, acc)) - st.mean(map(R, rej))) if acc and rej else None

def perm_p(acc, rej, n=5000):
    obs = diff(acc, rej); pool = acc + rej; k = len(acc); c = 0
    xs = [R(t) for t in pool]
    for _ in range(n):
        rng.shuffle(xs)
        d = st.mean(xs[:k]) - st.mean(xs[k:])
        if abs(d) >= abs(obs) - 1e-12: c += 1
    return (c + 1) / (n + 1)

def boot_ci(acc, rej, n=3000):
    a = [R(t) for t in acc]; r = [R(t) for t in rej]; ds = []
    for _ in range(n):
        ds.append(st.mean(rng.choices(a, k=len(a))) - st.mean(rng.choices(r, k=len(r))))
    ds.sort(); return ds[int(.025 * n)], ds[int(.975 * n)]

for group, mkts in (("REAL", h14.REAL), ("CONTROL", h14.CTRL)):
    b = lab.split_bounds({k: v for k, v in data.items() if k[0] in mkts})
    print(f"\n######## {group}   windows: dev → {time.strftime('%Y-%m-%d', time.gmtime(b['dev_end']))}, val → {time.strftime('%Y-%m-%d', time.gmtime(b['val_end']))}, holdout → {time.strftime('%Y-%m-%d', time.gmtime(b['end']))}")
    for fname, (tf, fn) in h14.FILTERS.items():
        base = [t for (m, tf2), ts in res.items() if m in mkts and tf2 == tf for t in ts]
        sp = lab.split(base, b)
        oos = sp["val"] + sp["holdout"]
        a_d = [t for t in sp["dev"] if fn(t)]; r_d = [t for t in sp["dev"] if not fn(t)]
        a_o = [t for t in oos if fn(t)]; r_o = [t for t in oos if not fn(t)]
        d_dev, d_oos = diff(a_d, r_d), diff(a_o, r_o)
        p_dev, p_oos = perm_p(a_d, r_d), perm_p(a_o, r_o)
        lo, hi = boot_ci(a_o, r_o)
        # month-by-month out of sample
        months = {}
        for t in oos:
            mo = time.strftime('%Y-%m', time.gmtime(t["opened_at"]))
            months.setdefault(mo, ([], []))[0 if fn(t) else 1].append(t)
        signs = [(mo, round(diff(a, r), 2)) for mo, (a, r) in sorted(months.items()) if len(a) >= 5 and len(r) >= 5]
        print(f"{fname:10s} accepted−rejected (R/trade): dev {d_dev:+.3f} (p {p_dev:.3f}, n {len(a_d)}/{len(r_d)})  "
              f"out-of-sample {d_oos:+.3f} [95% {lo:+.3f},{hi:+.3f}] (p {p_oos:.3f}, n {len(a_o)}/{len(r_o)})")
        print(f"           OOS by month (acc−rej, months with ≥5 each): {signs}")
