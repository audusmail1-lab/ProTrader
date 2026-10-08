"""
Drift: own the long-run rise of US Tech 100 and US 500; step aside below the 200-day line.

Why (research/experiments/H19-comeback-drift, H20-drift): on Deriv's synthetic
indices nothing has an edge; on real stock indices the one dependable source of
return is that they rise over the years. Holding the Nasdaq-100 through a Deriv
CFD keeps about half of that rise after financing (T-bill + about 2.5% a year on
the position), and the 200-day line keeps it out of the worst of the long falls.

The rule, every trading day, on Deriv's own daily candles (stored here, because
Deriv serves only one year of daily history):
  hold    when the day closes above its 200-day average
  aside   when it closes below it; fills at the next day's open
Two books run side by side on paper, from the same candles:
  pick    Joel's choice: half the account in each index (1x in all, no leverage)
  rules   what the demo bot trades: the same signal inside the risk framework.
          Each index risks 0.5% of equity at a stop 3% under the 200-day line;
          the stop is raised with the line every day and never lowered; at most
          0.5x of equity in each. Two positions at full risk use 1% of the 2%
          open-risk room, so Sentinel Live always keeps room for one A setup.
The demo (MT5, demo account only, after the owner presses Start) places the rules
book's positions through Sentinel Live's executor: same EA, same journal table,
same risk counters, so the 1% / 2% / 3% / three-losses rules cover both bots.

Nothing here touches a real account: entries go only to a demo account, and the
EA refuses real accounts on its own. Deriv calls are read-only (`ticks_history`).

Endpoints (owner: instructor session or owner key)
  GET  /api/sentinel/drift              signals, both paper books, the demo journal
  POST /api/sentinel/drift {action}     start | stop | symbols
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import time
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, HTTPException, Request

import sentinel_core as core

log = logging.getLogger("sentinel.drift")
router = APIRouter(tags=["sentinel-drift"])

MARKETS: list[dict] = [
    {"id": "frxNAS100", "deriv": "OTC_NDX", "label": "US Tech 100", "mt5": "US Tech 100"},
    {"id": "frxSPX500", "deriv": "OTC_SPC", "label": "US 500", "mt5": "US SP 500"},
]
MARKET_BY_ID = {m["id"]: m for m in MARKETS}
LINE_DAYS = 200
STOP_UNDER_LINE = 0.03          # the rules book's stop: 3% under the 200-day line
RISK_PCT_EACH = 0.5             # % of equity at that stop, per index (two = 1% of the 2% room)
CAP_EACH = 0.5                  # at most 0.5x of equity in each index: 1x in all
FINANCING_PA = 0.065            # paper estimate: 3-month T-bill (4.0% on 6 Oct 2026) + 2.5%; the demo shows Deriv's real swap
SPREAD = 0.0003                 # paper estimate per side, as a share of the position
PAPER_EQUITY = 10_000.0
RUN_EVERY_S = 600
FRESH_TICK_S = 300              # a Deriv tick older than this means the market is shut: no order
TRADE_HOURS_GMT = (6, 20)       # Deriv's US index hours: orders, stop moves and closes only inside them
MAX_SENDS_PER_SIGNAL = 3
DAY = 86400
BOOKS = {"pick": "Your pick: 1x, exit under the line", "rules": "Demo version: inside your risk rules"}
RULES_VERSION = "drift-" + hashlib.sha1(json.dumps(
    [[m["id"] for m in MARKETS], LINE_DAYS, STOP_UNDER_LINE, RISK_PCT_EACH, CAP_EACH], sort_keys=True).encode()).hexdigest()[:8]

# What history says (research/experiments/H20-drift/RESULT.md), Deriv CFD costs, fills at the close.
HISTORY = {
    "source": "Nasdaq-100 1987-2026 (FRED); US 500 only from 2016 (FRED keeps 10 years)",
    "rows": [
        {"what": "Index fund, held (no financing)", "span": "Nasdaq-100 1987-2026", "per_year": 14.3, "worst": -83},
        {"what": "Your pick, 1x CFD, out under the line", "span": "Nasdaq-100 1987-2026", "per_year": 6.8, "worst": -65,
         "note": "2000-2012: -4.8% a year"},
        {"what": "Your pick, both indices", "span": "2017-2026", "per_year": 8.2, "worst": -21},
        {"what": "Demo version (½% each at the line stop)", "span": "2017-2026", "per_year": 2.1, "worst": -6},
        {"what": "Demo version, Nasdaq half", "span": "1987-2026", "per_year": 1.1, "worst": -12,
         "note": "2000-2012: -0.6% a year"},
    ],
    "reading": "The rise is real, but a CFD hands about half of it to financing, and the 1% rule keeps the demo "
               "version small (about a fifth of the account invested on average). Long flat decades happen: "
               "2000-2012 lost money in every version.",
}

Call = Callable[[dict], Awaitable[dict]]

_S = None                       # the sentinel module (set by attach)
_state: dict[str, Any] = {"last_run": None, "last_error": None, "candles": {}, "ticks": {}, "notes": []}


def attach(sentinel_module) -> None:
    global _S
    _S = sentinel_module
    with _S._lock, _S._db() as con:
        _table(con)
    live = _live()
    if live is not None and _symbols not in live.EXTRA_SYMBOLS:
        live.EXTRA_SYMBOLS.append(_symbols)


def _live():
    return getattr(_S, "_live", None) if _S is not None else None


# ── storage ──────────────────────────────────────────────────────────────────

def _table(con) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS drift_candles (
        market TEXT, epoch INTEGER, o REAL, h REAL, l REAL, c REAL, PRIMARY KEY (market, epoch))""")


