# H20 — Drift: owning the indices' rise inside the bot's risk rules (8 Oct 2026)

Joel's choice (option 1): the demo bot holds US Tech 100 and US 500 long at no more than 1x the account, steps aside
when an index closes below its 200-day average, demo first. The question here is engineering, not a new edge
(the drift itself is H19): **can the demo bot do that inside the risk framework?** The EA requires a stop on every
entry and refuses more than 1% of equity at the stop, 2% open; that framework stays as it is.

## What fits

A 1x position whose only exit is the 200-day line has no stop, so the EA refuses it. The framework fits Drift only
when the line becomes the stop: a stop 3% under the 200-day average, raised with it every day, never lowered.
Sizing at that stop then decides how much is invested: risk ÷ distance to the stop.

## Numbers (FRED daily closes, Deriv CFD costs: financing T-bill + 2.5%/yr, 0.03% a side; fills at the close)

| Version | Span | A year | Worst | Invested on average |
|---|---|---|---|---|
| Index fund, held (H19) | Nasdaq-100 1987–2026 | +14.3% | −83% | 100% |
| **Joel's pick**: 1x CFD, out under the line | Nasdaq-100 1987–2026 | +6.8% | −65% (Mar 2000 → May 2009) | 76% |
| — its 2000–2012 | | −4.8% | | |
| Inside the rules, 1% risk at the line stop | Nasdaq-100 1987–2026 | +2.0% | −22% | 18% |
| Inside the rules, ½% (the demo version, Nasdaq half) | Nasdaq-100 1987–2026 | +1.1% | −12% | 9% |
| Fixed 8% stop, 1% risk, up to 3 units | Nasdaq-100 1987–2026 | +2.2% | −18% | 21% |
| Joel's pick, both indices | 2017–2026 | +8.2% | −21% | 82% |
| Both, 1% each at the line stop | 2017–2026 | +4.1% | −11% | 36% |
| **Both, ½% each (the demo version)** | 2017–2026 | +2.1% | −6% | 19% |

The stop distance is a dial on exposure, not an edge: 2% under the line gives more return and a deeper drop, 5% less
of both (`rules_probe.out.txt`). Rolling a risk-free position into a bigger one changed nothing (the 0.5x cap binds first).
FRED keeps only ten years of the S&P 500, so the two-index rows cover a rising decade only.

## Reading

- The 1% rule caps what can be invested at risk ÷ stop distance. With a stop wide enough for a months-long hold that
  is a fifth of the account or less, so inside the rules Drift is a small, steady sleeve.
- Joel's 1x version earns about three times as much with about five times the worst drop. It needs its own risk class
  (an investment sleeve outside the trading rules); that is Joel's decision and is not made here.
- Every version lost money over 2000–2012. A CFD hands about half of the index's rise to financing; an index fund keeps it.

## Why ½% per index on the demo

Two Drift positions at full risk then use 1% of the 2% open-risk room, so Sentinel Live always keeps room for one A
setup. At 1% each, a fresh pair of entries would hold the whole 2% for months (the stop sits 4–5% under the entry
until the line catches up) and Sentinel Live would be blocked.

## The minimum lot (8 Oct)

US Tech 100 closed 12.9% above its line: the stop sits about 4,390 points under the price, so one 0.01 lot at $1 a
point risks about $44 and ½% needs about $8,800 of equity. US 500: about 770 points, $7.70, $1,540. The demo reads
the real contract spec from MT5; below that equity Drift journals "minimum lot would risk …" and waits (the paper book
still trades fractional sizes).

## Built (preview, `drift.py`)

Stored Deriv daily candles (Deriv serves one year), the 200-day signal, two paper books from the same candles
(pick: 1x; rules: the demo version) with next-open fills, intraday stops and financing, and the demo through Sentinel
Live's executor (same journal table, same risk counters, demo-only, owner Start/Stop, orders only inside 06:00–20:00 GMT
with a fresh Deriv price). Tests: `tests/test_drift.py`, `tests/test_drift_browser.py`. Probed live 8 Oct: both indices
above their lines (US Tech 100 +12.9%, US 500 +7.6%); the books start from the 7 Oct close.

Scripts: `rules_probe.py` (line stop), `stop_probe.py` (fixed stops, the 1x drawdown). Data: FRED NASDAQ100, SP500,
DTB3 in `research/data/fred` (not committed).
