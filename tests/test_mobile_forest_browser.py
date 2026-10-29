"""
The phone shell ("forest"), tested in a real browser against protrader_mobile.html.

A phone gets the deep-green theme, the two-row header, the white chart card with a
timeframe menu and Expand, the Insights · Positions · Orders sheet fed by ARIA,
ORACLE and Sentinel, and the four-tab bar. Desktop keeps its own themes, pixel for
pixel. Synthetic provider-shaped candles replace the feed; this checks the UI
contract, not live provider delivery or Oracle's model quality.
   python3 tests/test_mobile_forest_browser.py [screenshot-dir]
"""
import functools
import http.server
import json
import os
import socketserver
import sys
import threading

from playwright.sync_api import sync_playwright

ROOT = os.path.join(os.path.dirname(__file__), "..")
PROXY = os.environ.get("HTTPS_PROXY", "")


def serve():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    httpd = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


# No provider sockets are opened by this UI fixture. A permanently connecting
# socket preserves the feed's normal waiting state until SETUP supplies history.
# In particular, a delayed live reply cannot overwrite the fixed test candles.
ISOLATE_FEED = """
(() => {
  class FixtureWebSocket extends EventTarget {
    static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
    constructor(url) { super(); this.url = String(url); this.readyState = 0; this.bufferedAmount = 0; }
    send() {}
    close() { this.readyState = 3; }
  }
  Object.assign(FixtureWebSocket.prototype, {CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3});
  window.WebSocket = FixtureWebSocket;
})()
"""

# Deterministic synthetic completed 1h candles: bullish direction, six of ten
# known rules met, and scanner patterns. Indicators and rules remain production code.
SETUP = """
(() => {
  selectPair('R_50'); if (S.tf !== '1h') MOB.pickTf('1h');
  const tf = 3600, t0 = Math.floor(Date.now() / 1000 / tf) * tf - 240 * tf;
  let p = 80, k = 7; const rnd = () => { k = (k * 9301 + 49297) % 233280; return k / 233280; };
  S.candles = Array.from({ length: 240 }, (_, i) => { const o = p, c = p + Math.sin(i / 7) * 0.35 + (rnd() - 0.5) * 0.4; p = c;
    return { time: t0 + i * tf, open: o, high: Math.max(o, c) + rnd() * 0.25, low: Math.min(o, c) - rnd() * 0.25, close: c, vol: 0 }; });
  S.wsConnected = true;
  // Deriv is the provider contract under test, not a claim of real delivery.
  S.candleProvenance = {symbol: S.sym, timeframe: S.tf, source: 'Deriv',
    observedAt: Date.now() / 1000, baseTime: S.candles.at(-1).time, needsRefresh: false,
    fixture: 'synthetic-mobile-forest'};
  const last = S.candles[S.candles.length - 1];
  otQuote = id => ({ ok: true, stale: false, bid: last.close, ask: last.close, last: last.close, mid: last.close, hasSpread: false });
  putQuote(S.sym, last.close, null, 'Deriv', true);
  drawChart(); renderARIA(); runPatternScanner(); updateTopbar(); renderCheck(); OT.renderBook();
  return S.candles.length;
})()
"""


def ok(msg):
    print("ok ", msg)


def rect(page, sel):
    return page.evaluate(f"(() => {{ const e = document.querySelector({json.dumps(sel)}); if (!e) return null; const r = e.getBoundingClientRect(); return {{ l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height }}; }})()")


def visible(page, sel):
    r = rect(page, sel)
    return bool(r and r["w"] > 0 and r["h"] > 0)


def boot(page, port):
    page.add_init_script(ISOLATE_FEED)
    page.goto(f"http://127.0.0.1:{port}/protrader_mobile.html", wait_until="domcontentloaded")
    page.wait_for_function("typeof MOB !== 'undefined' && typeof OT !== 'undefined' && typeof CH !== 'undefined' && CH.ready")
    page.wait_for_timeout(800)
    page.evaluate(SETUP)
    page.wait_for_timeout(600)
    fixture = page.evaluate("""(() => { const m = checkModel(); return {
      history: m?.dataStatus?.available, available: m?.gates?.available,
      dir: m?.gates?.dir, total: m?.gates?.total, score: m?.gates?.score,
      percentage: m?.gates?.percentage, unavailable: m?.gates?.unavailable,
      fixture: S.candleProvenance?.fixture
    }; })()""")
    assert fixture == {"history": True, "available": True, "dir": "buy", "total": 10,
                       "score": 6, "percentage": 60, "unavailable": 0,
                       "fixture": "synthetic-mobile-forest"}, fixture


