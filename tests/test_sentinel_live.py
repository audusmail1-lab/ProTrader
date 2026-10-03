"""Sentinel Live test on an MT5 demo account, with a fake EA.   python3 tests/test_sentinel_live.py"""
import json, os, sys, tempfile, time

os.environ["SENTINEL_ENABLED"] = "0"
os.environ["SENTINEL_DB"] = os.path.join(tempfile.mkdtemp(), "s.db")
os.environ["SENTINEL_ADMIN_KEY"] = "o" * 32
os.environ["ACCOUNTS_DB"] = os.path.join(tempfile.mkdtemp(), "a.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
import mt5_bridge
import sentinel as S
import sentinel_core as core
import sentinel_live as L

app = FastAPI(); app.include_router(mt5_bridge.router); app.include_router(S.router)
c = TestClient(app)
KEY = "b" * 32
OWNER = {"x-sentinel-key": "o" * 32}
CID = mt5_bridge.channel_id(KEY)
SPEC = {"XAUUSD": {"symbol": "XAUUSD", "tickSize": 0.01, "tickValue": 1.0, "contractSize": 100, "volMin": 0.01, "volStep": 0.01, "volMax": 50},
        "US Tech 100": {"symbol": "US Tech 100", "tickSize": 0.01, "tickValue": 0.01, "contractSize": 1, "volMin": 0.1, "volStep": 0.1, "volMax": 100}}


class EA:
    """Answers commands the way PROTraderBridge.mq5 does."""
    def __init__(self, mode="demo", equity=3000.0):
        self.mode, self.equity, self.positions, self.deals, self.results, self.cmds = mode, equity, {}, [], [], []
        self.next_ticket = 1000

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
            if cmd["symbol"] in SPEC:
                self.results.append({"id": cmd["id"], "ok": True, "msg": "spec", "spec": SPEC[cmd["symbol"]]})
            else:
                self.results.append({"id": cmd["id"], "ok": False, "msg": f"MT5 has no symbol called '{cmd['symbol']}'"})
        elif t == "market" and getattr(self, "risk_reject", 0) > 0:
            self.risk_reject -= 1
            self.results.append({"id": cmd["id"], "ok": False, "msg": "Risk at stop is 30.60, above 1.0% of equity (30.00)"})
        elif t == "market":
            tk = str(self.next_ticket); self.next_ticket += 1
            px = self.fill_px
            self.positions[tk] = {"ticket": tk, "symbol": cmd["symbol"], "side": cmd["side"], "volume": float(cmd["volume"]),
                                  "entry": px, "price": px, "sl": float(cmd["sl"]), "tp": 0, "profit": 0, "time": int(time.time())}
            self.results.append({"id": cmd["id"], "ok": True, "msg": "Filled", "price": px, "volume": float(cmd["volume"]), "ticket": tk})
        elif t == "modify":
            p = self.positions[cmd["ticket"]]; p["sl"] = float(cmd["sl"])
            self.results.append({"id": cmd["id"], "ok": True, "msg": "modified"})
        elif t == "close":
            p = self.positions.pop(cmd["ticket"])
            self.deals.append({"kind": "trade", "ticket": cmd["ticket"], "exit": p["price"], "profit": self.close_pnl, "reason": "PROTrader / EA", "time": time.time()})
            self.results.append({"id": cmd["id"], "ok": True, "msg": "closed"})


def trade(tid, market="frxXAUUSD", tf="15m", entry=2650.0, sl=2640.0, grade="A", d="buy"):
    t = core.Trade(id=tid, market=market, tf=tf, mode="real", tier="qualified", dir=d, opened_at=int(time.time()),
                   entry=entry, sl=sl, tp1=entry + 15, tp2=entry + 25, sl_dist=abs(entry - sl), cost_r=0.02, score=8,
                   gates=[], mcc="TREND", wyckoff="", pattern=None, rsi=50.0, model="7.2c", stop=sl)
    t.grade = grade
    return t


def cycle(ea, n=2):
    for _ in range(n):
        ea.sync(); L.tick()


def main():
    ea = EA(); ea.fill_px = 2650.4; ea.close_pnl = 0
    ea.sync()
    assert c.post("/api/sentinel/live", json={"action": "start"}, headers=OWNER).status_code == 409   # not bound yet
    S._meta_set("mt5_channel", CID)
    ea.mode = "real"; ea.sync()
    r = c.post("/api/sentinel/live", json={"action": "start"}, headers=OWNER)
    assert r.status_code == 409 and "demo" in r.json()["detail"], r.text          # never on a real account
    ea.mode = "demo"; ea.sync()
    assert c.post("/api/sentinel/live", json={"action": "start"}).status_code == 403                 # owner only
    assert c.post("/api/sentinel/live", json={"action": "start"}, headers=OWNER).status_code == 200
    cycle(ea)
    st = c.get("/api/sentinel/live", headers=OWNER).json()
    assert st["active"] and st["specs"]["XAUUSD"]["volMin"] == 0.01 and "BTCUSD" in st["spec_errors"], st
    print("ok  start: owner only, demo only, contract specs read from MT5")

    # an A setup on gold: 1% of $3,000 = $30; $10 stop x $100/lot per $1 -> 0.03 lots
    row = L.on_open(trade("x1"))
    assert row["state"] == "sent" and row["lots"] == 0.03 and row["risk_money"] == 30.0, row
    cycle(ea)
    r1 = L._row("x1")
    assert r1["state"] == "open" and r1["ticket"] == "1000" and abs(r1["slip_r"] - (-0.04)) < 1e-9, r1
    assert ea.cmds[-1]["type"] == "market" and float(ea.cmds[-1]["sl"]) == 2640.0
    print("ok  entry: A setup sized to 1% from MT5's spec, stop attached, fill and slippage recorded")

    # Sentinel moves its stop to breakeven, then trails; each move reaches MT5
    t = trade("x1"); t.stop = 2650.0; L.on_update(t); cycle(ea)
    t.stop = 2655.0; L.on_update(t); cycle(ea)
    t.stop = 2652.0; L.on_update(t); cycle(ea)                                   # never loosened
    r1 = L._row("x1")
    assert ea.positions["1000"]["sl"] == 2655.0 and r1["sl_live"] == 2655.0 and len(r1["stop_moves"]) == 2, r1
    print("ok  management: stop moves mirrored to MT5, never loosened")

    # not taken: other grades, the minimum lot above 1%, a real account
    assert L.on_open(trade("x2", grade="other")) is None
    ea.equity = 100.0; ea.sync()
    r2 = L.on_open(trade("x3", tf="1h", entry=2650, sl=2625))
    assert r2["state"] == "skipped" and "minimum lot 0.01 would risk $25.00 = 25.0%" in r2["reason"], r2
    ea.equity = 3000.0; ea.mode = "real"; ea.sync()
    assert "demo only" in L.on_open(trade("x4", market="frxNAS100", entry=20000, sl=19950))["reason"]
    ea.mode = "demo"; ea.sync()
    print("ok  skipped and journaled: other grades ignored, min lot above 1% ($100 account), real account")

    # 2% open-risk cap: x1 is protected (stop past entry = no risk), so two more
    # 1% trades fit; a fourth does not
    ea.fill_px = 20000.0
    L.on_open(trade("x5", market="frxNAS100", entry=20000, sl=19950)); cycle(ea)
    ea.fill_px = 2650.0
    L.on_open(trade("x6", tf="1h", entry=2650, sl=2640)); cycle(ea)
    assert L._row("x5")["state"] == "open" and L._row("x6")["state"] == "open", (L._row("x5"), L._row("x6"))
    r8 = L.on_open(trade("x8", tf="4h", entry=2650, sl=2640))
    assert r8["state"] == "skipped" and "open-risk" in r8["reason"], r8
    print("ok  2% open-risk cap respected; a protected trade counts as no risk")

    # the price moved against the entry before the order reached MT5: one step smaller, once
    ea.risk_reject = 1; ea.fill_px = 2650.0
    x9 = trade("x9", market="frxXAUUSD", tf="4h", entry=2650, sl=2645)                    # $5 stop: 1% of $3,000 = $30 -> 0.06 lots
    L._row("x6")["state"]
    r = L._row("x6"); r["risk_now"] = 0; L._save(r)                                      # x6 protected now: room for one more
    L.on_open(x9); cycle(ea, 4)
    r9 = L._row("x9")
    assert r9["state"] == "open" and r9["resized"] and r9["lots"] == 0.05, r9
    print("ok  an EA 1% rejection after a small adverse move is resent one lot step smaller")

    # closes: MT5's stop takes x1; Sentinel's timeout closes x5
    p = ea.positions.pop("1000")
    ea.deals.append({"kind": "trade", "ticket": "1000", "exit": 2655.0, "profit": 13.8, "reason": "Stop loss", "time": time.time()})
    L._row("x1")                                                                 # filled a moment ago: wait past the grace
    r = L._row("x1"); r["filled_at"] -= 30; L._save(r)
    cycle(ea)
    r1 = L._row("x1")
    assert r1["state"] == "closed" and r1["pnl"] == 13.8 and r1["exit_reason"] == "Stop loss", r1
    t5 = trade("x5", market="frxNAS100", entry=20000, sl=19950); t5.status, t5.r = "timeout", 0.3
    ea.close_pnl = 9.0
    L.on_update(t5); r = L._row("x5"); r["filled_at"] -= 30; L._save(r)
    cycle(ea, 3)
    r5 = L._row("x5")
    assert r5["state"] == "closed" and r5["paper_r"] == 0.3 and r5["pnl"] == 9.0, r5
    print("ok  exits: broker stop recorded; Sentinel's timeout closes the position")

    # bridge availability: minutes seen / observed, gaps, unobserved server time
    L._avail = None; S._meta_set(L.AVAIL_KEY, None)
    t0 = 1_800_000_000 - (1_800_000_000 % 86400) + 3600          # 01:00 UTC on a fixed day
    for i in range(0, 600, 3): L.avail_sample(True, t0 + i)                    # 10 min online
    for i in range(600, 1500, 3): L.avail_sample(False, t0 + i)                # 15 min offline
    for i in range(1500, 1800, 3): L.avail_sample(True, t0 + i)                # 5 min online
    for i in range(1800, 1830, 3): L.avail_sample(False, t0 + i)               # 30 s blip
    for i in range(1830, 2400, 3): L.avail_sample(True, t0 + i)                # 9.5 min online
    a = L.avail_report(t0 + 2400)
    assert a["state"] == "online" and a["today"]["obs"] == 39 and a["today"]["seen"] == 24, a["today"]     # minutes 0-38 closed; 39 still open
    assert a["today"]["pct"] == 61.5 and a["today"]["unobserved"] == 62, a["today"]       # 00:00-01:00 had no recorder: unobserved, not offline
    assert len(a["gaps"]) == 1 and a["gaps"][0]["minutes"] == 15 and a["gaps"][0]["end"] is not None, a["gaps"]
    L._avail = None                                                               # reloads from the database
    for i in range(2400, 2700, 3): L.avail_sample(False, t0 + i)                 # a gap still open
    a = L.avail_report(t0 + 2700)
    assert a["state"] == "offline" and a["gaps"][0]["end"] is None and a["gaps"][0]["minutes"] == 5 and a["d7"]["obs"] == 44, a
    st = c.get("/api/sentinel/live", headers=OWNER).json()["availability"]
    assert st["offline_skips"] == 0 and st["gap_min_s"] == 120 and st["state"] in ("offline", "online"), st
    print("ok  bridge availability: minutes seen/observed per day, gaps >= 2 min kept, 30 s blip ignored, server downtime unobserved")

    m = c.get("/api/sentinel/live", headers=OWNER).json()["metrics"]
    assert m["taken"] == 4 and m["closed"] == 2 and m["skipped"] >= 3 and m["risk_within_limit"] == "4/4", m
    assert m["stop_moves_ok"] == "2/2" and m["manual_interventions"] == 0 and m["total_r"] > 0, m
    assert "minimum lot above 1%" in m["skip_reasons"], m
    if os.environ.get("LIVE_DUMP"):
        json.dump(c.get("/api/sentinel/live", headers=OWNER).json(), open(os.environ["LIVE_DUMP"], "w"))
    lost_answers(ea)
    assert c.post("/api/sentinel/live", json={"action": "stop"}, headers=OWNER).status_code == 200
    assert L.on_open(trade("x7")) is None
    print("ok  metrics and stop:", {k: m[k] for k in ("taken", "skipped", "total_r", "avg_slippage_r", "risk_within_limit")})
    print("all Sentinel live-test checks passed")


def lost_answers(ea):
    """MT5 executed, but its answer never reached the relay (restart, results
    ring overrun). The position must not be forgotten, and a close must not
    wait forever on an answer that is not coming."""
    for r in L.rows():                                       # clear the book: x6 and x9 are still open
        if r["state"] in ("sent", "open"):
            r["state"] = "closed"; r["closed_at"] = time.time(); r["pnl"] = 0; L._save(r)
    ea.fill_px = 2650.2
    ea.positions["77"] = {"ticket": "77", "symbol": "XAUUSD", "side": "buy", "volume": 0.03, "entry": 2600.0, "price": 2600.0,
                          "sl": 2590.0, "tp": 0, "profit": 0, "time": int(time.time()) - 3600}        # someone's older trade: never ours
    ea.sync()
    row = L.on_open(trade("y1", tf="1h"))
    assert row["state"] == "sent" and "77" in row["tickets_before"], row
    ea.sync()                                                  # the EA fills it ...
    ea.results = []                                            # ... and the answer is lost
    L.tick()
    r = L._row("y1"); assert r["state"] == "sent", r
    r["at"] -= 61; L._save(r)                                  # a minute passes
    cycle(ea)
    r = L._row("y1")
    assert r["state"] == "open" and r["adopted"] and r["ticket"] != "77" and r["fill"] == 2650.2 and r["risk_now"] == 30.6, r
    # the same order, with no fill anywhere: given up, not invented
    ea.positions.pop(r["ticket"])
    ea.deals.append({"kind": "trade", "ticket": r["ticket"], "exit": 2651.0, "profit": 2.4, "reason": "Manual", "time": time.time()})
    r["filled_at"] -= 30; L._save(r); cycle(ea)
    assert L._row("y1")["state"] == "closed"
    row = L.on_open(trade("y2", tf="4h")); ea.sync(); ea.results = []
    ea.positions.pop(str(ea.next_ticket - 1))                  # the fill is gone before we look
    r = L._row("y2"); r["at"] -= 61; L._save(r); cycle(ea)
    assert L._row("y2")["state"] == "rejected" and "no matching position" in L._row("y2")["reason"], L._row("y2")
    # a close whose answer was lost is sent again after a minute
    L.on_open(trade("y3", market="frxNAS100", entry=20000, sl=19950)); ea.fill_px = 20000.0; cycle(ea)
    r = L._row("y3"); assert r["state"] == "open", r
    t3 = trade("y3", market="frxNAS100", entry=20000, sl=19950); t3.status, t3.r = "timeout", 0.1
    real_answer = ea.answer
    def swallow(cmd):
        if cmd["type"] == "close":
            ea.cmds.append(cmd); return                       # executed? no — the EA never saw it
        real_answer(cmd)
    ea.answer = swallow
    L.on_update(t3); r = L._row("y3"); r["filled_at"] -= 30; L._save(r)
    cycle(ea)
    r = L._row("y3"); assert r.get("close_cmd") and ea.positions.get(r["ticket"]), r
    sent = len([x for x in ea.cmds if x["type"] == "close"])
    cycle(ea)                                                   # within the minute: no second close
    assert len([x for x in ea.cmds if x["type"] == "close"]) == sent
    r["close_tried"] -= 61; L._save(r); ea.answer = real_answer; ea.close_pnl = 1.0
    cycle(ea, 5)                                                # drop the lost command, resend, EA fills, deal seen
    r = L._row("y3")
    assert r["state"] == "closed" and r["pnl"] == 1.0 and len([x for x in ea.cmds if x["type"] == "close"]) == sent + 1, r
    print("ok  lost MT5 answers: a fill is adopted from the snapshot, never invented; a close is retried after a minute")


if __name__ == "__main__":
    main()
