"""
PROTrader accounts: one person, one account, on every device and browser.

Accounts live in the Academy (protraderacademy.company). The app never
stores a password and never creates an account because it was opened in a
new browser (Telegram's in-app browser, Safari, the installed app...). A
browser without a session is a guest: it works as before, on that device
only, and is labelled "not saved".

Sign-in ("Sign in with Pro Trader Academy"), OAuth-style code flow + PKCE:
  GET  /auth/academy/start      -> Academy /app-login?state=..&challenge=..
  GET  /auth/academy/callback   <- code + state; the server exchanges the code
                                   (with its verifier) at the Academy, then
                                   opens a session for the canonical user.
Who gets a saved workspace: the instructor, and students whose application
is accepted and whose email is verified. Anyone else stays a guest.

The workspace (paper account, trade-management journal, auto-protect,
favourites, drawings) is stored here per user, so it is the same wherever
the person signs in. Other endpoints:
  GET  /api/account/me              who is signed in (or null)
  POST /api/account/logout
  GET  /api/account/workspace       every stored document with its version
  PUT  /api/account/workspace/{key} {data, version}: optimistic concurrency,
                                    409 + the current copy on a stale version
  POST /api/account/handoff         single-use 60 s link that signs another
  GET  /auth/handoff?code=..        browser on this device into the same
                                    account ("Open in Safari" from Telegram)

The instructor's account is also the Sentinel owner (see user_from_request),
so the owner key no longer has to be typed on each device.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

log = logging.getLogger("accounts")
router = APIRouter()

HERE = os.path.dirname(os.path.abspath(__file__))
ACADEMY_URL = os.getenv("ACADEMY_URL", "https://protraderacademy.company").rstrip("/")
# Server-to-server exchange. The branded Academy address sits behind
# Cloudflare; if that ever refuses a server request, the Render address is
# tried (the code only counts once it reaches the Academy).
ACADEMY_API_URLS = [u.rstrip("/") for u in os.getenv("ACADEMY_API_URLS", f"{ACADEMY_URL},https://protrader-academy.onrender.com").split(",") if u.strip()]
# The Academy sends people back to this one address, so sign-in starts there
# (the state cookie must be on the same host as the callback).
APP_URL = os.getenv("APP_URL", "https://app.protraderacademy.company").rstrip("/")
SESSION_COOKIE, STATE_COOKIE = "pt_session", "pt_signin"
MORE_COOKIE = "pt_more"          # other accounts signed in on this browser (switcher)
MAX_ACCOUNTS = 5                 # per browser, including the active one
SESSION_DAYS = 30
WORKSPACE_KEYS = {"trade", "mgmt", "autoprotect", "favorites", "drawings", "mt5bridge"}
DOC_MAX = 1_500_000
TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


def _db_path() -> str:
    want = os.getenv("ACCOUNTS_DB", "").strip()
    if not want and os.path.ismount("/var/data"):
        want = "/var/data/accounts.db"
    return want or os.path.join(HERE, "accounts.db")


DB_PATH = _db_path()
_lock = threading.Lock()


@contextmanager
def _db():
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


def init() -> None:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    with _db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY, name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'student', status TEXT NOT NULL DEFAULT 'pending',
            verified INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, last_seen REAL);
        -- one row per verified identity; (provider, subject) belongs to exactly one user
        CREATE TABLE IF NOT EXISTS identities(
            provider TEXT NOT NULL, subject TEXT NOT NULL, user_id INTEGER NOT NULL,
            created REAL NOT NULL, PRIMARY KEY(provider, subject));
        CREATE TABLE IF NOT EXISTS sessions(
            token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created REAL NOT NULL,
            expires REAL NOT NULL, agent TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS pending(
            state TEXT PRIMARY KEY, verifier TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS handoffs(
            code TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires REAL NOT NULL);
        -- a Telegram account linked to a PROTrader account: one each way
        CREATE TABLE IF NOT EXISTS telegram(
            tg_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL UNIQUE, username TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL DEFAULT '', chat_id TEXT NOT NULL, linked REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS tg_links(
            code TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(
            user_id INTEGER NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(user_id, key));
        CREATE TABLE IF NOT EXISTS workspace(
            user_id INTEGER NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL,
            version INTEGER NOT NULL, updated REAL NOT NULL, PRIMARY KEY(user_id, key));
        """)
        if "mode" not in {r[1] for r in db.execute("PRAGMA table_info(pending)")}:
            db.execute("ALTER TABLE pending ADD COLUMN mode TEXT NOT NULL DEFAULT ''")


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def _secure(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def allowed(user: dict) -> bool:
    """Saved workspace: the instructor, or an accepted student with a verified email."""
    return user.get("role") == "teacher" or (user.get("status") == "accepted" and bool(user.get("verified")))


def _public(u: sqlite3.Row | dict) -> dict:
    return {"id": u["id"], "name": u["name"], "email": u["email"], "role": u["role"],
            "owner": u["role"] == "teacher"}


# ── sessions ────────────────────────────────────────────────────────────────

def _user_for_token(raw: str) -> Optional[dict]:
    if not raw or not TOKEN.fullmatch(raw):
        return None
    with _db() as db:
        row = db.execute("SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id "
                         "WHERE s.token=? AND s.expires>?", (_digest(raw), time.time())).fetchone()
    return dict(row) if row and allowed(dict(row)) else None


def _more_tokens(request: Request) -> list:
    return [t for t in request.cookies.get(MORE_COOKIE, "").split(".") if TOKEN.fullmatch(t)][:MAX_ACCOUNTS]


def other_accounts(request: Request, active: Optional[dict]) -> list:
    """The other accounts signed in on this browser, as (raw token, user)."""
    out, seen = [], {active["id"]} if active else set()
    for t in _more_tokens(request):
        u = _user_for_token(t)
        if u and u["id"] not in seen:
            seen.add(u["id"]); out.append((t, u))
    return out


def _set_more(response, request: Request, tokens: list) -> None:
    if tokens:
        response.set_cookie(MORE_COOKIE, ".".join(tokens[:MAX_ACCOUNTS - 1]), max_age=SESSION_DAYS * 86400,
                            httponly=True, secure=_secure(request), samesite="lax", path="/")
    else:
        response.delete_cookie(MORE_COOKIE, path="/")


def user_from_request(request: Request) -> Optional[dict]:
    raw = request.cookies.get(SESSION_COOKIE, "")
    if not raw or not TOKEN.fullmatch(raw):
        return None
    now = time.time()
    with _db() as db:
        row = db.execute("SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id "
                         "WHERE s.token=? AND s.expires>?", (_digest(raw), now)).fetchone()
        if not row:
            return None
        if not row["last_seen"] or now - row["last_seen"] > 300:
            db.execute("UPDATE users SET last_seen=? WHERE id=?", (now, row["id"]))
    u = dict(row)
    return u if allowed(u) else None


def _need_user(request: Request) -> dict:
    u = user_from_request(request)
    if not u:
        raise HTTPException(401, "Sign in with your Academy account to use your saved workspace.")
    return u


def _same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin.split("://", 1)[-1] != request.headers.get("host", ""):
        raise HTTPException(403, "This request must come from the PROTrader app.")


def _open_session(response, request: Request, user_id: int) -> None:
    """Sign this browser in as user_id. An account that was already active
    here stays signed in behind it, for the account switcher."""
    active = user_from_request(request)
    keep = [t for t, u in other_accounts(request, active) if u["id"] != user_id]
    if active and active["id"] != user_id:
        keep.insert(0, request.cookies.get(SESSION_COOKIE, ""))
    _set_more(response, request, keep)
    raw = secrets.token_urlsafe(32)
    now = time.time()
    with _db() as db:
        db.execute("DELETE FROM sessions WHERE expires<?", (now,))
        db.execute("INSERT INTO sessions VALUES(?,?,?,?,?)",
                   (_digest(raw), user_id, now, now + SESSION_DAYS * 86400,
                    (request.headers.get("user-agent") or "")[:200]))
    response.set_cookie(SESSION_COOKIE, raw, max_age=SESSION_DAYS * 86400, httponly=True,
                        secure=_secure(request), samesite="lax", path="/")


# ── Academy sign-in ─────────────────────────────────────────────────────────

@router.get("/auth/academy/start")
def academy_start(request: Request, add: int = 0):
    """add=1: "Add another account" — the Academy asks for a sign-in even when
    someone is already signed in there, and this browser keeps both."""
    host = request.headers.get("host", "")
    if host.endswith(".onrender.com") and APP_URL:
        return RedirectResponse(f"{APP_URL}/auth/academy/start" + ("?add=1" if add else ""), 302)
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    with _db() as db:
        db.execute("DELETE FROM pending WHERE created<?", (time.time() - 900,))
        db.execute("INSERT INTO pending(state, verifier, created, mode) VALUES(?,?,?,?)",
                   (state, verifier, time.time(), "add" if add else ""))
    q = {"state": state, "challenge": _challenge(verifier)}
    if add:
        q["prompt"] = "login"
    resp = RedirectResponse(f"{ACADEMY_URL}/app-login?" + urlencode(q), 302)
    resp.set_cookie(STATE_COOKIE, state, max_age=900, httponly=True, secure=_secure(request), samesite="lax", path="/auth")
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _exchange(code: str, verifier: str) -> dict:
    last = "no Academy address configured"
    for base in ACADEMY_API_URLS:
        try:
            r = requests.post(f"{base}/api/app-exchange", json={"code": code, "verifier": verifier}, timeout=15,
                              headers={"User-Agent": "PROTrader-App/1.0 (+https://app.protraderacademy.company)"})
        except requests.RequestException as e:
            last = f"{base}: {e}"; continue
        is_json = r.headers.get("content-type", "").startswith("application/json")
        if r.status_code == 200 and is_json:
            return r.json()["user"]
        if is_json:                              # the Academy answered: the code is spent either way
            raise ValueError(r.json().get("error") or f"status {r.status_code}")
        last = f"{base}: status {r.status_code}"  # blocked before reaching the Academy: try the next address
    raise ValueError(last)


def upsert_academy_user(acad: dict) -> dict:
    """The Academy account is the identity; map it to the one canonical user."""
    subject = str(int(acad["id"]))
    now = time.time()
    with _lock, _db() as db:
        row = db.execute("SELECT user_id FROM identities WHERE provider='academy' AND subject=?", (subject,)).fetchone()
        if row:
            uid = row["user_id"]
            db.execute("UPDATE users SET name=?, email=?, role=?, status=?, verified=? WHERE id=?",
                       (acad.get("name", ""), acad.get("email", ""), acad.get("role", "student"),
                        acad.get("status", "pending"), int(bool(acad.get("verified"))), uid))
        else:
            uid = db.execute("INSERT INTO users(name,email,role,status,verified,created) VALUES(?,?,?,?,?,?)",
                             (acad.get("name", ""), acad.get("email", ""), acad.get("role", "student"),
                              acad.get("status", "pending"), int(bool(acad.get("verified"))), now)).lastrowid
            db.execute("INSERT INTO identities VALUES('academy',?,?,?)", (subject, uid, now))
        return dict(db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())


@router.get("/auth/academy/callback")
def academy_callback(request: Request, code: str = "", state: str = ""):
    back = lambda reason: RedirectResponse(f"/?signin={reason}", 302)
    cookie_state = request.cookies.get(STATE_COOKIE, "")
    if not (TOKEN.fullmatch(code) and TOKEN.fullmatch(state)) or state != cookie_state:
        return back("expired")
    with _db() as db:
        row = db.execute("SELECT verifier, created FROM pending WHERE state=?", (state,)).fetchone()
        db.execute("DELETE FROM pending WHERE state=?", (state,))
    if not row or time.time() - row["created"] > 900:
        return back("expired")
    try:
        user = upsert_academy_user(_exchange(code, row["verifier"]))
    except Exception as e:                      # Academy down, bad code...: stay a guest, say why
        log.warning("academy exchange failed: %s", e)
        return back("failed")
    if not allowed(user):
        resp = back("pending" if user.get("status") != "accepted" else "unverified")
    else:
        resp = RedirectResponse("/?signin=ok", 302)
        _open_session(resp, request, user["id"])
    resp.delete_cookie(STATE_COOKIE, path="/auth")
    return resp


# ── account API ─────────────────────────────────────────────────────────────

@router.get("/api/account/me")
def me(request: Request) -> dict:
    u = user_from_request(request)
    return {"user": _public(u) if u else None, "academy": ACADEMY_URL,
            "others": [_public(o) for _, o in other_accounts(request, u)],
            "telegram": telegram_of(u["id"]) if u else None,
            "telegramBot": _bot_username() is not None}


@router.post("/api/account/switch")
async def switch(request: Request):
    """Make another account that is signed in on this browser the active one."""
    _same_origin(request)
    try:
        want = int((await request.json()).get("id"))
    except Exception:
        raise HTTPException(400, "Send {id}")
    active = user_from_request(request)
    others = other_accounts(request, active)
    hit = next((t for t, u in others if u["id"] == want), None)
    if not hit:
        raise HTTPException(404, "That account is not signed in on this browser. Add it first.")
    rest = [t for t, u in others if u["id"] != want]
    if active:
        rest.insert(0, request.cookies.get(SESSION_COOKIE, ""))
    resp = JSONResponse({"ok": True, "user": _public(_user_for_token(hit))})
    resp.set_cookie(SESSION_COOKIE, hit, max_age=SESSION_DAYS * 86400, httponly=True,
                    secure=_secure(request), samesite="lax", path="/")
    _set_more(resp, request, rest)
    return resp


@router.post("/api/account/logout")
def logout(request: Request):
    """Sign the active account out of this browser. If another account is
    signed in here too, it becomes the active one."""
    _same_origin(request)
    raw = request.cookies.get(SESSION_COOKIE, "")
    active = user_from_request(request)
    others = other_accounts(request, active)
    if raw:
        with _db() as db:
            db.execute("DELETE FROM sessions WHERE token=?", (_digest(raw),))
    nxt = others[0] if others else None
    resp = JSONResponse({"ok": True, "next": _public(nxt[1]) if nxt else None})
    if nxt:
        resp.set_cookie(SESSION_COOKIE, nxt[0], max_age=SESSION_DAYS * 86400, httponly=True,
                        secure=_secure(request), samesite="lax", path="/")
        _set_more(resp, request, [t for t, _ in others[1:]])
    else:
        resp.delete_cookie(SESSION_COOKIE, path="/")
        resp.delete_cookie(MORE_COOKIE, path="/")
    return resp


@router.get("/api/account/workspace")
def workspace_get(request: Request) -> dict:
    u = _need_user(request)
    with _db() as db:
        rows = db.execute("SELECT key, data, version, updated FROM workspace WHERE user_id=?", (u["id"],)).fetchall()
    return {"docs": {r["key"]: {"data": json.loads(r["data"]), "version": r["version"], "updated": r["updated"]} for r in rows}}


@router.put("/api/account/workspace/{key}")
async def workspace_put(key: str, request: Request):
    _same_origin(request)
    u = _need_user(request)
    if key not in WORKSPACE_KEYS:
        raise HTTPException(404, "Unknown workspace document")
    raw = await request.body()
    if len(raw) > DOC_MAX:
        raise HTTPException(413, "This document is too large to save")
    try:
        body = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "Send JSON")
    if not isinstance(body, dict) or "data" not in body or not isinstance(body.get("version"), int):
        raise HTTPException(400, "Send {data, version}")
    blob = json.dumps(body["data"], separators=(",", ":"))
    now = time.time()
    with _lock, _db() as db:
        cur = db.execute("SELECT data, version, updated FROM workspace WHERE user_id=? AND key=?", (u["id"], key)).fetchone()
        have = cur["version"] if cur else 0
        if body["version"] != have:              # someone saved in between (another device)
            return JSONResponse({"error": "stale", "current": {"data": json.loads(cur["data"]) if cur else None,
                                 "version": have, "updated": cur["updated"] if cur else None}}, 409)
        db.execute("INSERT INTO workspace VALUES(?,?,?,?,?) ON CONFLICT(user_id,key) DO UPDATE SET "
                   "data=excluded.data, version=excluded.version, updated=excluded.updated",
                   (u["id"], key, blob, have + 1, now))
    return {"ok": True, "version": have + 1, "updated": now}


