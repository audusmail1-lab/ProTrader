"""
ARIA as a floating widget, tested in a real browser against protrader_mobile.html.

ARIA floats above the app instead of covering it: the header drags it, the drag is bounded to
the usable screen (less the notch, the home bar and the phone's tab bar), it snaps flush to an
edge it is dropped near, minimise leaves a draggable bubble that shows what ARIA is doing, the
position and the open/minimised state last for the browser session, and a conversation (a
listening microphone, the log) carries on while the chart and the order ticket are used.
Speech recognition is a fake the test drives, so nothing reaches a real microphone.
   python3 tests/test_aria_float_browser.py
"""
import functools
import http.server
import json
import os
import socketserver
import sys
import tempfile
import threading

from playwright.sync_api import sync_playwright

ROOT = os.path.join(os.path.dirname(__file__), "..")
PROXY = os.environ.get("HTTPS_PROXY", "")
KEY = "protrader.aria.float.v1"


def serve():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    httpd = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


# a fake microphone: records whether it was started or aborted, never hears anything by itself
SETUP = """
(() => {
  window.__recs = [];
  class FakeRec {
    constructor() { this.aborted = false; window.__recs.push(this); }
    start() { setTimeout(() => this.onstart && this.onstart(), 1); }
    abort() { this.aborted = true; setTimeout(() => this.onend && this.onend(), 1); }
    stop() { this.abort(); }
  }
  window.SpeechRecognition = FakeRec; window.webkitSpeechRecognition = FakeRec;
  window.speechSynthesis.speak = u => setTimeout(() => u.onend && u.onend(), 5);
  VOICE.cfg = Object.assign(VOICE.cfg || {}, { talk: false, handsFree: false });
  return true;
})()
"""


def ok(msg):
    print("ok ", msg)


def rect(page, sel):
    return page.evaluate(f"(() => {{ const r = document.querySelector({json.dumps(sel)}).getBoundingClientRect(); return {{ l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height }}; }})()")


def bounds(page):
    return page.evaluate("VXF.bounds()")


def visible(page, sel):
    return page.evaluate(f"(() => {{ const e = document.querySelector({json.dumps(sel)}); return !!e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().width > 0; }})()")


def stored(page):
    return page.evaluate(f"JSON.parse(sessionStorage.getItem('{KEY}') || 'null')")


CALM = """Promise.all(document.getAnimations().filter(a => {
  const t = a.effect && a.effect.target; const n = a.effect && a.effect.getTiming().iterations;
  return t && t.closest && t.closest('#vxSheet') && n !== Infinity; }).map(a => a.finished.catch(() => null))).then(() => true)"""


def calm(page):
    """Wait until ARIA's finite animations (rise, pop, snap glide) have finished; slow machines run them slowly."""
    page.wait_for_timeout(60)
    page.evaluate(CALM)
    page.wait_for_timeout(40)


def settle(page):
    page.wait_for_timeout(300)                    # past the snap animation (it starts after the release)
    calm(page)


def mouse_drag(page, x0, y0, x1, y1):
    page.mouse.move(x0, y0)
    page.mouse.down()
    page.mouse.move(x0 + (x1 - x0) * 0.3, y0 + (y1 - y0) * 0.3, steps=4)
    page.mouse.move(x1, y1, steps=8)
    page.mouse.up()
    settle(page)


def touch_drag(page, x0, y0, x1, y1):
    cdp = page.context.new_cdp_session(page)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x0, "y": y0}]})
    for i in range(1, 11):
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x0 + (x1 - x0) * i / 10, "y": y0 + (y1 - y0) * i / 10}]})
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    cdp.detach()
    settle(page)


def inside(r, b, tol=0.6):
    return r["l"] >= b["L"] - tol and r["t"] >= b["T"] - tol and r["r"] <= b["R"] + tol and r["b"] <= b["B"] + tol


def boot(page, port):
    page.goto(f"http://127.0.0.1:{port}/protrader_mobile.html", wait_until="domcontentloaded")
    page.wait_for_function("typeof VOICE !== 'undefined' && typeof VXF !== 'undefined' && typeof OT !== 'undefined'")
    page.wait_for_timeout(1200)
    page.evaluate(SETUP)


