"""
Research loop and lab: causal data, trade counting, cost accounting, version
isolation, evaluation gates, restart recovery, rollback.

    python3 -m pytest -q tests/test_sentinel_research.py
"""
import json
import math
import os
import random
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import sentinel_core as core      # noqa: E402
import research_lab as lab        # noqa: E402
import sentinel_research as sr    # noqa: E402


# ── fixtures ─────────────────────────────────────────────────────────────────

def bar(t, o, h, l, c):
    return {"time": t, "open": o, "high": h, "low": l, "close": c}


def walk(n, seed=1, start=100.0, drift=0.0, vol=0.4, t0=1_700_000_100, step=900):
    rng = random.Random(seed)
    out, px = [], start
    for i in range(n):
        o = px
        c = o + drift + rng.gauss(0, vol)
        h = max(o, c) + abs(rng.gauss(0, vol / 2))
        l = min(o, c) - abs(rng.gauss(0, vol / 2))
        out.append(bar(t0 + i * step, o, h, l, c))
        px = c
    return out


class FakeLive:
    def __init__(self, rows):
        self._rows = rows

    def rows(self, limit=500):
        return self._rows


class FakeSentinel:
    """What sentinel_research needs from the scanner module, and nothing else."""
    DB_PATH = "/nonexistent/sentinel.db"

    def __init__(self, trades=None, live_rows=None):
        self.trades = trades or []
        self._live = FakeLive(live_rows) if live_rows is not None else None
        self._state = {"running": True, "last_cycle": time.time()}
        self.sent = []

    def _load_trades(self, where="", args=(), limit=5000):
        return list(self.trades)

    def _meta_get(self, k, default=None):
        return default

    def _focus(self):
        return [{"id": "frxXAUUSD", "tfs": ["15m", "1h"]}]

    def _telegram(self, text):
        self.sent.append(text)

    def _check_key(self, request):
        pass


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINEL_RESEARCH_DB", str(tmp_path / "r.db"))
    sr._books.clear()
    sr._state.update(last_integrity=None, cycles=0)
    fake = FakeSentinel()
    sr.attach(fake)
    yield fake
    sr._books.clear()


def trade_from(d):
    """A core.Trade from a resolved() dict (fills the fields the dict leaves out)."""
    base = dict(mode="real", tier="exec", dir="buy", entry=100.0, sl=98.0, tp1=103.0, tp2=105.0, sl_dist=2.0, score=8,
                gates=[True] * 10, mcc="", wyckoff="", pattern=None, rsi=None)
    base.update({k: v for k, v in d.items() if k in core.Trade.__dataclass_fields__})
    return core.Trade(**base)


def resolved(i, r, opened, market="frxXAUUSD", tf="15m", trend="up", cost=0.05, mfe=None, status=None, bars=4):
    return {"id": f"{market}-{tf}-{opened}-{i}", "market": market, "tf": tf, "status": status or ("win" if r > 0 else "loss"),
            "opened_at": opened, "closed_at": opened + bars * 900, "r": r, "cost_r": cost, "trend_4h": trend,
            "mfe_r": mfe if mfe is not None else max(0.0, r + cost), "mae_r": 0.3, "engine": core.eng.ENGINE_VERSION,
            "model": core.SENTINEL_MODEL}


# ── lab: gates and indicators ────────────────────────────────────────────────

def test_session_windows_including_midnight_wrap():
    W = {"frxNAS100": [[13.5, 20.0]], "frxXAUUSD": [[22.0, 2.0]]}
    at = lambda h, m=0: int(time.mktime(time.gmtime(0))) + h * 3600 + m * 60    # epoch at UTC h:m on day 0
    at = lambda h, m=0: h * 3600 + m * 60
    assert lab.session_ok(W, "frxNAS100", at(13, 30)) and not lab.session_ok(W, "frxNAS100", at(13, 29))
    assert lab.session_ok(W, "frxNAS100", at(19, 59)) and not lab.session_ok(W, "frxNAS100", at(20, 0))
    assert lab.session_ok(W, "frxXAUUSD", at(23)) and lab.session_ok(W, "frxXAUUSD", at(1)) and not lab.session_ok(W, "frxXAUUSD", at(12))
    assert lab.session_ok(W, "cryBTCUSD", at(3))           # no window = control, always open
    assert lab.session_ok(None, "frxNAS100", at(3))


