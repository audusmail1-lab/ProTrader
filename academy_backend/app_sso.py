"""Sign in to the PROTrader app with an Academy account.

One account per person: the Academy is where accounts live, and the app
(app.protraderacademy.company) never stores passwords. The flow is the
standard authorization-code flow with PKCE:

  1. The app sends the browser to  GET /app-login?state=S&challenge=C
     (C = base64url(sha256(verifier)); the app keeps the verifier).
  2. If the person is signed in to the Academy, a one-time code (2 minutes,
     single use) is issued and the browser goes back to
     <ACADEMY_APP_URL>/auth/academy/callback?code=..&state=S.
     If not, a small sign-in page is shown first; it uses the normal
     /api/login, then continues.
  3. The app's server calls  POST /api/app-exchange {code, verifier}
     and receives the account's id, name, email, role, status and
     verification. A stolen code is useless without the verifier.

The app decides what each account may do (accepted, verified students and
the instructor get a saved workspace; everyone else can use it as a guest).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit

CODE_TTL = 120
TOKEN = re.compile(r'^[A-Za-z0-9_-]{16,128}$')

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Sign in to PROTrader · Pro Trader Academy</title><link rel="icon" href="/favicon.svg">
<style>
:root{color-scheme:dark;--bg:#0b1016;--panel:#121a23;--line:#243140;--ink:#e8edf3;--mute:#93a1b1;--accent:#e0a54a;--bad:#ef7a7a}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;padding:24px 16px}
main{width:min(420px,100%);display:grid;gap:18px}.tag{font:600 12px/1.3 ui-monospace,Menlo,monospace;letter-spacing:.1em;color:var(--accent)}
h1{margin:0;font-size:28px;line-height:1.15}p{margin:0;color:var(--mute)}form{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;display:grid;gap:12px}
label{display:grid;gap:6px;font-size:14px;color:var(--mute)}input{font:inherit;color:var(--ink);background:#0d141b;border:1px solid var(--line);border-radius:8px;padding:11px 12px;min-height:44px}
input:focus-visible,button:focus-visible,a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
button{font:600 16px inherit;min-height:46px;border:0;border-radius:8px;background:var(--accent);color:#1b1206;cursor:pointer}button[disabled]{opacity:.6}
.status{min-height:1.4em;font-size:14px;color:var(--bad)}.links{display:flex;gap:16px;flex-wrap:wrap;font-size:14px}a{color:var(--ink)}
</style></head><body><main>
<div class="tag">PRO TRADER ACADEMY · PROTRADER APP</div>
<h1>Sign in to PROTrader</h1>
<p>Use your Academy email and password. Your PROTrader workspace follows this account on every device and browser.</p>
<form id="f" novalidate>
<label>Email address<input name="email" type="email" autocomplete="email" maxlength="254" required></label>
<label>Password<input name="password" type="password" autocomplete="current-password" maxlength="128" required></label>
<div class="status" role="status" id="s"></div>
<button type="submit" id="b">Sign in and continue</button>
</form>
<div class="links"><a href="/classroom#forgot">Forgot password?</a><a href="/classroom#enroll">Apply to the Academy</a></div>
</main><script src="/app-login.js"></script></body></html>"""


def initialize(db) -> None:
    db.execute('CREATE TABLE IF NOT EXISTS app_codes(code TEXT PRIMARY KEY,user_id INTEGER NOT NULL,'
               'challenge TEXT NOT NULL,expires REAL NOT NULL)')


def challenge_of(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()


def _redirect(handler, target: str) -> None:
    handler.send_response(302)
    handler.send_header('Location', target)
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Referrer-Policy', 'no-referrer')
    handler.send_header('Content-Length', '0')
    handler.end_headers()


def login_get(handler) -> None:
    """GET /app-login — issue a code for a signed-in account, or ask it to sign in."""
    app = handler.app
    q = parse_qs(urlsplit(handler.path).query)
    state = (q.get('state') or [''])[0]
    challenge = (q.get('challenge') or [''])[0]
    fresh = (q.get('prompt') or [''])[0] == 'login'     # "Add another account": always ask
    if not app.app_url:
        raise handler.api_error(503, 'The PROTrader app address is not configured.')
    if not TOKEN.fullmatch(state) or not TOKEN.fullmatch(challenge):
        raise handler.api_error(400, 'This sign-in link is incomplete. Start again from the PROTrader app.')
    try:
        user = handler.user()
    except handler.api_error:
        user = None
    if not user or fresh:
        page = PAGE if not fresh else PAGE.replace('<h1>Sign in to PROTrader</h1>', '<h1>Add another account</h1>').replace(
            'Use your Academy email and password.', 'Sign in with the other Academy account you want to add to PROTrader.')
        return handler.output(page, content_type='text/html; charset=utf-8')
    raw = secrets.token_urlsafe(32)
    with app.db() as db:
        db.execute('DELETE FROM app_codes WHERE expires<?', (time.time(),))
        db.execute('INSERT INTO app_codes VALUES(?,?,?,?)', (app.digest(raw), user['id'], challenge, time.time() + CODE_TTL))
    return _redirect(handler, app.app_url.rstrip('/') + '/auth/academy/callback?' + urlencode({'code': raw, 'state': state}))


def exchange_post(handler) -> None:
    """POST /api/app-exchange — the app's server trades a code (+ verifier) for the account."""
    app, err = handler.app, handler.api_error
    if app.limited('app-exchange:' + handler.client_address[0], 60, 900):
        raise err(429, 'Too many sign-in attempts. Wait a few minutes.')
    if handler.headers.get_content_type() != 'application/json':
        raise err(415, 'Use a JSON request.')
    try:
        size = int(handler.headers.get('Content-Length', '0'))
    except ValueError:
        raise err(400, 'Invalid request size.')
    if not 1 <= size <= 2000:
        raise err(413, 'The request is too large or empty.')
    try:
        data = json.loads(handler.rfile.read(size))
    except (ValueError, UnicodeDecodeError):
        raise err(400, 'Invalid request.')
    code, verifier = str(data.get('code', '')), str(data.get('verifier', ''))
    if not TOKEN.fullmatch(code) or not TOKEN.fullmatch(verifier):
        raise err(400, 'Invalid sign-in code.')
    with app.db() as db:                    # claim and burn the code in its own transaction:
        db.execute('BEGIN IMMEDIATE')       # it is single use even when the verifier is wrong
        row = db.execute('SELECT * FROM app_codes WHERE code=?', (app.digest(code),)).fetchone()
        if row:
            db.execute('DELETE FROM app_codes WHERE code=?', (row['code'],))
    if not row or row['expires'] < time.time() or not hmac.compare_digest(row['challenge'], challenge_of(verifier)):
        raise err(400, 'This sign-in code is invalid or expired. Start again from the PROTrader app.')
    with app.db() as db:
        user = db.execute('SELECT * FROM users WHERE id=?', (row['user_id'],)).fetchone()
    if not user:
        raise err(400, 'This account no longer exists.')
    return handler.output({'user': handler.safe_user(dict(user))})
