"""
Sentinel watches the owner's paper account.

The paper account the trader uses on his phone (and every browser signed in
with the instructor's Academy account) is saved on this server as the
workspace document "trade" (accounts.py): balance, the last 500 fills, open
positions and orders. This module reads that document — read-only, owner
only — and turns it into evidence about the trader's own style:

  positions   fills grouped into positions (partial closes merged), kept in
              sentinel.db so the history outlives the 500-fill cap
  dollars     balance, profit since the start, wins and losses, worst and
              best trade, closed-equity drawdown, how much of the profit the
              biggest five trades carry
  R           the risk at the first stop is recorded when a paper position
              opens (paper keeps a stop on every trade), so R here is real:
              average R per position with its 95% interval, and a plain
              "is this beyond chance yet?" check
  breakdowns  by instrument, by how the trade ended, by setup tag (from the
              trade-management journal, counted only when tagged while open)
  twin        every closed paper position is also handed to Joel Twin
              (joel_twin.py) as "paperacct:<position>", so the journal can
              show you vs your rules on paper too

Paper fills use Deriv's public bid/ask: the spread is paid, slippage, swap
and commission are not. That caveat is shown with the numbers.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
from typing import Any, Optional

log = logging.getLogger("sentinel.paper")

START_BALANCE = 10_000.0          # the paper account's opening balance (S.balance / S.startBal in the app)
FILL_CAP = 500                    # the app keeps the last 500 fills in the saved document
MIN_N_SKILL = 30

_S = None                         # the sentinel module (set by attach)
_state: dict[str, Any] = {"last_read": None, "doc_updated": None, "positions": 0, "last_error": None}


def attach(sentinel_module) -> None:
    global _S
    _S = sentinel_module


# ── reading the saved paper account ──────────────────────────────────────────

def owner_doc() -> Optional[dict]:
    """The instructor's saved paper account, or None. Never another person's."""
    try:
        import accounts
    except Exception:
        return None
    try:
        with accounts._db() as db:
            row = db.execute("SELECT w.data, w.updated FROM workspace w JOIN users u ON u.id = w.user_id "
                             "WHERE u.role = 'teacher' AND w.key = 'trade' ORDER BY w.updated DESC LIMIT 1").fetchone()
    except sqlite3.Error as e:
        _state["last_error"] = str(e)
        return None
    if not row:
        return None
    try:
        doc = json.loads(row["data"] if isinstance(row, sqlite3.Row) else row[0])
    except (TypeError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    doc["_updated"] = row["updated"] if isinstance(row, sqlite3.Row) else row[1]
    return doc


def positions_from_fills(fills: list[dict]) -> list[dict]:
    """Fills → positions. A position is one id opened at one entry; partial
    closes are merged (volume-weighted exit, summed P&L)."""
    groups: dict[str, list[dict]] = {}
    for f in fills or []:
        if not isinstance(f, dict) or f.get("id") is None or not isinstance(f.get("pnl"), (int, float)):
            continue
        key = f"{f['id']}@{f.get('openTime') or f.get('entry')}"
        groups.setdefault(key, []).append(f)
    out = []
    for key, fs in groups.items():
        fs.sort(key=lambda f: f.get("closeTime") or 0)
        first, last = fs[0], fs[-1]
        vol = sum(float(f.get("volume") or 0) for f in fs)
        exit_px = (sum(float(f.get("exit") or 0) * float(f.get("volume") or 0) for f in fs) / vol) if vol else last.get("exit")
        pnl = round(sum(f["pnl"] for f in fs), 2)
        risk0 = first.get("risk0") if isinstance(first.get("risk0"), (int, float)) and first.get("risk0") > 0 else None
        out.append({
            "key": key, "id": first["id"], "sym": first.get("sym"), "label": first.get("pair") or first.get("sym"),
            "side": first.get("type"), "entry": first.get("entry"), "exit": exit_px, "volume": round(vol, 6),
            "open": first.get("openTime"), "close": last.get("closeTime"), "pnl": pnl,
            "reason": last.get("reason") or "Manual", "fills": len(fs), "closed": any(f.get("final") for f in fs),
            "sl0": first.get("sl0"), "risk0": risk0, "sl0_inferred": bool(first.get("sl0_inferred")),
            "r": round(pnl / risk0, 4) if risk0 else None,
        })
    out.sort(key=lambda p: p.get("close") or 0)
    return out


# ── persistence: keep positions beyond the 500-fill window ───────────────────

def _table(con) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS paper_positions (key TEXT PRIMARY KEY, close INTEGER, data TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS paper_meta (k TEXT PRIMARY KEY, v TEXT)")


FIRST_BOOK = "book-1"                  # positions stored before books existed belong here


def _meta_get(con, k: str) -> Optional[str]:
    row = con.execute("SELECT v FROM paper_meta WHERE k=?", (k,)).fetchone()
    return row[0] if row else None


def current_book() -> str:
    with _S._lock, _S._db() as con:
        _table(con)
        return _meta_get(con, "book") or FIRST_BOOK


def resolve_book(positions: list[dict], balance: Optional[float] = None) -> str:
    """Which paper account the saved document is. The same account shares a
    closed position with a stored one, or (when the 500-fill window has moved
    past every stored one) its balance follows on from the last one read plus
    the new results. Anything else is a different paper account (another
    device's) and gets its own book, so two accounts' results never mix."""
    keys = [p["key"] for p in positions if p.get("closed")]
    with _S._lock, _S._db() as con:
        _table(con)
        cur = _meta_get(con, "book") or FIRST_BOOK
        if not keys:
            return cur
        found = None
        for i in range(0, len(keys), 400):
            chunk = keys[i:i + 400]
            row = con.execute(f"SELECT data FROM paper_positions WHERE key IN ({','.join('?' * len(chunk))}) LIMIT 1", chunk).fetchone()
            if row:
                found = json.loads(row[0]).get("book") or FIRST_BOOK
                break
        if found is None:
            used = sum(1 for (d,) in con.execute("SELECT data FROM paper_positions")      # positions already in the current book
                       if (json.loads(d).get("book") or FIRST_BOOK) == cur)
            last = _meta_get(con, "balance:" + cur)
            follows = (balance is not None and last is not None
                       and abs(float(last) + sum(p["pnl"] for p in positions if p.get("closed")) - float(balance)) < 0.02)
            found = cur if (not used or follows) else f"book-{int(time.time())}"
        if balance is not None:
            con.execute("INSERT OR REPLACE INTO paper_meta VALUES (?, ?)", ("balance:" + found, repr(float(balance))))
        if found != cur:
            con.execute("INSERT OR REPLACE INTO paper_meta VALUES ('book', ?)", (found,))
            log.info("paper monitor: the saved paper account changed (%s -> %s)", cur, found)
        return found


def persist(positions: list[dict], book: Optional[str] = None) -> int:
    book = book or current_book()
    n = 0
    with _S._lock, _S._db() as con:
        _table(con)
        for p in positions:
            if not p.get("closed"):
                continue
            p = dict(p, book=book)
            con.execute("INSERT OR REPLACE INTO paper_positions VALUES (?,?,?)",
                        (p["key"], int(p.get("close") or 0), json.dumps(p)))
            n += 1
    return n


def stored(book: Optional[str] = None) -> list[dict]:
    """Stored closed positions of one paper account (the current one by default)."""
    book = book or current_book()
    with _S._lock, _S._db() as con:
        _table(con)
        rows = con.execute("SELECT data FROM paper_positions ORDER BY close").fetchall()
    out = [json.loads(r[0]) for r in rows]
    return [p for p in out if (p.get("book") or FIRST_BOOK) == book]


def other_books() -> dict[str, int]:
    """Earlier paper accounts kept apart: book -> closed positions."""
    cur = current_book()
    with _S._lock, _S._db() as con:
        _table(con)
        rows = con.execute("SELECT data FROM paper_positions").fetchall()
    out: dict[str, int] = {}
    for (d,) in rows:
        b = json.loads(d).get("book") or FIRST_BOOK
        if b != cur:
            out[b] = out.get(b, 0) + 1
    return out


def cycle() -> None:
    """After every scanner cycle: read the saved paper account and keep its positions."""
    try:
        doc = owner_doc()
        _state["last_read"] = time.time()
        if not doc:
            return
        _state["doc_updated"] = doc.get("_updated")
        ps = positions_from_fills(doc.get("trades") or [])
        bal = doc.get("balance") if isinstance(doc.get("balance"), (int, float)) else None
        book = resolve_book(ps, bal)
        _state["book"] = book
        _state["positions"] = persist(ps, book)
    except Exception as e:
        _state["last_error"] = f"{time.strftime('%H:%M:%S', time.gmtime())} {e}"
        log.warning("paper monitor: %s", e)


# ── analysis ─────────────────────────────────────────────────────────────────

def _mean_ci(xs: list[float]) -> tuple[Optional[float], Optional[list[float]], Optional[float]]:
    n = len(xs)
    if not n:
        return None, None, None
    m = sum(xs) / n
    if n < 2:
        return m, None, None
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    se = sd / math.sqrt(n)
    return m, [m - 1.96 * se, m + 1.96 * se], (m / se if se > 0 else None)


def skill_verdict(n: int, ci: Optional[list[float]]) -> str:
    if n < MIN_N_SKILL or not ci:
        return f"too few positions with a recorded stop to judge ({n} of {MIN_N_SKILL})"
    if ci[0] > 0:
        return "positive beyond chance so far"
    if ci[1] < 0:
        return "negative beyond chance so far"
    return "not distinguishable from zero yet"


def balances_before(positions: list[dict], balance_now: float) -> dict[str, float]:
    """Balance just before each position opened, rebuilt backwards from today's
    balance: today minus everything closed after that position opened."""
    out = {}
    for p in positions:
        t = p.get("open") or 0
        later = sum(q["pnl"] for q in positions if (q.get("close") or 0) > t)
        out[p["key"]] = balance_now - later
    return out


def analyze(doc: Optional[dict], positions: list[dict], setups: Optional[dict] = None) -> dict:
    """Everything the Sentinel tab shows about the paper account."""
    setups = setups or {}
    closed = [p for p in positions if p.get("closed")]
    balance = float(doc.get("balance")) if doc and isinstance(doc.get("balance"), (int, float)) else None
    fills = (doc or {}).get("trades") or []
    doc_pnl = sum(f.get("pnl") or 0 for f in fills if isinstance(f, dict))
    complete = len(fills) < FILL_CAP
    start = (balance - doc_pnl) if (balance is not None and complete) else None
    out: dict[str, Any] = {"balance": round(balance, 2) if balance is not None else None,
                           "start_balance": round(start, 2) if start is not None else None,
                           "history_complete": complete, "n": len(closed),
                           "caveat": "Paper fills at Deriv's public bid/ask: the spread is paid; slippage, swap and commission are not."}
    open_pos = (doc or {}).get("positions") or []
    out["open"] = {"n": len(open_pos), "risk_at_stops": round(sum(float(p.get("risk0") or 0) for p in open_pos if isinstance(p, dict)), 2),
                   "symbols": sorted({str(p.get("label") or p.get("symbol")) for p in open_pos if isinstance(p, dict)})[:8]}
    if not closed:
        return out
    pnl = [p["pnl"] for p in closed]
    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x < 0]
    eq = peak = 0.0
    dd = 0.0
    for x in pnl:
        eq += x
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    top = sorted(pnl, reverse=True)
    gross = sum(wins)
    rs = [p["r"] for p in closed if isinstance(p.get("r"), (int, float)) and not p.get("sl0_inferred")]
    m, ci, t = _mean_ci(rs)
    out.update({
        "pnl_total": round(sum(pnl), 2), "wins": len(wins), "losses": len(losses),
        "win_pct": round(len(wins) / len(closed), 4),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "best": round(max(pnl), 2), "worst": round(min(pnl), 2),
        "profit_factor": round(gross / -sum(losses), 2) if losses else None,
        "max_drawdown": round(dd, 2),
        "top5_share": round(sum(top[:5]) / sum(pnl), 4) if sum(pnl) > 0 else None,
        "r": {"n": len(rs), "mean": round(m, 3) if m is not None else None,
              "ci95": [round(ci[0], 3), round(ci[1], 3)] if ci else None, "t": round(t, 2) if t else None,
              "median": round(sorted(rs)[len(rs) // 2], 3) if rs else None,
              "full_stop_pct": round(sum(1 for r in rs if r <= -0.95) / len(rs), 4) if rs else None,
              "verdict": skill_verdict(len(rs), ci)},
    })
    try:
        import sentinel_core as core
        syn = sum(1 for p in closed if getattr(core.MARKET_BY_ID.get(str(p.get("sym"))), "mode", "") == "synthetic")
        out["synthetic_share"] = round(syn / len(closed), 4)
    except Exception:
        out["synthetic_share"] = None
    first, lastp = closed[0].get("open") or closed[0].get("close"), closed[-1].get("close")
    out["period"] = [first, lastp]

    def group(fn) -> dict:
        g: dict[str, dict] = {}
        for p in closed:
            k = fn(p)
            if not k:
                continue
            x = g.setdefault(k, {"n": 0, "pnl": 0.0, "wins": 0, "_r": []})
            x["n"] += 1
            x["pnl"] = round(x["pnl"] + p["pnl"], 2)
            x["wins"] += 1 if p["pnl"] > 0 else 0
            if isinstance(p.get("r"), (int, float)) and not p.get("sl0_inferred"):
                x["_r"].append(p["r"])
        for x in g.values():
            rr = x.pop("_r")
            x["avg_r"] = round(sum(rr) / len(rr), 3) if rr else None
            x["win_pct"] = round(x["wins"] / x["n"], 4)
        return dict(sorted(g.items(), key=lambda kv: -kv[1]["n"]))

    out["by_instrument"] = group(lambda p: p.get("label") or p.get("sym"))
    out["by_exit"] = group(lambda p: {"Stop loss": "stop", "Take profit": "target"}.get(p.get("reason"), "manual / other"))
    out["by_setup"] = group(lambda p: setups.get(str(p["id"])))
    out["untagged"] = sum(1 for p in closed if not setups.get(str(p["id"])))
    out["recent"] = [{k: p.get(k) for k in ("key", "label", "side", "pnl", "r", "reason", "open", "close")} for p in closed[-12:]][::-1]
    return out


def setups_from_journal(managed: list[dict]) -> dict[str, str]:
    """Paper position id → setup, from the trade-management journal (tags given while open only)."""
    out = {}
    for r in managed:
        k = str(r.get("key") or "")
        if k.startswith("paper:") and r.get("setup") and not r.get("setup_after_close"):
            out[k.split(":", 1)[1]] = r["setup"]
    return out


def twin_records(positions: Optional[list[dict]] = None, balance_now: Optional[float] = None) -> list[dict]:
    """Closed paper positions in the shape Joel Twin replays (key 'paperacct:...')."""
    if positions is None:
        positions = stored()
    if balance_now is None:
        doc = owner_doc()
        balance_now = float(doc["balance"]) if doc and isinstance(doc.get("balance"), (int, float)) else None
    if balance_now is None:
        return []
    before = balances_before(positions, balance_now)
    out = []
    for p in positions:
        if not p.get("closed") or not p.get("open") or not p.get("risk0") or p.get("sl0") is None or p.get("sl0_inferred"):
            continue
        dist = abs(float(p["entry"]) - float(p["sl0"]))
        if dist <= 0:
            continue
        out.append({"key": "paperacct:" + p["key"], "src": "paperacct", "symbol": p.get("sym"), "label": p.get("label"),
                    "side": p.get("side"), "entry": p["entry"], "opened": int(p["open"]), "closed": int(p["close"] or 0),
                    "initial_sl": p["sl0"], "r_dist": dist, "per_unit": float(p["risk0"]) / dist,
                    "eq_open": round(before.get(p["key"]) or 0, 2) or None, "pnl": p["pnl"], "exit_price": p.get("exit"),
                    "exit_reason": p.get("reason"), "events": []})
    return out
