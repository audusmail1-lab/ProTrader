"""
Sentinel research loop — the persistent, evidence-driven layer around the
scanner (design: research/docs/03-design.md).

  registry    frozen strategy versions (rules hashed, immutable), evaluation
              cohorts per version and evidence kind (backtest / paper / demo /
              live), explicit states with recorded transitions and rollbacks
  counting    unique, fully resolved positions per cohort; open, duplicate and
              unreconciled rows never count; re-runs over old bars never count
  reviews     100-trade diagnostic, 150-trade formal, then every 150 trades,
              each boundary stored once (UNIQUE(cohort, boundary)) so a
              restart cannot repeat it; classification: eligible /
              inconclusive / underperforming / invalid, with the diagnosis
  integrity   checked every cycle, acts at once (invalid), never waits for 100
  challengers one ResearchBook (research_lab) per version in paper-testing,
              fed the same bars the incumbent sees, journaled in its own table
  jobs        bounded experiment queue (per-day count, minutes per job)
  API         /api/sentinel/research/* — read for everyone, decisions for the
              owner (same key as the rest of Sentinel)

Nothing here places orders, changes the risk limits, or changes the
incumbent: a promotion is a recorded decision; the scanner's model is pinned
in code and a change to it is a reviewed release.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

import research_lab as lab
import sentinel_core as core

log = logging.getLogger("sentinel.research")
router = APIRouter(prefix="/research", tags=["sentinel-research"])   # included into /api/sentinel

HERE = os.path.dirname(os.path.abspath(__file__))
LIBRARY_DB = os.path.join(HERE, "research", "research.db")          # committed research library (read-only here)

STATES = ["researching", "backtesting", "validating", "paper-testing", "monitoring", "paused", "retired"]
TRANSITIONS = {
    "researching": {"backtesting", "retired"},
    "backtesting": {"validating", "researching", "retired"},
    "validating": {"paper-testing", "researching", "retired"},
    "paper-testing": {"monitoring", "paused", "retired", "validating"},
    "monitoring": {"paused", "retired"},
    "paused": {"paper-testing", "monitoring", "retired"},
    "retired": set(),
}
EVIDENCE_KINDS = ("backtest", "paper", "demo", "live")
CLASSES = ("eligible", "inconclusive", "underperforming", "invalid")
# The 7.2c paper journal began on 27 Sep 2026 (research/docs/01); trades before that were another model.
INCUMBENT_JOURNAL_START = __import__("calendar").timegm((2026, 9, 27, 0, 0, 0))

# Challengers defined in code. Each is registered once (child of the incumbent at
# the time of its first registration) and moved straight to paper-testing with
# the evidence named here, so it runs as a research book beside the incumbent
# without an owner-key call. It is NOT code-backed: the scanner cannot run it
# as the incumbent until a reviewed release teaches it to, so a promotion is
# reported as 'awaiting release'. Owner decisions (pause/retire) are respected
# on restart: an existing version is never re-transitioned.
REAL_MARKETS = ("frxNAS100", "frxXAUUSD", "cryBTCUSD")
CODE_CHALLENGERS = [
    {
        "key": "7.3-candidate",
        "name": "ARIA 7.3 candidate: real markets, cost cap 0.05, exit shadows",
        "rules": {"gates": {"cost_cap": 0.05}, "shadows": True},
        "slices": [[m, tf] for m in REAL_MARKETS for tf in ("15m", "1h", "4h")],
        "reason": ("same ARIA 7.2c entries and exit; skips entries whose spread exceeds 5% of the stop "
                   "(H2 cost rule: +0.057R dev, +0.109R val vs base on one year, never counted as edge); "
                   "real markets only (synthetic indices are a random number generator by Deriv's own description: "
                   "155 of 227 forward trades, -27.1R); shadows atr2 and chan10 paired against the model exit (H4, B3)"),
        "evidence_ref": "research/experiments/H2-costcap.result.json; research/experiments/V73-candidate.result.json; research/docs/04 B2+B3",
        "notes": "owner request 7 Oct 2026 ('build'); judged at 100/150 trades against the incumbent on the matched period",
    },
]

DEFAULT_CONFIG = {
    "diagnostic_at": 100,
    "formal_at": 150,
    "formal_every": 150,
    "criteria": {
        "eligible": {"min_n": 150, "pf_min": 1.2, "max_dd_r": 25, "min_days": 60, "min_regimes": 2,
                     "cost_mult_must_hold": 1.5, "thirds_positive_min": 2, "ci": "block"},
        "underperforming": {"exp_max_at_n": -0.05, "n_for_exp": 150, "max_dd_r": 40},
        "invalid": {"unknown_cost_share": 0.10, "unreconciled_share": 0.05, "scanner_stale_s": 3600},
    },
    "budget": {"experiments_per_day": 2, "max_minutes": 20},
    "incumbent_version": None,
}

_lock = threading.Lock()
_S = None                                     # the sentinel module (set by attach)
_books: dict[str, lab.ResearchBook] = {}      # challenger books by version id
_state: dict[str, Any] = {"started_at": None, "last_cycle": None, "cycles": 0, "last_error": None,
                          "last_integrity": None, "db": None}
_job_thread: Optional[threading.Thread] = None


# ── storage ──────────────────────────────────────────────────────────────────

def db_path() -> str:
    want = os.getenv("SENTINEL_RESEARCH_DB", "").strip()
    if want:
        return want
    if _S is not None:
        return os.path.join(os.path.dirname(_S.DB_PATH), "sentinel_research.db")
    return os.path.join(HERE, "sentinel_research.db")


SCHEMA = """
CREATE TABLE IF NOT EXISTS versions (
    id TEXT PRIMARY KEY, name TEXT, parent_id TEXT, rules TEXT, slices TEXT, code_backed INTEGER,
    created_at INTEGER, frozen_at INTEGER, state TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS cohorts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, version_id TEXT, evidence_kind TEXT, started_at INTEGER,
    ended_at INTEGER, label TEXT, trade_filter TEXT, created_at INTEGER);
CREATE TABLE IF NOT EXISTS research_trades (
    version_id TEXT, id TEXT, cohort_id INTEGER, market TEXT, tf TEXT, status TEXT,
    opened_at INTEGER, closed_at INTEGER, data TEXT, PRIMARY KEY (version_id, id));
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT, cohort_id INTEGER, boundary INTEGER, kind TEXT, trade_count INTEGER,
    computed_at INTEGER, metrics TEXT, classification TEXT, diagnosis TEXT, actions TEXT, decided_by TEXT,
    UNIQUE (cohort_id, boundary));
