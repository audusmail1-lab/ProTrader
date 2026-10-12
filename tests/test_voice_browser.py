"""
PROTrader Voice, tested in a real browser against protrader_mobile.html.
Speech recognition and speech synthesis are replaced by fakes, so every
spoken command is driven exactly; quotes are pinned so every number is exact.
   python3 tests/test_voice_browser.py
"""
import functools
import http.server
import json
import os
import socketserver
import tempfile
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


SETUP = """
(() => {
  S.balance = 10000; S.riskPct = 1; S.trades = []; S.pnlToday = 0;
  TR.positions = []; TR.orders = [];
  window.__px = 44000;
  otQuote = id => ({ ok: true, stale: false, bid: window.__px, ask: window.__px, last: window.__px, mid: window.__px, hasSpread: false });
  LIVE.routing = () => false;
  localStorage.removeItem('protrader.autoprotect.v1'); AUTOP.cfg = null;
  selectPair('R_75');
  const tf = 900, t0 = Math.floor(Date.now() / 1000 / tf) * tf - 239 * tf;
  S.candles = Array.from({ length: 240 }, (_, i) => { const o = 44000 + Math.sin(i / 9) * 120, c = 44000 + Math.sin((i + 1) / 9) * 120;
    return { time: t0 + i * tf, open: o, high: Math.max(o, c) + 40, low: Math.min(o, c) - 40, close: c, vol: 0 }; });
  S.wsConnected = true;
  // speech out: record every utterance, finish it at once
  window.__said = [];
  window.speechSynthesis.speak = u => { window.__said.push(u.text); setTimeout(() => u.onend && u.onend(), 5); };
  window.speechSynthesis.cancel = () => {};
  window.speechSynthesis.getVoices = () => [];
  // speech in: a fake recognizer the test drives
  window.__recs = [];
  class FakeRec {
    constructor() { window.__recs.push(this); }
    start() { setTimeout(() => this.onstart && this.onstart(), 1); }
    abort() { setTimeout(() => this.onend && this.onend(), 1); }
    stop() { this.abort(); }
    say(text) {
      this.onresult && this.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: text.slice(0, 6) }], { isFinal: false })] });
      this.onresult && this.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: text }, { transcript: text + ' x' }], { isFinal: true })] });
      setTimeout(() => this.onend && this.onend(), 1);
    }
    fail(err) { this.onerror && this.onerror({ error: err }); setTimeout(() => this.onend && this.onend(), 1); }
  }
  window.SpeechRecognition = FakeRec;
  VOICE.cfg = { talk: true, announce: false, lang: 'en-NG', voice: '', handsFree: false, rate: 1 };
  return true;
})()
"""


def run(page, js):
    return page.evaluate(js)


def talk(page, text, wait=700):
    """Tap the orb, say `text`, wait for the reply; returns what the assistant said."""
    page.evaluate("window.__said = []")
    page.evaluate("VOICE.state === 'listening' || VOICE.listen()")
    page.wait_for_function("window.__recs.length && VOICE.state === 'listening'", timeout=5000)
    page.evaluate(f"window.__recs[window.__recs.length - 1].say({json.dumps(text)})")
    page.wait_for_function("window.__said.length > 0 && VOICE.state !== 'thinking'", timeout=8000)
    page.wait_for_timeout(wait)
    return " ".join(page.evaluate("window.__said"))


def typed(page, text, wait=700):
    page.evaluate("window.__said = []")
    page.fill("#vxInput", text)
    page.press("#vxInput", "Enter")
    page.wait_for_function("window.__said.length > 0 && VOICE.state !== 'thinking'", timeout=8000)
    page.wait_for_timeout(wait)
    return " ".join(page.evaluate("window.__said"))


