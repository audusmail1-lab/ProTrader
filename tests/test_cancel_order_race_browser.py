"""
Cancelling a pending order must never claim success for an order that
filled while the cancel was in flight, tested in a real browser against
protrader_mobile.html.   python3 tests/test_cancel_order_race_browser.py

Broker.cancel() carries artificial latency; a live tick can fill the same
order via OT.checkPending() during that window (it runs synchronously off
the quote stream, no latency). OT.cancelOrder() must notice the order is
gone by the time its own await resolves, instead of reporting "Cancelled"
over a fill the user now holds as an open position.
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
  Broker.latencyMs = 160;   // real-sized: this is the window the race exploits
  localStorage.removeItem('protrader.autoprotect.v1'); AUTOP.cfg = null; AUTOP.pick('off');
  selectPair('R_75');
  const tf = TF_SEC[S.tf] || 900, t0 = Math.floor(Date.now() / 1000 / tf) * tf - 239 * tf;
  S.candles = Array.from({ length: 240 }, (_, i) => { const o = 44000 + Math.sin(i / 9) * 120, c = 44000 + Math.sin((i + 1) / 9) * 120;
    return { time: t0 + i * tf, open: o, high: Math.max(o, c) + 40, low: Math.min(o, c) - 40, close: c, vol: 0 }; });
  S.wsConnected = true; drawChart();
  return otSpec('R_75');
})()
"""


def run(page, js):
    return page.evaluate(js)


def check_fill_during_cancel_is_not_overwritten(page):
    """A tick fills the order after Broker.cancel() is already in flight:
    the fill must survive, and the toast must say so instead of "Cancelled"."""
    run(page, SETUP)
    r = run(page, """(async () => {
        TR.orders = [{ id: 501, symbol: 'R_75', label: 'Vol 75', side: 'buy', orderType: 'limit',
                       volume: 0.2, price: 44000, sl: null, tp: null, state: 'working',
                       placed: Date.now(), accountId: TR.acct.id }];
        window.__px = 44050;                 // above the limit: not triggered yet
        const cancelP = OT.cancelOrder(501);  // Broker.cancel() is now in flight (160ms)
        window.__px = 43990;                 // a tick arrives mid-cancel and fills the limit
        OT.checkPending('R_75');
        const filledDuringCancel = TR.orders.length === 0 && TR.positions.length === 1;
        await cancelP;
        return {
          filledDuringCancel,
          ordersLeft: TR.orders.length,
          positionsLeft: TR.positions.length,
          toast: document.getElementById('voiceText').textContent,
        };
      })()""")
    assert r["filledDuringCancel"], r              # the fill really did land before the cancel resolved
    assert r["ordersLeft"] == 0, r
    assert r["positionsLeft"] == 1, r              # the fill must survive the cancel, not be wiped out
    assert "already filled" in r["toast"], r
    assert "Cancelled" not in r["toast"], r


def check_genuine_cancel_still_works(page):
    """No race: cancelling a still-working order behaves as before."""
    run(page, SETUP)
    r = run(page, """(async () => {
        TR.orders = [{ id: 502, symbol: 'R_75', label: 'Vol 75', side: 'sell', orderType: 'stop',
                       volume: 0.1, price: 43000, sl: null, tp: null, state: 'working',
                       placed: Date.now(), accountId: TR.acct.id }];
        window.__px = 44000;                 // nowhere near the stop: never triggers
        await OT.cancelOrder(502);
        return { ordersLeft: TR.orders.length, toast: document.getElementById('voiceText').textContent };
      })()""")
    assert r["ordersLeft"] == 0, r
    assert "Cancelled SELL STOP" in r["toast"], r


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
        page.wait_for_function("typeof OT !== 'undefined' && CH.ready")
        page.wait_for_timeout(1500)
        checks = [
            ("a fill mid-cancel is not overwritten", check_fill_during_cancel_is_not_overwritten),
            ("a genuine cancel still works", check_genuine_cancel_still_works),
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
    print("all cancel-order race browser checks passed")


if __name__ == "__main__":
    main()
