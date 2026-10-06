"""
Pending orders on the chart, tested in a real browser against
protrader_mobile.html.   LANG=en_US.UTF-8 python3 tests/test_order_levels_browser.py

A working limit order must be drawn at the price it was placed at — even
with other labels crowding the axis — and the trader must be able to drag it
to a new price (TradeLocker-style), with the paper book, the store and the
chart all agreeing. A drop on the wrong side of the market is refused.
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
  LIVE.routing = () => false; LIVE.on = false;
  Broker.latencyMs = 5;
  if (LEVELS.draft) LEVELS.discard(true); LEVELS.orderDraft = null;
  selectPair('R_75');
  const tf = TF_SEC[S.tf] || 900, t0 = Math.floor(Date.now() / 1000 / tf) * tf - 239 * tf;
  S.candles = Array.from({ length: 240 }, (_, i) => { const o = 44000 + Math.sin(i / 9) * 120, c = 44000 + Math.sin((i + 1) / 9) * 120;
    return { time: t0 + i * tf, open: o, high: Math.max(o, c) + 40, low: Math.min(o, c) - 40, close: c, vol: 0 }; });
  S.wsConnected = true; drawChart();
  // a fixed visible range so the test's prices are on screen and y is stable
  CH.candle.applyOptions({ autoscaleInfoProvider: () => ({ priceRange: { minValue: 43700, maxValue: 44500 } }) });
  return otSpec('R_75');
})()
"""

PLACE = """
(() => {
  OT.placePending({ symbol: 'R_75', side: '%s', orderType: '%s', volume: 0.16, price: %s, stopLoss: %s, takeProfit: %s, timeInForce: 'GTC', accountId: TR.acct.id });
  const o = TR.orders[TR.orders.length - 1];
  CH._levelSig = null; CH.refreshLevels(); LEVELS.render();
  return o.id;
})()
"""

# where the library drew the order line's axis label: the orange rows on the
# price-axis canvas (the label is drawn in the line's colour)
LABEL_Y = """
(() => {
  const cs = [...document.querySelectorAll('#chartWrap canvas')];
  const axes = cs.filter(c => { const r = c.getBoundingClientRect(); return r.height > 100 && r.left > cs[0].getBoundingClientRect().left + 100; });
  let rows = [];
  axes.forEach(c => { const ctx = c.getContext('2d'); const W = c.width, H = c.height, dpr = W / c.getBoundingClientRect().width;
    const img = ctx.getImageData(0, 0, W, H).data;
    for (let y = 0; y < H; y++) { let hit = 0; for (let x = 0; x < W; x += 2) { const k = (y * W + x) * 4; if (img[k] > 200 && img[k+1] > 120 && img[k+1] < 200 && img[k+2] < 80) hit++; } if (hit > 3) rows.push(y / dpr); } });
  rows.sort((a, b) => a - b);
  return rows.length ? (rows[0] + rows[rows.length - 1]) / 2 : null;
})()
"""


def run(page, js):
    return page.evaluate(js)


def place(page, side="sell", typ="limit", price="44300", sl="null", tp="null"):
    return run(page, PLACE % (side, typ, price, sl, tp))


def check_label_at_the_order_price(page):
    """With five other labels within a few pixels, the order's axis label and
    its pill still sit at the order's own price (no library re-stacking)."""
    run(page, SETUP)
    oid = place(page, "sell", "limit", "44300")
    run(page, """(() => { CH.addLine(44285, 'rgba(59,130,246,.9)', 'A'); CH.addLine(44292, 'rgba(59,130,246,.9)', 'B');
        CH.addLine(44306, 'rgba(59,130,246,.9)', 'C'); CH.addLine(44313, 'rgba(59,130,246,.9)', 'D'); CH.addLine(44320, 'rgba(59,130,246,.9)', 'E'); })()""")
    page.wait_for_timeout(500)
    r = run(page, f"""(() => {{ const y = CH.toY(44300); const e = LEVELS.els.get('ord:{oid}');
        const lay = LEVELS.layer.getBoundingClientRect(), b = e.getBoundingClientRect();
        return {{ y, pillY: b.top + b.height / 2 - lay.top, want: parseFloat(e.style.top), text: e.textContent, align: CH.chart.priceScale('right').options().alignLabels }}; }})()""")
    label_y = run(page, LABEL_Y)
    assert r["align"] is False, r
    assert label_y is not None and abs(label_y - r["y"]) <= 3, (label_y, r)        # the library's tag: at the price
    assert abs(r["want"] - r["y"]) <= 1, r                                         # the pill wants the same y
    assert "SELL LIMIT" in r["text"] and "44300" in r["text"], r
    run(page, "CH._levelSig = null; CH.refreshLevels()")