def cfg() -> dict:
    c = _S._meta_get("drift_cfg", None) or {}
    c.setdefault("demo_on", False)
    c.setdefault("symbols", {m["id"]: m["mt5"] for m in MARKETS})
    c.setdefault("skips", {})
    return c


def _set_cfg(c: dict) -> None:
    _S._meta_set("drift_cfg", c)


def _symbols() -> set[str]:
    """MT5 symbols whose contract spec the executor must keep fresh (asked of Sentinel Live)."""
    c = cfg()
    live = _live()
    if not (c.get("demo_on") or (live is not None and any(r.get("kind") == "drift" for r in live._open_rows()))):
        return set()
    return {v for v in (c.get("symbols") or {}).values() if v}


def complete(candles: list[dict], now: float) -> list[dict]:
    """Whole trading days only: a daily candle starts at 00:00 GMT and is final once the day is over."""
    out = []
    for c in candles:
        e = int(c["epoch"])
        if e % DAY == 0 and e + DAY <= now:
            out.append({"epoch": e, "o": float(c["open"]), "h": float(c["high"]), "l": float(c["low"]), "c": float(c["close"])})
    return out


def store_candles(market: str, candles: list[dict]) -> int:
    with _S._lock, _S._db() as con:
        _table(con)
        con.executemany("INSERT OR REPLACE INTO drift_candles VALUES (?,?,?,?,?,?)",
                        [(market, c["epoch"], c["o"], c["h"], c["l"], c["c"]) for c in candles])
    return len(candles)


def load_candles(market: str) -> list[dict]:
    with _S._lock, _S._db() as con:
        _table(con)
        rows = con.execute("SELECT epoch, o, h, l, c FROM drift_candles WHERE market=? ORDER BY epoch", (market,)).fetchall()
    return [{"epoch": e, "o": o, "h": h, "l": l, "c": c} for e, o, h, l, c in rows]


# ── the signal ───────────────────────────────────────────────────────────────

def with_line(candles: list[dict]) -> list[dict]:
    """Each candle with its 200-day average (None until 200 closes exist)."""
    out, run = [], 0.0
    for i, c in enumerate(candles):
        run += c["c"]
        if i >= LINE_DAYS:
            run -= candles[i - LINE_DAYS]["c"]
        out.append(dict(c, line=run / LINE_DAYS if i >= LINE_DAYS - 1 else None))
    return out


