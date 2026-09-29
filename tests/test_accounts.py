"""One account per person across browsers.   python3 tests/test_accounts.py"""
import os, sys, tempfile, time
from urllib.parse import parse_qs, urlsplit

os.environ["ACCOUNTS_DB"] = os.path.join(tempfile.mkdtemp(), "accounts.db")
os.environ["SENTINEL_ENABLED"] = "0"
os.environ["SENTINEL_DB"] = os.path.join(tempfile.mkdtemp(), "s.db")
os.environ["SENTINEL_ADMIN_KEY"] = "k" * 32
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import accounts
import sentinel

app = FastAPI()
app.include_router(accounts.router)


@app.get("/owner-only")
def owner_only(request: Request):
    sentinel._check_key(request)
    return {"ok": True}


ACADEMY = {}          # code -> academy user; stands in for POST /api/app-exchange
accounts._exchange = lambda code, verifier: ACADEMY.pop(code)
HOST = "http://testserver"


def browser():
    return TestClient(app, base_url=HOST, follow_redirects=False)


def sign_in(c, academy_user):
    r = c.get("/auth/academy/start")
    assert r.status_code == 302 and r.headers["location"].startswith(accounts.ACADEMY_URL + "/app-login?")
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    code = "c" + os.urandom(12).hex()
    ACADEMY[code] = academy_user
    return c.get(f"/auth/academy/callback?code={code}&state={state}")


STUDENT = {"id": 7, "name": "Ada", "email": "ada@example.com", "role": "student", "status": "accepted", "verified": True}
TEACHER = {"id": 1, "name": "Joel", "email": "joel@example.com", "role": "teacher", "status": "accepted", "verified": True}


def put(c, key, data, version):
    return c.put(f"/api/account/workspace/{key}", json={"data": data, "version": version}, headers={"Origin": HOST})


def test_same_person_gets_the_same_account_in_every_browser():
    telegram, safari = browser(), browser()
    assert telegram.get("/api/account/me").json()["user"] is None                  # guest until signed in
    assert sign_in(telegram, STUDENT).headers["location"] == "/?signin=ok"
    assert sign_in(safari, dict(STUDENT, name="Ada L.")).headers["location"] == "/?signin=ok"
    a, b = telegram.get("/api/account/me").json()["user"], safari.get("/api/account/me").json()["user"]
    assert a["id"] == b["id"] and b["name"] == "Ada L." and not a["owner"]
    with accounts._db() as db:
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1          # no account per browser


def test_workspace_follows_the_account_and_stale_writes_conflict():
    telegram, safari = browser(), browser()
    sign_in(telegram, STUDENT); sign_in(safari, STUDENT)
    base = telegram.get("/api/account/workspace").json()["docs"].get("trade", {}).get("version", 0)
    r = put(telegram, "trade", {"balance": 10000, "trades": [1]}, base)
    assert r.status_code == 200 and r.json()["version"] == base + 1
    doc = safari.get("/api/account/workspace").json()["docs"]["trade"]
    assert doc["data"]["trades"] == [1]
    r = put(safari, "trade", {"trades": []}, base)                                  # Safari had not seen it yet
    assert r.status_code == 409 and r.json()["current"]["data"]["trades"] == [1]
    assert put(safari, "trade", {"trades": [1, 2]}, base + 1).status_code == 200
    assert put(safari, "passwords", {}, 0).status_code == 404                       # only the listed documents
    assert safari.put("/api/account/workspace/trade", json={"data": {}, "version": base + 2},
                      headers={"Origin": "https://evil.example"}).status_code == 403


def test_pending_or_unverified_students_stay_guests():
    c = browser()
    assert sign_in(c, dict(STUDENT, id=8, status="pending", verified=False)).headers["location"] == "/?signin=pending"
    assert sign_in(c, dict(STUDENT, id=9, verified=False)).headers["location"] == "/?signin=unverified"
    assert c.get("/api/account/me").json()["user"] is None
    assert c.get("/api/account/workspace").status_code == 401


def test_callback_needs_the_state_this_browser_started():
    a, b = browser(), browser()
    r = a.get("/auth/academy/start")
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    ACADEMY["x" * 20] = STUDENT
    assert b.get(f"/auth/academy/callback?code={'x' * 20}&state={state}").headers["location"] == "/?signin=expired"
    assert b.get("/api/account/me").json()["user"] is None


def test_handoff_link_opens_the_same_account_once():
    telegram, safari = browser(), browser()
    sign_in(telegram, STUDENT)
    path = telegram.post("/api/account/handoff", headers={"Origin": HOST}).json()["path"]
    assert safari.get(path).headers["location"] == "/?signin=ok"
    assert safari.get("/api/account/me").json()["user"]["email"] == "ada@example.com"
    assert browser().get(path).headers["location"] == "/?signin=expired"            # single use


def test_logout_and_instructor_is_sentinel_owner():
    t, s = browser(), browser()
    sign_in(t, TEACHER); sign_in(s, STUDENT)
    assert t.get("/api/account/me").json()["user"]["owner"] is True
    assert t.get("/owner-only", headers={"x-sentinel-key": "session"}).status_code == 200
    assert s.get("/owner-only", headers={"x-sentinel-key": "session"}).status_code == 403
    assert browser().get("/owner-only", headers={"x-sentinel-key": "k" * 32}).status_code == 200  # key still works
    assert t.post("/api/account/logout", headers={"Origin": HOST}).status_code == 200
    assert t.get("/api/account/me").json()["user"] is None
    assert t.get("/owner-only", headers={"x-sentinel-key": "session"}).status_code == 403


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); n += 1; print("ok", name)
    print(n, "passed")