def test_adx_high_in_a_trend_low_in_noise():
    trend = walk(300, seed=3, drift=0.5, vol=0.2)
    noise = walk(300, seed=4, drift=0.0, vol=0.5)
    a_t, pdi, mdi = lab.adx(trend, 14)
    a_n, _, _ = lab.adx(noise, 14)
    assert a_t[-1] > 40 and pdi[-1] > mdi[-1]
    assert a_n[-1] < a_t[-1]
    assert lab.adx(trend[:20], 14)[0][-1] is None          # not enough bars → no reading, never a guess


def test_acf1_sign():
    up = [100 + i + (0.3 if i % 2 else -0.3) for i in range(200)]           # alternating → negative autocorrelation
    assert lab.acf1(up, 100) < 0
    smooth = [100 * math.exp(0.001 * i + 0.0005 * math.sin(i / 7)) for i in range(200)]
    assert lab.acf1(smooth, 100) > 0
    assert lab.acf1([100.0] * 10, 100) is None


def test_rules_identity_and_validation():
    a = lab.rules_id({"gates": {"cost_cap": 0.08}})
    assert a == lab.rules_id({"gates": {"cost_cap": 0.08}, "entry": "aria"})      # defaults do not change identity
    assert a != lab.rules_id({"gates": {"cost_cap": 0.09}})
    with pytest.raises(ValueError):
        lab.normalize({"bogus": 1})
    with pytest.raises(ValueError):
        lab.normalize({"gates": {"magic": 1}})
    with pytest.raises(ValueError):
        lab.normalize({"model": "7.9"})


# ── lab: causal replay and parity ────────────────────────────────────────────

def test_research_book_without_gates_matches_paper_book():
    bars = walk(1400, seed=11, drift=0.05, vol=0.6)
    h4 = [bar(b["time"], b["open"], b["high"], b["low"], b["close"]) for b in walk(400, seed=12, drift=0.3, vol=1.0, step=14400)]
    m = core.MARKET_BY_ID["frxXAUUSD"]
    import sentinel_replay as rp
    a = rp.replay_series(m, "15m", bars, h4)
    b = lab.replay_slice({}, m, "15m", bars, h4)
    reads = lab.reads_for(m, "15m", bars)
    c = lab.replay_slice({}, m, "15m", bars, h4, reads)
    strip = lambda ts: [{k: v for k, v in t.items() if k not in ("shadow", "_research")} for t in ts]
    assert strip(a) == strip(b) == strip(c)
    assert all(t["opened_at"] % 900 == 0 for t in b)


def test_reads_never_look_ahead():
    """ARIA's read of bar i must not change when later bars change."""
    bars = walk(700, seed=21, drift=0.05, vol=0.6)
    m = core.MARKET_BY_ID["frxXAUUSD"]
    r1 = lab.reads_for(m, "15m", bars)
    altered = bars[:650] + [bar(b["time"], b["open"] * 1.1, b["high"] * 1.1, b["low"] * 1.1, b["close"] * 1.1) for b in bars[650:]]
    r2 = lab.reads_for(m, "15m", altered)
    for i in range(core.WINDOW - 1, 650):
        assert r1[i] == r2[i]


def test_session_gate_blocks_outside_window_and_records_reason():
    bars = walk(1400, seed=11, drift=0.05, vol=0.6)
    h4 = walk(400, seed=12, drift=0.3, vol=1.0, step=14400)
    m = core.MARKET_BY_ID["frxXAUUSD"]
    base = lab.replay_slice({}, m, "15m", bars, h4)
    assert base, "fixture must produce trades"
    hour = lambda t: time.gmtime(t["opened_at"]).tm_hour
    # a window that excludes the hour of the first base trade
    h0 = hour(base[0])
    W = {"frxXAUUSD": [[(h0 + 2) % 24, (h0 + 3) % 24]]}
    gated = lab.replay_slice({"gates": {"session": W}}, m, "15m", bars, h4)
    assert all(lab.session_ok(W, "frxXAUUSD", t["opened_at"]) for t in gated)
    assert base[0]["id"] not in {t["id"] for t in gated}


