"""Probe for the Drift engine: can it live inside the 1% / 2% / 3-position rules the EA enforces?
Nasdaq-100 1987-2026, daily. Long while the close is above its 200-day average; flat below. Deriv CFD costs
(0.03% spread per trade, financing T-bill + 2.5%/yr on open notional).
  A  exposure rule: 1x the account, exit on the 200-day line (the 40-year test).
  B  your rules: each unit risks 1% of equity at a stop 8% below its entry; when a unit's stop can sit at its entry
     (price 8% up) it becomes risk-free and another unit may be added; at most 3 units (EA: 3 positions, 2% open risk).
  C  your rules with a wider 15% stop (smaller units, fewer stop-outs)."""
import numpy as np, pandas as pd
L = 'research/data/fred'
def load(i):
    df = pd.read_csv(f"{L}/{i}.csv"); df.columns = ["d", "v"]; df["v"] = pd.to_numeric(df["v"], errors="coerce"); df["d"] = pd.to_datetime(df["d"])
    return df.dropna().set_index("d")["v"]
px = load("NASDAQ100"); tb = load("DTB3").reindex(px.index).ffill().fillna(5.0) / 100
sma = px.rolling(200).mean()
def sim(mode, k=0.08, maxu=3):
    eq = 1.0; units = []; curve = []; stops = 0; adds = 0
    dates = px.index
    for i in range(200, len(px)):
        p, d = px.iloc[i], dates[i]; dd = (d - dates[i - 1]).days
        # financing + mark to market
        for u in units:
            eq += u["n"] * (p / u["last"] - 1) - u["n"] * (tb.iloc[i] + 0.025) / 365 * dd; u["last"] = p
        above = p > sma.iloc[i]
        # stops (checked on the close: conservative-ish for a daily system)
        keep = []
        for u in units:
            if mode != "A" and p <= u["stop"]: eq -= u["n"] * 0.0003; stops += 1
            else: keep.append(u)
        units = keep
        if not above and units:
            eq -= sum(u["n"] for u in units) * 0.0003; units = []
        if above:
            if mode == "A":
                if not units: units = [dict(n=eq, last=p, stop=0)]; eq -= eq * 0.0003
            else:
                for u in units:
                    if p >= u["entry"] * (1 + k): u["stop"] = max(u["stop"], u["entry"])     # risk-free
                risky = sum(1 for u in units if u["stop"] < u["entry"])
                if len(units) < maxu and risky == 0 and eq > 0:
                    n = eq * 0.01 / k; units.append(dict(n=n, last=p, entry=p, stop=p * (1 - k))); eq -= n * 0.0003
                    adds += len(units) > 1
        curve.append((d, eq, sum(u["n"] for u in units) / eq if eq > 0 else 0))
    c = pd.DataFrame(curve, columns=["d", "eq", "expo"]).set_index("d")
    yrs = (c.index[-1] - c.index[0]).days / 365.25
    g = c["eq"].iloc[-1] ** (1 / yrs) - 1; dd = (c["eq"] / c["eq"].cummax() - 1).min()
    part = lambda a, b: (c["eq"][a:b].iloc[-1] / c["eq"][a:b].iloc[0]) ** (1 / max(1, int(b) - int(a) + 1)) - 1
    return g, dd, c.expo.mean(), [part(a, b) for a, b in (("1987", "1999"), ("2000", "2012"), ("2013", "2026"))], stops, c["eq"].iloc[-1]
print(f"{'':42s} {'per year':>9s} {'worst drop':>11s} {'avg exposure':>13s} {'87-99':>7s} {'00-12':>7s} {'13-26':>7s} {'$10k became':>12s}")
for label, mode, k in (("A  1x, 200-day exit (exposure rule)", "A", 0), ("B  your 1% rule, 8% stop, up to 3 units", "B", 0.08), ("C  your 1% rule, 15% stop, up to 3 units", "C", 0.15)):
    g, dd, ex, parts, stops, end = sim(mode, k or 0.08)
    print(f"{label:42s} {g*100:+8.1f}% {dd*100:10.0f}% {ex*100:12.0f}% " + " ".join(f"{x*100:+6.1f}%" for x in parts) + f" {10000*end:>12,.0f}")
tbr = tb["1987":].mean(); print(f"(3-month T-bill over the same years averaged {tbr*100:.1f}%/yr; Deriv pays nothing on idle cash)")

# where does A's worst drop happen, and what does buy-and-hold do over the same span?
def curve_A():
    eq = 1.0; n = 0; last = None; out = []
    for i in range(200, len(px)):
        p, d = px.iloc[i], px.index[i]; dd = (d - px.index[i - 1]).days
        if n: eq += n * (p / last - 1) - n * (tb.iloc[i] + 0.025) / 365 * dd
        last = p
        if p > sma.iloc[i] and not n: n = eq; eq -= n * 0.0003
        elif p <= sma.iloc[i] and n: eq -= n * 0.0003; n = 0
        else: n = eq if n else 0
        out.append((d, eq))
    return pd.Series(dict(out))
a = curve_A(); dd = a / a.cummax() - 1
lo = dd.idxmin(); hi = a[:lo].idxmax()
print(f"A worst drop {dd.min()*100:.0f}% from {hi.date()} to {lo.date()}; index over the same span {px[lo]/px[hi]*100-100:+.0f}%")
for y in ("2000", "2001", "2002", "2008", "2022"):
    s = a[y]; print(y, f"A {s.iloc[-1]/s.iloc[0]*100-100:+.0f}%  index {px[y].iloc[-1]/px[y].iloc[0]*100-100:+.0f}%")
yrs = (a.index[-1] - a.index[0]).days / 365.25
print(f"A daily-rebalanced 1x: {a.iloc[-1]**(1/yrs)*100-100:+.1f}%/yr; buy-and-hold index {(px.iloc[-1]/px.iloc[200])**(1/yrs)*100-100:+.1f}%/yr (no dividends)")
