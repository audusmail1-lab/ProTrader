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
SESSION_DAYS = 30
WORKSPACE_KEYS = {"trade", "mgmt", "autoprotect", "favorites", "drawings"}
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
        CREATE TABLE IF NOT EXISTS workspace(
            user_id INTEGER NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL,
            version INTEGER NOT NULL, updated REAL NOT NULL, PRIMARY KEY(user_id, key));
        """)


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
def academy_start(request: Request):
    host = request.headers.get("host", "")
    if host.endswith(".onrender.com") and APP_URL:
        return RedirectResponse(f"{APP_URL}/auth/academy/start", 302)
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    with _db() as db:
        db.execute("DELETE FROM pending WHERE created<?", (time.time() - 900,))
        db.execute("INSERT INTO pending VALUES(?,?,?)", (state, verifier, time.time()))
    resp = RedirectResponse(f"{ACADEMY_URL}/app-login?" + urlencode({"state": state, "challenge": _challenge(verifier)}), 302)
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
    return {"user": _public(u) if u else None, "academy": ACADEMY_URL}


@router.post("/api/account/logout")
def logout(request: Request):
    _same_origin(request)
    raw = request.cookies.get(SESSION_COOKIE, "")
    if raw:
        with _db() as db:
            db.execute("DELETE FROM sessions WHERE token=?", (_digest(raw),))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
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


@router.post("/api/account/handoff")
def handoff_create(request: Request) -> dict:
    _same_origin(request)
    u = _need_user(request)
    raw = secrets.token_urlsafe(32)
    with _db() as db:
        db.execute("DELETE FROM handoffs WHERE expires<?", (time.time(),))
        db.execute("INSERT INTO handoffs VALUES(?,?,?)", (_digest(raw), u["id"], time.time() + 60))
    return {"path": "/auth/handoff?" + urlencode({"code": raw}), "expires_in": 60}


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


init()