def check_parse(page):
    cases = {
        "Buy gold, 1% risk, stop at 2,640, target two to one": {"intent": "order", "sym": "frxXAUUSD", "side": "buy", "riskPct": 1, "stop": {"price": 2640}, "target": {"rr": 2}},
        "sell NAS100 0.5 lots stop 50 points": {"intent": "order", "sym": "frxNAS100", "side": "sell", "lots": 0.5, "stop": {"dist": 50, "unit": "points"}},
        "go long volatility 75 one second half a lot stop loss 3200": {"intent": "order", "sym": "1HZ75V", "lots": 0.5, "stop": {"price": 3200}},
        "buy stop 2660 stop loss 2640": {"intent": "order", "type": "stop", "price": 2660, "stop": {"price": 2640}},
        "close the long position": {"intent": "close", "side": "buy"},
        "close half of NAS": {"intent": "close", "sym": "frxNAS100", "half": True},
        "move my gold stop to breakeven": {"intent": "breakeven", "sym": "frxXAUUSD"},
        "move my stop to 2650": {"intent": "move_stop", "price": 2650},
        "should I buy gold": {"intent": "aria", "sym": "frxXAUUSD"},
        "show me vol 75 one second on the 4 hour": {"intent": "switch", "sym": "1HZ75V", "tf": "4h"},
        "what's the S&P at": {"intent": "price", "sym": "frxSPX500"},
        "how much am I risking": {"intent": "risk"},
        "never mind": {"intent": "cancel"},
    }
    for phrase, want in cases.items():
        got = run(page, f"VOICE.parse({json.dumps(phrase)})")
        for k, v in want.items():
            assert got.get(k) == v, (phrase, k, got)
    assert run(page, "vxNorm('two thousand six hundred and forty, one point five')").split() == ["2640", "1.5"]
    # "confirm" is only a confirmation while something is waiting for one
    assert run(page, "(VOICE.pending = null, VOICE.parse('yes').intent)") != "confirm"


def check_order_by_voice(page):
    run(page, "VOICE.open(false)")
    out = talk(page, "buy volatility 75, one percent risk, stop at 43,500, target two to one")
    # 1% of $10,000 = $100 at a stop 500 points away -> 0.2 lots; target 2R = 45,000
    assert "Buy 0.2 lots of Vol 75" in out and "risks $100" in out and "Target 45000" in out.replace(",", "") and "Say confirm" in out, out
    card = page.inner_text("#vxCard")
    assert "Buy 0.2 Vol 75" in card and "Paper" in card, card
    assert run(page, "TR.positions.length") == 0                               # nothing placed yet
    out = talk(page, "confirm")
    p = run(page, "TR.positions[0]")
    assert p and p["side"] == "buy" and p["volume"] == 0.2 and p["sl"] == 43500 and p["tp"] == 45000, p
    assert "Done. Bought 0.2 lots of Vol 75" in out and "worst case $100" in out, out
    assert run(page, "document.getElementById('vxCard').hidden")


def check_breakeven_is_honest(page):
    out = talk(page, "move my stop to breakeven")
    assert "spread" in out and run(page, "TR.positions[0].sl") == 43500, out   # not in profit: says so, nothing moved
    run(page, "window.__px = 44600")
    out = talk(page, "breakeven")
    # at entry (or above it already: auto-protect may trail it on from +1R)
    assert run(page, "TR.positions[0].sl") >= 44000 and "stop moved to entry, 44000" in out and "can no longer lose" in out, out


def check_rules_hold(page):
    out = talk(page, "sell volatility 75, 3 lots, stop 44,900")
    # 3 lots x 300 points = $900: over the 1% plan -> the coach, with a fix
    assert "more than your 1% plan" in out and "fix it" in out, out
    out = talk(page, "fix it")
    assert "Sell 0.33 lots of Vol 75" in out and "risks $99" in out, out          # price is 44,600 now: 300 points to the stop
    out = talk(page, "cancel")
    assert "Cancelled" in out and run(page, "TR.positions.length") == 1, out
    out = talk(page, "sell volatility 75, 2 percent risk, stop 44,900")
    assert "caps a trade at 1 percent" in out and "Sell 0.33 lots" in out, out
    talk(page, "confirm")
    assert run(page, "TR.positions.length") == 2 and run(page, "TR.positions[1].side") == "sell"


def check_questions(page):
    out = talk(page, "what's my risk")
    assert "$99" in out and "of your 2 percent cap of $200" in out, out      # the short holds 0.33 x 300; the long is protected
    out = talk(page, "how are my trades")
    assert "2 open trades" in out and "Vol 75 long 0.2 lots, up $120, that's 1.2 R, stop " in out and ("stop at breakeven" in out or "stop 44100, trailing" in out) and "Vol 75 short 0.33 lots, flat" in out, out
    out = talk(page, "balance")
    assert "Paper balance $10,000" in out, out
    out = talk(page, "what does ARIA say")
    assert "ARIA on Vol 75" in out and "of 10 gates" in out and "not a trade" in out, out
    out = talk(page, "brief me", wait=1200)
    assert "Paper balance" in out and "Risk in use" in out and "Vol 75 is" in out, out


