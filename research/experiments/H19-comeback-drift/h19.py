import math, sys
import numpy as np, pandas as pd
L = 'research/data/fred'
def load(i):
    df = pd.read_csv(f"{L}/{i}.csv"); df.columns = ["d", "v"]; df["v"] = pd.to_numeric(df["v"], errors="coerce"); df["d"] = pd.to_datetime(df["d"])
    return df.dropna().set_index("d")["v"]
ndx = load("NASDAQ100"); tb = load("DTB3").reindex(ndx.index).ffill().fillna(5.0) / 100
SPREAD, MARKUP, ACCT, SLOT, MAXOPEN = 0.0003, 0.025, 100_000.0, 0.10, 10
def run(px, rate, label, periods=True):
    px = px.astype(float); r = np.log(px).diff(); vol = r.ewm(com=60, min_periods=60).std()
    hi20 = px.rolling(20).max(); dates = px.index
    open_pos = []; closed = []; eq_curve = []; cash = 0.0
    for k in range(80, len(px)):
        d, p = dates[k], px.iloc[k]
        fin = sum(pos["notional"] for pos in open_pos) * (rate.iloc[k] + MARKUP) / 365 * ((d - dates[k - 1]).days)
        cash -= fin
        for pos in open_pos: pos["fin"] += pos["notional"] * (rate.iloc[k] + MARKUP) / 365 * ((d - dates[k - 1]).days)
        still = []
        for pos in open_pos:
            if p >= pos["tp"]:
                pnl = pos["notional"] * (p / pos["e"] - 1) - pos["notional"] * SPREAD
                cash += pnl; closed.append(dict(entry=pos["d"], exit=d, days=(d - pos["d"]).days, pnl=pnl - pos["fin"]))
            else: still.append(pos)
        open_pos = still
        v = vol.iloc[k]
        if len(open_pos) < MAXOPEN and v == v and p <= hi20.iloc[k] * math.exp(-2 * v) and (not open_pos or open_pos[-1]["d"] != d):
            open_pos.append(dict(d=d, e=p, tp=p * math.exp(v), notional=ACCT * SLOT, fin=0.0))
        mtm = sum(pos["notional"] * (p / pos["e"] - 1) for pos in open_pos)
        eq_curve.append((d, ACCT + cash + mtm, len(open_pos)))
    eq = pd.Series([x[1] for x in eq_curve], index=[x[0] for x in eq_curve])
    dd = (eq / eq.cummax() - 1).min()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / ACCT) ** (1 / yrs) - 1 if eq.iloc[-1] > 0 else -1
    c = pd.DataFrame(closed)
    print(f"{label}: {len(c)} closed, won {np.mean(c.pnl > 0)*100:.0f}% after costs; median wait {c.days.median():.0f} days, longest {c.days.max():,} days; "
          f"open at the end {len(open_pos)}; account {ACCT:,.0f} → {eq.iloc[-1]:,.0f} ({cagr*100:+.1f}%/yr), worst drawdown {dd*100:.0f}%")
    if periods:
        for a, b in (("1986", "1999"), ("2000", "2012"), ("2013", "2026")):
            seg = eq[a:b]; print(f"     {a}-{b}: {seg.iloc[0]:,.0f} → {seg.iloc[-1]:,.0f} ({(seg.iloc[-1]/seg.iloc[0]-1)*100:+.0f}%), worst drawdown {(seg/seg.cummax()-1).min()*100:.0f}%")
        worst = c.sort_values("days").tail(3)
        print("     longest waits:", "; ".join(f"bought {x.entry.date()} → back {x.exit.date()} ({x.days:,} days)" for x in worst.itertuples()))
    return eq, c
eq, c = run(ndx, tb, "Nasdaq-100 come-back, 1986-2026")
bh = ndx["1986-04":]; print(f"   (buy-and-hold Nasdaq-100 over the same span, before financing: {((bh.iloc[-1]/bh.iloc[0])**(1/((bh.index[-1]-bh.index[0]).days/365.25))-1)*100:+.1f}%/yr)")
# control: driftless random walk with the Nasdaq's daily volatility, same dates and costs, 20 runs
rng = np.random.default_rng(4); sd = float(np.log(ndx).diff().std()); res = []
for _ in range(20):
    lp = np.cumsum(rng.normal(-sd * sd / 2, sd, len(ndx))); fake = pd.Series(np.exp(lp) * 1000, index=ndx.index)
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        e2, c2 = run(fake, tb, "control", periods=False)
    res.append((e2.iloc[-1], (e2 / e2.cummax() - 1).min(), np.mean(c2.pnl > 0)))
res = np.array(res)
print(f"control, driftless random walk (synthetic-index case), 20 runs: won {res[:,2].mean()*100:.0f}% of trades; account 100,000 → median {np.median(res[:,0]):,.0f}; "
      f"ended below the start in {np.mean(res[:,0] < 100_000)*100:.0f}% of runs; median worst drawdown {np.median(res[:,1])*100:.0f}%")
