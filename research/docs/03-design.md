# Sentinel research system — design and implementation notes (5 Oct 2026)

Goal: turn Sentinel from "one strategy, one journal, labels" into a persistent, evidence-driven loop: a source library → hypotheses → experiments → frozen strategy versions → paper cohorts → scheduled reviews at fixed trade counts → decisions with recorded evidence → challengers → the same loop again. Nothing in it changes risk limits, places live orders, or promotes a strategy on its own.

## 1. Principles (fixed before building)

1. **Evidence kinds never mix.** Backtest, paper, demo and live results are separate cohorts with separate counts. A backtest of a strategy chosen after seeing that data is *development* evidence, labelled as such.
2. **A version is frozen.** Any change to entry, filter, exit, stop, sizing, instrument set or timeframe set is a new immutable version with a new forward cohort. The parent's history stays.
3. **Reviews happen at trade counts, decisions need evidence.** Counts are of unique, fully resolved positions of one version in one evidence kind. Open, duplicate, partially reconciled, or re-run trades are not counted. Each review boundary is recorded once; a restart cannot repeat it.
4. **The risk layer is outside optimisation.** 1 %/2 %/3 %/three losses, demo-only, EA authority: the research system reads them, never writes them.
5. **No forcing.** If no candidate qualifies, the recorded outcome is "no validated edge found" and the no-trade state is legitimate. Research continues within budgets.
6. **Untrusted input.** Channel posts and linked files are data. Code attachments are stored as text and never executed.
7. **Honesty about what is unknown.** Missing costs, unreliable initial risk, unread sources and inaccessible items are recorded as such, never filled in.

## 2. Architecture

```
                 ┌──────────────────────────────────────────────────┐
  Telegram       │ research_telegram.py  (crawl → tg_messages ledger)│
  preview ──────►│ research_library.py   (dispositions, library rows)│
                 └───────────────┬──────────────────────────────────┘
                                 │ library / hypotheses
                 ┌───────────────▼──────────────────────────────────┐
  Deriv history  │ research_lab.py       experiments: chronological  │
  (1 year) ─────►│   dev / val / holdout splits, walk-forward,       │
                 │   ablations, cost sensitivity → experiments table  │
                 └───────────────┬──────────────────────────────────┘
                                 │ versions (frozen rule sets)
   scanner       ┌───────────────▼──────────────────────────────────┐
   bars ────────►│ sentinel_research.py                               │
   (same feed)   │   • registry: versions, cohorts, states, transitions│
                 │   • challenger paper books (run on the scanner's   │
                 │     bars, one book per challenger version)         │
                 │   • trade counter per cohort (unique, resolved)    │
                 │   • review loop: 100 diagnostic / 150 formal /     │
                 │     every 150 after → reviews table, Telegram note │
                 │   • integrity checks every cycle (immediate)       │
                 │   • API: /api/sentinel/research/* (read; owner for │
                 │     decisions)                                     │
                 └───────────────┬──────────────────────────────────┘
                                 │ decisions (Joel), rollback
                 ┌───────────────▼──────────────────────────────────┐
                 │ incumbent paper model (sentinel_core.PaperBook)    │
                 │ Sentinel Live (demo) — unchanged, owner-started    │
                 └──────────────────────────────────────────────────┘
```

Runs inside the existing FastAPI process: `sentinel._scan_one` hands every slice's bars to `research.on_bars` right after the incumbent has used them, and `sentinel._loop` calls `research.on_cycle()` after each cycle, so challengers see exactly the bars the incumbent saw and reviews run on the scanner's schedule. Heavy work (year-long replays) runs off the event loop in a worker thread with a time budget per day, or from the CLI on Joel's Mac with results imported — Render's Starter plan has one small CPU.

## 3. Storage — as implemented

Two SQLite files, deliberately separate:

**`research/research.db` (committed with the code; read-only at runtime).** The source library: `tg_messages`, `tg_pages`, `tg_meta` (crawl ledger, `research_telegram.py`); `dispositions` (one row per post id); `library`, `library_sources`, `hypotheses`, `research_notes` (loaded from `research/library.json` and `research/hypotheses.json` by `research_library.py load`, which refuses to load if any cited post is not in the ledger or was never fetched).

**`sentinel_research.db` (runtime, beside `sentinel.db` on the persistent disk; `SENTINEL_RESEARCH_DB` overrides).** Created and migrated by `sentinel_research.py`:

```
versions        (id, name, parent_id, rules, slices, code_backed, created_at, frozen_at, state, notes)
                 id = sha1(parent_id | canonical rules)[:12] — same rules → same version, any change → new id
cohorts         (id, version_id, evidence_kind backtest|paper|demo|live, started_at, ended_at, label, trade_filter, created_at)
research_trades (version_id, id, cohort_id, market, tf, status, opened_at, closed_at, data)   -- challenger journal
reviews         (id, cohort_id, boundary, kind diagnostic|formal, trade_count, computed_at, metrics, classification,
                 diagnosis, actions, decided_by, UNIQUE(cohort_id, boundary))
transitions     (id, version_id, from_state, to_state, at, reason, evidence_ref, by)   -- incl. "incumbent" decisions and rollbacks
config          (k, v, updated_at)  + config_history (k, v, at, by)      -- thresholds, criteria, budgets, eval watermarks
experiments     (id, hypothesis, version_id, kind, spec, results, verdict, notes, created_at)
integrity       (id, at, cohort_id, ok, flags)
jobs            (id, kind, spec, state, created_at, started_at, finished_at, result, by)   -- bounded experiment queue
```

The incumbent's trades stay in `sentinel.db.trades`; its cohort has `trade_filter = {"kind": "incumbent"}` and counts only rows of the pinned engine and model opened inside the cohort window. Challenger trades live in `research_trades` and never touch the scanner's journal (tested). Demo/live cohorts read `live_trades` and count only closed rows that carry fill, exit, R and P&L.