# ── lab: exits ───────────────────────────────────────────────────────────────

def mk_trade(dir_="buy", entry=100.0, sl_dist=2.0, cost=0.05):
    s = 1 if dir_ == "buy" else -1
    return core.Trade(id="x", market="frxXAUUSD", tf="15m", mode="real", tier="exec", dir=dir_, opened_at=900,
                      entry=entry, sl=entry - s * sl_dist, tp1=entry + s * 1.5 * sl_dist, tp2=entry + s * 2.5 * sl_dist,
                      sl_dist=sl_dist, cost_r=cost, score=8, gates=[True] * 10, mcc="", wyckoff="", pattern=None, rsi=None,
                      last_bar=0, model="7.2c", stop=entry - s * sl_dist)


def book_with(rules, t, atr=1.0):
    b = lab.ResearchBook(rules)
    b.open[(t.market, t.tf)] = t
    b.meta[t.id] = {"version": b.version, "atr": atr}
    return b


def test_fixed_r_exit_and_stop_first():
    t = mk_trade(); b = book_with({"exit": {"kind": "fixed_r", "r": 2.0}}, t)
    b.update(t.market, t.tf, [bar(900, 100, 103, 99.5, 102), bar(1800, 102, 104.1, 101, 104)])
    assert t.status == "win" and abs(t.r - (2.0 - 0.05)) < 1e-9 and t.exit == 104.0
    t2 = mk_trade(); b2 = book_with({"exit": {"kind": "fixed_r", "r": 2.0}}, t2)
    b2.update(t2.market, t2.tf, [bar(900, 100, 105, 97.9, 101)])          # touches stop and target → stop
    assert t2.status == "loss" and abs(t2.r - (-1.05)) < 1e-9


def test_atr_trail_ratchets_and_never_loosens():
    t = mk_trade(); b = book_with({"exit": {"kind": "atr_trail", "mult": 2.0, "period": 14}}, t, atr=1.0)
    b.update(t.market, t.tf, [bar(900, 100, 106, 99, 105)])              # best 106 → stop 104
    assert abs(t.stop - 104.0) < 1e-9 and t.status == "open"
    b.update(t.market, t.tf, [bar(1800, 105, 105.5, 104.2, 104.5)])      # lower high: stop stays 104
    assert abs(t.stop - 104.0) < 1e-9
    b.update(t.market, t.tf, [bar(2700, 104.5, 104.6, 103.5, 103.8)])    # hits 104 → closed at the stop
    assert t.status == "win" and abs(t.r - (2.0 - 0.05)) < 1e-9
    assert t.protected_at == 1800 and t.locked_r == 2.0


def test_channel_exit_uses_prior_bars_only():
    rules = {"exit": {"kind": "channel", "channel": 3}}
    b = lab.ResearchBook(rules)
    hist = [bar(i * 900, 100, 101, 99 + i * 0.1, 100.5) for i in range(5)]      # lows 99.0..99.4
    b.update("frxXAUUSD", "15m", hist)                                        # no trade: history only
    t = mk_trade(); t.last_bar = hist[-1]["time"]; t.opened_at = t.last_bar + 900
    b.open[(t.market, t.tf)] = t; b.meta[t.id] = {"atr": 1.0}
    # prior-3 low = 99.2; a close at 99.3 does not exit, a close at 99.1 does
    b.update(t.market, t.tf, [bar(5 * 900, 100.5, 101, 99.25, 99.3)])
    assert t.status == "open"
    b.update(t.market, t.tf, [bar(6 * 900, 99.3, 100, 99.1, 99.1)])
    assert t.status == "loss" and abs(t.exit - 99.1) < 1e-9


def test_timeout_closes_at_close():
    t = mk_trade(); b = book_with({"exit": {"kind": "atr_trail", "mult": 5.0, "timeout": 3}}, t, atr=1.0)
    b.update(t.market, t.tf, [bar(900 * i, 100, 100.5, 99.8, 100.2) for i in range(1, 4)])
    assert t.status == "timeout" and t.bars == 3 and abs(t.r - (0.1 - 0.05)) < 1e-9


# ── lab: Donchian challenger ─────────────────────────────────────────────────

