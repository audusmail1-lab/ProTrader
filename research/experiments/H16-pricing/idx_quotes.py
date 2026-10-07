"""Read-only quotes on real indices / gold: long 'Rise' contracts and 'Ends between' ranges. Compare with a
risk-neutral price at market implied volatility (VXN for Nasdaq-100) to read Deriv's pricing rule."""
import asyncio, json, sys, csv, time
import numpy as np
from math import erf, sqrt, log
sys.path.insert(0, '/home/claude/pt')
import sentinel_core as core, websockets
L = 'research/experiments/H16-pricing/data/long'
Phi = lambda x: 0.5 * (1 + erf(x / sqrt(2)))
def last(name):
    v = [r for r in csv.DictReader(open(f"{L}/{name}.csv")) if r[list(r.keys())[1]] not in ("", ".")]
    return float(v[-1][list(v[-1].keys())[1]])
VXN, VIX, RF = last("VXNCLS") / 100, last("VIXCLS") / 100, last("DTB3") / 100
IV = {"OTC_NDX": VXN, "OTC_SPC": VIX, "OTC_DJI": VIX * 0.95, "OTC_GDAXI": VIX, "frxXAUUSD": None}
async def recv(ws, want):
    while True:
        m = json.loads(await asyncio.wait_for(ws.recv(), 20))
        if m.get("msg_type") == want or m.get("error"): return m
async def quote(ws, req):
    for a in range(6):
        await ws.send(json.dumps(req)); m = await recv(ws, "proposal")
        if m.get("error") and "rate limit" in m["error"]["message"]: await asyncio.sleep(5 * (a + 1)); continue
        return m
    return m
async def main(syms):
    rows = []
    async with websockets.connect(core.DERIV_WS_URL, open_timeout=15) as ws:
        for sym in syms:
            await ws.send(json.dumps({"ticks": sym})); m = await recv(ws, "tick")
            if m.get("error"): print(sym, m["error"]["message"]); continue
            spot = m["tick"]["quote"]; pip = m["tick"].get("pip_size", 2)
            await ws.send(json.dumps({"forget_all": "ticks"})); await recv(ws, "forget_all")
            iv = IV.get(sym) or 0.18
            for days in (30, 91, 182, 365):
                for ct in ("CALL", "PUT"):
                    m = await quote(ws, {"proposal": 1, "amount": 10, "basis": "stake", "currency": "USD", "underlying_symbol": sym, "contract_type": ct, "duration": days, "duration_unit": "d"})
                    if m.get("error"): print(f"  {sym} {ct} {days}d refused: {m['error']['message'][:70]}"); continue
                    p = m["proposal"]; pay = float(p["payout"]); T = (p["date_expiry"] - p["date_start"]) / (365 * 86400)
                    d2 = (RF - 0.01 - iv * iv / 2) * T / (iv * sqrt(T)); pm = Phi(d2) if ct == "CALL" else Phi(-d2)
                    rows.append(dict(sym=sym, ct=ct, days=days, payout=pay, priced=10 / pay, model=pm, iv=iv, T=T))
                    print(f"  {sym:9s} {ct:4s} {days:3d}d pays {pay:6.2f}  priced p {10/pay:.3f}  risk-neutral p at IV {iv:.1%}: {pm:.3f}  → markup {10/pay/pm-1:+.1%}")
                    await asyncio.sleep(0.7)
            for days in (7, 30):
                for k in (0.5, 1.0, 1.5):
                    b = k * iv * sqrt(days / 365)
                    U = round(spot * np.exp(b), pip); Lo = round(spot * np.exp(-b), pip)
                    m = await quote(ws, {"proposal": 1, "amount": 10, "basis": "stake", "currency": "USD", "underlying_symbol": sym, "contract_type": "EXPIRYRANGE",
                                         "duration": days, "duration_unit": "d", "barrier": f"{U:.{pip}f}", "barrier2": f"{Lo:.{pip}f}"})
                    if m.get("error"): print(f"  {sym} RANGE {days}d ±{k} refused: {m['error']['message'][:70]}"); continue
                    p = m["proposal"]; pay = float(p["payout"]); T = (p["date_expiry"] - p["date_start"]) / (365 * 86400)
                    mu = (RF - 0.01 - iv * iv / 2) * T; s = iv * sqrt(T)
                    pm = Phi((log(U / spot) - mu) / s) - Phi((log(Lo / spot) - mu) / s)
                    rows.append(dict(sym=sym, ct=f"EXPIRYRANGE±{k}", days=days, payout=pay, priced=10 / pay, model=pm, iv=iv, T=T))
                    print(f"  {sym:9s} ENDS BETWEEN ±{k}σ {days:2d}d pays {pay:6.2f}  priced p {10/pay:.3f}  risk-neutral p {pm:.3f}  → markup {10/pay/pm-1:+.1%}")
                    await asyncio.sleep(0.7)
    json.dump(rows, open(f"{L}/idx_quotes_{int(time.time())}.json", "w"))
print(f"VXN {VXN:.1%} VIX {VIX:.1%} T-bill {RF:.2%}")
asyncio.run(main(sys.argv[1].split(",")))
