# The 7.3 candidate — what was built, what was measured (7 Oct 2026)

Built on Joel's "build" (7 Oct). A **paper challenger** beside the incumbent; nothing about the incumbent's trades, Sentinel Live (demo) or the risk framework changes.

## What it is

| | Incumbent (ARIA 7.1 / 7.2c) | 7.3 candidate |
|---|---|---|
| Entries | ARIA 7.2c | same reads, same 4h-trend and Wave-5 filters |
| Markets | 8 (3 real, 5 synthetic) | **real markets only**: NAS100, XAUUSD, BTCUSD × 15m / 1h / 4h |
| Cost rule | none | **skip the entry when spread > 5 % of the stop** (H2) |
| Main exit | 7.2c 1R trail | same |
| Shadow exits (paired, change nothing) | usd100, structure, hybrid, hold | the same four **plus atr2 (2×ATR(14) ratchet) and chan10 (10-bar counter channel)** — also added to the incumbent, so both books collect them |
| Evidence | forward paper journal from 27 Sep | its own paper cohort from launch; 100/150 reviews against the incumbent on the matched period |

Code: `CODE_CHALLENGERS` and `register_code_challengers()` in `sentinel_research.py` (registered once at startup as a child of the incumbent, moved to `paper-testing` with the evidence reference; an owner pause or retirement survives restarts; not code-backed, so a promotion reads "awaiting release"); `atr2` / `chan10` in `sentinel_core.shadow_rules()`; challenger books now run shadows and restore trades whose shadow exits outlive the model exit; reviews carry the paired shadow table. With two versions under test the review's evidence bar rises (Bonferroni), for both.

## A. Measured — one-year replay (development evidence, `V73-candidate.result.json`)

Same windows as docs/04 (dev 3 Oct 2025 → 4 Apr 2026, validation → 17 Jun, holdout → 5 Oct). Estimated spreads; no commission, swap or slippage.

| | dev | validation | holdout | all (95 % CI) | holdout at ×2 cost |
|---|---|---|---|---|---|
| 7.2c on the three real markets | +0.078 R (n 1,037) | +0.089 (505) | +0.045 (713) | +0.070 [+0.007, +0.133], PF 1.13 | −0.024 |
| + cost cap 0.05 (the candidate) | +0.105 (732) | +0.168 (327) | +0.088 (452) | **+0.114 [+0.041, +0.186]**, PF 1.23, DD 41 R | +0.064 |

- **Placebo test of the cap** (accepted vs random subsets of the same signals): net p 0.18 / **0.026** / 0.28; gross p 0.39 / 0.10 / 0.63. Same verdict as H2: a **cost rule, not an edge**. The neighbourhood is a plateau from 0.04 to 0.06, no peak.
- **Shadow exits in replay (paired vs the 7.2c exit, all windows)**: atr2 +0.009 [−0.035, +0.054]; chan10 +0.006 [−0.079, +0.091]; hybrid +0.056 [−0.006, +0.118]; structure +0.036; usd100 −0.038; hold −0.071 [−0.127, −0.015].
- **In-sample warning.** The three real markets and the 7.2c filters were chosen on nearly this same year (docs/04). The candidate removes the synthetic indices for a structural reason (Deriv generates them with a random number generator), not from these numbers, but the positive per-market results above are not independent evidence.

## B. Measured — forward journal, the evidence that counts (7 Oct, public endpoints)

- **The same three real markets, forward since 27 Sep: 70 trades, −11.6 R, ≈ −0.17 R per trade.** The replay says +0.07. The gap (≈ 0.24 R per trade) is the backtest-to-live gap the literature describes (Quantopian, 888 algorithms), visible in our own data. The cap would not have rescued it: most of the forward loss is XAUUSD 15m (14 trades, −7.75 R), which the cap barely touches.
- **Forward shadow exits (incumbent, 188–214 paired trades):** usd100 (Joel's $100 breakeven-and-trail rule) **+0.148 R per trade better than the model exit [+0.015, +0.282]** — the only alternative exit whose interval clears zero; hybrid −0.095 [−0.194, +0.003]; structure −0.118 [−0.265, +0.030]; hold −0.001. The replay ranked them the other way round. Four rules were compared, so usd100 is *promising*, not proven (a Bonferroni bar for four comparisons would include zero).

## C. Proposed (not measured, nothing adopted)

1. Launch the candidate as built (owner decision). At the forward rate (≈ 6.9 real-market trades a day, two-thirds kept by the cap) the 100-trade diagnostic arrives in about three weeks and the 150 formal review in about five.
2. Watch usd100 on both books. If its paired advantage holds at the 150-trade boundary with the multiple-comparison bar, the next challenger is "7.3 entries + usd100 as the main exit" — that needs a `usd100` main-exit kind in `ResearchBook` (lab support, not built).
3. If the candidate's forward cohort is negative at 150 like the incumbent's, the recorded outcome stays "no validated edge" and the no-trade state remains the default; the replay numbers above do not override that.
