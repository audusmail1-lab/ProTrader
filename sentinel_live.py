"""
Sentinel Live test — one month on the owner's MT5 DEMO account.

Sentinel places and manages its own A-grade setups (the four candidate
slices) on the MT5 account whose bridge is bound as the owner's channel:

  entry     market order the moment Sentinel's paper trade opens, stop at
            Sentinel's stop, no fixed target (ARIA 7.2c)
  size      1% of current equity at the stop, from the EA's own contract
            spec; skipped (and recorded) when even the minimum lot is more
  managing  every stop move Sentinel makes (breakeven at +1R, then trailing
            1R behind the best price) is sent to MT5; Sentinel's 96-bar
            timeout closes the position
  limits    at most 2% open risk, stop after a 3% daily loss or 3 losing
            trades in a day — checked here AND by the EA, which has the final
            say (and refuses real accounts unless AllowRealAccount is set)

Demo only: an entry is never sent when the EA reports a real account. The
test runs for 30 days from Start; after that no new entries are made and open
positions are managed to the end. Every decision is journaled — trades taken,
skipped (with the reason) and rejected — so the month can be judged on trade
quality, rule adherence, drawdown and consistency, not profit alone.

Endpoints (owner: instructor session or owner key)
  GET  /api/sentinel/live                 status, rules, journal, metrics
  POST /api/sentinel/live {action}        start | stop | check | symbols
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import secrets
import threading
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

log = logging.getLogger("sentinel.live")
router = APIRouter(tags=["sentinel-live"])          # included into the /api/sentinel router

DAYS = 30
RISK_PCT = 1.0
OPEN_RISK_PCT = 2.0
DAILY_LOSS_PCT = 3.0
MAX_LOSSES_DAY = 3
GRADES = ("A", "A+")
DEFAULT_SYMBOLS = {"frxNAS100": "US Tech 100", "frxXAUUSD": "XAUUSD", "cryBTCUSD": "BTCUSD"}
SPEC_MAX_AGE = 6 * 3600
RETRY_S = 20
TICK_S = 3.0

_S = None                  # the sentinel module (set by attach)
_B = None                  # the mt5_bridge module
_task: Optional[asyncio.Task] = None


def attach(sentinel_module, bridge_module) -> None:
    global _S, _B
    _S, _B = sentinel_module, bridge_module
    with _S._lock, _S._db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS live_trades (
            id TEXT PRIMARY KEY, opened INTEGER, closed INTEGER, data TEXT)""")


# ── storage ─────────────────────────────────────────────────────────────────

def cfg() -> dict:
    c = _S._meta_get("live_cfg", None) or {}
    c.setdefault("on", False)
    c.setdefault("symbols", dict(DEFAULT_SYMBOLS))
    return c


def _set_cfg(c: dict) -> None:
    _S._meta_set("live_cfg", c)


def _save(row: dict) -> None:
    with _S._lock, _S._db() as con:
        con.execute("INSERT OR REPLACE INTO live_trades VALUES (?,?,?,?)",
                    (row["id"], int(row.get("at") or 0), int(row.get("closed_at") or 0) or None, json.dumps(row)))


def rows(limit: int = 500) -> list[dict]:
    with _S._lock, _S._db() as con:
        got = con.execute("SELECT data FROM live_trades ORDER BY opened DESC LIMIT ?", (limit,)).fetchall()
    return [json.loads(r[0]) for r in got]


def _row(rid: str) -> Optional[dict]:
    with _S._lock, _S._db() as con:
        r = con.execute("SELECT data FROM live_trades WHERE id=?", (rid,)).fetchone()
    return json.loads(r[0]) if r else None


def _open_rows() -> list[dict]:
    return [r for r in rows() if r["state"] in ("sent", "open")]


def _cid() -> Optional[str]:
    return _S._mt5_owner_channel()


def _view() -> Optional[dict]:
    cid = _cid()
    return _B.view(cid) if (cid and _B) else None


def _new_id(prefix: str) -> str:
    return prefix + secrets.token_hex(8)


def _telegram(text: str) -> None:
    """Off the caller's thread: tick() runs on the event loop and on_open under
    the scanner — a Telegram call that waits out its 10 s timeout must stall
    neither. Messages are rare, so one short-lived thread each is fine."""
    threading.Thread(target=_telegram_now, args=(text,), daemon=True, name="sentinel-live-tg").start()


