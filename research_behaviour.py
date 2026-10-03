"""
Behaviour leaks in Joel's own ledger (Joeltrades_Ledger, Trades sheet, 13 Aug - 27 Sep 2026).
   python3 research_behaviour.py

Question (AI coach research, 3 Oct 2026): before designing any coach, does the
trader's own record show the behaviours the literature says cost money -
size creep after wins, trades soon after a loss, early exits from fear,
losers held past the stop, rule breaks - and can the ledger even answer?

Exit reasons are tagged from Joel's own notes (the tag table below is the
judgement call; every other number is arithmetic on the sheet).
"""
from collections import Counter, defaultdict
from datetime import date

# Date, instrument, side, setup, tf, result R (position, weighted), lot, note, exit tag
# tags: plan = exit as planned / target hit; early = left profit from fear, stress or judgement;
#       lapse = management lapse (missed profit taking, closed half then gave the rest back);
#       cut = loser cut before the stop; none = no note
ROWS = [
    ("2026-08-13", "Volatility 75 (1s)", "Short", "TCL", "1h", 0.02, None, "breakeven, trade later contd got out due to stress from holding too long.", "early"),
    ("2026-08-14", "XAUUSD", "Long", "G2", "5m", 7.00, None, "Plan followed on trading app all tps hit", "plan"),
    ("2026-08-14", "HF Volatility 50", "Short", "SMOG", "1m", 0.50, None, "Tp hit (test).", "plan"),
    ("2026-08-17", "HF Volatility 50", "Short", "SMOG", "1w", 0.80, None, "clean trade missed profit taking", "lapse"),
    ("2026-08-18", "HF Volatility 50", "Long", "TCL", "1h", 0.40, None, "tp hit exceeded the tp", "plan"),
    ("2026-08-18", "HF Volatility 50", "Short", "SMOG", "15m", 0.50, None, "Sold into the rejection, i minute rising wedge helped us position right", "plan"),
    ("2026-08-19", "HF Volatility 50", "Long", "TCL", "15m", -0.16, None, "Zoom out, caught falling knife disguised as wedge taken from MT5 which is wrong", "cut"),
    ("2026-08-30", "HF Volatility 50", "Short", "SMOG", "1w", 4.40, None, "Held smoothly", "plan"),
    ("2026-08-31", "Volatility 50", "Long", "TCL", "1w", 4.60, 0.05, "followed plan to hold trade", "plan"),
    ("2026-09-01", "HF Volatility 50", "Long", "TCL", "1w", 0.80, 0.05, "Was to hold the trade longer closed cause i feared a retracement that didnt happen", "early"),
    ("2026-09-03", "Volatility 50 (1s)", "Long", "SMOG", "1w", 3.70, 0.05, "Closed because that was my Target area for one position letting the other run. at 2:38am", "plan"),
    ("2026-09-03", "Volatility 50 (1s)", "Long", "SMOG", "1w", 6.21, 0.03, "Took partial profit from the position i left running still running in 200+ profit after that", "plan"),
    ("2026-09-04", "Volatility 50", "Long", "SMOG", "1w", 0.80, 25, "Closed half a position, market continued buying", "lapse"),
    ("2026-09-07", "HF Volatility 50", "Short", "TCL", "1w", 7.10, 0.05, "Booked full position price retraced from 835, market could continue to tp $1000 target, but i made a judgement", "early"),
    ("2026-09-14", "Volatility 50 (1s)", "Long", "SMOG", "1w", 2.16, None, "Finally closed full position.", "plan"),
    ("2026-09-15", "Volatility 25 (1s)", "Short", "TCL", "1w", 1.65, 0.05, "Closed right", "plan"),
    ("2026-09-19", "Boom 1000", "Long", "G2", "1w", 3.22, 0.2, "Closed Cause i was making sure i preserved capital.", "early"),
    ("2026-09-20", "Volatility 25 (1s)", "Short", "SMOG", "1w", 1.21, 0.05, "Closed half first then full position as market went back to entry (50% at +2.42R, rest at entry)", "lapse"),
    ("2026-09-27", "Volatility 25 (1s)", "Short", "", "1w", 0.12, None, "", "none"),
]
SENTINEL_FORWARD = {"n": 109, "win_rate": 0.4587, "expectancy_r": -0.1977, "A_n": 14, "A_expectancy_r": -0.349,
                    "risk_free_pct": 0.4587, "avg_mfe_r": 1.084, "capture_pct": 0.403}   # /api/sentinel/stats, 3 Oct 2026