def head_point(page):
    r = rect(page, ".vx-title")
    return r["l"] + r["w"] / 2, r["t"] + r["h"] / 2


# ── laptop ─────────────────────────────────────────────────────────────────────

def check_desktop(page, port, shots):
    boot(page, port)
    page.evaluate("VOICE.open(false)")
    calm(page)
    b, r = bounds(page), rect(page, ".vx-sheet")
    assert abs(r["r"] - b["R"]) < 1 and abs(r["b"] - b["B"]) < 1, (r, b)
    assert not page.evaluate("!!document.querySelector('.vx-backdrop')")
    assert page.evaluate("document.body.classList.contains('vx-side-r')")
    ok("laptop: opens docked bottom-right, inside the screen, with no backdrop over the app")

    # a live conversation keeps going while the chart, the tabs and a field outside ARIA are used
    page.evaluate("VOICE.addLog('you', 'what is the trend'); VOICE.addLog('vx', 'Higher highs on the 15 minute.'); VOICE.listen()")
    page.wait_for_function("VOICE.state === 'listening'")
    page.evaluate("clearTimeout(VOICE._recT)")                       # a person still talking: no 12-second silence stop
    rec_n = page.evaluate("window.__recs.length")
    page.mouse.click(600, 300)                                      # the chart
    page.click("#pairSearch"); page.keyboard.type("GBP")            # a field outside ARIA
    page.locator(".rtab", has_text="Trade").first.click()           # the order ticket
    page.wait_for_timeout(250)
    st = page.evaluate("({ open: VOICE.open_, min: VOICE.min_, state: VOICE.state, aborted: window.__recs[window.__recs.length - 1].aborted, recs: window.__recs.length, log: VOICE.log.length })")
    assert st == {"open": True, "min": False, "state": "listening", "aborted": False, "recs": rec_n, "log": st["log"]} and st["log"] >= 2, st
    assert page.evaluate("document.getElementById('pairSearch').value") == "GBP"
    ok("laptop: the chart, a field and the order ticket work while ARIA keeps listening (nothing closes it)")

    # drag by the header into the middle: it stays where it is put
    x, y = head_point(page)
    mouse_drag(page, x, y, x - 420, y - 200)
    b, r = bounds(page), rect(page, ".vx-sheet")
    p = stored(page)
    assert inside(r, b) and p["ox"] > 40 and p["oy"] > 40, (r, b, p)
    assert not page.evaluate("document.body.classList.contains('vx-side-r') || document.body.classList.contains('vx-side-l')")
    assert page.evaluate("VOICE.state") == "listening"
    ok(f"laptop: dragged by the header to the middle, it stays there ({p['ax']}{p['ox']} / {p['ay']}{p['oy']}) and ARIA keeps listening")

    # thrown past the top-left corner: bounded, then flush to both edges
    x, y = head_point(page)
    mouse_drag(page, x, y, x - 2000, y - 2000)
    b, r = bounds(page), rect(page, ".vx-sheet")
    assert abs(r["l"] - b["L"]) < 1 and abs(r["t"] - b["T"]) < 1, (r, b)
    assert stored(page)[ "ax"] == "l" and stored(page)["ay"] == "t" and stored(page)["ox"] == 0 and stored(page)["oy"] == 0
    assert page.evaluate("document.body.classList.contains('vx-side-l')")
    ok("laptop: dragged off screen it stops at the edge and snaps flush top-left (docks left)")

    # dropped near the right edge: snaps flush to it
    x, y = head_point(page)
    r = rect(page, ".vx-sheet")
    mouse_drag(page, x, y, x + (b["R"] - r["r"]) - 25, y + 150)
    b, r = bounds(page), rect(page, ".vx-sheet")
    assert abs(r["r"] - b["R"]) < 1 and inside(r, b), (r, b)
    ok("laptop: dropped 25px from the right edge, it snaps flush to it")

    # the grip from the keyboard
    page.focus("#vxGrip")
    r0 = rect(page, ".vx-sheet")
    page.keyboard.press("ArrowLeft"); settle(page)
    r1 = rect(page, ".vx-sheet")
    assert abs((r0["l"] - r1["l"]) - 24) < 1.5, (r0, r1)
    page.keyboard.press("Home"); settle(page)
    b, r2 = bounds(page), rect(page, ".vx-sheet")
    assert abs(r2["l"] - b["L"]) < 1, (r2, b)
    page.keyboard.press("End"); page.keyboard.press("PageDown"); settle(page)
    b, r3 = bounds(page), rect(page, ".vx-sheet")
    assert abs(r3["r"] - b["R"]) < 1 and abs(r3["b"] - b["B"]) < 1, (r3, b)
    ok("laptop: the grip moves with the arrow keys; Home/End/PageDown dock it")
    if shots:
        page.screenshot(path=os.path.join(shots, "aria_float_laptop.png"))

    # minimise: the card hides, the bubble shows what ARIA is doing, the conversation keeps going
    page.click("#vxHide")
    calm(page)
    assert page.evaluate("VOICE.open_ && VOICE.min_") and not visible(page, ".vx-sheet") and visible(page, "#vxBub")
    b, rb = bounds(page), rect(page, "#vxBub")
    assert abs(rb["r"] - b["R"]) < 1 and abs(rb["b"] - b["B"]) < 1, (rb, b)
    assert page.evaluate("document.getElementById('vxBub').dataset.state") == "listening"
    assert page.evaluate("!window.__recs[window.__recs.length - 1].aborted && VOICE.state === 'listening'")
    assert page.evaluate("document.activeElement && document.activeElement.id") == "vxBub"
    assert stored(page)["min"] is True
    page.evaluate("VOICE.addLog('vx', 'Price is back at the level.')")
    assert page.evaluate("document.getElementById('vxBub').classList.contains('unread')")
    page.evaluate("ELV.rec = {}; VOICE.setState('listening'); ")
    assert page.evaluate("document.getElementById('vxBub').classList.contains('rec')")
    page.evaluate("ELV.rec = null; VOICE.setState('listening')")
    ok("laptop: minimised to a bubble at the same corner; it shows listening, recording and a new answer; the mic is untouched")

    # the bubble drags (and always rests against a side); a tap brings the card back there
    rb = rect(page, "#vxBub")
    mouse_drag(page, rb["l"] + 30, rb["t"] + 30, 420, 360)
    b, rb = bounds(page), rect(page, "#vxBub")
    assert abs(rb["l"] - b["L"]) < 1 and 300 < rb["t"] < 420 and visible(page, "#vxBub") and page.evaluate("VOICE.min_"), (rb, b)
    page.mouse.click(rb["l"] + 30, rb["t"] + 30)
    calm(page)
    b, r = bounds(page), rect(page, ".vx-sheet")
    assert page.evaluate("!VOICE.min_") and visible(page, ".vx-sheet") and abs(r["l"] - b["L"]) < 1 and inside(r, b), (r, b)
    assert not page.evaluate("document.getElementById('vxBub').classList.contains('unread')")
    assert page.evaluate("VOICE.log.slice(-1)[0].text") == "Price is back at the level."
    ok("laptop: the bubble drags and snaps to the left side; a tap restores the card there with the conversation intact")

    # Escape and V tuck it away and bring it back; neither ends the conversation
    page.mouse.click(600, 300)
    page.keyboard.press("Escape"); page.wait_for_timeout(150)
    assert page.evaluate("VOICE.open_ && VOICE.min_")
    page.keyboard.press("v"); page.wait_for_timeout(150)
    assert page.evaluate("VOICE.open_ && !VOICE.min_")
    page.keyboard.press("v"); page.wait_for_timeout(150)
    assert page.evaluate("VOICE.open_ && VOICE.min_")
    page.keyboard.press("v"); page.wait_for_timeout(150)
    page.focus("#vxInput"); page.keyboard.press("Escape"); page.wait_for_timeout(150)
    assert page.evaluate("VOICE.open_ && VOICE.min_ && VOICE.state === 'listening'")
    page.click("#voiceBtn"); page.wait_for_timeout(150)
    assert page.evaluate("VOICE.open_ && !VOICE.min_")
    ok("laptop: Escape (also from ARIA's own field), V and the mic button minimise and restore; the session never ends")

    # a dialog opened while ARIA is up (the MT5 confirmation, a deposit) sits above the card and takes the clicks
    page.evaluate("document.getElementById('depositModal').classList.add('open')")
    page.wait_for_timeout(250)
    r = rect(page, ".vx-sheet")
    top = page.evaluate(f"(() => {{ const e = document.elementFromPoint({r['l'] + r['w'] / 2}, {r['t'] + r['h'] / 2}); return !!(e && e.closest('#depositModal')); }})()")
    assert top, "the dialog must be above ARIA"
    page.evaluate("closeAllModals()"); page.wait_for_timeout(250)
    assert page.evaluate("VOICE.open_ && !VOICE.min_ && VOICE.state === 'listening'")
    ok("laptop: a dialog opens above ARIA (ARIA waits underneath, still listening)")

    # a press whose release never reaches the page (a context menu) does not leave the card stuck to the cursor
    x, y = head_point(page)
    r0 = rect(page, ".vx-sheet")
    page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x - 120, y - 60, steps=5)
    page.evaluate("window.dispatchEvent(new PointerEvent('pointermove', { pointerId: 1, pointerType: 'mouse', buttons: 0, clientX: 100, clientY: 100 }))")
    page.mouse.up(); settle(page)
    assert page.evaluate("VXF.drag") is None and inside(rect(page, ".vx-sheet"), bounds(page))
    # minimised in the middle of a drag: the last resting place is kept, not the corner
    pos = stored(page)
    x, y = head_point(page)
    page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x - 200, y - 100, steps=5)
    page.evaluate("VOICE.minimize()")
    page.mouse.move(x - 260, y - 140, steps=3); page.mouse.up(); settle(page)
    assert stored(page)["ax"] == pos["ax"] and stored(page)["ay"] == pos["ay"] and page.evaluate("VXF.drag") is None
    b, rb = bounds(page), rect(page, "#vxBub")
    assert (abs(rb["l"] - b["L"]) < 1 or abs(rb["r"] - b["R"]) < 1) and inside(rb, b), (rb, b)
    page.evaluate("VOICE.restore()"); calm(page)
    ok("laptop: a lost release ends the drag; minimising mid-drag keeps the place; the bubble always sits at a side")

    # a smaller window: re-placed inside it
    page.set_viewport_size({"width": 900, "height": 560}); page.wait_for_timeout(300); calm(page)
    assert inside(rect(page, ".vx-sheet"), bounds(page))
    page.set_viewport_size({"width": 1000, "height": 150}); page.wait_for_timeout(300); calm(page)
    r, hd = rect(page, ".vx-sheet"), rect(page, "#vxHide")
    assert r["t"] >= 0 and r["b"] <= 150 and hd["t"] >= 0 and hd["b"] <= 150, (r, hd)
    page.set_viewport_size({"width": 1280, "height": 860}); page.wait_for_timeout(300); calm(page)
    assert inside(rect(page, ".vx-sheet"), bounds(page))
    ok("laptop: a resized window (even a 150px strip) keeps the card, and its minimise control, on screen")

    # the session remembers: a reload (or an app update) brings ARIA back where it was, minimised, without the mic
    x, y = head_point(page)
    mouse_drag(page, x, y, x + 300, y - 120)
    before, pos = rect(page, ".vx-sheet"), stored(page)
    page.evaluate("VOICE.minimize()")
    calm(page)
    bub_before = rect(page, "#vxBub")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_function("typeof VXF !== 'undefined' && VOICE.open_", timeout=6000)
    page.wait_for_timeout(400); calm(page)
    assert page.evaluate("VOICE.min_ && VOICE.state !== 'listening' && !VOICE.rec") and visible(page, "#vxBub")
    rb = rect(page, "#vxBub")
    assert abs(rb["l"] - bub_before["l"]) < 1 and abs(rb["t"] - bub_before["t"]) < 1, (rb, bub_before)
    page.evaluate(SETUP)
    page.evaluate("VOICE.restore()"); calm(page)
    after = rect(page, ".vx-sheet")
    assert stored(page)["ox"] == pos["ox"] and stored(page)["oy"] == pos["oy"]
    # the card's height follows its conversation, so "the same place" is its anchored edges
    edge_y = "t" if pos["ay"] == "t" else "b"
    assert abs(after["l"] - before["l"]) < 1 and abs(after[edge_y] - before[edge_y]) < 1, (before, after, pos)
    assert page.evaluate("window.__recs.length") == 0
    ok("laptop: after a reload ARIA is back at the same place (minimised as it was), without starting the microphone")

    # this device's own voice: private read-backs only on a voice that runs on the device; ARIA's replies on the most natural
    picked = page.evaluate("""(() => {
      const mk = (name, lang, local, def) => ({ name, lang, localService: local, default: !!def, voiceURI: name });
      const list = [mk('Microsoft David - English (United States)', 'en-US', true, true), mk('Microsoft Zira Desktop', 'en-US', true),
        mk('Samantha', 'en-US', true), mk('Google UK English Female', 'en-GB', false),
        mk('Microsoft Ezinne Online (Natural) - English (Nigeria)', 'en-NG', false)];
      speechSynthesis.getVoices = () => list; VOICE._best = null; VOICE.cfg.voice = '';
      return [VOICE.pickVoice(true).name, VOICE.pickVoice(false).name]; })()""")
    assert picked == ["Samantha", "Microsoft Ezinne Online (Natural) - English (Nigeria)"], picked
    ok(f"device voice: private read-backs stay on a local voice ({picked[0]}); replies use the most natural ({picked[1]})")

    # × ends the conversation, and the next page load stays closed
    page.click(".vx-head .vx-icon[aria-label^='Close ARIA']")
    assert page.evaluate("!VOICE.open_") and stored(page)["open"] is False
    page.reload(wait_until="domcontentloaded")
    page.wait_for_function("typeof VXF !== 'undefined'")
    page.wait_for_timeout(500)
    assert page.evaluate("!VOICE.open_ && !document.querySelector('#vxSheet.open')")
    ok("laptop: × ends the conversation and stays closed after a reload")