def check_phone(page, port, shots):
    boot(page, port)
    assert page.evaluate("document.documentElement.dataset.theme") == "forest"
    assert page.evaluate("document.documentElement.scrollWidth") <= 392
    ok("phone: the forest theme is on, with no sideways scroll")

    # one compact header row: symbol · PAPER · ARIA; no price row, no clock; the chart starts right under it
    sym, acct, aria, hd, card = (rect(page, s) for s in ("#symChip", "#acctChip", "#voiceBtn", ".topbar", ".chart-toolbar"))
    assert abs(sym["t"] - acct["t"]) < 6 and abs(acct["t"] - aria["t"]) < 6 and aria["r"] <= 390, (sym, acct, aria)
    assert hd["h"] <= 56 and card["t"] - hd["b"] <= 4, (hd, card)
    assert not visible(page, "#livePrice") and not visible(page, "#liveChg") and not visible(page, "#updateTs")
    assert page.evaluate("document.getElementById('acctChip').textContent.trim().toUpperCase().startsWith('PAPER')")
    r = rect(page, "#voiceBtn"); assert r and abs(r["w"] - r["h"]) < 2, r                  # the round ARIA button
    assert not visible(page, "#notifyBtn") and not visible(page, "#themeBtn")
    ok("phone: one compact header (symbol · PAPER · ARIA); the chart card begins right under it")

    # the chart card: white, a timeframe menu, Draw, Indicators, Expand
    bg = page.evaluate("getComputedStyle(document.querySelector('.chart-wrap')).backgroundColor")
    assert bg == "rgb(255, 255, 255)", bg
    assert page.evaluate("document.getElementById('mTfLbl').textContent") == "1H"
    assert not visible(page, ".tf-btn") and visible(page, "#mExpand")
    page.tap("#mTf")
    page.wait_for_selector("#mTfMenu:not([hidden])")
    assert page.evaluate("[...document.querySelectorAll('#mTfMenu button')].map(b => b.firstChild.textContent.trim())") == ["1M", "5M", "15M", "1H", "4H", "1D", "1W"]
    page.evaluate("MOB.pickTf('15m')")
    page.wait_for_timeout(300)
    assert page.evaluate("S.tf") == "15m" and page.evaluate("document.getElementById('mTfLbl').textContent") == "15M"
    assert page.evaluate("document.getElementById('mTfMenu').hidden")
    page.evaluate(SETUP); page.wait_for_timeout(400)
    ok("phone: the white chart card with a timeframe menu (1M … 1W) that changes the chart")

    # rising candles are solid teal, the last-price line is the brand green, the EMA is grey, the markers are numbered
    opts = page.evaluate("({ up: CH.candle.options().upColor, border: CH.candle.options().borderVisible, ema: CH.ema20.options().color, spacing: CH.chart.timeScale().options().barSpacing, line: CH.candle.options().priceLineColor })")
    assert opts == {"up": "#089981", "border": True, "ema": "#7c9193", "spacing": 4, "line": "rgba(5,68,58,.75)"}, opts
    marks = page.evaluate("S.activePatterns.slice(0, 3).map((p, i) => String(i + 1))")
    assert len(marks) >= 1 and page.evaluate("BADGES.items.map(b => b.label)") == marks
    assert page.evaluate("!!document.querySelector('.ohlc-bar .m-eye')") and not visible(page, ".ohlc-bar .ohlc-item")
    page.tap(".ohlc-bar .m-eye"); page.wait_for_timeout(150)
    assert page.evaluate("!S.ind.ema && !CH.ema20.options().visible")
    page.tap(".ohlc-bar .m-eye"); page.wait_for_timeout(150)
    assert page.evaluate("S.ind.ema && CH.ema20.options().visible")
    ok(f"phone: solid rising candles, a thin grey EMA with an eye toggle, {len(marks)} numbered badge(s) drawn in the chart")

    # the sheet: Insights is the default tab, collapsed to one headline; the grip pulls it up
    assert page.evaluate("document.querySelector('.bstab.active').dataset.tab") == "insights"
    assert not visible(page, ".bstab[data-tab='scanner']") and not visible(page, ".bstab[data-tab='signals']") and not visible(page, ".bstab[data-tab='journal']")
    assert visible(page, "#insightsPane .mi-head .mi-row") and not visible(page, "#insightsPane .mi-chips")
    n = int(page.evaluate("document.getElementById('bsInsightsN').textContent"))
    assert n >= 3, n
    page.tap("#tradeDockGrip")
    page.wait_for_timeout(450)
    assert page.evaluate("MOB.sheet.isUp()") and visible(page, "#insightsPane .mi-chips")
    secs = page.evaluate("[...document.querySelectorAll('#insightsPane .mi-full .mi-sec')].map(s => s.firstChild.nextSibling.textContent.trim())")
    assert secs == ["ARIA", "ORACLE", "Patterns"], secs
    rows = page.evaluate("[...document.querySelectorAll('#insightsPane .mi-full .mi-row .mi-h')].map(h => h.firstChild.textContent)")
    # The strategy's UTC time restriction can pause this same known checklist.
    expected_aria = "Strategy restriction" if page.evaluate("checkModel().mcc.code === 'DEAD_ZONE'") else "Mixed checklist"
    assert rows[:2] == [expected_aria, "Oracle · independent review"], rows
    a = page.evaluate("""(() => { const r = document.querySelector('#insightsPane .mi-full .mi-row');
      return {tag: r.querySelector('.mi-tag').textContent, act: r.querySelector('.mi-act').textContent}; })()""")
    assert a == {"tag": "60% · 6/10", "act": "See checks"}, a
    badges = page.evaluate("[...document.querySelectorAll('#insightsPane .mi-full .mi-sec:last-of-type ~ .mi-row .mi-bd')].map(b => b.textContent)")
    assert badges[: len(marks)] == marks, (badges, marks)
    ok(f"phone: the sheet opens on the grip; {n} insights in ARIA · ORACLE · Patterns sections, patterns numbered like the chart")
    if shots:
        page.screenshot(path=os.path.join(shots, "forest_insights_up.png"))

    # Oracle is an independent review, not another score or a ticket-fill shortcut.
    page.evaluate("MOB.setFilter('oracle')")
    assert page.evaluate("document.querySelectorAll('#insightsPane .mi-full .mi-row').length") == 1
    o = page.evaluate("(() => { const r = document.querySelector('#insightsPane .mi-full .mi-row'); return { head: r.querySelector('.mi-h').firstChild.textContent, tag: r.querySelector('.mi-tag').textContent, sub: r.querySelector('.mi-p').textContent, act: r.querySelector('.mi-act').textContent, badge: r.querySelector('.mi-bd').textContent }; })()")
    assert o == {"head": "Oracle · independent review", "tag": "Open Oracle", "badge": "O",
                 "sub": "Read the 4H, 1H, 15m and 5m context, then discuss the evidence.",
                 "act": "Open review"}, o
    trade_state = page.evaluate("JSON.stringify({ticket: TK, positions: TR.positions, orders: TR.orders})")
    session_requests = []
    def record_oracle_session(route):
        session_requests.append(route.request.method)
        route.fulfill(status=503, content_type="application/json", body='{"error":"Provider sessions disabled in this UI fixture"}')
    page.route("**/api/oracle/conversation/session", record_oracle_session)
    page.tap("#insightsPane .mi-full .mi-row")
    page.wait_for_function("document.getElementById('rightPanel').classList.contains('open') && document.querySelector('.rtab.active').dataset.tab === 'oracle'")
    assert visible(page, "#oraclePane") and visible(page, "#oracle-panel .oa-panel")
    assert not page.evaluate("MOB.sheet.isUp()")
    assert page.evaluate("document.querySelector('.mobile-nav-btn.active').dataset.mobileView") == "chart"
    assert page.evaluate("JSON.stringify({ticket: TK, positions: TR.positions, orders: TR.orders})") == trade_state
    assert not session_requests, session_requests
    page.evaluate("mobileSetView('chart')")
    page.evaluate("MOB.setFilter('all')")
    ok("phone: Oracle's filtered row opens the independent review without changing the ticket, placing an order, or starting a provider conversation")

    # Plan trade opens the ticket on the pattern's side; the sheet drops, Workspace stays lit
    page.evaluate("MOB.plan('sell')")
    page.wait_for_timeout(400)
    assert page.evaluate("document.getElementById('rightPanel').classList.contains('open') && document.querySelector('.rtab.active').dataset.tab === 'trade'")
    assert page.evaluate("TK.side") == "sell" and not page.evaluate("MOB.sheet.isUp()")
    assert page.evaluate("document.querySelector('.mobile-nav-btn.active').dataset.mobileView") == "chart"
    if shots:
        page.screenshot(path=os.path.join(shots, "forest_ticket.png"))
    page.evaluate("mobileSetView('chart')")
    ok("phone: Plan trade opens the ticket on the sell side; the bar keeps Workspace lit")

    # the bar: Journal lives in the sheet, Portfolio carries the account card, Markets opens the picker
    page.evaluate("S.trades.push({ id: 7, type: 'sell', volume: 0.5, pair: 'Vol 50', sym: 'R_50', entry: 81.2, exit: 80.9, pnl: 15, reason: 'Take profit', openTime: Date.now() - 3600000, closeTime: Date.now() - 60000 })")
    page.tap(".mobile-nav-btn[data-mobile-view='journal']")
    page.wait_for_timeout(400)
    assert page.evaluate("MOB.sheet.isUp() && document.querySelector('.bstab.active').dataset.tab === 'journal'")
    assert visible(page, ".bstab[data-tab='journal']") and not visible(page, "#bsInsights")
    assert page.evaluate("document.querySelector('.mobile-nav-btn.active').dataset.mobileView") == "journal"
    j = page.evaluate("document.getElementById('journalPane').innerText")
    assert "1 closed trade" in j and "Vol 50" in j and "81.2" in j and "80.9" in j and "$15.00" in j, j
    assert visible(page, "#journalPane .hx-row") and rect(page, "#journalPane .hx-row")["l"] >= 8
    page.evaluate("MOB.sheet.close()"); page.wait_for_timeout(200)          # pulled down, the sheet is the Insights strip again
    assert page.evaluate("document.querySelector('.bstab.active').dataset.tab") == "insights" and visible(page, "#bsInsights")
    assert page.evaluate("document.querySelector('.mobile-nav-btn.active').dataset.mobileView") == "chart"
    page.tap(".mobile-nav-btn[data-mobile-view='journal']"); page.wait_for_timeout(300)
    page.tap(".mobile-nav-btn[data-mobile-view='chart']")
    page.wait_for_timeout(300)
    assert page.evaluate("document.querySelector('.bstab.active').dataset.tab") == "insights" and visible(page, "#bsInsights")
    page.evaluate("S.trades.pop(); OT.renderBook()")
    page.tap(".mobile-nav-btn[data-mobile-view='portfolio']")
    page.wait_for_timeout(400)
    assert page.evaluate("document.querySelector('.rtab.active').dataset.tab") == "portfolio"
    assert visible(page, "#mAcct") and "Guest" in page.evaluate("document.getElementById('mAcct').textContent")
    assert page.evaluate("!!document.querySelector('#mAcct button.pri')")
    build = page.evaluate("document.querySelector('#mAcct .m-acct-build').textContent")
    assert build.startswith("v") and "390×844" in build and "bottom inset" in build, build
    if shots:
        page.screenshot(path=os.path.join(shots, "forest_portfolio.png"))
    page.tap(".mobile-nav-btn[data-mobile-view='markets']")
    page.wait_for_timeout(400)
    assert page.evaluate("!!document.querySelector('#pairSheet.open')")
    page.evaluate("mobileSetView('chart')")
    ok("phone: Journal opens the trade history in the sheet and leaves with it; Portfolio shows the account card (guest → sign in); Markets opens the picker")

    # the audit's fixes: the active bar icon is the brand green on its mint pill; the toolbar's labels keep clear of each other
    page.tap(".mobile-nav-btn[data-mobile-view='portfolio']"); page.wait_for_timeout(300)
    ico = page.evaluate("getComputedStyle(document.querySelector('.mobile-nav-btn.active .ico')).color")
    assert ico == "rgb(5, 68, 58)", ico
    page.evaluate("mobileSetView('chart')"); page.wait_for_timeout(200)
    ind, exp = rect(page, ".chart-toolbar .ws-menu summary"), rect(page, "#mExpand")
    assert ind["r"] <= exp["l"] + 1 and page.evaluate("(() => { const s = document.querySelector('.chart-toolbar .ws-menu summary'); return s.scrollWidth <= s.clientWidth + 1; })()"), (ind, exp)
    ok("phone: the lit bar icon shows on its pill; Indicators and Expand each keep their own room")

    # the Indicators menu: styled like the card it opens from; Vol is refused on a market without volume
    page.tap(".chart-toolbar .ws-menu summary"); page.wait_for_timeout(300)
    m = page.evaluate("(() => { const b = document.querySelector('.ws-menu-body.is-portal'); return b && { bg: getComputedStyle(b).backgroundColor, act: getComputedStyle(b.querySelector('.ind-btn.active')).backgroundColor }; })()")
    assert m and m["bg"] == "rgb(255, 255, 255)" and m["act"] == "rgb(5, 68, 58)", m
    page.evaluate("togInd('vol', document.getElementById('ind-vol'))"); page.wait_for_timeout(100)
    assert not page.evaluate("S.ind.vol") and not page.evaluate("document.getElementById('ind-vol').classList.contains('active')")
    assert "no volume" in page.evaluate("document.getElementById('voiceText').textContent")
    page.keyboard.press("Escape"); page.wait_for_timeout(200)
    ok("phone: the Indicators menu is a white card with green active rows; Vol explains itself instead of lighting up")

    # a selected drawing's toolbar on the white card: every control dark on light, bordered, separated into groups
    page.evaluate("DT.arm('horizontal-line')"); page.wait_for_timeout(200)
    armed = page.evaluate("(() => { const a = document.querySelector('#dtFloat .dt-armed'); return a && getComputedStyle(a).color; })()")
    assert armed == "rgb(5, 68, 58)", armed
    page.tap("#lwChart", position={"x": 180, "y": 220}); page.wait_for_timeout(400)
    tb = page.evaluate("""(() => { const f = document.getElementById('dtFloat'); if (f.hidden) return null;
      const lum = c => { const m = c.match(/\\d+(\\.\\d+)?/g).map(Number); return (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / 255; };
      return { bg: getComputedStyle(f).backgroundColor, seps: f.querySelectorAll('.dt-fsep').length, title: getComputedStyle(f.querySelector('.dt-ftitle')).color,
        btns: [...f.querySelectorAll('.dt-fbtn')].map(b => { const cs = getComputedStyle(b); return [b.getAttribute('aria-label'), lum(cs.color) < 0.5, lum(cs.backgroundColor) > 0.85, cs.borderTopColor !== 'rgba(0, 0, 0, 0)', b.getBoundingClientRect().right <= 390]; }) }; })()""")
    assert tb and tb["bg"] == "rgb(255, 255, 255)" and tb["seps"] == 3 and tb["title"] == "rgb(21, 33, 30)", tb
    assert len(tb["btns"]) >= 7 and all(b[1] and b[2] and b[3] and b[4] for b in tb["btns"]), tb["btns"]
    page.tap('#dtFloat [aria-label="Remove (Del)"]'); page.wait_for_timeout(200)
    assert page.evaluate("DT.drawings().length") == 0 and page.evaluate("document.getElementById('dtFloat').hidden")
    ok(f"phone: a selected drawing's toolbar shows {len(tb['btns'])} dark, bordered controls on the white card in {tb['seps'] + 1} groups")

    # the drawing sheet sits above the tab bar, in the forest palette, without keyboard hints
    page.tap("#chartTools"); page.wait_for_timeout(300)
    d = page.evaluate("(() => { const s = document.getElementById('dtSheet'); const r = s.getBoundingClientRect(); const nav = document.querySelector('.mobile-nav'); return { z: +getComputedStyle(s).zIndex, navZ: +getComputedStyle(nav).zIndex, bg: getComputedStyle(s).backgroundColor, kbd: [...s.querySelectorAll('kbd')].some(k => k.getBoundingClientRect().width > 0), top: document.elementFromPoint(20, r.bottom - 8)?.closest('#dtSheet') != null }; })()")
    assert d["z"] > d["navZ"] and d["bg"] != "rgb(13, 19, 32)" and not d["kbd"] and d["top"], d
    page.evaluate("DT.closeSheet()")
    ok("phone: the drawing sheet opens above the tab bar in the forest palette, no shortcut badges")

    # the check panel counts every gate; the ticket's switches follow a fill; a capped size is worded honestly
    page.evaluate("openMobilePanel('check')"); page.wait_for_timeout(300)
    cnt = page.evaluate("document.querySelector('#check-panel .chk-score-count').textContent")
    n_gates = page.evaluate("checkModel().gates.gates.length")
    assert cnt == "6 of 10 conditions met" and n_gates == page.evaluate("ARIA_GATE_COUNT") == 10, (cnt, n_gates)
    assert page.evaluate("document.querySelector('#check-panel .chk-score-value').textContent") == "60%"
    assert page.evaluate("document.querySelector('#check-panel .chk-score-card').dataset.available") == "true"
    assert "Checklist completion, not the probability of a winning trade." in page.inner_text("#check-panel")
    assert page.evaluate("document.getElementById('chkMoreToggle').textContent") == "See all 10 checks ▾"
    assert page.get_attribute("#chkMoreToggle", "aria-expanded") == "false"
    assert page.evaluate("!!(document.getElementById('chkMoreToggle').compareDocumentPosition(document.getElementById('chkOracle')) & Node.DOCUMENT_POSITION_FOLLOWING)")
    page.tap("#chkMoreToggle")
    assert page.get_attribute("#chkMoreToggle", "aria-expanded") == "true"
    checks = page.evaluate("""[...document.querySelectorAll('#chkMore .chk')].map(row => ({
      visible: row.getBoundingClientRect().height > 0,
      pass: !row.classList.contains('fail') && !row.classList.contains('unknown'),
      label: row.querySelector('.chk-txt').firstChild.textContent
    }))""")
    assert len(checks) == 10 and all(c["visible"] for c in checks) and sum(c["pass"] for c in checks) == 6, checks
    assert len({c["label"] for c in checks}) == 10, checks
    assert page.evaluate("document.getElementById('chkMoreToggle').textContent") == "Hide all 10 checks ▴"
    page.tap("#chkMoreToggle")
    assert page.get_attribute("#chkMoreToggle", "aria-expanded") == "false" and not visible(page, "#chkMore")
    page.evaluate("openMobilePanel('trade'); OT.setSide('buy'); OT.setType('market'); OT.toggleSl(true); OT.toggleTp(true); document.getElementById('otSlOn').checked = true; document.getElementById('otTpOn').checked = true")
    page.wait_for_timeout(200)
    assert page.evaluate("TK.slOn && TK.tpOn && document.getElementById('otSlRow').style.display === 'grid'")
    page.evaluate("OT.consumeLevels()")
    st = page.evaluate("({ slOn: TK.slOn, box: document.getElementById('otSlOn').checked, row: document.getElementById('otSlRow').style.display, tbox: document.getElementById('otTpOn').checked, trow: document.getElementById('otTpRow').style.display })")
    assert st == {"slOn": False, "box": False, "row": "none", "tbox": False, "trow": "none"}, st
    page.evaluate("mobileSetView('chart')")
    ok(f"phone: the check panel says 'of {n_gates}'; after a fill the stop and target switches are off with their rows hidden")

    # an open position's row fits the sheet: every action button inside the screen and above the tab bar
    page.evaluate("TR.positions.push({ id: 99, symbol: S.sym, label: S.symLabel, side: 'buy', volume: 0.5, entry: S.candles[S.candles.length - 1].close, sl: S.candles[S.candles.length - 1].close - 1, tp: S.candles[S.candles.length - 1].close + 2, margin: 20, openTime: Date.now(), realized: 0 }); OT.renderBook(); MOB.sheet.tab('positions'); MOB.sheet.open()")
    page.wait_for_timeout(400)
    acts = page.evaluate("[...document.querySelectorAll('#positionsPane .pos-act')].map(b => { const r = b.getBoundingClientRect(); return [b.textContent.trim(), Math.round(r.right), Math.round(r.bottom)]; })")
    nav_top = rect(page, ".mobile-nav")["t"]
    assert [a[0] for a in acts] == ["BE", "Trail", "SL·TP", "½", "Close"] and all(a[1] <= 390 and a[2] <= nav_top for a in acts), (acts, nav_top)
    page.evaluate("TR.positions.pop(); OT.renderBook(); MOB.sheet.close(); MOB.sheet.tab('insights')")
    ok("phone: a position's BE · Trail · SL·TP · ½ · Close buttons all sit inside the screen, above the bar")

    # the right panel starts each tab at its top
    page.evaluate("openMobilePanel('trade'); document.querySelector('.right-panel .rpanel-body').scrollTop = 150; openMobilePanel('sentinel')"); page.wait_for_timeout(200)
    assert page.evaluate("document.querySelector('.right-panel .rpanel-body').scrollTop") == 0
    page.evaluate("mobileSetView('chart')")
    ok("phone: switching panel tabs starts the new tab at its top")

    # Expand hides the sheet and the bar; the chart takes the screen
    h0 = rect(page, ".chart-wrap")["h"]
    page.tap("#mExpand"); page.wait_for_timeout(400)
    assert not visible(page, "#tradeDock") and not visible(page, ".mobile-nav") and rect(page, ".chart-wrap")["h"] > h0 + 100
    page.tap("#mExpand"); page.wait_for_timeout(300)
    assert visible(page, "#tradeDock") and visible(page, ".mobile-nav")
    ok("phone: Expand gives the chart the whole screen and back")

    # the phone keeps its look: the T key, toggleTheme() and the voice "dark mode" intent leave forest alone
    page.evaluate("toggleTheme()"); page.keyboard.press("t"); page.wait_for_timeout(100)
    assert page.evaluate("document.documentElement.dataset.theme") == "forest" and visible(page, "#insightsPane")
    ok("phone: the theme toggle leaves the phone in forest")

    # turned sideways: one header row, a short bar, the sheet collapsed to its tabs, the chart gets the height
    page.set_viewport_size({"width": 844, "height": 390}); page.wait_for_timeout(400)
    assert page.evaluate("document.documentElement.dataset.theme") == "forest"
    hd, ch, nav = rect(page, ".topbar"), rect(page, ".chart-wrap"), rect(page, ".mobile-nav")
    assert hd["h"] <= 50 and ch["h"] >= 170 and nav["h"] <= 60 and page.evaluate("document.documentElement.scrollWidth") <= 846, (hd, ch, nav)
    page.set_viewport_size({"width": 390, "height": 844}); page.wait_for_timeout(400)
    ok("phone: landscape keeps a usable chart (one header row, short bar)")

    # ARIA's floating card: header, provider chip and the five mode tabs on top, the mic beside the field at the bottom, only the middle scrolls
    page.route("**/api/aria/ai/status", lambda r: r.fulfill(status=200, content_type="application/json", body='{"enabled":true,"label":"Claude Sonnet 5.5 (Anthropic API, promotional credits)","remaining_today":15,"privacy":"ARIA sends your words and chart data only. Do not share personal details."}'))
    page.evaluate("VOICE.open(false)"); page.wait_for_timeout(600)
    r = rect(page, ".vx-sheet")
    assert r and r["l"] >= 0 and r["r"] <= 390 and r["h"] <= 844 * 0.72, r
    tabs = page.evaluate("[...document.querySelectorAll('#cpModes .cp-mode')].map(b => [b.textContent, b.getBoundingClientRect().right <= 390 && b.getBoundingClientRect().width > 50])")
    assert [t[0] for t in tabs] == ["Talk", "Analyze", "Learn", "Practice", "Replay"] and all(t[1] for t in tabs), tabs
    page.wait_for_function("!document.getElementById('cpAiChip').hidden && document.getElementById('cpAiChipTxt').textContent.includes('Claude Sonnet 5.5')")
    chip = page.evaluate("document.getElementById('cpAiChipTxt').textContent")
    assert chip.startswith("Claude Sonnet 5.5 · 15 left") and page.evaluate("document.getElementById('cpAiNote').hidden"), chip
    page.tap("#cpAiChip"); page.wait_for_timeout(150)
    assert not page.evaluate("document.getElementById('cpAiNote').hidden") and "Do not share personal details" in page.evaluate("document.getElementById('cpAiNote').textContent")
    page.tap("#cpAiChip"); page.wait_for_timeout(150)
    assert page.evaluate("document.getElementById('cpAiNote').hidden")
    orb, inp, send = rect(page, "#vxOrb"), rect(page, "#vxInput"), rect(page, ".vx-type button[type=submit]")
    assert orb["r"] <= inp["l"] and inp["r"] <= send["l"] and abs(orb["t"] + orb["h"] / 2 - (inp["t"] + inp["h"] / 2)) < 6, (orb, inp, send)
    assert visible(page, "#vxHint") and not visible(page, "#vxHeard")
    page.evaluate("COPILOT.setMode('analyze')"); page.wait_for_timeout(300)
    read = page.evaluate("(() => { const r = document.querySelector('#cpPanel .cp-read'); return r && { pct: r.querySelector('.cp-read-h b').textContent, v: r.querySelector('.cp-read-v').textContent, tiles: [...r.querySelectorAll('.cp-dna span')].map(x => x.textContent), meaning: r.querySelector('.cp-read-x').textContent }; })()")
    assert read and read["pct"] == "60%" and read["tiles"] == ["RSI", "Stochastic", "6 of 10 gates"], read
    assert "Checklist completion, not win probability." in read["meaning"], read
    assert not visible(page, "#vxHint") and visible(page, "#cpModes") and visible(page, "#vxInput")
    page.evaluate("COPILOT.setMode('talk'); VOICE.close()")
    assert not session_requests, session_requests
    ok("phone: ARIA's card keeps its tabs and its mic + field in view; the provider chip opens the details; Analyze starts with the market read")


