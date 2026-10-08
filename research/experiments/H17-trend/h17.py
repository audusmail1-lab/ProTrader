import csv, math, sys
import numpy as np, pandas as pd
L = 'research/data/fred'
SER = {  # FRED id: (name, invert to USD-quote?, spread %)
    "NASDAQ100": ("US Tech 100", False, 0.03), "NIKKEI225": ("Japan 225", False, 0.03), "DCOILWTICO": ("Oil WTI", False, 0.05),
    "CBBTCUSD": ("BTC/USD", False, 0.15), "CBETHUSD": ("ETH/USD", False, 0.15),
    "DEXUSEU": ("EUR/USD", False, 0.02), "DEXJPUS": ("USD/JPY", False, 0.02), "DEXUSUK": ("GBP/USD", False, 0.02),
    "DEXUSAL": ("AUD/USD", False, 0.02), "DEXCAUS": ("USD/CAD", False, 0.02), "DEXSZUS": ("USD/CHF", False, 0.02),
    "DEXUSNZ": ("NZD/USD", False, 0.02), "DEXMXUS": ("USD/MXN", False, 0.03)}
FIN = 0.025
def load(i):
    df = pd.read_csv(f"{L}/{i}.csv"); df.columns = ["d", "v"]
    df["v"] = pd.to_numeric(df["v"], errors="coerce"); df["d"] = pd.to_datetime(df["d"])
    return df.dropna().set_index("d")["v"]
px = pd.DataFrame({SER[i][0]: load(i) for i in SER}).sort_index()
px = px[px.index >= "1984-01-01"].ffill(limit=5).clip(lower=1.0e-2)    # WTI printed below zero once (Apr 2020)
ret = np.log(px).diff()
vol = ret.ewm(com=60, min_periods=60).std() * math.sqrt(252)
spread = pd.Series({SER[i][0]: SER[i][2] / 100 for i in SER})
fridays = px.index[px.index.dayofweek == 4]
def run(lbs, start="1986-01-01"):
    sig = sum(np.sign(np.log(px).diff(lb)) for lb in lbs) / len(lbs)
    active = (px.notna() & vol.notna() & sig.notna())
    n_act = active.sum(axis=1).clip(lower=1)
    w = (sig * (0.10 / vol)).div(n_act, axis=0).where(active, 0.0)
    w = w.copy(); w.loc[~w.index.isin(fridays)] = np.nan
    w = w.ffill().shift(1).fillna(0.0)                                        # set on Friday close, held from next day
    gross = (w * ret.fillna(0)).sum(axis=1)
    turn = (w.diff().abs() * spread).sum(axis=1)
    fin = w.abs().sum(axis=1) * FIN / 252
    net = (gross - turn - fin)[start:]
    return net, gross[start:]
def stats(r):
    sh = r.mean() / r.std() * math.sqrt(252) if r.std() > 0 else float("nan")
    eq = r.cumsum(); dd = (np.exp(eq) / np.exp(eq.cummax()) - 1).min()
    return sh, r.mean() * 252, dd
net, gross = run([252])
sh, ann, dd = stats(net); shg, anng, _ = stats(gross)
print(f"12-month rule 1986-2026: net Sharpe {sh:.2f} ({ann*100:+.1f}%/yr, worst drawdown {dd*100:.0f}%), before costs {shg:.2f} ({anng*100:+.1f}%/yr)")
for a, b in (("1986", "1999"), ("2000", "2012"), ("2013", "2026")):
    s2 = stats(net[a:b]); print(f"   {a}-{b}: net Sharpe {s2[0]:+.2f}, {s2[1]*100:+.1f}%/yr, worst drawdown {s2[2]*100:.0f}%")
roll = net.rolling(756).sum().dropna(); print(f"   rolling 3-year windows positive: {(roll > 0).mean()*100:.0f}%")
for name, lbs in (("3-month", [63]), ("6-month", [126]), ("3/6/12 blend", [63, 126, 252])):
    s3 = stats(run(lbs)[0]); print(f"variant {name:12s}: net Sharpe {s3[0]:.2f} ({s3[1]*100:+.1f}%/yr, worst drawdown {s3[2]*100:.0f}%)")
# per market (12-month), net
print("per market, 12-month rule, net of its own costs (Sharpe):")
sig = np.sign(np.log(px).diff(252)); w1 = (sig * (0.10 / vol)).copy(); w1.loc[~w1.index.isin(fridays)] = np.nan; w1 = w1.ffill().shift(1)
for c in px.columns:
    r = (w1[c] * ret[c]).fillna(0) - (w1[c].diff().abs() * spread[c]).fillna(0) - w1[c].abs().fillna(0) * FIN / 252
    r = r["1986":]; r = r[w1[c]["1986":].notna() & (w1[c]["1986":] != 0)]
    if len(r) > 500: print(f"   {c:12s} {r.mean()/r.std()*math.sqrt(252):+.2f}  ({r.index[0].year}-)")
yr = net.groupby(net.index.year).sum()
print("calendar years positive:", f"{(yr > 0).mean()*100:.0f}%", "| worst years:", ", ".join(f"{y} {v*100:+.0f}%" for y, v in yr.nsmallest(4).items()))
print("trades per week (position changes of sign):", round(float((np.sign(w1).diff().abs() > 0).sum().sum() / (len(fridays[fridays >= '1986']) )), 2))
