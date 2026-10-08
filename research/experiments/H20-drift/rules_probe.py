"""Drift inside the 1% rule: the 200-day line itself as the stop.
Per index: enter on a daily close above the 200-day average; stop = line x (1 - b), raised daily with the line, never
lowered; size = 1% of equity at that stop, capped at `cap` x equity; exit on a close below the line (or the stop).
Roll-up (R2): once a position is risk-free and its 1%-sized target is 1.5x bigger, close it and reopen at the new size.
Costs: 0.03% of notional per side, financing T-bill + 2.5%/yr on notional, exit at the close (gaps through the stop
land at the close: conservative)."""
import sys, numpy as np, pandas as pd
L = 'research/data/fred'
def load(i):
    df = pd.read_csv(f"{L}/{i}.csv"); df.columns = ["d", "v"]; df["v"] = pd.to_numeric(df["v"], errors="coerce"); df["d"] = pd.to_datetime(df["d"])
    return df.dropna().set_index("d")["v"]
SPREAD, MARK = 0.0003, 0.025
def run(names, mode, b=0.03, cap=0.5, risk=0.01, start=None):
    px = pd.concat({n: load(n) for n in names}, axis=1).dropna()
    tb = load("DTB3").reindex(px.index).ffill().bfill() / 100
    sma = px.rolling(200).mean()
    if start: px, sma, tb = px[start:], sma[start:], tb[start:]
    px, sma = px[sma.notna().all(axis=1)], sma[sma.notna().all(axis=1)]; tb = tb.reindex(px.index)
    eq = 1.0; pos = {n: None for n in names}; rows = []; trades = 0; stops = 0
    for i in range(1, len(px)):
        d = px.index[i]; days = (d - px.index[i - 1]).days
        for n in names:
            p, line, u = px[n].iloc[i], sma[n].iloc[i], pos[n]
            if u:
                eq += u["n"] * (p / u["last"] - 1) - u["n"] * (tb.iloc[i] + MARK) / 365 * days; u["last"] = p
                if mode != "1x": u["stop"] = max(u["stop"], line * (1 - b))
                hit = mode != "1x" and p <= u["stop"]
                if p < line or hit:
                    eq -= u["n"] * SPREAD; stops += hit; pos[n] = None; continue
                if mode == "1x": u["n"] = eq * cap                      # keep 1x (half in each index)
                elif mode == "R2" and u["stop"] >= u["entry"]:
                    want = min(risk * eq / ((p - u["stop"]) / p), cap * eq)
                    if want > 1.5 * u["n"]:
                        eq -= (u["n"] + want) * SPREAD; trades += 1
                        pos[n] = dict(n=want, last=p, entry=p, stop=u["stop"])
            elif p > line:
                stop = line * (1 - b)
                n_ = cap * eq if mode == "1x" else min(risk * eq / ((p - stop) / p), cap * eq)
                eq -= n_ * SPREAD; trades += 1; pos[n] = dict(n=n_, last=p, entry=p, stop=stop)
        risk_open = sum(max(0, u["n"] * (u["entry"] - u["stop"]) / u["entry"]) for u in pos.values() if u) / eq if mode != "1x" else np.nan
        rows.append((d, eq, sum(u["n"] for u in pos.values() if u) / eq, risk_open))
    c = pd.DataFrame(rows, columns=["d", "e", "x", "r"]).set_index("d")
    yrs = (c.index[-1] - c.index[0]).days / 365.25
    g = c.e.iloc[-1] ** (1 / yrs) - 1; dd = (c.e / c.e.cummax() - 1).min()
    dec = {}
    for a, z in (("1987", "1999"), ("2000", "2012"), ("2013", "2026")):
        s = c.e[a:z]
        if len(s) > 250: dec[a] = (s.iloc[-1] / s.iloc[0]) ** (365.25 / (s.index[-1] - s.index[0]).days) - 1
    return dict(g=g, dd=dd, x=c.x.mean(), rk=c.r.mean(), busy=(c.r > 0.001).mean() if mode != "1x" else np.nan,
                trades=trades / yrs, stops=stops, dec=dec, end=c.e.iloc[-1], yrs=yrs)
def show(label, r):
    dec = " ".join(f"{k}: {v*100:+5.1f}%" for k, v in r["dec"].items())
    print(f"{label:44s} {r['g']*100:+6.1f}%/yr  worst {r['dd']*100:5.0f}%  exposure {r['x']*100:4.0f}%  "
          f"open risk {r['rk']*100 if r['rk']==r['rk'] else 0:4.2f}% (>0 on {r['busy']*100 if r['busy']==r['busy'] else 0:3.0f}% of days)  "
          f"{r['trades']:4.1f} trades/yr  {dec}")
print("== Nasdaq-100 alone, 1987-2026 (cap 1x) ==")
show("1x, exit below the line (Joel's pick)", run(["NASDAQ100"], "1x", cap=1.0))
for b in (0.02, 0.03, 0.05):
    show(f"rules, line stop -{b*100:.0f}%, one position", run(["NASDAQ100"], "R1", b=b, cap=1.0))
    show(f"rules, line stop -{b*100:.0f}%, roll-up", run(["NASDAQ100"], "R2", b=b, cap=1.0))
print("\n== US Tech 100 + US 500 together, 2017-2026 (FRED's S&P history starts 2016; cap 0.5x each = 1x total) ==")
show("1x, exit below the line (Joel's pick)", run(["NASDAQ100", "SP500"], "1x"))
for b in (0.02, 0.03, 0.05):
    show(f"rules, line stop -{b*100:.0f}%, one position each", run(["NASDAQ100", "SP500"], "R1", b=b))
    show(f"rules, line stop -{b*100:.0f}%, roll-up", run(["NASDAQ100", "SP500"], "R2", b=b))
print("\n== Nasdaq-100 alone over the same 2017-2026 window, for scale ==")
show("1x NDX", run(["NASDAQ100"], "1x", cap=1.0, start="2016-10-10"))
show("rules -3% roll-up NDX", run(["NASDAQ100"], "R2", b=0.03, cap=1.0, start="2016-10-10"))

print("\n== The engine as built: 0.5% risk per index at a stop 3% under the line, at most 0.5x each (1% open risk, 1x in all) ==")
show("NDX half, 1987-2026", run(["NASDAQ100"], "R1", b=0.03, cap=0.5, risk=0.005))
show("NDX half, 1x pick, 1987-2026", run(["NASDAQ100"], "1x", cap=0.5))
show("both, 2017-2026", run(["NASDAQ100", "SP500"], "R1", b=0.03, cap=0.5, risk=0.005))
show("both, 1x pick, 2017-2026", run(["NASDAQ100", "SP500"], "1x"))