CREATE TABLE IF NOT EXISTS transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, version_id TEXT, from_state TEXT, to_state TEXT, at INTEGER,
    reason TEXT, evidence_ref TEXT, by TEXT);
CREATE TABLE IF NOT EXISTS config (k TEXT PRIMARY KEY, v TEXT, updated_at INTEGER);
CREATE TABLE IF NOT EXISTS config_history (id INTEGER PRIMARY KEY AUTOINCREMENT, k TEXT, v TEXT, at INTEGER, by TEXT);
CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY, hypothesis TEXT, version_id TEXT, kind TEXT, spec TEXT, results TEXT, verdict TEXT,
    notes TEXT, created_at INTEGER);
CREATE TABLE IF NOT EXISTS integrity (id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER, cohort_id INTEGER,
    ok INTEGER, flags TEXT);
CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, spec TEXT, state TEXT,
    created_at INTEGER, started_at INTEGER, finished_at INTEGER, result TEXT, by TEXT);
"""


def _db() -> sqlite3.Connection:
    p = db_path()
    con = sqlite3.connect(p, timeout=10)
    con.executescript(SCHEMA)
    return con


def cfg_get(k: str, default: Any = None) -> Any:
    with _lock, _db() as con:
        row = con.execute("SELECT v FROM config WHERE k=?", (k,)).fetchone()
    if row:
        return json.loads(row[0])
    return DEFAULT_CONFIG.get(k, default) if default is None else default


def cfg_set(k: str, v: Any, by: str = "system") -> None:
    now = int(time.time())
    with _lock, _db() as con:
        con.execute("INSERT OR REPLACE INTO config VALUES (?,?,?)", (k, json.dumps(v), now))
        con.execute("INSERT INTO config_history (k, v, at, by) VALUES (?,?,?,?)", (k, json.dumps(v), now, by))


def config() -> dict:
    out = dict(DEFAULT_CONFIG)
    with _lock, _db() as con:
        for k, v in con.execute("SELECT k, v FROM config"):
            if not k.startswith("eval:"):
                out[k] = json.loads(v)
    return out


# ── versions ─────────────────────────────────────────────────────────────────

def version_id(rules: dict, parent_id: Optional[str]) -> str:
    """Immutable identity: the rules hash plus the parent. Same rules under
    the same parent → the same version; any change → a new one."""
    return hashlib.sha1(f"{parent_id or ''}|{lab.rules_id(rules)}".encode()).hexdigest()[:12]


def get_version(vid: str) -> Optional[dict]:
    with _lock, _db() as con:
        row = con.execute("SELECT * FROM versions WHERE id=?", (vid,)).fetchone()
        cols = [c[1] for c in con.execute("PRAGMA table_info(versions)")]
    if not row:
        return None
    d = dict(zip(cols, row))
    d["rules"] = json.loads(d["rules"])
    d["slices"] = json.loads(d["slices"] or "[]")
    return d


def list_versions() -> list[dict]:
    with _lock, _db() as con:
        rows = con.execute("SELECT id FROM versions ORDER BY created_at").fetchall()
    return [get_version(r[0]) for r in rows]


def create_version(name: str, rules: dict, slices: list, parent_id: Optional[str] = None, notes: str = "",
                   state: str = "researching", code_backed: bool = False, by: str = "system") -> dict:
    rules = lab.normalize(rules)
    vid = version_id(rules, parent_id)
    now = int(time.time())
    with _lock, _db() as con:
        if con.execute("SELECT 1 FROM versions WHERE id=?", (vid,)).fetchone():
            return get_version_unlocked(con, vid)
        con.execute("INSERT INTO versions VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (vid, name, parent_id, json.dumps(rules), json.dumps([list(s) for s in slices]),
                     1 if code_backed else 0, now, now, state, notes))
        con.execute("INSERT INTO transitions (version_id, from_state, to_state, at, reason, evidence_ref, by) VALUES (?,?,?,?,?,?,?)",
                    (vid, None, state, now, "created", None, by))
    return get_version(vid)


def get_version_unlocked(con: sqlite3.Connection, vid: str) -> dict:
    row = con.execute("SELECT * FROM versions WHERE id=?", (vid,)).fetchone()
    cols = [c[1] for c in con.execute("PRAGMA table_info(versions)")]
    d = dict(zip(cols, row))
    d["rules"] = json.loads(d["rules"])
    d["slices"] = json.loads(d["slices"] or "[]")
    return d


def transition(vid: str, to_state: str, reason: str, evidence_ref: Optional[str] = None, by: str = "owner") -> dict:
    v = get_version(vid)
    if not v:
        raise HTTPException(404, "unknown version")
    if to_state not in STATES:
        raise HTTPException(400, f"unknown state {to_state}")
    if to_state not in TRANSITIONS[v["state"]]:
        raise HTTPException(409, f"{v['state']} → {to_state} is not an allowed transition")
    now = int(time.time())
    with _lock, _db() as con:
        con.execute("UPDATE versions SET state=? WHERE id=?", (to_state, vid))
        con.execute("INSERT INTO transitions (version_id, from_state, to_state, at, reason, evidence_ref, by) VALUES (?,?,?,?,?,?,?)",
                    (vid, v["state"], to_state, now, reason, evidence_ref, by))
        if to_state == "paper-testing" and not con.execute(
                "SELECT 1 FROM cohorts WHERE version_id=? AND evidence_kind='paper' AND ended_at IS NULL", (vid,)).fetchone():
            con.execute("INSERT INTO cohorts (version_id, evidence_kind, started_at, ended_at, label, trade_filter, created_at) VALUES (?,?,?,?,?,?,?)",
                        (vid, "paper", now, None, f"{v['name']} paper from {time.strftime('%Y-%m-%d', time.gmtime(now))}",
                         json.dumps({"kind": "research"}), now))
        if to_state in ("retired", "paused"):
            con.execute("UPDATE cohorts SET ended_at=? WHERE version_id=? AND ended_at IS NULL", (now, vid))
    _sync_books()
    return get_version(vid)


def promote(vid: str, reason: str, evidence_ref: Optional[str], by: str = "owner") -> dict:
    """Record the decision that `vid` is the incumbent. The scanner's model is
    pinned in code (sentinel_core.SENTINEL_MODEL), so a version that is not
    code-backed is reported as 'awaiting release' until a reviewed deploy
    makes the scanner run it. Rollback = promote the previous id again."""
    v = get_version(vid)
    if not v:
        raise HTTPException(404, "unknown version")
    if v["state"] not in ("paper-testing", "monitoring", "paused"):
        raise HTTPException(409, f"a version in state {v['state']} cannot be promoted")
    prev = cfg_get("incumbent_version")
    if v["state"] != "monitoring":
        transition(vid, "monitoring", reason, evidence_ref, by)
    cfg_set("incumbent_version", vid, by)
    now = int(time.time())
    with _lock, _db() as con:
        con.execute("INSERT INTO transitions (version_id, from_state, to_state, at, reason, evidence_ref, by) VALUES (?,?,?,?,?,?,?)",
                    (vid, f"incumbent:{prev}", "incumbent", now, reason, evidence_ref, by))
    return {"incumbent_version": vid, "previous": prev, "awaiting_release": not v["code_backed"]}


def rollback(reason: str, by: str = "owner") -> dict:
    """Return to the previous incumbent; its paper cohort resumes as a new cohort from now."""
    with _lock, _db() as con:
        rows = con.execute("SELECT from_state FROM transitions WHERE to_state='incumbent' ORDER BY id DESC LIMIT 1").fetchall()
    if not rows or not rows[0][0] or rows[0][0] == "incumbent:None":
        raise HTTPException(409, "no previous incumbent to roll back to")
    prev = rows[0][0].split(":", 1)[1]
    v = get_version(prev)
    if not v:
        raise HTTPException(409, f"previous incumbent {prev} no longer exists")
    if v["state"] in ("paused", "retired"):
        if v["state"] == "retired":
            raise HTTPException(409, "previous incumbent is retired")
        transition(prev, "monitoring", "rollback: " + reason, None, by)
    out = promote(prev, "rollback: " + reason, None, by)
    now = int(time.time())
    with _lock, _db() as con:
        con.execute("UPDATE cohorts SET ended_at=? WHERE version_id=? AND evidence_kind='paper' AND ended_at IS NULL", (now, prev))
        con.execute("INSERT INTO cohorts (version_id, evidence_kind, started_at, ended_at, label, trade_filter, created_at) VALUES (?,?,?,?,?,?,?)",
                    (prev, "paper", now, None, f"{v['name']} paper after rollback {time.strftime('%Y-%m-%d', time.gmtime(now))}",
                     json.dumps({"kind": "incumbent"} if v["code_backed"] else {"kind": "research"}), now))
    out["rollback"] = True
    return out


# ── cohorts and counting ─────────────────────────────────────────────────────

def list_cohorts(active_only: bool = False) -> list[dict]:
    with _lock, _db() as con:
        cols = [c[1] for c in con.execute("PRAGMA table_info(cohorts)")]
        rows = con.execute("SELECT * FROM cohorts" + (" WHERE ended_at IS NULL" if active_only else "") + " ORDER BY id").fetchall()
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        d["trade_filter"] = json.loads(d["trade_filter"] or "{}")
        out.append(d)
    return out


def get_cohort(cid: int) -> Optional[dict]:
    return next((c for c in list_cohorts() if c["id"] == cid), None)


def resolved_trades(cohort: dict) -> tuple[list[dict], dict]:
    """Unique, fully resolved positions of this cohort, oldest close first,
    plus the exclusions (what was left out and why). Rules:
      paper (incumbent, code-backed): sentinel.db trades of the pinned engine
        and model, status win/loss/timeout, opened inside the cohort window
      paper (research): research_trades of the version and cohort, resolved
      demo/live: live_trades rows that are closed AND carry fill, exit, r and
        pnl (reconciled); rows missing any of these are 'unreconciled'
    Open rows never count; duplicate ids count once; a trade opened before
    the cohort started (a re-run over old bars) never counts."""
    kind, flt = cohort["evidence_kind"], cohort["trade_filter"]
    start, end = cohort["started_at"], cohort["ended_at"] or 2 ** 40
    excl = {"open": 0, "duplicate": 0, "before_cohort": 0, "unreconciled": 0, "other_version": 0}
    rows: list[dict] = []
    if kind == "paper" and flt.get("kind") == "incumbent":
        if _S is None:
            return [], excl
        for t in _S._load_trades(limit=50000):
            if t.get("engine", "7.0") != core.eng.ENGINE_VERSION or t.get("model", "fixed") != core.SENTINEL_MODEL:
                excl["other_version"] += 1
                continue
            rows.append(t)
    elif kind == "paper":
        with _lock, _db() as con:
            got = con.execute("SELECT data FROM research_trades WHERE version_id=? AND cohort_id=?",
                              (cohort["version_id"], cohort["id"])).fetchall()
        rows = [json.loads(r[0]) for r in got]
    elif kind in ("demo", "live"):
        if _S is None or getattr(_S, "_live", None) is None:
            return [], excl
        for r in _S._live.rows(5000):
            if r.get("state") != "closed":
                if r.get("state") in ("open", "sent"):
                    excl["open"] += 1
                continue
            if any(r.get(k) is None for k in ("fill", "exit", "r", "pnl", "closed_at")):
                excl["unreconciled"] += 1
                continue
            rows.append({"id": r["id"], "market": r.get("market"), "tf": r.get("tf"), "status": "win" if r["r"] > 0 else "loss",
                         "opened_at": int(r.get("at") or 0), "closed_at": int(r["closed_at"]), "r": r["r"],
                         "cost_r": None, "pnl": r.get("pnl"), "paper_r": r.get("paper_r"), "trend_4h": None,
                         "mfe_r": None, "mae_r": None, "net_financial": True})
    seen: set[str] = set()
    out = []
    for t in rows:
        if t.get("status") not in ("win", "loss", "timeout"):
            excl["open"] += 1
            continue
        if not (start <= (t.get("opened_at") or 0) < end):
            excl["before_cohort"] += 1
            continue
        if t["id"] in seen:
            excl["duplicate"] += 1
            continue
        seen.add(t["id"])
        out.append(t)
    out.sort(key=lambda t: (t.get("closed_at") or 0, t["id"]))
    return out, excl


# ── reviews ──────────────────────────────────────────────────────────────────

def boundaries_due(n: int, c: dict) -> list[tuple[int, str]]:
    out = []
    if n >= c["diagnostic_at"]:
        out.append((c["diagnostic_at"], "diagnostic"))
    b = c["formal_at"]
    while b <= n:
        out.append((b, "formal"))
        b += c["formal_every"]
    return out


def _regimes(trades: list[dict]) -> int:
    return len({t.get("trend_4h") for t in trades if t.get("trend_4h") in ("up", "down", "flat")})


def classify(m: dict, trades: list[dict], kind: str, integrity_flags: list[str], c: dict,
             incumbent: Optional[dict] = None, versions_under_test: int = 1) -> tuple[str, list[str]]:
    """The four outcomes, with the reasons. Order: invalid, then eligible
    (formal only), then underperforming, else inconclusive."""
    why: list[str] = []
    if integrity_flags:
        return "invalid", ["integrity: " + f for f in integrity_flags]
    e, u = c["criteria"]["eligible"], c["criteria"]["underperforming"]
    n = m.get("n", 0)
    z = core.z_for(max(1, versions_under_test))
    se = m.get("se_r") or float("inf")
    lo_n = m["expectancy_r"] - z * se
    hi_n = m["expectancy_r"] + z * se
    lo_b = (m.get("ci95_block_r") or [lo_n, hi_n])[0]
    lo = min(lo_n, lo_b) if e.get("ci") == "block" else lo_n
    days = ((trades[-1]["closed_at"] - trades[0]["opened_at"]) / 86400) if trades else 0
    if kind == "formal":
        checks = {
            f"n >= {e['min_n']}": n >= e["min_n"],
            f"interval lower bound > 0 (z={z:.2f}, {versions_under_test} versions)": lo > 0,
            f"PF >= {e['pf_min']}": (m.get("profit_factor") or 0) >= e["pf_min"],
            f"max DD <= {e['max_dd_r']}R": (m.get("max_drawdown_r") or 0) <= e["max_dd_r"],
            f">= {e['min_days']} days": days >= e["min_days"],
            f">= {e['min_regimes']} regimes": _regimes(trades) >= e["min_regimes"],
            f"> 0 at spreads x{e['cost_mult_must_hold']}": (m.get("at_cost_mult") or {}).get(str(e["cost_mult_must_hold"]), -1) > 0,
            f"positive in >= {e['thirds_positive_min']} of 3 thirds": (m.get("thirds_positive") or 0) >= e["thirds_positive_min"],
        }
        if incumbent and incumbent.get("n"):
            checks["not worse than incumbent on the matched period"] = m["expectancy_r"] >= incumbent["expectancy_r"]
        failed = [k for k, ok in checks.items() if not ok]
        if not failed:
            return "eligible", ["all promotion criteria met at this checkpoint (not a guarantee of future results)"]
        why.extend("not eligible: " + k for k in failed)
    if hi_n < 0:
        return "underperforming", why + ["interval upper bound below zero"]
    if n >= u["n_for_exp"] and m["expectancy_r"] <= u["exp_max_at_n"]:
        return "underperforming", why + [f"expectancy {m['expectancy_r']} <= {u['exp_max_at_n']}R at n >= {u['n_for_exp']}"]
    if (m.get("max_drawdown_r") or 0) > u["max_dd_r"]:
        return "underperforming", why + [f"max drawdown {m['max_drawdown_r']}R > {u['max_dd_r']}R"]
    return "inconclusive", why + ["interval includes zero; keep collecting"]


def diagnose(trades: list[dict], m: dict) -> dict:
    """Attribute a weak result to the factors the research library addresses.
    Every score is an expectancy gap in R per trade (how much of the shortfall
    that factor accounts for, measured on these trades), so they compare on
    one scale; the dominant factor is the largest gap. Measured, not opinion."""
    n = len(trades)
    if not n:
        return {"dominant": "uncertainty", "scores": {}, "factors": {}}
    rs = [lab.net_r(t) for t in trades]
    overall = sum(rs) / n
    mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None

    def groups(keyfn):
        g: dict[str, list[float]] = {}
        for t, r in zip(trades, rs):
            g.setdefault(keyfn(t), []).append(r)
        return g

    def worst_gap(g):
        """Expectancy gained by not trading the worst group (needs >= 2 groups of >= 10 trades)."""
        big = {k: v for k, v in g.items() if len(v) >= 10}
        if len(big) < 2:
            return 0.0
        k, v = min(big.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))
        rest = [x for kk, vv in g.items() if kk != k for x in vv]
        return max(0.0, (sum(rest) / len(rest)) - overall) if rest else 0.0

    hour = lambda t: time.gmtime(t.get("opened_at") or 0).tm_hour
    sess = lambda t: ("asia 00-07" if hour(t) < 7 else "london 07-13" if hour(t) < 13 else "ny 13-21" if hour(t) < 21 else "late 21-24")
    by_regime = groups(lambda t: t.get("trend_4h") or "none")
    by_session = groups(sess)
    by_slice = groups(lambda t: f"{t.get('market')} {t.get('tf')}")
    never = [r for t, r in zip(trades, rs) if (t.get("mfe_r") or 0) < 0.5]
    entry_gap = (len(never) / n) * max(0.0, -sum(never) / len(never)) if never else 0.0
    winners = [t for t in trades if (t.get("mfe_r") or 0) >= 1 and (t.get("r") or 0) > 0]
    capt = [((t.get("r") or 0) + (t.get("cost_r") or 0)) / t["mfe_r"] for t in winners]
    capture = sum(capt) / len(capt) if capt else None
    giveback = (sum((1 - c) * t["mfe_r"] for c, t in zip(capt, winners)) / n) if capt else 0.0
    cost = sum((t.get("cost_r") or 0.0) for t in trades) / n
    se = m.get("se_r") or 0.0
    factors = {
        "entry": {"never_reached_0.5R": round(len(never) / n, 3), "mean_r_of_those": mean(never), "mfe_avg_r": m.get("mfe_avg_r")},
        "regime": {k: {"n": len(v), "mean_r": mean(v)} for k, v in by_regime.items()},
        "session": {k: {"n": len(v), "mean_r": mean(v)} for k, v in by_session.items()},
        "slices": {k: {"n": len(v), "mean_r": mean(v)} for k, v in by_slice.items()},
        "exit": {"capture_share": round(capture, 3) if capture is not None else None, "timeouts": m.get("timeouts"),
                 "giveback_r_per_trade": round(giveback, 3)},
        "costs": {"avg_cost_r": round(cost, 4), "cost_share": m.get("cost_share"),
                  "expectancy_x1.5": (m.get("at_cost_mult") or {}).get("1.5"), "expectancy_x2": (m.get("at_cost_mult") or {}).get("2.0")},
        "uncertainty": {"se_r": m.get("se_r"), "ci95_r": m.get("ci95_r"), "ci95_block_r": m.get("ci95_block_r")},
    }
    scores = {
        "entry quality (L18, L24, L25, H7)": entry_gap,
        "regime fit (L02, L03, L04, H3, H5)": worst_gap(by_regime),
        "session (L01, H1)": worst_gap(by_session),
        "slice mix (focus list)": worst_gap(by_slice),
        "exit (L09, L11, L12, H4)": giveback,
        "costs (L34, L05, H2)": cost,
        "uncertainty (interval width)": se,
    }
    dominant = max(scores.items(), key=lambda kv: kv[1])[0]
    return {"dominant": dominant, "unit": "R per trade", "scores": {k: round(v, 3) for k, v in scores.items()}, "factors": factors}


def _review_metrics(trades: list[dict]) -> dict:
    m = lab.metrics(trades)
    m["at_cost_mult"] = {"1.5": lab.metrics(trades, 1.5, boot=0).get("expectancy_r"),
                         "2.0": lab.metrics(trades, 2.0, boot=0).get("expectancy_r")}
    m["by_slice"] = lab.by_slice(trades)
    m["shadows"] = lab.shadow_summary(trades)        # each shadow exit paired against the model exit (empty when none ran)
    m["net_financial"] = all(t.get("net_financial") for t in trades) if trades else False
    m["cost_basis"] = ("reconciled net" if m["net_financial"] else
                       "price-based R minus estimated spread; commission, swap, slippage not modelled")
    return m


def incumbent_matched(cohort: dict, trades: list[dict]) -> Optional[dict]:
    """The incumbent's resolved trades over the same period, for comparison."""
    inc = cfg_get("incumbent_version")
    if not inc or cohort["version_id"] == inc or not trades:
        return None
    ic = next((c for c in list_cohorts() if c["version_id"] == inc and c["evidence_kind"] == cohort["evidence_kind"]
               and c["ended_at"] is None), None)
    if not ic:
        return None
    its, _ = resolved_trades(ic)
    lo, hi = trades[0]["opened_at"], trades[-1]["closed_at"]
    matched = [t for t in its if lo <= t["opened_at"] <= hi]
    return lab.metrics(matched, boot=0) if matched else None


