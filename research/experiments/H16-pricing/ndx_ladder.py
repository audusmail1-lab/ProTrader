"""A weekly ladder of Nasdaq-100 'Rise' contracts, 2001-2026, priced off VXN (risk-neutral) plus a markup.
Each Monday: stake f x bankroll on a 'Rise over N days' contract. Settles at expiry: payout = stake / priced p, or nothing."""
import numpy as np, sys
sys.argv = [sys.argv[0]]
exec(open('research/experiments/H16-pricing/data/ndx_bt.py').read().split('print(f"Nasdaq-100')[0])
import datetime as dt
def ladder(days, f, m):
    bank = 1.0; open_ = []; curve = []; wins = losses = 0
    for i in range(len(dates)):
        # settle
        for c in [c for c in open_ if c[0] <= i]:
            open_.remove(c); bank += c[1] if c[2] else 0.0
            wins += c[2]; losses += (not c[2])
        if dt.date.fromisoformat(dates[i]).weekday() == 0:
            j = np.searchsorted(E, E[i] + days)
            if j < len(dates):
                T = (E[j] - E[i]) / 365; s = V[i] * sqrt(T); mu = (R[i] - Q - V[i] ** 2 / 2) * T
                p = float(Phi(mu / s)) * (1 + m)
                stake = f * (bank + sum(c[3] for c in open_))      # size off total equity incl. stakes in play
                stake = min(stake, bank)
                bank -= stake; open_.append((j, stake / p, P[j] > P[i], stake))
        curve.append(bank + sum(c[3] for c in open_))
    c = np.array(curve); yrs = (E[-1] - E[0]) / 365
    dd = 1 - (c / np.maximum.accumulate(c)).min()
    return c[-1] ** (1 / yrs) - 1, dd, wins / max(1, wins + losses)
for days in (30, 91):
    for m in (0.06, 0.10, 0.15):
        out = []
        for f in (0.005, 0.01, 0.02):
            cagr, dd, wr = ladder(days, f, m)
            out.append(f"stake {f:.1%}: {cagr:+.1%}/yr, worst drawdown {dd:.0%}")
        print(f"Rise {days}d, markup {m:.0%}, won {wr:.0%} | " + " | ".join(out))
