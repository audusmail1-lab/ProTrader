# H18 — "Randomness is why the edge works" (8 Oct 2026)

Joel: the edge on Deriv comes from the randomness itself. Checked on Deriv's own prices.

Deriv hourly candles, 8 Oct 2025 → 8 Oct 2026, entries every 6 h by coin toss, close at +1 typical hourly move, no stop:

| Index | Came back into profit | Median wait | Still open after a year | Their average loss | Deepest dip before a win |
|---|---|---|---|---|---|
| Vol 50 (1s) | 98.9% | 3 h | 16 | −49× the target | 160× |
| Vol 25 (1s) | 98.6% | 3 h | 21 | −42× | 62× |
| Vol 75 (1s) | 99.0% | 3 h | 15 | −28× | 90× |
| Vol 100 (1s) | 98.7% | 3 h | 19 | −31× | 168× |
| Vol 75 | 98.4% | 3 h | 23 | −35× | 69× |
| Vol 50 | 98.5% | 3 h | 22 | −52× | 78× |
| Boom 1000 | 97.6% | 3 h | 35 | −47× | 92× |
| Crash 1000 | 98.2% | 3 h | 26 | −61× | 60× |

The same entries with a stop one target away: −0.01 to −0.14 targets a trade (the spread).

2,000 simulated years of Vol 50 (1s) (the process its ticks match), $10,000 account, two entries a day, target sized to Joel's average win ($72), no stop: the median year banks about 160 winners first; 88% of years end with the account wiped out by positions that did not come back; the average year is −$5,900.

Reading: randomness is why a 98–99% win rate is easy (a random price revisits the entry most of the time). The few that do not come back are 30–170 times a win and arrive together when the index runs one way. The win rate is real; the edge is not.

## Follow-up (Joel: "I wait for it to come back"; "in peak areas the come-back is almost inevitable; how many times can you ride it and say this is enough?")

Peak entries (hour closes at its 24-hour extreme, 2+ typical moves from the mean, fade it) vs coin-toss entries at the same hours, all eight indices, one year: **98.6% vs 98.4% came back**; never came back 211 vs 238, averaging −41× vs −45× a win; same median wait (3 h). Peaks do not change the odds: any entry comes back about 98.5% of the time.

Size (Vol 50 (1s), $10,000, two entries a day, no stop, 500 years each): win per trade $72 → 94% of years wiped out; $36 → 83%; $18 → 62%; $9 → 34%. Every size loses on average.

"When to say enough" is gambler's ruin: with $A at risk in a fair game, the chance of making +$X before losing the $A is A/(A+X) at best (Deriv's spread makes it a little worse). $10,000 at risk: +$1,000 → 91%, +$5,000 → 67%, +$10,000 → 50%, +$16,000 → 38%. Withdrawing profits is what turns a lucky run into money kept.
