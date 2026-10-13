"""
The phone shell ("forest"), tested in a real browser against protrader_mobile.html.

A phone gets the deep-green theme, the two-row header, the white chart card with a
timeframe menu and Expand, the Insights · Positions · Orders sheet fed by ARIA,
ORACLE and Sentinel, and the four-tab bar. Desktop keeps its own themes, pixel for
pixel. The feed is replaced by fixed candles, so every number is exact.
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


# fixed candles with a clear bearish engulfing near the end, so the scanner has something to find
SETUP = """
(() => {
  selectPair('R_50'); if (S.tf !== '1h') MOB.pickTf('1h');
  const tf = 3600, t0 = Math.floor(Date.now() / 1000 / tf) * tf - 239 * tf;
  let p = 80, k = 7; const rnd = () => { k = (k * 9301 + 49297) % 233280; return k / 233280; };
  S.candles = Array.from({ length: 240 }, (_, i) => { const o = p, c = p + Math.sin(i / 7) * 0.35 + (rnd() - 0.5) * 0.4; p = c;
    return { time: t0 + i * tf, open: o, high: Math.max(o, c) + rnd() * 0.25, low: Math.min(o, c) - rnd() * 0.25, close: c, vol: 0 }; });
  S.wsConnected = true;
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
    page.goto(f"http://127.0.0.1:{port}/protrader_mobile.html", wait_until="domcontentloaded")
    page.wait_for_function("typeof MOB !== 'undefined' && typeof OT !== 'undefined' && typeof CH !== 'undefined' && CH.ready")
    page.wait_for_timeout(800)
    page.evaluate(SETUP)
    page.wait_for_timeout(600)


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
    assert any(r.startswith(("Leaning", "Wait", "Stand aside")) for r in rows) and any(r in ("Strong signal", "Moderate signal", "Weak · standby") for r in rows), rows
    badges = page.evaluate("[...document.querySelectorAll('#insightsPane .mi-full .mi-sec:last-of-type ~ .mi-row .mi-bd')].map(b => b.textContent)")
    assert badges[: len(marks)] == marks, (badges, marks)
    ok(f"phone: the sheet opens on the grip; {n} insights in ARIA · ORACLE · Patterns sections, patterns numbered like the chart")
    if shots:
        page.screenshot(path=os.path.join(shots, "forest_insights_up.png"))

    # filters, and the ORACLE row carries the Oracle tab's confidence (gates passed ÷ gates), its direction and levels
    page.evaluate("MOB.setFilter('oracle')")
    assert page.evaluate("document.querySelectorAll('#insightsPane .mi-full .mi-row').length") == 1
    o = page.evaluate("(() => { const r = document.querySelector('#insightsPane .mi-full .mi-row'); return { head: r.querySelector('.mi-h').firstChild.textContent, tag: r.querySelector('.mi-tag').textContent, sub: r.querySelector('.mi-p').textContent, act: r.querySelector('.mi-act').textContent, badge: r.querySelector('.mi-bd').textContent }; })()")
    conf = page.evaluate("checkModel().oracle")
    assert o["tag"] == f"{conf}%" and o["badge"] == "O", (o, conf)
    assert o["head"] == ("Strong signal" if conf >= 70 else "Moderate signal" if conf >= 50 else "Weak · standby"), (o, conf)
    assert o["sub"].startswith(("▲ Buy · entry ", "▼ Sell · entry ")) and " · stop " in o["sub"], o
    assert o["act"] == ("Use signal" if conf >= 70 else "Open Oracle"), o
    page.evaluate("MOB.setFilter('all')")
    ok(f"phone: filter chips narrow the list; the ORACLE row says '{o['head']}' at {conf}% with the direction, entry and stop")

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

    # the drawing sheet sits above the tab bar, in the forest palette, without keyboard hints
    page.tap("#chartTools"); page.wait_for_timeout(300)
    d = page.evaluate("(() => { const s = document.getElementById('dtSheet'); const r = s.getBoundingClientRect(); const nav = document.querySelector('.mobile-nav'); return { z: +getComputedStyle(s).zIndex, navZ: +getComputedStyle(nav).zIndex, bg: getComputedStyle(s).backgroundColor, kbd: [...s.querySelectorAll('kbd')].some(k => k.getBoundingClientRect().width > 0), top: document.elementFromPoint(20, r.bottom - 8)?.closest('#dtSheet') != null }; })()")
    assert d["z"] > d["navZ"] and d["bg"] != "rgb(13, 19, 32)" and not d["kbd"] and d["top"], d
    page.evaluate("DT.closeSheet()")
    ok("phone: the drawing sheet opens above the tab bar in the forest palette, no shortcut badges")

    # the check panel counts every gate; the ticket's switches follow a fill; a capped size is worded honestly
    page.evaluate("openMobilePanel('check')"); page.wait_for_timeout(300)
    cnt = page.evaluate("document.querySelector('#check-panel .chk-cnt').textContent")
    n_gates = page.evaluate("checkModel().gates.gates.length")
    assert cnt == f"{page.evaluate('checkModel().gates.score')} of {n_gates}" and n_gates == page.evaluate("ARIA_GATE_COUNT"), (cnt, n_gates)
    assert page.evaluate("document.getElementById('chkMoreToggle').textContent") == f"Show {n_gates - 5} more checks ▾"
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

    # ARIA's floating card still opens over the forest shell
    page.evaluate("VOICE.open(false)"); page.wait_for_timeout(400)
    r = rect(page, ".vx-sheet")
    assert r and r["l"] >= 0 and r["r"] <= 390
    page.evaluate("VOICE.close()")
    ok("phone: ARIA's floating card opens inside the screen")


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
