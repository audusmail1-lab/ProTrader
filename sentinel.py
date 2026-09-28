"""
ARIA Sentinel — the always-on scanner behind PROTrader's Sentinel pane.

What it does, every time a 15m / 1h bar closes:
  1. pulls the closed candles for each market in the FOCUS list from Deriv
     (Sentinel can read all 89 terminal instruments; the owner picks up to
     SENTINEL_MAX_MARKETS of them)
  2. runs ARIA v7.1 on them (sentinel_engine — identical to the terminal)
  3. opens a PAPER trade when ARIA says QUALIFIED (8/10) or EXECUTION READY
     (9+/10), and scores every open paper trade against the new bar
     (each focus market has its own timeframes: 15m, 1h and/or 4h)
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
  GET  /api/sentinel/costs    estimated vs MT5-measured spread per focus market
  GET/POST /api/sentinel/managed  the trader's own trade-management journal (owner key)
  POST /api/sentinel/costs    bid/ask snapshots from the MT5 bridge (owner key);
                              the median measured spread replaces the estimate

Environment:
  SENTINEL_ENABLED=0          switch the scanner off (API still answers)
  SENTINEL_DB=path            SQLite journal. Defaults to /var/data/sentinel.db
                              when a disk is mounted at /var/data, otherwise the
                              journal resets on every deploy. /status shows
                              whether the journal is persistent.
  SENTINEL_TFS=15m,1h         timeframes for a focus market saved without its own
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


DISK_DIR = "/var/data"


def _pick_db_path() -> tuple[str, bool, Optional[str]]:
    """
    Where the journal lives. SENTINEL_DB should point at a persistent disk
    (e.g. /var/data/sentinel.db on Render). If that location can't be
    written — disk not attached, wrong permissions — fall back to the app
    folder so the scanner keeps running, and say so in /status.
    """
    fallback = os.path.join(HERE, "sentinel.db")
    want = os.getenv("SENTINEL_DB", "").strip()
    if not want and os.path.ismount(DISK_DIR):
        want = os.path.join(DISK_DIR, "sentinel.db")   # Render disk mounted at /var/data
    if not want:
        return fallback, False, "no persistent disk at /var/data and SENTINEL_DB is not set: the journal resets on every deploy"
    try:
        d = os.path.dirname(os.path.abspath(want))
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".sentinel-write-test")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        return want, True, None
    except OSError as e:
        return fallback, False, f"cannot write {want} ({e.strerror or e}); using a temporary journal"


DB_PATH, DB_PERSISTENT, DB_WARNING = _pick_db_path()
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
    con.execute("""CREATE TABLE IF NOT EXISTS managed (
        key TEXT PRIMARY KEY, opened INTEGER, closed INTEGER, data TEXT)""")
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


def _load_costs() -> dict:
    """Measured MT5 spreads: {market: [{"pct", "spread", "mid", "symbol", "at"}, …]}."""
    return _meta_get("costs", {}) or {}


def _apply_costs(costs: dict) -> None:
    """Median of the recorded samples, as a fraction of price, per market."""
    core.MEASURED_SPREAD_PCT.clear()
    for mid, samples in costs.items():
        pcts = sorted(x["pct"] for x in samples if x.get("pct", 0) > 0)
        if pcts:
            core.MEASURED_SPREAD_PCT[mid] = pcts[len(pcts) // 2]


def _restore_book() -> core.PaperBook:
    book = core.PaperBook(news_week=bool(_meta_get("news_week", False)), model=core.SENTINEL_MODEL)
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
    if t.model == "fixed" and t.tier != "exec":
        return
    ev = _evidence().get(f"{t.market} {t.tf}", {}).get("status", "unproven")
    _telegram(
        f"ARIA Sentinel · {m.label}{' (synthetic)' if m.mode == 'synthetic' else ''} {t.tf} · {t.dir.upper()} {t.score}/{core.eng.GATE_COUNT}\n"
        f"{'EW ' + t.elliott + ' (soft) · ' if t.elliott else ''}"
        + (f"Entry {_fmt_px(t.entry)} · SL {_fmt_px(t.sl)} · TP {_fmt_px(t.tp2)}\n" if t.model == "fixed" else
           f"Entry {_fmt_px(t.entry)} · SL {_fmt_px(t.sl)} · no fixed target: at +1R trail the stop 1R behind the best price\n"
           f"4h trend {t.trend_4h} · ARIA {t.model} candidate\n")
        + 
        f"MCC {t.mcc} · {t.wyckoff}{' · ' + t.pattern if t.pattern else ''}\n"
        f"Evidence: {ev}. Paper signal — confirm on the chart before trading.")


def _alert_close(t: core.Trade) -> None:
    m = core.MARKET_BY_ID[t.market]
    if t.model == "fixed" and t.tier != "exec":
        return
    _telegram(f"ARIA Sentinel · {m.label} {t.tf} paper {t.dir} closed: {t.status.upper()} {t.r:+.2f}R")


# ── Scanner ──────────────────────────────────────────────────────────────────

SUPPORTED_TFS = [t for t in ("15m", "1h", "4h") if t in core.TF_SEC]
# Default per-market timeframes. 15m forex is left out on purpose: in the
# one-year replay the spread cost ~17% of each stop there and every 15m FX
# slice lost money.
# ARIA 7.2 candidate focus: the four market-timeframes that held up in both
# the full year and the hold-out of the 27 Sep 2026 research.
DEFAULT_FOCUS = [
    {"id": "frxNAS100", "tfs": ["15m"]},
    {"id": "frxXAUUSD", "tfs": ["15m", "1h"]},
    {"id": "cryBTCUSD", "tfs": ["1h"]},
]


def _norm_focus(raw) -> list[dict]:
    """Accept the old list-of-ids form and the new [{id, tfs}] form."""
    out, seen = [], set()
    for item in raw or []:
        mid, tfs = (item, TFS) if isinstance(item, str) else (item.get("id"), item.get("tfs") or TFS)
        if mid not in core.MARKET_BY_ID or mid in seen:
            continue
        tfs = [t for t in SUPPORTED_TFS if t in tfs] or TFS
        seen.add(mid)
        out.append({"id": mid, "tfs": tfs})
    return out[:MAX_MARKETS]


def _focus() -> list[dict]:
    return _norm_focus(_meta_get("focus", None) or DEFAULT_FOCUS)


def _focus_ids() -> list[str]:
    return [f["id"] for f in _focus()]


def _slices() -> list[str]:
    return [f"{f['id']} {tf}" for f in _focus() for tf in f["tfs"]]


def _current(trades: list[dict]) -> list[dict]:
    """Only trades made by the current ARIA rules AND paper model count as evidence."""
    return [t for t in trades if t.get("engine", "7.0") == core.eng.ENGINE_VERSION
            and t.get("model", "fixed") == core.SENTINEL_MODEL]


_trend_cache: dict[str, tuple] = {}   # market -> (close_times, trends, next_refresh_epoch)


async def _trend_4h(m: core.Market) -> Optional[str]:
    """4h trend from the last CLOSED 4h bar, refreshed once per 4h close."""
    now = time.time()
    hit = _trend_cache.get(m.id)
    if not hit or now >= hit[2]:
        h4 = await core.fetch_candles(m.deriv, "4h", 5000)
        ct, tr = core.trend_series(h4)
        nxt = (ct[-1] + core.TF_SEC["4h"] + 30) if ct else now + 600
        hit = _trend_cache[m.id] = (ct, tr, nxt)
    ct, tr, _ = hit
    return core.trend_at(ct, tr, int(now)) if ct else None


def _board_row(m: core.Market, tf: str, last: dict, r: dict) -> dict:
    return {"market": m.id, "label": m.label, "tf": tf, "mode": m.mode, "bar": last["time"],
            "price": last["close"],
            **{k: r[k] for k in ("dir", "score", "gates", "mcc", "wyckoff", "pattern", "verdict")},
            "sl": r["sl"], "tp2": r["tp2"], "elliott": r["elliott"]["label"], "fib_r": r["fib_r"],
            "trend_4h": r.get("trend_4h"), "block": r.get("block")}


async def _scan_one(m: core.Market, tf: str, focused: bool = True) -> None:
    """Score open paper trades; if the market is in focus, judge the new bar."""
    key = f"{m.id} {tf}"
    # Deriv's "count" is really a time span (count × timeframe back from now),
    # so across a weekend or outside index hours it returns far fewer bars.
    # Ask for the maximum and keep the last WINDOW+10 closed bars.
    bars = (await core.fetch_candles(m.deriv, tf, 5000))[-(core.WINDOW + 10):]
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
    t4 = None
    if last["time"] > evaluated or seen is None:
        try:
            t4 = await _trend_4h(m)
        except Exception as e:          # no 4h trend = no candidate entry, never a crash
            log.warning("4h trend %s: %s", m.id, e)
    read, new = (_book.consider(m, tf, bars[-core.WINDOW:], allow_open=fresh, trend_4h=t4)
                 if last["time"] > evaluated else (None, None))
    if read:
        _meta_set(f"eval:{key}", last["time"])
        _state["board"][key] = _board_row(m, tf, last, read)
    elif seen is None:
        # First cycle after a restart on an already-judged bar: show it, never enter.
        r, _ = _book.consider(m, tf, bars[-core.WINDOW:], allow_open=False, trend_4h=t4)
        if r:
            _state["board"][key] = _board_row(m, tf, last, r)
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
    _apply_costs(_load_costs())
    _wake = asyncio.Event()
    _state.update(running=True, started_at=time.time())
    log.info("Sentinel started: focus %s", _slices())
    while True:
        cycle_start = time.time()
        focus = _focus()
        wanted = {(f["id"], tf) for f in focus for tf in f["tfs"]}
        # Slices dropped from focus keep being read until their paper trade
        # finishes, so no result is lost by editing the list.
        jobs = sorted(wanted | set(_book.open), key=lambda x: (x[0] not in [f["id"] for f in focus], x))
        for mid, tf in jobs:
            m = core.MARKET_BY_ID.get(mid)
            if m and tf in core.TF_SEC:
                try:
                    await _scan_one(m, tf, focused=(mid, tf) in wanted)
                except Exception as e:
                    _state["last_error"] = f"{time.strftime('%H:%M:%S', time.gmtime())} {m.id} {tf}: {e}"
                    log.warning("sentinel %s %s: %s", m.id, tf, e)
                await asyncio.sleep(0.3)   # be gentle with the public feed
        keep = {f"{a} {b}" for a, b in wanted}
        for key in [k for k in _state["board"] if k not in keep]:
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
    live paper journal (current ARIA rules, exec-ready tier) both clear the
    bar on at least EVIDENCE_MIN_N trades. The bar is a 95% interval with a
    Bonferroni correction for the number of slices in focus, so watching more
    markets cannot manufacture a lucky "proven". Otherwise: unproven, or
    negative when either source is clearly below zero.
    """
    base = _baseline().get("by_slice", {})
    live = core.group_stats(_current(_load_trades()), lambda t: f"{t['market']} {t['tf']}")
    slices = _slices()
    k = len(slices)
    out = {}
    for key in slices:
        b, l = base.get(key, {}), live.get(key, {})
        sb, sl = core.edge_status(b, k, EVIDENCE_MIN_N), core.edge_status(l, k, EVIDENCE_MIN_N)
        status = ("proven" if sb == "proven" and sl == "proven"
                  else "negative" if "negative" in (sb, sl)
                  else "unproven")
        out[key] = {"status": status, "replay": b, "live": l}
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
        "last_error": _state["last_error"], "timeframes": sorted({tf for f in focus for tf in f["tfs"]}, key=SUPPORTED_TFS.index),
        "news_week": bool(_book.news_week) if _book else bool(_meta_get("news_week", False)),
        "markets": [{"id": f["id"], "label": core.MARKET_BY_ID[f["id"]].label,
                     "mode": core.MARKET_BY_ID[f["id"]].mode, "tfs": f["tfs"]} for f in focus],
        "supported_tfs": SUPPORTED_TFS, "engine": core.eng.ENGINE_VERSION,
        "model": core.SENTINEL_MODEL, "model_rules": core.MODELS[core.SENTINEL_MODEL],
        "gate_count": core.eng.GATE_COUNT,
        "evidence_z": round(core.z_for(len(_slices())), 2),
        "max_markets": MAX_MARKETS,
        "open_trades": len(_book.open) if _book else 0,
        "alerts": bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")),
        "owner_key_set": bool(os.getenv("SENTINEL_ADMIN_KEY")),
        "journal": {"path": DB_PATH, "persistent": DB_PERSISTENT, "warning": DB_WARNING,
                    "trades": _count_trades()},
    }


