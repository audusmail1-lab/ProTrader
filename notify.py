"""
Phone notifications for trade events — Web Push (installed PWA) and Telegram.

What it does
  • Registers a device (a browser profile of the PROTrader app) with its Web
    Push subscription and/or a paired Telegram chat.
  • Sends one notification per trade event: executed, pending order filled,
    stop loss hit, take profit hit, position closed.
  • Watches paper positions server-side: the app uploads its open paper
    positions, this module subscribes to Deriv ticks for those symbols and
    fires the notification the moment a stop or target is crossed — app open
    or not. The close is recorded here and the app reconciles it on its next
    sync, so the paper book never disagrees with what the phone was told.
  • Watches MT5 through the bridge: every EA snapshot is diffed for new
    positions (executed) and new closing deals (stop / target / manual, with
    the broker's own reason and realised P&L).

Configuration (environment)
  VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_SUBJECT   Web Push (generate once:
        python -c "from py_vapid import Vapid; v=Vapid(); v.generate_keys(); ..."
        or `vapid --gen`; the subject is a mailto: or https: URL)
  TELEGRAM_BOT_TOKEN                                    from @BotFather
  NOTIFY_STATE                                          state file path
        (default /var/data/notify.json when that disk is mounted, else ./notify_state.json)

Without the keys the endpoints still answer and the app shows what is missing.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
from collections import deque
from typing import Any, Optional

import requests
from fastapi import APIRouter, HTTPException, Request

log = logging.getLogger("notify")
router = APIRouter(prefix="/api/notify")

def _key_env(name: str, default: str = "") -> str:
    """Keys and tokens contain no whitespace, so any that arrives (a line
    wrapped while copying from a phone, a trailing newline) is dropped."""
    return re.sub(r"\s+", "", os.environ.get(name, default))


VAPID_PUBLIC = _key_env("VAPID_PUBLIC_KEY")
VAPID_PRIVATE = _key_env("VAPID_PRIVATE_KEY")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:support@protraderacademy.company").strip()
TG_TOKEN = _key_env("TELEGRAM_BOT_TOKEN")
DERIV_WS = os.environ.get("DERIV_WS_URL", "wss://ws.derivws.com/websockets/v3?app_id=1089")

_DEVICE_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9._-]{16,128}$")
MAX_DEVICES = 500
SEEN_KEEP = 400          # de-dupe memory per device (event keys)
CLOSED_KEEP = 50         # unacknowledged server-side closes kept per device

try:
    from pywebpush import webpush, WebPushException   # type: ignore
except Exception:                                      # dependency missing → push disabled
    webpush = None
    WebPushException = Exception


def _state_path() -> str:
    p = os.environ.get("NOTIFY_STATE", "").strip()
    if p:
        return p
    if os.path.isdir("/var/data") and os.access("/var/data", os.W_OK):
        return "/var/data/notify.json"
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "notify_state.json")


STATE_PATH = _state_path()
_lock = threading.RLock()
_state: dict = {"devices": {}, "tg_codes": {}}


def _load() -> None:
    global _state
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("devices"), dict):
            _state = {"devices": d["devices"], "tg_codes": d.get("tg_codes") or {}, "acct_seen": d.get("acct_seen") or {}}
    except FileNotFoundError:
        pass
    except Exception as e:                              # a corrupt file must not stop the app
        log.warning("notify state unreadable (%s) — starting empty", e)


def _save() -> None:
    try:
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_state, f)
        os.replace(tmp, STATE_PATH)
    except Exception as e:
        log.warning("notify state not saved: %s", e)


def _device(device_id: str, create: bool = True) -> dict:
    if not _DEVICE_RE.match(device_id or ""):
        raise HTTPException(400, "Malformed device id")
    d = _state["devices"].get(device_id)
    if d is None:
        if not create:
            raise HTTPException(404, "Unknown device")
        if len(_state["devices"]) >= MAX_DEVICES:
            oldest = min(_state["devices"], key=lambda k: _state["devices"][k].get("touched", 0))
            _state["devices"].pop(oldest, None)
        d = _state["devices"][device_id] = {
            "push": None, "tg": None, "bridge": None, "prefs": {},
            "paper": {}, "closed": [], "seen": [], "touched": time.time(),
            "mt5_seen_positions": None, "mt5_last_deal": 0,
        }
    d["touched"] = time.time()
    return d


async def _body(request: Request) -> dict:
    try:
        b = await request.json()
    except Exception:
        raise HTTPException(400, "Body must be JSON")
    if not isinstance(b, dict):
        raise HTTPException(400, "Expected a JSON object")
    return b


# ── message copy ─────────────────────────────────────────────────────────────
def _money(v: Any, ccy: str = "USD") -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    s = f"{abs(v):,.2f}"
    return ("+" if v >= 0 else "−") + s + " " + ccy


def _px(v: Any, dp: Any) -> str:
    try:
        d = int(dp) if dp is not None else 2
        return f"{float(v):,.{d}f}"
    except (TypeError, ValueError):
        return str(v)


def format_event(ev: dict) -> tuple[str, str]:
    """(title, body) in the TradeLocker / MT5 register: symbol and what happened
    in the title, side · size · price · money in the body."""
    sym = ev.get("label") or ev.get("symbol") or "Position"
    side = str(ev.get("side") or "").upper()
    vol = ev.get("volume")
    acct = ev.get("account") or "paper"
    acct_tag = "" if acct == "paper" else f" · {acct}"
    ccy = ev.get("ccy") or "USD"
    dp = ev.get("dp")
    t = ev.get("type")
    if t == "executed":
        title = f"{sym} · {side.title()} {vol} filled"
        parts = [f"at {_px(ev.get('price'), dp)}"]
        if ev.get("sl") is not None: parts.append(f"SL {_px(ev['sl'], dp)}")
        if ev.get("tp") is not None: parts.append(f"TP {_px(ev['tp'], dp)}")
        return title, " · ".join(parts) + acct_tag
    if t == "pending_filled":
        title = f"{sym} · {side.title()} {vol} order filled"
        parts = [f"at {_px(ev.get('price'), dp)}"]
        if ev.get("sl") is not None: parts.append(f"SL {_px(ev['sl'], dp)}")
        if ev.get("tp") is not None: parts.append(f"TP {_px(ev['tp'], dp)}")
        return title, " · ".join(parts) + acct_tag
    if t in ("sl", "tp", "closed", "stopout"):
        what = {"sl": "Stop loss hit", "tp": "Take profit hit", "closed": "Position closed", "stopout": "Stop out"}[t]
        title = f"{sym} · {what}"
        body = f"{side} {vol} closed at {_px(ev.get('price'), dp)} · {_money(ev.get('pnl'), ccy)}"
        return title, body + acct_tag
    if t == "test":
        return "PROTrader notifications are on", "You'll hear about fills, stops and targets here."
    return f"{sym} · {t}", ev.get("body") or ""


# ── delivery ─────────────────────────────────────────────────────────────────
def _send_push(sub: dict, title: str, body: str, data: dict) -> int:
    """1 delivered, 0 failed (try again later), -1 subscription gone for good."""
    if not (webpush and VAPID_PRIVATE and VAPID_PUBLIC):
        return 0
    payload = json.dumps({"title": title, "body": body, "data": data, "tag": data.get("tag")})
    try:
        webpush(subscription_info=sub, data=payload, ttl=600,
                vapid_private_key=VAPID_PRIVATE,
                vapid_claims={"sub": VAPID_SUBJECT},
                headers={"Urgency": "high"})
        return 1
    except WebPushException as e:                       # 404/410 = unsubscribed or expired
        code = getattr(getattr(e, "response", None), "status_code", None)
        log.info("push failed (%s): %s", code, e)
        return -1 if code in (404, 410) else 0
    except Exception as e:
        log.info("push failed: %s", e)
        return 0


def _redact(e: BaseException) -> str:
    """An error's text with the bot token removed — requests quotes the URL."""
    s = f"{type(e).__name__}: {e}"
    return s.replace(TG_TOKEN, "<token>") if TG_TOKEN else s


