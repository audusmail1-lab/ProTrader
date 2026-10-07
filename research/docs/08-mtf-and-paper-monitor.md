# Multi-timeframe agreement (H14) and the paper-account monitor (7 Oct 2026)

Joel asked for two things: Sentinel should use ARIA's multi-timeframe agreement to tell him when to wait for the best trades, and Sentinel should watch his paper trading on the phone (same style; balance $40,124 from $10,000).

## H14 — ARIA multi-timeframe agreement: rejected

Pre-registered before any run (criteria below), one year of Deriv history, the lab's windows, ARIA 7.2c as it runs (which already requires the 4h trend to agree). Script and raw output: `research/experiments/H14-mtf.py`, `H14-mtf.result.json`.

| Real markets (NAS100, XAU, BTC) | agrees on | development | validation | holdout | placebo p (net) dev / val / holdout |
|---|---|---|---|---|---|
| 15m trades, 1h ARIA read agrees (EXEC/QUALIFIED) | 18% | +0.228 vs base +0.070 | +0.035 vs +0.062 | −0.002 vs +0.040 | 0.10 / 0.57 / 0.60 |
| 15m trades, 1h read same direction, score ≥ 7 | 58% | +0.148 vs +0.070 | +0.013 vs +0.062 | +0.033 vs +0.040 | 0.05 / 0.79 / 0.55 |
| 1h trades, 4h ARIA read agrees | 12% | +0.144 vs +0.033 | **−0.551** vs +0.065 | **−0.250** vs +0.113 | 0.33 / 0.99 / 0.87 |
| 15m trades, 1h agrees and 4h same direction | 9% | **+0.496** vs +0.070 | −0.026 vs +0.062 | −0.072 vs +0.040 | **0.013** / 0.66 / 0.70 |

Every version is strong in the development window and loses it afterwards; in validation and holdout the trades the filter *rejects* do better than the ones it keeps. The development window is the period ARIA 7.2c's own filters were tuned on, so its +0.2 to +0.5 R is the familiar in-sample effect. Synthetic control (Vol 75, Vol 75 (1s)): null in every window, as expected. Without gold the accepted trades average about zero.

Pass criteria (written before the run): accepted trades positive on validation and holdout at ×1 and ≥ 0 at ×1.5; placebo p < 0.05 on development and validation; ≥ 50 accepted per window; not carried by one market. None met them. It is also not shown as "best trade" information, because in the later windows it points to worse trades, not better ones. Sentinel keeps the one multi-timeframe rule that earned its place: the 4h trend (removing it was worse in all three windows, docs/04).

## Paper-account monitor (built; preview)

The phone's paper account is saved on the server as the signed-in instructor's workspace document `trade` (balance, last 500 fills, open positions). `paper_monitor.py` reads it — owner only, read-only, never another person's account — after every scanner cycle, groups fills into positions and keeps them in sentinel.db (so the history outlives the 500-fill cap).

`GET /api/sentinel/paper` (owner) and the "Your paper account" card in the Sentinel tab show: balance and profit since the start; win share, average win and loss, worst trade, deepest dip, share of profit in the biggest five trades; **per-trade R from the risk at the first stop** (paper keeps a stop on every trade, so this R is real) with its 95% interval and a plain verdict (too few / not distinguishable from zero / positive or negative beyond chance), plus a caution when most trades are on synthetic indices; breakdowns by market, by how the trade ended, and by setup tag (tags given while open in the trade journal); and Joel Twin on every closed paper position (`paperacct:` records: same entry and size, his stop capped at 1%, breakeven then trail at +$100 per $36.9k).

Limits: paper fills use Deriv's public bid/ask (the spread is paid; slippage, swap and commission are not); the balance-before-each-trade used by the twin is rebuilt backwards from today's balance; positions closed before the server first read the account are known only as far as the saved 500 fills reach.

## Follow-up: is the sign flip itself an edge? (Joel's question, 7 Oct)

The pattern — agreement looks strong in development, then the trades it rejects do better — was tested directly (`H14-signflip.py`, `H14-extension.py`): accepted minus rejected, pooled over validation + holdout, two-sided permutation tests, month by month, and the same on the synthetic control, where the true effect is zero by construction.

| accepted − rejected, R per trade | real: development | real: out of sample | control (random walk): development | control: out of sample |
|---|---|---|---|---|
| 15m, 1h agrees (strong) | +0.196 (p 0.18) | −0.044 [−0.27, +0.19] (p 0.74) | −0.134 | −0.023 (p 0.84) |
| 15m, 1h same direction (loose) | +0.187 (p 0.10) | −0.058 [−0.25, +0.14] (p 0.56) | +0.133 | −0.068 (p 0.47) |
| 1h, 4h agrees | +0.124 (p 0.70) | −0.539 [−0.95, −0.13] (p 0.088, n 41 accepted) | +0.275 | −0.256 (p 0.24) |
| 15m, all three | +0.466 (p 0.022) | −0.113 [−0.37, +0.16] (p 0.51) | −0.151 | −0.057 (p 0.68) |

- The random-walk control produces the same shape at the same size (e.g. +0.275 → −0.256), so the shape is not evidence. It is regression to the mean: the best-looking of several filters is chosen on the period that flatters it; out of sample its effect returns to the truth (here ≈ 0) and lands below zero about half the time.
- The only notable gap (1h trades with 4h agreement, p 0.088) rests on 41 trades; across the four filters tested the adjusted p is about 0.35. Month by month the sign alternates for three of the four filters. Inverting the filter is not a rule: it would have lost in development, and nothing predicts which period is which.
- Mechanism check: agreement is not a proxy for entering late (extension beyond the 1h EMA50: 2.48 vs 2.41 ATR). Extension itself kept its sign pooled on real markets (lowest third worst in both periods; slope +0.075 R/ATR dev, +0.043 out of sample, p 0.06 / 0.17) and vanished on the control (dev p 0.002 → out of sample p 0.88), but split by market and timeframe it holds in only 3 of 6 slices out of sample. A weak lead at most; it would need a pre-registered test on fresh data.