def _count_trades() -> int:
    try:
        with _lock, _db() as con:
            return con.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    except sqlite3.Error:
        return -1


@router.get("/markets")
def markets() -> dict:
    """Everything Sentinel can read, grouped as in the terminal, plus the focus."""
    groups: dict[str, list] = {}
    for m in core.CATALOGUE:
        groups.setdefault(m.group, []).append({"id": m.id, "label": m.label, "mode": m.mode})
    return {"groups": [{"name": g, "markets": ms} for g, ms in groups.items()],
            "focus": _focus(), "max": MAX_MARKETS, "total": len(core.CATALOGUE),
            "supported_tfs": SUPPORTED_TFS}


@router.post("/focus")
async def set_focus(request: Request) -> dict:
    _check_key(request)
    body = await request.json()
    items = body.get("markets") if isinstance(body, dict) else None
    if not isinstance(items, list) or not items:
        raise HTTPException(400, "Send {\"markets\": [id or {\"id\", \"tfs\"}, …]} with at least one market")
    ids = [i if isinstance(i, str) else (i or {}).get("id") for i in items]
    unknown = [i for i in ids if i not in core.MARKET_BY_ID]
    if unknown:
        raise HTTPException(400, f"Unknown market(s): {', '.join(map(str, unknown[:5]))}")
    if len(set(ids)) > MAX_MARKETS:
        raise HTTPException(400, f"Sentinel reads at most {MAX_MARKETS} markets at a time")
    for i in items:
        if isinstance(i, dict) and i.get("tfs") is not None:
            bad = [t for t in i["tfs"] if t not in SUPPORTED_TFS]
            if bad or not i["tfs"]:
                raise HTTPException(400, f"Timeframes must be some of {', '.join(SUPPORTED_TFS)}")
    _meta_set("focus", _norm_focus(items))
    if _wake:
        _wake.set()
    return markets()


