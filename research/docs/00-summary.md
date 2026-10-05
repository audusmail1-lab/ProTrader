# Sentinel research system — assessment, coverage, library, loop, measured results (5 Oct 2026)

**Status: built and tested on the cloud clone as four commits on top of origin/main 9f3cae7 (6c5aff1 → 8d32f76); NOT pushed, NOT deployed.** Awaiting Joel's "launch". Live execution untouched; Sentinel Live (demo) and the 1/2/3 %/three-loss risk layer are not changed by anything here.

Full write-ups live in the repo under `research/docs/`: 01 current-system assessment · 02 Telegram coverage and library · 03 design and implementation · 04 candidates and measured results · 05 roadmap and blocked inputs. This page is the summary.

## 1. Sentinel as it is (verified on origin/main, not the sentinel-update folder)

Production = ARIA 7.1 engine (10 gates, 8+/10 taken) + paper model 7.2c (entry only with the last closed 4h EMA20/50 trend, no Wave-5 entries, stop 1.5/2.0/2.5×ATR, +1R arms a 1R trail, 96-bar timeout), one open paper position per market×timeframe, closed bars only, one estimated spread per trade, no commission/swap/slippage. `/Users/joelaudu/Trading bot/sentinel-update` is an unmerged review candidate (reliability changes absent from production). The 100-trade threshold (`EVIDENCE_MIN_N`) is only a proven/unproven label; nothing in production changed strategy automatically — the right starting point.

Measured (not proposed): one-year replay 4,341 real-market trades −0.046 R/trade; 9–10/10 scores no better than 8/10; forward paper journal since 27 Sep n = 154 at −0.14 R, A-grade slices n = 16 at −0.43 R. Weaknesses: the 7.2c filters and the four slices were chosen on the same year they were measured on; costs are a guess; the score is not a signal strength; a 4h-boundary parity gap between live and replay; trades assumed independent.

## 2. Telegram coverage (verifiable)