def test_donchian_entry_stop_and_trend_filter():
    rules = {"entry": "donchian", "stop": {"kind": "atr", "mult": 2.0, "period": 20}, "exit": {"kind": "fixed_r", "r": 2.0}}
    window = [bar(i * 3600, 100, 101, 99, 100) for i in range(60)]
    window.append(bar(60 * 3600, 100, 102, 99.5, 101.5))               # closes above the prior 20-bar high (101)
    m = core.MARKET_BY_ID["frxXAUUSD"]
    b = lab.ResearchBook(rules)
    read, t = b.consider(m, "1h", window, trend_4h="down")
    assert t is None and read["block"].startswith("4h trend")
    read, t = b.consider(m, "1h", window, trend_4h="up")
    assert t is not None and t.dir == "buy" and t.entry == 101.5 and t.engine == "donchian-1"
    atr = lab.wilder_atr(window[-60:], 20)[-1]
    assert abs(t.sl_dist - 2 * atr) < 1e-9 and t.id == f"frxXAUUSD-1h-{60 * 3600}"
    read2, t2 = b.consider(m, "1h", window, trend_4h="up")
    assert t2 is None                                                    # one position per slice


# ── metrics, costs, placebo ──────────────────────────────────────────────────

def test_cost_multiplier_and_gross():
    ts = [resolved(i, r, 1_700_000_000 + i * 86400, cost=0.1) for i, r in enumerate([1.0, -1.1, 0.5, -1.1, 2.0])]
    m1, m15, m2 = lab.metrics(ts, 1.0, boot=0), lab.metrics(ts, 1.5, boot=0), lab.metrics(ts, 2.0, boot=0)
    assert abs(m15["expectancy_r"] - (m1["expectancy_r"] - 0.05)) < 1e-6
    assert abs(m2["expectancy_r"] - (m1["expectancy_r"] - 0.10)) < 1e-6
    assert abs(m1["gross_expectancy_r"] - (m1["expectancy_r"] + 0.1)) < 1e-6
    assert m1["profit_factor"] == round(3.5 / 2.2, 3) and m1["max_drawdown_r"] == 1.7


def test_placebo_test_distinguishes_a_real_subset_from_noise():
    rng = random.Random(5)
    base = [resolved(i, rng.gauss(0, 1), 1_700_000_000 + i * 3600) for i in range(400)]
    best = sorted(range(400), key=lambda i: -base[i]["r"])[:100]
    cherry = [i in best for i in range(400)]
    rnd = [rng.random() < 0.25 for _ in range(400)]
    p_good = lab.placebo_test(base, cherry, 300)
    p_rand = lab.placebo_test(base, rnd, 300)
    assert p_good["p_net"] == 0.0 and p_good["p_gross"] == 0.0
    assert p_rand["p_net"] > 0.05
    assert lab.placebo_test(base, [True] * 400, 50)["p_net"] is None


# ── registry: counting ───────────────────────────────────────────────────────

def test_counting_excludes_open_duplicate_early_and_unreconciled(registry):
    sr.init()
    v = sr.create_version("c1", {"gates": {"cost_cap": 0.08}}, [["frxXAUUSD", "15m"]], parent_id=None, state="validating")
    sr.transition(v["id"], "paper-testing", "test")
    coh = sr._active_cohort(v["id"])
    start = coh["started_at"]
    book = sr._books[v["id"]]
    rows = [resolved(1, 0.8, start + 900), resolved(2, -1.0, start + 1800), resolved(3, 0.2, start - 90000),
            resolved(4, 0.0, start + 2700, status="open")]
    for d in rows:
        t = trade_from(d)
        sr._save_research_trade(v["id"], coh["id"], book, t)
        sr._save_research_trade(v["id"], coh["id"], book, t)             # saved twice: still one row
    got, excl = sr.resolved_trades(coh)
    assert [t["id"] for t in got] == [rows[0]["id"], rows[1]["id"]]
    assert excl["open"] == 1 and excl["before_cohort"] == 1
    # demo cohort: unreconciled rows never count
    registry._live = FakeLive([
        {"id": "a", "state": "closed", "market": "frxXAUUSD", "tf": "15m", "at": start + 10, "closed_at": start + 100, "fill": 1, "exit": 2, "r": 0.4, "pnl": 10},
        {"id": "b", "state": "closed", "market": "frxXAUUSD", "tf": "15m", "at": start + 20, "closed_at": start + 200, "fill": 1, "exit": None, "r": None, "pnl": None},
        {"id": "c", "state": "open", "market": "frxXAUUSD", "tf": "15m", "at": start + 30},
    ])
    with sr._lock, sr._db() as con:
        con.execute("INSERT INTO cohorts (version_id, evidence_kind, started_at, ended_at, label, trade_filter, created_at) VALUES (?,?,?,?,?,?,?)",
                    (v["id"], "demo", start, None, "demo", json.dumps({}), start))
    demo = next(c for c in sr.list_cohorts() if c["evidence_kind"] == "demo")
    got, excl = sr.resolved_trades(demo)
    assert [t["id"] for t in got] == ["a"] and excl["unreconciled"] == 1 and excl["open"] == 1
    assert got[0]["net_financial"] is True and got[0]["cost_r"] is None


