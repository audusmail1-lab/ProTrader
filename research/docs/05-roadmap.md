# Implementation roadmap and remaining work (5 Oct 2026)

## Delivered in this change set (review candidate, not launched)

| Piece | Where | Verified by |
|---|---|---|
| Current-system assessment | `research/docs/01` | read from origin/main 9f3cae7 and the live endpoints |
| Telegram coverage ledger (4,304 ids, every one with a disposition) | `research_telegram.py`, `research/research.db`, `research/coverage_ledger.csv`, `docs/02` | `python research_library.py coverage` recomputes every number in the report |
| Research library (35 methods, 302 cited posts) and ranked shortlist (12 hypotheses with rejection criteria) | `research/library.json`, `research/hypotheses.json`, `research_library.py` | `python research_library.py check` refuses any citation not in the ledger |
| Frozen rule sets, research book, replay with cached reads, chronological splits, cost multipliers, placebo tests, neighbourhood tables | `research_lab.py` | `tests/test_sentinel_research.py` (parity with the incumbent book, no look-ahead, exits, Donchian entry, placebo sanity) |
| Registry: versions, cohorts, counting, 100/150 reviews, classification, diagnosis, integrity, challenger books, jobs, API, CLI | `sentinel_research.py`, hooks in `sentinel.py` | same suite: counting exclusions, idempotent boundaries across restarts, configurable thresholds, classification rules, Bonferroni with more versions, integrity before boundaries, immutability/isolation, promote/rollback, restored open trades, one judgement per bar |
| Measured experiments H1–H7 | `research/experiments/*.result.json`, `docs/04` | `python research_lab.py report <id>` |
| One-year history cache (not committed, 30 MB) | `research/history/` via `python research_lab.py fetch` | — |

`sentinel_core.py` changed in one behaviour-preserving way: `PaperBook.consider` now calls `_open_from_read`, so research books can gate between the read and the entry. The replay of NAS100 1h before and after the change is byte-identical (checked), and the existing book/parity suites pass.

## What happens after a launch

1. On the server, `sentinel_research.db` is created beside `sentinel.db`; the incumbent version (ARIA 7.1 / 7.2c) and its paper cohort from 27 Sep 2026 are registered; `GET /api/sentinel/research/status` shows the resolved count (the forward journal had 154 resolved trades on 5 Oct, so the **100-trade diagnostic review of the incumbent is produced on the first cycle**, and the 150 formal review with it). Both are stored once; restarts never repeat them.
2. Integrity runs every cycle: unreconciled demo rows, trades without a known cost, a silent scanner → `invalid` at once, with a Telegram note.
3. No challenger runs until one is created and moved to `paper-testing` by the owner (`POST /versions`, `POST /transition`), with the experiment id as evidence. The shortlist's first qualifying candidate is **none yet** (see `docs/04`): the recorded outcome is "no validated edge found", the incumbent keeps collecting evidence, and the no-trade option stays legitimate.
4. Experiments on the server are bounded (`budget.experiments_per_day` = 2, `max_minutes` = 20) and need the history cache (`python research_lab.py fetch` on the host, or run from the Mac and `python sentinel_research.py import-experiments`).

## Blocked inputs (cannot be done from this session)

- **Measured costs.** Spread samples per market by hour, commission and swap from Joel's Deriv MT5 accounts (the `spec` bridge command and `POST /api/sentinel/costs`). Until then every R figure is price-based minus an estimated spread; the results are reported at ×1, ×1.5 and ×2 of that estimate for exactly this reason.
- **Owner-only journals.** Sentinel Live (demo) and management journals are behind the owner key; the demo cohort logic is implemented and tested on synthetic rows but has not seen real rows.
- **Telegram comments/replies** and the 30 unavailable ids: only a logged-in export (Telegram Desktop → Export chat history → JSON) would add them.
- **Historical economic calendar** for L06 (news blackout tests).
- **MT5 ↔ WebSocket candle parity**: needs bridge samples of MT5 bars to compare with Deriv's public feed.

## Next steps, in order

