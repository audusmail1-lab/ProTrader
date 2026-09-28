"""Paper-book scoring rules for Sentinel.   python3 tests/test_sentinel_book.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import sentinel_core as core


def trade(dir_="buy", entry=100.0, sl_dist=2.0, cost_r=0.1):
    s = 1 if dir_ == "buy" else -1
    return core.Trade(id="t", market="frxXAUUSD", tf="15m", mode="real", tier="exec", dir=dir_,
                      opened_at=900, entry=entry, sl=entry - s * sl_dist, tp1=entry + s * sl_dist * 1.5,
                      tp2=entry + s * sl_dist * 2.5, sl_dist=sl_dist, cost_r=cost_r, score=8, gates=[True] * 9,
                      mcc="TREND_UP", wyckoff="MARKUP", pattern=None, rsi=60, last_bar=0)


def bar(t, o, h, l, c):
    return {"time": t, "open": o, "high": h, "low": l, "close": c}


def book_with(t):
    b = core.PaperBook()
    b.open[(t.market, t.tf)] = t
    return b


def test_target_win_net_of_cost():
    t = trade(); b = book_with(t)
    b.update(t.market, t.tf, [bar(900, 100, 103, 99, 102), bar(1800, 102, 105.5, 101, 105)])
    assert t.status == "win" and abs(t.r - (2.5 - 0.1)) < 1e-9 and t.tp1_hit and t.bars == 2


def test_stop_first_when_both_touched():
    t = trade(); b = book_with(t)
    b.update(t.market, t.tf, [bar(900, 100, 106, 97, 101)])
    assert t.status == "loss" and abs(t.r - (-1.1)) < 1e-9


def test_short_side_and_old_bars_ignored():
    t = trade("sell"); t.last_bar = 900; b = book_with(t)
    b.update(t.market, t.tf, [bar(900, 100, 200, 0, 100)])          # already seen: ignored
    assert t.status == "open"
    b.update(t.market, t.tf, [bar(1800, 100, 101, 94.9, 95)])
    assert t.status == "win"


def test_timeout_marks_to_close():
    t = trade(); b = book_with(t)
    bars = [bar(900 * (i + 1), 100, 100.5, 99.5, 100) for i in range(core.MAX_BARS - 1)]
    bars.append(bar(900 * core.MAX_BARS, 100, 101, 99.5, 101))
    b.update(t.market, t.tf, bars)
    assert t.status == "timeout" and abs(t.r - (0.5 - 0.1)) < 1e-9 and (t.market, t.tf) not in b.open


def test_summary_breakeven_math():
    rows = [{"status": "win", "r": 2.5, "cost_r": 0, "closed_at": i} for i in range(30)] + \
           [{"status": "loss", "r": -1.0, "cost_r": 0, "closed_at": 100 + i} for i in range(70)]
    s = core.summarise(rows)
    assert s["n"] == 100 and abs(s["expectancy_r"] - 0.05) < 1e-9 and s["breakeven_win_rate"] == round(1 / 3.5, 4)
    assert s["verdict"].startswith("no proven edge")


def test_trailing_model_matches_research_simulator():
    """The live paper book and the research simulator must score trades identically."""
    import random
    from research_exits import simulate, EXIT_MODELS
    rnd = random.Random(7)
    for trial in range(300):
        d = rnd.choice(["buy", "sell"])
        px, bars = 100.0, [bar(0, 100, 100, 100, 100)]
        for k in range(1, 130):
            o = px; px = max(1.0, px + rnd.gauss(0, 1.2) + (0.15 if d == "buy" else -0.15) * rnd.random())
            bars.append(bar(900 * k, o, max(o, px) + rnd.random(), min(o, px) - rnd.random(), px))
        t = trade(d, entry=100.0, sl_dist=2.0, cost_r=0.0)
        t.model, t.stop, t.last_bar = "7.2c", t.sl, 0
        b = book_with(t)
        b.update(t.market, t.tf, bars[1:])
        want, _ = simulate(bars, 0, d, 100.0, 2.0, EXIT_MODELS["trail_1R"])
        assert t.status != "open", trial
        assert abs(t.r - want) < 1e-4, (trial, t.r, want)   # r is stored to 4 dp


def test_management_stages():
    base = dict(cost_r=0.05, model="7.2c")
    assert core.stage_of({**base, "status": "loss", "r": -1.05}) == "Full loser"
    assert core.stage_of({**base, "status": "win", "r": 0.95, "protected_at": 1}) == "Managed winner"
    assert core.stage_of({**base, "status": "loss", "r": -0.05, "protected_at": 1}) == "Protected flat"
    assert core.stage_of({**base, "status": "timeout", "r": 0.3}) == "Time exit"
    assert core.stage_of({"status": "win", "r": 2.45, "cost_r": 0.05, "model": "fixed"}) == "Full winner"
    m = core.management_stats([
        {**base, "status": "win", "r": 1.95, "protected_at": 1, "mfe_r": 3.0, "locked_r": 2.0},
        {**base, "status": "loss", "r": -0.05, "protected_at": 1, "mfe_r": 1.2, "locked_r": 0.0},
        {**base, "status": "loss", "r": -1.05, "mfe_r": 0.4}])
    assert m["stages"]["Managed winner"] == 1 and m["stages"]["Protected flat"] == 1 and m["stages"]["Full loser"] == 1
    assert abs(m["risk_free_pct"] - 2 / 3) < 1e-3 and m["risk_free_positive_pct"] == 0.5
    assert abs(m["capture_pct"] - 2.0 / 3.0) < 1e-3


def test_trailing_records_protection():
    t = trade("buy", entry=100.0, sl_dist=2.0, cost_r=0.0)
    t.model, t.stop = "7.2c", t.sl
    b = book_with(t)
    b.update(t.market, t.tf, [bar(900, 100, 102.5, 99.5, 102), bar(1800, 102, 104, 101.5, 103.5), bar(2700, 103.5, 103.6, 101, 101)])
    assert t.protected_at == 900 + 900        # +1.25R on the first bar moves the stop to +0.25R
    assert t.status == "win" and abs(t.r - 1.0) < 1e-9 and abs(t.locked_r - 1.0) < 1e-9
    assert core.stage_of(t.to_dict()) == "Managed winner"


def test_shadow_rules_run_beside_the_model_and_outlive_it():
    t = trade()                      # buy 100, stop 98, 1R = 2
    t.model = "7.2c"; t.stop = t.sl
    t.shadow = core.shadow_init(t.entry, t.sl, [bar(0, 100, 100.4, 99.6, 100), bar(0, 100, 100.3, 99.7, 100)])
    b = book_with(t)
    T = core.shadow_rules()["usd100"]["trig"]
    assert abs(T - 0.271) < 0.001                       # $100 on $36.9k at 1% risk
    seq = [bar(900, 100, 101.0, 99.9, 100.9),          # +0.5R: $100 rule protects and trails
           bar(1800, 100.9, 102.2, 100.9, 102.1),      # +1.1R: 7.2c arms; structure arms
           bar(2700, 102.1, 102.3, 101.5, 101.6),
           bar(3600, 101.6, 101.7, 101.2, 101.3),
           bar(4500, 101.3, 101.4, 101.0, 101.2),      # swing low 101.0 ...
           bar(5400, 101.2, 101.5, 101.3, 101.4),
           bar(6300, 101.4, 101.8, 101.6, 101.7),      # ... confirmed here -> stop 101 - 0.133
           bar(7200, 101.7, 101.8, 100.1, 100.6)]      # drop: 7.2c, $100 and structure all stopped
    for i in range(len(seq)):
        b.update("frxXAUUSD", "15m", seq[:i + 1])
        b.update_shadows("frxXAUUSD", "15m", seq[:i + 1])
    u, st, h = t.shadow["usd100"], t.shadow["structure"], t.shadow["hold"]
    assert u["state"] == "closed" and u["protected_at"] and 0 < u["gross"] < 1.1, u
    assert st["state"] == "closed" and abs(st["gross"] - (101.0 - 0.1 * 2 / 1.5 - 100) / 2) < 1e-3, st
    assert t.status != "open"                           # the model trade closed too
    assert h["state"] == "open" and t.id in b.shadowing  # hold still running after the model closed
    more = seq + [bar(8100, 100.6, 105.2, 100.5, 105.0)]
    b.update_shadows("frxXAUUSD", "15m", more)
    assert h["state"] == "closed" and h["gross"] == 2.5 and t.id not in b.shadowing
    st_ = core.shadow_stats([t.to_dict()])
    assert st_["hold"]["n"] == 1 and st_["usd100"]["n"] == 1 and st_["hold"]["reached_2_5r_pct"] == 1.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
