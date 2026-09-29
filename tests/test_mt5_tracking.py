"""Server-side MT5 management tracking.   python3 tests/test_mt5_tracking.py"""
import os, sys, tempfile, time
os.environ["SENTINEL_ENABLED"] = "0"
os.environ["SENTINEL_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import sentinel as s


def snap(sl, price, profit, t0):
    return {"positions": [{"ticket": "9", "symbol": "Volatility 75 Index", "side": "sell", "volume": 0.02,
                           "entry": 50000.0, "price": price, "sl": sl, "tp": 0, "profit": profit, "time": t0}]}


def run(step):
    s._mt5_state["last"] = 0          # skip the 2 s throttle in tests
    step()


def test_sell_trade_managed_to_profit_and_other_channels_ignored():
    s._meta_set("mt5_channel", "owner")
    t0 = int(time.time()) - 5
    run(lambda: s._mt5_track("stranger", snap(50100, 49990, 2, t0), None))
    assert not s._mt5_open                                   # not the owner's account
    run(lambda: s._mt5_track("owner", snap(50100, 49950, 10, t0), None))
    run(lambda: s._mt5_track("owner", snap(50000, 49850, 30, t0), None))    # stop to breakeven
    run(lambda: s._mt5_track("owner", snap(49900, 49700, 60, t0), None))    # lock +1R
    r = s._mt5_open["mt5:9"]
    assert r["r_dist"] == 100 and r["be_at"] and r["locked_r"] == 1.0 and r["peak_pnl"] == 60
    run(lambda: s._mt5_track("owner", {"positions": []},
                             [{"kind": "trade", "ticket": "9", "exit": 49900, "profit": 20.0, "reason": "Stop loss"}]))
    rec = [x for x in s._managed_rows() if x["key"] == "mt5:9"][0]
    assert rec["closed"] and rec["exit_r"] == 1.0 and rec["stage"] == "Managed winner"
    assert [e["type"] for e in rec["events"]] == ["open", "stop", "risk_free", "stop", "close"]
    assert "mt5:9" not in s._mt5_open


def test_rule_break_flagged_and_kept_out_of_stats():
    s._meta_set("mt5_channel", "owner")
    t0 = int(time.time()) - 5
    big = {"account": {"equity": 1000.0}, "positions": [{"ticket": "77", "symbol": "Volatility 75 Index", "side": "buy",
            "volume": 1.0, "entry": 100.0, "price": 101.0, "sl": 90.0, "tp": 0, "profit": 10.0, "time": t0}]}
    run(lambda: s._mt5_track("owner", big, None))          # $10 per point x 10 points = $100 = 10% of $1,000
    r = s._mt5_open["mt5:77"]
    assert r["rule_break"].startswith("risked 10.0%") and r["risk_pct"] == 10.0
    ok = {"account": {"equity": 1000.0}, "positions": [{"ticket": "78", "symbol": "Volatility 75 Index", "side": "buy",
           "volume": 0.1, "entry": 100.0, "price": 101.0, "sl": 90.0, "tp": 0, "profit": 1.0, "time": t0}]}
    run(lambda: s._mt5_track("owner", ok, None))           # $10 = 1% -> fine
    r2 = s._mt5_open["mt5:78"]
    assert not r2.get("rule_break") and r2["risk_pct"] == 1.0
    recs = [{"closed": 1, "pnl": -100, "rule_break": "risked 10.0% (limit 1%)", "stage": "Full loser"},
            {"closed": 1, "pnl": 20, "stage": "Managed winner", "be_at": 1}]
    st = s._managed_stats(recs)
    assert st["n"] == 1 and st["pnl_total"] == 20 and st["rule_breaks"] == {"n": 1, "pnl": -100}
    s._mt5_open.clear()


def test_stages():
    assert s.mgmt_stage({"pnl": -10, "r_dist": 1, "exit_r": -1.0}) == "Full loser"
    assert s.mgmt_stage({"pnl": 0.2, "r_dist": 1, "exit_r": 0.02, "be_at": 1}) == "Protected flat"
    assert s.mgmt_stage({"pnl": 30, "exit_reason": "Take profit"}) == "Full winner"
    assert s.mgmt_stage({"pnl": 12}) == "Unprotected winner"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
