# 10 — Everything we know, in one place (8 Oct 2026)

Joel asked for all of it recollected and used to better the bot. Numbers first; each line points to where it was measured.

## 1. Joel

| | |
|---|---|
| MT5 record, 1 May – 3 Oct 2026 (v3 ledger) | 261 trades, **+$16,022** net; 234 winners / 27 losers; all losses together −$763; worst trade −$253; 6 losing days of 76; $15,300 withdrawn (docs: v3 ledger analysis) |
| Where it was made | 235 trades on synthetic indices (+$14,431); 26 on BTC, NAS100, gold (+$1,591) |
| Discipline | with a stop: 182 trades, 94.5% won; no stop: 79 trades, 78.5% won, worst −$159. Memory notes a long-standing habit of sizing above ARIA's limits on conviction |
| Paper account (phone) | $40,124 from $10,000; now monitored by Sentinel after the phone-account switch (docs: phone paper account) |
| Open questions | MT5 Equity vs Balance (any losing positions still open?); no trades in July in the export |
| Setups | TCL, SMOG, G2: none of the 261 trades is tagged, so no setup has been measured yet. One-tap tags are live |

What a machine can copy from this: small losses, a stop on every trade, profits locked by trailing, money taken out. What it cannot copy yet: an entry edge, because none has been measured.

## 2. The markets

- **Synthetic indices are random by design.** Deriv generates them with a secure random number generator at a fixed volatility. Tested here: per-tick volatility within 1% of the stated figure, normal tails, no autocorrelation, variance ratio 1.0 from 2 hours to a week, uniform last digits. On a random walk no entry rule and no exit rule has a positive average before costs.
- **Deriv also prices every synthetic contract at exact odds minus a margin** (about 700 quotes across options, accumulators, multipliers with cancellation, Bull/Bear drift indices): 0.35–0.6% per tick on accumulators, 2–4% on Rise/Fall, up to 51% on far touches (docs/09).
- **Real markets** (NAS100, gold, BTC, FX) carry structure that can in principle be traded, but at retail spreads and swaps the margins are thin.

## 3. The bot (Sentinel, ARIA 7.1 gates + 7.2c filters and exit)

| Forward paper journal since 27 Sep (public endpoints, 8 Oct) | n | R per trade | total |
|---|---|---|---|
| All | 247 | **−0.168** (95% −0.31 to −0.02) | −41.5 R |
| Synthetic indices | 165 | −0.17 | −28.5 R |
| Real markets | 82 | −0.16 | −12.9 R |
| **Grade A/A+ (exactly what Sentinel Live trades on the demo)** | 40 | **−0.24** | −9.6 R |

- The A grade is the four "candidate slices" (NAS100 15m, XAU 15m and 1h, BTC 1h) that the one-year replay put at **+0.16 R**. Forward they are the worst real-market subset; the other real trades are about −0.02 R. Selection made on past data did not carry forward.
- Trades reach +1.14 R on average and give it back to −0.09 R; 35% never reach +0.5 R.
- The research loop's 150-trade review called the incumbent **underperforming**.

## 4. Exits: Joel's $100 rule (new check, 8 Oct)

The forward shadow says the $100 rule beats the model exit by +0.17 R a trade (n 239). Re-run on **1-minute bars** for the same 180 trades:

| | 15m/1h bars (journal) | 1-minute bars |
|---|---|---|
| Synthetic (n 133) | +0.20 ±0.16 | +0.17 ±0.16 |
| Real markets (n 47) | +0.11 ±0.31 | **−0.05 ±0.38** |

On synthetics the advantage cannot be real (random walk), and the one-year 1-minute study on 6,890 trades found −0.016 R (−0.042 to +0.011). On real markets, the only place an exit rule could matter, it vanishes at minute resolution. **Do not switch the main exit to the $100 rule.** The hybrid and structure shadows are negative forward.

## 5. Ideas tested and rejected (each with numbers in its doc)

Session window (H1), ADX regime (H3), exit challengers (H4), autocorrelation (H5), Donchian breakout (H6), gate ablation (H7), fade-the-15-minutes "Joel Scalper" (H13), multi-timeframe agreement (H14) and its sign flip, the volatility premium on ranges, short index Rise contracts, and now **H17 slow trend following** across 13 real markets over 40 years: Sharpe 0.56 before costs, **−0.03 after** a 2.5%/yr retail financing markup and spreads; negative in 2000–2012 and 2013–2026. Retail financing removes the one edge with a century of evidence.

What helped, as cost rules only: skipping entries when the spread is over 5% of the stop (H2); the 4h trend filter and the trailing exit beat worse versions of themselves.

## 6. Running now

Incumbent paper journal (monitoring) · 7.3 candidate: real markets, cost cap (paper, 3 trades) · Sentinel Live on the MT5 demo (A/A+ on NAS100, XAU, BTC) · Joel Twin (replays, never trades) · paper-account monitor · contract book (6- and 12-month index Rise at Deriv's price) · weekly edge search.

## 7. What "better" can honestly mean now

No entry edge has survived forward or out-of-sample testing on these markets at these costs. The improvements that are real are the ones that stop measured losses and protect the trader:

1. Stop opening paper trades on synthetic indices (watch-only): removes about two-thirds of the forward losses for a structural reason, not a fitted one.
2. **Evidence brake on Sentinel Live (built 8 Oct, Joel's choice):** the demo bot stands down while the forward paper record of what it trades is negative beyond chance — the model's paper trades on its markets (NAS100, gold, BTC) or the A/A+ trades it takes, 30+ closed trades with the whole 95% range below zero — journals every skipped signal, tells Joel once, and resumes by itself. On 8 Oct it is armed but not triggered: model on those markets −0.16 R over 82 (95% −0.44 to +0.12), A/A+ −0.24 R over 40 (−0.66 to +0.21). Synthetic losses do not count against a bot that does not trade them. If the real-market record stays near −0.16 R, it crosses the line after roughly 250 trades.
3. Keep the model exit; record the $100-rule result above.
4. Joel's own trades: the twin's rules as a live guard on MT5 (a stop on every position, capped at 1%; breakeven and trail at +$100 per $36.9k), only with his explicit approval, because it moves real stops.
5. The route to a bot that trades like Joel stays: tag setups, let the monitor measure each, code the one that proves itself.
6. **Drift (built 8 Oct, Joel's choice, preview):** own US Tech 100 and US 500 while each closes above its 200-day line. Joel's 1x version runs as a paper book (Nasdaq-100 1987–2026: +6.8%/yr after CFD financing, worst −65%, −4.8%/yr in 2000–2012). The demo bot trades the version the risk rules allow: ½% risk per index at a stop 3% under the line, raised daily (2017–2026: +2.1%/yr, worst −6%; about a fifth of the account invested). The 1% rule caps exposure at risk ÷ stop distance, so the 1x version needs its own risk class — Joel's call (H20).