def signal(candles: list[dict]) -> Optional[dict]:
    """The latest whole day: close, line, distance, hold or aside, and where the rules stop sits."""
    cs = with_line(candles)
    if not cs or cs[-1]["line"] is None:
        return None
    c = cs[-1]
    return {"epoch": c["epoch"], "close": c["c"], "line": round(c["line"], 4), "dist_pct": round(100 * (c["c"] / c["line"] - 1), 2),
            "hold": c["c"] > c["line"], "stop": round(c["line"] * (1 - STOP_UNDER_LINE), 4), "days": len(cs)}


# ── the paper books (pure: the same candles always give the same book) ───────

def simulate(candles: dict[str, list[dict]], start: int, book: str, equity0: float = PAPER_EQUITY) -> dict:
    """Run one book from the close of the day `start` onwards. Decisions on a whole day's close,
    fills at the next day's open; the rules book's stop works inside the day (a gap through it
    fills at the open). Financing is charged on the position every calendar day it is held."""
    lined = {m: {c["epoch"]: c for c in with_line(cs)} for m, cs in candles.items()}
    days = sorted({e for cs in lined.values() for e in cs if e >= start})
    eq = equity0
    pos: dict[str, Optional[dict]] = {m: None for m in candles}
    pend: dict[str, Optional[dict]] = {m: None for m in candles}
    trades: list[dict] = []
    curve: list[tuple[int, float]] = []
    peak, max_dd = eq, 0.0

    def close(m: str, price: float, day: int, why: str) -> None:
        nonlocal eq
        p = pos[m]
        cost = p["q"] * price * SPREAD
        eq += p["q"] * (price - p["last"]) - cost
        p["costs"] += cost
        pnl = p["q"] * (price - p["entry"]) - p["costs"]
        trades.append({"market": m, "opened": p["opened"], "entry": round(p["entry"], 4), "closed": day, "exit": round(price, 4),
                       "why": why, "size": round(p["q"] * p["entry"], 2), "pnl": round(pnl, 2),
                       "risk": round(p["risk"], 2) if p.get("risk") else None,
                       "r": round(pnl / p["risk"], 3) if p.get("risk") else None})
        pos[m] = None

    for d in days:
        for m in candles:
            bar = lined[m].get(d)
            if bar is None or d == start:
                if bar is not None and d == start:          # the first decision is taken on the start day's close
                    _decide(m, bar, pos, pend, book)
                continue
            p = pos[m]
            if p:
                cost = p["q"] * p["last"] * FINANCING_PA / 365 * ((d - p["day"]) / DAY)
                eq -= cost; p["costs"] += cost; p["day"] = d
            todo, pend[m] = pend[m], None
            if todo and todo["do"] == "exit" and p:
                close(m, bar["o"], d, "closed under the 200-day line")
            elif todo and todo["do"] == "enter" and not p:
                o = bar["o"]
                stop = todo.get("stop")
                if book == "pick":
                    n = CAP_EACH * eq
                elif o <= stop * 1.002:
                    n = 0                                   # opened at or under the stop: no trade today
                else:
                    n = min(RISK_PCT_EACH / 100 * eq / ((o - stop) / o), CAP_EACH * eq)
                if n > 0:
                    q = n / o
                    eq -= n * SPREAD
                    pos[m] = {"q": q, "entry": o, "last": o, "stop": stop if book == "rules" else None, "opened": d, "day": d,
                              "costs": n * SPREAD, "risk": q * (o - stop) if book == "rules" else None}
            p = pos[m]
            if p and p["stop"] is not None and bar["l"] <= p["stop"]:
                close(m, min(bar["o"], p["stop"]), d, "stop under the line")
            p = pos[m]
            if p:
                eq += p["q"] * (bar["c"] - p["last"]); p["last"] = bar["c"]
            _decide(m, bar, pos, pend, book)
        if d > start:
            curve.append((d, round(eq, 2)))
            peak = max(peak, eq)
            max_dd = max(max_dd, (peak - eq) / peak if peak > 0 else 0)
    open_pos = {}
    for m, p in pos.items():
        if p:
            open_pos[m] = {"opened": p["opened"], "entry": round(p["entry"], 4), "last": round(p["last"], 4),
                           "size": round(p["q"] * p["last"], 2), "stop": round(p["stop"], 4) if p["stop"] else None,
                           "pnl": round(p["q"] * (p["last"] - p["entry"]) - p["costs"], 2),
                           "risk_at_stop": round(max(0.0, p["q"] * (p["entry"] - p["stop"])), 2) if p["stop"] else None}
    exposure = sum(p["q"] * p["last"] for p in pos.values() if p) / eq if eq > 0 else 0.0
    return {"book": book, "label": BOOKS[book], "start": start, "start_equity": equity0, "equity": round(eq, 2),
            "return_pct": round(100 * (eq / equity0 - 1), 2), "max_dd_pct": round(100 * max_dd, 2),
            "exposure_pct": round(100 * exposure, 1), "positions": open_pos,
            "pending": {m: x["do"] for m, x in pend.items() if x}, "trades": trades, "curve": curve, "days": len(curve)}