def run_reviews(now: Optional[int] = None) -> list[dict]:
    """Produce every review that is due and not yet recorded. Idempotent."""
    now = now or int(time.time())
    c = config()
    made = []
    active = list_cohorts(active_only=True)
    under_test = max(1, sum(1 for v in list_versions() if v["state"] in ("paper-testing", "monitoring")))
    for coh in active:
        trades, excl = resolved_trades(coh)
        n = len(trades)
        flags = integrity_flags(coh, trades, excl, c)
        with _lock, _db() as con:
            done = {r[0] for r in con.execute("SELECT boundary FROM reviews WHERE cohort_id=?", (coh["id"],))}
        for b, kind in boundaries_due(n, c):
            if b in done:
                continue
            first = trades[:b]                                   # the first b resolved trades, always the same set
            m = _review_metrics(first)
            inc = incumbent_matched(coh, first)
            cls, why = classify(m, first, kind, flags, c, inc, under_test)
            diag = diagnose(first, m) if cls in ("underperforming", "inconclusive") else None
            actions = _actions_for(cls, kind, diag)
            rec = {"cohort_id": coh["id"], "boundary": b, "kind": kind, "trade_count": n, "computed_at": now,
                   "metrics": {**m, "incumbent_matched": inc, "exclusions": excl},
                   "classification": cls, "diagnosis": {"why": why, "attribution": diag}, "actions": actions, "decided_by": "system"}
            with _lock, _db() as con:
                try:
                    con.execute("INSERT INTO reviews (cohort_id, boundary, kind, trade_count, computed_at, metrics, classification, diagnosis, actions, decided_by) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                (coh["id"], b, kind, n, now, json.dumps(rec["metrics"]), cls, json.dumps(rec["diagnosis"]),
                                 json.dumps(actions), "system"))
                except sqlite3.IntegrityError:
                    continue                                     # another process got there first
            made.append(rec)
            _notify(f"review · {coh['label']} · {kind} at {b}: {cls} · {m['expectancy_r']:+.3f}R/trade (n {m['n']})")
    return made


