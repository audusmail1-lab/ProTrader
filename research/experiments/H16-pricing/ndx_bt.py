"""25 years of Nasdaq-100: if a broker prices binary contracts off market implied volatility (VXN) with a risk-neutral drift,
how would buying them have done? Contracts: 'Higher than today' (equity drift) and 'Ends between +/- k sigma' (volatility premium)."""
import csv, sys
import numpy as np
from math import erf, sqrt, log
D = 'research/experiments/H16-pricing/data/long'
def load(name):
    out = {}
    for r in csv.DictReader(open(f"{D}/{name}.csv")):
        k = list(r.keys())[1]
        try: out[r["observation_date"]] = float(r[k])
        except ValueError: pass
    return out
px, vx, tb = load("NASDAQ100"), load("VXNCLS"), load("DTB3")
dates = sorted(d for d in px if d in vx)
P = np.array([px[d] for d in dates]); V = np.array([vx[d] for d in dates]) / 100
last_tb = 0.0; R = []
for d in dates:
    last_tb = tb.get(d, last_tb); R.append(last_tb / 100)
R = np.array(R); Q = 0.008                                     # Nasdaq-100 dividend yield, roughly
import datetime as dt
E = np.array([dt.date.fromisoformat(d).toordinal() for d in dates])
Phi = np.vectorize(lambda x: 0.5 * (1 + erf(x / sqrt(2))))
def run(days, kind, k=1.0):
    rows = []
    for i in range(len(dates)):
        j = np.searchsorted(E, E[i] + days)
        if j >= len(dates): break
        T = (E[j] - E[i]) / 365; s = V[i] * sqrt(T); mu = (R[i] - Q - V[i] ** 2 / 2) * T
        x = log(P[j] / P[i])
        if kind == "higher":
            p = float(Phi(mu / s)); win = x > 0
        else:
            b = k * s; p = float(Phi((b - mu) / s) - Phi((-b - mu) / s)); win = -b < x < b
        rows.append((dates[i], p, win))
    return rows
def report(rows, label):
    p = np.array([r[1] for r in rows]); w = np.array([r[2] for r in rows], float); yrs = np.array([int(r[0][:4]) for r in rows])
    out = [label, f"n {len(rows)}", f"fair p (avg) {p.mean():.3f}", f"won {w.mean():.3f}"]
    for m in (0.00, 0.03, 0.06, 0.10):
        ev = w / (p * (1 + m)) - 1
        # one entry per ~30 days to get roughly independent samples for the error bar
        idx = np.arange(0, len(ev), 21)
        se = ev[idx].std() / sqrt(len(idx))
        out.append(f"markup {m:.0%}: EV {ev.mean():+.1%} (±{2*se:.1%})")
    by = {y: (w[yrs == y] / (p[yrs == y] * 1.06) - 1).mean() for y in sorted(set(yrs))}
    worst = sorted(by.items(), key=lambda kv: kv[1])[:4]
    pos = np.mean([v > 0 for v in by.values()])
    print(" | ".join(out)); print(f"     at 6% markup: {pos:.0%} of years positive; worst years {[(y, f'{v:+.0%}') for y, v in worst]}")
print(f"Nasdaq-100 {dates[0]} → {dates[-1]}, {len(dates)} days with VXN")
for days in (30, 91, 182, 365):
    report(run(days, "higher"), f"HIGHER {days}d")
for days in (7, 30):
    for k in (0.5, 1.0, 1.5):
        report(run(days, "range", k), f"ENDS BETWEEN ±{k}σ {days}d")

print("\nSub-periods (6% markup) — 2001-2012 the Nasdaq-100 went nowhere, so this separates the volatility premium from the bull market:")
for days, kind, k in ((30, "higher", 0), (91, "higher", 0), (365, "higher", 0), (7, "range", 1.0), (30, "range", 1.0)):
    rows = run(days, kind, k or 1.0)
    for a, b in (("2001", "2012"), ("2013", "2026")):
        sub = [r for r in rows if a <= r[0][:4] <= b]
        p = np.array([r[1] for r in sub]); w = np.array([r[2] for r in sub], float)
        ev = w / (p * 1.06) - 1
        print(f"  {kind.upper()}{'' if kind == 'higher' else f' ±{k}σ'} {days}d {a}-{b}: won {w.mean():.3f} vs fair {p.mean():.3f}  EV {ev.mean():+.1%}")
