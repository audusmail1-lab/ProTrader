"""Deriv's own process (Vol 50 (1s): geometric random walk, 50% a year, as verified on its ticks), 2,000 simulated years.
'Hold until profit': every 12 h enter by coin toss, close at +1 hourly move (sized so that is $72, Joel's average win), no stop.
Account $10,000. A year ends early if equity (closed profit + open positions) falls to zero."""
import numpy as np
rng = np.random.default_rng(3)
SIG, H = 0.50, 24 * 365
s = SIG / np.sqrt(8760)
WIN_USD, ACCT, EVERY = 72.0, 10_000.0, 12
notional = WIN_USD / s
YEARS = 2000
out = []
for y in range(YEARS):
    lp = np.concatenate([[0.0], np.cumsum(rng.normal(-s * s / 2, s, H))])
    entries = np.arange(0, H, EVERY); side = rng.choice([-1.0, 1.0], len(entries))
    e = lp[entries]; open_ = np.ones(len(entries), bool); closed_pnl = 0.0; ruined = None; worst_eq = ACCT; max_open = 0
    started = np.zeros(len(entries), bool)
    for t in range(1, H + 1):
        started |= entries < t
        act = open_ & started
        if act.any():
            move = side[act] * (lp[t] - e[act])
            hit = move >= s
            if hit.any():
                idx = np.where(act)[0][hit]
                closed_pnl += WIN_USD * len(idx); open_[idx] = False
                act = open_ & started
            if t % 6 == 0 or t == H:
                fl = (notional * (np.exp(side[act] * (lp[t] - e[act])) - 1)).sum() if act.any() else 0.0   # sides' P&L in $ (short ≈ −long)
                eq = ACCT + closed_pnl + fl; worst_eq = min(worst_eq, eq); max_open = max(max_open, int(act.sum()))
                if eq <= 0 and ruined is None:
                    ruined = t; break
    act = open_ & started
    fl = (notional * (np.exp(side[act] * (lp[min(t, H)] - e[act])) - 1)).sum() if act.any() else 0.0
    out.append((closed_pnl, fl, ruined is not None, worst_eq, max_open, int(act.sum())))
a = np.array(out, dtype=float)
net = np.where(a[:, 2] > 0, -ACCT, a[:, 0] + a[:, 1])
print(f"closed profit, median year: ${np.median(a[:,0]):,.0f}  (that is {np.median(a[:,0])/WIN_USD:.0f} winning trades)")
print(f"years that ended with the account wiped out: {a[:,2].mean()*100:.1f}%")
print(f"years ahead (closed + open, account intact): {np.mean((net > 0))*100:.0f}%   median year {np.median(net):+,.0f}   mean year {net.mean():+,.0f}")
print(f"open positions at the end of a surviving year: median {np.median(a[a[:,2]==0,5]):.0f}, their median floating loss ${np.median(a[a[:,2]==0,1]):,.0f}")
print(f"lowest equity reached in a year (median of years): ${np.median(a[:,3]):,.0f}; in 1 year of 10: below ${np.percentile(a[:,3],10):,.0f}")
