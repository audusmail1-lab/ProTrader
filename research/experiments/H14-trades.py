"""Re-run the H14 replay, keep every trade with its higher-timeframe reads and an
extension measure, and save them for the sign-flip analysis."""
import json, sys, pickle, bisect
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, '/home/claude/pt'); sys.path.insert(0, '/tmp/claude-0/-home-claude/76d7836d-a469-5749-8e9e-0722ccff9b7a/scratchpad/mtf')
import research_lab as lab, sentinel_core as core
import h14

def ema(xs, n):
    k = 2 / (n + 1); out = []; e = None
    for x in xs:
        e = x if e is None else e + k * (x - e); out.append(e)
    return out

def job2(args):
    key, trades = h14.job(args)
    mid, tf = key
    data = lab.load_history([mid], ["1h", "4h"])
    feats = {}
    for utf in ("1h", "4h"):
        ub = data.get((mid, utf))
        if not ub: continue
        closes = [b["close"] for b in ub]
        e50 = ema(closes, 50); atr = lab.wilder_atr(ub, 14)
        ct = [b["time"] + core.TF_SEC[utf] for b in ub]
        feats[utf] = (ct, e50, atr, closes)
    for t in trades:
        s = 1 if t["dir"] == "buy" else -1
        for utf, (ct, e50, atr, closes) in feats.items():
            i = bisect.bisect_right(ct, t["opened_at"]) - 1
            if i >= 50 and atr[i]:
                t[f"ext_{utf}"] = s * (t["entry"] - e50[i]) / atr[i]       # how far price already ran in the trade's direction, in ATRs
                j = max(0, i - 20)
                t[f"trend20_{utf}"] = abs(closes[i] - closes[j]) / (atr[i] * (20 ** 0.5))   # 20-bar move vs a random walk's typical size
    return key, trades

if __name__ == "__main__":
    slices = [(m, tf) for m in h14.REAL + h14.CTRL for tf in ("15m", "1h")]
    with ProcessPoolExecutor(max_workers=2) as ex:
        res = dict(ex.map(job2, slices))
    pickle.dump(res, open('/tmp/claude-0/-home-claude/76d7836d-a469-5749-8e9e-0722ccff9b7a/scratchpad/mtf/h14_trades.pkl', 'wb'))
    print({f"{k[0]} {k[1]}": len(v) for k, v in res.items()})
