"""
Paper-account rules, chart tags and auto-protect, tested in a real browser
against protrader_mobile.html.   python3 tests/test_paper_rules_browser.py

Quotes are pinned (otQuote is replaced) so every check is deterministic.
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
  S.balance = 36900; S.riskPct = 1; S.trades = [];
  TR.positions = []; TR.orders = [];
  window.__px = 44000;
  otQuote = id => ({ ok: true, stale: false, bid: window.__px, ask: window.__px, mid: window.__px });
  LIVE.routing = () => false;
  localStorage.removeItem('protrader.autoprotect.v1'); AUTOP.cfg = null;
  selectPair('R_75');
  return otSpec('R_75');
})()
"""


def run(page, js):
    return page.evaluate(js)


def check_rules(page):
    spec = run(page, SETUP)
    assert spec["label"], spec
    # 1. no stop -> refused
    e = run(page, "(() => { Object.assign(TK, {side:'buy', type:'market', volume: 0.5, slOn:false, sl:null, tpOn:false}); return OT.validate(); })()")
    assert "stop loss" in (e.get("sl") or ""), e
    # 2. the 50-lot mistake: stop 1,705 points away on $36,900 -> refused with the right lot
    e = run(page, "(() => { Object.assign(TK, {volume: 50, slOn:true, sl: 44000 - 1705}); return OT.validate(); })()")
    assert "Your limit is 1%" in (e.get("volume") or ""), e
    lots = run(page, "riskLots('R_75', 44000, 44000 - 1705, S.balance).lots")
    assert 0 < lots < 1, lots
    e = run(page, f"(() => {{ TK.volume = {lots}; return OT.validate(); }})()")
    assert not e.get("volume") and not e.get("general"), e
    # 3. open risk cap: one open trade already risking 1.5% blocks a new 1% trade
    e = run(page, f"""(() => {{
        TR.positions = [{{id: 91, symbol:'R_75', label:'Vol 75', side:'buy', volume: {lots} * 1.5, entry: 44000, sl: 44000 - 1705, tp: null, margin: 1, openTime: Date.now()}}];
        return OT.validate(); }})()""")
    assert "2% cap" in (e.get("general") or ""), e
    # 4. an open trade without a stop blocks new trades
    e = run(page, "(() => { TR.positions[0].sl = null; return OT.validate(); })()")
    assert "no stop loss" in (e.get("general") or ""), e
    # 5. three losing trades today -> locked
    e = run(page, """(() => { TR.positions = []; const t = Date.now();
        S.trades = [1,2,3].map(i => ({pnl: -10, closeTime: t})); return OT.validate(); })()""")
    assert "Three losing trades" in (e.get("general") or ""), e
    # 6. 3% daily loss -> locked
    e = run(page, "(() => { S.trades = [{pnl: -1200, closeTime: Date.now()}]; return OT.validate(); })()")
    assert "Daily loss limit" in (e.get("general") or ""), e
    run(page, "S.trades = []")


def check_tags(page):
    run(page, SETUP)
    txt = run(page, """(() => {
        TR.positions = [{id: 7, symbol:'R_75', label:'Vol 75', side:'buy', volume: 0.2, entry: 43990, sl: 43500, tp: 44800, margin: 1, openTime: Date.now()},
                        {id: 8, symbol:'R_75', label:'Vol 75', side:'buy', volume: 0.2, entry: 43900, sl: 43400, tp: 44900, margin: 1, openTime: Date.now()}];
        LEVELS.render();
        const q = k => { const e = LEVELS.els.get(k); return e ? e.querySelector('.c-qty').textContent : null; };
        const x = LEVELS.els.get('paper:7:sl').querySelector('.lvl-x');
        LEVELS.select('paper:7'); LEVELS.render();
        const faded = k => LEVELS.els.get(k).classList.contains('is-faded');
        const out = { sl: q('paper:7:sl'), tp: q('paper:7:tp'), entry: q('paper:7:entry'), xHidden: x.hidden,
                      focusSelf: faded('paper:7:entry'), focusOther: faded('paper:8:entry') && faded('paper:8:sl') };
        LEVELS.remove(LEVELS.groups()[0], 'sl');
        out.draftAfterRemove = !!LEVELS.draft;
        LEVELS.select('paper:7'); LEVELS.render();
        out.unfocused = !faded('paper:8:entry');
        return out; })()""")
    assert txt["sl"] == "SL" and txt["tp"] == "TP" and txt["entry"] == "0.2", txt
    assert txt["xHidden"] is True, txt                       # paper stops cannot be removed
    assert txt["draftAfterRemove"] is False, txt
    assert txt["focusSelf"] is False and txt["focusOther"] is True, txt
    assert txt["unfocused"] is True, txt                     # tapping again clears the focus