Channel: @mql5dev "MQL5 Algo Trading" (official MetaQuotes, 566K subscribers). Crawled the public preview end to end: ids 1–4304, 4,274 fetched with text/links/media, 30 unavailable (listed), 0 forwarded, no comments exposed. Every id has exactly one disposition (implementation_technique 1,883 · supporting_insight 1,370 · testable_hypothesis 673 · no_strategy_content 187 · announcement 101 · unsupported_claim 50 · inaccessible 40). Ledger: `research/coverage_ledger.csv`; numbers recomputed by `python research_library.py coverage`. Limits: linked mql5.com articles were not fetched (only the posts' text is cited); comments/replies would need a logged-in Telegram Desktop export.

## 3. Library and shortlist

35 distinct methods from 302 cited posts (`research/library.json`): claim vs evidence, rules by field, missing rules, my interpretation marked as mine, relation to Sentinel. Ranked 12 hypotheses with hypothesis, rules, sources, expected benefit, failure conditions, bounded parameters, rejection criteria and ablations written before any test (`research/hypotheses.json`). "Working strategy" criteria defined first: n ≥ 150 forward, interval above 0 (block bootstrap by week, Bonferroni for versions under test), PF ≥ 1.2, max DD ≤ 25 R, ≥ 60 days and ≥ 2 regimes, still > 0 at spreads ×1.5, not worse than the incumbent on the matched period, positive in 2 of 3 thirds. Development evidence can only qualify a candidate for a paper cohort; it never promotes.

What the channel offers: very few quantified results, almost none out of sample; its real value is a handful of careful studies (#3292 session filter, #4121 gold reopen drift, #4282/#4283 gold breakouts, #4027 null ML result) and a consistent validation/cost methodology (placebo and permutation tests, CSCV/walk-forward, bootstrap/concentration, measured spreads, data audits) that the loop now adopts.

## 4. First testable improvement and what the tests found

First candidate: a session-window gate on ARIA entries (post #3292, the only quantified source). Measured on one year of Deriv history, 16 slices, chronological dev/val/holdout, costs ×1/×1.5/×2, placebo against 1,000 random subsets:

| Hypothesis | Result |
|---|---|
| Baseline 7.2c | −0.035 R/trade (n 6,257), negative in all three windows; 4h trend and trailing exit each earn their place vs worse versions of itself |
| H1 session window | **rejected as an edge**: beats random subsets only on validation (p 0.002), not on development (0.13) or holdout (0.35); lift is cost, gross unchanged |
| H2 cost-to-stop cap ≤ 0.05 | **cost rule, not edge**: net improves on dev/val, gross never beats placebo, holdout −0.012; it is a "don't trade 15m FX at this spread" rule (keeps 96 % of index/gold trades) |
| H3 ADX gate | **rejected**: worse than random in every window; family closed |
| H4 ATR-trail / channel exits | **inconclusive**: nothing turns the system positive; channel-10 better on dev and holdout, worse on validation → propose as paired shadows on the forward journal |
| H5 autocorrelation gate | **rejected** (p 0.086 / 0.39) |
| H6 Donchian breakout challenger (gold/indices 1h–4h, #4282) | **rejected on this data**: no variant positive on validation and holdout; the gold H4 claim is absent in the last year |
| H7 gate ablation | **no gate makes it positive**; Fibonacci and Stochastic carry some information, EMA/RSI/structure/macro are inert |

93 configurations in all, so the holdout is no longer untouched for these ideas. **Recorded outcome: no validated edge found.** The no-trade state is legitimate.

## 5. What was built (the loop as software)

- `research_lab.py`: frozen rule sets (hash = version identity), ResearchBook (same conventions as the incumbent; identical trades with no gates — tested), causal replay with cached ARIA reads, splits, cost multipliers, placebo tests, neighbourhood tables, `report`.
- `sentinel_research.py` + three guarded hooks in `sentinel.py`: registry on the persistent disk (`sentinel_research.db`): versions (immutable), cohorts per evidence kind (backtest/paper/demo/live), unique resolved-position counting (open, duplicate, pre-cohort re-runs, unreconciled demo rows excluded), reviews at 100 (diagnostic) / 150 (formal) / every 150 after, configurable; each boundary stored once (restart-safe); classification eligible / inconclusive / underperforming / invalid with a diagnosis in R per factor (entry, regime, session, slice mix, exit, costs, uncertainty) pointing at library rows; integrity every cycle (acts at once); challenger paper books fed the scanner's own bars; bounded experiment jobs (2/day, 20 min); explicit states with recorded transitions; promote and rollback as recorded owner decisions (the scanner's model stays pinned in code: a promoted research version shows "awaiting release" until a reviewed deploy). API under `/api/sentinel/research/*` (status, versions, reviews, cohorts, hypotheses, library, coverage, experiments; owner: versions, transition, config, jobs).
- Tests: 24 new (causal reads, parity, exits, Donchian, counting, idempotent boundaries across restarts, configurable thresholds, classification incl. Bonferroni, integrity-before-boundary, immutability/isolation, promote/rollback, restored open trades, one judgement per bar) + all existing suites green (54 pytest, 22 node). Integration run: one scanner cycle on cached bars produced the incumbent's 100 (inconclusive) and 150 (underperforming) reviews, no duplicates after a simulated restart.

## 6. After launch

On the first cycle the incumbent's 100/150 reviews are produced from the forward journal (154 resolved on 5 Oct) and sent to Telegram. No challenger runs until Joel creates one and moves it to paper-testing with an experiment id as evidence.

## 7. Blocked inputs / remaining work

Measured costs (spread by hour, commission, swap from Deriv MT5 — the biggest unknown: every number above is worse at ×1.5); owner-only journals (demo cohort logic tested only on synthetic rows); Telegram comments; historical calendar for news filters; MT5↔WebSocket candle parity; re-basing the sentinel-update reliability changes; adding the two exit shadows (B3); H2 as a cost rule once spreads are measured.