def check_pointer_drag_moves_the_order(page):
    """Pick the order pill up, drop it 60 points higher: the paper order, the
    chart line and the store all carry the new price; the pill follows."""
    run(page, SETUP)
    oid = place(page, "sell", "limit", "44300")
    page.wait_for_timeout(300)
    box = run(page, f"""(() => {{ LEVELS.render(); const e = LEVELS.els.get('ord:{oid}'); const r = e.getBoundingClientRect();
        return {{ x: r.left + 8, y: r.top + r.height / 2, y0: CH.toY(44300), y1: CH.toY(44360) }}; }})()""")
    page.mouse.move(box["x"], box["y"])
    page.mouse.down()
    page.mouse.move(box["x"], box["y"] + (box["y1"] - box["y0"]) / 2, steps=4)
    mid = run(page, f"""(() => {{ const o = TR.orders.find(x => x.id === {oid}); const l = CH._lineById.get('ord:{oid}');
        return {{ draft: LEVELS.orderDraft && LEVELS.orderDraft.price, saved: o.price, line: l && l.options().price }}; }})()""")
    assert mid["saved"] == 44300 and mid["draft"] is not None and abs(mid["draft"] - 44330) <= 1, mid   # mid-drag: draft moves, the order does not
    assert abs(mid["line"] - mid["draft"]) < 1e-6, mid                                                    # the dotted line follows the finger
    page.mouse.move(box["x"], box["y"] + (box["y1"] - box["y0"]), steps=4)
    page.mouse.up()
    page.wait_for_timeout(500)
    r = run(page, f"""(() => {{ const o = TR.orders.find(x => x.id === {oid});
        const st = JSON.parse(localStorage.getItem(TRADE_STORE_KEY)); const so = st.orders.find(x => x.id === {oid});
        const l = CH._lineById.get('ord:{oid}'); const e = LEVELS.els.get('ord:{oid}');
        return {{ price: o.price, state: o.state, stored: so && so.price, line: l && l.options().price, pillTop: parseFloat(e.style.top), y: CH.toY(o.price), draft: LEVELS.orderDraft, text: e.textContent }}; }})()""")
    assert abs(r["price"] - 44360) <= 0.6, r
    assert r["state"] == "working" and r["stored"] == r["price"] and abs(r["line"] - r["price"]) < 1e-6, r
    assert abs(r["pillTop"] - r["y"]) <= 1 and r["draft"] is None and str(int(r["price"])) in r["text"], r


def check_wrong_side_is_refused(page):
    """A sell limit dropped below the market would fill on the next tick: the
    drop is refused and the order stays where it was."""
    run(page, SETUP)
    oid = place(page, "sell", "limit", "44300")
    page.wait_for_timeout(300)
    box = run(page, f"""(() => {{ LEVELS.render(); const e = LEVELS.els.get('ord:{oid}'); const r = e.getBoundingClientRect();
        return {{ x: r.left + 8, y: r.top + r.height / 2, y0: CH.toY(44300), y1: CH.toY(43900) }}; }})()""")
    page.mouse.move(box["x"], box["y"]); page.mouse.down()
    page.mouse.move(box["x"], box["y"] + (box["y1"] - box["y0"]), steps=6)
    page.mouse.up()
    page.wait_for_timeout(500)
    r = run(page, f"""(() => {{ const o = TR.orders.find(x => x.id === {oid}); const l = CH._lineById.get('ord:{oid}');
        return {{ price: o.price, line: l && l.options().price, draft: LEVELS.orderDraft, toast: (document.querySelector('.toast, #toast') || {{}}).textContent || '' }}; }})()""")
    assert r["price"] == 44300 and abs(r["line"] - 44300) < 1e-6 and r["draft"] is None, r
    # the same rule for the other shapes, through the validator
    msgs = run(page, """(() => { const sp = otSpec('R_75'); const mk = (side, type, price) => ({ side, type, price, sl: null, tp: null, kind: 'paper' });
        return [LEVELS.checkOrder(mk('buy', 'limit', 44100), 44100), LEVELS.checkOrder(mk('buy', 'stop', 43900), 43900),
                LEVELS.checkOrder(mk('sell', 'stop', 44100), 44100), LEVELS.checkOrder(mk('buy', 'limit', 43900), 43900),
                LEVELS.checkOrder({ side: 'sell', type: 'limit', price: 44300, sl: 44350, tp: null, kind: 'paper' }, 44360)]; })()""")
    assert msgs[0] and msgs[1] and msgs[2], msgs          # buy limit above, buy stop below, sell stop above the market: refused
    assert msgs[3] == "", msgs                             # buy limit below the market: fine
    assert "stop" in msgs[4], msgs                         # a move past the order's own stop: refused