def _handoff(user_id: int, ttl: int) -> str:
    raw = secrets.token_urlsafe(32)
    with _db() as db:
        db.execute("DELETE FROM handoffs WHERE expires<?", (time.time(),))
        db.execute("INSERT INTO handoffs VALUES(?,?,?)", (_digest(raw), user_id, time.time() + ttl))
    return "/auth/handoff?" + urlencode({"code": raw})


@router.post("/api/account/handoff")
def handoff_create(request: Request) -> dict:
    _same_origin(request)
    u = _need_user(request)
    return {"path": _handoff(u["id"], 60), "expires_in": 60}


@router.get("/auth/handoff")
def handoff_use(request: Request, code: str = ""):
    if not TOKEN.fullmatch(code):
        return RedirectResponse("/?signin=expired", 302)
    with _lock, _db() as db:
        row = db.execute("SELECT user_id, expires FROM handoffs WHERE code=?", (_digest(code),)).fetchone()
        db.execute("DELETE FROM handoffs WHERE code=?", (_digest(code),))
    if not row or row["expires"] < time.time():
        return RedirectResponse("/?signin=expired", 302)
    resp = RedirectResponse("/?signin=ok", 302)
    _open_session(resp, request, row["user_id"])
    return resp


# ── account settings (notifications) ────────────────────────────────────────