1. ~~Launch the change set; confirm the incumbent's 100/150 reviews on the server and read them.~~ Done 5 Oct: diagnostic at 100 inconclusive (−0.199 R), formal at 150 underperforming (−0.130 R), dominant factor exit, then entry quality (docs/00).
2. Record H1/H3/H5 as rejected and H2 as a cost rule in `hypotheses.json` (done in this change set) and queue the next two from the ranked list that the incumbent's diagnosis points at — the diagnosis in the 150-trade review decides, not the order of the list.
3. Measure costs (blocked input above); re-run H1–H7 at measured spreads by hour. If measured spreads are wider than the estimates, every result above gets worse, and the cost-cap rule gets more important, not less.
4. If H6 (Donchian challenger) survives its own rejection criteria on measured costs, create its version, move it to `paper-testing` with the experiment id, and let the 100/150 loop judge it against the incumbent on the matched period.
5. ~~Add the ATR-trail and channel exits as shadow rules on the incumbent (H4) so the forward journal collects paired evidence at no extra cost.~~ Built 7 Oct with the 7.3 candidate (docs/06): atr2 and chan10 run on both books.
6. Re-base and review the `sentinel-update` reliability changes (H4 anchoring, staleness as "unavailable", cost provenance) as their own change set; they are not in this one.
7. Every 150 trades: the loop produces the review; a human reads the classification and the diagnosis; at most two challengers from the library per cycle; "no validated edge found" is a complete, acceptable outcome of a cycle.
8. 7 Oct: the 7.3 candidate (real markets, cost cap 0.05, exit shadows) is built as a code-registered paper challenger (docs/06). Replay +0.114 R/trade but forward on the same markets −0.17 R; the forward cohort decides. Forward shadows favour usd100 (+0.148 R vs the model exit, not yet multiple-comparison proof).
9. 7 Oct: Joel Twin built (docs/07): every closed MT5 trade on the bridged account replayed under Joel's own rules (1% stop cap, $100-per-$36.9k breakeven and trail), shown as you vs twin. Replay verified against the live usd100 shadow on 190 trades.
10. 7 Oct: H13 (fade the last 15 minutes on Vol 50 (1s), found on 8 days of minute bars) **rejected** before any build: on the year of 15-minute bars before the discovery window, 34,218 decisions averaged −0.02 bp gross (95% ±0.28), hit rate 49.8%, lag-1 autocorrelation +0.0006 — against a spread of about 2 bp. The 'Joel Scalper' paper bot was therefore not built.
11. 7 Oct: H14 (ARIA multi-timeframe agreement as a trade filter) **rejected** on its pre-registered criteria — strong in development, gone or reversed in validation and holdout (docs/08). Paper-account monitor built: Sentinel reads the owner's saved paper account, real R per trade, skill check, Joel Twin on paper positions.
12. Pricing audit (09): synthetic contracts all carry a fixed house margin (closed). Live index quotes (8 Oct) show Deriv builds an upward drift into Rise prices (~62% odds on US Tech 100); short Rise and all range contracts have no edge. Only 6- and 12-month Rise beat Deriv's price on 2001-2026 history, on few independent years. Contract book (preview) watches those four contracts.
13. 8 Oct: everything recollected in docs/10. New: the A/A+ trades Sentinel Live takes are −0.24 R over 40 forward trades (replay said +0.16); the $100 rule's forward lead vanishes on real markets at 1-minute resolution (do not switch exits); H17 slow trend following on 13 real markets over 40 years **rejected** after retail financing (Sharpe 0.56 → −0.03). Evidence brake built into Sentinel Live (Joel's choice).
14. 8 Oct: Drift built as a preview (H20, `drift.py`): the 200-day line on US Tech 100 and US 500 from stored Deriv daily candles; paper books for Joel's 1x pick and for the demo version inside the risk rules (½% per index at a stop 3% under the line); the demo runs through Sentinel Live's executor and limits after the owner presses Start. Inside the 1% rule it is a small sleeve (+2.1%/yr over 2017–2026); the 1x version needs its own risk class, which is Joel's decision.