def _send_tg(chat_id: str, title: str, body: str, button: Optional[tuple] = None) -> bool:
    if not TG_TOKEN or not chat_id:
        return False
    text = f"<b>{_esc(title)}</b>\n{_esc(body)}"
    msg = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if button:
        msg["reply_markup"] = {"inline_keyboard": [[{"text": button[0], "url": button[1]}]]}
    try:
        r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", json=msg, timeout=8)
        return r.ok
    except Exception as e:
        log.info("telegram failed: %s", _redact(e))
        return False


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _account(d: dict) -> Optional[dict]:
    """Settings of the account this device is signed in to: notification
    choices and the linked Telegram chat live on the account, so every device
    of that person shares them. None for a guest device."""
    uid = d.get("user")
    if not uid:
        return None
    try:
        import accounts
        return {"id": uid, "prefs": (accounts.get_setting(uid, "notify").get("prefs") or {}),
                "tg": accounts.telegram_chat(uid), "tgInfo": accounts.telegram_of(uid)}
    except Exception as e:
        log.info("account settings unavailable: %s", e)
        return None


def _account_seen(uid: Any, key: str) -> bool:
    """Telegram goes to the account's chat once per event, however many of
    that person's devices report it."""
    seen = _state.setdefault("acct_seen", {}).setdefault(str(uid), [])
    if key in seen:
        return True
    seen.append(key); del seen[:-SEEN_KEEP]
    return False


