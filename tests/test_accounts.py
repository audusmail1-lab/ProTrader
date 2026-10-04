"""One account per person across browsers.   python3 tests/test_accounts.py"""
import os, sys, tempfile, time
from urllib.parse import parse_qs, urlsplit

os.environ["ACCOUNTS_DB"] = os.path.join(tempfile.mkdtemp(), "accounts.db")
os.environ["SENTINEL_ENABLED"] = "0"
os.environ["SENTINEL_DB"] = os.path.join(tempfile.mkdtemp(), "s.db")
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


def test_logout_and_instructor_is_sentinel_owner(monkeypatch):
    # sentinel reads the owner key from the environment on every request; set it
    # here, not at import, so another test module's key cannot win when pytest
    # imports every module before running any test
    monkeypatch.setenv("SENTINEL_ADMIN_KEY", "k" * 32)
    t, s = browser(), browser()
    sign_in(t, TEACHER); sign_in(s, STUDENT)
    assert t.get("/api/account/me").json()["user"]["owner"] is True
    assert t.get("/owner-only", headers={"x-sentinel-key": "session"}).status_code == 200
    assert s.get("/owner-only", headers={"x-sentinel-key": "session"}).status_code == 403
    assert browser().get("/owner-only", headers={"x-sentinel-key": "k" * 32}).status_code == 200  # key still works
    assert t.post("/api/account/logout", headers={"Origin": HOST}).status_code == 200
    assert t.get("/api/account/me").json()["user"] is None
    assert t.get("/owner-only", headers={"x-sentinel-key": "session"}).status_code == 403


def test_switcher_keeps_several_accounts_on_one_browser():
    c = browser()
    sign_in(c, dict(STUDENT, id=20, email="one@example.com", name="One"))
    r = c.get("/auth/academy/start?add=1")
    assert "prompt=login" in r.headers["location"]                                  # the Academy must ask again
    sign_in(c, dict(TEACHER, id=21, email="two@example.com", name="Two"))
    me = c.get("/api/account/me").json()
    assert me["user"]["email"] == "two@example.com" and [o["email"] for o in me["others"]] == ["one@example.com"]
    uid_one = me["others"][0]["id"]
    assert c.post("/api/account/switch", json={"id": 999999}, headers={"Origin": HOST}).status_code == 404
    assert c.post("/api/account/switch", json={"id": uid_one}, headers={"Origin": HOST}).status_code == 200
    me = c.get("/api/account/me").json()
    assert me["user"]["email"] == "one@example.com" and [o["email"] for o in me["others"]] == ["two@example.com"]
    nxt = c.post("/api/account/logout", headers={"Origin": HOST}).json()["next"]
    assert nxt["email"] == "two@example.com" and c.get("/api/account/me").json()["user"]["email"] == "two@example.com"
    assert c.post("/api/account/logout", headers={"Origin": HOST}).json()["next"] is None
    assert c.get("/api/account/me").json()["user"] is None
    with accounts._db() as db:                                                       # still one account per person
        assert db.execute("SELECT COUNT(*) FROM users WHERE email IN ('one@example.com','two@example.com')").fetchone()[0] == 2


def test_telegram_is_linked_only_after_telegram_proves_it():
    accounts._bot_username = lambda: "pt_bot"
    a, b = browser(), browser()
    sign_in(a, dict(STUDENT, id=30, email="tg1@example.com")); sign_in(b, dict(STUDENT, id=31, email="tg2@example.com"))
    url = a.post("/api/account/telegram/link", headers={"Origin": HOST}).json()["url"]
    code = url.split("start=")[1]
    assert url.startswith("https://t.me/pt_bot?start=L")
    assert a.get("/api/account/me").json()["telegram"] is None                     # nothing until the bot sees /start
    title, _ = accounts.telegram_start(code, 555, 555, "ada_tg", "Ada")
    assert title == "Telegram linked to PROTrader"
    assert accounts.telegram_start(code, 555, 555)[0] == "PROTrader"                 # single use
    assert a.get("/api/account/me").json()["telegram"]["username"] == "ada_tg"
    # the same Telegram cannot be taken over by another account
    code_b = b.post("/api/account/telegram/link", headers={"Origin": HOST}).json()["url"].split("start=")[1]
    assert accounts.telegram_start(code_b, 555, 555)[0] == "Already linked"
    assert b.get("/api/account/me").json()["telegram"] is None
    # /app in the bot: a signed-in link for this Telegram's account only
    fresh = browser()
    assert fresh.get(accounts.telegram_login_path(555)).headers["location"] == "/?signin=ok"
    assert fresh.get("/api/account/me").json()["user"]["email"] == "tg1@example.com"
    assert accounts.telegram_login_path(777) is None                                 # unlinked: no account made
    assert a.post("/api/account/telegram/unlink", headers={"Origin": HOST}).status_code == 200
    assert accounts.telegram_login_path(555) is None