COST_SAMPLES_KEEP = 30


@router.get("/costs")
def costs() -> dict:
    """Estimated vs measured spread for every focus market."""
    data = _load_costs()
    _apply_costs(data)
    rows = []
    for f in _focus():
        m = core.MARKET_BY_ID[f["id"]]
        samples = data.get(m.id, [])
        last = samples[-1] if samples else None
        price = last["mid"] if last else next(
            (b["price"] for k, b in _state["board"].items() if b["market"] == m.id), None)
        est = core.estimated_spread(m, price) if price else None
        rows.append({
            "market": m.id, "label": m.label, "mode": m.mode,
            "estimate_pct": (est / price) if (est and price) else (m.spread_pct or None),
            "measured_pct": core.MEASURED_SPREAD_PCT.get(m.id),
            "samples": len(samples), "last": last,
        })
    return {"rows": rows}


@router.post("/costs")
async def add_costs(request: Request) -> dict:
    """Owner-only: record bid/ask snapshots taken from MT5 through the bridge."""
    _check_key(request)
    body = await request.json()
    items = body.get("samples") if isinstance(body, dict) else None
    if not isinstance(items, list) or not items or len(items) > 60:
        raise HTTPException(400, "Send {\"samples\": [{market, symbol, bid, ask}, …]}")
    data = _load_costs()
    now = int(time.time())
    took, skipped = 0, []
    for it in items:
        mid = (it or {}).get("market")
        try:
            bid, ask = float(it.get("bid")), float(it.get("ask"))
        except (TypeError, ValueError):
            skipped.append(f"{mid}: no prices"); continue
        if mid not in core.MARKET_BY_ID or not (bid > 0 and ask >= bid):
            skipped.append(f"{mid}: bad quote"); continue
        mid_px = (bid + ask) / 2
        pct = (ask - bid) / mid_px
        if pct > 0.05:                      # a 5%+ spread is a broken quote, not a cost
            skipped.append(f"{mid}: spread {pct:.1%} looks wrong"); continue
        data.setdefault(mid, []).append({"pct": pct, "spread": ask - bid, "mid": mid_px,
                                         "symbol": str(it.get("symbol", ""))[:40], "at": now})
        data[mid] = data[mid][-COST_SAMPLES_KEEP:]
        took += 1
    _meta_set("costs", data)
    _apply_costs(data)
    return {"recorded": took, "skipped": skipped, **costs()}


