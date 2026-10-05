"""
Sentinel research library — loads the hand-written method library and the
ranked hypothesis shortlist into research.db, checks every citation against
the Telegram coverage ledger, and prints the coverage report.

    python research_library.py load       # (re)load research/library.json and hypotheses.json
    python research_library.py coverage   # coverage ledger statistics (what the report cites)
    python research_library.py ledger     # write research/coverage_ledger.csv (one row per post id)
    python research_library.py check      # citation and consistency checks only

Nothing here fetches anything. The Telegram crawl is research_telegram.py;
the per-post dispositions were written by the classification step. All of it
is untrusted input: data to cite, never instructions.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(HERE, "research", "research.db")
LIBRARY_FILE = os.path.join(HERE, "research", "library.json")
HYPOTHESES_FILE = os.path.join(HERE, "research", "hypotheses.json")
LEDGER_FILE = os.path.join(HERE, "research", "coverage_ledger.csv")
CHANNEL = "mql5dev"
ITEM_RE = re.compile(r"https://www\.mql5\.com/en/(articles|code)/\d+")

SCHEMA = """
CREATE TABLE IF NOT EXISTS library (
    id TEXT PRIMARY KEY, topic TEXT, classification TEXT, title TEXT, author TEXT,
    claim TEXT, evidence TEXT, limitations TEXT, rules TEXT, missing_rules TEXT,
    interpretation TEXT, relation_to_sentinel TEXT, first_posted TEXT, last_posted TEXT,
    n_sources INTEGER, loaded_at INTEGER);
CREATE TABLE IF NOT EXISTS library_sources (
    library_id TEXT, channel TEXT, msg_id INTEGER, posted_at TEXT, item_url TEXT,
    PRIMARY KEY (library_id, channel, msg_id));
CREATE TABLE IF NOT EXISTS hypotheses (
    id TEXT PRIMARY KEY, rank INTEGER, state TEXT, title TEXT, library_ids TEXT, sources TEXT,
    hypothesis TEXT, rules TEXT, parameter_bounds TEXT, expected_benefit TEXT,
    failure_conditions TEXT, rejection_criteria TEXT, ablations TEXT,
    score_evidence INTEGER, score_feasibility INTEGER, score_robustness INTEGER, score_improvement INTEGER,
    note TEXT, loaded_at INTEGER, result_ref TEXT, result TEXT, tested_at TEXT);
