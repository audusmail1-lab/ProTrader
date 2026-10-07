"""
Contract book: Deriv contracts tracked on paper. Nothing is ever bought.

Each spec is one contract the book "takes" on paper once a week. On the first
scan of the week inside the US session, it asks Deriv for a live price
(the read-only `proposal` call), records the payout Deriv offers, takes the
first tick after the quote as the entry and settles the contract at its expiry
from Deriv's own prices. The question it answers, with Deriv's real prices
rather than a model: do these contracts win more often than Deriv charges for?

The lead it tests (research/docs/09-pricing-audit.md): Deriv prices long index
"Rise" contracts close to the risk-neutral price, which leaves out the equity
premium. Over 2001-2026 the Nasdaq-100 rose over 30 days 63% of the time and
over 91 days 70%; over 2016-2026 the S&P 500 did 70% and 77%.

The specs are frozen as BOOK_VERSION. Changing one is a new version; results of
different versions are never mixed.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import logging
import math
import time
from typing import Any, Awaitable, Callable, Optional

import sentinel_core as core

log = logging.getLogger("sentinel.book")

SPECS: list[dict] = [
    {"id": "ndx-rise-30", "symbol": "OTC_NDX", "label": "US Tech 100 · Rise · 30 days", "contract_type": "CALL", "days": 30,
     "history": {"won": 0.631, "source": "Nasdaq-100 2001–2026, every 30-day window"}},
    {"id": "ndx-rise-91", "symbol": "OTC_NDX", "label": "US Tech 100 · Rise · 91 days", "contract_type": "CALL", "days": 91,
     "history": {"won": 0.698, "source": "Nasdaq-100 2001–2026, every 91-day window"}},
    {"id": "spx-rise-30", "symbol": "OTC_SPC", "label": "US 500 · Rise · 30 days", "contract_type": "CALL", "days": 30,
     "history": {"won": 0.697, "source": "S&P 500 2016–2026, every 30-day window"}},
    {"id": "spx-rise-91", "symbol": "OTC_SPC", "label": "US 500 · Rise · 91 days", "contract_type": "CALL", "days": 91,
     "history": {"won": 0.772, "source": "S&P 500 2016–2026, every 91-day window"}},
]
STAKE = 10.0                           # paper dollars per contract
ENTRY_HOURS_GMT = (14, 19)             # US cash session, well before Deriv's 20:00 close
SETTLE_DELAY_S = 15 * 60               # settle a quarter of an hour after expiry
BOOK_VERSION = "book-" + hashlib.sha1(json.dumps(
    [{k: s[k] for k in ("id", "symbol", "contract_type", "days")} for s in SPECS] + [STAKE, list(ENTRY_HOURS_GMT)],
    sort_keys=True).encode()).hexdigest()[:8]
SPEC_BY_ID = {s["id"]: s for s in SPECS}

Call = Callable[[dict], Awaitable[dict]]

_S = None                              # the sentinel module (set by attach)
_state: dict[str, Any] = {"last_run": None, "last_error": None, "opened": 0, "settled": 0}


def attach(sentinel_module) -> None:
    global _S
    _S = sentinel_module


# ── storage ──────────────────────────────────────────────────────────────────

def _table(con) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS contract_book (
        key TEXT PRIMARY KEY, version TEXT, spec TEXT, status TEXT, opened INTEGER, updated INTEGER, data TEXT)""")


def load_all() -> list[dict]:
    with _S._lock, _S._db() as con:
        _table(con)
        rows = con.execute("SELECT data FROM contract_book WHERE version=? ORDER BY opened", (BOOK_VERSION,)).fetchall()
    return [json.loads(d) for (d,) in rows]


def _save(rec: dict) -> None:
    with _S._lock, _S._db() as con:
        _table(con)
        con.execute("INSERT OR REPLACE INTO contract_book VALUES (?,?,?,?,?,?,?)",
                    (rec["key"], BOOK_VERSION, rec["spec"], rec["status"], int(rec["quoted_at"]), int(time.time()), json.dumps(rec)))


# ── when to enter ────────────────────────────────────────────────────────────

def week_key(spec_id: str, now_s: int) -> str:
    y, w, _ = dt.datetime.fromtimestamp(now_s, dt.timezone.utc).isocalendar()
    return f"{spec_id}:{y}-W{w:02d}"