@router.get("/board")
def board() -> dict:
    ev = _evidence()
    keep = set(_slices())
    rows = [{**b, "evidence": ev.get(k, {}).get("status", "unproven")}
            for k, b in _state["board"].items() if k in keep]
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
    for t in closed:
        t["stage"] = core.stage_of(t)
    return {"open": open_, "closed": closed}


@router.get("/stats")
def stats() -> dict:
    all_trades = _load_trades()
    for t in all_trades:
        t["mode"] = LEGACY_MODE.get(t.get("mode"), t.get("mode"))
    trades = _current(all_trades)
    real = [t for t in trades if t["mode"] == "real"]
    syn = [t for t in trades if t["mode"] == "synthetic"]
    base = _baseline()
    return {
        "journal": {
            "all": core.summarise(trades),
            "exec": core.summarise(trades),          # every trade the current model took
            "real": core.summarise(real),
            "synthetic": core.summarise(syn),
            "by_slice": core.group_stats(trades, lambda t: f"{t['market']} {t['tf']}"),
            "by_elliott": core.group_stats([t for t in trades if t["tier"] == "exec"],
                                           lambda t: t.get("elliott") or "no count"),
            "management": core.management_stats(trades),
            "older_rules": len(all_trades) - len(trades),
        },
        "baseline": {k: base.get(k) for k in ("generated", "period", "notes", "all", "exec", "by_slice",
                                             "by_score", "synthetic", "gate_pass_rate")},
        "evidence": {k: v["status"] for k, v in _evidence().items()},
        "model": {"target_r": core.TARGET_R, "breakeven_win_rate": round(core.BREAKEVEN_WINRATE, 4),
                  "max_bars": core.MAX_BARS, "evidence_min_trades": EVIDENCE_MIN_N,
                  "engine": core.eng.ENGINE_VERSION, "gate_count": core.eng.GATE_COUNT,
                  "model": core.SENTINEL_MODEL,
                  "evidence_z": round(core.z_for(len(_slices())), 2), "slices": len(_slices())},
    }