def _actions_for(cls: str, kind: str, diag: Optional[dict]) -> list[str]:
    if cls == "eligible":
        return ["owner decision required: promote to paper incumbent, or keep monitoring (nothing changes automatically)"]
    if cls == "invalid":
        return ["fix the data/reconciliation problem before counting resumes", "no strategy conclusion drawn from this cohort"]
    if cls == "underperforming":
        dom = (diag or {}).get("dominant", "uncertainty")
        return [f"dominant factor: {dom}", "queue at most two challengers from the ranked shortlist that address it",
                "keep the incumbent cohort running for the paired comparison", "'no validated edge found' stands until a challenger passes validation"]
    return ["keep collecting; next boundary per config", "no change to the strategy"]


# ── integrity ────────────────────────────────────────────────────────────────

def integrity_flags(coh: dict, trades: list[dict], excl: dict, c: dict) -> list[str]:
    inv = c["criteria"]["invalid"]
    flags = []
    n = len(trades)
    if coh["evidence_kind"] in ("demo", "live"):
        tot = n + excl.get("unreconciled", 0)
        if tot and excl["unreconciled"] / tot > inv["unreconciled_share"]:
            flags.append(f"{excl['unreconciled']}/{tot} rows unreconciled")
    if n:
        unknown = sum(1 for t in trades if t.get("cost_r") is None and not t.get("net_financial"))
        if unknown / n > inv["unknown_cost_share"]:
            flags.append(f"{unknown}/{n} trades without a known cost")
    if _S is not None and _S._state.get("running") and _S._state.get("last_cycle"):
        age = time.time() - _S._state["last_cycle"]
        if age > inv["scanner_stale_s"]:
            flags.append(f"scanner has not cycled for {int(age // 60)} min")
    return flags