def _telegram_now(text: str) -> None:
    try:
        _S._telegram("Sentinel Live (demo) · " + text)
    except Exception:
        pass


# ── the test window ─────────────────────────────────────────────────────────

def active(now: Optional[float] = None) -> bool:
    c = cfg()
    now = now or time.time()
    return bool(c.get("on")) and c.get("started", 0) <= now < c.get("ends", 0)


def _account(view: Optional[dict]) -> dict:
    snap = (view or {}).get("snapshot") or {}
    return snap.get("account") or {}


def _day_start(now: float) -> float:
    return now - (now % 86400)          # UTC day


def _risk_state(now: float, equity: float) -> dict:
    """What the framework still allows right now, from this test's own trades."""
    rs = rows()
    open_risk = sum((r["risk_now"] if r.get("risk_now") is not None else r.get("risk_money") or 0)
                    for r in rs if r["state"] in ("sent", "open"))
    today = [r for r in rs if r["state"] == "closed" and (r.get("closed_at") or 0) >= _day_start(now)]
    day_pnl = sum(r.get("pnl") or 0 for r in today)
    losses = sum(1 for r in today if (r.get("pnl") or 0) < -0.005)
    return {"open_risk": open_risk, "open_cap": equity * OPEN_RISK_PCT / 100,
            "day_loss": max(0.0, -day_pnl), "day_cap": equity * DAILY_LOSS_PCT / 100, "losses": losses}


# ── entries ─────────────────────────────────────────────────────────────────

def on_open(t) -> Optional[dict]:
    """Sentinel just opened a paper trade. Take it live if it qualifies."""
    if not active():
        return None
    grade = t.grade
    if grade not in GRADES:
        return None
    c = cfg()
    sym = (c.get("symbols") or {}).get(t.market)
    now = time.time()
    row = {"id": t.id, "at": now, "market": t.market, "tf": t.tf, "dir": t.dir, "grade": grade,
           "symbol": sym, "sentinel_entry": t.entry, "sl_initial": t.sl, "sl_dist": t.sl_dist,
           "score": t.score, "state": "skipped", "stop_moves": []}

    def skip(reason: str) -> dict:
        row["reason"] = reason
        _save(row)
        _telegram(f"skipped {t.market} {t.tf} {t.dir}: {reason}")
        return row

    if not sym:
        return skip("no MT5 symbol set for this market")
    view = _view()
    if not view or not view["online"]:
        return skip("MT5 bridge offline at the signal (no late entries)")
    acct = _account(view)
    if acct.get("mode") != "demo":
        return skip("the account is not a demo account — this test runs on demo only")
    equity = float(acct.get("equity") or 0)
    if equity <= 0:
        return skip("no equity reported by MT5")
    spec = (c.get("specs") or {}).get(sym)
    if not spec or not spec.get("tickSize") or not spec.get("tickValue"):
        request_specs()
        return skip(f"no contract spec yet for {sym} (requested — run Check symbols)")
    per_lot = t.sl_dist / spec["tickSize"] * spec["tickValue"]
    budget = equity * RISK_PCT / 100
    rs = _risk_state(now, equity)
    if rs["losses"] >= MAX_LOSSES_DAY:
        return skip("three losing trades today — no new trades until tomorrow")
    if rs["day_loss"] >= rs["day_cap"] - 0.005:
        return skip("daily loss limit (3%) reached")
    budget = min(budget, rs["open_cap"] - rs["open_risk"], rs["day_cap"] - rs["day_loss"])
    step = spec.get("volStep") or 0.01
    vmin = spec.get("volMin") or step
    lots = math.floor(max(0.0, budget) / per_lot / step + 1e-9) * step if per_lot > 0 else 0
    if spec.get("volMax"):
        lots = min(lots, spec["volMax"])
    lots = round(lots, 6)
    if lots < vmin - 1e-9:
        pct = 100 * vmin * per_lot / equity
        why = (f"minimum lot {vmin:g} would risk ${vmin * per_lot:.2f} = {pct:.1f}% of equity (limit {RISK_PCT:g}%)"
               if budget >= equity * RISK_PCT / 100 - 0.005 else
               f"only ${max(0.0, budget):.2f} of risk room left under the 2% open-risk cap")
        return skip(why)
    cmd = _new_id("sl")
    before = [str(p.get("ticket")) for p in ((view.get("snapshot") or {}).get("positions") or []) if isinstance(p, dict)]
    row.update(state="sent", cmd=cmd, lots=lots, risk_money=round(lots * per_lot, 2), equity_at_entry=equity,
               per_lot=per_lot, sl_live=t.sl, sl_target=t.sl, reason=None, tickets_before=before)
    try:
        _B.enqueue(_cid(), {"id": cmd, "type": "market", "symbol": sym, "side": t.dir,
                            "volume": lots, "sl": t.sl})
    except HTTPException as e:
        row.update(state="skipped", reason=f"could not send: {e.detail}")
    _save(row)
    if row["state"] == "sent":
        _telegram(f"sending {t.dir.upper()} {lots:g} {sym} · SL {t.sl:g} · risk ${row['risk_money']:.2f} "
                  f"({100 * row['risk_money'] / equity:.2f}%) · {t.market} {t.tf} {grade}")
    return row