IPHONE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1"


def check_safari_bar(page, port):
    """When the page stops short of the screen's bottom (Safari's minimised tab bar keeps a strip; the
    Home Screen app on Joel's iPhone ends above the edge too) the home indicator sits in the system's
    strip, so the tab bar drops the inset it was carrying for nothing. A page as tall as the screen keeps it."""
    boot(page, port)
    assert page.evaluate("document.documentElement.dataset.theme") == "forest"
    assert page.evaluate("document.querySelector('meta[name=theme-color]').content") == "#03362e"
    assert page.evaluate("getComputedStyle(document.documentElement).backgroundColor") == "rgb(3, 54, 46)"
    short = page.evaluate("window.innerHeight <= screen.height - 34")
    sb = page.evaluate("document.documentElement.style.getPropertyValue('--safe-bottom')")
    nav = rect(page, ".mobile-nav")
    if short:
        assert sb == "0px" and abs(nav["h"] - 46) < 1 and abs(nav["b"] - page.evaluate("innerHeight")) < 1, (sb, nav)
        ok("iPhone, page shorter than the screen (Safari's strip, or the Home Screen app ending above the edge): the tab bar is 46px flush with the page's bottom, no dead inset; theme-color and canvas are the bar's deep green")
    else:
        assert sb == "", sb
        ok("iPhone, page as tall as the screen: the inset is left to iOS")


