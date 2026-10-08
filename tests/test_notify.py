"""GET /api/notify/status must be read-only.   python3 tests/test_notify.py

Before the fix, status() called _device(device) with its create=True default,
so any GET with a made-up device id (no auth required, just an id matching
_DEVICE_RE) inserted a new device row. Once _state["devices"] hit MAX_DEVICES,
each further fake GET evicted the oldest-touched *real* device, silently
dropping that person's push subscription / linked Telegram chat.
"""
import os, sys, tempfile

os.environ["ACCOUNTS_DB"] = os.path.join(tempfile.mkdtemp(), "accounts.db")
os.environ["SENTINEL_ENABLED"] = "0"
os.environ["SENTINEL_DB"] = os.path.join(tempfile.mkdtemp(), "s.db")
os.environ["SENTINEL_ADMIN_KEY"] = "k" * 32
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient

import notify

HOST = "http://testserver"


def app():
    a = FastAPI()
    a.include_router(notify.router)
    return a


def test_status_of_unknown_device_is_404_and_creates_nothing():
    notify._save = lambda: None
    c = TestClient(app(), base_url=HOST)
    before = len(notify._state["devices"])
    r = c.get("/api/notify/status", params={"device": "neverregistered1"})
    assert r.status_code == 404
    assert len(notify._state["devices"]) == before                # nothing inserted
    assert "neverregistered1" not in notify._state["devices"]


def test_status_polling_cannot_evict_real_devices():
    notify._save = lambda: None
    notify._state["devices"].clear()
    real_max = notify.MAX_DEVICES
    notify.MAX_DEVICES = 3                                         # small table, easy to fill
    try:
        c = TestClient(app(), base_url=HOST)
        c.post("/api/notify/register", json={"device": "real0001"})
        c.post("/api/notify/register", json={"device": "real0002"})
        assert set(notify._state["devices"]) == {"real0001", "real0002"}

        # An attacker (or a stray client) GETs /status for a pile of ids that
        # were never registered — more than MAX_DEVICES of them.
        for i in range(10):
            r = c.get("/api/notify/status", params={"device": f"fakedevice{i:03d}"})
            assert r.status_code == 404

        # The real devices must both still be there.
        assert set(notify._state["devices"]) == {"real0001", "real0002"}
        assert c.get("/api/notify/status", params={"device": "real0001"}).status_code == 200
        assert c.get("/api/notify/status", params={"device": "real0002"}).status_code == 200
    finally:
        notify.MAX_DEVICES = real_max


def test_status_of_registered_device_still_works():
    notify._save = lambda: None
    notify._state["devices"].clear()
    c = TestClient(app(), base_url=HOST)
    c.post("/api/notify/register", json={"device": "phone0001", "prefs": {"tp": False}})
    r = c.get("/api/notify/status", params={"device": "phone0001"})
    assert r.status_code == 200
    assert r.json()["prefs"] == {"tp": False}


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); n += 1; print("ok", name)
    print(n, "passed")