def _deliver(device_id: str, d: dict, ev: dict, key: Optional[str] = None) -> dict:
    """Send one event to every channel the device has. `key` de-duplicates:
    the same (device, key) is delivered once, whoever reports it first."""
    if key:
        if key in d["seen"]:
            return {"sent": False, "dup": True}
        d["seen"].append(key)
        del d["seen"][:-SEEN_KEEP]
    acct = _account(d)
    prefs = (acct["prefs"] if acct else d.get("prefs")) or {}
    if ev.get("type") != "test" and prefs.get(ev.get("type", ""), True) is False:
        return {"sent": False, "muted": True}
    title, body = format_event(ev)
    data = {"tag": key or f"{ev.get('type')}-{int(time.time())}", "sym": ev.get("symbol"), "type": ev.get("type")}
    out = {"push": False, "tg": False}
    sub = d.get("push")
    if sub:
        r = _send_push(sub, title, body, data)
        out["push"] = r == 1
        if r == -1:
            d["push"] = None
    if acct:
        if acct["tg"] and (not key or ev.get("type") == "test" or not _account_seen(acct["id"], key)):
            out["tg"] = _send_tg(acct["tg"], title, body)
    elif d.get("tg"):
        out["tg"] = _send_tg(d["tg"], title, body)
    out["sent"] = out["push"] or out["tg"]
    return out


# ── endpoints ────────────────────────────────────────────────────────────────
_tg_username: Optional[str] = None


def _bot_username() -> Optional[str]:
    global _tg_username
    if not TG_TOKEN:
        return None
    if _tg_username is None:
        try:
            r = requests.get(f"https://api.telegram.org/bot{TG_TOKEN}/getMe", timeout=6).json()
            _tg_username = (r.get("result") or {}).get("username") or ""
        except Exception:
            _tg_username = ""
    return _tg_username or None


@router.get("/config")
def config() -> dict:
    return {
        "push": bool(webpush and VAPID_PUBLIC and VAPID_PRIVATE),
        "vapidPublicKey": VAPID_PUBLIC or None,
        "telegram": bool(TG_TOKEN),
        "botUsername": _bot_username(),
        "paperWatch": True,
    }


@router.post("/register")
async def register(request: Request) -> dict:
    """The app calls this on every load and whenever a channel changes. It is
    idempotent, so a redeploy that lost the state file heals itself."""
    b = await _body(request)
    try:
        import accounts
        user = accounts.user_from_request(request)
    except Exception:
        user = None
    with _lock:
        d = _device(str(b.get("device", "")))
        d["user"] = user["id"] if user else None          # this browser's account, if signed in
        if user and isinstance(b.get("prefs"), dict):
            accounts.put_setting(user["id"], "notify", {"prefs": {k: bool(v) for k, v in b["prefs"].items()}})
            b.pop("prefs")
        if "push" in b:
            sub = b["push"]
            d["push"] = sub if isinstance(sub, dict) and sub.get("endpoint") else None
        if "tg" in b:
            d["tg"] = str(b["tg"]) if b["tg"] else None
        if "prefs" in b and isinstance(b["prefs"], dict):
            d["prefs"] = {k: bool(v) for k, v in b["prefs"].items()}
        if "bridgeKey" in b:
            k = str(b["bridgeKey"] or "")
            d["bridge"] = hashlib.sha256(k.encode()).hexdigest() if _KEY_RE.match(k) else None
        _save()
        return _status(d)


