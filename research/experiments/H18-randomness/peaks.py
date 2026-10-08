"""Do 'peak areas' make the come-back more certain? Deriv hourly candles, one year.
Peak entry: sell when the hour closes at its 24-hour high and at least 2 typical moves above the 24-hour mean; buy at the mirror low.
Random entry: coin toss at the same hours. Both: close at +1 typical hourly move, no stop."""
import json, random
import numpy as np
D = 'research/data/hold'
NAMES = {"1HZ50V": "Vol 50 (1s)", "1HZ25V": "Vol 25 (1s)", "1HZ75V": "Vol 75 (1s)", "1HZ100V": "Vol 100 (1s)", "R_75": "Vol 75", "R_50": "Vol 50",
         "BOOM1000": "Boom 1000", "CRASH1000": "Crash 1000"}
rng = random.Random(5)
def ride(h, l, cl, i, side, s):
    e = cl[i]; tp = e * (1 + side * s); mae = 0.0
    for j in range(i + 1, len(cl)):
        if (h[j] >= tp) if side > 0 else (l[j] <= tp):
            return True, j - i, mae
        mae = max(mae, ((e - l[j]) if side > 0 else (h[j] - e)) / e / s)
    return False, len(cl) - 1 - i, side * (cl[-1] - e) / e / s
tot = {"peak": [], "random": []}
print(f"{'index':13s} {'peak entries':>12s} {'came back':>10s} {'random':>8s} {'median wait peak/random':>24s} {'worst dip before a win peak/random':>35s}")
for sym, name in NAMES.items():
    c = json.load(open(f"{D}/{sym}_h1.json"))
    h = np.array([x["high"] for x in c]); l = np.array([x["low"] for x in c]); cl = np.array([x["close"] for x in c])
    s = float(np.std(np.diff(np.log(cl))))
    pk, rd = [], []
    for i in range(24, len(c) - 1):
        w = cl[i - 23:i + 1]; m = w.mean()
        side = 0
        if cl[i] >= w.max() and (cl[i] - m) / m >= 2 * s: side = -1
        elif cl[i] <= w.min() and (m - cl[i]) / m >= 2 * s: side = 1
        if not side: continue
        pk.append(ride(h, l, cl, i, side, s))
        rd.append(ride(h, l, cl, i, 1 if rng.random() < .5 else -1, s))
    tot["peak"] += pk; tot["random"] += rd
    f = lambda xs: (np.mean([x[0] for x in xs]) * 100, np.median([x[1] for x in xs if x[0]]), max([x[2] for x in xs if x[0]]))
    a, b = f(pk), f(rd)
    print(f"{name:13s} {len(pk):12d} {a[0]:9.1f}% {b[0]:7.1f}% {a[1]:>13.0f} h / {b[1]:.0f} h {a[2]:>25.0f}× / {b[2]:.0f}×")
f = lambda xs: (np.mean([x[0] for x in xs]) * 100, sum(1 for x in xs if not x[0]), np.mean([x[2] for x in xs if not x[0]]))
a, b = f(tot["peak"]), f(tot["random"])
print(f"ALL: peak entries {len(tot['peak'])}: came back {a[0]:.1f}%, never {a[1]} (avg {a[2]:+.0f}× a win) | random at the same hours: {b[0]:.1f}%, never {b[1]} (avg {b[2]:+.0f}×)")
