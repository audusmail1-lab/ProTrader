"""
ARIA Sentinel — the always-on scanner behind PROTrader's Sentinel pane.

What it does, every time a 15m / 1h bar closes:
  1. pulls the closed candles for each market in the FOCUS list from Deriv
     (Sentinel can read all 89 terminal instruments; the owner picks up to
     SENTINEL_MAX_MARKETS of them)
  2. runs ARIA v7 on them (sentinel_engine — identical to the terminal)
  3. opens a PAPER trade when ARIA says QUALIFIED (7/9) or EXECUTION READY
     (8+/9), and scores every open paper trade against the new bar
  4. journals everything to SQLite and, if configured, pings Telegram

What it never does: place an order. Sentinel prepares, the trader confirms —
the terminal's "Load setup" button only fills the trade ticket.

Endpoints (all read-only except config):
  GET  /api/sentinel/status   scanner health, focus markets, news-week flag
  GET  /api/sentinel/markets  every market Sentinel can read + the focus list
  POST /api/sentinel/focus    {"markets": [ids]} up to the cap (needs X-Sentinel-Key)
  GET  /api/sentinel/board    latest ARIA read for every market × timeframe
  GET  /api/sentinel/feed     open paper trades + recent results
  GET  /api/sentinel/stats    journal statistics + one-year replay baseline
  POST /api/sentinel/config   {"news_week": bool}  (needs X-Sentinel-Key)

Environment:
  SENTINEL_ENABLED=0          switch the scanner off (API still answers)
  SENTINEL_DB=path            SQLite journal (default ./sentinel.db). On
                              Render, point this at a persistent disk or the
                              journal resets on every deploy.
  SENTINEL_TFS=15m,1h         timeframes to scan
  SENTINEL_MAX_MARKETS=12     how many markets the focus list may hold
  SENTINEL_ADMIN_KEY=…        owner key: enables POST /focus and /config
  TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID   optional alerts
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

import sentinel_core as core

log = logging.getLogger("sentinel")
router = APIRouter(prefix="/api/sentinel", tags=["sentinel"])

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("SENTINEL_DB", os.path.join(HERE, "sentinel.db"))
TFS = [t for t in os.getenv("SENTINEL_TFS", "15m,1h").split(",") if t in core.TF_SEC]
BASELINE_FILE = os.path.join(HERE, "sentinel_baseline.json")
EVIDENCE_MIN_N = 100     # trades before a slice can be called "proven"
FRESH_S = 150            # a bar older than this is judged but never entered
# Sentinel can read every market in core.CATALOGUE, but scans only the
# trader's focus list, capped so one cycle stays well inside 15 minutes and
# the public Deriv feed isn't hammered.
MAX_MARKETS = max(1, min(40, int(os.getenv("SENTINEL_MAX_MARKETS", "12"))))
LEGACY_MODE = {"live-eligible": "real", "research": "synthetic"}

_lock = threading.Lock()
_state: dict[str, Any] = {
    "running": False, "started_at": None, "last_cycle": None, "last_error": None,
    "cycles": 0, "board": {},
}
_book: Optional[core.PaperBook] = None
_task: Optional[asyncio.Task] = None


# ── Storage ──────────────────────────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.execute("""CREATE TABLE IF NOT EXISTS trades (
        id TEXT PRIMARY KEY, market TEXT, tf TEXT, status TEXT,
        opened_at INTEGER, closed_at INTEGER, data TEXT)""")
    con.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    return con


def _save_trade(t: core.Trade) -> None:
    with _lock, _db() as con:
        con.execute("INSERT OR REPLACE INTO trades VALUES (?,?,?,?,?,?,?)",
                    (t.id, t.market, t.tf, t.status, t.opened_at, t.closed_at, json.dumps(t.to_dict())))


def _meta_get(k: str, default: Any = None) -> Any:
    with _lock, _db() as con:
        row = con.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return json.loads(row[0]) if row else default


def _meta_set(k: str, v: Any) -> None:
    with _lock, _db() as con:
        con.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, json.dumps(v)))


def _load_trades(where: str = "", args: tuple = (), limit: int = 5000) -> list[dict]:
    with _lock, _db() as con:
        rows = con.execute(f"SELECT data FROM trades {where} ORDER BY opened_at DESC LIMIT ?",
                           args + (limit,)).fetchall()
    return [json.loads(r[0]) for r in rows]


def _restore_book() -> core.PaperBook:
    book = core.PaperBook(news_week=bool(_meta_get("news_week", False)))
    for d in _load_trades("WHERE status='open'"):
        d["mode"] = LEGACY_MODE.get(d.get("mode"), d.get("mode"))
        t = core.Trade(**d)
        book.open[(t.market, t.tf)] = t
    return book


# ── Alerts ───────────────────────────────────────────────────────────────────

def _fmt_px(v: float) -> str:
    return f"{v:,.5f}" if abs(v) < 10 else f"{v:,.2f}"


def _telegram(text: str) -> None:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    try:
        import requests
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": text}, timeout=10)
    except Exception as e:  # alerts must never stop the scanner
        log.warning("telegram failed: %s", e)


def _alert_open(t: core.Trade) -> None:
    m = core.MARKET_BY_ID[t.market]
    if t.tier != "exec":
        return
    ev = _evidence().get(f"{t.market} {t.tf}", {}).get("status", "unproven")
    _telegram(
        f"ARIA Sentinel · {m.label}{' (synthetic)' if m.mode == 'synthetic' else ''} {t.tf} · {t.dir.upper()} {t.score}/9\n"
        f"Entry {_fmt_px(t.entry)} · SL {_fmt_px(t.sl)} · TP {_fmt_px(t.tp2)}\n"
        f"MCC {t.mcc} · {t.wyckoff}{' · ' + t.pattern if t.pattern else ''}\n"
        f"Evidence: {ev}. Paper signal — confirm on the chart before trading.")


def _alert_close(t: core.Trade) -> None:
    m = core.MARKET_BY_ID[t.market]
    if t.tier != "exec":
        return
    _telegram(f"ARIA Sentinel · {m.label} {t.tf} paper {t.dir} closed: {t.status.upper()} {t.r:+.2f}R")


# ── Scanner ──────────────────────────────────────────────────────────────────

def _focus() -> list[str]:
    ids = _meta_get("focus", None) or core.DEFAULT_FOCUS
    return [i for i in ids if i in core.MARKET_BY_ID][:MAX_MARKETS]


async def _scan_one(m: core.Market, tf: str, focused: bool = True) -> None:
    """Score open paper trades; if the market is in focus, judge the new bar."""
    key = f"{m.id} {tf}"
    bars = await core.fetch_candles(m.deriv, tf, core.WINDOW + 10)
    if len(bars) < core.WINDOW // 2:
        return
    for t in _book.update(m.id, tf, bars):
        _save_trade(t)
        _alert_close(t)
    last = bars[-1]
    if not focused:          # dropped from focus: only finish its open trade
        t = _book.open.get((m.id, tf))
        if t:
            _save_trade(t)
        _state["board"].pop(key, None)
        return
    seen = _state["board"].get(key, {}).get("bar")
    evaluated = _meta_get(f"eval:{key}", 0)
    # Only enter on a bar that closed moments ago. After a restart or an
    # outage the latest close may be stale, and its price is no longer
    # available to a trader — record the read, skip the entry.
    fresh = time.time() - (last["time"] + core.TF_SEC[tf]) < FRESH_S
    read, new = (_book.consider(m, tf, bars[-core.WINDOW:], allow_open=fresh)
                 if last["time"] > evaluated else (None, None))
    if read:
        _meta_set(f"eval:{key}", last["time"])
        _state["board"][key] = {
            "market": m.id, "label": m.label, "tf": tf, "mode": m.mode, "bar": last["time"],
            "price": last["close"], **{k: read[k] for k in ("dir", "score", "gates", "mcc", "wyckoff", "pattern", "verdict")},
            "sl": read["sl"], "tp2": read["tp2"],
        }
    elif seen is None:
        # First cycle after a restart on an already-judged bar: still show it.
        r = core.eng.evaluate(bars[-core.WINDOW:], m.id, core.bar_close_hour(last, tf), _book.news_week)
        if r:
            _state["board"][key] = {"market": m.id, "label": m.label, "tf": tf, "mode": m.mode,
                                    "bar": last["time"], "price": last["close"],
                                    **{k: r[k] for k in ("dir", "score", "gates", "mcc", "wyckoff", "pattern", "verdict")},
                                    "sl": r["sl"], "tp2": r["tp2"]}
    # Keep the open trade's progress on disk so a restart resumes it.
    t = _book.open.get((m.id, tf))
    if t:
        _save_trade(t)
    if new:
        _save_trade(new)
        _alert_open(new)


_wake: Optional[asyncio.Event] = None


async def _loop() -> None:
    global _book, _wake
    _book = _restore_book()
    _wake = asyncio.Event()
    _state.update(running=True, started_at=time.time())
    log.info("Sentinel started: focus %s × %s", _focus(), TFS)
    while True:
        cycle_start = time.time()
        focus = _focus()
        # Markets dropped from focus keep being read until their paper
        # trade finishes, so no result is lost by editing the list.
        extra = sorted({mk for (mk, _tf) in _book.open} - set(focus))
        for mid in focus + extra:
            m = core.MARKET_BY_ID.get(mid)
            if not m:
                continue
            for tf in TFS:
                try:
                    await _scan_one(m, tf, focused=mid in focus)
                except Exception as e:
                    _state["last_error"] = f"{time.strftime('%H:%M:%S', time.gmtime())} {m.id} {tf}: {e}"
                    log.warning("sentinel %s %s: %s", m.id, tf, e)
                await asyncio.sleep(0.3)   # be gentle with the public feed
        for key in [k for k in _state["board"] if k.split(" ")[0] not in focus]:
            _state["board"].pop(key, None)
        _state["last_cycle"] = time.time()
        _state["cycles"] += 1
        # Wake shortly after the next 15-minute close, or at once when the
        # focus list changes so new markets appear on the board.
        nxt = (int(cycle_start // 900) + 1) * 900 + 8
        _wake.clear()
        try:
            await asyncio.wait_for(_wake.wait(), timeout=max(20.0, nxt - time.time()))
        except asyncio.TimeoutError:
            pass


def start() -> None:
    """Start the scanner on the running event loop. Safe to call twice."""
    global _task
    if os.getenv("SENTINEL_ENABLED", "1") == "0" or _task is not None:
        return
    _task = asyncio.get_running_loop().create_task(_loop())


def attach(app) -> None:
    """
    Run the scanner for the app's lifetime. Wraps the existing lifespan
    rather than using startup events, which newer Starlette removed.
    """
    from contextlib import asynccontextmanager
    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(a):
        start()
        try:
            async with inner(a) as state:
                yield state
        finally:
            global _task
            if _task:
                _task.cancel()
                _task = None

    app.router.lifespan_context = lifespan


# ── Evidence ─────────────────────────────────────────────────────────────────

def _baseline() -> dict:
    try:
        with open(BASELINE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _evidence() -> dict[str, dict]:
    """
    A market × timeframe is "proven" only when the one-year replay AND the
    live paper journal both show a 95% interval above zero on enough trades.
    Until then Sentinel's signals are labelled unproven, whatever the score.
    Markets without a replay can only become proven after a replay is run.
    """
    base = _baseline().get("by_slice", {})
    live = core.group_stats([t for t in _load_trades() if t["tier"] == "exec"],
                            lambda t: f"{t['market']} {t['tf']}")
    ok = lambda s: s.get("n", 0) >= EVIDENCE_MIN_N and (s.get("ci95_r") or [0])[0] > 0
    neg = lambda s: s.get("n", 0) >= EVIDENCE_MIN_N and (s.get("ci95_r") or [0, 0])[1] < 0
    out = {}
    for mid in _focus():
        for tf in TFS:
            k = f"{mid} {tf}"
            b, l = base.get(k, {}), live.get(k, {})
            status = ("proven" if ok(b) and ok(l)
                      else "negative" if neg(b) or neg(l)
                      else "unproven")
            out[k] = {"status": status, "replay": b, "live": l}
    return out


def _check_key(request: Request) -> None:
    key = os.getenv("SENTINEL_ADMIN_KEY", "")
    given = request.headers.get("x-sentinel-key", "")
    if not key:
        raise HTTPException(403, "Owner key is not set on this server (SENTINEL_ADMIN_KEY)")
    if not hmac.compare_digest(key, given):
        raise HTTPException(403, "Wrong owner key")


# ── API ──────────────────────────────────────────────────────────────────────

@router.get("/status")
def status() -> dict:
    focus = _focus()
    return {
        "enabled": os.getenv("SENTINEL_ENABLED", "1") != "0",
        "running": _state["running"], "started_at": _state["started_at"],
        "last_cycle": _state["last_cycle"], "cycles": _state["cycles"],
        "last_error": _state["last_error"], "timeframes": TFS,
        "news_week": bool(_book.news_week) if _book else bool(_meta_get("news_week", False)),
        "markets": [{"id": i, "label": core.MARKET_BY_ID[i].label, "mode": core.MARKET_BY_ID[i].mode} for i in focus],
        "max_markets": MAX_MARKETS,
        "open_trades": len(_book.open) if _book else 0,
        "alerts": bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")),
        "owner_key_set": bool(os.getenv("SENTINEL_ADMIN_KEY")),
    }


@router.get("/markets")
def markets() -> dict:
    """Everything Sentinel can read, grouped as in the terminal, plus the focus."""
    groups: dict[str, list] = {}
    for m in core.CATALOGUE:
        groups.setdefault(m.group, []).append({"id": m.id, "label": m.label, "mode": m.mode})
    return {"groups": [{"name": g, "markets": ms} for g, ms in groups.items()],
            "focus": _focus(), "max": MAX_MARKETS, "total": len(core.CATALOGUE)}


@router.post("/focus")
async def set_focus(request: Request) -> dict:
    _check_key(request)
    body = await request.json()
    ids = body.get("markets") if isinstance(body, dict) else None
    if not isinstance(ids, list) or not ids:
        raise HTTPException(400, "Send {\"markets\": [ids…]} with at least one market")
    unknown = [i for i in ids if i not in core.MARKET_BY_ID]
    if unknown:
        raise HTTPException(400, f"Unknown market(s): {', '.join(map(str, unknown[:5]))}")
    clean = list(dict.fromkeys(ids))
    if len(clean) > MAX_MARKETS:
        raise HTTPException(400, f"Sentinel reads at most {MAX_MARKETS} markets at a time")
    _meta_set("focus", clean)
    if _wake:
        _wake.set()
    return markets()


@router.get("/board")
def board() -> dict:
    ev = _evidence()
    focus = set(_focus())
    rows = [{**b, "evidence": ev.get(k, {}).get("status", "unproven")}
            for k, b in _state["board"].items() if b["market"] in focus]
    order = {"EXEC_READY": 0, "QUALIFIED": 1, "WAITING": 2, "BLOCKED": 3, "OBSERVER": 4}
    rows.sort(key=lambda r: (order.get(r["verdict"], 9), -r["score"], r["mode"] != "real"))
    return {"updated": _state["last_cycle"], "rows": rows}


@router.get("/feed")
def feed(limit: int = 40) -> dict:
    limit = max(1, min(int(limit), 200))
    open_ = _load_trades("WHERE status='open'")
    closed = _load_trades("WHERE status!='open'", limit=limit)
    closed.sort(key=lambda t: t.get("closed_at") or 0, reverse=True)
    for t in open_ + closed:
        t["mode"] = LEGACY_MODE.get(t.get("mode"), t.get("mode"))
    return {"open": open_, "closed": closed}


@router.get("/stats")
def stats() -> dict:
    trades = _load_trades()
    for t in trades:
        t["mode"] = LEGACY_MODE.get(t.get("mode"), t.get("mode"))
    real = [t for t in trades if t["mode"] == "real"]
    syn = [t for t in trades if t["mode"] == "synthetic"]
    base = _baseline()
    return {
        "journal": {
            "all": core.summarise(trades),
            "exec": core.summarise([t for t in trades if t["tier"] == "exec"]),
            "real": core.summarise(real),
            "synthetic": core.summarise(syn),
            "by_slice": core.group_stats(trades, lambda t: f"{t['market']} {t['tf']}"),
        },
        "baseline": {k: base.get(k) for k in ("generated", "period", "notes", "all", "exec", "by_slice",
                                             "by_score", "synthetic", "gate_pass_rate")},
        "evidence": {k: v["status"] for k, v in _evidence().items()},
        "model": {"target_r": core.TARGET_R, "breakeven_win_rate": round(core.BREAKEVEN_WINRATE, 4),
                  "max_bars": core.MAX_BARS, "evidence_min_trades": EVIDENCE_MIN_N},
    }


@router.post("/config")
async def config(request: Request) -> dict:
    _check_key(request)
    body = await request.json()
    if "news_week" in body:
        nw = bool(body["news_week"])
        _meta_set("news_week", nw)
        if _book:
            _book.news_week = nw
    return status()
