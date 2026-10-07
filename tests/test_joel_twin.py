"""Joel Twin: Joel's own management rules replayed on his closed MT5 positions.

    python3 -m pytest -q tests/test_joel_twin.py
"""
import asyncio
import os
import sys
import tempfile
import time

os.environ["SENTINEL_ENABLED"] = "0"
os.environ.setdefault("SENTINEL_DB", os.path.join(tempfile.mkdtemp(), "twin.db"))
os.environ["SENTINEL_ADMIN_KEY"] = "k"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import sentinel as s            # noqa: E402
import joel_twin as jt          # noqa: E402


def bar(t, o, h, l, c):
    return {"time": t, "open": o, "high": h, "low": l, "close": c}


RULES0 = dict(jt.TWIN_RULES, half_spread=False)


def rec(**kw):
    r = {"key": "mt5:1", "symbol": "Volatility 50 (1s) Index", "side": "buy", "entry": 100.0, "opened": 600_000,
         "initial_sl": 99.0, "r_dist": 1.0, "per_unit": 10.0, "eq_open": 1000.0, "events": [], "closed": 1, "pnl": 5.0}
    r.update(kw)
    return r


def test_mt5_names_map_to_the_public_feed():
    f = lambda n: (jt.feed_market(n).id if jt.feed_market(n) else None)
    assert f("Volatility 50 (1s) Index") == "1HZ50V" and f("Volatility 75 Index") == "R_75"
    assert f("Boom 1000 Index") == "BOOM1000" and f("Crash 300 Index") == "CRASH300N" and f("Jump 25 Index") == "JD25"
    assert f("XAUUSD") == "frxXAUUSD" and f("BTCUSD") == "cryBTCUSD" and f("US Tech 100") == "frxNAS100"
    assert f("EURUSD.m") == "frxEURUSD" and f("Step Index") == "stpRNG"
    assert f("HF Volatility 50 Index") is None and f("") is None


def test_stop_sources_and_the_lock_distance():
    # $10 per point, $1,000 equity: 1% = $10 = 1.0 point; $100 per $36.9k = $2.71 = 0.271 point
    p = jt.plan(rec(), rules=RULES0)
    assert p["stop_source"] == "yours" and p["stop0"] == 99.0 and p["risk_money"] == 10.0
    assert abs(p["lock_px"] - 100 / 36900 * 1000 / 10) < 1e-12 and p["lock_money"] == 2.71
    p = jt.plan(rec(initial_sl=97.0, r_dist=3.0), rules=RULES0)                 # 3% → capped to 1%
    assert p["stop_source"] == "capped" and abs(p["stop0"] - 99.0) < 1e-12
    p = jt.plan(rec(initial_sl=None, r_dist=None), rules=RULES0)                # no stop → added at 1%
    assert p["stop_source"] == "added" and abs(p["stop0"] - 99.0) < 1e-12
    p = jt.plan(rec(late=True), rules=RULES0)                                    # tracked after the fill
    assert p["stop_source"] == "unknown"
    p = jt.plan(rec(side="sell", initial_sl=None, r_dist=None), rules=RULES0)
    assert abs(p["stop0"] - 101.0) < 1e-12
    assert "skip" in jt.plan(rec(symbol="HF Volatility 50 Index"))


def test_money_per_point_and_equity_fallbacks():
    r = rec(per_unit=None, exit_price=102.0, pnl=20.0, eq_open=None, risk_pct=1.0)
    p = jt.plan(r, rules=RULES0)
    assert p["per_unit"] == 10.0 and p["equity"] == 1000.0 and p["equity_source"] == "from the recorded risk %"
    r2 = rec(per_unit=None, exit_price=102.0, pnl=20.0, events=[{"type": "partial"}])
    assert "skip" in jt.plan(r2)                                                 # partly closed: per-point unknown
    r3 = rec(eq_open=None, risk_pct=None)
    assert jt.plan(r3, equity_fallback=2000.0, rules=RULES0)["equity_source"] == "latest account equity"


def test_breakeven_then_trail_exits_at_the_trailed_stop():
    p = jt.plan(rec(opened=600_000), rules=RULES0)            # fill at t=600 s; 1-minute bars from 600
    lock = p["lock_px"]                                       # 0.271
    bars = [bar(540, 100, 100.5, 99.5, 100),                 # before the fill: ignored
            bar(600, 100, 100.2, 99.8, 100.1),               # +0.2 < lock: nothing
            bar(660, 100.1, 100.9, 100.0, 100.8),            # best 100.9 → stop 100.9 - 0.271 = 100.629
            bar(720, 100.8, 101.0, 100.7, 100.75),           # best 101.0 → stop 100.729; close 100.75 above it
            bar(780, 100.75, 100.8, 100.5, 100.6)]           # low 100.5 ≤ 100.729 → exit at the stop
    sim = jt.simulate(p, bars, 60, 10_000, rules=RULES0)
    assert sim["state"] == "closed" and sim["how"] == "stop" and sim["closed_at"] == 840
    assert abs(sim["exit_price"] - (101.0 - lock)) < 1e-9 and abs(sim["pnl"] - round((101.0 - lock - 100) * 10, 2)) < 1e-9
    assert sim["armed_at"] == 720


