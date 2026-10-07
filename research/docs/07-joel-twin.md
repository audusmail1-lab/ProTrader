# Joel Twin (7 Oct 2026)

Joel asked for "a better and advanced me". The record (docs: v3 ledger analysis, 7 Oct) shows two things a machine can do better than a person — apply the same rule every time, and record the truth at the fill — and one thing it cannot yet do: find an entry edge on the Volatility indices. The twin is built on the first two.

## What it does

For every MT5 position the server tracks on the owner's bridge account (`managed` journal), after Joel closes it, `joel_twin.py` replays the same entry, side and size under fixed rules and records what the twin would have made. It never places an order.

| Rule | Source |
|---|---|
| Stop: Joel's first stop if it risks ≤ 1% of the account; otherwise (none within a minute, wider than 1%, or first seen after the fill) a stop at 1% | ARIA's per-trade limit and Iron Stop Law; v3 shows 79 of 261 trades closed with no stop |
| At +$100 per $36,900 of equity: breakeven, then trail that distance behind the best price | Joel's own stated rule (the `usd100` shadow), scaled to the account |
| No target; exit on the stop or after 5 days | — |
| Replay on Deriv's public candles: 1-minute up to 6 days old, 15-minute after; first full bar after the fill; stop before favourable move; a stop raised from a bar's high that the bar then closes through exits at the stop; a bar opening through the stop exits at its open; half the estimated spread off the twin's exit | Same conventions as every Sentinel book |

Rules are frozen as `TWIN_VERSION` (hash of `TWIN_RULES`); a change is a new version and results never mix.

The tracker now records, at the fill, the account equity (`eq_open`) and the money per 1.0 of price at full size (`per_unit`). Older records fall back to the close (when nothing was closed early) and to the recorded risk % or the latest equity.

Owner endpoints: `GET /api/sentinel/managed` (each record carries `twin`, stats carry `twin`) and `GET /api/sentinel/twin` (rules, every replayed position, paired totals). The Sentinel tab's "Your trade management" shows the twin per trade and a summary: you vs twin in dollars, the per-trade difference with its 95% interval, who was better how often, worst trade each, and the subtotal where the twin added or capped a stop.

## Measured: the replay is exact

Set to Sentinel's own stop and the usd100 rule, the twin replay reproduces Sentinel's live `usd100` shadow on all **190** public closed paper trades with a closed shadow (7 Oct): every trade within 0.0005 R (rounding), total +27.185 R vs +27.188 R. (Two replay bugs were found and fixed by this check: the first bar after a fill on a bar boundary, and a stop raised and crossed inside the same bar.)

## Limits

- Only positions on the bridged MT5 account are seen. Joel's real account (140371751) is replayed only if its terminal runs the bridge EA as the owner channel; Sentinel Live's demo test uses that channel today, and its EA refuses entries on a real account by design.
- Instruments without a public Deriv feed (e.g. HF Volatility 50, 65 of Joel's 261 v3 trades) are listed as "not replayed".
- Candle replay is not tick replay: inside a bar the order of high and low is unknown (stop first is the conservative choice); MT5 prices for real-market CFDs can differ slightly from the public feed.
- On the Volatility indices no exit rule changes the expected result (docs: v3 analysis §3). What the twin can change there is the size of the losses, which is what the "added or capped" subtotal shows.
