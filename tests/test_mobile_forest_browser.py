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

    # rising candles are hollow, the EMA is violet, the markers are numbered
    opts = page.evaluate("({ up: CH.candle.options().upColor, border: CH.candle.options().borderVisible, ema: CH.ema20.options().color, spacing: CH.chart.timeScale().options().barSpacing })")
    assert opts == {"up": "#FFFFFF", "border": True, "ema": "#7c9193", "spacing": 4}, opts
    marks = page.evaluate("S.activePatterns.slice(0, 3).map((p, i) => String(i + 1))")
    assert len(marks) >= 1 and page.evaluate("BADGES.items.map(b => b.label)") == marks
    assert page.evaluate("!!document.querySelector('.ohlc-bar .m-eye')") and not visible(page, ".ohlc-bar .ohlc-item")
    page.tap(".ohlc-bar .m-eye"); page.wait_for_timeout(150)
    assert page.evaluate("!S.ind.ema && !CH.ema20.options().visible")
    page.tap(".ohlc-bar .m-eye"); page.wait_for_timeout(150)
    assert page.evaluate("S.ind.ema && CH.ema20.options().visible")
    ok(f"phone: hollow rising candles, a thin grey EMA with an eye toggle, {len(marks)} numbered badge(s) drawn in the chart")

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
    assert secs == ["ARIA", "ORACLE", "Sentinel"], secs
    rows = page.evaluate("[...document.querySelectorAll('#insightsPane .mi-full .mi-row .mi-h')].map(h => h.firstChild.textContent)")
    assert any(r.startswith(("Leaning", "Wait", "Stand aside")) for r in rows) and "Plan incomplete" in rows, rows
    badges = page.evaluate("[...document.querySelectorAll('#insightsPane .mi-full .mi-sec:last-of-type ~ .mi-row .mi-bd')].map(b => b.textContent)")
    assert badges[: len(marks)] == marks, (badges, marks)
    ok(f"phone: the sheet opens on the grip; {n} insights in ARIA · ORACLE · Sentinel sections, patterns numbered like the chart")
    if shots:
        page.screenshot(path=os.path.join(shots, "forest_insights_up.png"))

    # filters, and the ORACLE row reads the ticket
    page.evaluate("MOB.setFilter('oracle')")
    assert page.evaluate("document.querySelectorAll('#insightsPane .mi-full .mi-row').length") == 1
    page.evaluate("TK.slOn = true; TK.sl = S.candles[S.candles.length - 1].close - 0.6; TK.tpOn = true; TK.tp = S.candles[S.candles.length - 1].close + 1.2; TK.side = 'buy'; MOB.insights.render()")
    head = page.evaluate("document.querySelector('#insightsPane .mi-full .mi-row .mi-h').firstChild.textContent")
    assert head in ("Plan supported", "Plan incomplete", "Plan contradicted"), head
    page.evaluate("TK.slOn = false; TK.tpOn = false; MOB.setFilter('all')")
    ok(f"phone: filter chips narrow the list; with a stop and target on the ticket ORACLE says '{head}'")

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
    page.tap(".mobile-nav-btn[data-mobile-view='journal']")
    page.wait_for_timeout(400)
    assert page.evaluate("MOB.sheet.isUp() && document.querySelector('.bstab.active').dataset.tab === 'journal'")
    assert visible(page, ".bstab[data-tab='journal']") and not visible(page, "#bsInsights")
    assert page.evaluate("document.querySelector('.mobile-nav-btn.active').dataset.mobileView") == "journal"
    page.tap(".mobile-nav-btn[data-mobile-view='chart']")
    page.wait_for_timeout(300)
    assert page.evaluate("document.querySelector('.bstab.active').dataset.tab") == "insights" and visible(page, "#bsInsights")
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
    ok("phone: Journal opens in the sheet, Portfolio shows the account card (guest → sign in), Markets opens the picker")

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


def check_desktop(page, port):
    boot(page, port)
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    assert not visible(page, "#mTf") and not visible(page, "#mExpand") and not visible(page, "#bsInsights") and not visible(page, "#mAcct") and not visible(page, ".vb-txt")
    assert visible(page, ".tf-btn") and page.evaluate("document.querySelector('.bstab.active').textContent.trim()") == "Scanner"
    assert page.evaluate("CH.candle.options().upColor") != "#FFFFFF"
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