def get_setting(user_id: int, key: str) -> dict:
    with _db() as db:
        row = db.execute("SELECT data FROM settings WHERE user_id=? AND key=?", (user_id, key)).fetchone()
    try:
        return json.loads(row["data"]) if row else {}
    except ValueError:
        return {}


def put_setting(user_id: int, key: str, data: dict) -> None:
    with _db() as db:
        db.execute("INSERT INTO settings VALUES(?,?,?) ON CONFLICT(user_id,key) DO UPDATE SET data=excluded.data",
                   (user_id, key, json.dumps(data, separators=(",", ":"))))


# ── Telegram linked to the account ──────────────────────────────────────────
# Linking: the signed-in account asks for a one-time code, opens the bot with
# it (t.me/<bot>?start=<code>), and the bot's /start proves which Telegram
# account pressed it. After that, the bot can hand that Telegram account a
# signed-in link to the app, the Mini App signs in by itself, and trade
# notifications go to that chat for every device of the account.

LINK_TTL = 600
LOGIN_TTL = 300
TG_CODE = re.compile(r"^L[A-Za-z0-9_-]{16,40}$")


def _tg_token() -> str:
    try:
        import notify
        return notify.TG_TOKEN
    except Exception:
        return re.sub(r"\s+", "", os.environ.get("TELEGRAM_BOT_TOKEN", ""))