def _status(d: dict) -> dict:
    acct = _account(d)
    if acct:
        info = acct["tgInfo"] or {}
        return {"push": bool(d.get("push")), "tg": bool(acct["tg"]), "tgChat": None, "account": True,
                "tgUser": info.get("username") or info.get("name") or None,
                "prefs": acct["prefs"], "bridge": bool(d.get("bridge")),
                "watching": len(d.get("paper") or {}), "pendingCloses": len(d.get("closed") or [])}
    return {"push": bool(d.get("push")), "tg": bool(d.get("tg")), "tgChat": d.get("tg"), "account": False,
            "prefs": d.get("prefs") or {}, "bridge": bool(d.get("bridge")),
            "watching": len(d.get("paper") or {}), "pendingCloses": len(d.get("closed") or [])}


@router.get("/status")
def status(device: str) -> dict:
    with _lock:
        return _status(_device(device))


@router.post("/telegram/code")
async def telegram_code(request: Request) -> dict:
    b = await _body(request)
    if not TG_TOKEN:
        raise HTTPException(503, "Telegram is not configured on the server")
    with _lock:
        d = _device(str(b.get("device", "")))
        code = secrets.token_urlsafe(9).replace("-", "x").replace("_", "y")
        # one live code per device
        for c in [c for c, dev in _state["tg_codes"].items() if dev == b.get("device")]:
            _state["tg_codes"].pop(c, None)
        _state["tg_codes"][code] = str(b.get("device"))
        _save()
    user = _bot_username()
    return {"code": code, "url": f"https://t.me/{user}?start={code}" if user else None}


@router.post("/test")
async def test(request: Request) -> dict:
    b = await _body(request)
    with _lock:
        d = _device(str(b.get("device", "")))
        return _deliver(str(b.get("device")), d, {"type": "test"})


@router.post("/event")
async def event(request: Request) -> dict:
    """An event the app itself observed (a fill, a close it made). Keyed so
    the server-side watcher and the app never double-report one close."""
    b = await _body(request)
    ev = b.get("event")
    if not isinstance(ev, dict) or ev.get("type") not in ("executed", "pending_filled", "sl", "tp", "closed", "stopout"):
        raise HTTPException(400, "Unknown event")
    with _lock:
        d = _device(str(b.get("device", "")))
        key = f"{ev.get('account', 'paper')}:{ev.get('id')}:{'open' if ev['type'] in ('executed', 'pending_filled') else 'close'}"
        res = _deliver(str(b.get("device")), d, ev, key)
        # a close the app made itself stops the watcher for that position
        if ev["type"] in ("sl", "tp", "closed", "stopout") and ev.get("account", "paper") == "paper":
            d["paper"].pop(str(ev.get("id")), None)
        _save()
        return res


