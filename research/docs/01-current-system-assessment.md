# Sentinel as deployed — current-system assessment (5 Oct 2026)

Authoritative code: `origin/main` of audusmail1-lab/ProTrader at **9f3cae7**, served at app.protraderacademy.company (Render, persistent disk at /var/data; `/api/health` reports every store persistent). Everything below was read from that tree and from the live public endpoints, not from the `sentinel-update` candidate.

## 1. What is production, what is not

| Thing | Where | Status |
|---|---|---|
| ARIA 7.1 engine (Python port of the terminal's gates) | `sentinel_engine.py` | **production**; parity-tested against the JS (`tests/sentinel-parity.test.cjs`) |
| Paper book, models, shadow exits, statistics | `sentinel_core.py` | **production** |
| Scanner service, journal (SQLite), API, evidence labels | `sentinel.py` | **production**; model `7.2c`, 8 focus markets × 15m/1h/4h at the moment (Joel's saved focus overrides the 3-market default) |
| Sentinel Live (demo-account execution of A setups through the MT5 EA) | `sentinel_live.py` | **production code, demo only**; whether the 30-day test has been started is owner-only data I cannot read from a guest session |
| Replay harness (same code over Deriv history) | `sentinel_replay.py` | research tool; produced `sentinel_baseline.json` (26 Sep 2025 → 28 Sep 2026) |
| Exit/management/selectivity/sizing research | `research_*.py` | one-off research scripts (27–29 Sep 2026); results in the project docs |
| `/Users/joelaudu/Trading bot/sentinel-update/` | Joel's older clone (main at 7c3965c, 25 Sep) | **review candidate, not deployed**: based on f76b4af (28 Sep); its `sentinel_engine.py` equals production, its `sentinel.py`/`sentinel_core.py` carry reliability changes (H4 lookup anchored to the evaluated bar, staleness as "unavailable", `entry_fresh`/`htf_status` on the board, cost-provenance labels, SQLite connection hygiene) that are **absent from production** (`grep entry_fresh sentinel.py` → nothing). Its tests are not in the repo either. |

## 2. The strategy, rule by rule (7.2c, production)

**Data.** Closed candles only, from Deriv's public WebSocket (`fetch_candles` drops the forming bar). ARIA sees a 300-bar window per evaluation. Timeframes 15m, 1h, 4h; the 4h series feeds the trend filter.

**Direction.** `buy` only if close > EMA20 > EMA50 on the evaluated bar; otherwise the read is a `sell` candidate (gate 1 then requires close < EMA20 < EMA50, so a non-stacked market scores at most 9).

**Ten gates (score 0–10).** EMA stack · RSI 50–75 (buy) / 25–50 (sell) · MACD line vs signal · market structure (≥2 higher-high/higher-low pairs in the last 10 bars) · last candle (engulfing, pin, or body in the direction) · ATR band (0.6–1.8 × its 100-bar mean) · macro (close vs EMA200) · stochastic K < 50 for buys / > 50 for sells · pattern gate (same-direction pattern, confidence ≥ 75, on the last 3 bars) · Fibonacci zone (45–66.8 % pullback of the last ≥3-ATR swing, touched within 5 bars, with a reaction).

**Verdict.** ≥ 9 EXEC_READY, 8 QUALIFIED (both are taken), 6–7 WAITING, else OBSERVER. MCC veto: UTC 02:00–06:00 (dead zone) and "fake break" bars are OBSERVER; NAS100 shorts are BLOCKED in a news week (manual flag, off in replay).

**7.2c filters (added 27–28 Sep 2026).** Enter only when the last *closed* 4h bar trends the same way (close vs EMA20 vs EMA50 on 4h; "flat" or "against" holds the signal). No entry on a completed Elliott Wave 5 (soft zigzag count, 2-ATR swings).

**Entry and stop.** Entry = the judged bar's close. Stop = 1.5 × ATR(14) (2.0 on FAKE_BREAK, 2.5 on VOLATILE) → −1R. One open paper position per market × timeframe. A bar that touches stop and a favourable level counts the stop first.

**Exit (7.2c).** No fixed target. Once the trade reaches +1R the stop trails 1R behind the best price; time-out after 96 bars at the close. `tp1_hit` is recorded at +1.5R for reporting only.

**Cost.** One estimated round-trip spread per trade, converted to R (`cost_r = spread / stop distance`): XAU 0.4, NAS100 1.8 points, BTC 30, forex 1.2–2 pips, synthetics 0.02–0.03 % of price. Measured MT5 spreads replace the estimate per market only when the owner has recorded samples (`POST /api/sentinel/costs`). **No commission, swap, slippage or execution delay is modelled anywhere.**

**Freshness.** A bar older than 150 s when scanned is judged but never entered; after a restart the first read never enters.

**Grades (28 Sep).** `A` = 7.2c conditions on one of four slices (NAS100 15m, XAU 15m, XAU 1h, BTC 1h); `A+` = A with 9–10/10; `other` = everything else. Grades label trades; Sentinel paper-trades all focus slices regardless, as a comparison group.

**Shadow exits.** Every paper trade is also managed in parallel by four alternative exits (Joel's $100 rule, swing-structure stop, the hybrid, hold-to-2.5R) on the same bars, so each can be compared trade for trade. They never change what Sentinel takes.

**Risk controls.** Not in Sentinel's paper book (it sizes nothing). They live in the terminal's paper ticket and in the EA for Sentinel Live: 1 % per trade, 2 % open risk, 3 % daily loss, stop after 3 losses, demo only, `AllowRealAccount=false`. The research work must leave that layer untouched.

## 3. Performance calculations as they stand

`summarise()` on finished trades: n, wins (status = win, i.e. a trailing stop above entry or a target), win rate, expectancy in net R with a normal 95 % interval, profit factor, max drawdown in R (time order), average cost, time-outs, and a verdict (needs n ≥ 30; "positive/negative edge" when the interval clears zero). Slices use a Bonferroni-corrected z for the number of focus slices (`z_for`). "Evidence" for a slice is **proven only if the one-year replay AND the forward journal both clear the corrected interval with ≥ 100 trades** (`EVIDENCE_MIN_N`).

Known defects in the calculations:
- `breakeven_win_rate` and `p_vs_breakeven` assume the old fixed-2.5R model; for 7.2c (trailing, no target) they are not meaningful and still appear in `/stats`. The candidate README noted the same.
- `win_rate` counts a trailing-stop exit above entry as a win by label; a trade that locked +0.02R and a −1R loss are "win"/"loss" alike. Net R is the honest measure; stages (`management_stats`) partly repair this.
- Trades are treated as independent. XAU 15m and XAU 1h, or NAS100 and US500 later, open on the same move; the intervals are too narrow by an unknown factor.
- Costs are one spread; see above.

## 4. Where the thresholds come from, and what they do

- `EVIDENCE_MIN_N = 100` (sentinel.py): a **label** on the board/stats ("proven / unproven / negative"), nothing else. It never changes focus, model or risk. It is an evidence requirement, not a trigger.
- The 28 Sep research docs pre-registered two manual checkpoints: at ~100 forward trades per candidate slice, keep a slice only if its forward result is positive and beats the "other" group; at ~150 finished shadow trades, adopt the hybrid exit only if its paired difference vs 7.2c has a 95 % range entirely above zero and its full-loss rate is not higher than breakeven-at-+1R's. **Nothing in code evaluates these; they are notes.** No automatic strategy change exists today, which is the right starting point for the review loop.

## 5. Results so far (measured, not proposed)

**Replay (26 Sep 2025 → 28 Sep 2026, estimated spreads, no slippage), 7.2c, 8+/10:** real markets 4,341 trades, −0.046 R/trade (95 % −0.089 to −0.004), PF 0.92, max DD 225 R. By score: 8/10 −0.044 (n 4,057), 9/10 −0.057 (262), 10/10 −0.35 (22): the score does not separate good from bad. Gate pass rates among signals: Stochastic 29 %, Fibonacci 15 %, everything else > 76 % — most 8/10 signals are "all gates except Stoch and Fib". Four slices were positive on the year (NAS100 15m +0.22, XAU 15m +0.17, XAU 1h +0.18, BTC 1h +0.05) and were chosen on that same year: in-sample.

**Forward paper journal (7.2c, from 27 Sep 2026; read 5 Oct 06:00 UTC):** 154 finished trades, −0.14 R/trade (95 % −0.32 to +0.04), 47 % wins, PF 0.75, max DD 27 R, 0 time-outs, 41 % of each winning move kept. Grade A (the four slices): n 16, **−0.43 R** (−0.86 to −0.01); other: n 136, −0.10. Per slice, n is 1–21 everywhere. Shadows (n ≈ 140 each, paired vs the live exit): $100 rule +0.08 (−0.09 to +0.24), hold +0.03, swing-structure −0.06, hybrid −0.07 (−0.18 to +0.05). **Under the pre-registered rule the hybrid does not qualify at this checkpoint**; 7.2c stays.

**Management journals (owner-only):** unread from here — guest session.

Read plainly: a year of retrospective data says the gate system has no edge across markets after an estimated spread, and the one week of truly out-of-sample evidence says the chosen slices are not escaping that. The right conclusion today is "no validated edge found", with the forward test continuing.

## 6. Weaknesses that the research system must address first

1. **Selection and contamination.** The 7.2c filters, the exit and the four slices were all chosen on the same year; the "hold-out" (last 30 %) was looked at before choosing. The only clean evaluation period for *anything* chosen before 28 Sep is forward from 28 Sep; for anything chosen now, forward from now. Retrospective tests from here on are development evidence only.
2. **Costs are a guess.** Spread estimates; no commission (Deriv MT5 charges commission on some accounts), no swap on 1h/4h holds that span days, no slippage. A −0.05 R system and a +0.05 R system are inside the cost uncertainty.
3. **The score is not a signal strength.** 9–10/10 does no better than 8/10 on 4,341 trades. Any rule that "requires more gates" is already answered: no.
4. **Live/replay parity gap at 4h boundaries.** Live refreshes the 4h trend 30 s after a 4h close, but the cycle runs 8 s after the close, so on the 15m/1h bar that coincides with a 4h close the live scanner uses the 4h bar that closed four hours earlier; replay uses the one that just closed. One in sixteen 15m bars, one in four 1h bars. Small, but it is a real difference between what was measured and what runs.
5. **Candidate reliability changes never merged.** The `sentinel-update` candidate's anchoring, staleness and provenance work addresses genuine causality concerns (H4 availability as "unavailable" rather than flat; cost provenance; partial-close weighting for MT5 results). It is stale against main (two weeks of changes) and would need re-basing and re-review before any of it ships.
6. **Dependence.** One book per market × timeframe but no cap on simultaneous correlated exposure; statistics assume independence.
7. **Trade identity for counting.** Paper trades are unique by `market-tf-bartime` (good). Sentinel Live rows carry `paper_r` beside live `r`; MT5 history "lacks unique deal IDs and may omit entry commissions" (candidate README) — demo/live counts need reconciliation flags, not just closed rows.

## 7. What is good and should be kept

Closed-bar evaluation (no repainting); a replay that runs the same code as the scanner; the shadow design (same entry, same bars, paired comparison); the Bonferroni-corrected evidence label; honest cost-in-R accounting; the pre-registered adoption rule; the persistent disk; the demo-only live path with limits in the EA.