def _decide(m: str, bar: dict, pos: dict, pend: dict, book: str) -> None:
    line = bar.get("line")
    if line is None:
        return
    p = pos[m]
    if p and bar["c"] < line:
        pend[m] = {"do": "exit"}
    elif not p and bar["c"] > line:
        pend[m] = {"do": "enter", "stop": line * (1 - STOP_UNDER_LINE)}
    if p and book == "rules":
        p["stop"] = max(p["stop"], line * (1 - STOP_UNDER_LINE))


# ── the demo (MT5 demo account through Sentinel Live's executor) ─────────────

def _demo_rows(open_only: bool = False) -> list[dict]:
    live = _live()
    if live is None:
        return []
    rs = [r for r in live.rows(2000) if r.get("kind") == "drift"]
    return [r for r in rs if r["state"] in ("sent", "open")] if open_only else rs


def _skip(c: dict, key: str, market: str, reason: str, now: float, tell: bool = True) -> dict:
    """Record why an entry did not go out — once per signal day and reason, not every cycle."""
    kind = re.split(r"[\d$]", reason, maxsplit=1)[0].strip()[:40]      # the wording, not the numbers that move with price
    seen = c["skips"].setdefault(key, [])
    if kind in seen:
        return {"skipped": reason, "new": False}
    seen.append(kind)
    for k in sorted(c["skips"], key=lambda k: k.split(":")[-1])[:-40]:
        c["skips"].pop(k, None)
    live = _live()
    rid = "dk" + hashlib.sha1(f"{key}|{kind}".encode()).hexdigest()[:14]
    live._save({"id": rid, "kind": "drift", "at": now, "market": market, "tf": "1d", "dir": "buy", "grade": None,
                "symbol": c["symbols"].get(market), "state": "skipped", "reason": reason, "sig_key": key, "stop_moves": []})
    told = c.setdefault("told", {})
    if tell and told.get(market) != kind:              # once per kind of reason, not every day it persists
        told[market] = kind
        live._telegram(f"Drift · not entered {MARKET_BY_ID[market]['label']}: {reason}")
    return {"skipped": reason, "new": True}


def market_open(tick: Optional[tuple[int, float]], now: float) -> bool:
    """Inside Deriv's US index hours on a weekday, with a Deriv price from the last few minutes."""
    t = time.gmtime(now)
    return bool(tick and now - tick[0] <= FRESH_TICK_S and t.tm_wday < 5 and TRADE_HOURS_GMT[0] <= t.tm_hour < TRADE_HOURS_GMT[1])