def check_desktop(page, port):
    boot(page, port)
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    assert not visible(page, "#mTf") and not visible(page, "#mExpand") and not visible(page, "#bsInsights") and not visible(page, "#mAcct") and not visible(page, ".vb-txt")
    assert visible(page, ".tf-btn") and page.evaluate("document.querySelector('.bstab.active').textContent.trim()") == "Scanner"
    assert page.evaluate("CH.candle.options().upColor") != "#FFFFFF"
    assert page.evaluate("document.querySelector('meta[name=theme-color]').content") == "#070B14" and page.evaluate("document.documentElement.style.getPropertyValue('--safe-bottom')") == ""
    page.evaluate("toggleTheme()"); page.wait_for_timeout(200)
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    page.evaluate("toggleTheme()")
    ok("laptop: dark and light themes as before; none of the phone shell shows")
    # a window narrowed to phone width and widened again comes back to the desktop dock and theme
    page.evaluate("toggleTheme()")                                   # light
    page.set_viewport_size({"width": 700, "height": 860}); page.wait_for_timeout(400)
    assert page.evaluate("document.documentElement.dataset.theme") == "forest"
    page.set_viewport_size({"width": 1280, "height": 860}); page.wait_for_timeout(400)
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    assert page.evaluate("document.querySelector('.bstab.active').dataset.tab") == "scanner" and not visible(page, "#bsInsights")
    page.evaluate("toggleTheme()")
    ok("laptop: crossing the phone breakpoint and back restores the theme and the Scanner tab")


