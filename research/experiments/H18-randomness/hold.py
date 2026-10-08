"""'Randomness is why it works': on Deriv's own prices, what does 'hold until it comes back into profit' do?
Every 6 hours, enter (buy or sell, by coin toss); close at a small profit (+1 hourly move); no stop loss.
Compare with the same entries managed with a stop. Deriv public hourly candles, 8 Oct 2025 → 8 Oct 2026."""
import json, math, random, sys
import numpy as np
sys.path.insert(0, '/home/claude/pt')
import sentinel_core as core
D = 'research/data/hold'
NAMES = {"1HZ50V": "Vol 50 (1s)", "1HZ25V": "Vol 25 (1s)", "1HZ75V": "Vol 75 (1s)", "1HZ100V": "Vol 100 (1s)", "R_75": "Vol 75", "R_50": "Vol 50",
         "BOOM1000": "Boom 1000", "CRASH1000": "Crash 1000"}
rng = random.Random(7)
print("Each row: ~1,460 trades in the year. TP = one typical hourly move. 'Came back' = closed in profit.")
print(f"{'index':13s} {'won':>6s} {'still open':>10s} {'median wait':>11s} {'90% wait':>9s} {'worst dip before a win':>23s} {'open now, avg':>13s} {'net, in TP units':>17s} {'with a 1-TP stop':>16s}")
allrows = {}
for sym, name in NAMES.items():
    c = json.load(open(f"{D}/{sym}_h1.json"))
    o = np.array([x["open"] for x in c]); h = np.array([x["high"] for x in c]); l = np.array([x["low"] for x in c]); cl = np.array([x["close"] for x in c])
    r = np.diff(np.log(cl)); sig_h = float(np.std(r))
    m = core.MARKET_BY_ID.get(sym)
    cost = (core.estimated_spread(m, float(cl[-1])) / float(cl[-1])) if m else 0.0002
    res = []
    for i in range(24, len(c) - 1, 6):
        side = 1 if rng.random() < 0.5 else -1
        e = cl[i]; tp = e * (1 + side * sig_h); stop = e * (1 - side * sig_h)
        mae = 0.0; out = None; outs = None
        for j in range(i + 1, len(c)):
            adverse = (e - l[j]) / e if side > 0 else (h[j] - e) / e
            fav_hit = (h[j] >= tp) if side > 0 else (l[j] <= tp)
            stop_hit = (l[j] <= stop) if side > 0 else (h[j] >= stop)
            if outs is None and stop_hit: outs = -1.0                     # stop-managed twin: stop first
            elif outs is None and fav_hit: outs = 1.0
            if fav_hit and out is None:
                out = ("won", j - i, mae); break
            mae = max(mae, adverse)
        if out is None:
            last = side * (cl[-1] - e) / e / sig_h
            out = ("open", len(c) - 1 - i, mae, last)
        res.append((out, outs if outs is not None else side * (cl[-1] - e) / e / sig_h, cost / sig_h))
    won = [x[0] for x in res if x[0][0] == "won"]; opn = [x[0] for x in res if x[0][0] == "open"]
    waits = np.array([w[1] for w in won]); dips = np.array([w[2] for w in won]) / sig_h
    net = sum(1.0 for _ in won) + sum(x[3] for x in opn) - sum(x[2] for x in res)
    net_stop = sum(x[1] for x in res) - sum(x[2] for x in res)
    n = len(res)
    print(f"{name:13s} {len(won)/n*100:5.1f}% {len(opn):10d} {np.median(waits):9.0f} h {np.percentile(waits, 90):7.0f} h {dips.max():19.0f}× TP {np.mean([x[3] for x in opn]) if opn else 0:+11.1f}× {net/n:+15.3f}/trade {net_stop/n:+14.3f}/trade")
    allrows[sym] = dict(n=n, won=len(won), open=len(opn), wait_med=float(np.median(waits)), wait90=float(np.percentile(waits, 90)), dip_max=float(dips.max()),
                        dip_p95=float(np.percentile(dips, 95)), open_avg=float(np.mean([x[3] for x in opn])) if opn else 0.0, net=net / n, net_stop=net_stop / n, sig_h=sig_h)
json.dump(allrows, open(f"{D}/hold_rows.json", "w"), indent=1)
