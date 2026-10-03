# Production-readiness pass — 3 October 2026

Scope: every real user flow of the PROTrader terminal (`protrader_mobile.html`
served by `dashboard.py`), its backend modules (`accounts.py`, `notify.py`,
`mt5_bridge.py`, `sentinel*.py`) and deployment config. The pass was run in a
cloud container without outbound access to Deriv or Yahoo, so live-feed
behaviour was exercised through the recorded Deriv replay the test suite
ships with, and the live-feed failure paths were exercised for real.

**Verdict: production-ready for paper trading and for the MT5 demo flows,
with the "needs attention" items below scheduled.** The reported
position-close bug was reproduced, root-caused and fixed, with regression
tests. Three items are blocking for *real-money* use and are marked as such.

---

## 1. The reported bug: position closed at a level other than the dragged TP

### What happened
Reproduced in a browser test (`tests/test_position_updates_browser.py`,
check "server close must match the current levels"): a buy position with
target 44100 had its target dragged to 44140 on the chart; the journal then
recorded **"Take profit" at level 44140 with an exit of 44105**.

### Root cause — execution on stale trade state (two independent paths)

1. **Server-side watcher judged the old levels, and the app adopted its close
   blindly.** When notifications are on, the app uploads its open paper
   positions to `notify.py`, which subscribes to Deriv ticks and "closes"
   positions server-side so the phone is notified even with the app closed.
   The upload is debounced (400 ms, then every 20 s). A level moved on the
   chart therefore reaches the watcher late — or never, if the phone is
   offline. If a tick crossed the *old* target in that window, the watcher
   recorded a close at the old level, and `NOTIFY.reconcile()` in the app
   closed the position at that price without checking that the level the
   watcher used was still the position's level. The journal then wrote the
   *current* target as the level, producing exactly the mismatch reported.

2. **The chart drag wrote back a stale copy of the other level.** The drag
   draft snapshots the position's stop *and* target when the pill is picked
   up. Confirming a target drag wrote both back, so a stop that had trailed or
   been auto-protected while the pill was held was silently reset to the older,
   looser level (and the trailing flag turned off). The same pattern existed in
   the SL·TP dialog.

Related gaps found while tracing the flow: breakeven ("BE") moved the stop
in memory only — not saved for up to 5 s and never sent to the watcher, so the
watcher kept the old stop; and a modify could be applied to a position whose
manual close was already in flight.

### Fix (all in `protrader_mobile.html` and `notify.py`, shell bumped to v39)
- The watcher's close record now carries the stop and target it was judged
  on. The app accepts a server close only if that level is the position's
  current level (older records without levels: only if the price is at or
  through the current level). A stale close is ignored, acknowledged so it is
  not re-sent, logged, and the position is re-watched on its current levels.
  The server also drops a close when the next sync still lists the position
  with a different level, so the app never sees it.
- The drag confirm re-reads the position before writing and writes **only the
  level that was dragged**; same for the SL·TP dialog (fields left as shown
  are not written). Level changes sync to the watcher immediately.
- Breakeven saves and syncs. Modify/breakeven refuse a position mid-close and
  check the position is still open after the broker round-trip.
- Every trigger close records the exact level it fired on in the journal.

### Residual risk (by design, documented)
The watcher can still *notify the phone* of a close on a level the trader
has just moved, in the sub-second window before the new level reaches the
server. The paper book is now never wrong, but the notification may be. Making
the server the single source of truth for paper positions would remove this;
it is not a quick change.

---

## 2. What was checked

| Area | How | Result |
|---|---|---|
| Market feed, candles, charts | `tests/test_feed_browser.py` against the Deriv replay: loading states, 1,000 aligned bars, paging to 2,000, day stats, local/UTC axis, per-timeframe reads, instrument switching | pass |
| Drawing tools | `tests/test_drawing_browser.py`: all tools, lock/hide, persistence per instrument across reload, measure, text, long-position tool → ticket | pass |
| Trade ticket & risk rules | `tests/test_paper_rules_browser.py`: stop required, 1 % per-trade, 2 % open-risk cap, unprotected trade blocks, 3-loss and 3 % daily locks, auto-sizing from the stop, pending orders sized from the limit price | pass |
| SL/TP, chart drag, position updates | new `tests/test_position_updates_browser.py` (7 checks, incl. a real pointer drag) | pass |
| Server paper watcher | new `tests/test_notify_watcher.py` | pass |
| Journal / position tallies | positions-not-fills, partial closes netted, R multiples, win rate | pass |
| Accounts & auth | `tests/test_accounts.py` + code review (cookies HttpOnly/Secure/SameSite, hashed tokens, PKCE + state, CSRF origin check on every mutating route, no open redirect, graceful when provider or env vars missing) | pass; see §4 |
| MT5 bridge | `tests/test_mt5_tracking.py` + review: 401 without key, body caps, numeric validation, TTL expiry, 409/429 | pass; hardened |
| Sentinel | `tests/test_sentinel_book.py`, `test_sentinel_live.py`, node parity tests | pass |
| Failure handling | server started with no outbound network: `/`, `/app`, `/api/tickers`, notify/account/bridge/sentinel routes all answer; data routes now 404/502/504 instead of 500 | pass after fix |
| Static / PWA | path traversal blocked, ETag/304, service-worker shell cache (version bumped) | pass |
| Logs | 0 tracebacks across all smoke runs; secrets no longer logged | pass |

