"""Drift: the 200-day line on US Tech 100 / US 500 — paper books and the MT5 demo through Sentinel Live.
   python3 -m pytest -q tests/test_drift.py      (or: python3 tests/test_drift.py)"""
import asyncio
import json
import os
import sys
import tempfile
import time

os.environ["SENTINEL_ENABLED"] = "0"
os.environ["SENTINEL_DB"] = os.path.join(tempfile.mkdtemp(), "d.db")
os.environ["SENTINEL_ADMIN_KEY"] = "o" * 32
os.environ["ACCOUNTS_DB"] = os.path.join(tempfile.mkdtemp(), "a.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI                     # noqa: E402
from fastapi.testclient import TestClient       # noqa: E402
import mt5_bridge                                # noqa: E402
import sentinel as S                             # noqa: E402
import sentinel_live as L                        # noqa: E402
import drift as D                                # noqa: E402

app = FastAPI(); app.include_router(mt5_bridge.router); app.include_router(S.router)
c = TestClient(app)
KEY = "d" * 32
OWNER = {"x-sentinel-key": "o" * 32}
CID = mt5_bridge.channel_id(KEY)
DAY = 86400
T0 = 1_700_006_400 - (1_700_006_400 % DAY)          # a 00:00 GMT boundary
# 1 lot = 1 index unit, $1 a point (tickValue/tickSize = 1)
SPEC = {"US Tech 100": {"symbol": "US Tech 100", "tickSize": 0.01, "tickValue": 0.01, "contractSize": 1, "volMin": 0.01, "volStep": 0.01, "volMax": 100},
        "US SP 500": {"symbol": "US SP 500", "tickSize": 0.01, "tickValue": 0.01, "contractSize": 1, "volMin": 0.01, "volStep": 0.01, "volMax": 100}}


def bars(closes, start=T0, spread=0.0):
    """Daily candles from closes: open = previous close, high/low around the day."""
    out, prev = [], closes[0]
    for i, x in enumerate(closes):
        out.append({"epoch": start + i * DAY, "o": prev, "h": max(prev, x) + spread, "l": min(prev, x) - spread, "c": x})
        prev = x
    return out


# ── the signal and the paper books (pure) ────────────────────────────────────

def test_line_and_signal():
    cs = bars([100.0] * 199)
    assert D.signal(cs) is None                                              # 199 closes: no line yet
    cs = bars([100.0] * 199 + [120.0])
    s = D.signal(cs)
    assert abs(s["line"] - (199 * 100 + 120) / 200) < 1e-9 and s["hold"] and s["dist_pct"] > 0
    assert abs(s["stop"] - s["line"] * 0.97) < 1e-3
    assert not D.signal(bars([100.0] * 199 + [90.0]))["hold"]
    lined = D.with_line(bars([float(i) for i in range(1, 401)]))
    assert abs(lined[-1]["line"] - sum(range(201, 401)) / 200) < 1e-9          # rolling, not cumulative


def test_complete_keeps_whole_days_only():
    now = T0 + 3 * DAY + 3600                                                 # an hour into day 4
    raw = [{"epoch": T0 - 43200 + 60, "open": 1, "high": 1, "low": 1, "close": 1}] + \
          [{"epoch": T0 + i * DAY, "open": 1, "high": 2, "low": 0.5, "close": 1.5} for i in range(4)]
    got = D.complete(raw, now)
    assert [g["epoch"] for g in got] == [T0, T0 + DAY, T0 + 2 * DAY]          # partial first candle and today dropped


def _path():
    """200 flat days, a rise above the line, then a fall through it."""
    return [100.0] * 200 + [101.0, 103.0, 106.0, 110.0, 112.0, 111.0, 113.0] + [100.0, 96.0, 95.0]


def test_pick_book_enters_next_open_exits_under_the_line():
    cs = {"frxNAS100": bars(_path())}
    start = cs["frxNAS100"][199]["epoch"]                                     # first day with a line
    b = D.simulate(cs, start, "pick")
    assert len(b["trades"]) == 1, b["trades"]
    t = b["trades"][0]
    # day 200 closes at 101 > line -> buy at day 201's open (101); day 207 closes at 100 < line -> sell at day 208's open (100)
    assert t["opened"] == T0 + 201 * DAY and t["entry"] == 101.0 and t["exit"] == 100.0 and t["why"].startswith("closed under")
    size = 0.5 * 10_000 * (1 - 0)                                             # half the account in the index
    assert abs(t["size"] - size) < 1e-6 * size + 0.01
    q = size / 101.0
    fin = sum(q * x * D.FINANCING_PA / 365 for x in [101.0, 103.0, 106.0, 110.0, 112.0, 111.0, 113.0])   # one charge a day held
    expect = q * (100.0 - 101.0) - size * D.SPREAD - q * 100.0 * D.SPREAD - fin
    assert abs(t["pnl"] - expect) < 0.05, (t["pnl"], expect)
    assert abs(b["equity"] - (10_000 + expect)) < 0.05 and b["positions"] == {}
    assert D.simulate(cs, start, "pick") == b                                 # same candles, same book


def test_rules_book_sizes_to_half_a_percent_and_raises_the_stop():
    cs = {"frxNAS100": bars(_path())}
    start = cs["frxNAS100"][199]["epoch"]
    b = D.simulate(cs, start, "rules")
    t = b["trades"][0]
    line200 = (199 * 100 + 101) / 200
    stop0 = line200 * 0.97
    risk = 0.005 * 10_000
    size = min(risk / ((101.0 - stop0) / 101.0), 0.5 * 10_000)
    assert abs(t["size"] - size) < 0.02 and abs(t["risk"] - risk) < 0.02, t
    assert t["entry"] == 101.0 and t["exit"] == 100.0                         # the line exit comes before the stop here
    assert abs(t["r"] - t["pnl"] / t["risk"]) < 1e-3
    # a gap through the stop fills at the open, not at the stop
    cs2 = bars([100.0] * 200 + [101.0, 104.0, 108.0])
    cs2.append({"epoch": T0 + 203 * DAY, "o": 85.0, "h": 86.0, "l": 80.0, "c": 82.0})
    t2 = D.simulate({"frxNAS100": cs2}, start, "rules")["trades"][0]
    assert t2["why"] == "stop under the line" and t2["exit"] == 85.0, t2


def test_rules_stop_inside_the_day():
    path = [100.0] * 200 + [101.0, 104.0, 106.0]
    cs = bars(path)
    cs.append({"epoch": T0 + 203 * DAY, "o": 105.0, "h": 105.5, "l": 90.0, "c": 104.0})   # dips through the stop, closes back up
    b = D.simulate({"frxNAS100": cs}, T0 + 199 * DAY, "rules")
    t = b["trades"][0]
    stop = max(x["line"] for x in D.with_line(cs)[200:203]) * 0.97
    assert t["why"] == "stop under the line" and abs(t["exit"] - stop) < 1e-3, t
    assert b["pending"] == {"frxNAS100": "enter"}                            # closed back above the line: in again tomorrow


def test_two_markets_share_one_account():
    cs = {"frxNAS100": bars(_path()), "frxSPX500": bars([50.0] * 200 + [52.0] * 10)}
    b = D.simulate(cs, T0 + 199 * DAY, "pick")
    assert set(b["positions"]) == {"frxSPX500"} and abs(b["exposure_pct"] - 50) < 2, b["exposure_pct"]
    sizes = sorted(t["size"] for t in b["trades"]) + [b["positions"]["frxSPX500"]["size"]]
    assert all(s <= 0.5 * 10_000 * 1.2 for s in sizes)


# ── the demo, through Sentinel Live's executor with a fake EA ────────────────

class EA:
    def __init__(self, equity=100_000.0):
        self.mode, self.equity, self.positions, self.deals, self.results, self.cmds = "demo", equity, {}, [], [], []
        self.next_ticket, self.fill_px, self.close_pnl = 5000, {"US Tech 100": 30_000.0, "US SP 500": 7_700.0}, 0.0

    def sync(self):
        body = {"account": {"mode": self.mode, "equity": self.equity, "balance": self.equity, "currency": "USD"},
                "positions": list(self.positions.values()), "orders": [], "limits": {}, "ea": {},
                "results": self.results, "history": self.deals}
        self.results = []
        r = c.post("/api/bridge/ea", content=json.dumps(body), headers={"x-bridge-key": KEY})
        assert r.status_code == 200, r.text
        for line in r.text.strip().split("\n")[1:]:
            f = line.split("|")
            cmd = {"id": f[1], "type": f[2], "symbol": f[3], "side": f[4], "volume": f[5], "price": f[6], "sl": f[7], "ticket": f[9]}
            self.cmds.append(cmd)
            self.answer(cmd)

    def answer(self, cmd):
        t = cmd["type"]
        if t == "spec":
            ok = cmd["symbol"] in SPEC
            self.results.append({"id": cmd["id"], "ok": ok, "msg": "spec" if ok else "no such symbol", **({"spec": SPEC[cmd["symbol"]]} if ok else {})})
        elif t == "market":
            tk = str(self.next_ticket); self.next_ticket += 1
            px = self.fill_px[cmd["symbol"]]
            self.positions[tk] = {"ticket": tk, "symbol": cmd["symbol"], "side": cmd["side"], "volume": float(cmd["volume"]),
                                  "entry": px, "price": px, "sl": float(cmd["sl"]), "tp": 0, "profit": 0, "time": int(time.time()), "mine": True}
            self.results.append({"id": cmd["id"], "ok": True, "msg": "Filled", "price": px, "volume": float(cmd["volume"]), "ticket": tk})
        elif t == "modify":
            self.positions[cmd["ticket"]]["sl"] = float(cmd["sl"])
            self.results.append({"id": cmd["id"], "ok": True, "msg": "modified"})
        elif t == "close":
            p = self.positions.pop(cmd["ticket"])
            self.deals.append({"kind": "trade", "ticket": cmd["ticket"], "exit": p["price"], "profit": self.close_pnl, "reason": "PROTrader / EA", "time": time.time()})
            self.results.append({"id": cmd["id"], "ok": True, "msg": "closed"})


def run(ea, n=2, now=None):
    for _ in range(n):
        ea.sync(); L.tick(now)          # the executor's clock follows the test's clock


def _reset():
    with S._lock, S._db() as con:
        con.execute("DELETE FROM live_trades")
        con.execute("DELETE FROM drift_candles")
    S._meta_set("drift_cfg", {})
    S._meta_set("live_cfg", {})


def _sig(close, line, epoch, hold=None):
    return {"epoch": epoch, "close": close, "line": line, "dist_pct": 100 * (close / line - 1),
            "hold": close > line if hold is None else hold, "stop": round(line * 0.97, 4), "days": 260}


def test_demo_start_rules_entry_stop_moves_exit():
    _reset()
    sent = []
    L._telegram = lambda text: sent.append(text)
    ea = EA()
    ea.sync()
    assert c.post("/api/sentinel/drift", json={"action": "start"}, headers=OWNER).status_code == 409    # bridge not bound
    S._meta_set("mt5_channel", CID)
    ea.mode = "real"; ea.sync()
    r = c.post("/api/sentinel/drift", json={"action": "start"}, headers=OWNER)
    assert r.status_code == 409 and "demo" in r.json()["detail"]                                          # never real
    ea.mode = "demo"; ea.sync()
    assert c.post("/api/sentinel/drift", json={"action": "start"}).status_code == 403                    # owner only
    assert c.post("/api/sentinel/drift", json={"action": "start"}, headers=OWNER).status_code == 200
    run(ea)                                                                                               # specs for Drift's symbols
    assert set(L.cfg()["specs"]) >= {"US Tech 100", "US SP 500"}, L.cfg().get("spec_errors")

    # Wednesday 12:00 GMT, market open, both indices above their lines
    now = T0 + 6 * DAY + 12 * 3600
    while time.gmtime(now).tm_wday != 2:
        now += DAY
    day = now - now % DAY - DAY                                       # yesterday's whole candle
    sigs = {"frxNAS100": _sig(30_000.0, 28_000.0, day), "frxSPX500": _sig(7_700.0, 7_400.0, day)}
    ticks = {"frxNAS100": (int(now) - 5, 30_000.0), "frxSPX500": (int(now) - 5, 7_700.0)}
    shut = {k: (v[0] - 3600, v[1]) for k, v in ticks.items()}
    assert D.demo_step(sigs, shut, now)["frxNAS100"].startswith("market shut")                          # stale price: nothing sent
    assert not [x for x in ea.cmds if x["type"] == "market"]
    out = D.demo_step(sigs, ticks, now)
    assert out["frxNAS100"]["sent"] and out["frxSPX500"]["sent"], out
    ndx = next(r for r in L.rows() if r.get("kind") == "drift" and r["market"] == "frxNAS100" and r["state"] == "sent")
    # 0.5% of $100,000 = $500 at a stop 3% under the line (27,160): 2,840 points a lot -> 0.17 lots (by size cap 1.66)
    assert ndx["sl_initial"] == 27_160.0 and ndx["lots"] == 0.17 and abs(ndx["risk_money"] - 0.17 * 2840) < 0.01, ndx
    assert any(t.startswith("Drift · buying 0.17 US Tech 100") for t in sent), sent
    run(ea, now=now + 5)
    rows = {r["market"]: r for r in L.rows() if r.get("kind") == "drift" and r["state"] == "open"}
    assert set(rows) == {"frxNAS100", "frxSPX500"} and any("Drift · filled" in t for t in sent)
    # both bots share the framework: Drift's open risk counts in Sentinel Live's risk state
    rs = L._risk_state(now, ea.equity)
    assert abs(rs["open_risk"] - (rows["frxNAS100"]["risk_now"] + rows["frxSPX500"]["risk_now"])) < 0.01 and rs["open_risk"] <= 1000.01
    # Sentinel Live's own panel does not list Drift's trades
    st = c.get("/api/sentinel/live", headers=OWNER).json()
    assert not any(t["id"] == ndx["id"] for t in st["trades"]) and st["metrics"]["signals"] == 0

    # same signal later the same day: no second entry
    assert "waiting" in D.demo_step(sigs, ticks, now + 600)["frxNAS100"] or "holding" in D.demo_step(sigs, ticks, now + 600)["frxNAS100"]
    assert sum(1 for x in ea.cmds if x["type"] == "market") == 2

    # next day the line has risen: the stop follows it up (never down), and MT5 gets the move
    now2, day2 = now + DAY, day + DAY
    sigs2 = {"frxNAS100": _sig(30_500.0, 28_200.0, day2), "frxSPX500": _sig(7_750.0, 7_380.0, day2)}
    ticks2 = {k: (int(now2) - 5, v["close"]) for k, v in sigs2.items()}
    out = D.demo_step(sigs2, ticks2, now2)
    assert out["frxNAS100"].startswith("stop raised") and out["frxSPX500"] == "holding", out
    run(ea, now=now2 + 5)
    tk = rows["frxNAS100"]["ticket"]
    assert ea.positions[tk]["sl"] == 27_354.0 and ea.positions[rows["frxSPX500"]["ticket"]]["sl"] == 7_178.0

    # a close under the line: close it at the next open, journaled with Drift's own reason
    now3, day3 = now2 + DAY, day2 + DAY
    sigs3 = {"frxNAS100": _sig(28_000.0, 28_300.0, day3), "frxSPX500": _sig(7_760.0, 7_390.0, day3)}
    ticks3 = {k: (int(now3) - 5, v["close"]) for k, v in sigs3.items()}
    ea.close_pnl = -340.0
    assert D.demo_step(sigs3, ticks3, now3)["frxNAS100"] == "closing"
    run(ea, 3, now=now3 + 5)
    r = L._row(ndx["id"])
    assert r["state"] == "closed" and r["pnl"] == -340.0 and r["exit_why"] == "closed under the 200-day line", r
    assert any("Drift · closing US Tech 100" in t for t in sent) and any(t.startswith("Drift · closed US Tech 100") for t in sent)
    # closed today: no new entry until tomorrow's close, even if the line flips back
    sigs4 = dict(sigs3, frxNAS100=_sig(28_600.0, 28_300.0, day3))
    assert D.demo_step(sigs4, ticks3, now3 + 1800)["frxNAS100"].startswith("traded or stopped today")

    # the endpoint shows Drift's own journal
    got = c.get("/api/sentinel/drift", headers=OWNER).json()
    assert got["demo"]["on"] and got["demo"]["closed"] == 1 and got["demo"]["open"] == 1 and got["demo"]["net"] == -340.0


def test_demo_skips_small_accounts_and_real_accounts_once():
    _reset()
    sent = []
    L._telegram = lambda text: sent.append(text)
    S._meta_set("mt5_channel", CID)
    ea = EA(equity=2_000.0); ea.sync()
    assert c.post("/api/sentinel/drift", json={"action": "start"}, headers=OWNER).status_code == 200
    run(ea)
    now = T0 + 12 * 3600
    while time.gmtime(now).tm_wday != 1:
        now += DAY
    day = now - now % DAY - DAY
    sigs = {"frxNAS100": _sig(30_000.0, 28_000.0, day), "frxSPX500": _sig(7_700.0, 7_400.0, day, hold=False)}
    ticks = {k: (int(now) - 5, v["close"]) for k, v in sigs.items()}
    out = D.demo_step(sigs, ticks, now)
    # 0.01 lot x 2,840 points = $28.40 = 1.42% of $2,000: above Drift's 0.5%
    assert out["frxNAS100"]["skipped"].startswith("minimum lot 0.01 would risk $28.40 = 1.42%"), out
    assert out["frxSPX500"] == "aside: under the line"
    D.demo_step(sigs, {k: (v[0] + 60, v[1] * 1.01) for k, v in ticks.items()}, now + 60)   # price moved: same reason, new numbers
    assert sum(1 for r in L.rows() if r.get("kind") == "drift" and r["state"] == "skipped") == 1
    for k in range(3):                                                 # same reason on later cycles and days: told once
        D.demo_step({**sigs, "frxNAS100": _sig(30_000.0, 28_000.0, day + k * DAY)}, ticks, now + k * DAY)
    assert sum(1 for t in sent if "not entered US Tech 100" in t) == 1, sent
    assert not [x for x in ea.cmds if x["type"] == "market"]
    ea.mode = "real"; ea.sync()
    out = D.demo_step(sigs, ticks, now)
    assert "not a demo account" in out["frxNAS100"]["skipped"] and not [x for x in ea.cmds if x["type"] == "market"]


def test_run_once_reads_deriv_stores_whole_days_and_never_trades():
    _reset()
    now = T0 + 300 * DAY + 13 * 3600
    reqs = []

    async def call(req):
        reqs.append(req)
        assert set(req) <= {"ticks_history", "end", "count", "style", "granularity"} and "buy" not in req
        if req["style"] == "candles":
            n = 260
            first = now - now % DAY - (n - 1) * DAY
            return {"msg_type": "candles", "candles": [{"epoch": first + i * DAY, "open": 100 + i * 0.1, "high": 101 + i * 0.1,
                                                       "low": 99 + i * 0.1, "close": 100 + i * 0.1} for i in range(n)]}
        return {"msg_type": "history", "history": {"times": [int(now) - 3], "prices": [126.0]}}
    out = asyncio.run(D.run_once(now, call))
    assert len(D.load_candles("frxNAS100")) == 259                             # today's unfinished candle left out
    assert out["signals"]["frxNAS100"]["hold"] and D.cfg()["paper_start"] == out["signals"]["frxNAS100"]["epoch"]
    assert out["demo"] == {}                                                    # demo not started: no orders at all
    asyncio.run(D.run_once(now + 600, call))
    assert any(r.get("count") == 15 for r in reqs)                              # once a year is stored, only the latest days are read
    got = c.get("/api/sentinel/drift", headers=OWNER).json()
    assert set(got["books"]) == {"pick", "rules"} and got["signals"]["frxSPX500"]["hold"] and got["history"]["rows"]
    # with MT5's spec known, the panel says what equity one minimum lot needs at today's distance from the stop
    L._set_cfg(dict(L.cfg(), specs={k: dict(v, at=now) for k, v in SPEC.items()}))
    sg = got["signals"]["frxNAS100"]
    need = c.get("/api/sentinel/drift", headers=OWNER).json()["demo"]["needs"]["frxNAS100"]
    assert need["min_lot"] == 0.01 and abs(need["risk_min_lot"] - 0.01 * (sg["close"] - sg["stop"])) < 0.01
    assert abs(need["equity_needed"] - need["risk_min_lot"] / 0.005) <= 1


if __name__ == "__main__":
    for name, f in list(globals().items()):
        if name.startswith("test_") and callable(f):
            f(); print("ok ", name)
