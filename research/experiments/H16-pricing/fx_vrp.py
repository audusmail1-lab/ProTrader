"""Forex range/no-touch contracts are a bet that the market stays calmer than priced (the volatility risk premium).
Quote them (read-only), back out the volatility Deriv charges, and test each quote against one year of history."""
import asyncio, json, sys, time
import numpy as np
from math import erf, sqrt, log
sys.path.insert(0, '/home/claude/pt')
import sentinel_core as core, websockets
D = 'research/experiments/H16-pricing/data/fx'
PAIRS = sys.argv[1].split(',') if len(sys.argv) > 1 else ["frxEURUSD","frxGBPUSD","frxUSDJPY","frxAUDUSD","frxUSDCAD","frxUSDCHF","frxNZDUSD","frxEURGBP","frxEURJPY","frxGBPJPY","frxAUDJPY","frxEURAUD","frxEURCHF","frxEURCAD","frxGBPAUD"]
Phi = lambda x: 0.5 * (1 + erf(x / sqrt(2)))
def model_p(ct, bu, bd, s):              # bu, bd: log distances (>0) to upper / lower barrier; s = sigma*sqrt(T)
    if ct == "EXPIRYRANGE": return Phi(bu / s) - Phi(-bd / s)
    if ct == "EXPIRYMISS": return 1 - (Phi(bu / s) - Phi(-bd / s))
    if ct == "NOTOUCH_U": return 1 - 2 * Phi(-bu / s)
    if ct == "NOTOUCH_D": return 1 - 2 * Phi(-bd / s)
    if ct == "ONETOUCH_U": return 2 * Phi(-bu / s)
    if ct == "ONETOUCH_D": return 2 * Phi(-bd / s)
    if ct in ("RANGE", "UPORDOWN"):      # double barrier, series solution
        L = bu + bd; x = bd; p = 0.0
        for k in range(-20, 21):
            p += Phi((x + 2 * k * L) / s) - Phi((x + 2 * k * L - L) / s) - (Phi((-x + 2 * k * L) / s) - Phi((-x + 2 * k * L - L) / s))
        p = p  # probability of staying in
        p = max(0.0, min(1.0, p))
        return p if ct == "RANGE" else 1 - p
def implied_vol(ct, bu, bd, price_p, T):
    lo, hi = 1e-4, 3.0
    f = lambda sg: model_p(ct, bu, bd, sg * sqrt(T)) - price_p
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0: return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0: hi = mid
        else: lo = mid
    return (lo + hi) / 2
def hist(sym, ct, up_rel, dn_rel, days):
    c = json.load(open(f"{D}/{sym}_d1.json"))
    e = np.array([x["epoch"] for x in c]); cl = np.array([x["close"] for x in c]); hi = np.array([x["high"] for x in c]); lo = np.array([x["low"] for x in c])
    wins = []
    for i in range(len(c)):
        j = np.where((e > e[i]) & (e <= e[i] + days * 86400))[0]
        if len(j) == 0 or e[-1] < e[i] + days * 86400: continue
        s0 = cl[i]; U = s0 * (1 + up_rel); L = s0 * (1 - dn_rel)
        H, Lo, end = hi[j].max(), lo[j].min(), cl[j[-1]]
        w = {"EXPIRYRANGE": L < end < U, "EXPIRYMISS": not (L < end < U), "NOTOUCH_U": H < U, "NOTOUCH_D": Lo > L,
             "ONETOUCH_U": H >= U, "ONETOUCH_D": Lo <= L, "RANGE": H < U and Lo > L, "UPORDOWN": H >= U or Lo <= L}[ct]
        wins.append(w)
    return np.array(wins, float)
async def recv(ws, want):
    while True:
        m = json.loads(await asyncio.wait_for(ws.recv(), 20))
        if m.get("msg_type") == want or m.get("error"): return m
async def main():
    rows = []
    async with websockets.connect(core.DERIV_WS_URL, open_timeout=15) as ws:
        for sym in PAIRS:
            c = json.load(open(f"{D}/{sym}_d1.json")); cl = np.array([x["close"] for x in c])
            sig = float(np.std(np.diff(np.log(cl))) * sqrt(260))
            await ws.send(json.dumps({"ticks": sym})); m = await recv(ws, "tick"); spot = m["tick"]["quote"]; pip = m["tick"].get("pip_size", 5)
            await ws.send(json.dumps({"forget_all": "ticks"})); await recv(ws, "forget_all")
            for days in (1, 7, 30):
                sT = sig * sqrt(days / 365)
                for k in (0.75, 1.25, 2.0):
                    d = k * sT
                    U = round(spot * (1 + d), pip); L = round(spot * (1 - d), pip)
                    for ct, b1, b2 in (("EXPIRYRANGE", U, L), ("EXPIRYMISS", U, L), ("RANGE", U, L), ("UPORDOWN", U, L),
                                       ("NOTOUCH_U", U, None), ("NOTOUCH_D", L, None), ("ONETOUCH_U", U, None), ("ONETOUCH_D", L, None)):
                        req = {"proposal": 1, "amount": 10, "basis": "stake", "currency": "USD", "underlying_symbol": sym,
                               "contract_type": ct.split("_")[0], "duration": days, "duration_unit": "d", "barrier": f"{b1:.{pip}f}"}
                        if b2 is not None: req["barrier2"] = f"{b2:.{pip}f}"
                        for attempt in range(6):
                            await ws.send(json.dumps(req)); m = await recv(ws, "proposal")
                            if m.get("error") and "rate limit" in m["error"]["message"]:
                                await asyncio.sleep(5 * (attempt + 1)); continue
                            break
                        if m.get("error"):
                            rows.append(dict(sym=sym, days=days, k=k, ct=ct, err=m["error"]["message"])); continue
                        p = m["proposal"]; pay = float(p["payout"]); pp = 10 / pay
                        T = (p["date_expiry"] - p["date_start"]) / (365 * 86400)
                        bu, bd = log(U / spot), log(spot / L)
                        iv = implied_vol(ct, bu, bd, pp, T)
                        w = hist(sym, ct, U / spot - 1, 1 - L / spot, days)
                        pm = model_p(ct, bu, bd, sig * sqrt(T))
                        rows.append(dict(sym=sym, days=days, k=k, ct=ct, payout=pay, priced=pp, iv=iv, rv=sig, p_model=pm, ev_model=pm * pay / 10 - 1,
                                         p_hist=float(w.mean()), n=len(w), ev_hist=float(w.mean()) * pay / 10 - 1, hours=(p["date_expiry"] - p["date_start"]) / 3600))
                        await asyncio.sleep(0.7)
            ok = [r for r in rows if r["sym"] == sym and "err" not in r]
            print(f"{sym}: realized vol {sig:.1%}, {len(ok)} quotes; implied vol on calm-side contracts (median) {np.median([r['iv'] for r in ok if r['iv'] and r['ct'] in ('EXPIRYRANGE','RANGE','NOTOUCH_U','NOTOUCH_D')]) if ok else float('nan'):.1%}")
    json.dump(rows, open(f"{D}/vrp_rows_{sys.argv[2] if len(sys.argv) > 2 else 0}.json", "w"))
asyncio.run(main())