def check_close(page):
    out = talk(page, "close all")
    assert "Close all 2 trades" in out and "Say confirm" in out, out
    talk(page, "cancel")
    assert run(page, "TR.positions.length") == 2
    out = talk(page, "close the long position")
    assert "Close your Vol 75 long" in out, out
    out = talk(page, "confirm")
    assert run(page, "TR.positions.length") == 1 and run(page, "TR.positions[0].side") == "sell" and "Vol 75 closed" in out, out


def check_expiry(page):
    talk(page, "close all")
    run(page, "VOICE.pending.expires = Date.now() - 1")
    out = talk(page, "confirm")
    assert "expired" in out and run(page, "TR.positions.length") == 1, out


def check_mt5_needs_a_tap(page):
    run(page, """(() => {
      window.__mt5 = [];
      LIVE.routing = () => true; LIVE.validate = () => ({}); LIVE.acct = () => ({ equity: 10000, balance: 10000, mode: 'demo' });
      LIVE.snap = () => ({ positions: [{ ticket: '77', symbol: LIVE.mt5Symbol('R_75'), side: 'buy', volume: 0.2, entry: 44000, price: 44600, sl: 43500, tp: 0, profit: 120 }] });
      LIVE.sizeToRisk = () => { OT.setLots(0.2); };
      LIVE.place = async order => { window.__mt5.push(['place', order]); };
      LIVE.breakeven = async t => { window.__mt5.push(['breakeven', t]); };
      LIVE.closePosition = async t => { window.__mt5.push(['close', t]); };
      window.__paperSubmits = 0; const orig = Broker.submit.bind(Broker); Broker.submit = o => { window.__paperSubmits++; return orig(o); };
    })()""")
    out = talk(page, "buy volatility 75 stop 43,500")
    assert "This goes to MT5" in out and "tap to send" in out, out
    out = talk(page, "confirm")
    calls = run(page, "window.__mt5")
    assert calls and calls[0][0] == "place" and run(page, "window.__paperSubmits") == 0 and "Tap it to send" in out, (calls, out)
    talk(page, "breakeven")
    assert run(page, "window.__mt5")[-1] == ["breakeven", "77"]
    talk(page, "close my trade")
    assert run(page, "window.__mt5")[-1] == ["close", "77"]
    run(page, "LIVE.routing = () => false")


def check_mt5_multi_position(page):
    """A command that matches more than one MT5 position must act on all of
    them (never silently only the first), and a filtered command (by symbol
    or side) must never widen into LIVE.closeAll() unless "all"/"everything"
    was said with no symbol filter."""
    run(page, """(() => {
      window.__mt5 = [];
      LIVE.routing = () => true; LIVE.validate = () => ({}); LIVE.acct = () => ({ equity: 10000, balance: 10000, mode: 'demo' });
      LIVE.snap = () => ({ positions: [
        { ticket: '101', symbol: LIVE.mt5Symbol('R_75'), side: 'buy', volume: 0.2, entry: 44000, price: 44600, sl: 43500, tp: 0, profit: 120 },
        { ticket: '202', symbol: LIVE.mt5Symbol('frxXAUUSD'), side: 'buy', volume: 0.1, entry: 1900, price: 1920, sl: 1850, tp: 0, profit: 80 },
        { ticket: '303', symbol: LIVE.mt5Symbol('frxXAUUSD'), side: 'sell', volume: 0.1, entry: 1950, price: 1920, sl: 2000, tp: 0, profit: 30 },
      ] });
      LIVE.breakeven = async t => { window.__mt5.push(['breakeven', t]); };
      LIVE.closePosition = async t => { window.__mt5.push(['close', t]); };
      LIVE.closeAll = async () => { window.__mt5.push(['closeAll']); };
    })()""")
    talk(page, "breakeven everything")
    calls = run(page, "window.__mt5")
    assert ["breakeven", "101"] in calls and ["breakeven", "202"] in calls and ["breakeven", "303"] in calls, calls

    run(page, "window.__mt5 = []")
    # matches tickets 202 and 303 (the Gold positions) out of 3 open trades: must close only those two.
    talk(page, "close all my gold")
    assert run(page, "window.__mt5") == [["close", "202"], ["close", "303"]], run(page, "window.__mt5")

    run(page, "window.__mt5 = []")
    talk(page, "close everything")
    assert run(page, "window.__mt5") == [["closeAll"]], run(page, "window.__mt5")
    run(page, "LIVE.routing = () => false")