def run_integrity(now: Optional[int] = None) -> dict:
    now = now or int(time.time())
    c = config()
    out = {}
    for coh in list_cohorts(active_only=True):
        trades, excl = resolved_trades(coh)
        flags = integrity_flags(coh, trades, excl, c)
        out[coh["id"]] = {"ok": not flags, "flags": flags, "n": len(trades), "exclusions": excl}
        last = (_state.get("last_integrity") or {}).get(coh["id"])
        if last is None or last.get("flags") != flags:
            with _lock, _db() as con:
                con.execute("INSERT INTO integrity (at, cohort_id, ok, flags) VALUES (?,?,?,?)",
                            (now, coh["id"], 0 if flags else 1, json.dumps(flags)))
            if flags:
                _notify(f"integrity · {coh['label']}: " + "; ".join(flags))
    _state["last_integrity"] = out
    return out


# ── challengers on the scanner's bars ────────────────────────────────────────

def _sync_books() -> None:
    """One ResearchBook per version in paper-testing, restored from its open rows."""
    want = {v["id"]: v for v in list_versions() if v["state"] == "paper-testing" and not v["code_backed"]}
    for vid in list(_books):
        if vid not in want:
            _books.pop(vid)
    for vid, v in want.items():
        if vid in _books:
            continue
        book = lab.ResearchBook(v["rules"], news_week=bool(_S._meta_get("news_week", False)) if _S else False)
        with _lock, _db() as con:
            rows = con.execute("SELECT data FROM research_trades WHERE version_id=?", (vid,)).fetchall()
        for (data,) in rows:
            d = json.loads(data)
            meta = d.pop("_research", {})
            t = core.Trade(**d)
            if t.status == "open":
                book.open[(t.market, t.tf)] = t
                book.meta[t.id] = meta
            elif book.shadows_open(t):            # model exit done, a shadow rule still running (as sentinel.py does)
                book.shadowing[t.id] = t
                book.meta[t.id] = meta
        _books[vid] = book


