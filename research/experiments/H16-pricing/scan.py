"""
Price every Deriv contract on the Volatility indices against its exact fair value.

The indices are a geometric random walk with a published volatility (verified on
12,000 ticks each: per-tick sigma within 1% of the stated figure, normal tails,
no autocorrelation, uniform last digits). So the true probability of any event is
computable. Deriv quotes the payout for a $10 stake; a contract has positive
expected value for the buyer exactly when  P_true x payout > stake.
Read-only: price quotes only, nothing is bought.
"""
import asyncio, json, sys, time
import numpy as np
sys.path.insert(0, '/home/claude/pt')
import sentinel_core as core
import websockets

SIG = {"1HZ50V": (0.50, 1), "1HZ100V": (1.00, 1), "R_50": (0.50, 2), "R_100": (1.00, 2)}
N = 400_000
rng = np.random.default_rng(11)


def paths(sym, n_ticks):
    sig, dt = SIG[sym]
    s = sig * np.sqrt(dt / (365 * 86400))
    r = rng.normal(-s * s / 2, s, size=(N, n_ticks))
    return np.cumsum(r, axis=1)                     # log(S_k / S_entry), k = 1..n


def fair(sym, c, spot):
    """True probability that contract c pays, under the published model."""
    ct, n = c["contract_type"], c.get("_ticks")
    b = c.get("_b")                                  # barrier offset in price points (relative contracts)
    lb = (lambda x: np.log1p(x / spot))
    if ct in ("DIGITEVEN", "DIGITODD"):
        return 0.5
    if ct == "DIGITMATCH":
        return 0.1
    if ct == "DIGITDIFF":
        return 0.9
    if ct == "DIGITOVER":
        return (9 - int(c["barrier"])) / 10
    if ct == "DIGITUNDER":
        return int(c["barrier"]) / 10
    X = paths(sym, n)
    last = X[:, -1]
    if ct == "CALL":
        return float((last > (lb(b) if b else 0)).mean())
    if ct == "PUT":
        return float((last < (lb(b) if b else 0)).mean())
    if ct == "CALLE":
        return float((last >= 0).mean())
    if ct == "PUTE":
        return float((last <= 0).mean())
    if ct == "ONETOUCH":
        return float(((X >= lb(b)).any(axis=1) if b > 0 else (X <= lb(b)).any(axis=1)).mean())
    if ct == "NOTOUCH":
        return 1 - float(((X >= lb(b)).any(axis=1) if b > 0 else (X <= lb(b)).any(axis=1)).mean())
    if ct == "RANGE":
        return float(((X < lb(b)) & (X > lb(-b))).all(axis=1).mean())
    if ct == "UPORDOWN":
        return 1 - float(((X < lb(b)) & (X > lb(-b))).all(axis=1).mean())
    if ct == "EXPIRYRANGE":
        return float(((last < lb(b)) & (last > lb(-b))).mean())
    if ct == "EXPIRYMISS":
        return float(((last >= lb(b)) | (last <= lb(-b))).mean())
    if ct == "TICKHIGH":
        k = int(c["selected_tick"]) - 1
        return float((X.argmax(axis=1) == k).mean())
    if ct == "TICKLOW":
        k = int(c["selected_tick"]) - 1
        return float((X.argmin(axis=1) == k).mean())
    if ct == "RUNHIGH":
        steps = np.diff(np.concatenate([np.zeros((N, 1)), X], axis=1), axis=1)
        return float((steps > 0).all(axis=1).mean())
    if ct == "RUNLOW":
        steps = np.diff(np.concatenate([np.zeros((N, 1)), X], axis=1), axis=1)
        return float((steps < 0).all(axis=1).mean())
    if ct == "ASIANU":
        avg = np.log(np.exp(X).mean(axis=1))
        return float((last > avg).mean())
    if ct == "ASIAND":
        avg = np.log(np.exp(X).mean(axis=1))
        return float((last < avg).mean())
    return None


