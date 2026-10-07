"""
Joel Twin — Joel's own trade management, applied the same way every time.

For every MT5 position the server tracks on the owner's bridge account (the
`managed` journal in sentinel.py), the twin takes the same entry, the same side
and the same size, and manages it by fixed rules taken from Joel's framework
and his own stated habit. It never sends an order; it replays the position on
Deriv's public candles after Joel has closed it and records what the twin would
have made, so every trade reads "you vs your twin" in dollars.

  stop   Joel's first stop when it risks at most 1% of the account. Otherwise —
         no stop within a minute of the fill, a stop wider than 1%, or a position
         first seen after its fill — a stop at the 1% distance (ARIA's per-trade
         limit and Iron Stop Law: the twin always has one, never widens it).
  lock   once open profit reaches $100 per $36,900 of equity (Joel's rule: at
         +$100 move the stop to breakeven, then trail $100 behind the best price;
         scaled to the account so it means the same thing at any balance), the
         stop goes to breakeven and then trails that distance behind the best
         price. The stop never moves back.
  exit   the stop only, no target; at most 5 days.

Replay: 1-minute candles while Deriv still serves them (about a week), 15-minute
after that; the first bar used is the first full bar after the fill; inside a
bar the stop is checked before any favourable move (as every Sentinel book
does); a stop raised from a bar's best price that the same bar then closes through
exits at the stop; a bar that opens through the stop exits at its open; half the estimated
spread comes off the twin's exit price (Joel's entry price already paid it).

These rules are frozen as TWIN_VERSION. Changing any of them is a new version;
results of different versions are never mixed.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import time
from typing import Any, Optional

import sentinel_core as core

log = logging.getLogger("sentinel.twin")

TWIN_RULES = {
    "risk_cap_pct": 1.0,               # ARIA per-trade limit
    "lock_usd": 100.0,                 # Joel's $100 rule ...
    "lock_per_equity": 36900.0,        # ... on the $36.9k balance it was stated for
    "max_hold_s": 5 * 86400,
    "fine_gran_s": 60,                 # 1-minute candles while Deriv serves them
    "fine_max_age_s": 6 * 86400,
    "coarse_gran_s": 900,              # 15-minute candles after that
    "half_spread": True,
}
TWIN_VERSION = "twin-" + hashlib.sha1(json.dumps(TWIN_RULES, sort_keys=True).encode()).hexdigest()[:8]
MAX_PER_CYCLE = 4                      # positions replayed per scanner cycle (gentle on the public feed)
HISTORY_S = 365 * 86400

STOP_LABELS = {
    "yours": "your stop",
    "capped": "your stop was wider than 1%: twin used 1%",
    "added": "you had no stop: twin used 1%",
    "unknown": "your first stop is unknown (tracked after the fill): twin used 1%",
}


# ── MT5 symbol → Deriv public feed ───────────────────────────────────────────

def feed_market(symbol: Optional[str]) -> Optional[core.Market]:
    """The Deriv feed market behind an MT5 symbol name, or None.
    Inverse of the terminal's LIVE.guessSymbol()."""
    if not symbol:
        return None
    s = re.sub(r"\s+", " ", str(symbol).strip().lower())
    s = re.sub(r"[._-](?:[a-z]{1,3}|\d)$", "", s)          # broker suffixes: '.0', '.m', '-ecn'
    s = re.sub(r" index$", "", s)
    by = core.MARKET_BY_ID
    m = re.fullmatch(r"volatility (\d+) \(1s\)", s)
    if m:
        return by.get(f"1HZ{m.group(1)}V")
    m = re.fullmatch(r"volatility (\d+)", s)
    if m:
        return by.get(f"R_{m.group(1)}")
    m = re.fullmatch(r"(boom|crash) (\d+)", s)
    if m:
        k = f"{m.group(1).upper()}{m.group(2)}"
        return by.get(k) or by.get(k + "N")
    m = re.fullmatch(r"jump (\d+)", s)
    if m:
        return by.get(f"JD{m.group(1)}")
    if s == "step":
        return by.get("stpRNG")
    m = re.fullmatch(r"step (\d)00", s)
    if m:
        return by.get("stpRNG" if m.group(1) == "1" else f"stpRNG{m.group(1)}")
    m = re.fullmatch(r"range break (\d+)", s)
    if m:
        return by.get(f"RB{m.group(1)}")
    if s in ("us tech 100", "nas100", "ustec", "us100", "nasdaq 100"):
        return by.get("frxNAS100")
    m = re.fullmatch(r"([a-z]{6})", s)
    if m:
        k = m.group(1).upper()
        return by.get(f"frx{k}") or by.get(f"cry{k}")
    return None


# ── the twin's plan for one position ─────────────────────────────────────────

