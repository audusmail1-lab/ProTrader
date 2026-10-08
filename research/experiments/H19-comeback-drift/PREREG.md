# H19 — Joel's come-back, applied where a real drift pulls price back (pre-registered 8 Oct 2026, before any run)

Joel's method: enter, never cut the loser, wait for it to come back, take a small profit. On Deriv's synthetic indices it wins
98-99% of trades and loses on average (H18): nothing pulls price back. Equity indices have a century-long upward drift.
Question: does the same method have a positive average on the Nasdaq-100 (Deriv: US Tech 100), long only, after retail CFD costs?

Data: FRED NASDAQ100 daily close 1986-2026; DTB3 for the financing benchmark.
Rules (fixed): buy when the close is at least 2 daily volatilities (EWMA, 60-day) below its 20-day high; at most one new
position a day and at most 10 open; each position's notional is 10% of the starting account (so at most 1x the account);
close when the close is 1 daily volatility (at entry) above the entry price. No stop. Long only.
Costs: 0.03% spread per trade; financing (3-month T-bill + 2.5%) a year on open notional, charged daily.
Control: the same rules on a driftless random walk with the Nasdaq's volatility (the synthetic-index case).

Pass (all required): average result per trade > 0 after costs over 1986-2026; positive in each of 1986-1999, 2000-2012,
2013-2026 (positions marked to market at each period's end); the control is not positive; the worst equity drawdown
at 1x is reported, not hidden.