# ── paper watcher ────────────────────────────────────────────────────────────
@router.post("/paper/sync")
async def paper_sync(request: Request) -> dict:
    """Replace the device's watched paper positions with the app's open book
    and hand back any closes the watcher made that the app has not seen."""
    b = await _body(request)
    positions = b.get("positions")
    if not isinstance(positions, list):
        raise HTTPException(400, "positions must be a list")
    with _lock:
        d = _device(str(b.get("device", "")))
        watched = {}
        for p in positions[:100]:
            if not isinstance(p, dict):
                continue
            try:
                pos = {
                    "id": str(p["id"]), "symbol": str(p["symbol"]), "label": str(p.get("label") or p["symbol"]),
                    "side": "buy" if p.get("side") == "buy" else "sell", "volume": float(p.get("volume") or 0),
                    "entry": float(p["entry"]),
                    "sl": float(p["sl"]) if p.get("sl") is not None else None,
                    "tp": float(p["tp"]) if p.get("tp") is not None else None,
                    "unit": float(p["unit"]) if p.get("unit") is not None else None,   # money per 1.0 price move
                    "dp": int(p.get("dp") or 2), "spread": float(p.get("spread") or 0),
                }
            except (KeyError, TypeError, ValueError):
                continue
            watched[pos["id"]] = pos
        d["paper"] = watched
        # A close judged on levels the app has since changed is not a fill: the
        # app still lists the position, with a different stop or target than the
        # one that "fired". Drop it here so the app never sees it, and keep
        # watching the position on its current levels. A close on the levels the
        # app still has stands: the app was away and adopts it.
        def _superseded(c: dict) -> bool:
            p = watched.get(str(c.get("id")))
            if p is None or "sl" not in c or "tp" not in c:
                return False
            lvl = c.get(c.get("reason"))
            cur = p.get(c.get("reason"))
            return lvl is None or cur is None or abs(float(lvl) - float(cur)) > 1e-9
        d["closed"] = [c for c in (d.get("closed") or []) if not _superseded(c)]
        closed = list(d["closed"])
        _save()
    _feed.want(_all_symbols())
    return {"watching": len(watched), "closed": closed}


@router.post("/paper/ack")
async def paper_ack(request: Request) -> dict:
    b = await _body(request)
    ids = {str(i) for i in (b.get("ids") or [])}
    with _lock:
        d = _device(str(b.get("device", "")))
        d["closed"] = [c for c in d.get("closed") or [] if c["id"] not in ids]
        _save()
        return {"pendingCloses": len(d["closed"])}


def _all_symbols() -> set:
    with _lock:
        out = set()
        for d in _state["devices"].values():
            for p in (d.get("paper") or {}).values():
                out.add(p["symbol"])
        return out


def _on_tick(symbol: str, quote: float, tbid: Optional[float] = None, task: Optional[float] = None) -> None:
    """Runs on every Deriv tick for a watched symbol. A stop or target is
    'hit' the way the app judges it: buys close on the bid, sells on the ask.
    The venue's own bid/ask are used when the tick carries them; otherwise
    half the last-known spread is applied each way around the quote."""
    fired = []
    with _lock:
        for dev_id, d in _state["devices"].items():
            for pid, p in list((d.get("paper") or {}).items()):
                if p["symbol"] != symbol:
                    continue
                if tbid is not None and task is not None and task >= tbid:
                    bid, ask = tbid, task
                else:
                    half = (p.get("spread") or 0) / 2
                    bid, ask = quote - half, quote + half
                reason = None; price = None
                if p["side"] == "buy":
                    if p["sl"] is not None and bid <= p["sl"]: reason, price = "sl", bid
                    elif p["tp"] is not None and bid >= p["tp"]: reason, price = "tp", bid
                else:
                    if p["sl"] is not None and ask >= p["sl"]: reason, price = "sl", ask
                    elif p["tp"] is not None and ask <= p["tp"]: reason, price = "tp", ask
                if not reason:
                    continue
                dirn = 1 if p["side"] == "buy" else -1
                pnl = (price - p["entry"]) * dirn * p["unit"] if p.get("unit") is not None else None
                d["paper"].pop(pid, None)
                rec = {"id": pid, "reason": reason, "price": round(price, p["dp"]), "pnl": pnl, "at": time.time(),
                       "sl": p["sl"], "tp": p["tp"]}      # the levels this close was judged on
                d["closed"].append(rec); del d["closed"][:-CLOSED_KEEP]
                ev = {"type": reason, "account": "paper", "id": pid, "symbol": symbol, "label": p["label"],
                      "side": p["side"], "volume": p["volume"], "price": price, "pnl": pnl, "dp": p["dp"]}
                fired.append((dev_id, d, ev, f"paper:{pid}:close"))
        if fired:
            _save()
    for dev_id, d, ev, key in fired:
        with _lock:
            _deliver(dev_id, d, ev, key)