## 3. Fixed in this pass (safe, tested)

- `protrader_mobile.html`: everything in §1.
- `notify.py`: close records carry levels; superseded closes dropped on sync;
  Telegram poller no longer busy-loops on a revoked token / 409; bot token
  redacted from error logs; per-account de-dupe memory restored after restart.
- `mt5_bridge.py`: a flood of guessed keys can no longer evict a channel with
  a live EA from the relay (unbound channels are evicted first); `true` is no
  longer accepted as a lot size; malformed `results` no longer 500.
- `sentinel.py`: owner-key comparison on bytes (non-ASCII header no longer
  500s); bot token redacted from logs.
- `dashboard.py`: data routes map "no data"/timeouts to 404/504/502 with a
  fixed message and a server-side log line instead of leaking library text as
  a 500; `/api/quotes` capped at 25 symbols, timeout handled, cache bounded.
- `accounts.py`: startup warning on Render when the DB is on ephemeral disk.
- `DEPLOY.md`: persistent-disk section. `static/sw.js`: shell v39.

## 4. Needs attention (not changed here)

**Blocking before real-money use**
1. **Persistent disk on Render** (`render.yaml` has no `disk:`). Without it every
   deploy wipes accounts, sessions, Telegram links, saved workspaces and the
   notification state. Cost ≈ $0.25/month; instructions in DEPLOY.md. Not
   added to `render.yaml` here because it changes billing.
2. **Blocking I/O on the event loop / under locks.** `notify._deliver`
   (push + Telegram, up to ~16 s) runs while holding the notify lock and, for
   MT5 events, inside the bridge lock on the async `/ea` handler. A slow
   Telegram stalls every bridge channel and the whole server. Fix: hand events
   to a queue drained by a sender thread. Several `async def` handlers also
   run synchronous `requests`/SQLite (`notify.register/test/event`,
   `accounts.switch/workspace_put/telegram_webapp`); make them plain `def`.
3. **Sentinel live orphaned positions.** An entry whose result is lost
   (relay restart, results deque overflow) is marked rejected after 60 s and
   forgotten; a filled position would then be unmanaged and outside the risk
   caps. A lost *close* result is never retried. Both need reconciliation
   against the EA snapshot.

**Should fix soon**
4. Paper-trading alerts (`/api/alerts`) are global, in-memory and only
   evaluated when someone calls `/api/analyze`; they are not used by the app
   itself — remove or move behind the account.
5. yfinance routes run unbounded blocking downloads on the shared threadpool
   that also serves `/` and the health check; a hung Yahoo can stall the app.
   The live app does not call them (it is Deriv-only), so gate them or add a
   per-call timeout.
6. Session/role refresh: `allowed()` uses the role cached at sign-in for up to
   30 days; re-check the Academy profile periodically. Telegram WebApp
   `initData` accepted for 24 h (lower to minutes).
7. Bridge key entropy is not checked (format only) and 401s are not
   rate-limited.
8. `requirements.txt` pins need Python 3.12 (Dockerfile has it; local dev on
   3.11 cannot install the pins).

**Test suite**
9. `tests/test_accounts.py::test_logout_and_instructor_is_sentinel_owner`
   fails only when run together with the other test modules (shared env/DB
   between modules); passes alone and on the untouched code. Isolate the
   Sentinel owner-key env var per test.
10. Browser tests need the Playwright build that matches the installed
    Chromium; `python3 tests/test_*_browser.py` each, plus `node tests/*.cjs`.

## 5. Running the checks

```bash
python3 -m pytest tests -q                       # Python unit + API tests
python3 tests/test_paper_rules_browser.py        # risk rules, auto-protect, journal
python3 tests/test_position_updates_browser.py   # SL/TP drag, server closes, breakeven
python3 tests/test_feed_browser.py               # Deriv feed, candles, charts
python3 tests/test_drawing_browser.py            # drawing tools
for f in tests/*.test.cjs; do node "$f"; done    # Sentinel parity
```