# ── phone ──────────────────────────────────────────────────────────────────────

def check_phone(page, port, shots):
    boot(page, port)
    page.evaluate("VOICE.open(false)")
    calm(page)
    b, r = bounds(page), rect(page, ".vx-sheet")
    nav = rect(page, ".mobile-nav")
    assert abs(r["l"] - 8) < 1 and abs(r["r"] - 382) < 1, r
    assert r["b"] <= nav["t"] - 7.5 and inside(r, b), (r, nav)
    assert r["h"] <= (b["B"] - b["T"]) * 0.78 + 1, (r, b)
    assert page.evaluate("document.documentElement.scrollWidth") <= 392
    ok("phone: a floating card above the tab bar, leaving the chart a share of the screen; no sideways scroll")

    page.evaluate("VOICE.addLog('vx', 'Watching the level for you.'); VOICE.listen()")
    page.wait_for_function("VOICE.state === 'listening'")
    page.evaluate("clearTimeout(VOICE._recT)")

    # a finger drags it by the header: up to the top, bounded under the status bar
    x, y = head_point(page)
    touch_drag(page, x, y, x, y - 1500)
    b, r = bounds(page), rect(page, ".vx-sheet")
    assert abs(r["t"] - b["T"]) < 1 and abs(r["l"] - 8) < 1 and stored(page)["ay"] == "t", (r, b)
    assert page.evaluate("VOICE.state") == "listening"
    ok("phone: dragged up by a finger, it stops under the status bar and snaps to the top; ARIA keeps listening")

    # the order ticket (opened from an insight's Plan trade): ARIA stays, and the session carries on
    page.evaluate("openMobilePanel('trade')")
    page.wait_for_timeout(400)
    assert page.evaluate("VOICE.open_ && VOICE.state === 'listening' && !window.__recs[window.__recs.length - 1].aborted")
    if shots:
        page.screenshot(path=os.path.join(shots, "aria_float_phone_ticket.png"))
    # choosing a typing field (the keyboard is about to take half the screen) tucks ARIA away;
    # the app focusing a field by itself, or a switch, does not
    x, y = head_point(page)
    touch_drag(page, x, y, x, y + 1500)                           # back down to the bottom
    page.evaluate("""(() => { const c = document.querySelector('.vx-sheet').getBoundingClientRect();
      const mk = (id, type, top) => { const f = document.createElement('input'); f.id = id; f.type = type;
        f.style.cssText = `position:fixed;left:40px;top:${top}px;width:200px;height:40px;z-index:300`; document.body.appendChild(f); };
      mk('fieldUnder', 'number', c.top + 40); mk('switchUnder', 'checkbox', c.top + 100); })()""")
    page.evaluate("document.getElementById('fieldUnder').focus(); document.getElementById('fieldUnder').blur()")
    assert page.evaluate("!VOICE.min_"), "the app focusing a field must not minimise ARIA"
    tap_js = """(id => { const f = document.getElementById(id); f.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerType: 'touch' })); f.focus(); })"""
    page.evaluate(f"{tap_js}('switchUnder')"); page.wait_for_timeout(120)
    assert page.evaluate("!VOICE.min_"), "a switch under the card must not minimise ARIA"
    page.evaluate(f"{tap_js}('fieldUnder')"); page.wait_for_timeout(120)
    assert page.evaluate("VOICE.min_ && VOICE.open_ && VOICE.state === 'listening'")
    page.evaluate("document.getElementById('fieldUnder').remove(); document.getElementById('switchUnder').remove(); VOICE.restore()")
    ok("phone: choosing a typing field tucks ARIA into its bubble before the keyboard opens (listening continues); app focus and switches do not")

    page.click("#vxHide")
    calm(page)
    b, rb = bounds(page), rect(page, "#vxBub")
    assert abs(rb["r"] - b["R"]) < 1 and abs(rb["b"] - b["B"]) < 1, (rb, b)
    touch_drag(page, rb["l"] + 30, rb["t"] + 30, 120, 520)
    b, rb = bounds(page), rect(page, "#vxBub")
    assert abs(rb["l"] - b["L"]) < 1 and 420 < rb["t"] < 560 and inside(rb, b), (rb, b)
    touch_drag(page, rb["l"] + 30, rb["t"] + 30, 200, 2000)
    b, rb = bounds(page), rect(page, "#vxBub")
    nav = rect(page, ".mobile-nav")
    assert rb["b"] <= nav["t"] - 7.5 and inside(rb, b), (rb, nav)
    if shots:
        page.screenshot(path=os.path.join(shots, "aria_float_phone_bubble.png"))
    page.tap("#vxBub")
    calm(page)
    b, r = bounds(page), rect(page, ".vx-sheet")
    assert page.evaluate("!VOICE.min_ && VOICE.state === 'listening'") and inside(r, b) and abs(r["b"] - b["B"]) < 1, (r, b)
    assert page.evaluate("document.documentElement.scrollWidth") <= 392
    ok("phone: the bubble drags by a finger, rests against a side, never under the tab bar; a tap brings the card back above it")

    # turned sideways: still whole and inside
    page.set_viewport_size({"width": 844, "height": 390}); page.wait_for_timeout(350); calm(page)
    assert inside(rect(page, ".vx-sheet"), bounds(page)), (rect(page, ".vx-sheet"), bounds(page))
    lh = page.evaluate("document.getElementById('vxLog').getBoundingClientRect().height")
    assert lh >= 50, lh                                           # a short screen scrolls the card; the replies stay readable
    page.set_viewport_size({"width": 390, "height": 844}); page.wait_for_timeout(350); calm(page)
    assert inside(rect(page, ".vx-sheet"), bounds(page))
    ok("phone: rotated to landscape and back, the card stays whole and on screen")


def main():
    shots = sys.argv[1] if len(sys.argv) > 1 else None
    httpd = serve()
    port = httpd.server_address[1]
    args = ["--ignore-certificate-errors"]
    if PROXY:
        args += [f"--proxy-server={PROXY}", "--proxy-bypass-list=127.0.0.1;localhost;<local>"]
    with sync_playwright() as p:
        b = p.chromium.launch(args=args)
        for name, kw, fn in [("laptop", dict(viewport={"width": 1280, "height": 860}), check_desktop),
                             ("phone", dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True), check_phone)]:
            ctx = b.new_context(locale="en-US", timezone_id="UTC", **kw)
            page = ctx.new_page()
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            fn(page, port, shots)
            assert not errs, errs
            ctx.close()
        b.close()
    httpd.shutdown()
    print("all ARIA floating-widget checks passed")


if __name__ == "__main__":
    main()