class _DerivFeed(threading.Thread):
    """One websocket to Deriv, subscribed to whatever the watched positions
    need. Reconnects on its own; sleeps when nothing is watched."""
    def __init__(self):
        super().__init__(daemon=True, name="notify-deriv-feed")
        self._want: set = set(); self._have: set = set(); self._ws = None; self._wake = threading.Event()

    def want(self, symbols: set) -> None:
        self._want = set(symbols); self._wake.set()

    def run(self) -> None:
        try:
            from websockets.sync.client import connect   # websockets ≥ 12
        except Exception as e:
            log.warning("paper watcher off — websockets client unavailable: %s", e); return
        backoff = 2
        while True:
            if not self._want:
                self._wake.wait(30); self._wake.clear(); continue
            try:
                with connect(DERIV_WS, open_timeout=15, close_timeout=5) as ws:
                    self._ws = ws; self._have = set(); backoff = 2
                    ws.send(json.dumps({"ping": 1}))
                    last_ping = time.time()
                    while True:
                        missing = self._want - self._have
                        for s in missing:
                            ws.send(json.dumps({"ticks": s, "subscribe": 1})); self._have.add(s)
                        if not self._want:
                            break
                        try:
                            raw = ws.recv(timeout=20)
                        except TimeoutError:
                            if time.time() - last_ping > 25:
                                ws.send(json.dumps({"ping": 1})); last_ping = time.time()
                            continue
                        m = json.loads(raw)
                        t = m.get("tick")
                        if t and t.get("symbol") in self._want:
                            try:
                                _bid = float(t["bid"]) if t.get("bid") is not None else None
                                _ask = float(t["ask"]) if t.get("ask") is not None else None
                                _on_tick(t["symbol"], float(t["quote"]), _bid, _ask)
                            except Exception as e:
                                log.warning("tick handler error: %s", e)
                        elif m.get("error"):
                            log.info("deriv: %s", m["error"].get("message"))
            except Exception as e:
                log.info("deriv feed reconnecting (%s)", e)
                time.sleep(backoff); backoff = min(backoff * 2, 60)


_feed = _DerivFeed()


# ── MT5 through the bridge ───────────────────────────────────────────────────
def mt5_snapshot_hook(cid: str, snap: dict, deals: Optional[list]) -> None:
    """Registered with mt5_bridge.SNAPSHOT_HOOKS. Diffs each EA snapshot for
    the devices that share this bridge: new tickets → executed; new closing
    deals → stop / target / manual with the broker's reason and P&L."""
    fired = []
    with _lock:
        devices = [(k, d) for k, d in _state["devices"].items() if d.get("bridge") == cid]
        if not devices:
            return
        positions = {str(p.get("ticket")): p for p in (snap.get("positions") or []) if isinstance(p, dict)}
        acct = (snap.get("account") or {})
        acct_name = "MT5 real" if acct.get("mode") == "real" else "MT5 demo"
        ccy = acct.get("currency") or "USD"
        for dev_id, d in devices:
            seen = d.get("mt5_seen_positions")
            if seen is None:
                d["mt5_seen_positions"] = list(positions)      # first sight: baseline, no backfill
            else:
                for tk, p in positions.items():
                    if tk not in seen:
                        ev = {"type": "executed", "account": acct_name, "id": tk, "symbol": p.get("symbol"),
                              "label": p.get("symbol"), "side": p.get("side"), "volume": p.get("volume"),
                              "price": p.get("entry"), "sl": p.get("sl") or None, "tp": p.get("tp") or None,
                              "dp": p.get("digits"), "ccy": ccy}
                        fired.append((dev_id, d, ev, f"mt5:{tk}:open"))
                d["mt5_seen_positions"] = list(positions)
            if deals is not None:
                last = d.get("mt5_last_deal") or 0
                newest = last
                first = not d.get("mt5_hist_init")
                d["mt5_hist_init"] = True
                for deal in deals:
                    if not isinstance(deal, dict) or deal.get("kind") != "trade":
                        continue
                    when = float(deal.get("time") or 0)
                    if when <= last:
                        continue
                    newest = max(newest, when)
                    if first:
                        continue                                # first sight: baseline, don't replay history
                    why = str(deal.get("reason") or "")
                    t = "sl" if why == "Stop loss" else "tp" if why == "Take profit" else "stopout" if why == "Stop out" else "closed"
                    ev = {"type": t, "account": acct_name, "id": str(deal.get("ticket")), "symbol": deal.get("symbol"),
                          "label": deal.get("symbol"), "side": deal.get("side"), "volume": deal.get("volume"),
                          "price": deal.get("exit"), "pnl": deal.get("profit"), "dp": deal.get("digits"), "ccy": ccy}
                    fired.append((dev_id, d, ev, f"mt5:{deal.get('ticket')}:close"))
                if newest != last:
                    d["mt5_last_deal"] = newest
        if fired or any(True for _ in devices):
            _save()
    for dev_id, d, ev, key in fired:
        with _lock:
            _deliver(dev_id, d, ev, key)