def check_without_speech(page):
    run(page, "VOICE.close(); delete window.SpeechRecognition; delete window.webkitSpeechRecognition; VOICE.open(true)")
    assert "no speech input" in page.inner_text("#vxHeard")
    out = typed(page, "price of vol 75")
    assert "Vol 75 is 44600" in out.replace(",", ""), out
    # the iPhone home-screen app has no speech input: the reason is named
    run(page, """(() => { VOICE.close(); window.SpeechRecognition = class { constructor(){ window.__recs.push(this); } start(){ setTimeout(() => { this.onerror({ error: 'service-not-allowed' }); this.onend(); }, 1); } abort(){} };
      VOICE.isIOS = true; VOICE.open(true); })()""")
    page.wait_for_function("/home-screen app/.test(document.getElementById('vxHeard').textContent)", timeout=4000)
    run(page, "VOICE.isIOS = false; VOICE.close()")


def check_phone(p, port, args):
    b = p.chromium.launch(args=args)
    ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(f"http://127.0.0.1:{port}/protrader_mobile.html", wait_until="domcontentloaded")
    page.wait_for_function("typeof VOICE !== 'undefined' && typeof OT !== 'undefined'")
    page.wait_for_timeout(1200)
    run(page, SETUP)
    box = page.locator("#voiceBtn").bounding_box()
    assert box and box["width"] > 0 and box["x"] + box["width"] <= 390, box               # the mic is on the phone's top bar
    page.locator("#voiceBtn").tap()
    page.wait_for_function("window.__recs.length && VOICE.state === 'listening'", timeout=4000)
    page.evaluate("window.__recs[window.__recs.length - 1].say('buy volatility 75 one percent risk stop 43,500 target two to one')")
    page.wait_for_selector("#vxCard:not([hidden])", timeout=6000)
    page.wait_for_timeout(600)
    assert page.evaluate("document.documentElement.scrollWidth") <= 392
    sheet = page.locator(".vx-sheet").bounding_box()
    assert sheet["x"] >= 0 and sheet["x"] + sheet["width"] <= 391 and sheet["y"] >= 0, sheet
    page.screenshot(path=os.path.join(tempfile.gettempdir(), "voice_phone.png"))
    assert not errs, errs
    b.close()


def main():
    httpd = serve()
    port = httpd.server_address[1]
    args = ["--ignore-certificate-errors"]
    if PROXY:
        args += [f"--proxy-server={PROXY}", "--proxy-bypass-list=127.0.0.1;localhost;<local>"]
    with sync_playwright() as p:
        b = p.chromium.launch(args=args)
        page = b.new_context(locale="en-US", timezone_id="UTC", viewport={"width": 1280, "height": 860}).new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(f"http://127.0.0.1:{port}/protrader_mobile.html", wait_until="domcontentloaded")
        page.wait_for_function("typeof VOICE !== 'undefined' && typeof OT !== 'undefined' && typeof AUTOP !== 'undefined'")
        page.wait_for_timeout(1500)
        run(page, SETUP)
        for name, fn in [("parser", check_parse), ("an order by voice, confirmed by voice", check_order_by_voice),
                         ("breakeven tells the truth", check_breakeven_is_honest), ("the risk rules hold", check_rules_hold),
                         ("questions", check_questions), ("closing asks first", check_close), ("a plan expires", check_expiry),
                         ("MT5 always needs a tap", check_mt5_needs_a_tap), ("MT5 commands cover every matched position", check_mt5_multi_position),
                         ("no speech input: typing works", check_without_speech)]:
            fn(page)
            print(f"ok  {name}")
        page.screenshot(path=os.path.join(tempfile.gettempdir(), "voice_desktop.png"))
        assert not errs, errs
        b.close()
        check_phone(p, port, args)
        print("ok  phone: mic on the top bar, sheet fits, no sideways scroll")
    httpd.shutdown()
    print("all voice checks passed")


if __name__ == "__main__":
    main()
