"""
MT5 bridge relay.

PROTrader (the web app) cannot talk to MetaTrader 5 directly, and Deriv has no
API for placing MT5 orders. So an Expert Advisor running inside the user's own
MT5 terminal calls this relay about once a second: it uploads the account
snapshot and collects any commands the app queued for it.

    app  --POST /api/bridge/cmd-->  relay  <--POST /api/bridge/ea--  EA (in MT5)
    app  <--GET /api/bridge/state-- relay

Design rules
  * The relay holds no credentials and never sees the MT5 password. A channel
    is identified only by the SHA-256 of a random key that the user generates
    on their device and pastes into the EA. The raw key is never stored.
  * Everything is in memory. A restart forgets queues, which is the safe
    direction: an order is never executed late.
  * Commands are short-lived. One that is not collected within CMD_TTL_S is
    dropped, and nothing is queued at all unless the EA has checked in within
    EA_ONLINE_S — so an order cannot sit waiting and fire minutes later.
  * A command is handed to the EA exactly once. If that response is lost the
    order is NOT retried; the app reports it as unconfirmed.
  * The EA is the authority on risk limits (max risk, daily loss, max
    positions, real-account switch). The relay only moves messages.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import OrderedDict, deque
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

router = APIRouter(prefix="/api/bridge", tags=["mt5-bridge"])

CMD_TTL_S = 15.0          # uncollected commands die after this
EA_ONLINE_S = 8.0         # EA counts as online if seen within this window
MAX_QUEUE = 10            # queued commands per channel
MAX_RESULTS = 60          # remembered results per channel
MAX_CHANNELS = 300
CHANNEL_IDLE_S = 6 * 3600
MAX_BODY = 96 * 1024
MIN_KEY_LEN = 24

CMD_TYPES = {"market", "limit", "stop", "close", "modify", "cancel", "closeall", "spec", "trail"}
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,40}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{%d,128}$" % MIN_KEY_LEN)

_lock = threading.Lock()
_channels: "OrderedDict[str, dict]" = OrderedDict()


def _now() -> float:
    return time.time()


def _channel(request: Request) -> dict:
    key = request.headers.get("x-bridge-key", "")
    if not _KEY_RE.match(key):
        raise HTTPException(401, "Missing or malformed bridge key")
    cid = hashlib.sha256(key.encode()).hexdigest()
    now = _now()
    ch = _channels.get(cid)
    if ch is None:
        # evict idle channels before adding a new one
        for k in [k for k, v in _channels.items() if now - v["touched"] > CHANNEL_IDLE_S]:
            _channels.pop(k, None)
        if len(_channels) >= MAX_CHANNELS:
            _channels.popitem(last=False)
        ch = {
            "queue": deque(), "results": deque(maxlen=MAX_RESULTS), "seen_ids": deque(maxlen=200),
            "ea_seen": 0.0, "snapshot": None, "history": None, "touched": now,
        }
        _channels[cid] = ch
    ch["touched"] = now
    _channels.move_to_end(cid)
    return ch


async def _json_body(request: Request) -> Any:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(413, "Body too large")
    try:
        return json.loads(raw.decode("utf-8", "replace") or "{}")
    except ValueError:
        raise HTTPException(400, "Body is not valid JSON")


def _num(v: Any, name: str, *, required: bool = False, positive: bool = False) -> float | None:
    if v is None or v == "":
        if required:
            raise HTTPException(422, f"{name} is required")
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise HTTPException(422, f"{name} must be a number")
    if f != f or f in (float("inf"), float("-inf")):
        raise HTTPException(422, f"{name} must be finite")
    if positive and f <= 0:
        raise HTTPException(422, f"{name} must be greater than zero")
    return f


def _clean_text(v: Any, limit: int = 64) -> str:
    # '|' and newlines are the EA wire-format separators; never let them through.
    return re.sub(r"[|\r\n\t]", " ", str(v or ""))[:limit].strip()


def _fmt(v: float | None) -> str:
    # "-" marks an empty field: MQL5's StringSplit is not trusted to keep
    # empty substrings between consecutive separators.
    return "-" if v is None else repr(float(v))


# ── app → relay ───────────────────────────────────────────────────────────────
@router.post("/cmd")
async def queue_command(request: Request):
    body = await _json_body(request)
    with _lock:
        ch = _channel(request)
        now = _now()
        if now - ch["ea_seen"] > EA_ONLINE_S:
            raise HTTPException(503, "MT5 bridge is offline — open MT5 and check the EA is running")

        cid = str(body.get("id", ""))
        ctype = str(body.get("type", ""))
        if not _ID_RE.match(cid):
            raise HTTPException(422, "Bad command id")
        if ctype not in CMD_TYPES:
            raise HTTPException(422, "Unknown command type")
        if cid in ch["seen_ids"]:
            raise HTTPException(409, "Duplicate command id")

        cmd = {"id": cid, "type": ctype, "ts": now,
               "symbol": "", "side": "", "volume": None, "price": None,
               "sl": None, "tp": None, "ticket": ""}

        if ctype in ("market", "limit", "stop"):
            cmd["symbol"] = _clean_text(body.get("symbol"))
            cmd["side"] = str(body.get("side", ""))
            if not cmd["symbol"]:
                raise HTTPException(422, "symbol is required")
            if cmd["side"] not in ("buy", "sell"):
                raise HTTPException(422, "side must be buy or sell")
            cmd["volume"] = _num(body.get("volume"), "volume", required=True, positive=True)
            cmd["price"] = _num(body.get("price"), "price", required=ctype != "market", positive=True)
            cmd["sl"] = _num(body.get("sl"), "sl", positive=True)
            cmd["tp"] = _num(body.get("tp"), "tp", positive=True)
        elif ctype in ("close", "modify", "cancel"):
            ticket = str(body.get("ticket", ""))
            if not ticket.isdigit():
                raise HTTPException(422, "ticket must be the MT5 ticket number")
            cmd["ticket"] = ticket
            if ctype == "close":
                cmd["volume"] = _num(body.get("volume"), "volume", positive=True)  # None = full
            if ctype == "modify":
                cmd["sl"] = _num(body.get("sl"), "sl")
                cmd["tp"] = _num(body.get("tp"), "tp")
        elif ctype == "trail":
            ticket = str(body.get("ticket", ""))
            if not ticket.isdigit():
                raise HTTPException(422, "ticket must be the MT5 ticket number")
            cmd["ticket"] = ticket
            # distance travels in the price field; 0 switches trailing off
            dist = _num(body.get("distance"), "distance", required=True)
            if dist < 0:
                raise HTTPException(422, "distance cannot be negative")
            cmd["price"] = dist
            cmd["side"] = "be" if body.get("mode") == "be" else "now"
        elif ctype == "spec":
            cmd["symbol"] = _clean_text(body.get("symbol"))
            if not cmd["symbol"]:
                raise HTTPException(422, "symbol is required")

        # drop expired, then enforce the cap
        while ch["queue"] and now - ch["queue"][0]["ts"] > CMD_TTL_S:
            ch["queue"].popleft()
        if len(ch["queue"]) >= MAX_QUEUE:
            raise HTTPException(429, "Too many commands waiting")
        ch["queue"].append(cmd)
        ch["seen_ids"].append(cid)
        return {"ok": True, "id": cid, "ttl": CMD_TTL_S}


@router.get("/state")
async def bridge_state(request: Request, since: float = 0.0):
    with _lock:
        ch = _channel(request)
        now = _now()
        ago = now - ch["ea_seen"] if ch["ea_seen"] else None
        return {
            "online": ago is not None and ago <= EA_ONLINE_S,
            "lastSeenAgo": None if ago is None else round(ago, 1),
            "serverTime": now,
            "snapshot": ch["snapshot"],
            "history": ch["history"],
            "results": [r for r in ch["results"] if r.get("_at", 0) > since],
        }


# ── EA → relay ────────────────────────────────────────────────────────────────
@router.post("/ea", response_class=PlainTextResponse)
async def ea_sync(request: Request):
    """The EA posts its snapshot as JSON and receives pending commands as
    plain text, one per line, because MQL5 has no JSON parser:

        CMD|id|type|symbol|side|volume|price|sl|tp|ticket      ("-" = empty)
    """
    body = await _json_body(request)
    if not isinstance(body, dict):
        raise HTTPException(400, "Expected a JSON object")
    with _lock:
        ch = _channel(request)
        now = _now()
        ch["ea_seen"] = now

        snap = {k: body.get(k) for k in ("account", "positions", "orders", "limits", "ea")}
        snap["at"] = now
        ch["snapshot"] = snap
        if isinstance(body.get("history"), list):
            ch["history"] = {"at": now, "deals": body["history"][:200]}

        for r in (body.get("results") or [])[:20]:
            if isinstance(r, dict) and _ID_RE.match(str(r.get("id", ""))):
                r = dict(r)
                r["_at"] = now
                ch["results"].append(r)

        lines = ["OK|%d" % int(now)]
        while ch["queue"]:
            cmd = ch["queue"].popleft()
            if now - cmd["ts"] > CMD_TTL_S:
                ch["results"].append({"id": cmd["id"], "ok": False, "_at": now,
                                      "msg": "Expired before MT5 collected it — not executed"})
                continue
            lines.append("|".join([
                "CMD", cmd["id"], cmd["type"], cmd["symbol"] or "-", cmd["side"] or "-",
                _fmt(cmd["volume"]), _fmt(cmd["price"]), _fmt(cmd["sl"]), _fmt(cmd["tp"]),
                cmd["ticket"] or "-",
            ]))
        return "\n".join(lines) + "\n"
