# H17 — slow trend following across real markets (pre-registered 8 Oct 2026, before any run)

Question: the one strategy class with a century of out-of-sample evidence (time-series momentum, Hurst-Ooi-Pedersen) —
does it hold on the real markets Deriv offers, at retail CFD costs, over decades?

Data: FRED daily closes. NASDAQ-100 (1986-), Nikkei 225, WTI oil (1986-), BTC (2014-), ETH (2016-),
EUR/USD (1999-), USD/JPY, GBP/USD, AUD/USD, USD/CAD, USD/CHF, NZD/USD, USD/MXN (1971-/1993-). Test from 1986.
Rule (fixed): each Friday, each market: direction = sign of its trailing 12-month return; size so the market's
expected volatility is 10%/N of the account (EWMA vol, 60-day centre of mass); hold to next Friday.
Costs: spread on every change in position (FX 0.02%, indices 0.03%, oil 0.05%, crypto 0.15% of notional) and a
financing markup of 2.5% a year on every open notional, long or short. No carry credited.
Variants (robustness only, not chosen): 3-month, 6-month, and the average of 3/6/12-month signs.

Pass (all required):
1. 1986-2026 net Sharpe >= 0.4 for the 12-month rule.
2. Net Sharpe > 0 in each of 1986-1999, 2000-2012, 2013-2026.
3. Every variant net Sharpe > 0.2 over the full period.
4. Worst drawdown < 35% at the 10% volatility target.
5. Positive in >= 75% of rolling 3-year windows.
Otherwise: rejected; Sentinel does not get a trend engine.