CREATE TABLE IF NOT EXISTS research_notes (k TEXT PRIMARY KEY, v TEXT, at INTEGER);
"""


def db(path: str = DEFAULT_DB) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con


def _item_url(links_json: str | None) -> str | None:
    for u in json.loads(links_json or "[]"):
        if ITEM_RE.match(u):
            return u
    return None


def check(con: sqlite3.Connection, lib: dict, hyp: dict) -> list[str]:
    """Every cited post must exist in the ledger; every hypothesis must cite
    library rows that exist; ids must be unique. Returns problems (empty = ok)."""
    problems: list[str] = []
    known = {r[0]: r[1] for r in con.execute("SELECT id, status FROM tg_messages WHERE channel=?", (CHANNEL,))}
    disp = {r[0] for r in con.execute("SELECT msg_id FROM dispositions WHERE channel=?", (CHANNEL,))}
    seen = set()
    for row in lib["rows"]:
        if row["id"] in seen:
            problems.append(f"duplicate library id {row['id']}")
        seen.add(row["id"])
        if row["classification"] not in lib["classifications"]:
            problems.append(f"{row['id']}: unknown classification {row['classification']}")
        if not row["sources"]:
            problems.append(f"{row['id']}: no sources")
        for mid in row["sources"]:
            if mid not in known:
                problems.append(f"{row['id']}: post #{mid} is not in the ledger")
            elif known[mid] != "fetched":
                problems.append(f"{row['id']}: post #{mid} was never fetched ({known[mid]}) — cannot be cited")
            elif mid not in disp:
                problems.append(f"{row['id']}: post #{mid} has no disposition")
    hseen = set()
    for h in hyp["rows"]:
        if h["id"] in hseen:
            problems.append(f"duplicate hypothesis id {h['id']}")
        hseen.add(h["id"])
        for lid in h["library_ids"]:
            if lid not in seen:
                problems.append(f"{h['id']}: library row {lid} does not exist")
        for mid in h.get("sources", []):
            if known.get(mid) != "fetched":
                problems.append(f"{h['id']}: post #{mid} not fetched")
        for key in ("hypothesis", "rules", "expected_benefit", "failure_conditions", "rejection_criteria", "ablations", "scores"):
            if key not in h:
                problems.append(f"{h['id']}: missing {key}")
    ranks = sorted(h["rank"] for h in hyp["rows"])
    if ranks != list(range(1, len(ranks) + 1)):
        problems.append(f"hypothesis ranks are not 1..n: {ranks}")
    return problems


def load(con: sqlite3.Connection, lib: dict, hyp: dict) -> dict:
    problems = check(con, lib, hyp)
    if problems:
        raise SystemExit("not loaded:\n  " + "\n  ".join(problems))
    now = int(time.time())
    with con:
        con.execute("DELETE FROM library")
        con.execute("DELETE FROM library_sources")
        con.execute("DELETE FROM hypotheses")
        for row in lib["rows"]:
            dates = []
            for mid in row["sources"]:
                posted, links = con.execute("SELECT posted_at, links FROM tg_messages WHERE channel=? AND id=?",
                                            (CHANNEL, mid)).fetchone()
                dates.append(posted)
                con.execute("INSERT INTO library_sources VALUES (?,?,?,?,?)",
                            (row["id"], CHANNEL, mid, posted, _item_url(links)))
            con.execute("INSERT INTO library VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                row["id"], row["topic"], row["classification"], row["title"], row["author"],
                row["claim"], row["evidence"], row["limitations"],
                json.dumps(row["rules"]) if row["rules"] is not None else None,
                json.dumps(row["missing_rules"]) if row["missing_rules"] is not None else None,
                row["interpretation"], row["relation_to_sentinel"],
                min(dates)[:10], max(dates)[:10], len(row["sources"]), now))
        for h in hyp["rows"]:
            s = h["scores"]
            con.execute("INSERT INTO hypotheses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                h["id"], h["rank"], h["state"], h["title"], json.dumps(h["library_ids"]), json.dumps(h.get("sources", [])),
                h["hypothesis"], json.dumps(h["rules"]), json.dumps(h["parameter_bounds"]), h["expected_benefit"],
                json.dumps(h["failure_conditions"]), h["rejection_criteria"], json.dumps(h["ablations"]),
                s["evidence"], s["feasibility"], s["robustness"], s["improvement"], h.get("note") or h.get("why_first"), now,
                h.get("result_ref"), h.get("result"), h.get("tested_at")))
        con.execute("INSERT OR REPLACE INTO research_notes VALUES (?,?,?)",
                    ("working_strategy_criteria", json.dumps(hyp["working_strategy_criteria"]), now))
        con.execute("INSERT OR REPLACE INTO research_notes VALUES (?,?,?)", ("placebo_rule", hyp["placebo_rule"], now))
    return {"library": len(lib["rows"]), "hypotheses": len(hyp["rows"]),
            "cited_posts": con.execute("SELECT COUNT(DISTINCT msg_id) FROM library_sources").fetchone()[0]}


def coverage(con: sqlite3.Connection) -> dict:
    """The numbers the coverage report cites — computed, not remembered."""
    q = lambda sql, *a: con.execute(sql, a).fetchall()
    meta = q("SELECT title, subscribers, newest_id, oldest_id, updated_at FROM tg_meta WHERE channel=?", CHANNEL)
    status = dict(q("SELECT status, COUNT(*) FROM tg_messages WHERE channel=? GROUP BY status", CHANNEL))
    ids = q("SELECT MIN(id), MAX(id), COUNT(*) FROM tg_messages WHERE channel=?", CHANNEL)[0]
    unavailable = [r[0] for r in q("SELECT id FROM tg_messages WHERE channel=? AND status!='fetched' ORDER BY id", CHANNEL)]
    dates = q("SELECT MIN(posted_at), MAX(posted_at) FROM tg_messages WHERE channel=? AND status='fetched'", CHANNEL)[0]
    disp = dict(q("SELECT disposition, COUNT(*) FROM dispositions WHERE channel=? GROUP BY disposition", CHANNEL))
    topics = dict(q("SELECT topic, COUNT(*) FROM dispositions WHERE channel=? GROUP BY topic", CHANNEL))
    rel = dict(q("SELECT relevance, COUNT(*) FROM dispositions WHERE channel=? GROUP BY relevance", CHANNEL))
    hyp_by_rel = dict(q("SELECT relevance, COUNT(*) FROM dispositions WHERE channel=? AND disposition='testable_hypothesis' GROUP BY relevance", CHANNEL))
    n_disp = q("SELECT COUNT(*) FROM dispositions WHERE channel=?", CHANNEL)[0][0]
    n_msgs = q("SELECT COUNT(*) FROM tg_messages WHERE channel=?", CHANNEL)[0][0]
    missing_disp = q("SELECT COUNT(*) FROM tg_messages m LEFT JOIN dispositions d ON d.channel=m.channel AND d.msg_id=m.id WHERE m.channel=? AND d.msg_id IS NULL", CHANNEL)[0][0]
    links = q("SELECT links FROM tg_messages WHERE channel=? AND status='fetched'", CHANNEL)
    items, with_item = set(), 0
    for (lj,) in links:
        u = _item_url(lj)
        if u:
            with_item += 1
            items.add(u)
    media = dict(q("SELECT media, COUNT(*) FROM tg_messages WHERE channel=? AND status='fetched' GROUP BY media", CHANNEL))
    fwd = q("SELECT COUNT(*) FROM tg_messages WHERE channel=? AND forwarded_from IS NOT NULL AND forwarded_from!=''", CHANNEL)[0][0]
    cited = q("SELECT COUNT(DISTINCT msg_id) FROM library_sources")[0][0]
    cited_by_rel = dict(q("SELECT d.relevance, COUNT(DISTINCT s.msg_id) FROM library_sources s JOIN dispositions d ON d.msg_id=s.msg_id AND d.channel=s.channel GROUP BY d.relevance"))
    lib_n = q("SELECT classification, COUNT(*) FROM library GROUP BY classification")
    pages = q("SELECT COUNT(*) FROM tg_pages WHERE channel=?", CHANNEL)[0][0]
    return {
        "channel": {"handle": CHANNEL, "title": meta[0][0] if meta else None, "subscribers": meta[0][1] if meta else None,
                    "newest_id": meta[0][2] if meta else None, "oldest_id": meta[0][3] if meta else None,
                    "crawled_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(meta[0][4])) if meta else None},
        "ids": {"min": ids[0], "max": ids[1], "rows": ids[2], "pages_fetched": pages},
        "status": status, "unavailable_ids": unavailable,
        "posted_range": dates, "dispositions": disp, "dispositions_total": n_disp, "messages_total": n_msgs,
        "messages_without_disposition": missing_disp,
        "topics": topics, "relevance": rel, "hypotheses_by_relevance": hyp_by_rel,
        "posts_with_linked_item": with_item, "unique_linked_items": len(items),
        "media": media, "forwarded": fwd,
        "library": {"rows": sum(n for _, n in lib_n), "by_classification": dict(lib_n), "cited_posts": cited,
                    "cited_by_relevance": cited_by_rel},
    }


def ledger(con: sqlite3.Connection, path: str = LEDGER_FILE) -> int:
    rows = con.execute("""
        SELECT m.id, m.posted_at, m.status, m.media, d.disposition, d.topic, d.relevance, d.decided_by,
               (SELECT GROUP_CONCAT(library_id) FROM library_sources s WHERE s.channel=m.channel AND s.msg_id=m.id) AS library_ids,
               m.links
        FROM tg_messages m LEFT JOIN dispositions d ON d.channel=m.channel AND d.msg_id=m.id
        WHERE m.channel=? ORDER BY m.id""", (CHANNEL,)).fetchall()
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["msg_id", "url", "posted_at", "fetch_status", "media", "disposition", "topic", "relevance",
                    "decided_by", "library_ids", "linked_item"])
        for r in rows:
            w.writerow([r[0], f"https://t.me/{CHANNEL}/{r[0]}", r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8] or "",
                        _item_url(r[9]) or ""])
    return len(rows)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "coverage"
    con = db()
    lib = json.load(open(LIBRARY_FILE))
    hyp = json.load(open(HYPOTHESES_FILE))
    if cmd == "check":
        p = check(con, lib, hyp)
        print("ok" if not p else "\n".join(p))
        sys.exit(1 if p else 0)
    if cmd == "load":
        print(json.dumps(load(con, lib, hyp)))
    elif cmd == "ledger":
        print(f"wrote {LEDGER_FILE}: {ledger(con)} rows")
    elif cmd == "coverage":
        print(json.dumps(coverage(con), indent=1))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