def per_unit_of(rec: dict) -> Optional[float]:
    """Money per 1.0 of price at the position's full size: recorded at the
    fill, or (older records) from the close when nothing was closed early."""
    v = rec.get("per_unit")
    if isinstance(v, (int, float)) and v > 0:
        return float(v)
    if any(e.get("type") == "partial" for e in rec.get("events") or []):
        return None
    px, pnl, entry = rec.get("exit_price"), rec.get("pnl"), rec.get("entry")
    if isinstance(px, (int, float)) and isinstance(pnl, (int, float)) and pnl and abs(px - entry) > 1e-12:
        return abs(pnl / (px - entry))
    return None


def equity_of(rec: dict, per_unit: float, fallback: Optional[float]) -> tuple[Optional[float], str]:
    v = rec.get("eq_open")
    if isinstance(v, (int, float)) and v > 0:
        return float(v), "at the fill"
    rp, rd = rec.get("risk_pct"), rec.get("r_dist")
    if isinstance(rp, (int, float)) and rp > 0 and isinstance(rd, (int, float)) and rd > 0:
        return 100.0 * per_unit * rd / rp, "from the recorded risk %"
    if fallback and fallback > 0:
        return float(fallback), "latest account equity"
    return None, "unknown"


def plan(rec: dict, equity_fallback: Optional[float] = None, rules: dict = TWIN_RULES) -> dict:
    """Everything the replay needs, or {"skip": reason}."""
    m = feed_market(rec.get("symbol"))
    if m is None:
        return {"skip": f"no public price feed for {rec.get('symbol')}"}
    try:
        entry, side, opened_ms = float(rec["entry"]), rec["side"], int(rec["opened"])
    except (KeyError, TypeError, ValueError):
        return {"skip": "position record incomplete"}
    if side not in ("buy", "sell"):
        return {"skip": "unknown side"}
    pu = per_unit_of(rec)
    if not pu:
        return {"skip": "money per point unknown (partly closed before tracking recorded it)"}
    eq, eq_src = equity_of(rec, pu, equity_fallback)
    if not eq:
        return {"skip": "account equity unknown"}
    s = 1 if side == "buy" else -1
    cap_px = rules["risk_cap_pct"] / 100.0 * eq / pu
    yours = rec.get("initial_sl")
    rd = abs(entry - yours) if isinstance(yours, (int, float)) and s * (yours - entry) < 0 else None
    if rec.get("late"):
        stop, src = entry - s * cap_px, "unknown"
    elif rd is None:
        stop, src = entry - s * cap_px, "added"
    elif rd > cap_px * 1.05:                       # lot steps round: 1.05% still counts as 1%
        stop, src = entry - s * cap_px, "capped"
    else:
        stop, src = float(yours), "yours"
    lock_px = rules["lock_usd"] / rules["lock_per_equity"] * eq / pu
    return {"market": m.id, "deriv": m.deriv, "side": side, "entry": entry, "opened_s": opened_ms // 1000,
            "per_unit": pu, "equity": round(eq, 2), "equity_source": eq_src, "stop0": stop, "stop_source": src,
            "risk_money": round(pu * abs(entry - stop), 2), "lock_px": lock_px,
            "lock_money": round(pu * lock_px, 2), "half_spread": (core.spread_for(m, entry) / 2.0) if rules["half_spread"] else 0.0}