def check_autoprotect(page):
    run(page, SETUP)
    # default preset: +1R -> breakeven, trail 1R
    r = run(page, """(() => {
        TR.positions = [{id: 5, symbol:'R_75', label:'Vol 75', side:'buy', volume: 0.2, entry: 44000, sl: 43800, tp: null, r0: 200, margin: 1, openTime: Date.now()}];
        const p = TR.positions[0], out = {};
        __px = 44150; OT.checkProtection(); out.before = p.sl;          // +0.75R: nothing
        __px = 44200; OT.checkProtection(); out.at1R = p.sl; out.trail = p.trail;
        __px = 44350; OT.checkProtection(); out.after = p.sl;           // trails 1R behind
        __px = 44300; OT.checkProtection(); out.noLoosen = p.sl;
        return out; })()""")
    assert r["before"] == 43800 and r["at1R"] == 44000 and r["trail"] == 200, r
    assert r["after"] == 44150 and r["noLoosen"] == 44150, r
    # $100 preset on a sell: trigger and trail in dollars, converted with the position's size
    r = run(page, """(() => {
        AUTOP.pick('usd', 100);
        TR.positions = [{id: 6, symbol:'R_75', label:'Vol 75', side:'sell', volume: 0.24, entry: 44000, sl: 44300, tp: null, r0: 300, margin: 1, openTime: Date.now()}];
        const p = TR.positions[0], out = {};
        const per = otPnl('sell', 44000, 43999, 0.24, 'R_75');           // $ per point for 0.24 lots
        out.per = per;
        const need = 100 / per;
        __px = 44000 - need * 0.9; OT.checkProtection(); out.before = p.sl;
        __px = 44000 - need * 1.01; OT.checkProtection(); out.at = p.sl; out.trail = p.trail;
        __px = 44000 - need * 3; OT.checkProtection(); out.after = p.sl; out.need = need;
        AUTOP.pick('off');
        return out; })()""")
    assert r["before"] == 44300, r
    assert abs(r["at"] - (44000 - 0.01 * r["need"])) < 0.02, r   # breakeven, already trailing 1 point past it
    assert abs(r["trail"] - r["need"]) < 0.01, r
    assert abs(r["after"] - (44000 - 2 * r["need"])) < 0.02, r
    # off: nothing moves
    r = run(page, """(() => {
        TR.positions = [{id: 9, symbol:'R_75', label:'Vol 75', side:'buy', volume: 0.2, entry: 44000, sl: 43800, tp: null, r0: 200, margin: 1, openTime: Date.now()}];
        __px = 44600; OT.checkProtection(); return TR.positions[0] ? TR.positions[0].sl : 'closed'; })()""")
    assert r == 43800, r


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
        page.wait_for_function("typeof OT !== 'undefined' && typeof LEVELS !== 'undefined' && typeof AUTOP !== 'undefined'")
        page.wait_for_timeout(1500)
        for name, fn in [("risk rules", check_rules), ("chart tags", check_tags), ("auto-protect", check_autoprotect)]:
            fn(page)
            print(f"ok  {name}")
        assert not errs, errs
        b.close()
    httpd.shutdown()
    print("all paper-rule browser checks passed")


if __name__ == "__main__":
    main()