def check_keyboard_nudge_and_cancel(page):
    """Arrow keys move the order one tick (ten with shift); × cancels it and
    the pill and line disappear."""
    run(page, SETUP)
    oid = place(page, "buy", "stop", "44200")
    page.wait_for_timeout(300)
    r = run(page, f"""(() => {{ LEVELS.render(); const e = LEVELS.els.get('ord:{oid}'); e.focus();
        e.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'ArrowUp', bubbles: true }}));
        e.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'ArrowUp', shiftKey: true, bubbles: true }}));
        const o = TR.orders.find(x => x.id === {oid}); return {{ price: o.price, tick: otSpec('R_75').tick }}; }})()""")
    assert abs(r["price"] - (44200 + 11 * r["tick"])) < 1e-6, r
    r = run(page, f"""(() => {{ const e = LEVELS.els.get('ord:{oid}'); e.querySelector('.lvl-x').click();
        return new Promise(res => setTimeout(() => {{ LEVELS.render(); res({{ n: TR.orders.filter(x => x.id === {oid}).length, pill: !!LEVELS.els.get('ord:{oid}'), line: !!(CH._lineById && CH._lineById.get('ord:{oid}')) }}); }}, 300)); }})()""")
    assert r["n"] == 0 and r["pill"] is False and r["line"] is False, r


def check_mt5_orders_are_shown_but_not_dragged(page):
    """A pending order on the MT5 account is drawn at its price with a pill and
    a cancel, and a drag attempt explains that moving happens in MT5."""
    run(page, SETUP)
    run(page, """(() => { LIVE.on = true; LIVE.snap = () => ({ positions: [], orders: [{ ticket: 777, symbol: 'Volatility 75 Index', side: 'sell', kind: 'limit', volume: 0.2, price: 44320, sl: 0, tp: 0 }] });
        LIVE.mt5Symbol = () => 'Volatility 75 Index'; window.__cancelled = []; LIVE.cancelOrder = t => { window.__cancelled.push(t); };
        CH._levelSig = null; CH.refreshLevels(); LEVELS.render(); })()""")
    page.wait_for_timeout(300)
    r = run(page, """(() => { const e = LEVELS.els.get('mt5ord:777'); const l = CH._lineById.get('mt5ord:777');
        return { pill: !!e, static: e && e.classList.contains('is-static'), top: e && parseFloat(e.style.top), y: CH.toY(44320), line: l && l.options().price, text: e && e.textContent }; })()""")
    assert r["pill"] and r["static"] and abs(r["top"] - r["y"]) <= 1 and abs(r["line"] - 44320) < 1e-6 and "SELL LIMIT" in r["text"], r
    box = run(page, "(() => { const e = LEVELS.els.get('mt5ord:777'); const r = e.getBoundingClientRect(); return { x: r.left + 8, y: r.top + r.height / 2 }; })()")
    page.mouse.move(box["x"], box["y"]); page.mouse.down(); page.mouse.move(box["x"], box["y"] + 40, steps=3); page.mouse.up()
    page.wait_for_timeout(300)
    r = run(page, "(() => ({ draft: LEVELS.orderDraft, drag: LEVELS.drag, line: CH._lineById.get('mt5ord:777').options().price }))()")
    assert r["draft"] is None and r["drag"] is None and abs(r["line"] - 44320) < 1e-6, r
    run(page, "(() => { LEVELS.els.get('mt5ord:777').querySelector('.lvl-x').click(); })()")
    assert run(page, "window.__cancelled") == ["777"]
    run(page, "LIVE.on = false; CH._levelSig = null; CH.refreshLevels(); LEVELS.render()")


def main():
    httpd = serve()
    port = httpd.server_address[1]
    args = ["--ignore-certificate-errors"]
    if PROXY:
        args += [f"--proxy-server={PROXY}", "--proxy-bypass-list=127.0.0.1;localhost;<local>"]
    with sync_playwright() as p:
        b = p.chromium.launch(args=args)
        page = b.new_context(locale="en-US", timezone_id="UTC", ignore_https_errors=True, viewport={"width": 1280, "height": 800}).new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(f"http://127.0.0.1:{port}/protrader_mobile.html", wait_until="domcontentloaded")
        page.wait_for_function("typeof OT !== 'undefined' && typeof LEVELS !== 'undefined' && CH.ready")
        page.wait_for_timeout(1500)
        checks = [
            ("label and pill sit at the order price", check_label_at_the_order_price),
            ("pointer drag moves the order", check_pointer_drag_moves_the_order),
            ("wrong side is refused", check_wrong_side_is_refused),
            ("keyboard nudge and cancel", check_keyboard_nudge_and_cancel),
            ("MT5 orders shown, not dragged", check_mt5_orders_are_shown_but_not_dragged),
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
    print("all order-level browser checks passed")


if __name__ == "__main__":
    main()