# ── Trader's own trade management (owner only) ──────────────────────────────
# The terminal watches the trader's paper and MT5 positions and records how
# each one was managed: initial stop, every stop move, when it became risk
# free, partials, peak profit and the exit. Sentinel's paper trade for the
# same setup (when the position came from "Load setup") is kept alongside,
# so the system's part and the trader's part can be judged separately.

MANAGED_MAX = 2000


def _managed_rows() -> list[dict]:
    with _lock, _db() as con:
        rows = con.execute("SELECT data FROM managed ORDER BY opened DESC LIMIT ?", (MANAGED_MAX,)).fetchall()
    return [json.loads(r[0]) for r in rows]


RISK_LIMIT_PCT = 1.0      # the framework's per-trade limit
RULE_TOLERANCE = 1.05     # lot steps round; 1.05% still counts as within 1%


def rule_break(r: dict, equity: Optional[float], risk_money: Optional[float], now_ms: int) -> None:
    """Mark a position that broke the risk rules: no stop within a minute of
    opening, or more than 1% of the account lost at its first stop. Such
    trades are counted, and shown, but kept out of the management stats so
    one oversized mistake cannot drown out the real record."""
    if r.get("rule_checked") or r.get("late"):
        return
    if r.get("r_dist") is None:
        if now_ms - int(r.get("opened") or now_ms) > 60_000:
            r["rule_break"], r["rule_checked"] = "no stop loss", True
        return
    if not (equity and equity > 0 and risk_money and risk_money > 0):
        return
    pct = 100 * risk_money / equity
    r["risk_pct"] = round(pct, 2)
    r["rule_checked"] = True
    if pct > RISK_LIMIT_PCT * RULE_TOLERANCE:
        r["rule_break"] = f"risked {pct:.1f}% (limit {RISK_LIMIT_PCT:g}%)"


def _managed_stats(recs: list[dict]) -> dict:
    done_all = [r for r in recs if r.get("closed")]
    broke = [r for r in done_all if r.get("rule_break")]
    rb = {"n": len(broke), "pnl": round(sum(r.get("pnl") or 0 for r in broke), 2)} if broke else None
    done = [r for r in done_all if not r.get("rule_break")]
    n = len(done)
    if not n:
        return {"n": 0, "open": sum(1 for r in recs if not r.get("closed")), "rule_breaks": rb}
    stages: dict[str, int] = {}
    for r in done:
        stages[r.get("stage") or "Unclassified"] = stages.get(r.get("stage") or "Unclassified", 0) + 1
    with_r = [r for r in done if isinstance(r.get("exit_r"), (int, float))]
    prot = [r for r in done if r.get("be_at")]
    capt = [r["exit_r"] / r["mfe_r"] for r in with_r if (r.get("mfe_r") or 0) >= 1 and r["exit_r"] > 0]
    pnl = [r.get("pnl") or 0 for r in done]
    linked = [r for r in with_r if isinstance(r.get("sentinel_r"), (int, float))]
    return {
        "n": n, "open": sum(1 for r in recs if not r.get("closed")), "stages": stages, "rule_breaks": rb,
        "pnl_total": round(sum(pnl), 2),
        "win_pct": round(sum(1 for x in pnl if x > 0) / n, 4),
        "risk_free_pct": round(len(prot) / n, 4),
        "risk_free_positive_pct": round(sum(1 for r in prot if (r.get("pnl") or 0) > 0) / len(prot), 4) if prot else None,
        "avg_exit_r": round(sum(r["exit_r"] for r in with_r) / len(with_r), 3) if with_r else None,
        "avg_mfe_r": round(sum(r.get("mfe_r") or 0 for r in with_r) / len(with_r), 3) if with_r else None,
        "capture_pct": round(sum(capt) / len(capt), 3) if capt else None,
        "vs_sentinel": ({"n": len(linked),
                         "trader_avg_r": round(sum(r["exit_r"] for r in linked) / len(linked), 3),
                         "sentinel_avg_r": round(sum(r["sentinel_r"] for r in linked) / len(linked), 3)}
                        if linked else None),
    }


