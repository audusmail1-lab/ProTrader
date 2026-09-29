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
        S.trades = [1,2,3].map(i => ({id: i, entry: 100 + i, pnl: -10, closeTime: t})); return OT.validate(); })()""")
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
    assert run(page, "AUTOP.load().preset") == "r1"      # default: +1R -> breakeven, trail 1R
    # +1R -> breakeven, trail 1R
    r = run(page, """(() => {
        AUTOP.pick('r1');
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


def check_positions(page):
    run(page, SETUP)
    r = run(page, """(async () => {
        S.trades = []; S.posStats = null; S.balance = 36900;
        // a position opened through the ticket path records its entry stop and risk
        OT.openPosition({ symbol: 'R_75', side: 'buy', volume: 0.2, stopLoss: 43800, takeProfit: null, accountId: TR.acct.id }, 44000);
        const p = TR.positions[TR.positions.length - 1], out = { sl0: p.sl0, risk0: p.risk0 };
        __px = 44300; await OT.closePosition(p.id, 0.1, 'Partial close');        // +$30 tranche
        __px = 43850; await OT.closePosition(p.id, null, 'Manual');               // -$15 tranche -> net +$15
        OT.openPosition({ symbol: 'R_75', side: 'sell', volume: 0.2, stopLoss: 44200, takeProfit: null, accountId: TR.acct.id }, 44000);
        const q = TR.positions[TR.positions.length - 1];
        __px = 43900; await OT.closePosition(q.id, 0.1, 'Partial close');        // +$10
        __px = 44150; await OT.closePosition(q.id, null, 'Manual');               // -$15 -> net -$5
        // an old record without an id or stop: grouped by entry price
        S.trades.push({ sym: 'R_75', type: 'buy', volume: 0.1, entry: 100, exit: 101, pnl: 2, closeTime: Date.now() },
                      { sym: 'R_75', type: 'buy', volume: 0.1, entry: 100, exit: 99, pnl: -1, closeTime: Date.now() });
        S.posStats = null; renderPortfolio();
        const st = posStats();
        out.fills = S.trades.length; out.wins = st.wins; out.losses = st.losses; out.rN = st.rN; out.avgR = st.rSum / st.rN;
        out.wr = document.getElementById('winRate').textContent; out.total = document.getElementById('totalTrades').textContent;
        out.fillR = S.trades[0].r; out.fillSl0 = S.trades[0].sl0;
        return out; })()""")
    assert r["sl0"] == 43800 and abs(r["risk0"] - 40) < 1e-6, r            # 0.2 lots x 200 points
    assert r["fills"] == 6 and r["wins"] == 2 and r["losses"] == 1, r       # 3 positions, not 6 fills
    assert r["wr"] == "67%" and r["total"] == "3", r
    assert r["rN"] == 2 and abs(r["avgR"] - ((15 / 40) + (-5 / 40)) / 2) < 1e-6, r
    assert r["fillSl0"] == 43800 and abs(r["fillR"] - 30 / 40) < 1e-6, r
    run(page, "TR.positions = []; S.trades = []; S.posStats = null")


def check_modify(page):
    run(page, SETUP)
    r = run(page, """(async () => {
        window.__px = 44200;   // price has rallied well past entry
        TR.positions = [{id: 41, symbol:'R_75', label:'Vol 75', side:'buy', volume: 0.2, entry: 44000, sl: 43800, tp: null, margin: 1, openTime: Date.now()}];
        const out = {};
        OT.openModify('position', 41);
        // moving the stop to breakeven is a routine, safe move once a trade is in profit
        document.getElementById('modSl').value = '44000';
        document.getElementById('modTp').value = '';
        await OT.applyModify('position', 41);
        const err1 = document.getElementById('modErr');
        out.breakevenRejected = !!err1 && err1.style.display !== 'none';
        out.slAfterBreakeven = TR.positions[0].sl;
        // a stop inside the required buffer (half the minimum distance) should be refused
        const minDist = otMinDist('R_75');
        out.minDist = minDist;
        OT.openModify('position', 41);
        document.getElementById('modSl').value = String(window.__px - minDist / 2);
        document.getElementById('modTp').value = '';
        await OT.applyModify('position', 41);
        const err2 = document.getElementById('modErr');
        out.tightStopRejected = !!err2 && err2.style.display !== 'none';
        return out; })()""")
    assert r["breakevenRejected"] is False, r          # moving SL to breakeven on a winner must be allowed
    assert r["slAfterBreakeven"] == 44000, r
    assert r["tightStopRejected"] is True, r           # a stop inside the live buffer must still be refused
    run(page, "TR.positions = []")


def check_auto_size(page):
    run(page, SETUP)
    r = run(page, """(() => {
        const out = {}, sp = otSpec('R_75');
        S.trades = []; TR.positions = []; TR.orders = []; S.balance = 36900; S.riskPct = 1; TK.auto = true;
        const loss = () => -otPnl(TK.side, OT.entryRef(), TK.sl, TK.volume, 'R_75');
        // a buy limit: the lot is sized from the LIMIT price, not the market
        OT.setSide('buy'); OT.setType('limit'); OT.onPriceInput('43800'); OT.toggleSl(true); OT.onSlInput('43500');
        out.lot1 = TK.volume; out.loss1 = loss(); out.note1 = document.getElementById('otRiskNote').textContent;
        OT.onSlInput('43650');                                     // stop half as far -> lot doubles, same risk
        out.lot2 = TK.volume; out.loss2 = loss();
        OT.onPriceInput('43900');                                  // limit moved -> resized again
        out.lot3 = TK.volume; out.loss3 = loss();
        out.err3 = OT.validate();
        // another trade already risks 1.5%: only the 0.5% of room left under the 2% cap is offered
        TR.positions = [{id: 71, symbol:'R_75', label:'Vol 75', side:'buy', volume: 0.1, entry: 44000, sl: 44000 - 5535, tp: null, margin: 1, openTime: Date.now()}];
        OT.render(); out.lot4 = TK.volume; out.loss4 = loss(); out.note4 = document.getElementById('otRiskNote').textContent; out.err4 = OT.validate();
        TR.positions = []; OT.render();
        // a manual lot stays put until the tile is tapped
        OT.onVolumeInput('0.05'); OT.onSlInput('43600');
        out.manual = TK.volume; out.manualNote = document.getElementById('otRiskNote').textContent;
        OT.sizeToRisk(true); out.back = TK.volume; out.backLoss = loss(); out.auto = TK.auto;
        // market order: price ticks never grow the lot, but it shrinks if a tick pushes risk over the budget
        OT.setType('market'); OT.onSlInput('43700'); const m0 = TK.volume;
        __px = 43990; OT.render(); out.tickSame = TK.volume <= m0;
        __px = 44200; OT.render(); out.tickShrunk = TK.volume < m0; out.tickLoss = loss();
        __px = 44000;
        return out; })()""")
    budget = 369
    assert abs(r["loss1"] - budget) <= 0.01 * 300 * 1 + 1 and r["loss1"] <= budget + 0.01, r
    assert abs(r["lot2"] - 2 * r["lot1"]) < 0.02 and r["loss2"] <= budget + 0.01, r
    assert r["lot3"] != r["lot2"] and r["loss3"] <= budget + 0.01 and not r["err3"].get("volume"), r
    assert r["note1"] == "$369.00 ÷ $300.00 per lot", r            # the working: risk ÷ loss per lot at the stop
    assert r["loss4"] <= 0.005 * 36900 + 0.01 and "2% open-risk cap" in r["note4"] and not r["err4"].get("general"), r
    assert r["manual"] == 0.05 and r["manualNote"].startswith("manual"), r
    assert r["auto"] is True and r["back"] > 0.05 and r["backLoss"] <= budget + 0.01, r
    assert r["tickSame"] and r["tickShrunk"] and r["tickLoss"] <= budget + 0.01, r

    run(page, "TR.positions = []; TR.orders = []; S.trades = []; OT.setType('market'); OT.toggleSl(false)")


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
        for name, fn in [("risk rules", check_rules), ("chart tags", check_tags), ("auto-protect", check_autoprotect), ("positions not fills", check_positions), ("modify SL/TP", check_modify), ("auto size from risk", check_auto_size)]:
            fn(page)
            print(f"ok  {name}")
        assert not errs, errs
        b.close()
    httpd.shutdown()
    print("all paper-rule browser checks passed")


if __name__ == "__main__":
    main()