# ── management ──────────────────────────────────────────────────────────────

def on_update(t) -> None:
    """Sentinel advanced a paper trade (stop move, close). Mirror it."""
    r = _row(t.id)
    if not r:
        return
    changed = False
    if t.status != "open":
        if r.get("paper_r") is None and t.r is not None:
            r["paper_r"], r["paper_status"] = t.r, t.status
            changed = True
        if r["state"] in ("sent", "open") and not r.get("close_wanted"):
            # Sentinel's trade is over (timeout, or its stop on the Deriv feed).
            # A timeout closes at once; after a stop, MT5's own stop normally
            # closes the position first — close it after a minute if not.
            r["close_wanted"] = True
            r["close_after"] = time.time() + (0 if t.status == "timeout" else 60)
            changed = True
    elif r["state"] in ("sent", "open") and t.stop is not None:
        s = 1 if r["dir"] == "buy" else -1
        if s * (t.stop - (r.get("sl_target") or r["sl_initial"])) > 1e-12:
            r["sl_target"] = t.stop                    # only ever tighter
            changed = True
    if changed:
        _save(r)


def _results(view: dict) -> dict:
    return {x.get("id"): x for x in (view.get("results") or []) if isinstance(x, dict)}


def _orphan_for(r: dict, positions: dict) -> Optional[dict]:
    """The position a sent order filled when MT5's answer was lost: one of ours
    (the EA's magic number), on this symbol and side with these lots, that was
    not open when the order went out and that no other row owns. Rows from
    before this check (no `tickets_before`) are never matched — a position
    that predates the order could be mistaken for its fill."""
    if "tickets_before" not in r:
        return None
    before = set(r["tickets_before"] or [])
    owned = {str(x.get("ticket")) for x in rows() if x.get("ticket") and x["id"] != r["id"]}
    for tk, p in positions.items():
        if tk in before or tk in owned or p.get("mine") is False:
            continue
        if p.get("symbol") != r["symbol"] or p.get("side") != r["dir"]:
            continue
        try:
            if abs(float(p.get("volume")) - float(r["lots"])) > 1e-6:
                continue
        except (TypeError, ValueError):
            continue
        return p
    return None


def request_specs() -> list[str]:
    c = cfg()
    want = c.setdefault("spec_pending", {})
    sent = []
    for sym in sorted(set((c.get("symbols") or {}).values())):
        cmd = _new_id("ls")
        try:
            _B.enqueue(_cid(), {"id": cmd, "type": "spec", "symbol": sym})
            want[cmd] = sym
            sent.append(sym)
        except HTTPException as e:
            c.setdefault("spec_errors", {})[sym] = str(e.detail)
    _set_cfg(c)
    return sent


# ── bridge availability ──────────────────────────────────────────────────────
# How often is the owner's MT5 bridge actually reachable? Sampled on every
# live tick (3 s), rolled up per UTC minute and per day, with the gaps kept.
# A minute counts as seen when any sample in it saw the EA online; a minute
# with no sample at all (the server itself was down or restarting) is
# "unobserved", not offline. Gaps shorter than AVAIL_GAP_S are ignored: a
# relay restart or one dropped poll is not an outage.

AVAIL_KEY = "bridge_avail"
AVAIL_DAYS = 31
AVAIL_GAP_S = 120
AVAIL_MAX_GAPS = 300
_avail: Optional[dict] = None