def _active_cohort(vid: str) -> Optional[dict]:
    return next((c for c in list_cohorts(active_only=True) if c["version_id"] == vid and c["evidence_kind"] == "paper"), None)


def _save_research_trade(vid: str, cohort_id: int, book: lab.ResearchBook, t: core.Trade) -> None:
    d = book.trade_record(t)
    with _lock, _db() as con:
        con.execute("INSERT OR REPLACE INTO research_trades VALUES (?,?,?,?,?,?,?,?,?)",
                    (vid, t.id, cohort_id, t.market, t.tf, t.status, t.opened_at, t.closed_at, json.dumps(d)))


async def on_bars(m: core.Market, tf: str, bars: list[dict], fresh: bool, trend_fn) -> None:
    """Called by the scanner for every slice it reads, with the same bars.
    Each challenger scores its open trade, then judges the new bar once."""
    if not _books:
        return
    key = f"{m.id} {tf}"
    last = bars[-1]
    t4 = None
    for vid, book in list(_books.items()):
        busy = book.open.get((m.id, tf)) or any(t.market == m.id and t.tf == tf for t in book.shadowing.values())
        if [m.id, tf] not in get_version(vid)["slices"] and not busy:
            continue
        coh = _active_cohort(vid)
        if not coh:
            continue
        for t in book.update(m.id, tf, bars):
            _save_research_trade(vid, coh["id"], book, t)
        if book.rules["shadows"]:
            for t in book.update_shadows(m.id, tf, bars):
                _save_research_trade(vid, coh["id"], book, t)
        evaluated = cfg_get(f"eval:{vid}:{key}", 0)
        if last["time"] > evaluated:
            if t4 is None:
                try:
                    t4 = await trend_fn()
                except Exception as e:
                    log.warning("research 4h trend %s: %s", m.id, e)
            read, new = book.consider(m, tf, bars[-core.WINDOW:], allow_open=fresh, trend_4h=t4)
            if read:
                cfg_set(f"eval:{vid}:{key}", last["time"], "system")
            if new:
                _save_research_trade(vid, coh["id"], book, new)
                _notify(f"challenger {get_version(vid)['name']} opened {new.dir} {m.label} {tf}")
        o = book.open.get((m.id, tf))
        if o:
            _save_research_trade(vid, coh["id"], book, o)


def on_cycle() -> None:
    """After every scanner cycle: integrity first (acts at once), then reviews."""
    try:
        run_integrity()
        run_reviews()
        _state["last_cycle"] = time.time()
        _state["cycles"] += 1
    except Exception as e:
        _state["last_error"] = f"{time.strftime('%H:%M:%S', time.gmtime())} {e}"
        log.warning("research cycle: %s", e)
    _run_jobs_if_budget()


# ── experiments (bounded queue) ──────────────────────────────────────────────

def record_experiment(exp_id: str, hypothesis: Optional[str], results: dict, kind: str = "backtest",
                      version_id: Optional[str] = None, verdict: str = "", notes: str = "", spec: Optional[dict] = None) -> None:
    with _lock, _db() as con:
        con.execute("INSERT OR REPLACE INTO experiments VALUES (?,?,?,?,?,?,?,?,?)",
                    (exp_id, hypothesis, version_id, kind, json.dumps(spec or {}), json.dumps(results), verdict, notes, int(time.time())))


def list_experiments(full: bool = False) -> list[dict]:
    with _lock, _db() as con:
        rows = con.execute("SELECT id, hypothesis, version_id, kind, verdict, notes, created_at, results FROM experiments ORDER BY created_at").fetchall()
    out = []
    for r in rows:
        d = {"id": r[0], "hypothesis": r[1], "version_id": r[2], "kind": r[3], "verdict": r[4], "notes": r[5], "created_at": r[6]}
        if full:
            d["results"] = json.loads(r[7])
        out.append(d)
    return out


def queue_job(kind: str, spec: dict, by: str = "owner") -> int:
    with _lock, _db() as con:
        cur = con.execute("INSERT INTO jobs (kind, spec, state, created_at, by) VALUES (?,?,?,?,?)",
                          (kind, json.dumps(spec), "queued", int(time.time()), by))
        return cur.lastrowid