def demo_step(sigs: dict[str, Optional[dict]], ticks: dict[str, Optional[tuple[int, float]]], now: Optional[float] = None) -> dict:
    """Bring the demo in line with the rules book's signal: enter above the line, raise the stop
    with the line, close under it. Sentinel Live's executor carries the orders out."""
    live = _live()
    now = now or time.time()
    out: dict[str, Any] = {}
    if live is None:
        return {"error": "Sentinel Live is not available"}
    c = cfg()
    open_rows = {r["market"]: r for r in _demo_rows(open_only=True)}
    for m in MARKETS:
        mid, sig = m["id"], sigs.get(m["id"])
        r = open_rows.get(mid)
        tick = ticks.get(mid)
        fresh = market_open(tick, now)
        if sig is None:
            out[mid] = "no 200-day line yet"
            continue
        if r:
            if r["state"] != "open" or r.get("close_wanted"):
                out[mid] = "waiting for MT5"
                continue
            if not fresh:
                out[mid] = "holding (market shut: changes wait for the open)"
            elif not sig["hold"]:
                r.update(close_wanted=True, close_after=now, exit_why="closed under the 200-day line")
                live._save(r)
                live._telegram(f"Drift · closing {m['label']}: the day closed under its 200-day line "
                               f"({sig['close']:g} vs {sig['line']:g})")
                out[mid] = "closing"
            elif sig["stop"] > (r.get("sl_target") or r["sl_initial"]) + 1e-9 and tick[1] > sig["stop"] * 1.002:
                r["sl_target"] = sig["stop"]                # Live's tick sends the move; only ever higher
                live._save(r)
                out[mid] = f"stop raised to {sig['stop']:g}"
            else:
                out[mid] = "holding"
            continue
        if not sig["hold"]:
            out[mid] = "aside: under the line"
            continue
        if not c.get("demo_on"):
            out[mid] = "demo off"
            continue
        key = f"{mid}:{sig['epoch']}"
        sent = [x for x in _demo_rows() if x.get("sig_key") == key and x["state"] != "skipped"]
        done_today = [x for x in _demo_rows() if x["market"] == mid and x["state"] == "closed"
                      and (x.get("closed_at") or 0) >= sig["epoch"] + DAY]
        if done_today or any(x["state"] in ("open", "closed") for x in sent):
            out[mid] = "traded or stopped today; next decision after today's close"
            continue
        if len(sent) >= MAX_SENDS_PER_SIGNAL:
            out[mid] = "MT5 refused it three times today; trying again after the next close"
            continue
        if not fresh:
            out[mid] = "market shut: entry waits for the open"
            continue
        out[mid] = _enter(c, m, sig, key, tick[1], now)
    _set_cfg(c)
    return out