def due(now_s: int, keys: set[str]) -> list[dict]:
    """Specs not yet taken this ISO week, inside the entry window (weekdays, US session)."""
    t = dt.datetime.fromtimestamp(now_s, dt.timezone.utc)
    if t.weekday() >= 5 or not (ENTRY_HOURS_GMT[0] <= t.hour < ENTRY_HOURS_GMT[1]):
        return []
    return [s for s in SPECS if week_key(s["id"], now_s) not in keys]


# ── Deriv calls (read-only) ──────────────────────────────────────────────────

async def _ticks_after(call: Call, symbol: str, t: int) -> Optional[tuple[int, float]]:
    end: Any = int(t) + 120 if time.time() > t + 120 else "latest"
    m = await call({"ticks_history": symbol, "start": int(t) + 1, "end": end, "count": 5000, "style": "ticks"})
    h = (m or {}).get("history") or {}
    ts, ps = h.get("times") or [], h.get("prices") or []
    i = next((k for k, e in enumerate(ts) if int(e) > t), None)
    return (int(ts[i]), float(ps[i])) if i is not None else None


async def _price_at(call: Call, symbol: str, t: int) -> Optional[tuple[int, float]]:
    """Deriv's last price at or before t: its tick, else the close of its 1-minute candle."""
    m = await call({"ticks_history": symbol, "end": int(t), "count": 1, "style": "ticks"})
    h = (m or {}).get("history") or {}
    if not m.get("error") and h.get("times"):
        e, p = int(h["times"][-1]), float(h["prices"][-1])
        if e <= t:
            return e, p
    m = await call({"ticks_history": symbol, "end": int(t), "count": 2, "style": "candles", "granularity": 60})
    cs = [c for c in (m or {}).get("candles") or [] if int(c["epoch"]) + 60 <= t + 1]      # closed by t
    if cs:
        return int(cs[-1]["epoch"]) + 59, float(cs[-1]["close"])
    return None


async def take(call: Call, spec: dict, now_s: int) -> Optional[dict]:
    """Quote one contract and record it on paper. None when Deriv will not quote it right now."""
    req = {"proposal": 1, "amount": STAKE, "basis": "stake", "currency": "USD", "underlying_symbol": spec["symbol"],
           "contract_type": spec["contract_type"], "duration": spec["days"], "duration_unit": "d"}
    m = await call(req)
    if m.get("error"):
        _state["last_error"] = f"{spec['id']}: {m['error'].get('message')}"
        return None
    p = m["proposal"]
    payout = float(p["payout"])
    rec = {"key": week_key(spec["id"], now_s), "spec": spec["id"], "symbol": spec["symbol"], "contract_type": spec["contract_type"],
           "days": spec["days"], "stake": STAKE, "payout": payout, "priced_p": round(STAKE / payout, 4),
           "quoted_at": int(now_s), "quote_spot": float(p.get("spot") or 0), "quote_spot_time": int(p.get("spot_time") or now_s),
           "date_start": int(p.get("date_start") or now_s), "date_expiry": int(p["date_expiry"]),
           "longcode": p.get("longcode", ""), "status": "open", "version": BOOK_VERSION}
    return rec


async def fill_entry(call: Call, rec: dict) -> bool:
    """The entry is the first tick after the quote, as on Deriv. False until that tick exists."""
    got = await _ticks_after(call, rec["symbol"], rec["quote_spot_time"])
    if not got:
        return False
    rec["entry_time"], rec["entry"] = got
    return True


def settle(rec: dict, exit_time: int, exit_price: float) -> dict:
    up = exit_price > rec["entry"]
    down = exit_price < rec["entry"]
    won = up if rec["contract_type"] == "CALL" else down if rec["contract_type"] == "PUT" else False
    rec.update(exit_time=int(exit_time), exit=float(exit_price), won=bool(won),
               returned=round(rec["payout"] if won else 0.0, 2), status="won" if won else "lost",
               net=round((rec["payout"] if won else 0.0) - rec["stake"], 2))
    return rec


# ── the per-cycle job ────────────────────────────────────────────────────────

