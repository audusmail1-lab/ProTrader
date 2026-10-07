import asyncio, json, sys
from math import erf, sqrt
sys.path.insert(0, '/home/claude/pt')
import sentinel_core as core, websockets
Phi = lambda x: 0.5 * (1 + erf(x / sqrt(2)))
SIG = {"1HZ10V": (0.10, 1), "1HZ25V": (0.25, 1), "1HZ50V": (0.50, 1), "1HZ75V": (0.75, 1), "1HZ100V": (1.00, 1), "R_10": (0.10, 2), "R_25": (0.25, 2), "R_50": (0.50, 2), "R_75": (0.75, 2), "R_100": (1.00, 2)}
async def recv(ws, want):
    while True:
        m = json.loads(await asyncio.wait_for(ws.recv(), 20))
        if m.get("msg_type") == want or m.get("error"): return m
async def main():
    best = []
    async with websockets.connect(core.DERIV_WS_URL, open_timeout=15) as ws:
        for sym, (sg, dt) in SIG.items():
            s = sg * sqrt(dt / (365 * 86400)); line = []
            for g in (0.01, 0.02, 0.03, 0.04, 0.05):
                await ws.send(json.dumps({"proposal": 1, "amount": 10, "basis": "stake", "currency": "USD", "underlying_symbol": sym, "contract_type": "ACCU", "growth_rate": g}))
                m = await recv(ws, "proposal")
                if m.get("error"): line.append(f"{g:.0%}: n/a"); continue
                cd = m["proposal"]["contract_details"]; b = float(cd["tick_size_barrier"]); L = cd.get("ticks_stayed_in") or []
                p_th = 2 * Phi(b / s) - 1
                f = (1 + g) * p_th; best.append((f, sym, g))
                line.append(f"{g:.0%}: {f:.4f}" + (f" (record {(1+g)*sum(L)/(sum(L)+len(L)):.4f})" if L else ""))
                await asyncio.sleep(0.6)
            print(f"{sym:8s} per-tick value of $1 (exact, published volatility): " + "  ".join(line))
    best.sort(reverse=True); print("closest to fair:", [(round(f, 4), s, g) for f, s, g in best[:5]])
asyncio.run(main())