def _bot_username() -> Optional[str]:
    try:
        import notify
        return notify._bot_username()
    except Exception:
        return None


def telegram_of(user_id: int) -> Optional[dict]:
    with _db() as db:
        row = db.execute("SELECT username, name, chat_id, linked FROM telegram WHERE user_id=?", (user_id,)).fetchone()
    return {"username": row["username"], "name": row["name"], "linked": row["linked"]} if row else None


def telegram_chat(user_id: int) -> Optional[str]:
    with _db() as db:
        row = db.execute("SELECT chat_id FROM telegram WHERE user_id=?", (user_id,)).fetchone()
    return row["chat_id"] if row else None


def telegram_user(tg_id: Any) -> Optional[dict]:
    with _db() as db:
        row = db.execute("SELECT u.* FROM users u JOIN telegram t ON t.user_id=u.id WHERE t.tg_id=?", (str(tg_id),)).fetchone()
    return dict(row) if row and allowed(dict(row)) else None


@router.post("/api/account/telegram/link")
def telegram_link(request: Request) -> dict:
    _same_origin(request)
    u = _need_user(request)
    bot = _bot_username()
    if not bot:
        raise HTTPException(503, "Telegram is not configured on the server yet.")
    raw = "L" + secrets.token_urlsafe(18)
    with _db() as db:
        db.execute("DELETE FROM tg_links WHERE expires<? OR user_id=?", (time.time(), u["id"]))
        db.execute("INSERT INTO tg_links VALUES(?,?,?)", (_digest(raw), u["id"], time.time() + LINK_TTL))
    return {"url": f"https://t.me/{bot}?start={raw}", "expires_in": LINK_TTL}


