"""Do Deriv's prices for Bull/Bear Market contracts include the built-in drift? Read-only quotes."""
import asyncio, json, sys, time
import numpy as np
from math import erf, sqrt
sys.path.insert(0, '/home/claude/pt')
import sentinel_core as core, websockets
S='research/experiments/H16-pricing/data/struct'
Phi = lambda x: 0.5 * (1 + erf(x / sqrt(2)))
def params(sym):
    d = json.load(open(f"{S}/{sym}.json"))
    o = np.array([c["open"] for c in d["d1"]]); c = np.array([c["close"] for c in d["d1"]])
    lr = np.log(c / o)
    return lr.mean() / 86400, lr.std() / sqrt(86400), d
def emp(d, secs, up):
    """empirical P(close after `secs` > entry) from minute candles (same-day only), or hour candles."""
    if secs >= 3600:
        h = d["h1"]; k = secs // 3600
        e = np.array([x["epoch"] for x in h]); o = np.array([x["open"] for x in h]); c = np.array([x["close"] for x in h])
        ok = [(i) for i in range(len(h) - k + 1) if (e[i] % 86400) + secs <= 86400 and e[i + k - 1] - e[i] == (k - 1) * 3600]
        r = np.array([c[i + k - 1] / o[i] for i in ok])
    else:
        m = d["m1"]; k = max(1, secs // 60)
        e = np.array([x["epoch"] for x in m]); o = np.array([x["open"] for x in m]); c = np.array([x["close"] for x in m])
        ok = [i for i in range(len(m) - k + 1) if (e[i] % 86400) + secs <= 86400 and e[i + k - 1] - e[i] == (k - 1) * 60]
        r = np.array([c[i + k - 1] / o[i] for i in ok])
    return float(np.mean(r > 1) if up else np.mean(r < 1)), len(r)
async def main():
    rows = []
    async with websockets.connect(core.DERIV_WS_URL, open_timeout=15) as ws:
        for sym in ("RDBULL", "RDBEAR"):
            mu, sd, d = params(sym)
            for dur, unit, secs in ((5, "t", 10), (10, "t", 20), (15, "s", 15), (1, "m", 60), (5, "m", 300), (15, "m", 900), (30, "m", 1800), (1, "h", 3600), (2, "h", 7200)):
                for ct in ("CALL", "PUT"):
                    req = {"proposal": 1, "amount": 10, "basis": "stake", "currency": "USD", "underlying_symbol": sym,
                           "contract_type": ct, "duration": dur, "duration_unit": unit}
                    await ws.send(json.dumps(req))
                    while True:
                        m = json.loads(await asyncio.wait_for(ws.recv(), 15))
                        if m.get("msg_type") == "proposal" or m.get("error"): break
                    if m.get("error"):
                        print(sym, ct, dur, unit, "refused:", m["error"]["message"]); continue
                    pay = float(m["proposal"]["payout"])
                    z = mu * secs / (sd * sqrt(secs))
                    pm = Phi(z) if ct == "CALL" else Phi(-z)
                    pe, n = emp(d, secs, ct == "CALL") if secs >= 60 else (None, 0)
                    rows.append((sym, ct, f"{dur}{unit}", pay, 10 / pay, pm, pe, n))
                    print(f"{sym:7s} {ct:4s} {dur:>2}{unit:1s}  payout {pay:6.2f} (priced p {10/pay:.3f})  model p {pm:.3f} EV {pm*pay/10-1:+.1%}" +
                          (f"  history p {pe:.3f} (n {n}) EV {pe*pay/10-1:+.1%}" if pe is not None else ""))
                    await asyncio.sleep(0.3)
    json.dump(rows, open(f"{S}/drift_quotes.json", "w"))
asyncio.run(main())