# ── Telegram pairing ─────────────────────────────────────────────────────────
class _TelegramPoller(threading.Thread):
    """Long-polls getUpdates to pair `/start <code>` with the device that
    asked for the code. Nothing else is read from the chat."""
    def __init__(self):
        super().__init__(daemon=True, name="notify-telegram")

    def run(self) -> None:
        if not TG_TOKEN:
            return
        offset = 0
        while True:
            try:
                r = requests.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
                                 params={"timeout": 50, "offset": offset, "allowed_updates": json.dumps(["message"])},
                                 timeout=60).json()
                if not r.get("ok"):
                    log.info("telegram getUpdates not ok (%s) — pausing", r.get("description") or r.get("error_code"))
                    time.sleep(5)
                    continue
                for u in r.get("result") or []:
                    offset = max(offset, int(u["update_id"]) + 1)
                    msg = u.get("message") or {}
                    text = str(msg.get("text") or "").strip()
                    chat = msg.get("chat") or {}
                    sender = msg.get("from") or {}
                    if not chat.get("id") or chat.get("type", "private") != "private":
                        continue
                    if text.split("@")[0] in ("/app", "/login") or text == "/start":
                        self._login(sender, chat)
                        continue
                    if not text.startswith("/start"):
                        continue
                    code = text[6:].strip()
                    if code.startswith("L"):                   # link this Telegram to a PROTrader account
                        try:
                            import accounts
                            name = " ".join(x for x in (sender.get("first_name"), sender.get("last_name")) if x)
                            title, body = accounts.telegram_start(code, sender.get("id"), chat["id"], sender.get("username") or "", name)
                        except Exception as e:
                            log.warning("telegram link failed: %s", e)
                            title, body = "PROTrader", "Linking failed. Please try again in a minute."
                        _send_tg(str(chat["id"]), title, body)
                        continue
                    with _lock:
                        dev = _state["tg_codes"].pop(code, None)
                        if dev and dev in _state["devices"]:
                            _state["devices"][dev]["tg"] = str(chat["id"])
                            _save()
                    if dev:
                        _send_tg(str(chat["id"]), "PROTrader connected",
                                 "This chat will receive your fills, stops and targets.")
                    else:
                        _send_tg(str(chat["id"]), "PROTrader",
                                 "Open PROTrader → Notifications → Connect Telegram, and use the link it gives you.")
            except Exception as e:
                log.info("telegram poller: %s", _redact(e))
                time.sleep(5)

    @staticmethod
    def _login(sender: dict, chat: dict) -> None:
        """/app: a one-time link that opens PROTrader signed in as the account
        this Telegram is linked to."""
        try:
            import accounts
            path = accounts.telegram_login_path(sender.get("id"))
        except Exception as e:
            log.warning("telegram login link failed: %s", e); path = None
        if path:
            _send_tg(str(chat["id"]), "Open PROTrader", "This button signs you in. It works once, for 5 minutes.",
                     ("Open PROTrader", accounts.APP_URL + path))
        else:
            _send_tg(str(chat["id"]), "PROTrader",
                     "This Telegram is not linked to a PROTrader account yet. In PROTrader open Account → "
                     "Link Telegram (you need to be signed in with your Academy account).")


def start() -> None:
    """Call once at import time from dashboard.py."""
    _load()
    try:
        import mt5_bridge
        mt5_bridge.SNAPSHOT_HOOKS.append(mt5_snapshot_hook)
    except Exception as e:
        log.warning("MT5 notifications off: %s", e)
    _feed.want(_all_symbols())
    _feed.start()
    _TelegramPoller().start()
    log.info("notify ready — push:%s telegram:%s state:%s", bool(webpush and VAPID_PUBLIC), bool(TG_TOKEN), STATE_PATH)