def _avail_state() -> dict:
    global _avail
    if _avail is None:
        _avail = _S._meta_get(AVAIL_KEY, None) or {}
        _avail.setdefault("days", {})
        _avail.setdefault("gaps", [])
    return _avail


def _avail_day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def avail_sample(online: bool, now: float) -> None:
    """Record one sample of the bridge's state. Writes to the database at most
    once a minute, plus on every online/offline transition."""
    a = _avail_state()
    minute = int(now // 60)
    write = False
    if a.get("minute") != minute:
        if a.get("minute") is not None:
            d = a["days"].setdefault(_avail_day(a["minute"] * 60), {"seen": 0, "obs": 0})
            d["obs"] += 1
            if a.get("minute_seen"):
                d["seen"] += 1
            for old in [k for k in a["days"] if k < _avail_day(now - AVAIL_DAYS * 86400)]:
                a["days"].pop(old, None)
            a["gaps"] = a["gaps"][-AVAIL_MAX_GAPS:]
        a["minute"], a["minute_seen"], write = minute, bool(online), True
    else:
        a["minute_seen"] = bool(a.get("minute_seen")) or bool(online)
    state = "online" if online else "offline"
    if a.get("state") != state:
        if a.get("state") == "offline" and a.get("open_gap") is not None:
            if now - a["open_gap"] >= AVAIL_GAP_S:
                a["gaps"].append([round(a["open_gap"]), round(now)])
            a["open_gap"] = None
        if state == "offline":
            a["open_gap"] = now
        a["state"], a["since"], write = state, now, True
    a["last_sample"] = now
    if write:
        _S._meta_set(AVAIL_KEY, a)


def avail_report(now: Optional[float] = None) -> dict:
    """What the Sentinel tab shows: availability today / 7 days / 30 days,
    the gaps, and what is unobserved."""
    now = now or time.time()
    a = _avail_state()
    days = a.get("days") or {}
    today = _avail_day(now)
    minute = int(now // 60)
    cur = {"seen": 1 if a.get("minute_seen") else 0, "obs": 1} if a.get("minute") == minute else {"seen": 0, "obs": 0}

    def span(n: int) -> dict:
        keys = [_avail_day(now - i * 86400) for i in range(n)]
        seen = sum(days.get(k, {}).get("seen", 0) for k in keys) + cur["seen"]
        obs = sum(days.get(k, {}).get("obs", 0) for k in keys) + cur["obs"]
        return {"seen": seen, "obs": obs, "pct": round(100 * seen / obs, 1) if obs else None}

    t = days.get(today, {"seen": 0, "obs": 0})
    elapsed = int((now % 86400) // 60) + 1
    gaps = [{"start": g[0], "end": g[1], "minutes": round((g[1] - g[0]) / 60)} for g in (a.get("gaps") or [])[-10:]]
    open_gap = a.get("open_gap")
    if a.get("state") == "offline" and open_gap is not None and now - open_gap >= AVAIL_GAP_S:
        gaps.append({"start": round(open_gap), "end": None, "minutes": round((now - open_gap) / 60)})
    return {
        "state": a.get("state"), "since": a.get("since"), "last_sample": a.get("last_sample"),
        "today": {"seen": t["seen"] + cur["seen"], "obs": t["obs"] + cur["obs"], "elapsed": elapsed,
                  "unobserved": max(0, elapsed - t["obs"] - cur["obs"]),
                  "pct": round(100 * (t["seen"] + cur["seen"]) / (t["obs"] + cur["obs"]), 1) if (t["obs"] + cur["obs"]) else None},
        "d7": span(7), "d30": span(30),
        "gaps": list(reversed(gaps)),
        "gap_min_s": AVAIL_GAP_S,
        "days_recorded": len(days) + (0 if today in days else (1 if cur["obs"] else 0)),
    }


def tick(now: Optional[float] = None) -> None:
    """Every few seconds: read EA results, send pending stop moves and
    closes, detect closed positions, track the equity curve."""
    view = _view()
    now = now or time.time()
    if _cid():
        try:
            avail_sample(bool(view and view.get("online")), now)
        except Exception as e:                  # the record must never stop the tick
            log.warning("availability: %s", e)
    if not view:
        return
    res = _results(view)
    c = cfg()
    # contract specs
    pend = c.get("spec_pending") or {}
    if pend:
        for cmd, sym in list(pend.items()):
            x = res.get(cmd)
            if not x:
                continue
            pend.pop(cmd)
            if x.get("ok") and isinstance(x.get("spec"), dict):
                c.setdefault("specs", {})[sym] = dict(x["spec"], at=now)
                c.setdefault("spec_errors", {}).pop(sym, None)
            else:
                c.setdefault("spec_errors", {})[sym] = x.get("msg") or "spec failed"
        _set_cfg(c)
    if active(now) and view.get("online") and not pend:
        old = [s for s in set((c.get("symbols") or {}).values())
               if now - ((c.get("specs") or {}).get(s) or {}).get("at", 0) > SPEC_MAX_AGE]
        if old and now - c.get("spec_asked", 0) > 600:
            c["spec_asked"] = now
            _set_cfg(c)
            request_specs()
            c = cfg()
    # equity curve (for drawdown), only while the test is running or trades are open
    acct = _account(view)
    eq = acct.get("equity")
    if c.get("started") and isinstance(eq, (int, float)) and eq > 0 and (active(now) or _open_rows()):
        curve = c.setdefault("curve", {"start": eq, "peak": eq, "low": eq, "max_dd_pct": 0.0, "last": eq})
        curve["peak"] = max(curve["peak"], eq)
        curve["low"] = min(curve["low"], eq)
        curve["last"] = eq
        dd = 100 * (curve["peak"] - eq) / curve["peak"] if curve["peak"] > 0 else 0
        if dd > curve["max_dd_pct"] + 0.01 or now - c.get("curve_saved", 0) > 300:
            curve["max_dd_pct"] = round(max(curve["max_dd_pct"], dd), 3)
            c["curve_saved"] = now
            _set_cfg(c)
    snap = view.get("snapshot") or {}
    positions = {str(p.get("ticket")): p for p in (snap.get("positions") or []) if isinstance(p, dict)}
    deals = {str(d.get("ticket")): d for d in ((view.get("history") or {}).get("deals") or [])
             if isinstance(d, dict) and d.get("kind") == "trade"}
    for r in _open_rows():
        dirty = False
        if r["state"] == "sent":
            x = res.get(r["cmd"])
            if x and x.get("ok"):
                fill = float(x.get("price") or r["sentinel_entry"])
                s = 1 if r["dir"] == "buy" else -1
                r.update(state="open", ticket=str(x.get("ticket")), fill=fill, filled_at=now,
                         lots=float(x.get("volume") or r["lots"]),
                         slip_r=round(-s * (fill - r["sentinel_entry"]) / r["sl_dist"], 4))
                r["risk_now"] = r["risk_actual"] = round(abs(fill - r["sl_initial"]) / r["sl_dist"] * r["per_lot"] * r["lots"], 2)
                _telegram(f"filled {r['dir'].upper()} {r['lots']:g} {r['symbol']} @ {fill:g} (slippage {r['slip_r']:+.2f}R)")
                dirty = True
            elif x and "Risk at stop" in (x.get("msg") or "") and not r.get("resized"):
                # price moved a little against the entry since the signal, so the
                # EA's own 1% check failed: one lot step smaller, once, right away
                step = ((c.get("specs") or {}).get(r["symbol"]) or {}).get("volStep") or 0.01
                vmin = ((c.get("specs") or {}).get(r["symbol"]) or {}).get("volMin") or step
                lots = round(r["lots"] - step, 6)
                if lots >= vmin - 1e-9:
                    cmd = _new_id("sl")
                    try:
                        _B.enqueue(_cid(), {"id": cmd, "type": "market", "symbol": r["symbol"], "side": r["dir"],
                                            "volume": lots, "sl": r["sl_initial"]})
                        r.update(cmd=cmd, lots=lots, risk_money=round(lots * r["per_lot"], 2), resized=True, at=now)
                    except HTTPException as e:
                        r.update(state="rejected", reason=f"{x.get('msg')} — resend failed: {e.detail}")
                else:
                    r.update(state="rejected", reason=x.get("msg"))
                dirty = True
            elif x:
                r.update(state="rejected", reason=x.get("msg") or "rejected by the EA")
                _telegram(f"MT5 rejected {r['symbol']}: {r['reason']}")
                dirty = True
            elif now - r["at"] > 60:
                # No answer in 60 s. The EA may well have filled it and the result
                # been lost (relay restart, results ring overrun): a live position
                # must not be forgotten and run outside the risk caps. Adopt the
                # fill if the snapshot shows it; only then give the order up.
                p = _orphan_for(r, positions)
                if p:
                    fill = float(p.get("entry") or r["sentinel_entry"])
                    s = 1 if r["dir"] == "buy" else -1
                    r.update(state="open", ticket=str(p.get("ticket")), fill=fill, filled_at=now, adopted=True,
                             lots=float(p.get("volume") or r["lots"]),
                             slip_r=round(-s * (fill - r["sentinel_entry"]) / r["sl_dist"], 4))
                    r["risk_now"] = r["risk_actual"] = round(abs(fill - r["sl_initial"]) / r["sl_dist"] * r["per_lot"] * r["lots"], 2)
                    _telegram(f"adopted {r['dir'].upper()} {r['lots']:g} {r['symbol']} @ {fill:g} — filled, but MT5's answer was lost")
                else:
                    r.update(state="rejected", reason="no answer from MT5 within 60 s and no matching position")
                dirty = True
        if r["state"] == "open":
            p = positions.get(r.get("ticket"))
            if p is None and now - (r.get("filled_at") or now) > 8:
                d = deals.get(r.get("ticket"))
                if not d and now - (r.get("filled_at") or now) > 900 and not r.get("gone_since"):
                    r["gone_since"] = now                      # start the clock on an unexplained disappearance
                    dirty = True
                elif not d and r.get("gone_since") and now - r["gone_since"] > 900:
                    # 15 min gone and no deal reported (history limited to 200 deals, or
                    # closed from another terminal): not open any more, P&L unknown
                    r.update(state="closed", closed_at=now, exit=None, pnl=None, r=None,
                             exit_reason="unknown — position gone, no deal in the MT5 history received", manual=True)
                    _telegram(f"{r['symbol']} is no longer open on MT5 and no deal was reported — marked closed, P&L unknown")
                    dirty = True
                if d:
                    pnl = float(d.get("profit") or 0)
                    risk = r.get("risk_actual") or r.get("risk_money") or 0
                    r.update(state="closed", closed_at=now, exit=d.get("exit"), pnl=round(pnl, 2),
                             r=round(pnl / risk, 3) if risk > 0 else None, exit_reason=d.get("reason"),
                             manual=d.get("reason") == "Manual")
                    _telegram(f"closed {r['symbol']} ({d.get('reason')}): ${pnl:+.2f} = {r['r'] if r['r'] is not None else '?'}R")
                    dirty = True
            elif p is not None:
                live_sl = float(p.get("sl") or 0) or None
                if live_sl and r.get("sl_live") and abs(live_sl - r["sl_live"]) > 1e-9 and not r.get("mod_cmd"):
                    r["sl_live"] = live_sl
                    r["manual_sl"] = True                   # someone moved the stop by hand
                    dirty = True
                if live_sl:
                    s = 1 if r["dir"] == "buy" else -1
                    r["risk_now"] = round(max(0.0, -s * (live_sl - r["fill"])) / r["sl_dist"] * r["per_lot"] * r["lots"], 2)
                # a stop move Sentinel asked for
                m = r.get("mod_cmd")
                if m:
                    x = res.get(m["id"])
                    if x:
                        r["stop_moves"].append({"at": now, "to": m["to"], "ok": bool(x.get("ok")),
                                                "msg": None if x.get("ok") else x.get("msg"),
                                                "lag_s": round(now - m["asked"], 1)})
                        if x.get("ok"):
                            r["sl_live"] = m["to"]
                        r.pop("mod_cmd")
                        dirty = True
                    elif now - m["sent"] > 60:
                        r.pop("mod_cmd"); dirty = True
                want = r.get("sl_target")
                if (not r.get("mod_cmd") and want and r.get("sl_live") and abs(want - r["sl_live"]) > 1e-9
                        and (want != r.get("mod_last_to") or now - r.get("mod_tried", 0) > RETRY_S)):
                    cmd = _new_id("lm")
                    try:
                        _B.enqueue(_cid(), {"id": cmd, "type": "modify", "ticket": r["ticket"], "sl": want})
                        r["mod_cmd"] = {"id": cmd, "to": want, "sent": now, "asked": r.get("sl_asked", now)}
                        r.setdefault("sl_asked", now)
                    except HTTPException:
                        pass
                    r["mod_tried"], r["mod_last_to"] = now, want
                    dirty = True
                if r.get("sl_live") == want:
                    r.pop("sl_asked", None)
                if (r.get("close_wanted") and now >= r.get("close_after", 0) and not r.get("close_cmd")
                        and now - r.get("close_tried", 0) > RETRY_S):
                    cmd = _new_id("lc")
                    try:
                        _B.enqueue(_cid(), {"id": cmd, "type": "close", "ticket": r["ticket"]})
                        r["close_cmd"] = cmd
                    except HTTPException:
                        pass
                    r["close_tried"] = now
                    dirty = True
                elif r.get("close_cmd") and ((res.get(r["close_cmd"]) and not res[r["close_cmd"]].get("ok"))
                                            or (not res.get(r["close_cmd"]) and now - r.get("close_tried", 0) > 60)):
                    r.pop("close_cmd"); dirty = True          # rejected, or the answer was lost: retry
        if dirty:
            _save(r)


async def run() -> None:
    while True:
        try:
            tick()
        except Exception as e:                  # the test must never stop Sentinel
            log.warning("live tick: %s", e)
        await asyncio.sleep(TICK_S)


def start_loop() -> None:
    global _task
    if _task is None:
        _task = asyncio.get_running_loop().create_task(run())


# ── metrics ─────────────────────────────────────────────────────────────────

def metrics(rs: list[dict], c: dict) -> dict:
    taken = [r for r in rs if r["state"] in ("open", "closed")]
    closed = [r for r in rs if r["state"] == "closed"]
    skipped = [r for r in rs if r["state"] == "skipped"]
    rejected = [r for r in rs if r["state"] == "rejected"]
    reasons: dict[str, int] = {}
    for r in skipped + rejected:
        k = (r.get("reason") or "?").split(" (")[0].split(":")[0]
        k = k if not k.startswith("minimum lot") else "minimum lot above 1%"
        reasons[k] = reasons.get(k, 0) + 1
    rr = [r["r"] for r in closed if r.get("r") is not None]
    pnl = sum(r.get("pnl") or 0 for r in closed)
    curve = c.get("curve") or {}
    start = curve.get("start")
    wins = sum(1 for x in rr if x > 0.05)
    within = [r for r in taken if r.get("equity_at_entry") and (r.get("risk_actual") or r.get("risk_money"))]
    risk_ok = sum(1 for r in within if 100 * (r.get("risk_actual") or r["risk_money"]) / r["equity_at_entry"] <= RISK_PCT * 1.05)
    moves = [m for r in taken for m in r.get("stop_moves") or []]
    weekly: dict[str, float] = {}
    for r in closed:
        if r.get("r") is not None:
            wk = time.strftime("%G-W%V", time.gmtime(r["closed_at"]))
            weekly[wk] = round(weekly.get(wk, 0) + r["r"], 3)
    gap = [r["r"] - r["paper_r"] for r in closed if r.get("r") is not None and r.get("paper_r") is not None]
    eq = r_dd = peak_r = 0.0
    for x in [r["r"] for r in sorted(closed, key=lambda r: r["closed_at"]) if r.get("r") is not None]:
        eq += x; peak_r = max(peak_r, eq); r_dd = max(r_dd, peak_r - eq)
    return {
        "signals": len(rs), "taken": len(taken), "open": sum(1 for r in taken if r["state"] == "open"),
        "closed": len(closed), "skipped": len(skipped), "rejected": len(rejected), "skip_reasons": reasons,
        "wins": wins, "win_rate": round(wins / len(rr), 3) if rr else None,
        "total_r": round(sum(rr), 3), "avg_r": round(sum(rr) / len(rr), 3) if rr else None,
        "max_dd_r": round(r_dd, 3), "net": round(pnl, 2),
        "start_equity": start, "equity": curve.get("last"),
        "return_pct": round(100 * (curve["last"] - start) / start, 2) if start and curve.get("last") else None,
        "max_dd_pct": curve.get("max_dd_pct"),
        "risk_within_limit": f"{risk_ok}/{len(within)}" if within else None,
        "stop_moves_ok": f"{sum(1 for m in moves if m['ok'])}/{len(moves)}" if moves else None,
        "stop_move_lag_s": round(sum(m["lag_s"] for m in moves if m["ok"]) / max(1, sum(1 for m in moves if m["ok"])), 1) if moves else None,
        "manual_interventions": sum(1 for r in taken if r.get("manual") or r.get("manual_sl")),
        "avg_slippage_r": round(sum(r.get("slip_r") or 0 for r in taken) / len(taken), 3) if taken else None,
        "live_vs_paper_r": round(sum(gap) / len(gap), 3) if gap else None,
        "weekly_r": weekly,
    }


def _public_row(r: dict) -> dict:
    keep = ("id", "at", "market", "tf", "dir", "grade", "symbol", "state", "reason", "lots", "risk_money",
            "risk_actual", "equity_at_entry", "sentinel_entry", "fill", "slip_r", "sl_initial", "sl_live",
            "sl_target", "exit", "pnl", "r", "paper_r", "exit_reason", "closed_at", "manual", "manual_sl")
    out = {k: r.get(k) for k in keep}
    out["stop_moves"] = len(r.get("stop_moves") or [])
    return out


# ── API ─────────────────────────────────────────────────────────────────────

@router.get("/live")
def live_status(request: Request) -> dict:
    _S._check_key(request)
    c = cfg()
    view = _view()
    acct = _account(view)
    rs = rows()
    return {
        "on": bool(c.get("on")), "active": active(), "started": c.get("started"), "ends": c.get("ends"),
        "stopped": c.get("stopped"),
        "rules": {"grades": list(GRADES), "risk_pct": RISK_PCT, "open_risk_pct": OPEN_RISK_PCT,
                  "daily_loss_pct": DAILY_LOSS_PCT, "max_losses_day": MAX_LOSSES_DAY, "days": DAYS, "demo_only": True},
        "bridge": {"bound": bool(_cid()), "online": bool(view and view["online"]), "mode": acct.get("mode"),
                   "equity": acct.get("equity"), "currency": acct.get("currency")},
        "availability": dict(avail_report(), offline_skips=sum(
            1 for r in rs if r.get("state") == "skipped" and str(r.get("reason") or "").startswith("MT5 bridge offline"))),
        "symbols": c.get("symbols"), "specs": {k: {kk: v.get(kk) for kk in ("volMin", "volStep", "tickSize", "tickValue", "contractSize")}
                                                for k, v in (c.get("specs") or {}).items()},
        "spec_errors": c.get("spec_errors") or {},
        "metrics": metrics(rs, c),
        "trades": [_public_row(r) for r in rs[:100]],
    }


@router.post("/live")
async def live_control(request: Request) -> dict:
    _S._check_key(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Send JSON")
    action = str(body.get("action") or "")
    c = cfg()
    if action == "symbols":
        syms = body.get("symbols") or {}
        if not isinstance(syms, dict):
            raise HTTPException(400, "symbols must be {market: MT5 symbol}")
        for k, v in syms.items():
            if k in DEFAULT_SYMBOLS and isinstance(v, str) and 0 < len(v.strip()) <= 40:
                c["symbols"][k] = v.strip()
        _set_cfg(c)
        return {"ok": True, "symbols": c["symbols"], "checking": request_specs() if _view() else []}
    if action == "check":
        if not (_view() or {}).get("online"):
            raise HTTPException(503, "The MT5 bridge is offline. Open MT5 with the EA running.")
        return {"ok": True, "checking": request_specs()}
    if action == "start":
        view = _view()
        if not _cid():
            raise HTTPException(409, "Connect the MT5 bridge in Trade → Trade live first (it binds your account).")
        if not (view and view["online"]):
            raise HTTPException(503, "The MT5 bridge is offline. Open MT5 with the EA running, then start.")
        if _account(view).get("mode") != "demo":
            raise HTTPException(409, "The connected MT5 account is not a demo account. This test runs on demo only.")
        if c.get("on") and active():
            return {"ok": True, "already": True}
        now = time.time()
        eq = _account(view).get("equity")
        c.update(on=True, started=now, ends=now + DAYS * 86400, stopped=None,
                 curve={"start": eq, "peak": eq, "low": eq, "max_dd_pct": 0.0, "last": eq} if eq else None)
        _set_cfg(c)
        request_specs()
        _telegram(f"started — {DAYS} days, A setups only, {RISK_PCT:g}% risk, equity {eq}")
        return {"ok": True, "started": now, "ends": c["ends"]}
    if action == "stop":
        c.update(on=False, stopped=time.time())
        _set_cfg(c)
        _telegram("stopped by the owner — no new entries; open positions keep their stops")
        return {"ok": True}
    raise HTTPException(400, "Unknown action")
