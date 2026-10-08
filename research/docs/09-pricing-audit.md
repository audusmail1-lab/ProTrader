# 09 — Deriv pricing audit and the risk-premium lead (7 Oct 2026)

Question: instead of predicting prices, can we find contracts that Deriv pays more for than they are worth?

## 1. Synthetic indices: every product carries a fixed house margin (closed)

Deriv publishes each synthetic index's volatility. 12,000 ticks per index confirm a clean random walk (σ within 1% of stated, normal tails, no autocorrelation, uniform last digits), so the true odds of every contract can be computed exactly. Read-only quotes only; nothing was bought.

| Product | Quotes | Buyer's expected value per $1 |
|---|---|---|
| Options, 20 types (Rise/Fall, digits, touch, range, high/low tick, only-ups, Asians) on V50/V100 (1s), V50, V100 | 312 | −0.4% (wide Up-or-Down) to −51%; Rise/Fall about −2.3%, Digit Match −10.7% |
| Step Index Rise/Fall, exact coin-flip odds incl. ties | 28 | −1.6% to −4.6% |
| Bull/Bear Market (built-in drift of about +9%/−5.5% a day, t = 18) | 36 | −1.5% to −3.2%: the drift is priced in exactly |
| Accumulators, 10 Volatility indices × 5 growth rates | 50 | −0.35% to −0.62% **per tick**, identical on every index (barrier set to a fixed margin) |
| Accumulators on Boom/Crash | 70 | Deriv's own record shows the same margin; its knock-outs don't follow the public tick feed, so the feed can't be used to beat them |
| Multipliers + deal cancellation (fee vs fair value of the protection) | ~200 | −0.2% to −7% of stake |

Every price is exact odds minus a margin. On a game where the house sets both the odds and the payouts, any mix or sequence of these bets has negative expectancy (optional stopping). **Synthetic indices are closed as a source of edge.** Useful by-product: we can show users the true cost of any synthetic contract before they buy (a "house edge meter").

## 2. Forex binaries (quoted 22:00 GMT, 9 pairs, 396 quotes)

Large margins: 1-day contracts −11% to −58%, 7-day −7% to −38%, 30-day calm-side contracts about break-even after the margin. One year of history is too short to call the 30-day ones either way. Not an edge at these prices; re-quote during London hours before closing it.

## 3. The lead (7 Oct): were real-index "Rise" contracts priced risk-neutrally?

Gold quotes show how Deriv prices long contracts: Rise and Fall prices sum to 1.05–1.10 (2.5–5% margin per side) around a risk-neutral centre. If the Nasdaq-100 is priced the same way, buying "Rise" collects the equity risk premium plus the volatility premium: the market goes up over a quarter far more often than the risk-neutral price assumes.

25-year test (Nasdaq-100 2001–2026, priced at VXN implied volatility, risk-neutral drift, plus a margin):

| Contract | Fair price p | Won | EV at 6% margin | 2001–2012 (flat decade) | 2013–2026 |
|---|---|---|---|---|---|
| Rise 30d | 0.491 | 0.631 | +21% ±10% | +11% | +30% |
| Rise 91d | 0.484 | 0.698 | +36% ±11% | +19% | +51% |
| Rise 365d | 0.468 | 0.819 | +65% | +56% | +75% |
| Ends between ±1σ, 30d | 0.682 | 0.774 | +7% ±7% | +8% | +7% |

Weekly ladder (stake a fixed share of equity every Monday, 2001–2026): Rise 91d at 1% stake and a 10% margin gave +13%/yr with a worst drawdown of 35%; at 0.5% stake +7%/yr, drawdown 19%. Losses cluster in bear years (2001–02, 2008, 2022).

What it is: the equity risk premium, the most documented premium in finance, bought through defined-risk contracts. What it isn't: a prediction system or a guaranteed income.

## 4. The deciding check (8 Oct 2026, live index quotes): the strong claim fails, a narrow one survives

Deriv does not price index "Rise" contracts risk-neutrally. It builds in an upward drift: about 62% odds for US Tech 100 at every length (pays about 1.61×), and 67–70% for US 500. Rise and Fall prices sum to 1.00–1.04.

US Tech 100 Rise at Deriv's real price against Nasdaq-100 history:

| Length | Deriv odds | Rose 2001–2026 | EV | Flat decade 2001–12 | Bull decade 2013–26 |
|---|---|---|---|---|---|
| 32 days | 0.614 | 0.633 | +3% | −6% | +11% |
| 91 days | 0.620 | 0.698 | +13% | −2% | +25% |
| 182 days | 0.630 | 0.748 | +19% | +4% | +32% |
| 365 days | 0.617 | 0.819 | +33% | +23% | +42% |

"Ends between" ranges (the volatility premium) are all priced above their historical win rate: −0.3% to −21%. Closed.

What survives: 6- and 12-month Rise beat Deriv's price on 25 years of history, the 12-month one in both decades. It rests on few independent years (one 12-month outcome a year) and is a bet that the index rises over a year: the same bet as holding the index, with the loss capped at the stake. Not proven; plausible.

The contract book was re-specified to US Tech 100 and US 500 Rise, 6 and 12 months (30- and 91-day dropped). Weekend or holiday expiries move to the next trading day, as Deriv requires. Probed live on 8 Oct: quotes, entry ticks, expiries Thu 8 Apr and Fri 8 Oct 2027; only `proposal` and `ticks_history` were called. A verdict on outcomes needs 20 settled contracts of a kind, about 1.5 years for the 12-month one; until then the book's job is to show whether Deriv's price stays where it is.

Scripts and raw results: `research/experiments/H16-pricing/`. Long histories from FRED (NASDAQ100, VXNCLS, VIXCLS, DTB3).
