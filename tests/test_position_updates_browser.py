"""
Position updates must never execute on stale trade state, tested in a real
browser against protrader_mobile.html.   python3 tests/test_position_updates_browser.py

Covers the flow "place a trade → move the stop and target on the chart →
the position closes": the dragged level is the one that counts, for the
app's own trigger loop, for the server-side watcher's closes, and for the
journal entry that records it. Quotes are pinned (otQuote is replaced).
"""
import functools
import http.server
import os
import socketserver
import threading

from playwright.sync_api import sync_playwright

ROOT = os.path.join(os.path.dirname(__file__), "..")
PROXY = os.environ.get("HTTPS_PROXY", "")


def serve():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=ROOT)
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


SETUP = """
(() => {
  S.balance = 36900; S.riskPct = 1; S.trades = []; S.posStats = null;
  TR.positions = []; TR.orders = []; TR.seq = 1;
  window.__px = 44000;
  otQuote = id => ({ ok: true, stale: false, bid: window.__px, ask: window.__px, last: window.__px, hasSpread: false, spread: null, src: 'test', age: 0, exec: false });
  LIVE.routing = () => false;
  Broker.latencyMs = 5;
  localStorage.removeItem('protrader.autoprotect.v1'); AUTOP.cfg = null; AUTOP.pick('off');
  // the server watcher's answers are scripted per test; its calls are recorded
  window.__api = []; NOTIFY.cfg = { push: true }; NOTIFY.status = { push: true };
  NOTIFY.api = async (path, body) => { window.__api.push({ path, body }); return window.__reply ? window.__reply(path, body) : {}; };
  if (LEVELS.draft) LEVELS.discard(true);
  selectPair('R_75');
  const tf = TF_SEC[S.tf] || 900, t0 = Math.floor(Date.now() / 1000 / tf) * tf - 239 * tf;
  S.candles = Array.from({ length: 240 }, (_, i) => { const o = 44000 + Math.sin(i / 9) * 120, c = 44000 + Math.sin((i + 1) / 9) * 120;
    return { time: t0 + i * tf, open: o, high: Math.max(o, c) + 40, low: Math.min(o, c) - 40, close: c, vol: 0 }; });
  S.wsConnected = true; drawChart();
  return otSpec('R_75');
})()
"""

OPEN = """
(() => {
  OT.openPosition({ symbol: 'R_75', side: '%s', volume: 0.2, stopLoss: %s, takeProfit: %s, accountId: TR.acct.id }, 44000);
  const p = TR.positions[TR.positions.length - 1]; LEVELS.render(); return p.id;
})()
"""


def run(page, js):
    return page.evaluate(js)


def open_pos(page, side="buy", sl="43900", tp="44100"):
    return run(page, OPEN % (side, sl, tp))


def check_server_close_matches_current_levels(page):
    """A close the server watcher made on a target the trader has since moved
    is not a fill: the app keeps the position and judges it on its own levels."""
    run(page, SETUP)
    pid = open_pos(page)
    r = run(page, f"""(async () => {{
        const p = TR.positions.find(x => x.id === {pid});
        // the trader drags the target from 44100 to 44140
        const g = LEVELS.groups().find(x => x.key === 'paper:{pid}');
        LEVELS.begin(g, true); LEVELS.draft.tp = {{ intent: 'set', price: 44140 }};
        await LEVELS.confirm();
        const out = {{ tpAfterDrag: p.tp, draftOpen: !!LEVELS.draft }};
        // meanwhile the watcher, still holding 44100, saw a tick at 44105 and "closed" the trade there
        __px = 44105;
        await NOTIFY.reconcile([{{ id: String({pid}), reason: 'tp', price: 44105, tp: 44100, sl: 43900 }}]);
        out.stillOpen = TR.positions.some(x => x.id === {pid});
        out.trades = S.trades.length;
        out.acked = __api.filter(a => a.path === '/paper/ack').length;
        out.balance = S.balance;
        // a close the watcher made on the levels the trader actually has is adopted (the app was away)
        __px = 44140;
        await NOTIFY.reconcile([{{ id: String({pid}), reason: 'tp', price: 44140.5, tp: 44140, sl: 43900 }}]);
        out.closedNow = !TR.positions.some(x => x.id === {pid});
        const t = S.trades[S.trades.length - 1];
        out.exit = t && t.exit; out.level = t && t.level; out.reason = t && t.reason;
        return out; }})()""")
    assert r["tpAfterDrag"] == 44140 and r["draftOpen"] is False, r
    assert r["stillOpen"] is True and r["trades"] == 0 and r["balance"] == 36900, r
    assert r["acked"] >= 1, r                                    # the stale close is acknowledged, not re-sent forever
    assert r["closedNow"] is True and r["exit"] == 44140.5 and r["level"] == 44140 and r["reason"] == "Take profit", r