def test_incumbent_cohort_counts_only_the_pinned_model_and_rerun_never_counts(registry):
    start = sr.INCUMBENT_JOURNAL_START
    registry.trades = [resolved(1, 0.5, start + 900), resolved(2, -1.0, start + 1800),
                       {**resolved(3, 1.0, start + 2700), "model": "fixed"},          # another model: not this version
                       {**resolved(4, 1.0, start + 3600), "engine": "7.0"},
                       resolved(5, 1.0, start - 900)]                                 # before the cohort: a re-run over old bars
    sr.init()
    coh = sr.list_cohorts(active_only=True)[0]
    got, excl = sr.resolved_trades(coh)
    assert len(got) == 2 and excl["other_version"] == 2 and excl["before_cohort"] == 1
    # init again (a restart) must not create a second cohort or version
    sr.init()
    assert len(sr.list_cohorts()) == 1 and len(sr.list_versions()) == 1


# ── registry: reviews, gates, restart ────────────────────────────────────────

def make_cohort_with(registry, rs, start=None, trend_cycle=("up", "down")):
    start = start or sr.INCUMBENT_JOURNAL_START
    registry.trades = [resolved(i, r, start + i * 7200, trend=trend_cycle[i % len(trend_cycle)]) for i, r in enumerate(rs)]
    sr.init()
    return sr.list_cohorts(active_only=True)[0]


def test_reviews_at_boundaries_once_and_configurable(registry):
    rng = random.Random(2)
    make_cohort_with(registry, [rng.gauss(0, 1) for _ in range(160)])
    made = sr.run_reviews()
    assert [(r["boundary"], r["kind"]) for r in made] == [(100, "diagnostic"), (150, "formal")]
    assert made[0]["metrics"]["n"] == 100 and made[1]["metrics"]["n"] == 150
    assert sr.run_reviews() == []                                         # same process, nothing new
    sr._state.update(last_integrity=None)                                  # restart: module state gone, DB stays
    assert sr.run_reviews() == []
    # more trades → 300 is next; 100/150 never repeat
    registry.trades += [resolved(200 + i, rng.gauss(0, 1), sr.INCUMBENT_JOURNAL_START + (200 + i) * 7200) for i in range(150)]
    made = sr.run_reviews()
    assert [r["boundary"] for r in made] == [300]
    sr.cfg_set("diagnostic_at", 320, "owner"); sr.cfg_set("formal_every", 50, "owner")
    made = sr.run_reviews()
    assert sorted(r["boundary"] for r in made) == [200, 250]              # 300 is already recorded; 320 diagnostic not yet reached
    assert any("review" in s for s in registry.sent)