@router.post("/api/account/telegram/unlink")
def telegram_unlink(request: Request) -> dict:
    _same_origin(request)
    u = _need_user(request)
    with _db() as db:
        db.execute("DELETE FROM telegram WHERE user_id=?", (u["id"],))
        db.execute("DELETE FROM identities WHERE provider='telegram' AND user_id=?", (u["id"],))
    return {"ok": True}


def telegram_start(code: str, tg_id: Any, chat_id: Any, username: str = "", name: str = "") -> tuple:
    """The bot received /start <code>. Returns (title, body) to reply with."""
    if not TG_CODE.fullmatch(code or ""):
        return ("PROTrader", "That link is not valid. In PROTrader open Account → Link Telegram and try again.")
    with _lock, _db() as db:
        row = db.execute("SELECT user_id, expires FROM tg_links WHERE code=?", (_digest(code),)).fetchone()
        db.execute("DELETE FROM tg_links WHERE code=?", (_digest(code),))
        if not row or row["expires"] < time.time():
            return ("PROTrader", "That link has expired. In PROTrader open Account → Link Telegram for a new one.")
        uid = row["user_id"]
        other = db.execute("SELECT user_id FROM telegram WHERE tg_id=?", (str(tg_id),)).fetchone()
        if other and other["user_id"] != uid:
            return ("Already linked", "This Telegram account is linked to a different PROTrader account. "
                    "Unlink it there first (Account → Unlink Telegram), then try again.")
        db.execute("DELETE FROM telegram WHERE user_id=? OR tg_id=?", (uid, str(tg_id)))
        db.execute("INSERT INTO telegram VALUES(?,?,?,?,?,?)",
                   (str(tg_id), uid, (username or "")[:64], (name or "")[:80], str(chat_id), time.time()))
        db.execute("DELETE FROM identities WHERE provider='telegram' AND (user_id=? OR subject=?)", (uid, str(tg_id)))
        db.execute("INSERT INTO identities VALUES('telegram',?,?,?)", (str(tg_id), uid, time.time()))
        who = db.execute("SELECT name, email FROM users WHERE id=?", (uid,)).fetchone()
    return ("Telegram linked to PROTrader",
            f"This Telegram is now linked to {who['name'] or who['email']}. Your fills, stops and targets "
            "come here, and /app opens PROTrader already signed in.")