def main():
    n = len(ROWS); rs = [r[5] for r in ROWS]
    print(f"Ledger: {n} positions, {min(r[0] for r in ROWS)} to {max(r[0] for r in ROWS)}, net {sum(rs):+.2f}R, "
          f"wins {sum(1 for r in rs if r > 0.1)}, losses {sum(1 for r in rs if r < -0.1)}, breakeven {sum(1 for r in rs if -0.1 <= r <= 0.1)}")

    # 1. Exit discipline, from the notes
    tags = Counter(r[8] for r in ROWS)
    print("\n1. Exit discipline (tagged from Joel's notes)")
    for t, label in [("plan", "as planned / target"), ("early", "left profit from fear, stress or judgement"), ("lapse", "management lapse (missed exit, gave back)"), ("cut", "loser cut before the stop"), ("none", "no note")]:
        rows = [r for r in ROWS if r[8] == t]
        print(f"   {label:46s} {len(rows):2d}  ({len(rows)/n:4.0%})  R: {', '.join(f'{r[5]:+.2f}' for r in rows)}")
    off = [r for r in ROWS if r[8] in ("early", "lapse")]
    print(f"   -> {len(off)} of {n} exits ({len(off)/n:.0%}) deviated from the plan, ALL in winners; the only loser was cut early, none held past a stop.")
    print(f"   -> R realised on those {len(off)} deviations: {sum(r[5] for r in off):+.2f}R. The notes say more was available on at least 5 of them; the sheet's 'Planned Target R' and 'R Left on Table' columns are empty on every row, so the cost cannot be measured.")

    # 2. Trades after a loss
    print("\n2. After the one loss (19 Aug, -0.16R): next trade 30 Aug, 11 days later. No same-day re-entry. One event; no pattern can be claimed.")

    # 3. Size after wins
    lots = [(r[0], r[1], r[6]) for r in ROWS if r[6] is not None]
    print(f"\n3. Size after wins: lot size filled on {len(lots)} of {n} rows, across 5 instruments with different lot scales "
          f"(0.03-0.05 on Vol 50 (1s)/HF Vol 50/Vol 25 (1s), 0.2 on Boom 1000, 25 on Volatility 50). 'Risk %' is typed as 1.00% on every row and 'Actual Risk $' is blank on every row.")
    print("   -> size creep cannot be measured from this ledger: risk per trade is asserted, not recorded.")

    # 4. Timeframe and session
    by_tf = defaultdict(list)
    for r in ROWS: by_tf[r[4]].append(r[5])
    print("\n4. Where the R came from")
    for tf, v in sorted(by_tf.items(), key=lambda kv: -sum(kv[1])):
        print(f"   {tf:4s} n={len(v):2d}  net {sum(v):+6.2f}R  avg {sum(v)/len(v):+.2f}R")
    wk = [r for r in ROWS if date.fromisoformat(r[0]).weekday() >= 5]
    print(f"   weekend positions (synthetics): {len(wk)} of {n}: {', '.join(r[0][5:] for r in wk)}; one exit logged at 2:38am (3 Sep).")

    # 5. What the record cannot show
    print("\n5. Logging gaps a coach would hit first")
    print(f"   - 1 loss in {n} positions (win rate {sum(1 for r in rs if r > 0.1)/(n-1):.0%} ex-breakeven) against Sentinel's forward record of {SENTINEL_FORWARD['win_rate']:.0%} wins and {SENTINEL_FORWARD['expectancy_r']:+.2f}R per trade "
          f"on {SENTINEL_FORWARD['n']} trades (A setups {SENTINEL_FORWARD['A_expectancy_r']:+.2f}R, n={SENTINEL_FORWARD['A_n']}). Either Joel's discretionary exits are far better than the system's, or losers are not being logged. Only the broker statement settles it.")
    print("   - Position ID stopped after 15 Sep; Setup blank on 27 Sep; Via Nexus blank on all rows; no entry/exit times, no stop price, no peak price -> no risk-free moment, no capture %, no stop moves.")
    print("   - R is self-reported per row; P&L $ is derived from a typed $10,000 equity and 1%, not from the account.")

    # 6. What the server journals would add (not reachable without Joel's signed-in session)
    print("\n6. Not yet read: the trade-management journal and Sentinel Live journal on the server (owner only). They hold what the ledger lacks: every stop move with its time, the risk-free moment, locked R, peak R, exit reason, and the trader-vs-system comparison for setups opened from Sentinel.")
    print(f"   System baseline from /api/sentinel/stats: {SENTINEL_FORWARD['risk_free_pct']:.0%} of paper trades reached risk-free, avg peak {SENTINEL_FORWARD['avg_mfe_r']:.2f}R, {SENTINEL_FORWARD['capture_pct']:.0%} of the winning move kept.")


if __name__ == "__main__":
    main()