def _enter(c: dict, m: dict, sig: dict, key: str, price: float, now: float) -> Any:
    live = _live()
    mid = m["id"]
    sym = (c.get("symbols") or {}).get(mid)
    view = live._view()
    if not sym:
        return _skip(c, key, mid, "no MT5 symbol set", now)
    if not view or not view.get("online"):
        return _skip(c, key, mid, "MT5 bridge offline", now, tell=False)
    acct = live._account(view)
    if acct.get("mode") != "demo":
        return _skip(c, key, mid, "the account is not a demo account — Drift runs on demo only", now)
    equity = float(acct.get("equity") or 0)
    if equity <= 0:
        return _skip(c, key, mid, "no equity reported by MT5", now, tell=False)
    spec = (live.cfg().get("specs") or {}).get(sym)
    if not spec or not spec.get("tickSize") or not spec.get("tickValue"):
        live.request_specs()
        return _skip(c, key, mid, f"no contract spec yet for {sym} (requested)", now, tell=False)
    stop = sig["stop"]
    if price <= stop * 1.002:
        return _skip(c, key, mid, "price is at the stop under the line", now, tell=False)
    per_unit = spec["tickValue"] / spec["tickSize"]                 # account money per 1.0 price move per lot
    per_lot = (price - stop) * per_unit
    rs = live._risk_state(now, equity)
    if rs["losses"] >= live.MAX_LOSSES_DAY:
        return _skip(c, key, mid, "three losing trades today — no new trades until tomorrow", now, tell=False)
    if rs["day_loss"] >= rs["day_cap"] - 0.005:
        return _skip(c, key, mid, "daily loss limit (3%) reached", now, tell=False)
    budget = min(equity * RISK_PCT_EACH / 100, rs["open_cap"] - rs["open_risk"], rs["day_cap"] - rs["day_loss"])
    step = spec.get("volStep") or 0.01
    vmin = spec.get("volMin") or step
    by_risk = max(0.0, budget) / per_lot if per_lot > 0 else 0
    by_size = CAP_EACH * equity / (price * per_unit)
    lots = math.floor(min(by_risk, by_size) / step + 1e-9) * step
    if spec.get("volMax"):
        lots = min(lots, spec["volMax"])
    lots = round(lots, 6)
    if lots < vmin - 1e-9:
        why = (f"only ${max(0.0, budget):.2f} of risk room left under the 2% open-risk cap"
               if budget < equity * RISK_PCT_EACH / 100 - 0.005 else
               f"minimum lot {vmin:g} would risk ${vmin * per_lot:.2f} = {100 * vmin * per_lot / equity:.2f}% (Drift uses {RISK_PCT_EACH:g}%)")
        return _skip(c, key, mid, why, now)
    cmd = live._new_id("dr")
    before = [str(p.get("ticket")) for p in ((view.get("snapshot") or {}).get("positions") or []) if isinstance(p, dict)]
    row = {"id": cmd, "kind": "drift", "at": now, "market": mid, "tf": "1d", "dir": "buy", "grade": None, "symbol": sym,
           "sig_key": key, "sig_close": sig["close"], "sig_line": sig["line"], "sentinel_entry": price, "sl_initial": stop,
           "sl_dist": price - stop, "sl_live": stop, "sl_target": stop, "per_lot": per_lot, "lots": lots,
           "risk_money": round(lots * per_lot, 2), "size": round(lots * price * per_unit, 2), "equity_at_entry": equity,
           "state": "sent", "cmd": cmd, "reason": None, "tickets_before": before, "stop_moves": []}
    try:
        live._B.enqueue(live._cid(), {"id": cmd, "type": "market", "symbol": sym, "side": "buy", "volume": lots, "sl": stop})
    except HTTPException as e:
        row.update(state="rejected", reason=f"could not send: {e.detail}")
    live._save(row)
    c.setdefault("told", {}).pop(mid, None)
    if row["state"] == "sent":
        live._telegram(f"Drift · buying {lots:g} {sym} (≈${row['size']:,.0f}, {100 * row['size'] / equity:.0f}% of equity) · "
                       f"stop {stop:g} = {RISK_PCT_EACH:g}% risk, 3% under the 200-day line ({sig['line']:g})")
    return {"sent": lots, "stop": stop}


def demo_summary(now: Optional[float] = None) -> dict:
    rs = _demo_rows()
    taken = [r for r in rs if r["state"] in ("open", "closed")]
    closed = [r for r in rs if r["state"] == "closed"]
    keep = ("id", "at", "market", "symbol", "state", "reason", "lots", "size", "risk_money", "risk_now", "equity_at_entry",
            "sentinel_entry", "fill", "sl_initial", "sl_live", "sl_target", "exit", "pnl", "r", "exit_reason", "exit_why",
            "closed_at", "sig_close", "sig_line")
    pnl = sum(r.get("pnl") or 0 for r in closed)
    return {"taken": len(taken), "open": sum(1 for r in taken if r["state"] == "open"), "closed": len(closed),
            "net": round(pnl, 2), "open_risk": round(sum(r.get("risk_now") if r.get("risk_now") is not None else (r.get("risk_money") or 0)
                                                         for r in rs if r["state"] in ("sent", "open")), 2),
            "rows": [{k: r.get(k) for k in keep} for r in ([r for r in rs if r["state"] != "skipped"][:40]
                                                            + [r for r in rs if r["state"] == "skipped"][:3])]}


