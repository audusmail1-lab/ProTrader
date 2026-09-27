"""Paper-book scoring rules for Sentinel.   python3 tests/test_sentinel_book.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import sentinel_core as core


def trade(dir_="buy", entry=100.0, sl_dist=2.0, cost_r=0.1):
    s = 1 if dir_ == "buy" else -1
    return core.Trade(id="t", market="frxXAUUSD", tf="15m", mode="live-eligible", tier="exec", dir=dir_,
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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
