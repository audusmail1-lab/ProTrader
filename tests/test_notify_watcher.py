"""The server-side paper watcher: a close it makes carries the levels it was
judged on, and a sync that still lists the position with other levels
supersedes that close (the app moved the stop or target after the watcher's
copy was taken — that is not a fill).   python3 -m pytest tests/test_notify_watcher.py -q
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import notify  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

DEV = "d0123456789abcdef0123456"
REAL_DELIVER = notify._deliver                                 # _client() stubs it; one test wants the real one


def _client(tmp_path):
    notify.STATE_PATH = str(tmp_path / "notify.json")
    notify._state = {"devices": {}, "tg_codes": {}}
    notify._deliver = lambda *a, **k: {"sent": False}      # no push, no Telegram in tests
    notify._feed.want = lambda symbols: None
    app = FastAPI(); app.include_router(notify.router)
    return TestClient(app)


def _sync(c, positions):
    r = c.post("/api/notify/paper/sync", json={"device": DEV, "positions": positions})
    assert r.status_code == 200, r.text
    return r.json()


def _pos(sl, tp, side="buy"):
    return {"id": "7", "symbol": "R_75", "label": "Vol 75", "side": side, "volume": 0.2, "entry": 44000,
            "sl": sl, "tp": tp, "unit": 1.0, "dp": 2, "spread": 0}


def test_close_records_the_levels_it_fired_on(tmp_path):
    c = _client(tmp_path)
    assert _sync(c, [_pos(43900, 44100)])["watching"] == 1
    notify._on_tick("R_75", 44105, 44105, 44105)
    closed = notify._state["devices"][DEV]["closed"]
    assert len(closed) == 1 and closed[0]["reason"] == "tp" and closed[0]["price"] == 44105
    assert closed[0]["sl"] == 43900 and closed[0]["tp"] == 44100
    # the app, which moved nothing, syncs the same levels: the close is handed back and it adopts it
    r = _sync(c, [_pos(43900, 44100)])
    assert [x["id"] for x in r["closed"]] == ["7"]


def test_sync_with_newer_levels_supersedes_the_close(tmp_path):
    c = _client(tmp_path)
    _sync(c, [_pos(43900, 44100)])
    notify._on_tick("R_75", 44105, 44105, 44105)                 # judged on tp 44100
    # the trader had dragged the target to 44140 before that tick reached the app
    r = _sync(c, [_pos(43900, 44140)])
    assert r["closed"] == [], r                                   # not a fill
    assert r["watching"] == 1
    assert notify._state["devices"][DEV]["paper"]["7"]["tp"] == 44140   # watched again, on the current level
    # a stop that only trailed does not supersede a close on the target
    notify._on_tick("R_75", 44141, 44141, 44141)
    r = _sync(c, [_pos(44000, 44140)])
    assert [x["id"] for x in r["closed"]] == ["7"] and r["closed"][0]["tp"] == 44140


def test_delivery_leaves_the_lock_before_the_network(tmp_path, monkeypatch):
    """The watcher and the MT5 hook run under locks (notify's, the bridge's):
    a close only queues its message; the sender thread does the network."""
    c = _client(tmp_path)
    monkeypatch.setattr(notify, "_deliver", REAL_DELIVER)
    sent = []
    monkeypatch.setattr(notify, "_send_tg", lambda chat, title, body, button=None: sent.append((chat, title)) or True)
    monkeypatch.setattr(notify, "_send_push", lambda sub, title, body, data: sent.append(("push", title)) or 1)
    monkeypatch.setattr(notify, "_account", lambda d: None)
    while not notify._outbox.empty():
        notify._outbox.get_nowait()
    with notify._lock:
        d = notify._device(DEV)
        d["tg"] = "4242"; d["push"] = {"endpoint": "https://push.example/x"}
        r = notify._deliver(DEV, d, {"type": "tp", "account": "paper", "id": "7", "symbol": "R_75", "label": "Vol 75",
                                      "side": "buy", "volume": 0.2, "price": 44140.0, "pnl": 28.0, "dp": 2}, "paper:7:close")
    assert r["queued"] and r["push"] and r["tg"] and sent == [], r               # nothing sent under the lock
    assert notify._deliver(DEV, d, {"type": "tp"}, "paper:7:close")["dup"] is True
    job = notify._outbox.get_nowait()
    out = notify._send(job)
    assert out["sent"] and sorted(x[0] for x in sent) == ["4242", "push"], (out, sent)
    # a subscription that is gone for good is dropped, under the lock, by the sender
    monkeypatch.setattr(notify, "_send_push", lambda *a: -1)
    notify._send(job)
    assert notify._state["devices"][DEV]["push"] is None
    # "Send a test" sends itself, once the lock is released
    monkeypatch.setattr(notify, "_send_push", lambda sub, title, body, data: 1)
    r = c.post("/api/notify/test", json={"device": DEV})
    assert r.status_code == 200 and r.json()["sent"] is True and r.json()["tg"] is True, r.text


def test_ack_clears_closes(tmp_path):
    c = _client(tmp_path)
    _sync(c, [_pos(43900, 44100)])
    notify._on_tick("R_75", 43890, 43890, 43890)
    r = c.post("/api/notify/paper/ack", json={"device": DEV, "ids": ["7"]})
    assert r.json()["pendingCloses"] == 0
    assert _sync(c, [])["closed"] == []