# ── the per-cycle job ────────────────────────────────────────────────────────

async def fetch(call: Call, now: float) -> dict:
    """Read Deriv's daily candles (last year) and latest tick for each index; store whole days."""
    got = {}
    for m in MARKETS:
        have = _state["candles"].get(m["id"]) or len(load_candles(m["id"]))
        r = await call({"ticks_history": m["deriv"], "end": "latest", "count": 15 if have >= LINE_DAYS + 10 else 400,
                        "style": "candles", "granularity": DAY})
        if r.get("error"):
            _state["last_error"] = f"{m['label']}: {r['error'].get('message')}"
            continue
        store_candles(m["id"], complete(r.get("candles") or [], now))
        _state["candles"][m["id"]] = len(load_candles(m["id"]))
        t = await call({"ticks_history": m["deriv"], "end": "latest", "count": 1, "style": "ticks"})
        h = (t or {}).get("history") or {}
        got[m["id"]] = (int(h["times"][-1]), float(h["prices"][-1])) if h.get("times") else None
    _state["ticks"] = {k: v for k, v in got.items()}
    return got


def books(now: Optional[float] = None) -> dict:
    c = cfg()
    candles = {m["id"]: load_candles(m["id"]) for m in MARKETS}
    start = c.get("paper_start")
    sigs = {mid: signal(cs) for mid, cs in candles.items()}
    out = {"signals": sigs, "start": start, "books": {}}
    if start:
        for b in BOOKS:
            out["books"][b] = simulate(candles, start, b)
    return out


async def run_once(now: Optional[float] = None, call: Optional[Call] = None) -> dict:
    now = now or time.time()

    async def go(cl: Call) -> dict:
        ticks = await fetch(cl, now)
        c = cfg()
        state = books(now)
        sigs = state["signals"]
        if not c.get("paper_start"):
            last = [s["epoch"] for s in sigs.values() if s]
            if len(last) == len(MARKETS):
                c["paper_start"] = min(last)                 # the books start from the first day both lines exist
                _set_cfg(c)
        demo = {}
        if c.get("demo_on") or _demo_rows(open_only=True):
            demo = demo_step(sigs, ticks, now)
        return {"signals": sigs, "demo": demo}

    if call is not None:
        return await go(call)
    import websockets
    async with websockets.connect(core.DERIV_WS_URL, max_size=2 ** 24, open_timeout=15) as ws:
        async def ws_call(req: dict) -> dict:
            await ws.send(json.dumps(req))
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), 20))
                if m.get("msg_type") in ("history", "candles") or m.get("error"):
                    return m
        return await go(ws_call)


async def cycle() -> None:
    now = time.time()
    if _state["last_run"] and now - _state["last_run"] < RUN_EVERY_S:
        return
    try:
        out = await run_once(now)
        _state["last_run"] = now
        _state["last_demo"] = out.get("demo")
    except Exception as e:
        _state["last_error"] = f"{time.strftime('%H:%M:%S', time.gmtime())} {e}"
        log.warning("drift: %s", e)


# ── API ──────────────────────────────────────────────────────────────────────