def test_classification_rules(registry):
    c = sr.config()
    days = lambda ts: [t for t in ts]
    # eligible: steady positive edge over > 60 days, two regimes, three positive thirds
    rng = random.Random(9)
    ts = [resolved(i, 0.25 + rng.gauss(0, 0.6), sr.INCUMBENT_JOURNAL_START + i * 43200, trend=("up", "down")[i % 2], cost=0.03) for i in range(160)]
    m = sr._review_metrics(ts)
    cls, why = sr.classify(m, ts, "formal", [], c, None, 1)
    assert cls == "eligible", why
    # the same trades at the diagnostic boundary can never be 'eligible'
    cls, _ = sr.classify(m, ts, "diagnostic", [], c, None, 1)
    assert cls == "inconclusive"
    # worse than the incumbent on the matched period → not eligible
    cls, why = sr.classify(m, ts, "formal", [], c, {"n": 100, "expectancy_r": m["expectancy_r"] + 1}, 1)
    assert cls == "inconclusive" and any("incumbent" in w for w in why)
    # more versions under test → higher bar (Bonferroni)
    weak = [resolved(i, 0.08 + rng.gauss(0, 0.6), sr.INCUMBENT_JOURNAL_START + i * 43200, trend=("up", "down")[i % 2], cost=0.03) for i in range(160)]
    mw = sr._review_metrics(weak)
    one, _ = sr.classify(mw, weak, "formal", [], c, None, 1)
    many, _ = sr.classify(mw, weak, "formal", [], c, None, 12)
    assert not (one == "inconclusive" and many == "eligible")
    # underperforming: interval below zero
    bad = [resolved(i, -0.3 + rng.gauss(0, 0.5), sr.INCUMBENT_JOURNAL_START + i * 7200) for i in range(150)]
    cls, why = sr.classify(sr._review_metrics(bad), bad, "formal", [], c, None, 1)
    assert cls == "underperforming"
    # integrity flags win over everything
    cls, why = sr.classify(m, ts, "formal", ["12/150 rows unreconciled"], c, None, 1)
    assert cls == "invalid" and why[0].startswith("integrity")


def test_integrity_acts_before_any_boundary(registry):
    start = sr.INCUMBENT_JOURNAL_START
    registry.trades = [resolved(i, 0.1, start + i * 7200) for i in range(5)]
    sr.init()
    registry._state["last_cycle"] = time.time() - 7200                   # scanner silent for 2 h
    out = sr.run_integrity()
    coh = sr.list_cohorts(active_only=True)[0]
    assert out[coh["id"]]["ok"] is False and "scanner" in out[coh["id"]]["flags"][0]
    assert any("integrity" in s for s in registry.sent)
    registry._state["last_cycle"] = time.time()
    out = sr.run_integrity()
    assert out[coh["id"]]["ok"] is True


def test_diagnosis_names_the_dominant_factor(registry):
    rng = random.Random(4)
    # trades that never travel: entry quality should dominate
    ts = [resolved(i, -1.0 if i % 3 else 0.3, sr.INCUMBENT_JOURNAL_START + i * 7200, mfe=0.2 if i % 3 else 1.0) for i in range(120)]
    m = sr._review_metrics(ts)
    d = sr.diagnose(ts, m)
    assert d["dominant"].startswith("entry quality") and d["factors"]["entry"]["never_reached_0.5R"] > 0.6


# ── registry: versions, transitions, isolation, rollback ─────────────────────

def test_versions_are_immutable_and_isolated(registry):
    sr.init()
    a = sr.create_version("a", {"gates": {"cost_cap": 0.08}}, [["frxXAUUSD", "15m"]])
    b = sr.create_version("a again", {"gates": {"cost_cap": 0.08}}, [["frxXAUUSD", "15m"]])
    c = sr.create_version("a changed", {"gates": {"cost_cap": 0.09}}, [["frxXAUUSD", "15m"]])
    d = sr.create_version("child of a", {"gates": {"cost_cap": 0.08}}, [["frxXAUUSD", "15m"]], parent_id=a["id"])
    assert a["id"] == b["id"] and a["id"] != c["id"] and d["id"] != a["id"] and d["parent_id"] == a["id"]
    assert a["name"] == "a"                                                # the first registration stands
    with pytest.raises(Exception):
        sr.transition(a["id"], "monitoring", "skip ahead")                  # researching → monitoring not allowed
    sr.transition(a["id"], "backtesting", "r1"); sr.transition(a["id"], "validating", "r2")
    sr.transition(a["id"], "paper-testing", "validated", "exp:H2-costcap")
    assert sr._active_cohort(a["id"]) is not None and a["id"] in sr._books
    inc = sr.cfg_get("incumbent_version")
    assert inc != a["id"]
    # challenger trades never touch the scanner's journal
    before = list(registry.trades)
    book = sr._books[a["id"]]
    t = trade_from(resolved(1, 0.4, sr._active_cohort(a["id"])["started_at"] + 900))
    sr._save_research_trade(a["id"], sr._active_cohort(a["id"])["id"], book, t)
    assert registry.trades == before
    got, _ = sr.resolved_trades(sr._active_cohort(a["id"]))
    assert len(got) == 1 and got[0]["_research"]["version"] == book.version