def _attach_sentinel(recs: list[dict]) -> None:
    """Fill in Sentinel's own paper result for linked positions."""
    ids = [r["sentinel_id"] for r in recs if r.get("sentinel_id")]
    if not ids:
        return
    by_id = {}
    with _lock, _db() as con:
        for i in ids:
            row = con.execute("SELECT data FROM trades WHERE id=?", (i,)).fetchone()
            if row:
                by_id[i] = json.loads(row[0])
    for r in recs:
        t = by_id.get(r.get("sentinel_id"))
        if t:
            r["sentinel_status"] = t.get("status")
            r["sentinel_r"] = (t.get("r") + t.get("cost_r", 0)) if t.get("r") is not None else None
            r["sentinel_stage"] = core.stage_of(t) if t.get("status") != "open" else "open"


# ── Server-side MT5 management tracking ─────────────────────────────────────
# The MT5 bridge relay receives the EA's snapshot about once a second while
# MT5 runs, with or without a browser open. For the OWNER's bridge channel
# (bound once from the terminal with the owner key), this tracker records how
# every MT5 position is managed: initial stop, each stop/target move, when it
# became risk free, the profit the stop locked, partials, peak profit, exit.
# Same record format and stages as the terminal's MGMT journal.

_mt5_open: dict[str, dict] = {}       # ticket key -> live record (owner channel only)
_mt5_state = {"loaded": False, "last": 0.0, "deals": [], "deals_at": 0.0}
MT5_EVERY_S = 2.0


def _mt5_owner_channel() -> Optional[str]:
    return _meta_get("mt5_channel")


def _save_managed(r: dict) -> None:
    with _lock, _db() as con:
        con.execute("INSERT OR REPLACE INTO managed VALUES (?,?,?,?)",
                    (r["key"], int(r.get("opened") or 0), int(r.get("closed") or 0) or None,
                     json.dumps({k: v for k, v in r.items() if not k.startswith("_")})))


def _load_open_mt5() -> None:
    with _lock, _db() as con:
        rows = con.execute("SELECT data FROM managed WHERE key LIKE 'mt5:%' AND closed IS NULL").fetchall()
    for (blob,) in rows:
        r = json.loads(blob)
        _mt5_open[r["key"]] = r
    _mt5_state["loaded"] = True


def mgmt_stage(r: dict) -> str:
    """Same rules as MGMT.stage() in the terminal."""
    pnl = r.get("pnl") or 0
    if r.get("r_dist") and isinstance(r.get("exit_r"), (int, float)):
        flat = abs(r["exit_r"]) <= 0.1
    else:
        flat = abs(pnl) < 0.5
    if "take profit" in (r.get("exit_reason") or "").lower():
        return "Full winner"
    if r.get("be_at"):
        return "Protected flat" if flat else ("Managed winner" if pnl > 0 else "Protected loss")
    if flat:
        return "Scratch"
    return "Unprotected winner" if pnl > 0 else "Full loser"