def _book_view(b: dict) -> dict:
    out = {k: v for k, v in b.items() if k != "curve"}
    out["trades"] = list(reversed(b["trades"]))[:30]
    cv = b["curve"]
    pts = cv[:: max(1, len(cv) // 120)]
    if cv and pts[-1] != cv[-1]:
        pts.append(cv[-1])
    out["curve"] = pts
    return out


@router.get("/drift")
def drift_status(request: Request) -> dict:
    _S._check_key(request)
    c = cfg()
    st = books()
    live = _live()
    view = live._view() if live is not None else None
    acct = live._account(view) if live is not None else {}
    specs = (live.cfg().get("specs") or {}) if live is not None else {}
    errs = (live.cfg().get("spec_errors") or {}) if live is not None else {}
    need = {}
    for m in MARKETS:
        sp, sg = specs.get(c["symbols"].get(m["id"])), st["signals"].get(m["id"])
        if sp and sg and sp.get("tickSize") and sp.get("tickValue") and sg["close"] > sg["stop"]:
            risk_min_lot = (sp.get("volMin") or 0.01) * (sg["close"] - sg["stop"]) * sp["tickValue"] / sp["tickSize"]
            need[m["id"]] = {"min_lot": sp.get("volMin"), "risk_min_lot": round(risk_min_lot, 2),
                             "equity_needed": round(risk_min_lot / (RISK_PCT_EACH / 100), 0)}
    return {
        "version": RULES_VERSION,
        "rules": {"line_days": LINE_DAYS, "stop_under_line_pct": 100 * STOP_UNDER_LINE, "risk_pct_each": RISK_PCT_EACH,
                  "cap_each": CAP_EACH, "financing_pa_pct": 100 * FINANCING_PA, "spread_pct": 100 * SPREAD,
                  "paper_equity": PAPER_EQUITY, "demo_only": True},
        "markets": [{"id": m["id"], "label": m["label"], "symbol": c["symbols"].get(m["id"]),
                     "spec": bool(specs.get(c["symbols"].get(m["id"]))), "spec_error": errs.get(c["symbols"].get(m["id"]))} for m in MARKETS],
        "signals": st["signals"], "start": st["start"],
        "books": {k: _book_view(v) for k, v in st["books"].items()},
        "demo": dict(demo_summary(), on=bool(c.get("demo_on")), started=c.get("started"), stopped=c.get("stopped"),
                     bridge={"bound": bool(live and live._cid()), "online": bool(view and view.get("online")),
                             "mode": acct.get("mode"), "equity": acct.get("equity")},
                     last=_state.get("last_demo"), needs=need),
        "history": HISTORY,
        "state": {k: _state.get(k) for k in ("last_run", "last_error", "candles")},
    }


@router.post("/drift")
async def drift_control(request: Request) -> dict:
    _S._check_key(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Send JSON")
    action = str(body.get("action") or "")
    c = cfg()
    live = _live()
    if live is None:
        raise HTTPException(503, "Sentinel Live (the MT5 executor) is not available on this server")
    if action == "symbols":
        syms = body.get("symbols") or {}
        if not isinstance(syms, dict):
            raise HTTPException(400, "symbols must be {market: MT5 symbol}")
        for k, v in syms.items():
            if k in MARKET_BY_ID and isinstance(v, str) and 0 < len(v.strip()) <= 40:
                c["symbols"][k] = v.strip()
        _set_cfg(c)
        return {"ok": True, "symbols": c["symbols"], "checking": live.request_specs() if live._view() else []}
    if action == "start":
        view = live._view()
        if not live._cid():
            raise HTTPException(409, "Connect the MT5 bridge in Trade → Trade live first (it binds your account).")
        if not (view and view.get("online")):
            raise HTTPException(503, "The MT5 bridge is offline. Open MT5 with the EA running, then start.")
        if live._account(view).get("mode") != "demo":
            raise HTTPException(409, "The connected MT5 account is not a demo account. Drift runs on demo only.")
        c.update(demo_on=True, started=time.time(), stopped=None)
        _set_cfg(c)
        live.request_specs()
        _state["last_run"] = None                            # act on the next cycle, not in ten minutes
        live._telegram("Drift started on the demo: US Tech 100 and US 500 long above their 200-day lines, "
                       f"{RISK_PCT_EACH:g}% risk each at a stop 3% under the line")
        return {"ok": True}
    if action == "stop":
        c.update(demo_on=False, stopped=time.time())
        _set_cfg(c)
        live._telegram("Drift stopped by the owner — no new entries; open positions keep their stops and still close under the line")
        return {"ok": True}
    raise HTTPException(400, "Unknown action")