def simulate(p: dict, bars: list[dict], gran: int, now_s: int, rules: dict = TWIN_RULES) -> dict:
    """Replay the twin on candles (oldest first). Pure: same input, same answer."""
    s = 1 if p["side"] == "buy" else -1
    entry, stop, lock = p["entry"], p["stop0"], p["lock_px"]
    first = -(-p["opened_s"] // gran) * gran              # first full bar after the fill (a fill on a bar boundary starts that bar)
    limit = p["opened_s"] + rules["max_hold_s"]
    best = entry
    armed_at = None
    out: dict[str, Any] = {"state": "open", "bars": 0, "gran": gran}
    last = None
    for b in bars:
        if b["time"] < first:
            continue
        last = b
        out["bars"] += 1
        bar_end = b["time"] + gran
        adverse = b["low"] if s > 0 else b["high"]
        if s * (b["open"] - stop) <= 0:                     # opened through the stop
            return _close(out, p, b["open"], "stop (gap)", bar_end, armed_at, best)
        if s * (adverse - stop) <= 0:                       # stop first
            return _close(out, p, stop, "stop", bar_end, armed_at, best)
        fav = b["high"] if s > 0 else b["low"]
        if s * (fav - best) > 0:
            best = fav
        if armed_at is None and s * (best - entry) >= lock - 1e-12:
            armed_at = bar_end
        if armed_at is not None:
            cand = best - s * lock
            if s * (cand - stop) > 0:
                stop = cand
                if s * (b["close"] - stop) <= 0:            # the close comes after the high: the new stop was crossed in this bar
                    return _close(out, p, stop, "stop", bar_end, armed_at, best)
        if bar_end >= limit:
            return _close(out, p, b["close"], "5-day limit", bar_end, armed_at, best)
    out.update(stop_now=stop, armed_at=armed_at, best=best, last_bar=last["time"] if last else None)
    if now_s >= limit + 2 * gran and last is not None:    # data ran out after the limit: close at the last bar
        return _close(out, p, last["close"], "5-day limit", last["time"] + gran, armed_at, best)
    return out


def _close(out: dict, p: dict, px: float, how: str, at: int, armed_at, best) -> dict:
    s = 1 if p["side"] == "buy" else -1
    exit_px = px - s * p["half_spread"]
    out.update(state="closed", exit_price=exit_px, how=how, closed_at=at, armed_at=armed_at,
               pnl=round(s * (exit_px - p["entry"]) * p["per_unit"], 2),
               r=round(s * (exit_px - p["entry"]) / abs(p["entry"] - p["stop0"]), 3),
               peak_money=round(s * (best - p["entry"]) * p["per_unit"], 2))
    return out


# ── candles from the public feed ─────────────────────────────────────────────

async def fetch_bars(deriv_sym: str, start_s: int, end_s: int, gran: int) -> list[dict]:
    """Closed candles covering [start_s, end_s], oldest first (pages backwards)."""
    import websockets
    out: list[dict] = []
    end: Any = int(end_s)
    async with websockets.connect(core.DERIV_WS_URL, max_size=2 ** 24, open_timeout=15) as ws:
        for _ in range(12):
            await ws.send(json.dumps({"ticks_history": deriv_sym, "adjust_start_time": 1, "start": int(start_s),
                                      "end": end, "count": 5000, "granularity": gran, "style": "candles"}))
            msg = json.loads(await asyncio.wait_for(ws.recv(), 20))
            if msg.get("error"):
                raise RuntimeError(f"{deriv_sym}: {msg['error'].get('message')}")
            page = [{"time": int(c["epoch"]), "open": float(c["open"]), "high": float(c["high"]),
                     "low": float(c["low"]), "close": float(c["close"])} for c in msg.get("candles", [])]
            if not page or (out and page[-1]["time"] >= out[0]["time"]):
                break
            out = page + out
            if page[0]["time"] <= start_s:
                break
            end = page[0]["time"] - 1
    now = time.time()
    return [b for b in out if b["time"] + gran <= now]       # closed bars only


# ── persistence and the per-cycle job ────────────────────────────────────────

_S = None               # the sentinel module (set by attach)
_state: dict[str, Any] = {"last_run": None, "last_error": None, "done": 0}


def attach(sentinel_module) -> None:
    global _S
    _S = sentinel_module


def _table(con) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS twin (
        key TEXT PRIMARY KEY, version TEXT, final INTEGER, updated INTEGER, data TEXT)""")


def load_all() -> dict[str, dict]:
    with _S._lock, _S._db() as con:
        _table(con)
        rows = con.execute("SELECT key, data FROM twin WHERE version=?", (TWIN_VERSION,)).fetchall()
    return {k: json.loads(d) for k, d in rows}


def _save(key: str, data: dict, final: bool) -> None:
    with _S._lock, _S._db() as con:
        _table(con)
        con.execute("INSERT OR REPLACE INTO twin VALUES (?,?,?,?,?)",
                    (key, TWIN_VERSION, 1 if final else 0, int(time.time()), json.dumps(data)))


def pending(records: list[dict], done: dict[str, dict], now_s: int) -> list[dict]:
    """Closed MT5 positions of the last year whose twin is not final yet, newest first."""
    out = []
    for r in records:
        if not str(r.get("key", "")).startswith("mt5:") or not r.get("closed"):
            continue
        if now_s - int(r.get("opened") or 0) // 1000 > HISTORY_S:
            continue
        d = done.get(r["key"])
        if d and d.get("final"):
            continue
        out.append(r)
    # least recently tried first, then newest: a twin still running never starves the others
    out.sort(key=lambda r: ((done.get(r["key"]) or {}).get("tried", 0), -(r.get("opened") or 0)))
    return out


async def run_once(now_s: Optional[int] = None, fetch=None, limit: int = MAX_PER_CYCLE) -> int:
    """Replay up to `limit` pending positions. Returns how many were updated."""
    now_s = int(now_s or time.time())
    fetch = fetch or fetch_bars
    done = load_all()
    todo = pending(_S._managed_rows(), done, now_s)[:limit]
    eq_fb = _S._mt5_state.get("equity") if hasattr(_S, "_mt5_state") else None
    n = 0
    for rec in todo:
        p = plan(rec, eq_fb)
        if "skip" in p:
            _save(rec["key"], {"final": True, "skip": p["skip"]}, True)
            n += 1
            continue
        age = now_s - p["opened_s"]
        gran = TWIN_RULES["fine_gran_s"] if age <= TWIN_RULES["fine_max_age_s"] else TWIN_RULES["coarse_gran_s"]
        end = min(now_s, p["opened_s"] + TWIN_RULES["max_hold_s"] + gran)
        try:
            bars = await fetch(p["deriv"], p["opened_s"] - gran, end, gran)
        except Exception as e:
            _state["last_error"] = f"{rec['key']}: {e}"
            log.warning("twin %s: %s", rec["key"], e)
            continue
        sim = simulate(p, bars, gran, now_s)
        final = sim["state"] == "closed"
        data = {"final": final, "tried": now_s, "plan": {k: v for k, v in p.items() if k != "deriv"}, "sim": sim,
                "you": {"pnl": rec.get("pnl"), "exit_price": rec.get("exit_price"), "exit_reason": rec.get("exit_reason"),
                        "closed": rec.get("closed")}}
        _save(rec["key"], data, final)
        n += 1
    _state.update(last_run=now_s, done=_state["done"] + n)
    return n


async def cycle() -> None:
    """Called after every scanner cycle; never lets an error out."""
    try:
        await asyncio.wait_for(run_once(), timeout=90)
    except Exception as e:
        _state["last_error"] = f"{time.strftime('%H:%M:%S', time.gmtime())} {e}"
        log.warning("twin cycle: %s", e)


# ── results ─────────────────────────────────────────────────────────────────

def summary(t: Optional[dict]) -> Optional[dict]:
    """The compact per-trade view the journal shows."""
    if not t:
        return None
    if t.get("skip"):
        return {"skip": t["skip"]}
    sim, p = t.get("sim") or {}, t.get("plan") or {}
    out = {"final": bool(t.get("final")), "stop_source": p.get("stop_source"),
           "stop_label": STOP_LABELS.get(p.get("stop_source"), ""), "risk_money": p.get("risk_money"),
           "lock_money": p.get("lock_money"), "gran": sim.get("gran")}
    if sim.get("state") == "closed":
        out.update(pnl=sim["pnl"], r=sim["r"], how=sim["how"], closed_at=sim["closed_at"], locked=bool(sim.get("armed_at")))
    return out


def stats(pairs: list[tuple[dict, dict]]) -> dict:
    """Paired 'you vs twin' over positions where both are closed. pairs = [(managed record, twin summary)]."""
    rows = [(r, t) for r, t in pairs if t and t.get("final") and "pnl" in t and isinstance(r.get("pnl"), (int, float))]
    n = len(rows)
    skipped = sum(1 for _, t in pairs if t and t.get("skip"))
    if not n:
        return {"n": 0, "skipped": skipped, "version": TWIN_VERSION}
    you = [r["pnl"] for r, _ in rows]
    twin = [t["pnl"] for _, t in rows]
    d = [b - a for a, b in zip(you, twin)]
    md = sum(d) / n
    sd = math.sqrt(sum((x - md) ** 2 for x in d) / (n - 1)) if n > 1 else 0.0
    by: dict[str, dict] = {}
    for (r, t), a, b in zip(rows, you, twin):
        g = by.setdefault(t.get("stop_source") or "?", {"n": 0, "you": 0.0, "twin": 0.0})
        g["n"] += 1
        g["you"] = round(g["you"] + a, 2)
        g["twin"] = round(g["twin"] + b, 2)
    return {
        "n": n, "skipped": skipped, "version": TWIN_VERSION,
        "you_total": round(sum(you), 2), "twin_total": round(sum(twin), 2),
        "diff_per_trade": round(md, 2),
        "diff_ci95": [round(md - 1.96 * sd / math.sqrt(n), 2), round(md + 1.96 * sd / math.sqrt(n), 2)] if n > 1 else None,
        "twin_better": sum(1 for x in d if x > 0.005), "you_better": sum(1 for x in d if x < -0.005),
        "you_worst": round(min(you), 2), "twin_worst": round(min(twin), 2),
        "by_stop_source": by,
    }


def rules_text() -> list[str]:
    r = TWIN_RULES
    return [f"Same entry, side and size as your trade.",
            f"Stop: yours if it risks at most {r['risk_cap_pct']:g}% of the account; otherwise a stop at {r['risk_cap_pct']:g}%.",
            f"At +${r['lock_usd']:g} per ${r['lock_per_equity']:,.0f} of equity the stop goes to breakeven, then trails that distance behind the best price.",
            "No target. Exit on the stop, or after 5 days.",
            "Replayed on Deriv's candles after you close; never places an order."]
