# Telegram coverage report and research library (5 Oct 2026)

## 1. What was covered, and how

**Channel.** "MQL5 Algo Trading", handle `@mql5dev` (t.me/mql5dev), the official MetaQuotes channel ("The best publications of the largest community of algotraders"), 566K subscribers at crawl time. Every post is a short editorial summary (typically 600–900 characters) of one mql5.com article or CodeBase item, with the link. There are no forwarded posts; comments and replies are not exposed by the public preview; the owner's export (section 5) confirms there are none to review.

**Method.** `research_telegram.py` crawled the public web preview (`t.me/s/mql5dev`, paginated with `?before=<id>`) from the newest post back to id 1, in 213 pages, with resumable checkpoints (`tg_pages`). Every message id from 1 to 4304 has a row in `tg_messages` (`research/research.db`): 4,274 fetched with full text, links and media type; 30 ids that the preview does not serve are recorded as `unavailable` (ids 2–25 — the channel's first days, deleted or service messages — plus 111, 386, 450, 895, 976, 3211). The crawl finished 2026-10-05 11:11 UTC; the newest post is #4304 (2026-10-05 06:00 UTC), the oldest fetched is #1 (2023-10-05).

**Dispositions.** All 4,304 ids have exactly one row in `dispositions` (`messages_without_disposition = 0`). The 4,274 fetched posts were classified in 29 batches of ≤150 by independent Sonnet classification passes under `research/classify_instructions.md` (schema: topic, disposition, summary, claim, evidence stated, explicit rules, missing rules, relation to Sentinel, relevance 0–3), then validated (every id present, every field present) and merged. The 30 unavailable ids are `inaccessible` by the crawler. Ten fetched posts are also `inaccessible` because their body is empty, a media placeholder, a "pinned a photo" service line, or — in three cases (#2815, #3236, #3255) — the channel published a text-generation error placeholder instead of a summary; their linked CodeBase items (66130, 37066, 37065) are known but their content was not read, so they are not cited.

**Spot checks.** The 116 relevance-3 posts were read in full by me, as were the summaries of all 468 relevance-2 hypotheses; the library below was built from those readings, not from the classifier's labels alone. Linked mql5.com articles were **not** fetched: every claim in the library is what the *post* states, which is the channel's summary of the article. That is a real limit: author names, exact parameters and result tables often live only in the article. Where the post names numbers they are quoted; where it does not, the row says "not stated".

**Untrusted input.** Posts, links, images and any code mentioned were treated as data. No attachment or CodeBase item was executed or reproduced.

## 2. Coverage ledger — numbers (computed by `python research_library.py coverage`)

| | |
|---|---|
| Message ids | 1 – 4304 (4,304 rows) |
| Fetched with text | 4,274 |
| Unavailable in the preview | 30 (listed above) |
| Dispositions | 4,304 (one per id) |
| Posts linking a unique mql5.com article/code item | 4,180 posts → 4,173 unique items |
| Media | photo 4,242 · video 6 · link preview 1 · none 25 |

Disposition totals: implementation_technique 1,883 · supporting_insight 1,370 · testable_hypothesis 673 · no_strategy_content 187 · announcement 101 · unsupported_claim 50 · inaccessible 40.
Topics: infrastructure 1,428 · entry_signal 1,005 · ml_forecasting 579 · validation_testing 351 · filter_regime 246 · risk_sizing 171 · portfolio_multi 161 · exit_management 136 · other 122 · announcement 101 · market_commentary 4.
Relevance to Sentinel: 3 → 116 posts (56 hypotheses) · 2 → 822 (468 hypotheses) · 1 → 1,876 · 0 → 1,490.

The per-post ledger is `research/coverage_ledger.csv` (id, URL, date, fetch status, media, disposition, topic, relevance, who decided, library rows citing it, linked item).

## 3. The library

`research/library.json` (loaded into the `library` and `library_sources` tables) holds **35 distinct methods** built from **302 cited posts** (110 of the 116 relevance-3 posts and 192 relevance-2 posts). Each row records source post ids and dates, the mql5.com item each post links, author (named only when the post names one — almost never), the claim as stated, the evidence the posts themselves offer, limitations, explicit rules by field, missing rules, my interpretation marked as mine, and the relation to Sentinel (overlap / contradiction / complement / none). Classification: 23 testable hypotheses, 10 supporting insights, 2 implementation techniques. Duplicates (the same article posted twice, e.g. #27/#47, #1492/#1508/#1527, #3638/#3709) are cited together on one row rather than given rows of their own.

| id | Method | Relation to Sentinel | Best evidence in the posts |
|---|---|---|---|
| L01 | Session-window entry filter | complement | #3292: +0.017R → +0.100R (PF 1.03 → 1.20) with a 14:00–20:00 window on US_TECH100 H1, five years |
| L02 | ADX trend-strength gate | overlap/complement | logic only; #3292's regime layer "added little" |
| L03 | Persistence/randomness gates (Hurst, autocorrelation, FDI, ApEn, entropy) | complement | logic only |
| L04 | H4 swing-structure context gate | overlap with 4h trend | logic only |
| L05 | Spread-to-stop / spread-percentile gate | complement | logic only; part of #4282's EA |
| L06 | Calendar blackout | complement, blocked on data | logic only |
| L07 | Multi-timeframe agreement filters | overlap with 7.2c mtf | #2126 admits forward degradation |
| L08 | Volatility-regime gating, GARCH | overlap with ATR band gate | logic only |
| L09 | ATR ratchet trailing stop | alternative to the 1R trail | #4283, #2420 backtest claims |
| L10 | Exit lab (parallel exits scored in R) | overlap with shadows | #4283 XAU H4 per-year R |
| L11 | MAE/MFE-calibrated stops, targets, scale-out | diagnosis / alternative exit | logic only |
| L12 | Staged stop management, loss-only exits | overlap / complement | logic only |
| L13 | Time-based exits | complement | logic only |
| L14 | OU-derived SL/TP (warning against grid search) | methodological | synthetic paths |
| L15 | Donchian/Turtle breakouts incl. XAU H4 above EMA200 | alternative strategy | #4282: PF 1.77, 198 trades, 2020–26, concentrated 2024–25 |
| L16 | Close(1) > High(2) index breakout | alternative/control | backtest referenced, no numbers |
| L17 | Session/opening-range breakouts | alternative strategy | logic; #1771 cites ORB papers |
| L18 | Trend-pullback entries (EMA retest, golden zone, FVG) | overlap with Fib/structure gates | logic only |
| L19 | D1 trend templates (Seykota, Weinstein, Minervini) | none (horizon) | qualitative |
| L20 | MA-crossover variants, score-gated crossovers | overlap; negative evidence from Sentinel's replay | screenshots |
| L21 | Mean-reversion entries | contradiction / flat-regime complement | #2399 small profit vs loss |
| L22 | Liquidity-sweep / SMC structure entries | partial contradiction / alternative | #4270 qualitative |
| L23 | Calendar/time-of-day anomalies (gold reopen, Turnaround Tuesday) | none | #4121: +1.60 bps, t = 3.42, 10/11 years |
| L24 | Short-term OHLC pattern rules (Williams) | overlap with candle gates | logic only |
| L25 | Score-gated multi-condition signals | overlap; **negative** (Sentinel replay) | none |
| L26 | Supertrend + ADX H4 system | alternative | logic only |
| L27 | ML meta-labelling | deferred | #4027 AUC ≈ 0.50 on XAU M15; #4209 accuracy ≠ profit |
| L28 | Portfolio heat / correlation caps | evaluation methodology | logic only |
| L29 | Sizing models (ATR parity, Kelly, drawdown scaling) | risk layer untouched | simulation |
| L30 | Daily caps / equity governance | already in the EA | logic only |
| L31 | Placebo/permutation tests, sequential evaluation | **adopted** | #3229 random entries lose the spread |
| L32 | CSCV/PBO, CPCV, walk-forward efficiency, plateaus | **adopted** | literature |
| L33 | Bootstrap/MC, concentration, Wilson bound, attribution | **adopted** | methodological |
| L34 | Measuring real costs | **adopted**; blocked inputs listed | #4114 20 vs 6 points; #4147 swap 44 % of gross; #4121 reopen 60 vs 19 |
| L35 | Data-quality audits, look-ahead leakage | **adopted** | #4123 23.8 % wrong on 20-pt brackets |

## 4. What the channel does and does not offer

Three years of posts contain very few quantified strategy results and essentially no out-of-sample ones; most "strategies" are CodeBase EAs described by their inputs. The channel's real value for Sentinel is in two places: a handful of carefully stated studies (#3292 session filter, #4121 reopen drift, #4282/#4283 gold breakouts, #4027 null ML result) and a strong, consistent body of validation and cost methodology (L31–L35) that the channel's own authors apply to expose fragile backtests. The library records the first as candidates with rejection criteria and the second as rules the research system adopts.

## 5. Independent verification — the owner's Telegram Desktop export (5 Oct 2026, 13:43)

Joel exported the channel from Telegram Desktop (HTML, `ChatExport_MQL5 Algo Trading/`, 561 MB with media). `messages.html` was parsed and compared with the preview ledger, row by row (`tg_export`, `tg_export_meta` in `research.db`; the export texts are kept as hashes, not copies):

- **Same message ids.** 4,274 ids in both; the same 30 ids (2–25, 111, 386, 450, 895, 976, 3211) are absent from the export too, so they do not exist in the channel (deleted or service events). Id 1 is "Channel created"; 20 service messages (pins, a giveaway) carry no content.
- **Same texts.** 4,252 of 4,254 post bodies are identical once whitespace and reaction counters are ignored (the preview crawler had appended reaction counts to the text; they moved by ±1–2 between crawl and export). The two exceptions are media placeholders (#464, #3087). The channel's own "…" truncations are present in the export as well, so **no text was lost to the preview**; where a post truncates its numbers, the number is not in Telegram at all.
- **What the export adds.** Reaction counts per post (engagement, not evidence); 16 posts flagged as edited; 2 replies (both media placeholders); 0 forwards; the full-size post images.
- **Images reviewed.** The photos attached to the 25 most-cited posts were examined (`tg_media_notes`): 13 are generic cover illustrations; 12 carry data, and that data is now quoted in the library rows it belongs to — the #4282 gold H4 equity curve (flat for ~115 trades, all the gain in the last ~80), the #4121 cost-corrected edge card (+3.34 → +1.60 bps, t 3.42, Sharpe 1.23, 10/11 years), the #4114 spread/swap card (live spread 3.3× the bar field; gold swap −0.58 USD per night per 0.01 lot — about three spreads for a two-night hold), the #4123 OHLC-error curve (nil above 500 points), the #3979 cost-line chart, tester reports for #3453 (PF 1.10, Sharpe 0.73), #4270 (PF 1.10, DD 10.6 %) and #2847 (30 trades, DD 58.6 %). None of it changes a verdict in docs/04; the #4114 swap figure strengthens the cost caveat on Sentinel's XAU 1h/4h longs.

## 6. Limits of this coverage

Linked articles unread (the posts are summaries); comments are not part of a channel export (the channel has no linked discussion group in the export); authors unnamed; several posts truncate their own numbers ("text truncated" in the dispositions) and the export confirms the truncation is the channel's. Anything a future reviewer wants to rely on beyond the post text and images must be fetched and recorded in `sources` with its own fetched_at before it is cited.
