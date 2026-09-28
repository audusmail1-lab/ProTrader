"""
Download about one year of Deriv 1-minute candles per market into
data/1m_<symbol>.npz (time, open, high, low, close as numpy arrays).
Used by research_management.py to walk each trade minute by minute.

    python research_fetch_1m.py R_75 frxXAUUSD ...
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

import numpy as np
import websockets

import sentinel_core as core

OUT = os.environ.get("RESEARCH_DATA", "/home/claude/data")
DAYS = 365
PAGE = 1000  # Deriv returns 1000 one-minute bars per request


async def fetch_symbol(sym: str) -> None:
    path = f"{OUT}/1m_{sym}.npz"
    if os.path.exists(path):
        print(f"  have {sym}", file=sys.stderr)
        return
    stop = time.time() - DAYS * 86400
    end = int(time.time())
    rows = {}
    tries = 0
    while end > stop:
        try:
            async with websockets.connect(core.DERIV_WS_URL, max_size=2 ** 24, open_timeout=20) as ws:
                while end > stop:
                    await ws.send(json.dumps({"ticks_history": sym, "count": PAGE, "end": str(end),
                                              "granularity": 60, "style": "candles", "adjust_start_time": 1}))
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 30))
                    if msg.get("error"):
                        raise RuntimeError(msg["error"].get("message"))
                    cs = msg.get("candles") or []
                    if not cs:
                        end -= PAGE * 60   # a closed-market gap: step back
                        continue
                    first = int(cs[0]["epoch"])
                    if first >= end:       # history wrapped around
                        end = stop
                        break
                    await asyncio.sleep(0.15)
                    for c in cs:
                        rows[int(c["epoch"])] = (float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"]))
                    end = first - 1
                    if len(rows) % 50000 < PAGE:
                        print(f"  {sym}: {len(rows)} bars", file=sys.stderr, flush=True)
        except Exception as e:  # reconnect a few times, then give up on this symbol
            if "rate limit" in str(e).lower():   # Deriv throttles ticks_history: wait it out
                print(f"  … {sym}: rate limited at {len(rows)} bars, waiting", file=sys.stderr, flush=True)
                await asyncio.sleep(20)
                continue
            tries += 1
            print(f"  ! {sym}: {e} (retry {tries})", file=sys.stderr)
            if tries > 8:
                break
            await asyncio.sleep(2 * tries)
    t = np.array(sorted(rows), dtype=np.int64)
    a = np.array([rows[x] for x in t], dtype=np.float64).reshape(-1, 4)
    np.savez_compressed(path, time=t, open=a[:, 0], high=a[:, 1], low=a[:, 2], close=a[:, 3])
    span = (t[-1] - t[0]) / 86400 if len(t) else 0
    print(f"  saved {sym}: {len(t)} bars, {span:.0f} days", file=sys.stderr)


async def main(syms):
    sem = asyncio.Semaphore(1)

    async def one(s):
        async with sem:
            await fetch_symbol(s)
    await asyncio.gather(*(one(s) for s in syms))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    asyncio.run(main(sys.argv[1:]))