async def run_once(now_s: Optional[int] = None, call: Optional[Call] = None) -> dict:
    """Open this week's contracts that are due, fill pending entries, settle expired ones."""
    now_s = int(now_s if now_s is not None else time.time())
    recs = load_all()
    keys = {r["key"] for r in recs}
    todo_open = due(now_s, keys)
    todo_entry = [r for r in recs if r["status"] == "open" and "entry" not in r]
    todo_settle = [r for r in recs if r["status"] == "open" and "entry" in r and now_s >= r["date_expiry"] + SETTLE_DELAY_S]
    done = {"opened": 0, "entries": 0, "settled": 0}
    if not (todo_open or todo_entry or todo_settle):
        return done

    async def run(c: Call) -> None:
        for spec in todo_open:
            rec = await take(c, spec, now_s)
            if rec:
                _save(rec); done["opened"] += 1
                todo_entry.append(rec)
        if todo_open:
            await asyncio.sleep(3 if call is None else 0)         # let the next tick arrive
        for rec in todo_entry:
            if await fill_entry(c, rec):
                _save(rec); done["entries"] += 1
        for rec in todo_settle:
            got = await _price_at(c, rec["symbol"], rec["date_expiry"])
            if got:
                _save(settle(rec, *got)); done["settled"] += 1

    if call is not None:
        await run(call)
    else:
        import websockets
        async with websockets.connect(core.DERIV_WS_URL, max_size=2 ** 24, open_timeout=15) as ws:
            async def ws_call(req: dict) -> dict:
                await ws.send(json.dumps(req))
                while True:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 20))
                    if m.get("msg_type") in ("proposal", "history", "candles") or m.get("error"):
                        return m
            await run(ws_call)
    _state["opened"] += done["opened"]
    _state["settled"] += done["settled"]
    return done


async def cycle() -> None:
    try:
        await run_once()
        _state["last_run"] = time.time()
    except Exception as e:
        _state["last_error"] = f"{time.strftime('%H:%M:%S', time.gmtime())} {e}"
        log.warning("contract book: %s", e)


# ── results ──────────────────────────────────────────────────────────────────

def _verdict(n: int, wins: int, ps: list[float]) -> tuple[str, Optional[float]]:
    if n < 20:
        return f"too few settled yet ({n} of 20)", None
    exp = sum(ps)
    var = sum(p * (1 - p) for p in ps)
    z = (wins - exp) / math.sqrt(var) if var > 0 else 0.0
    if z >= 2:
        return "wins more often than Deriv charges for", z
    if z <= -2:
        return "Deriv's price is winning", z
    return "no difference from Deriv's price yet", z


def stats(recs: list[dict]) -> dict:
    out = {}
    for s in SPECS:
        rs = [r for r in recs if r["spec"] == s["id"]]
        st = [r for r in rs if r["status"] in ("won", "lost")]
        wins = sum(1 for r in st if r["won"])
        staked = sum(r["stake"] for r in st)
        returned = sum(r["returned"] for r in st)
        verdict, z = _verdict(len(st), wins, [r["priced_p"] for r in st])
        out[s["id"]] = {
            "label": s["label"], "history": s["history"], "taken": len(rs), "open": len(rs) - len(st), "settled": len(st),
            "wins": wins, "win_rate": round(wins / len(st), 3) if st else None,
            "priced_p": round(sum(r["priced_p"] for r in rs) / len(rs), 3) if rs else None,
            "last_payout": rs[-1]["payout"] if rs else None,
            "staked": round(staked, 2), "returned": round(returned, 2), "net": round(returned - staked, 2),
            "roi": round(returned / staked - 1, 3) if staked else None,
            "edge_on_history": round(s["history"]["won"] / (sum(r["priced_p"] for r in rs) / len(rs)) - 1, 3) if rs else None,
            "verdict": verdict, "z": round(z, 2) if z is not None else None,
        }
    all_st = [r for r in recs if r["status"] in ("won", "lost")]
    tot_staked = sum(r["stake"] for r in all_st)
    tot_ret = sum(r["returned"] for r in all_st)
    return {"specs": out, "taken": len(recs), "settled": len(all_st), "net": round(tot_ret - tot_staked, 2),
            "roi": round(tot_ret / tot_staked - 1, 3) if tot_staked else None}
