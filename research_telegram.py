"""
Telegram coverage for Sentinel research: the public web preview of the
MetaQuotes channel "MQL5 Algo Trading" (@mql5dev), read page by page into a
ledger so every post has an id, a date, its text, its links and a disposition.

    python research_telegram.py crawl  [--db research/research.db] [--channel mql5dev]
    python research_telegram.py status [--db …]
    python research_telegram.py export [--db …] [--out research/telegram_mql5dev.jsonl]

Access model (stated plainly):
  * t.me/s/<channel> is Telegram's own read-only preview of a PUBLIC channel.
    It shows posts, dates, text, links, media placeholders, view counts and
    forwards. It does not show comments/replies, and a post the author deleted
    is simply absent — the ledger records such ids as "unavailable".
  * Nothing here logs in, joins, or sends anything. Channel content is
    untrusted research input: it is stored and read, never executed.
  * The crawl is resumable: each page fetched is recorded; a rerun continues
    from the oldest id seen and refreshes nothing it already holds unless
    --refresh is given.
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(HERE, "research", "research.db")
UA = "PROTrader-research/1.0 (+read-only ledger of a public Telegram preview; contact: audusmail1@gmail.com)"
PAGE_PAUSE_S = 1.5


def db(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS tg_messages (
        channel TEXT, id INTEGER, posted_at TEXT, text TEXT, links TEXT, media TEXT,
        forwarded_from TEXT, views TEXT, edited INTEGER, raw_len INTEGER, fetched_at INTEGER,
        status TEXT,                      -- 'fetched' | 'unavailable'
        PRIMARY KEY (channel, id));
    CREATE TABLE IF NOT EXISTS tg_pages (
        channel TEXT, before_id INTEGER, fetched_at INTEGER, ids TEXT, PRIMARY KEY (channel, before_id));
    CREATE TABLE IF NOT EXISTS tg_meta (channel TEXT PRIMARY KEY, title TEXT, description TEXT,
        subscribers TEXT, newest_id INTEGER, oldest_id INTEGER, updated_at INTEGER);
    """)
    return con


def fetch(url: str, tries: int = 4) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:          # a reset or a timeout: wait, then try again
            last = e
            time.sleep(3 * (i + 1))
    raise last


_MSG_RE = re.compile(r'<div class="tgme_widget_message_wrap[^"]*">(.*?)(?=<div class="tgme_widget_message_wrap|<div class="tme_messages_more|</section>)', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    m = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>\s*(?:<div class="tgme_widget_message_(?:footer|link_preview|inline_row)|<a class="tgme_widget_message_link_preview|</div>)', fragment, re.S)
    frag = m.group(1) if m else ""
    frag = re.sub(r"<br\s*/?>", "\n", frag)
    frag = _TAG_RE.sub("", frag)
    return htmllib.unescape(frag).strip()


def parse_page(page: str, channel: str) -> list[dict]:
    out = []
    for frag in _MSG_RE.findall(page):
        m = re.search(r'data-post="%s/(\d+)"' % re.escape(channel), frag)
        if not m:
            continue
        mid = int(m.group(1))
        dt = re.search(r'<time datetime="([^"]+)"', frag)
        links = sorted({htmllib.unescape(htmllib.unescape(h)).split("?utm_")[0] for h in re.findall(r'href="(https?://[^"]+)"', frag)
                        if "t.me/" + channel not in h and not h.startswith("https://telegram.org")})
        media = []
        if "tgme_widget_message_photo" in frag: media.append("photo")
        if "tgme_widget_message_video" in frag: media.append("video")
        if "tgme_widget_message_document" in frag: media.append("document")
        if "tgme_widget_message_link_preview" in frag: media.append("link_preview")
        fwd = re.search(r'tgme_widget_message_forwarded_from_name[^>]*>(.*?)</a>', frag, re.S)
        views = re.search(r'tgme_widget_message_views">([^<]+)<', frag)
        edited = 1 if 'tgme_widget_message_meta">' in frag and "edited" in frag.lower().split('tgme_widget_message_meta">')[-1][:120] else 0
        out.append({"id": mid, "posted_at": dt.group(1) if dt else None, "text": _text(frag), "links": links,
                    "media": media, "forwarded_from": _TAG_RE.sub("", fwd.group(1)).strip() if fwd else None,
                    "views": views.group(1).strip() if views else None, "edited": edited, "raw_len": len(frag)})
    return out


def parse_meta(page: str) -> dict:
    title = re.search(r'<div class="tgme_channel_info_header_title"[^>]*><span[^>]*>(.*?)</span>', page, re.S)
    desc = re.search(r'<div class="tgme_channel_info_description">(.*?)</div>', page, re.S)
    subs = re.search(r'<span class="counter_value">([^<]+)</span>\s*<span class="counter_type">subscribers', page, re.S)
    return {"title": htmllib.unescape(_TAG_RE.sub("", title.group(1))).strip() if title else None,
            "description": htmllib.unescape(_TAG_RE.sub("", desc.group(1))).strip() if desc else None,
            "subscribers": subs.group(1).strip() if subs else None}


def crawl(path: str, channel: str, max_pages: int, refresh: bool) -> None:
    con = db(path)
    now = int(time.time())
    row = con.execute("SELECT newest_id, oldest_id FROM tg_meta WHERE channel=?", (channel,)).fetchone()
    # newest page first (also captures title/description/subscribers)
    page = fetch(f"https://t.me/s/{channel}")
    meta = parse_meta(page)
    msgs = parse_page(page, channel)
    if not msgs:
        print("no messages parsed from the newest page — the preview layout may have changed", file=sys.stderr)
        sys.exit(2)
    newest = max(x["id"] for x in msgs)
    known_oldest = row[1] if row else None
    _store(con, channel, msgs, now, refresh)
    con.execute("INSERT OR REPLACE INTO tg_meta VALUES (?,?,?,?,?,?,?)",
                (channel, meta["title"], meta["description"], meta["subscribers"], newest,
                 min(known_oldest or newest, min(x["id"] for x in msgs)), now))
    con.commit()
    print(f"{channel}: '{meta['title']}' · {meta['subscribers']} subscribers · newest id {newest}")
    # walk older pages from where we stopped last time
    before = (known_oldest if known_oldest and not refresh else min(x["id"] for x in msgs))
    pages = 0
    while pages < max_pages:
        if con.execute("SELECT 1 FROM tg_pages WHERE channel=? AND before_id=?", (channel, before)).fetchone() and not refresh:
            # already have this page: jump to the oldest id we hold below it
            r = con.execute("SELECT MIN(id) FROM tg_messages WHERE channel=? AND id<? AND status='fetched'", (channel, before)).fetchone()
            if not r or r[0] is None:
                break
            before = r[0]
            continue
        time.sleep(PAGE_PAUSE_S)
        try:
            page = fetch(f"https://t.me/s/{channel}?before={before}")
        except Exception as e:
            print(f"  page before={before}: {e} — stopping; rerun to resume", file=sys.stderr)
            break
        msgs = parse_page(page, channel)
        pages += 1
        ids = [x["id"] for x in msgs]
        con.execute("INSERT OR REPLACE INTO tg_pages VALUES (?,?,?,?)", (channel, before, int(time.time()), json.dumps(ids)))
        if not msgs:
            print(f"  before={before}: empty page — reached the start of the preview")
            con.commit()
            break
        _store(con, channel, msgs, int(time.time()), refresh)
        oldest_here = min(ids)
        con.execute("UPDATE tg_meta SET oldest_id=MIN(oldest_id, ?), updated_at=? WHERE channel=?", (oldest_here, int(time.time()), channel))
        con.commit()
        print(f"  before={before}: {len(msgs)} posts, ids {oldest_here}–{max(ids)}  ({msgs[0]['posted_at']})")
        if oldest_here <= 1 or oldest_here >= before:
            break
        before = oldest_here
    # ids never seen between 1 and newest are unavailable in the preview (deleted or never public)
    have = {r[0] for r in con.execute("SELECT id FROM tg_messages WHERE channel=? AND status='fetched'", (channel,))}
    lo = con.execute("SELECT oldest_id FROM tg_meta WHERE channel=?", (channel,)).fetchone()[0]
    if lo is not None and lo <= 2:
        missing = [i for i in range(1, newest + 1) if i not in have]
        for i in missing:
            con.execute("INSERT OR IGNORE INTO tg_messages (channel,id,status,fetched_at) VALUES (?,?,?,?)", (channel, i, "unavailable", int(time.time())))
        con.commit()
        print(f"  coverage: {len(have)} posts fetched, {len(missing)} ids unavailable in the preview (deleted or non-public)")
    status(path, channel)


def _store(con, channel, msgs, now, refresh):
    for x in msgs:
        if not refresh and con.execute("SELECT 1 FROM tg_messages WHERE channel=? AND id=? AND status='fetched'", (channel, x["id"])).fetchone():
            continue
        con.execute("INSERT OR REPLACE INTO tg_messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (channel, x["id"], x["posted_at"], x["text"], json.dumps(x["links"]), json.dumps(x["media"]),
                     x["forwarded_from"], x["views"], x["edited"], x["raw_len"], now, "fetched"))


