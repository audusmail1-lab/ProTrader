"""Hold-until-profit on Vol 50 (1s) at different sizes: $10,000 account, two entries a day, no stop, one year."""
import numpy as np
rng = np.random.default_rng(11)
SIG, H, ACCT, EVERY = 0.50, 24 * 365, 10_000.0, 12
s = SIG / np.sqrt(8760)
def year(win_usd):
    notional = win_usd / s
    lp = np.concatenate([[0.0], np.cumsum(rng.normal(-s * s / 2, s, H))])
    entries = np.arange(0, H, EVERY); side = rng.choice([-1.0, 1.0], len(entries))
    e = lp[entries]; open_ = np.ones(len(entries), bool); closed = 0.0; worst = ACCT
    for t in range(1, H + 1):
        act = open_ & (entries < t)
        if not act.any(): continue
        mv = side[act] * (lp[t] - e[act]); hit = mv >= s
        if hit.any():
            idx = np.where(act)[0][hit]; closed += win_usd * len(idx); open_[idx] = False; act = open_ & (entries < t)
        if t % 6 == 0 and act.any():
            d = lp[t] - e[act]
            fl = (notional * np.where(side[act] > 0, np.exp(d) - 1, 1 - np.exp(d))).sum()
            eq = ACCT + closed + fl; worst = min(worst, eq)
            if eq <= 0: return closed, -ACCT, True, worst
    act = open_ & (entries < H); d = lp[H] - e[act]
    fl = (notional * np.where(side[act] > 0, np.exp(d) - 1, 1 - np.exp(d))).sum()
    return closed, closed + fl, False, worst
print(f"{'win per trade':>13s} {'closed profit (median yr)':>26s} {'wiped out':>10s} {'down 50%+ at some point':>24s} {'year ahead':>11s} {'average year':>13s}")
for w in (72, 36, 18, 9):
    r = np.array([year(w) for _ in range(500)], dtype=float)
    print(f"{'$'+str(w):>13s} {np.median(r[:,0]):>24,.0f} $ {r[:,2].mean()*100:8.0f}% {np.mean(r[:,3] <= ACCT*0.5)*100:22.0f}% {np.mean(r[:,1] > 0)*100:9.0f}% {r[:,1].mean():>+12,.0f}")
