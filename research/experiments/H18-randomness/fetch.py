"""One year of Deriv's own hourly candles for the indices Joel trades (public feed, read-only)."""
import asyncio, json, sys, time
sys.path.insert(0, '/home/claude/pt')
import sentinel_core as core, websockets
OUT = 'research/data/hold'
SYMS = ["1HZ50V", "1HZ25V", "1HZ75V", "1HZ100V", "R_75", "R_50", "BOOM1000", "CRASH1000"]
async def main():
    async with websockets.connect(core.DERIV_WS_URL, open_timeout=15, max_size=2**26) as ws:
        for sym in SYMS:
            out = []; end = "latest"
            for _ in range(15):
                await ws.send(json.dumps({"ticks_history": sym, "end": end, "count": 5000, "style": "candles", "granularity": 3600}))
                while True:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 30))
                    if m.get("msg_type") == "candles" or m.get("error"): break
                if m.get("error"): print(sym, m["error"]["message"]); break
                c = m.get("candles") or []
                if out: c = [x for x in c if x["epoch"] < out[0]["epoch"]]
                if not c: break
                out = c + out; end = c[0]["epoch"] - 1
                if out[-1]["epoch"] - out[0]["epoch"] > 366 * 86400: break
                await asyncio.sleep(0.3)
            json.dump(out, open(f"{OUT}/{sym}_h1.json", "w"))
            print(sym, len(out), time.strftime('%Y-%m-%d', time.gmtime(out[0]["epoch"])), "→", time.strftime('%Y-%m-%d', time.gmtime(out[-1]["epoch"])))
asyncio.run(main())