def telegram_login_path(tg_id: Any) -> Optional[str]:
    """A signed-in link for the app, for the Telegram account the bot is talking to."""
    u = telegram_user(tg_id)
    return _handoff(u["id"], LOGIN_TTL) if u else None


def verify_webapp(init_data: str, token: str, max_age: int = 86400) -> Optional[dict]:
    """Telegram Mini App initData, checked as Telegram documents it."""
    import hmac as _hmac
    from urllib.parse import parse_qsl
    if not init_data or not token or len(init_data) > 4096:
        return None
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    given = pairs.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = _hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    want = _hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not given or not _hmac.compare_digest(want, given):
        return None
    try:
        if time.time() - int(pairs.get("auth_date", "0")) > max_age:
            return None
        return json.loads(pairs.get("user") or "null")
    except ValueError:
        return None


@router.post("/auth/telegram/webapp")
async def telegram_webapp(request: Request):
    """Opened as a Telegram Mini App: sign in as the account this Telegram is
    linked to. An unlinked Telegram never creates an account."""
    _same_origin(request)
    try:
        init_data = str((await request.json()).get("initData") or "")
    except Exception:
        raise HTTPException(400, "Send {initData}")
    tg = verify_webapp(init_data, _tg_token())
    if not tg or not tg.get("id"):
        raise HTTPException(401, "Telegram sign-in could not be verified.")
    u = telegram_user(tg["id"])
    if not u:
        return JSONResponse({"linked": False}, 404)
    resp = JSONResponse({"ok": True, "user": _public(u)})
    active = user_from_request(request)
    if not active or active["id"] != u["id"]:
        _open_session(resp, request, u["id"])
    return resp


init()
