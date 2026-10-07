"""Contract book: weekly paper contracts at Deriv's quoted prices.   python3 -m pytest -q tests/test_contract_book.py"""
import asyncio
import datetime as dt
import os
import sys
import tempfile

os.environ["SENTINEL_ENABLED"] = "0"
os.environ.setdefault("SENTINEL_DB", os.path.join(tempfile.mkdtemp(), "cb.db"))
os.environ.setdefault("ACCOUNTS_DB", os.path.join(tempfile.mkdtemp(), "acc.db"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import sentinel as s             # noqa: E402
import contract_book as cb       # noqa: E402

MON_1500 = int(dt.datetime(2026, 10, 12, 15, 0, tzinfo=dt.timezone.utc).timestamp())    # a Monday, US session


def _clear():
    with s._lock, s._db() as con:
        con.execute("DROP TABLE IF EXISTS contract_book")


class FakeDeriv:
    """Answers the three read-only calls the book makes. Records every request: nothing may try to buy."""
    def __init__(self, payout=19.0, entry=100.0, exit_=101.0, closed=False):
        self.payout, self.entry, self.exit, self.closed, self.reqs = payout, entry, exit_, closed, []

    async def __call__(self, req):
        self.reqs.append(req)
        assert "buy" not in req and "sell" not in req
        if "proposal" in req:
            if self.closed:
                return {"error": {"message": "This market is presently closed."}}
            t = MON_1500
            return {"msg_type": "proposal", "proposal": {"payout": self.payout, "spot": 99.5, "spot_time": t - 1, "date_start": t,
                                                          "date_expiry": t + req["duration"] * 86400, "longcode": "Win payout if ..."}}
        if req.get("style") == "ticks" and "start" in req:
            return {"msg_type": "history", "history": {"times": [req["start"], req["start"] + 1], "prices": [self.entry, self.entry + 0.1]}}
        if req.get("style") == "ticks":
            return {"msg_type": "history", "history": {"times": [req["end"] - 5], "prices": [self.exit]}}
        return {"msg_type": "candles", "candles": []}


def test_entry_window_and_one_contract_per_spec_per_week():
    assert len(cb.due(MON_1500, set())) == len(cb.SPECS)
    sat = MON_1500 - 2 * 86400
    assert cb.due(sat, set()) == []                                      # weekend
    assert cb.due(MON_1500 - 3 * 3600, set()) == []                      # before the US session
    taken = {cb.week_key(sp["id"], MON_1500) for sp in cb.SPECS}
    assert cb.due(MON_1500 + 86400, taken) == []                         # Tuesday, same week: already taken
    assert len(cb.due(MON_1500 + 7 * 86400, taken)) == len(cb.SPECS)     # next week: due again


def test_takes_quotes_records_entry_and_never_buys():
    _clear()
    f = FakeDeriv(payout=18.5, entry=100.0)
    out = asyncio.run(cb.run_once(now_s=MON_1500, call=f))
    assert out["opened"] == len(cb.SPECS) and out["entries"] == len(cb.SPECS)
    recs = cb.load_all()
    r = next(x for x in recs if x["spec"] == "ndx-rise-91")
    assert r["payout"] == 18.5 and r["priced_p"] == round(10 / 18.5, 4) and r["entry"] == 100.0 and r["status"] == "open"
    assert r["date_expiry"] == MON_1500 + 91 * 86400
    assert all("proposal" in q or "ticks_history" in q for q in f.reqs)
    assert asyncio.run(cb.run_once(now_s=MON_1500 + 3600, call=f))["opened"] == 0          # same week: nothing new


def test_closed_market_records_nothing():
    _clear()
    f = FakeDeriv(closed=True)
    out = asyncio.run(cb.run_once(now_s=MON_1500, call=f))
    assert out["opened"] == 0 and cb.load_all() == [] and "closed" in cb._state["last_error"]


def test_settles_at_expiry_from_deriv_prices_and_scores():
    _clear()
    asyncio.run(cb.run_once(now_s=MON_1500, call=FakeDeriv(payout=19.0, entry=100.0)))
    later = MON_1500 + 31 * 86400 + 3600
    t = dt.datetime.fromtimestamp(later, dt.timezone.utc)
    assert t.weekday() == 3                                               # a Thursday: the 30-day ones settle, new ones open too
    out = asyncio.run(cb.run_once(now_s=later, call=FakeDeriv(payout=19.0, entry=100.0, exit_=101.0)))
    assert out["settled"] == 2                                            # both 30-day contracts
    recs = {r["key"]: r for r in cb.load_all()}
    r = recs[cb.week_key("ndx-rise-30", MON_1500)]
    assert r["status"] == "won" and r["returned"] == 19.0 and r["net"] == 9.0
    assert recs[cb.week_key("ndx-rise-91", MON_1500)]["status"] == "open"
    st = cb.stats(list(recs.values()))
    sp = st["specs"]["ndx-rise-30"]
    assert sp["settled"] == 1 and sp["wins"] == 1 and sp["roi"] == 0.9 and sp["verdict"].startswith("too few")
    assert sp["edge_on_history"] == round(0.631 / (10 / 19.0) - 1, 3)
    # a fall loses the stake
    lost = cb.settle(dict(r, status="open"), later, 99.0)
    assert lost["status"] == "lost" and lost["returned"] == 0.0 and lost["net"] == -10.0


def test_verdict_needs_twenty_and_two_standard_errors():
    assert cb._verdict(10, 9, [0.5] * 10)[0].startswith("too few")
    assert cb._verdict(40, 32, [0.52] * 40)[0] == "wins more often than Deriv charges for"
    assert cb._verdict(40, 21, [0.52] * 40)[0] == "no difference from Deriv's price yet"
    assert cb._verdict(40, 10, [0.52] * 40)[0] == "Deriv's price is winning"


def test_endpoint(monkeypatch):
    monkeypatch.setenv("SENTINEL_ADMIN_KEY", "k")
    _clear()
    asyncio.run(cb.run_once(now_s=MON_1500, call=FakeDeriv()))

    class Req:
        headers = {"x-sentinel-key": "k"}
    out = s.contracts(Req())
    assert out["version"] == cb.BOOK_VERSION and out["stats"]["taken"] == len(cb.SPECS) and len(out["records"]) == len(cb.SPECS)
    assert set(out["stats"]["specs"]) == {sp["id"] for sp in cb.SPECS}
