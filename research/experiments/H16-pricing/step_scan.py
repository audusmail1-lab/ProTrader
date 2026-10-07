"""Step Index: each second the price moves exactly +0.1 or -0.1, 50/50. Exact binomial odds vs Deriv's payouts (read-only)."""
import asyncio, json, sys
from math import comb
sys.path.insert(0, '/home/claude/pt')
import sentinel_core as core, websockets
def p(ct, n):
    up = sum(comb(n, k) for k in range(n + 1) if 2 * k - n > 0) / 2 ** n
    tie = (comb(n, n // 2) / 2 ** n) if n % 2 == 0 else 0.0
    return {"CALL": up, "PUT": up, "CALLE": up + tie, "PUTE": up + tie}[ct]
async def recv(ws, want):
    while True:
        m = json.loads(await asyncio.wait_for(ws.recv(), 20))
        if m.get("msg_type") == want or m.get("error"): return m
async def main():
    async with websockets.connect(core.DERIV_WS_URL, open_timeout=15) as ws:
        for n in (1, 2, 3, 4, 5, 6, 10):
            out = []
            for ct in ("CALL", "PUT", "CALLE", "PUTE"):
                await ws.send(json.dumps({"proposal": 1, "amount": 10, "basis": "stake", "currency": "USD", "underlying_symbol": "stpRNG", "contract_type": ct, "duration": n, "duration_unit": "t"}))
                m = await recv(ws, "proposal")
                if m.get("error"): out.append(f"{ct} n/a ({m['error']['message'][:30]})"); continue
                pay = float(m["proposal"]["payout"]); out.append(f"{ct} pays {pay:5.2f} true p {p(ct, n):.3f} EV {p(ct, n) * pay / 10 - 1:+.1%}")
                await asyncio.sleep(0.6)
            print(f"{n:2d} ticks: " + " | ".join(out))
asyncio.run(main())
