"""Deal cancellation = an at-the-money option sold for a fixed fee. Is the fee ever below the option's fair value? Read-only quotes."""
import asyncio, json, sys
import numpy as np
sys.path.insert(0, '/home/claude/pt')
import sentinel_core as core, websockets
SIG = {"1HZ10V": (0.10, 1), "1HZ25V": (0.25, 1), "1HZ50V": (0.50, 1), "1HZ75V": (0.75, 1), "1HZ100V": (1.00, 1),
       "R_10": (0.10, 2), "R_25": (0.25, 2), "R_50": (0.50, 2), "R_75": (0.75, 2), "R_100": (1.00, 2)}
CAN = {"5m": 300, "10m": 600, "15m": 900, "30m": 1800, "60m": 3600}
rng = np.random.default_rng(5)
def fair(sym, mult, secs, stake, comm, stop_frac):
    sig, dt = SIG[sym]; n = secs // dt; N = 20000
    s = sig * np.sqrt(dt / (365 * 86400))
    x = np.zeros(N); low = np.zeros(N)
    for _ in range(n):
        x += rng.normal(-s * s / 2, s, N); np.minimum(low, x, out=low)
    rT = np.expm1(x)
    pnl = mult * stake * rT - comm
    stopped = np.expm1(low) <= -stop_frac
    keep = np.where(stopped, 0.0, np.maximum(pnl, 0.0))      # cancel (stake back) if behind or about to stop out
    return float(keep.mean()), float(stopped.mean())
async def recv(ws, want):
    while True:
        m = json.loads(await asyncio.wait_for(ws.recv(), 20))
        if m.get("msg_type") == want or m.get("error"): return m
async def main():
    rows = []
    async with websockets.connect(core.DERIV_WS_URL, open_timeout=15) as ws:
        for sym in SIG:
            await ws.send(json.dumps({"contracts_for": sym})); cf = await recv(ws, "contracts_for")
            av = [a for a in (cf.get("contracts_for") or {}).get("available", []) if a["contract_type"] == "MULTUP"]
            if not av: print(sym, "no multipliers"); continue
            mults = av[0].get("multiplier_range", []); cans = av[0].get("cancellation_range", [])
            for mult in mults:
                for c in cans:
                    await ws.send(json.dumps({"proposal": 1, "amount": 10, "basis": "stake", "currency": "USD", "underlying_symbol": sym,
                                              "contract_type": "MULTUP", "multiplier": mult, "cancellation": c}))
                    m = await recv(ws, "proposal")
                    if m.get("error"): print(sym, mult, c, m["error"]["message"][:60]); continue
                    p = m["proposal"]; fee = float(p["cancellation"]["ask_price"]); comm = float(p["commission"])
                    stop_frac = (float(p["spot"]) - float(p["limit_order"]["stop_out"]["value"])) / float(p["spot"])
                    f, ps = fair(sym, mult, CAN[c], 10.0, comm, stop_frac)
                    rows.append(dict(sym=sym, mult=mult, can=c, fee=fee, comm=comm, fair=f, ev=f - fee, p_stop=ps))
                    print(f"{sym:8s} x{mult:<4d} cancel {c:>3s}  fee {fee:5.2f}  commission {comm:4.2f}  fair value of protection {f:5.2f}  EV per $10 {f-fee:+.2f}  (stop-out reached {ps:.1%})")
                    await asyncio.sleep(0.2)
    json.dump(rows, open('research/experiments/H16-pricing/data/cancel_rows.json', 'w'))
    rows.sort(key=lambda r: -r["ev"])
    print("BEST:", [(r["sym"], r["mult"], r["can"], round(r["ev"], 2)) for r in rows[:8]])
asyncio.run(main())