def _run_jobs_if_budget() -> None:
    """At most budget.experiments_per_day jobs per UTC day, one at a time, in a
    worker thread with a time budget. Heavier work runs from the CLI."""
    global _job_thread
    if _job_thread and _job_thread.is_alive():
        return
    b = config()["budget"]
    day0 = int(time.time() // 86400 * 86400)
    with _lock, _db() as con:
        today = con.execute("SELECT COUNT(*) FROM jobs WHERE started_at >= ?", (day0,)).fetchone()[0]
        job = con.execute("SELECT id, kind, spec FROM jobs WHERE state='queued' ORDER BY id LIMIT 1").fetchone()
    if not job or today >= b["experiments_per_day"]:
        return
    _job_thread = threading.Thread(target=_run_job, args=(job[0], job[1], json.loads(job[2]), b["max_minutes"]), daemon=True, name="sentinel-research-job")
    _job_thread.start()


def _run_job(jid: int, kind: str, spec: dict, max_minutes: int) -> None:
    with _lock, _db() as con:
        con.execute("UPDATE jobs SET state='running', started_at=? WHERE id=?", (int(time.time()), jid))
    deadline = time.time() + max_minutes * 60
    try:
        if kind != "experiment":
            raise ValueError(f"unknown job kind {kind}")
        data = lab.load_history(lab.FOCUS, ["15m", "1h", "4h"])
        if not data:
            raise RuntimeError("no history cache on this host; run `python research_lab.py fetch` or import results")
        res = lab.experiment(spec, data, workers=1, log=lambda s: None)
        if time.time() > deadline:
            res["over_budget"] = True
        record_experiment(spec["id"], spec.get("hypothesis"), res, "backtest", spec=spec, notes="server job")
        state, result = "done", {"id": spec["id"], "seconds": res.get("seconds")}
    except Exception as e:
        state, result = "failed", {"error": str(e)}
    with _lock, _db() as con:
        con.execute("UPDATE jobs SET state=?, finished_at=?, result=? WHERE id=?", (state, int(time.time()), json.dumps(result), jid))


# ── wiring ───────────────────────────────────────────────────────────────────

def _notify(text: str) -> None:
    if _S is None:
        return
    try:
        threading.Thread(target=_S._telegram, args=("Sentinel research · " + text,), daemon=True).start()
    except Exception:
        pass


def init() -> None:
    """Startup / restart: schema, defaults, the incumbent's version row and
    cohort, challenger books restored. Safe to call repeatedly."""
    _state["db"] = db_path()
    with _lock, _db():
        pass
    for k, v in DEFAULT_CONFIG.items():
        if k != "incumbent_version" and cfg_get(k) is None:
            cfg_set(k, v)
    slices = [[f["id"], tf] for f in _S._focus() for tf in f["tfs"]] if _S else []
    inc = create_version(f"ARIA {core.eng.ENGINE_VERSION} / {core.SENTINEL_MODEL} (incumbent)", {"model": core.SENTINEL_MODEL},
                         slices, None, "the scanner's pinned model; its paper journal is sentinel.db", "monitoring", code_backed=True)
    cur = cfg_get("incumbent_version")
    curv = get_version(cur) if cur else None
    if cur != inc["id"] and (curv is None or curv["code_backed"]):
        # first start, or a reviewed release changed the pinned model: the code decides who the incumbent is
        cfg_set("incumbent_version", inc["id"], "release")
        now = int(time.time())
        with _lock, _db() as con:
            con.execute("INSERT INTO transitions (version_id, from_state, to_state, at, reason, evidence_ref, by) VALUES (?,?,?,?,?,?,?)",
                        (inc["id"], f"incumbent:{cur}", "incumbent", now, "pinned in code (release)", None, "release"))
            if curv:
                con.execute("UPDATE cohorts SET ended_at=? WHERE version_id=? AND ended_at IS NULL", (now, cur))
                con.execute("UPDATE versions SET state='retired' WHERE id=? AND state!='retired'", (cur,))
    if not _active_cohort(inc["id"]):
        start = int(_S._meta_get("research_incumbent_start", 0)) if _S else 0
        if not start:
            start = INCUMBENT_JOURNAL_START
        with _lock, _db() as con:
            con.execute("INSERT INTO cohorts (version_id, evidence_kind, started_at, ended_at, label, trade_filter, created_at) VALUES (?,?,?,?,?,?,?)",
                        (inc["id"], "paper", start, None, f"{core.SENTINEL_MODEL} paper journal from {time.strftime('%Y-%m-%d', time.gmtime(start))}",
                         json.dumps({"kind": "incumbent"}), int(time.time())))
    register_code_challengers(cfg_get("incumbent_version"))
    _sync_books()
    _state["started_at"] = time.time()


def register_code_challengers(parent_id: Optional[str]) -> list[dict]:
    """Register every CODE_CHALLENGERS entry once, as a child of `parent_id`,
    and move it to paper-testing (which opens its cohort). A version that
    already exists is left exactly as it is, whatever state the owner put it in."""
    out = []
    for ch in CODE_CHALLENGERS:
        vid = version_id(lab.normalize(ch["rules"]), parent_id)
        existing = get_version(vid)
        if existing:
            out.append(existing)
            continue
        v = create_version(ch["name"], ch["rules"], ch["slices"], parent_id, ch.get("notes", ""), "validating",
                           code_backed=False, by="release")
        v = transition(v["id"], "paper-testing", ch["reason"], ch.get("evidence_ref"), by="release")
        _notify(f"challenger registered: {v['name']} · paper cohort open · judged at 100/150 against the incumbent")
        out.append(v)
    return out


def attach(sentinel_module) -> None:
    global _S
    _S = sentinel_module


# ── API ──────────────────────────────────────────────────────────────────────

def _lib() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{LIBRARY_DB}?mode=ro", uri=True)
    return con


@router.get("/status")
def status() -> dict:
    c = config()
    vs = list_versions()
    cohorts = []
    for coh in list_cohorts(active_only=True):
        trades, excl = resolved_trades(coh)
        n = len(trades)
        with _lock, _db() as con:
            done = sorted(r[0] for r in con.execute("SELECT boundary FROM reviews WHERE cohort_id=?", (coh["id"],)))
        nxt = next((b for b, _ in [(c["diagnostic_at"], "d")] + [(c["formal_at"] + i * c["formal_every"], "f") for i in range(200)]
                    if b > n and b not in done), None)
        cohorts.append({**coh, "resolved": n, "exclusions": excl, "reviews_done": done, "next_boundary": nxt,
                        "last_closed": trades[-1]["closed_at"] if trades else None})
    with _lock, _db() as con:
        jobs = con.execute("SELECT id, kind, state, created_at, started_at, finished_at, result FROM jobs ORDER BY id DESC LIMIT 10").fetchall()
        n_exp = con.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    return {"config": c, "state": _state, "versions": [{k: v[k] for k in ("id", "name", "parent_id", "state", "code_backed", "created_at")} for v in vs],
            "cohorts": cohorts, "challenger_books": {vid: len(b.open) for vid, b in _books.items()},
            "experiments": n_exp, "jobs": [dict(zip(("id", "kind", "state", "created_at", "started_at", "finished_at", "result"), j)) for j in jobs],
            "live_execution": "disabled for research versions; Sentinel Live (demo) follows the incumbent only"}


@router.get("/versions")
def versions() -> dict:
    with _lock, _db() as con:
        tr = con.execute("SELECT version_id, from_state, to_state, at, reason, evidence_ref, by FROM transitions ORDER BY id").fetchall()
    return {"versions": list_versions(), "incumbent": cfg_get("incumbent_version"),
            "transitions": [dict(zip(("version_id", "from", "to", "at", "reason", "evidence_ref", "by"), t)) for t in tr]}


@router.get("/reviews")
def reviews(cohort: Optional[int] = None) -> dict:
    with _lock, _db() as con:
        q = "SELECT id, cohort_id, boundary, kind, trade_count, computed_at, metrics, classification, diagnosis, actions, decided_by FROM reviews"
        rows = con.execute(q + (" WHERE cohort_id=?" if cohort else "") + " ORDER BY id", (cohort,) if cohort else ()).fetchall()
    out = []
    for r in rows:
        out.append({"id": r[0], "cohort_id": r[1], "boundary": r[2], "kind": r[3], "trade_count": r[4], "computed_at": r[5],
                    "metrics": json.loads(r[6]), "classification": r[7], "diagnosis": json.loads(r[8]), "actions": json.loads(r[9]),
                    "decided_by": r[10]})
    return {"reviews": out}


@router.get("/cohorts/{cid}")
def cohort_detail(cid: int) -> dict:
    coh = get_cohort(cid)
    if not coh:
        raise HTTPException(404, "unknown cohort")
    trades, excl = resolved_trades(coh)
    m = _review_metrics(trades) if trades else {"n": 0}
    return {"cohort": coh, "resolved": len(trades), "exclusions": excl, "metrics": m,
            "note": "live numbers for inspection; the recorded reviews are the evidence of record"}


@router.get("/hypotheses")
def hypotheses() -> dict:
    with _lib() as con:
        cols = [c[1] for c in con.execute("PRAGMA table_info(hypotheses)")]
        rows = con.execute("SELECT * FROM hypotheses ORDER BY rank").fetchall()
        notes = dict(con.execute("SELECT k, v FROM research_notes").fetchall())
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        for k in ("library_ids", "sources", "rules", "parameter_bounds", "failure_conditions", "ablations"):
            d[k] = json.loads(d[k]) if d.get(k) else None
        out.append(d)
    return {"hypotheses": out, "working_strategy_criteria": json.loads(notes.get("working_strategy_criteria", "null")),
            "placebo_rule": notes.get("placebo_rule")}


@router.get("/library")
def library(id: Optional[str] = None) -> dict:
    with _lib() as con:
        cols = [c[1] for c in con.execute("PRAGMA table_info(library)")]
        rows = con.execute("SELECT * FROM library" + (" WHERE id=?" if id else "") + " ORDER BY id", (id,) if id else ()).fetchall()
        src = con.execute("SELECT library_id, msg_id, posted_at, item_url FROM library_sources ORDER BY library_id, msg_id").fetchall()
    by: dict[str, list] = {}
    for lid, mid, posted, url in src:
        by.setdefault(lid, []).append({"post": mid, "url": f"https://t.me/mql5dev/{mid}", "posted_at": posted, "item": url})
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        d["rules"] = json.loads(d["rules"]) if d.get("rules") else None
        d["missing_rules"] = json.loads(d["missing_rules"]) if d.get("missing_rules") else None
        d["sources"] = by.get(d["id"], [])
        out.append(d)
    return {"library": out}


@router.get("/coverage")
def coverage() -> dict:
    import research_library as rl
    with _lib() as con:
        return rl.coverage(con)


@router.get("/experiments")
def experiments(id: Optional[str] = None) -> dict:
    if id:
        with _lock, _db() as con:
            r = con.execute("SELECT id, hypothesis, version_id, kind, spec, results, verdict, notes, created_at FROM experiments WHERE id=?", (id,)).fetchone()
        if not r:
            raise HTTPException(404, "unknown experiment")
        return {"experiment": {"id": r[0], "hypothesis": r[1], "version_id": r[2], "kind": r[3], "spec": json.loads(r[4]),
                               "results": json.loads(r[5]), "verdict": r[6], "notes": r[7], "created_at": r[8]}}
    return {"experiments": list_experiments()}


def _owner(request: Request) -> None:
    _S._check_key(request)


@router.post("/versions")
async def create_version_api(request: Request) -> dict:
    _owner(request)
    b = await request.json()
    try:
        v = create_version(b.get("name") or "unnamed", b.get("rules") or {}, b.get("slices") or [],
                           b.get("parent_id"), b.get("notes") or "", b.get("state") or "researching", by="owner")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"version": v}