def test_promote_records_decision_and_rollback_restores(registry):
    sr.init()
    inc0 = sr.cfg_get("incumbent_version")
    a = sr.create_version("a", {"gates": {"cost_cap": 0.08}}, [["frxXAUUSD", "15m"]], state="validating")
    sr.transition(a["id"], "paper-testing", "validated")
    out = sr.promote(a["id"], "formal review 150: eligible", "review:1")
    assert out["incumbent_version"] == a["id"] and out["previous"] == inc0 and out["awaiting_release"] is True
    assert sr.get_version(a["id"])["state"] == "monitoring"
    n_coh = len([c for c in sr.list_cohorts() if c["version_id"] == inc0])
    rb = sr.rollback("drawdown after promotion")
    assert rb["incumbent_version"] == inc0 and rb["rollback"] is True
    cohorts = [c for c in sr.list_cohorts() if c["version_id"] == inc0]
    assert len(cohorts) == n_coh + 1 and cohorts[-1]["ended_at"] is None and cohorts[-2]["ended_at"] is not None
    tr = sr.versions()["transitions"]
    assert [t["to"] for t in tr if t["to"] == "incumbent"][-2:] == ["incumbent", "incumbent"]
    assert sr.get_version(inc0)["state"] == "monitoring"
    # a retired version cannot come back
    sr.transition(a["id"], "retired", "done")
    with pytest.raises(Exception):
        sr.transition(a["id"], "paper-testing", "again")


def test_restart_restores_open_challenger_trades(registry):
    sr.init()
    a = sr.create_version("a", {"exit": {"kind": "atr_trail", "mult": 2.0}}, [["frxXAUUSD", "15m"]], state="validating")
    sr.transition(a["id"], "paper-testing", "ok")
    coh = sr._active_cohort(a["id"])
    book = sr._books[a["id"]]
    t = mk_trade(); t.id = "frxXAUUSD-15m-123"; t.opened_at = coh["started_at"] + 900; t.status = "open"
    book.open[(t.market, t.tf)] = t; book.meta[t.id] = {"version": book.version, "atr": 1.25, "gates": {"cost_r": 0.05}}
    sr._save_research_trade(a["id"], coh["id"], book, t)
    sr._books.clear()                                                      # process restart
    sr.init()
    nb = sr._books[a["id"]]
    assert (t.market, t.tf) in nb.open and nb.open[(t.market, t.tf)].id == t.id
    assert nb.meta[t.id]["atr"] == 1.25                                    # the ATR at entry survives, so the trail is unchanged
    # the restored trade is managed by the research exit on the next bars
    nb.update(t.market, t.tf, [bar(coh["started_at"] + 1800, 100, 106, 99, 105)])
    assert abs(nb.open[(t.market, t.tf)].stop - 103.5) < 1e-9


def test_on_bars_judges_each_bar_once_and_persists_watermark(registry):
    import asyncio
    asyncio.run(_on_bars_case(registry))


async def _on_bars_case(registry):
    sr.init()
    a = sr.create_version("a", {"gates": {"cost_cap": 0.5}}, [["frxXAUUSD", "15m"]], state="validating")
    sr.transition(a["id"], "paper-testing", "ok")
    m = core.MARKET_BY_ID["frxXAUUSD"]
    bars = walk(320, seed=11, drift=0.05, vol=0.6, t0=sr._active_cohort(a["id"])["started_at"])
    calls = []

    async def trend():
        calls.append(1)
        return "up"
    await sr.on_bars(m, "15m", bars, True, trend)
    await sr.on_bars(m, "15m", bars, True, trend)                          # same bar: no second judgement
    assert len(calls) == 1
    assert sr.cfg_get(f"eval:{a['id']}:frxXAUUSD 15m", 0) == bars[-1]["time"]
    await sr.on_bars(m, "15m", bars + [bar(bars[-1]["time"] + 900, 100, 101, 99, 100)], True, trend)
    assert len(calls) == 2