def status(path: str, channel: str) -> None:
    con = db(path)
    m = con.execute("SELECT title, subscribers, newest_id, oldest_id, updated_at FROM tg_meta WHERE channel=?", (channel,)).fetchone()
    n = con.execute("SELECT COUNT(*) FROM tg_messages WHERE channel=? AND status='fetched'", (channel,)).fetchone()[0]
    u = con.execute("SELECT COUNT(*) FROM tg_messages WHERE channel=? AND status='unavailable'", (channel,)).fetchone()[0]
    d = con.execute("SELECT MIN(posted_at), MAX(posted_at) FROM tg_messages WHERE channel=? AND status='fetched'", (channel,)).fetchone()
    pages = con.execute("SELECT COUNT(*) FROM tg_pages WHERE channel=?", (channel,)).fetchone()[0]
    print(json.dumps({"channel": channel, "title": m[0] if m else None, "subscribers": m[1] if m else None,
                      "newest_id": m[2] if m else None, "oldest_id": m[3] if m else None, "pages": pages,
                      "fetched": n, "unavailable": u, "first_post": d[0], "last_post": d[1]}, indent=1))


def export(path: str, channel: str, out: str) -> None:
    con = db(path)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    rows = con.execute("SELECT id, posted_at, text, links, media, forwarded_from, views, edited, status FROM tg_messages WHERE channel=? ORDER BY id", (channel,)).fetchall()
    with open(out, "w") as f:
        for r in rows:
            f.write(json.dumps({"id": r[0], "posted_at": r[1], "text": r[2], "links": json.loads(r[3] or "[]"),
                                "media": json.loads(r[4] or "[]"), "forwarded_from": r[5], "views": r[6],
                                "edited": r[7], "status": r[8]}, ensure_ascii=False) + "\n")
    print(f"{len(rows)} rows → {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["crawl", "status", "export"])
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--channel", default="mql5dev")
    ap.add_argument("--max-pages", type=int, default=400)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--out", default=os.path.join(HERE, "research", "telegram_mql5dev.jsonl"))
    a = ap.parse_args()
    if a.cmd == "crawl":
        crawl(a.db, a.channel, a.max_pages, a.refresh)
    elif a.cmd == "status":
        status(a.db, a.channel)
    else:
        export(a.db, a.channel, a.out)