@router.post("/transition")
async def transition_api(request: Request) -> dict:
    _owner(request)
    b = await request.json()
    action = b.get("action") or "transition"
    reason = (b.get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "a reason is required for every transition")
    if action == "promote":
        return promote(b["version_id"], reason, b.get("evidence_ref"))
    if action == "rollback":
        return rollback(reason)
    return {"version": transition(b["version_id"], b["to_state"], reason, b.get("evidence_ref"))}


@router.post("/config")
async def config_api(request: Request) -> dict:
    _owner(request)
    b = await request.json()
    for k in ("diagnostic_at", "formal_at", "formal_every"):
        if k in b:
            if not isinstance(b[k], int) or b[k] < 10:
                raise HTTPException(400, f"{k} must be an integer >= 10")
            cfg_set(k, b[k], "owner")
    if "criteria" in b:
        cur = config()["criteria"]
        for grp, vals in b["criteria"].items():
            cur.setdefault(grp, {}).update(vals)
        cfg_set("criteria", cur, "owner")
    if "budget" in b:
        cur = config()["budget"]
        cur.update(b["budget"])
        cfg_set("budget", cur, "owner")
    return {"config": config()}


@router.post("/jobs")
async def jobs_api(request: Request) -> dict:
    _owner(request)
    b = await request.json()
    spec = b.get("spec")
    if not spec or "id" not in spec or "slices" not in spec:
        raise HTTPException(400, "spec with id and slices required")
    return {"job": queue_job("experiment", spec)}


# ── CLI (inspection without the server) ──────────────────────────────────────

def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Sentinel research registry — inspect or import without the server")
    ap.add_argument("cmd", choices=["status", "import-experiments", "reviews", "versions"])
    ap.add_argument("--db", help="registry path (default: beside sentinel.db, or SENTINEL_RESEARCH_DB)")
    a = ap.parse_args()
    if a.db:
        os.environ["SENTINEL_RESEARCH_DB"] = a.db
    if a.cmd == "import-experiments":
        n = 0
        for f in sorted(os.listdir(lab.EXPERIMENTS_DIR)):
            if f.endswith(".result.json"):
                res = json.load(open(os.path.join(lab.EXPERIMENTS_DIR, f)))
                spec_path = os.path.join(lab.EXPERIMENTS_DIR, f.replace(".result.json", ".json"))
                spec = json.load(open(spec_path)) if os.path.exists(spec_path) else {}
                verdict = (res.get("verdict") or "")
                record_experiment(res["id"], res.get("hypothesis"), res, "backtest", res.get("base_version"), verdict,
                                  res.get("notes", "imported from research/experiments"), spec)
                n += 1
        print(f"imported {n} experiment results into {db_path()}")
    elif a.cmd == "status":
        print(json.dumps(status(), indent=1, default=str))
    elif a.cmd == "reviews":
        print(json.dumps(reviews(), indent=1))
    elif a.cmd == "versions":
        print(json.dumps(versions(), indent=1))


if __name__ == "__main__":
    _cli()