def main():
    shots = sys.argv[1] if len(sys.argv) > 1 else None
    httpd = serve()
    port = httpd.server_address[1]
    args = ["--ignore-certificate-errors"]
    if PROXY:
        args += [f"--proxy-server={PROXY}", "--proxy-bypass-list=127.0.0.1;localhost;<local>"]
    with sync_playwright() as p:
        b = p.chromium.launch(args=args)
        for name, kw, fn in [("phone", dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True), lambda pg: check_phone(pg, port, shots)),
                             ("safari", dict(viewport={"width": 390, "height": 790}, screen={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True, has_touch=True, user_agent=IPHONE_UA), lambda pg: check_safari_bar(pg, port)),
                             ("installed", dict(viewport={"width": 390, "height": 844}, screen={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True, has_touch=True, user_agent=IPHONE_UA), lambda pg: check_safari_bar(pg, port)),
                             ("laptop", dict(viewport={"width": 1280, "height": 860}), lambda pg: check_desktop(pg, port))]:
            ctx = b.new_context(locale="en-US", timezone_id="UTC", **kw)
            page = ctx.new_page()
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            fn(page)
            assert not errs, errs
            ctx.close()
        b.close()
    httpd.shutdown()
    print("all forest shell checks passed")


if __name__ == "__main__":
    main()
