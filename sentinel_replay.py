"""
Sentinel replay — run the exact live Sentinel logic over months of Deriv
history and report how ARIA's signals would have performed, after costs.

    python sentinel_replay.py                    # all markets, 15m + 1h
    python sentinel_replay.py --pages 6 --tf 1h --market frxXAUUSD
    python sentinel_replay.py --out replay.json  # keep every trade
    python sentinel_replay.py --pages 40 --baseline sentinel_baseline.json
                                                 # refresh the baseline the
                                                 # Sentinel pane shows

Limits to keep in mind when reading the numbers:
  * News Week is unknown historically, so the NAS100 news-week short block
    is OFF in replay. Live Sentinel applies it.
  * Spreads are estimates (see sentinel_core.MARKETS). Slippage is ignored.
  * Deriv's public feed serves ~1000 bars per page; --pages controls depth.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import sentinel_core as core


def replay_series(m: core.Market, tf: str, bars: list[dict]) -> list[dict]:
    book = core.PaperBook(news_week=False)
    W = core.WINDOW
    for i in range(W - 1, len(bars)):
        book.update(m.id, tf, [bars[i]])
        book.consider(m, tf, bars[i - W + 1:i + 1])
    return [t.to_dict() for t in book.closed]


def _job(args):
    mid, tf, bars = args
    return mid, tf, replay_series(core.MARKET_BY_ID[mid], tf, bars)


async def _load(markets, tfs, pages):
    data = {}
    for m in markets:
        for tf in tfs:
            try:
                bars = await core.fetch_candles(m.deriv, tf, 5000, pages_back=pages)
            except Exception as e:  # keep going; report what failed
                print(f"  ! {m.id} {tf}: {e}", file=sys.stderr)
                continue
            data[(m.id, tf)] = bars
            span = (bars[-1]["time"] - bars[0]["time"]) / 86400 if bars else 0
            print(f"  loaded {m.id:10s} {tf:3s} {len(bars):6d} bars · {span:5.0f} days", file=sys.stderr)
    return data


def write_baseline(trades: list[dict], bars_info: dict, path: str) -> None:
    """Compact summary the live Sentinel shows next to its own journal."""
    live = [t for t in trades if t["mode"] == "real"]
    ex = [t for t in live if t["tier"] == "exec"]            # headline: real markets
    ex_all = [t for t in trades if t["tier"] == "exec"]      # per-market evidence: everything
    starts = [v[0] for v in bars_info.values()]
    ends = [v[1] for v in bars_info.values()]
    fmt_d = lambda e: time.strftime("%Y-%m-%d", time.gmtime(e))
    out = {
        "generated": int(time.time()),
        "period": [fmt_d(min(starts)), fmt_d(max(ends))] if starts else None,
        "notes": ("Replay of the live Sentinel rules on Deriv history. Estimated spreads, "
                  "no slippage, news-week block off. 'exec' = execution-ready (9+/10 gates, ARIA 7.1) on real markets."),
        "all": core.summarise(live),
        "exec": core.summarise(ex),
        "by_slice": core.group_stats(ex_all, lambda t: f"{t['market']} {t['tf']}"),
        "by_score": core.group_stats(live, lambda t: f"{t['score']}/{core.eng.GATE_COUNT}"),
        "synthetic": core.summarise([t for t in trades if t["mode"] == "synthetic"]),
        "engine": core.eng.ENGINE_VERSION,
        "by_elliott": core.group_stats(ex, lambda t: t.get("elliott") or "no count"),
        "gate_pass_rate": {name: round(sum(1 for t in live if t["gates"][i]) / len(live), 3)
                           for i, name in enumerate(core.eng.GATE_NAMES)} if live else {},
    }
    with open(path, "w") as f:
        json.dump(out, f, indent=1)


def fmt(s: dict) -> str:
    if not s.get("n"):
        return "   —"
    ci = s.get("ci95_r") or [float("nan")] * 2
    return (f"{s['n']:5d}  win {s['win_rate']*100:5.1f}%  exp {s['expectancy_r']:+.3f}R "
            f"[{ci[0]:+.2f},{ci[1]:+.2f}]  total {s['total_r']:+8.1f}R  PF {s['profit_factor'] or 0:4.2f}  "
            f"maxDD {s['max_drawdown_r']:6.1f}R  cost {s['avg_cost_r']:.3f}R  → {s['verdict']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=18, help="extra 1000-bar pages of history to load")
    ap.add_argument("--tf", action="append", choices=list(core.TF_SEC), help="timeframe(s); default 15m and 1h")
    ap.add_argument("--market", action="append", help="terminal id(s), e.g. frxXAUUSD (default: the default focus list)")
    ap.add_argument("--out", help="write every trade and the summaries to this JSON file")
    ap.add_argument("--baseline", help="write the compact baseline the Sentinel pane shows")
    a = ap.parse_args()
    tfs = a.tf or ["15m", "1h"]
    markets = [core.MARKET_BY_ID[x] for x in (a.market or core.DEFAULT_FOCUS)]

    t0 = time.time()
    data = asyncio.run(_load(markets, tfs, a.pages))
    with ProcessPoolExecutor() as ex:
        results = list(ex.map(_job, [(mid, tf, bars) for (mid, tf), bars in data.items()]))
    trades = [t for _, _, ts in results for t in ts]

    def show(title, groups):
        print(f"\n{title}")
        for k, s in groups.items():
            print(f"  {k:28s} {fmt(s)}")

    print(f"\nSentinel replay · {len(trades)} paper trades · {time.time()-t0:.0f}s")
    print(f"Target 2.5R → break-even win rate before costs {core.BREAKEVEN_WINRATE*100:.1f}%")
    live = [t for t in trades if t["mode"] == "real"]
    res = [t for t in trades if t["mode"] == "synthetic"]
    show("ALL real markets", {"all": core.summarise(live)})
    show("Synthetic indices", {"all": core.summarise(res)})
    show("By tier (real markets)", core.group_stats(live, lambda t: t["tier"]))
    show("By market × timeframe", core.group_stats(trades, lambda t: f"{t['market']} {t['tf']}"))
    show("By gate score (real markets)", core.group_stats(live, lambda t: f"{t['score']}/{core.eng.GATE_COUNT}"))
    show("By MCC (real markets)", core.group_stats(live, lambda t: t["mcc"]))
    show("By direction (real markets)", core.group_stats(live, lambda t: t["dir"]))
    ex_live = [t for t in live if t["tier"] == "exec"]
    show("Exec-ready by Elliott label (soft layer, real markets)", core.group_stats(ex_live, lambda t: t.get("elliott") or "no count"))
    show("Exec-ready by Elliott alignment (real markets)",
         core.group_stats(ex_live, lambda t: {True: "aligned", False: "against", None: "no count"}[t.get("ew_aligned")]))
    # Which gates carry information? Compare trades where a gate passed vs failed.
    by_gate = {}
    for gi, name in enumerate(core.eng.GATE_NAMES):
        passed = [t for t in live if t["gates"][gi]]
        failed = [t for t in live if not t["gates"][gi]]
        by_gate[f"{name} pass"] = core.summarise(passed)
        by_gate[f"{name} FAIL"] = core.summarise(failed)
    show("Per gate (real markets; FAIL rows = trades taken with that gate failing)", by_gate)

    bars_info = {f"{k[0]} {k[1]}": [v[0]["time"], v[-1]["time"], len(v)] for k, v in data.items() if v}
    if a.baseline:
        write_baseline(trades, bars_info, a.baseline)
        print(f"wrote {a.baseline}")
    if a.out:
        with open(a.out, "w") as f:
            json.dump({"generated": int(time.time()), "pages": a.pages, "tfs": tfs,
                       "bars": bars_info,
                       "trades": trades}, f)
        print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