def grid(sym, spot):
    sig, dt = SIG[sym]
    st = spot * sig * np.sqrt(dt / (365 * 86400))      # one tick's typical move, in price points
    dp = 2 if sym.startswith("1HZ") else (4 if sym == "R_50" else 2)
    fmt = lambda x: f"{'+' if x >= 0 else '-'}{abs(x):.{dp}f}"
    out = []
    base = {"proposal": 1, "amount": 10, "basis": "stake", "currency": "USD", "underlying_symbol": sym}
    for n in (1, 2, 3, 5, 10):
        for ct in ("CALL", "PUT"):
            out.append(dict(base, contract_type=ct, duration=n, duration_unit="t", _ticks=n, _b=0))
    for ct in ("DIGITEVEN", "DIGITODD"):
        out.append(dict(base, contract_type=ct, duration=1, duration_unit="t", _ticks=1))
    for d in (0, 4, 8):
        out.append(dict(base, contract_type="DIGITOVER", duration=1, duration_unit="t", barrier=str(d), _ticks=1))
    for d in (1, 5, 9):
        out.append(dict(base, contract_type="DIGITUNDER", duration=1, duration_unit="t", barrier=str(d), _ticks=1))
    out.append(dict(base, contract_type="DIGITMATCH", duration=1, duration_unit="t", barrier="5", _ticks=1))
    out.append(dict(base, contract_type="DIGITDIFF", duration=1, duration_unit="t", barrier="5", _ticks=1))
    for k in (1, 2, 3, 4, 5):
        for ct in ("TICKHIGH", "TICKLOW"):
            out.append(dict(base, contract_type=ct, duration=5, duration_unit="t", selected_tick=k, _ticks=5))
    for n in (2, 3, 5):
        for ct in ("RUNHIGH", "RUNLOW"):
            out.append(dict(base, contract_type=ct, duration=n, duration_unit="t", _ticks=n))
    for n in (5, 10):
        for ct in ("ASIANU", "ASIAND"):
            out.append(dict(base, contract_type=ct, duration=n, duration_unit="t", _ticks=n))
        for m in (0.5, 1.0, 2.0):
            b = round(m * st * np.sqrt(n), dp)
            for ct, bb in (("ONETOUCH", b), ("ONETOUCH", -b), ("NOTOUCH", b), ("NOTOUCH", -b)):
                out.append(dict(base, contract_type=ct, duration=n, duration_unit="t", barrier=fmt(bb), _ticks=n, _b=bb))
            for ct, bb in (("CALL", b), ("PUT", -b)):
                out.append(dict(base, contract_type=ct, duration=n, duration_unit="t", barrier=fmt(bb), _ticks=n, _b=bb))
    secs = 120
    n2 = secs // dt
    for m in (0.5, 1.0, 2.0):
        b = round(m * st * np.sqrt(n2), dp)
        for ct, bb in (("ONETOUCH", b), ("NOTOUCH", b)):
            out.append(dict(base, contract_type=ct, duration=2, duration_unit="m", barrier=fmt(bb), _ticks=n2, _b=bb))
        for ct in ("RANGE", "UPORDOWN", "EXPIRYRANGE", "EXPIRYMISS"):
            out.append(dict(base, contract_type=ct, duration=2, duration_unit="m", barrier=fmt(b), barrier2=fmt(-b), _ticks=n2, _b=b))
    return out


async def main():
    rows = []
    async with websockets.connect(core.DERIV_WS_URL, open_timeout=15, max_size=2 ** 24) as ws:
        for sym in SIG:
            await ws.send(json.dumps({"ticks": sym}))
            spot = None
            while spot is None:
                m = json.loads(await asyncio.wait_for(ws.recv(), 15))
                if m.get("msg_type") == "tick":
                    spot = m["tick"]["quote"]
            await ws.send(json.dumps({"forget_all": "ticks"}))
            await asyncio.wait_for(ws.recv(), 15)
            for c in grid(sym, spot):
                req = {k: v for k, v in c.items() if not k.startswith("_")}
                await ws.send(json.dumps(req))
                m = json.loads(await asyncio.wait_for(ws.recv(), 15))
                while m.get("msg_type") not in ("proposal",) and not m.get("error"):
                    m = json.loads(await asyncio.wait_for(ws.recv(), 15))
                if m.get("error"):
                    rows.append({"sym": sym, "ct": c["contract_type"], "dur": f"{c['duration']}{c['duration_unit']}",
                                 "barrier": c.get("barrier") or c.get("selected_tick"), "error": m["error"].get("message")})
                    continue
                p = m["proposal"]
                payout = float(p["payout"])
                f = fair(sym, c, float(p["spot"]))
                ev = f * payout / 10 - 1 if f is not None else None
                rows.append({"sym": sym, "ct": c["contract_type"], "dur": f"{c['duration']}{c['duration_unit']}",
                             "barrier": c.get("barrier") or c.get("selected_tick"), "payout": payout, "implied": 10 / payout,
                             "fair": f, "ev": ev})
                await asyncio.sleep(0.25)
    json.dump(rows, open('research/experiments/H16-pricing/data/scan_rows.json', 'w'), indent=0)
    ok = [r for r in rows if r.get("ev") is not None]
    ok.sort(key=lambda r: -r["ev"])
    print(f"priced {len(ok)} contracts, {sum(1 for r in rows if r.get('error'))} refused")
    print("best 15 for the buyer (expected value per $1 staked):")
    for r in ok[:15]:
        print(f"  {r['sym']:8s} {r['ct']:11s} {r['dur']:4s} {str(r['barrier'] or ''):>9s}  payout {r['payout']:6.2f}  true p {r['fair']:.4f} vs priced {r['implied']:.4f}  EV {r['ev']*100:+.2f}%")
    by = {}
    for r in ok:
        by.setdefault(r["ct"], []).append(r["ev"])
    print("house edge by contract type (median, range):")
    for k, v in sorted(by.items(), key=lambda kv: -np.median(kv[1])):
        print(f"  {k:11s} n {len(v):3d}  median {np.median(v)*100:+.2f}%  best {max(v)*100:+.2f}%  worst {min(v)*100:+.2f}%")
    errs = [r for r in rows if r.get("error")]
    if errs:
        print("refused examples:", [(e["sym"], e["ct"], e["dur"], e["barrier"], e["error"][:60]) for e in errs[:6]])

asyncio.run(main())