def test_telegram_mini_app_signs_in_the_linked_account():
    import hashlib, hmac, json as _j
    from urllib.parse import urlencode
    token = "123:ABC"
    accounts._tg_token = lambda: token
    a = browser(); sign_in(a, dict(STUDENT, id=40, email="mini@example.com"))
    accounts._bot_username = lambda: "pt_bot"
    code = a.post("/api/account/telegram/link", headers={"Origin": HOST}).json()["url"].split("start=")[1]
    accounts.telegram_start(code, 4242, 4242, "mini")

    def init(uid, auth=None):
        f = {"auth_date": str(int(auth or time.time())), "query_id": "q1", "user": _j.dumps({"id": uid, "first_name": "M"})}
        check = "\n".join(f"{k}={v}" for k, v in sorted(f.items()))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        f["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        return urlencode(f)
    c = browser()
    r = c.post("/auth/telegram/webapp", json={"initData": init(4242)}, headers={"Origin": HOST})
    assert r.status_code == 200 and c.get("/api/account/me").json()["user"]["email"] == "mini@example.com"
    bad = init(4242).replace("first_name%22%3A+%22M", "first_name%22%3A+%22X")
    assert browser().post("/auth/telegram/webapp", json={"initData": bad}, headers={"Origin": HOST}).status_code == 401
    assert browser().post("/auth/telegram/webapp", json={"initData": init(4242, time.time() - 3 * 86400)}, headers={"Origin": HOST}).status_code == 401
    assert browser().post("/auth/telegram/webapp", json={"initData": init(9999)}, headers={"Origin": HOST}).status_code == 404


def test_notifications_and_mt5_bridge_follow_the_account():
    import notify
    napp = FastAPI(); napp.include_router(notify.router); napp.include_router(accounts.router)
    sent = []
    notify._send_tg = lambda chat, title, body, button=None: sent.append((chat, title)) or True
    notify._save = lambda: None
    accounts._bot_username = lambda: "pt_bot"
    phone, laptop = (TestClient(napp, base_url=HOST, follow_redirects=False) for _ in range(2))
    for c in (phone, laptop):
        sign_in(c, dict(STUDENT, id=50, email="n@example.com"))
    code = phone.post("/api/account/telegram/link", headers={"Origin": HOST}).json()["url"].split("start=")[1]
    accounts.telegram_start(code, 6060, 6060, "n_tg")
    st = phone.post("/api/notify/register", json={"device": "phone0001", "prefs": {"tp": False}}).json()
    assert st["account"] and st["tg"] and st["prefs"] == {"tp": False}
    st = laptop.post("/api/notify/register", json={"device": "laptop001"}).json()   # the other device sees the same
    assert st["tg"] and st["prefs"] == {"tp": False} and st["tgUser"] == "n_tg"
    ev = {"type": "sl", "account": "paper", "id": "p1", "symbol": "R_75", "side": "buy", "volume": 1, "price": 1, "pnl": -5}
    phone.post("/api/notify/event", json={"device": "phone0001", "event": ev})
    laptop.post("/api/notify/event", json={"device": "laptop001", "event": ev})
    notify.flush_outbox()                                                            # messages go out on the sender thread
    assert sent == [("6060", "R_75 · Stop loss hit")]                                # once per person, not per device
    laptop.post("/api/notify/event", json={"device": "laptop001", "event": dict(ev, type="tp", id="p2")})
    notify.flush_outbox()
    assert len(sent) == 1                                                            # take-profit muted on the account
    guest = TestClient(napp, base_url=HOST).post("/api/notify/register", json={"device": "guest0001", "prefs": {"sl": False}}).json()
    assert guest["account"] is False and guest["prefs"] == {"sl": False}
    # the MT5 bridge settings are a synced workspace document
    r = put(phone, "mt5bridge", {"key": "k" * 32, "shown": True, "symMap": {}}, 0)
    assert r.status_code == 200
    assert laptop.get("/api/account/workspace").json()["docs"]["mt5bridge"]["data"]["shown"] is True


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); n += 1; print("ok", name)
    print(n, "passed")