def test_stop_first_gap_and_same_bar_trail():
    p = jt.plan(rec(), rules=RULES0)
    # one bar touches both the stop and a big high: the stop wins
    sim = jt.simulate(p, [bar(600, 100, 103, 98.9, 102)], 60, 10_000, rules=RULES0)
    assert sim["how"] == "stop" and sim["exit_price"] == 99.0 and sim["pnl"] == -10.0 and sim["r"] == -1.0
    # opens through the stop: exits at the open
    sim = jt.simulate(p, [bar(600, 100, 100.1, 99.9, 100), bar(660, 98.5, 98.6, 98.0, 98.2)], 60, 10_000, rules=RULES0)
    assert sim["how"] == "stop (gap)" and sim["exit_price"] == 98.5
    # the bar that raises the stop then closes below it: out at the raised stop in that bar
    sim = jt.simulate(p, [bar(600, 100, 101.0, 99.9, 100.5)], 60, 10_000, rules=RULES0)
    assert sim["how"] == "stop" and abs(sim["exit_price"] - (101.0 - p["lock_px"])) < 1e-9 and sim["closed_at"] == 660


def test_sell_side_half_spread_and_time_limit():
    p = jt.plan(rec(side="sell", entry=100.0, initial_sl=101.0), rules=RULES0)
    bars = [bar(600 + 60 * i, 100, 100.1, 99.95, 100) for i in range(5)]
    rules = dict(RULES0, max_hold_s=240)
    sim = jt.simulate(p, bars, 60, 10_000, rules=rules)
    assert sim["how"] == "5-day limit" and sim["exit_price"] == 100 and sim["pnl"] == 0.0
    p2 = jt.plan(rec(), rules=dict(jt.TWIN_RULES, half_spread=True))
    sim2 = jt.simulate(p2, [bar(600, 100, 100.1, 98.9, 99)], 60, 10_000, rules=jt.TWIN_RULES)
    assert sim2["exit_price"] < 99.0                                             # the twin pays half the spread on exit
    # still running when the data stops before the limit: not final
    sim3 = jt.simulate(p, [bar(600, 100, 100.1, 99.95, 100)], 60, 700, rules=RULES0)
    assert sim3["state"] == "open"


def test_run_once_replays_closed_positions_and_endpoints_show_you_vs_twin(monkeypatch):
    monkeypatch.setenv("SENTINEL_ADMIN_KEY", "k")
    with s._lock, s._db() as con:
        con.execute("CREATE TABLE IF NOT EXISTS twin (key TEXT PRIMARY KEY, version TEXT, final INTEGER, updated INTEGER, data TEXT)")
        con.execute("DELETE FROM twin")
        con.execute("DELETE FROM managed")
    t0 = int(time.time()) - 3600
    a = rec(key="mt5:11", opened=t0 * 1000, pnl=-30.0, initial_sl=None, r_dist=None, exit_price=97.0,
            exit_reason="Manual", rule_break="no stop loss")
    b = rec(key="mt5:12", opened=t0 * 1000, pnl=2.0, exit_price=100.2, exit_reason="Stop loss")
    c = rec(key="mt5:13", opened=t0 * 1000, symbol="HF Volatility 50 Index")
    o = rec(key="mt5:14", opened=t0 * 1000, closed=None)                         # still open for Joel: not replayed
    for r in (a, b, c, o):
        s._save_managed(r)
    calls = []

    async def fake_fetch(sym, start, end, gran):
        calls.append(sym)
        first = -(-t0 // gran) * gran
        return [bar(first, 100, 100.2, 99.9, 100.1), bar(first + gran, 100.1, 100.15, 98.5, 98.6)]
    n = asyncio.run(jt.run_once(now_s=t0 + 7200, fetch=fake_fetch, limit=10))
    assert n == 3 and calls == ["1HZ50V", "1HZ50V"]
    tw = jt.load_all()
    assert tw["mt5:13"]["skip"].startswith("no public price feed") and "mt5:14" not in tw
    assert tw["mt5:11"]["final"] and tw["mt5:11"]["sim"]["pnl"] < -9.9          # twin: −1% at its added stop, not −$30

    class Req:
        headers = {"x-sentinel-key": "k"}
    out = s.managed(Req())
    by = {r["key"]: r for r in out["records"]}
    assert by["mt5:11"]["twin"]["stop_source"] == "added" and by["mt5:13"]["twin"]["skip"]
    st = out["stats"]["twin"]
    assert st["n"] == 2 and st["skipped"] == 1 and st["by_stop_source"]["added"]["n"] == 1
    assert st["you_total"] == -28.0 and st["twin_better"] >= 1
    full = s.twin(Req())
    assert full["version"] == jt.TWIN_VERSION and len(full["records"]) == 3 and full["rules"]
    # final results are not replayed again
    assert asyncio.run(jt.run_once(now_s=t0 + 7300, fetch=fake_fetch, limit=10)) == 0


def test_tracker_records_equity_and_money_per_point_at_the_fill():
    s._meta_set("mt5_channel", "owner")
    s._mt5_state["last"] = 0
    t0 = int(time.time()) - 5
    snap = {"account": {"equity": 1234.0}, "positions": [{"ticket": "99", "symbol": "Volatility 75 Index", "side": "buy",
            "volume": 0.5, "entry": 100.0, "price": 101.0, "sl": 99.0, "tp": 0, "profit": 5.0, "time": t0}]}
    s._mt5_track("owner", snap, None)
    r = s._mt5_open["mt5:99"]
    assert r["eq_open"] == 1234.0 and r["per_unit"] == 5.0 and s._mt5_state["equity"] == 1234.0
    s._mt5_open.clear()