def _num_or_none(v) -> Optional[float]:
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _mt5_track(cid: str, snap: dict, deals) -> None:
    """Relay hook: runs on every EA snapshot."""
    if deals is not None:
        _mt5_state["deals"], _mt5_state["deals_at"] = deals, time.time()
    now = time.time()
    if now - _mt5_state["last"] < MT5_EVERY_S:
        return
    owner = _mt5_owner_channel()
    if not owner or cid != owner:
        return
    _mt5_state["last"] = now
    if not _mt5_state["loaded"]:
        _load_open_mt5()
    t_ms = int(now * 1000)
    seen = set()
    for p in (snap or {}).get("positions") or []:
        try:
            key = "mt5:" + str(p["ticket"])
            side = p["side"]
            entry, price = float(p["entry"]), float(p["price"])
            vol, pnl = float(p["volume"]), float(p.get("profit") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        sl, tp = _num_or_none(p.get("sl")), _num_or_none(p.get("tp"))
        opened = int(p.get("time") or 0) * 1000 or t_ms
        seen.add(key)
        s = 1 if side == "buy" else -1
        r = _mt5_open.get(key)
        dirty = False
        if r is None:
            late = t_ms - opened > 90_000
            r = _mt5_open[key] = {
                "key": key, "src": "mt5", "tracker": "server", "symbol": p.get("symbol"), "label": p.get("symbol"),
                "side": side, "entry": entry, "opened": opened, "first_seen": t_ms, "late": late,
                "initial_sl": None if late else sl, "r_dist": None,
                "sentinel_id": None, "events": [{"t": t_ms, "type": "joined" if late else "open",
                                                 "sl": sl, "tp": tp, "volume": vol, "price": price}],
                "sl": sl, "tp": tp, "volume": vol, "max_volume": vol,
                "be_at": None, "lock_at": None, "locked_r": None, "locked_pnl": None,
                "mfe_price": price, "peak_pnl": pnl, "pnl_now": pnl, "closed": None,
            }
            if r["initial_sl"] is not None:
                r["r_dist"] = abs(entry - r["initial_sl"])
            dirty = True
        if r.get("r_dist") is None and sl is not None and not r.get("late") and s * (sl - entry) < 0:
            r["initial_sl"], r["r_dist"] = sl, abs(entry - sl)
            dirty = True
        if sl != r.get("sl"):
            r["events"].append({"t": t_ms, "type": "stop", "from": r.get("sl"), "to": sl, "price": price, "pnl": pnl})
            r["sl"] = sl
            dirty = True
        if tp != r.get("tp"):
            r["events"].append({"t": t_ms, "type": "target", "from": r.get("tp"), "to": tp})
            r["tp"] = tp
            dirty = True
        if vol < (r.get("volume") or vol) - 1e-9:
            r["events"].append({"t": t_ms, "type": "partial", "closed": round(r["volume"] - vol, 6), "price": price, "pnl": pnl})
            dirty = True
        r["volume"] = vol
        if r.get("mfe_price") is None or s * (price - r["mfe_price"]) > 0:
            r["mfe_price"] = price
        r["pnl_now"] = pnl
        if r.get("peak_pnl") is None or pnl > r["peak_pnl"]:
            r["peak_pnl"] = pnl
        if sl is not None and s * (sl - entry) >= -1e-9:
            if not r.get("be_at"):
                r["be_at"] = t_ms
                r["events"].append({"t": t_ms, "type": "risk_free", "sl": sl})
                dirty = True
            if r.get("r_dist"):
                lr = round(s * (sl - entry) / r["r_dist"], 3)
                if r.get("locked_r") is None or lr > r["locked_r"]:
                    r["locked_r"] = lr
            if price != entry:
                lp = round(pnl * (sl - entry) / (price - entry), 2)
                if r.get("locked_pnl") is None or lp > r["locked_pnl"]:
                    r["locked_pnl"] = lp
            if s * (sl - entry) > 0 and not r.get("lock_at"):
                r["lock_at"] = t_ms
        if r.get("r_dist"):
            r["mfe_r"] = round(s * (r["mfe_price"] - entry) / r["r_dist"], 3)
        if not r.get("rule_checked"):
            # money per unit of price from the live P&L (linear), times the 1R distance
            per = abs(pnl / (price - entry)) if abs(price - entry) > 1e-12 and pnl else None
            acct = (snap or {}).get("account") or {}
            eq = _num_or_none(acct.get("equity")) or _num_or_none(acct.get("balance"))
            was = r.get("rule_break")
            rule_break(r, eq, per * r["r_dist"] if per and r.get("r_dist") else None, t_ms)
            dirty = dirty or r.get("rule_break") != was
        r["_saved"] = r.get("_saved", 0)
        if dirty or t_ms - r["_saved"] > 30_000:
            r["_saved"] = t_ms
            _save_managed(r)
    # Closed: gone from the snapshot. Take the exit from the deal history.
    for key in [k for k in _mt5_open if k not in seen]:
        r = _mt5_open[key]
        ticket = key.split(":", 1)[1]
        rows = [d for d in _mt5_state["deals"] if isinstance(d, dict) and d.get("kind") == "trade"
                and str(d.get("ticket")) == ticket]
        if not rows and t_ms - r.setdefault("_gone", t_ms) < 180_000:
            continue                                  # history arrives on its own schedule
        s = 1 if r["side"] == "buy" else -1
        r["closed"] = t_ms
        r["exit_price"] = float(rows[0]["exit"]) if rows else None
        r["pnl"] = round(sum(float(d.get("profit") or 0) for d in rows), 2) if rows else r.get("pnl_now")
        r["exit_reason"] = rows[0].get("reason", "Manual") if rows else "Unknown"
        r["exit_r"] = (round(s * (r["exit_price"] - r["entry"]) / r["r_dist"], 3)
                       if r.get("r_dist") and r["exit_price"] is not None else None)
        if (not r.get("be_at") and "stop" in (r["exit_reason"] or "").lower()
                and r["exit_price"] is not None and s * (r["exit_price"] - r["entry"]) >= -1e-9):
            r["be_at"] = t_ms
            r["events"].append({"t": t_ms, "type": "risk_free", "sl": r["exit_price"]})
        r["stage"] = mgmt_stage(r)
        r["events"].append({"t": t_ms, "type": "close", "price": r["exit_price"], "pnl": r["pnl"],
                            "reason": r["exit_reason"]})
        r.pop("_gone", None)
        _save_managed(r)
        _mt5_open.pop(key, None)


try:
    import mt5_bridge as _bridge
    _bridge.SNAPSHOT_HOOKS.append(_mt5_track)
except Exception:        # bridge not present (tests): server tracking simply off
    _bridge = None


@router.post("/managed/bind")
async def managed_bind(request: Request) -> dict:
    """Owner-only: mark THIS bridge key's channel as the owner's MT5 account."""
    _check_key(request)
    cid = _bridge.channel_id(request.headers.get("x-bridge-key", "")) if _bridge else None
    if not cid:
        raise HTTPException(400, "Send the MT5 bridge key in X-Bridge-Key")
    if _mt5_owner_channel() != cid:
        _meta_set("mt5_channel", cid)
        _mt5_open.clear()
        _mt5_state["loaded"] = False
    return {"bound": True, "server_tracking": True}


@router.post("/managed/link")
async def managed_link(request: Request) -> dict:
    """Owner-only: attach a Sentinel setup to an MT5 position the server tracks."""
    _check_key(request)
    body = await request.json()
    key, sid = str(body.get("key", "")), str(body.get("sentinel_id", ""))
    if not key.startswith("mt5:") or not sid:
        raise HTTPException(400, "Send {key: 'mt5:<ticket>', sentinel_id, sl, sl_dist}")
    r = _mt5_open.get(key)
    if r is None:
        with _lock, _db() as con:
            row = con.execute("SELECT data FROM managed WHERE key=?", (key,)).fetchone()
        r = json.loads(row[0]) if row else None
    if r is None:
        raise HTTPException(404, "Position not tracked yet")
    r["sentinel_id"] = sid
    r["sentinel_model"] = body.get("model")
    try:
        sd = float(body.get("sl_dist") or 0)
        if sd > 0:
            r["r_dist"], r["initial_sl"] = sd, float(body.get("sl"))
    except (TypeError, ValueError):
        pass
    _save_managed(r)
    return {"linked": True}


@router.get("/managed")
def managed(request: Request) -> dict:
    _check_key(request)
    recs = _managed_rows()
    _attach_sentinel(recs)
    return {"records": recs[:100], "stats": _managed_stats(recs),
            "server_tracking": bool(_mt5_owner_channel()),
            "mt5_open_tracked": len(_mt5_open)}


@router.post("/managed")
async def managed_upsert(request: Request) -> dict:
    """Owner-only: the terminal sends the records it has been tracking."""
    _check_key(request)
    body = await request.json()
    items = body.get("records") if isinstance(body, dict) else None
    if not isinstance(items, list) or len(items) > 200:
        raise HTTPException(400, "Send {\"records\": [...]} (at most 200)")
    saved = 0
    server_mt5 = bool(_mt5_owner_channel())
    with _lock, _db() as con:
        for r in items:
            if not isinstance(r, dict) or not isinstance(r.get("key"), str) or len(r["key"]) > 80:
                continue
            if server_mt5 and r["key"].startswith("mt5:"):
                continue            # the server tracks MT5 itself; it is the authority
            blob = json.dumps(r)
            if len(blob) > 20000:
                continue
            con.execute("INSERT OR REPLACE INTO managed VALUES (?,?,?,?)",
                        (r["key"], int(r.get("opened") or 0), int(r.get("closed") or 0) or None, blob))
            saved += 1
    return {"saved": saved}


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
