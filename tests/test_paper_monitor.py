"""Sentinel reads the owner's saved paper account.   python3 -m pytest -q tests/test_paper_monitor.py"""
import asyncio
import json
import os
import sys
import tempfile
import time

os.environ["SENTINEL_ENABLED"] = "0"
os.environ.setdefault("SENTINEL_DB", os.path.join(tempfile.mkdtemp(), "pm.db"))
os.environ.setdefault("ACCOUNTS_DB", os.path.join(tempfile.mkdtemp(), "acc.db"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import accounts                  # noqa: E402
import sentinel as s             # noqa: E402
import paper_monitor as pm       # noqa: E402
import joel_twin as jt           # noqa: E402

T0 = 1_791_000_000_000           # ms


def fill(i, pnl, *, sym="1HZ50V", side="buy", entry=100.0, exit_=101.0, vol=1.0, open_=None, close=None,
         reason="Manual", risk0=10.0, sl0=99.0, final=True):
    return {"id": i, "sym": sym, "pair": "Vol 50 (1s)" if sym == "1HZ50V" else sym, "type": side, "volume": vol,
            "entry": entry, "exit": exit_, "pnl": pnl, "openTime": open_ or T0 + i * 60_000,
            "closeTime": close or T0 + i * 60_000 + 30_000, "reason": reason, "sl0": sl0, "risk0": risk0, "final": final}


def test_fills_become_positions_with_real_r():
    fills = [fill(1, 5.0, vol=0.5, final=False, close=T0 + 70_000), fill(1, 7.0, vol=0.5, exit_=102.0, close=T0 + 90_000),
             fill(2, -10.0, exit_=99.0, reason="Stop loss")]
    ps = pm.positions_from_fills(fills)
    assert len(ps) == 2
    p1 = next(p for p in ps if p["id"] == 1)
    assert p1["fills"] == 2 and p1["pnl"] == 12.0 and p1["closed"] and abs(p1["exit"] - 101.5) < 1e-9 and p1["r"] == 1.2
    p2 = next(p for p in ps if p["id"] == 2)
    assert p2["r"] == -1.0 and p2["reason"] == "Stop loss"


def test_analysis_dollars_r_verdict_and_breakdowns():
    fills = [fill(i, 6.0 if i % 3 else -10.0, reason="Take profit" if i % 3 else "Stop loss",
                  sym="1HZ50V" if i % 2 else "frxXAUUSD") for i in range(1, 41)]
    doc = {"balance": 10_000 + sum(f["pnl"] for f in fills), "trades": fills, "positions": [{"label": "Vol 50 (1s)", "risk0": 12.5}]}
    ps = pm.positions_from_fills(fills)
    a = pm.analyze(doc, ps, {"3": "TCL", "4": "SMOG"})
    assert a["n"] == 40 and a["start_balance"] == 10_000.0 and a["history_complete"]
    assert a["wins"] == 27 and a["losses"] == 13 and a["pnl_total"] == round(27 * 6 - 130, 2)
    assert a["r"]["n"] == 40 and abs(a["r"]["mean"] - (27 * 0.6 - 13) / 40) < 1e-3 and a["r"]["full_stop_pct"] == 0.325
    assert a["r"]["verdict"] == "not distinguishable from zero yet"
    assert set(a["by_exit"]) == {"target", "stop"} and a["by_setup"]["TCL"]["n"] == 1 and a["untagged"] == 38
    assert a["open"] == {"n": 1, "risk_at_stops": 12.5, "symbols": ["Vol 50 (1s)"]}
    assert "spread is paid" in a["caveat"]
    good = [fill(i, 8.0, reason="Take profit") for i in range(1, 41)] + [fill(41, -10.0, reason="Stop loss")]
    a2 = pm.analyze({"balance": 10_000 + 310, "trades": good}, pm.positions_from_fills(good))
    assert a2["r"]["verdict"] == "positive beyond chance so far"
    assert pm.analyze({"balance": 1, "trades": []}, [])["n"] == 0
    assert pm.skill_verdict(12, [0.1, 0.5]).startswith("too few")


def test_owner_doc_reads_only_the_instructor_and_cycle_persists():
    accounts.init()
    with accounts._db() as db:
        db.execute("DELETE FROM workspace"); db.execute("DELETE FROM users")
        db.execute("INSERT INTO users(id, name, email, role, status, verified, created) VALUES (1,'Joel','j@x','teacher','accepted',1,0)")
        db.execute("INSERT INTO users(id, name, email, role, status, verified, created) VALUES (2,'Stu','s@x','student','accepted',1,0)")
        db.execute("INSERT INTO workspace VALUES (2,'trade',?,1,?)", (json.dumps({"balance": 5, "trades": []}), time.time()))
    assert pm.owner_doc() is None                                       # a student's account is never read
    fills = [fill(1, 12.0), fill(2, -10.0, reason="Stop loss")]
    with accounts._db() as db:
        db.execute("INSERT INTO workspace VALUES (1,'trade',?,1,?)", (json.dumps({"balance": 10_002.0, "trades": fills, "positions": []}), time.time()))
    assert pm.owner_doc()["balance"] == 10_002.0
    with s._lock, s._db() as con:
        con.execute("DROP TABLE IF EXISTS paper_positions")
    pm.cycle()
    assert pm._state["positions"] == 2 and len(pm.stored()) == 2
    # the saved account later drops old fills (500 cap): the stored history keeps them
    with accounts._db() as db:
        db.execute("UPDATE workspace SET data=? WHERE user_id=1", (json.dumps({"balance": 10_007.0, "trades": [fill(3, 5.0)]}),))
    pm.cycle()
    assert [p["id"] for p in pm.stored()] == [1, 2, 3]


def test_twin_records_and_balance_rebuild():
    ps = pm.positions_from_fills([fill(1, 12.0, open_=T0, close=T0 + 60_000), fill(2, -10.0, open_=T0 + 120_000, close=T0 + 180_000)])
    recs = pm.twin_records(ps, 10_002.0)
    r1, r2 = recs
    assert r1["key"].startswith("paperacct:") and r1["per_unit"] == 10.0 and r1["r_dist"] == 1.0
    assert r1["eq_open"] == 10_000.0 and r2["eq_open"] == 10_012.0                  # balance just before each opened
    assert jt.feed_market(r1["symbol"]).id == "1HZ50V"
    p = jt.plan(r1, rules=dict(jt.TWIN_RULES, half_spread=False))
    assert p["stop_source"] == "yours" and p["stop0"] == 99.0


def test_endpoint_and_twin_cover_paper_positions(monkeypatch):
    monkeypatch.setenv("SENTINEL_ADMIN_KEY", "k")
    accounts.init()
    t0 = int(time.time()) - 7200
    fills = [fill(7, 15.0, open_=t0 * 1000, close=(t0 + 600) * 1000), fill(8, -10.0, open_=(t0 + 900) * 1000, close=(t0 + 1500) * 1000, reason="Stop loss")]
    with accounts._db() as db:
        db.execute("DELETE FROM workspace"); db.execute("DELETE FROM users")
        db.execute("INSERT INTO users(id, name, email, role, status, verified, created) VALUES (1,'Joel','j@x','teacher','accepted',1,0)")
        db.execute("INSERT INTO workspace VALUES (1,'trade',?,1,?)", (json.dumps({"balance": 10_005.0, "trades": fills, "positions": []}), time.time()))
    with s._lock, s._db() as con:
        con.execute("DROP TABLE IF EXISTS paper_positions")
        con.execute("CREATE TABLE IF NOT EXISTS twin (key TEXT PRIMARY KEY, version TEXT, final INTEGER, updated INTEGER, data TEXT)")
        con.execute("DELETE FROM twin"); con.execute("DELETE FROM managed")
    s._save_managed({"key": "paper:7", "src": "paper", "opened": t0 * 1000, "closed": None, "setup": "G2", "events": []})
    pm.cycle()

    async def fake_fetch(sym, start, end, gran):
        first = -(-start // gran) * gran
        return [{"time": first + gran * i, "open": 100, "high": 100.5, "low": 98.5, "close": 99} for i in range(4)]
    n = asyncio.run(jt.run_once(now_s=t0 + 9000, fetch=fake_fetch, limit=10))
    assert n == 2

    class Req:
        headers = {"x-sentinel-key": "k"}
    out = s.paper(Req())
    assert out["found"] and out["n"] == 2 and out["balance"] == 10_005.0 and out["start_balance"] == 10_000.0
    assert out["by_setup"] == {"G2": {"n": 1, "pnl": 15.0, "wins": 1, "win_pct": 1.0, "avg_r": 1.5}}
    assert out["twin"]["n"] == 2 and out["twin"]["eligible"] == 2