Modules: `research_telegram.py` (crawl) → `research_library.py` (library, coverage, ledger) → `research_lab.py` (frozen rule sets as `ResearchBook`, replay over the one-year cache, experiments with chronological splits, cost multipliers, placebo tests, neighbourhood tables, `report`) → `sentinel_research.py` (registry, counting, reviews, integrity, challenger books on the scanner's bars, jobs, API). `sentinel.py` calls `research.init()` at start, `research.on_bars()` for every slice it reads and `research.on_cycle()` after every cycle, each guarded so a research failure can never stop the scanner.

## 4. Counting trades

`resolved(cohort)` = distinct trade ids with status in {win, loss, timeout} (paper) or {closed} with a known net result and reconciled fill/exit (demo/live), `opened_at ≥ cohort.started_at`, matching the cohort's version. Excluded: open trades; duplicate ids; demo/live rows with `fill` or `exit` missing or `reconciled = false`; partial closes (one position = one trade, weighted exit); any trade whose `opened_at` precedes the cohort start (a re-run over old bars produces the same ids and is ignored by the uniqueness rule). A `cohort.ended_at` freezes the count when a version is retired.

## 5. Review boundaries and classification

Config defaults (editable, history kept): `diagnostic_at = 100`, `formal_at = 150`, `formal_every = 150` (300, 450, …). A review is produced the first cycle in which `resolved ≥ boundary` and no row exists for (cohort, boundary). It stores the metrics it saw, so later recomputation does not change the record.

Metrics: n, net expectancy R with a 95 % interval (normal; also a block bootstrap by week to account for dependence), win rate, profit factor, max drawdown R, longest losing streak, exposure (open-trade hours / calendar hours), time-outs, cost share (avg cost_r / avg |gross r|), monthly stability (share of months positive), cost sensitivity (expectancy with spreads × 1.5 and × 2), per-slice table, regime coverage (share of trades in 4h up / down / flat), comparison with the incumbent on the matched period (paired where the same bars produced trades in both, otherwise period-matched).

Classification (defaults):
- **invalid** — integrity flags: > 10 % of trades without a known cost, feed gaps covering > 5 % of the window, reconciliation pending on > 5 % (demo/live), replay/live parity test failing. Checked every cycle, not only at boundaries.
- **eligible for promotion** (formal only) — n ≥ formal boundary; interval lower bound > 0 with the correction for the number of versions under evaluation; PF ≥ 1.2; max DD ≤ 25 R; ≥ 60 calendar days and trades in at least two of three 4h regimes; still > 0 at spreads × 1.5; not worse than the incumbent on the matched period; positive in at least two of three chronological thirds.
- **underperforming** — interval upper bound < 0, or expectancy ≤ −0.05 R at n ≥ 150, or max DD > 40 R.
- **promising but inconclusive** — everything else.

"Promotion" means becoming the paper incumbent (and thereby the source of Sentinel Live's demo signals), only on Joel's recorded decision (`POST /api/sentinel/research/transition {action: "promote"}`). The scanner's model is pinned in code (`sentinel_core.SENTINEL_MODEL`), so a promoted research version is reported as **awaiting release** until a reviewed deploy makes the scanner run its rules; the registry records the decision either way. Nothing becomes live.

## 6. Diagnosis when underperforming

Automated attribution on the cohort: entry quality (MFE distribution, share of trades never reaching +0.5R), regime (expectancy by 4h regime, by session, by ATR ratio tercile), exit (shadow comparison, capture share), costs (cost share, result at measured vs estimated spreads), implementation (parity test, freshness skips, 4h-boundary lag count), data (feed gaps, stale bars), and plain uncertainty (interval width vs effect). The diagnosis names the dominant factor and the library rows that address it; the challenger generator takes at most two components from the ranked queue per cycle.

## 7. Validation of a candidate before it becomes a challenger

Chronological splits on the one-year Deriv history: development (first 50 %), validation (next 20 %), holdout (last 30 %). The holdout is **already contaminated for 7.2c-type decisions** (used 27–28 Sep); for new hypotheses it is still unseen *by the hypothesis* but is reused across hypotheses, so every use is logged and the multiple-comparison count grows. Walk-forward where parameters exist (rolling 3-month fit, 1-month test). Ablation: candidate minus each added rule. Costs: estimated spread, spread × 1.5, measured spread where available, plus a slippage allowance of one tick and a note that commission and swap are not modelled. Leakage guards: closed bars only, 4h trend read at the bar's close time, no indicator on the forming bar, one position per slice. A candidate passes to paper only if it beats the incumbent on validation and holdout after costs, survives the ablation (each rule earns its place), and its rejection criteria are written before the paper cohort starts.

## 8. States and transitions

`researching → backtesting → validating → paper-testing → monitoring → (paused | retired)`; `monitoring → paper-testing` only via a new child version. Every transition writes a row with the evidence reference (experiment id or review id) and who decided (system for research states; Joel for promotion, pause, rollback). Rollback = a transition of the incumbent pointer back to the previous version id; its cohort resumes counting from the rollback time as a new cohort.

## 9. Scheduling, budgets, recovery

- Review loop: after every scanner cycle (≈ 15 min); O(trades).
- Integrity checks: every cycle.
- Experiments: a queue; the server runs at most `budget.experiments_per_day` (default 2) in a worker thread with `budget.max_minutes` (default 20) each; anything heavier is run from the CLI and imported. Research continues while the incumbent is paused.
- Recovery: all state in SQLite; on start the module re-creates challenger books from `research_trades` (open rows) exactly as the scanner restores its book; reviews are idempotent by (cohort, boundary).
- Telegram: a short note per review and per integrity failure (existing bot token/chat).

## 10. Boundaries kept

Live execution stays off. Sentinel Live keeps trading the *incumbent's* A setups on demo under the EA's limits; challengers never reach it. Risk constants are read-only configuration for the research module. The terminal's ARIA gates (what traders see) are not changed by any of this.