def check_server_close_without_levels(page):
    """An older watcher record carries no levels: it is adopted only when its
    price is at or through the level the trader has now."""
    run(page, SETUP)
    pid = open_pos(page, "sell", "44100", "43900")
    r = run(page, f"""(async () => {{
        const p = TR.positions.find(x => x.id === {pid});
        p.tp = 43850; OT.save();
        await NOTIFY.reconcile([{{ id: String({pid}), reason: 'tp', price: 43900 }}]);     // old target: not a fill
        const out = {{ open1: TR.positions.some(x => x.id === {pid}) }};
        await NOTIFY.reconcile([{{ id: String({pid}), reason: 'tp', price: 43849 }}]);     // through the current one
        out.open2 = TR.positions.some(x => x.id === {pid});
        out.exit = S.trades.length ? S.trades[S.trades.length - 1].exit : null;
        return out; }})()""")
    assert r["open1"] is True and r["open2"] is False and r["exit"] == 43849, r


def check_drag_keeps_the_other_level_current(page):
    """Confirming a target drag writes only the target. A stop that trailed or
    was auto-protected while the pill was held is not reset to the older level."""
    run(page, SETUP)
    pid = open_pos(page, "buy", "43900", "44100")
    r = run(page, f"""(async () => {{
        const p = TR.positions.find(x => x.id === {pid});
        p.trail = 50; OT.save();                                     // trailing 50 behind price
        const g = LEVELS.groups().find(x => x.key === 'paper:{pid}');
        LEVELS.begin(g, true);                                       // the pill is picked up: snapshot sl 43900
        __px = 44060; OT.checkProtection();                          // price rises: the stop trails to 44010
        const out = {{ trailed: p.sl }};
        LEVELS.draft.tp = {{ intent: 'set', price: 44150 }};
        await LEVELS.confirm();
        out.slAfter = p.sl; out.tpAfter = p.tp; out.trail = p.trail;
        return out; }})()""")
    assert r["trailed"] == 44010, r
    assert r["tpAfter"] == 44150, r
    assert r["slAfter"] == 44010, r                              # not 43900
    assert r["trail"] == 50, r                                   # a target drag does not stop the trail


def check_pointer_drag(page):
    """The real gesture: pick the target pill up, drop it on another price, and
    that is the price the position carries, the store holds and the watcher gets."""
    run(page, SETUP)
    pid = open_pos(page, "buy", "43900", "44100")
    page.wait_for_timeout(300)
    box = run(page, f"""(() => {{ LEVELS.render(); const e = LEVELS.els.get('paper:{pid}:tp'); const r = e.getBoundingClientRect();
        const lay = LEVELS.layer.getBoundingClientRect();
        return {{ x: r.left + 8, y: r.top + r.height / 2, layTop: lay.top, y0: CH.toY(44100), y1: CH.toY(44130) }}; }})()""")
    assert box["y0"] is not None and box["y1"] is not None, box
    run(page, "__api = []")
    page.mouse.move(box["x"], box["y"])
    page.mouse.down()
    page.mouse.move(box["x"], box["y"] + (box["y1"] - box["y0"]) / 2, steps=4)
    page.mouse.move(box["x"], box["y"] + (box["y1"] - box["y0"]), steps=4)
    page.mouse.up()
    page.wait_for_timeout(700)
    r = run(page, f"""(() => {{ const p = TR.positions.find(x => x.id === {pid});
        const st = JSON.parse(localStorage.getItem(TRADE_STORE_KEY)); const sp = st.positions.find(x => x.id === {pid});
        const sync = __api.filter(a => a.path === '/paper/sync').pop();
        const sent = sync && sync.body.positions.find(x => x.id === String({pid}));
        return {{ tp: p.tp, sl: p.sl, stored: sp && sp.tp, synced: sent && sent.tp, draft: !!LEVELS.draft }}; }})()""")
    assert abs(r["tp"] - 44130) <= 0.6, r                         # within a few pixels' worth of ticks
    assert r["sl"] == 43900 and r["stored"] == r["tp"] and r["synced"] == r["tp"] and r["draft"] is False, r


