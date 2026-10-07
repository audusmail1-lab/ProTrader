import asyncio, json, sys, time
sys.path.insert(0, '/home/claude/pt')
import sentinel_core as core, websockets
async def main(sym, g, secs):
    async with websockets.connect(core.DERIV_WS_URL, open_timeout=15) as ws:
        await ws.send(json.dumps({"ticks": sym, "subscribe": 1}))
        await ws.send(json.dumps({"proposal": 1, "amount": 10, "basis": "stake", "currency": "USD", "underlying_symbol": sym, "contract_type": "ACCU", "growth_rate": g, "subscribe": 1}))
        ticks = {}; runs = []; t0 = time.time(); dist = None
        while time.time() - t0 < secs:
            m = json.loads(await asyncio.wait_for(ws.recv(), 20))
            if m.get("msg_type") == "tick": ticks[m["tick"]["epoch"]] = m["tick"]["quote"]
            elif m.get("msg_type") == "proposal":
                cd = m["proposal"]["contract_details"]; runs.append((cd["last_tick_epoch"], cd["ticks_stayed_in"][-1])); dist = float(cd["barrier_spot_distance"])
    resets = [ep for (e0, a), (ep, b) in zip(runs, runs[1:]) if b < a]
    eps = sorted(ticks)
    big = [b for a, b in zip(eps, eps[1:]) if abs(ticks[b] - ticks[a]) >= dist]
    print(f"{sym} g {g}: {len(eps)} ticks, barrier distance {dist}: knock-outs on Deriv's record {len(resets)} at {[time.strftime('%M:%S', time.gmtime(e)) for e in resets]}")
    print(f"     ticks in the public feed that moved more than the barrier: {len(big)} at {[time.strftime('%M:%S', time.gmtime(e)) for e in big]}")
asyncio.run(main(sys.argv[1], float(sys.argv[2]), int(sys.argv[3])))
