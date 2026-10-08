"""Owning the drift instead of waiting on dips: Nasdaq-100 1986-2026, daily.
A: hold an index fund (0.2%/yr fee). B: hold a US Tech 100 CFD on Deriv (financing T-bill + 2.5%/yr).
C: CFD, long only while the close is above its 200-day average, flat otherwise (spread 0.03% per switch)."""
import numpy as np, pandas as pd
L = 'research/data/fred'
def load(i):
    df = pd.read_csv(f"{L}/{i}.csv"); df.columns = ["d", "v"]; df["v"] = pd.to_numeric(df["v"], errors="coerce"); df["d"] = pd.to_datetime(df["d"])
    return df.dropna().set_index("d")["v"]
px = load("NASDAQ100"); tb = load("DTB3").reindex(px.index).ffill().fillna(5.0) / 100
ret = px.pct_change().fillna(0); days = px.index.to_series().diff().dt.days.fillna(1)
sma = px.rolling(200).mean(); on = (px > sma).shift(1).fillna(False)
fund = ret - 0.002 / 365 * days
cfd = ret - (tb + 0.025) / 365 * days
timed = np.where(on, cfd, 0.0) - on.astype(int).diff().abs().fillna(0) * 0.0003
S = pd.DataFrame({"index fund": fund, "CFD, always long": cfd, "CFD, 200-day filter": timed}, index=px.index)["1987":]
def rep(r):
    eq = (1 + r).cumprod(); yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    return (eq.iloc[-1]) ** (1 / yrs) - 1, (eq / eq.cummax() - 1).min(), eq
print(f"{'':22s} {'1987-2026 /yr':>14s} {'worst drop':>11s} {'1987-1999':>10s} {'2000-2012':>10s} {'2013-2026':>10s}  $1,000 became")
for c in S.columns:
    g, dd, eq = rep(S[c]); parts = [rep(S[c][a:b])[0] for a, b in (("1987", "1999"), ("2000", "2012"), ("2013", "2026"))]
    print(f"{c:22s} {g*100:+13.1f}% {dd*100:10.0f}% " + " ".join(f"{x*100:+9.1f}%" for x in parts) + f"  ${1000*eq.iloc[-1]:,.0f}")
print("time in the market with the filter:", f"{on['1987':].mean()*100:.0f}%", "| switches per year:", round(on['1987':].astype(int).diff().abs().sum() / 39.8, 1))