def check_breakeven_is_saved(page):
    """Breakeven moves the stop on the position, in the store and on the watcher."""
    run(page, SETUP)
    pid = open_pos(page, "buy", "43900", "44100")
    r = run(page, f"""(async () => {{
        __api = []; __px = 44050;
        await OT.breakeven({pid});
        const st = JSON.parse(localStorage.getItem(TRADE_STORE_KEY)); const sp = st.positions.find(x => x.id === {pid});
        await new Promise(r => setTimeout(r, 600));
        const sync = __api.filter(a => a.path === '/paper/sync').pop();
        const sent = sync && sync.body.positions.find(x => x.id === String({pid}));
        return {{ sl: TR.positions.find(x => x.id === {pid}).sl, stored: sp && sp.sl, synced: sent && sent.sl }}; }})()""")
    assert r["sl"] == 44000 and r["stored"] == 44000 and r["synced"] == 44000, r


def check_trigger_records_the_level_it_fired_on(page):
    """The journal names the level that closed the trade, not whatever the
    position holds by the time the fill lands."""
    run(page, SETUP)
    pid = open_pos(page, "buy", "43900", "44100")
    r = run(page, f"""(async () => {{
        __px = 44100; OT.checkProtection();                          // target touched: the close is in flight
        const p = TR.positions.find(x => x.id === {pid});
        const out = {{ closing: !!(p && p._closing) }};
        await new Promise(r => setTimeout(r, 60));
        const t = S.trades[S.trades.length - 1];
        out.reason = t && t.reason; out.exit = t && t.exit; out.level = t && t.level; out.open = TR.positions.some(x => x.id === {pid});
        return out; }})()""")
    assert r["open"] is False and r["reason"] == "Take profit" and r["exit"] == 44100 and r["level"] == 44100, r


def check_no_modify_while_closing(page):
    """A level change on a position that is mid-close is refused, not applied
    to a trade that is about to be gone."""
    run(page, SETUP)
    pid = open_pos(page, "buy", "43900", "44100")
    r = run(page, f"""(async () => {{
        Broker.latencyMs = 150;
        const p = TR.positions.find(x => x.id === {pid});
        const g = LEVELS.groups().find(x => x.key === 'paper:{pid}');
        __px = 44050; const closing = OT.closePosition({pid}, null, 'Manual');   // a manual close waits for the broker's fill
        const out = {{ inFlight: !!p._closing }};
        LEVELS.begin(g, true); LEVELS.draft.tp = {{ intent: 'set', price: 44200 }};
        await LEVELS.confirm();
        out.err = document.getElementById('lvlErr').textContent; out.draft = !!LEVELS.draft;
        await closing;
        const t = S.trades[S.trades.length - 1];
        out.open = TR.positions.some(x => x.id === {pid}); out.reason = t && t.reason; out.exit = t && t.exit; out.tp = p.tp;
        if (LEVELS.draft) LEVELS.discard(true);
        Broker.latencyMs = 5;
        return out; }})()""")
    assert r["inFlight"] is True and r["open"] is False and r["reason"] == "Manual" and r["exit"] == 44050, r
    assert r["tp"] == 44100 and r["draft"] is True and "clos" in r["err"].lower(), r


def main():
    httpd = serve()
    port = httpd.server_address[1]
    args = ["--ignore-certificate-errors"]
    if PROXY:
        args += [f"--proxy-server={PROXY}", "--proxy-bypass-list=127.0.0.1;localhost;<local>"]
    with sync_playwright() as p:
        b = p.chromium.launch(args=args)
        page = b.new_context(locale="en-US", timezone_id="UTC", ignore_https_errors=True).new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(f"http://127.0.0.1:{port}/protrader_mobile.html", wait_until="domcontentloaded")
        page.wait_for_function("typeof OT !== 'undefined' && typeof LEVELS !== 'undefined' && typeof NOTIFY !== 'undefined' && CH.ready")
        page.wait_for_timeout(1500)
        checks = [
            ("server close must match the current levels", check_server_close_matches_current_levels),
            ("server close without levels", check_server_close_without_levels),
            ("drag keeps the other level current", check_drag_keeps_the_other_level_current),
            ("pointer drag lands on the dropped price", check_pointer_drag),
            ("breakeven is saved and synced", check_breakeven_is_saved),
            ("trigger records the level it fired on", check_trigger_records_the_level_it_fired_on),
            ("no modify while closing", check_no_modify_while_closing),
        ]
        failed = []
        for name, fn in checks:
            try:
                fn(page)
                print(f"ok  {name}")
            except AssertionError as e:
                failed.append(name)
                print(f"FAIL {name}: {e}")
        assert not errs, errs
        b.close()
    httpd.shutdown()
    if failed:
        raise SystemExit(f"{len(failed)} check(s) failed: {failed}")
    print("all position-update browser checks passed")


if __name__ == "__main__":
    main()
