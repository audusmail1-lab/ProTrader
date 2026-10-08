"""
The Drift card in the Sentinel tab, rendered by protrader_mobile.html from the real
server code (FastAPI TestClient behind Playwright's network interception).
   python3 tests/test_drift_browser.py
"""
import functools
import http.server
import json
import os
import socketserver
import sys
import tempfile
import threading
import time

os.environ["SENTINEL_ENABLED"] = "0"
os.environ["SENTINEL_DB"] = os.path.join(tempfile.mkdtemp(), "db.db")
os.environ["SENTINEL_ADMIN_KEY"] = "o" * 32
os.environ["ACCOUNTS_DB"] = os.path.join(tempfile.mkdtemp(), "a.db")
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from fastapi import FastAPI                     # noqa: E402
from fastapi.testclient import TestClient       # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
import mt5_bridge                                # noqa: E402
import sentinel as S                             # noqa: E402
import drift as D                                # noqa: E402

PROXY = os.environ.get("HTTPS_PROXY", "")
OWNER = "o" * 32
app = FastAPI(); app.include_router(mt5_bridge.router); app.include_router(S.router)
client = TestClient(app)
DAY = 86400


def serve():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    httpd = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def seed():
    """A year of daily candles: US Tech 100 rising then dipping under its line, US 500 rising."""
    today = int(time.time()) // DAY * DAY
    for mid, base, slope in (("frxNAS100", 25_000.0, 30.0), ("frxSPX500", 6_500.0, 4.0)):
        cs = []
        for i in range(260):
            c = base + slope * i
            if mid == "frxNAS100" and i >= 250:
                c = base + slope * 200 - 400 * (i - 249)                    # the last ten days fall through the line
            cs.append({"epoch": today - (260 - i) * DAY, "o": c - 5, "h": c + 20, "l": c - 25, "c": c})
        D.store_candles(mid, cs)
    D._set_cfg(dict(D.cfg(), paper_start=today - 60 * DAY))


def handle(route):
    req = route.request
    path = req.url.split("/api/sentinel/", 1)[1]
    hdr = {"x-sentinel-key": req.headers.get("x-sentinel-key", "")}
    if req.method == "POST":
        r = client.post("/api/sentinel/" + path, content=req.post_data or "{}", headers=dict(hdr, **{"content-type": "application/json"}))
    else:
        r = client.get("/api/sentinel/" + path, headers=hdr)
    route.fulfill(status=r.status_code, content_type="application/json", body=r.text)


def main():
    seed()
    httpd = serve()
    port = httpd.server_address[1]
    args = ["--ignore-certificate-errors"]
    if PROXY:
        args += [f"--proxy-server={PROXY}", "--proxy-bypass-list=127.0.0.1;localhost;<local>"]
    with sync_playwright() as p:
        b = p.chromium.launch(args=args)
        page = b.new_context(locale="en-US", timezone_id="UTC", ignore_https_errors=True, viewport={"width": 390, "height": 844}).new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.route("**/api/sentinel/**", handle)
        page.goto(f"http://127.0.0.1:{port}/protrader_mobile.html", wait_until="domcontentloaded")
        page.evaluate(f"localStorage.setItem('protrader.sentinelKey', '{OWNER}')")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function("typeof SENT !== 'undefined'")
        page.evaluate("setRTab('sentinel')")
        page.wait_for_selector("text=Drift · own the rise", timeout=20000)
        card = page.locator(".sn-h", has_text="Drift · own the rise").locator("xpath=following-sibling::div[1]")
        text = card.inner_text()
        assert "US Tech 100" in text and "Aside" in text and "US 500" in text and "Hold" in text, text
        assert "Your pick: 1x" in text and "Demo version: inside your risk rules" in text, text
        assert "MT5 bridge not connected" in text and "Not started" in text, text
        assert page.locator("button", has_text="Start Drift on the demo").is_disabled()
        hist = page.evaluate("""(() => { const d = [...document.querySelectorAll('#sentinel-panel details')].find(x => /What history says/.test(x.textContent));
          d.open = true; return d.innerText; })()""")
        assert "2000-2012" in hist and "Your pick, 1x CFD" in hist, hist
        # the price helper the scanner cards use is still the old one (no name clash with Drift's actions)
        assert page.evaluate("typeof SENT.driftAct === 'function'")
        w = page.evaluate("document.documentElement.scrollWidth")
        assert w <= 392, w                                                    # no sideways scroll on a phone
        page.screenshot(path=os.path.join(tempfile.gettempdir(), "drift_card.png"), full_page=False)
        if os.environ.get("SHOW"):
            print(text)
        assert not errs, errs
        b.close()
    httpd.shutdown()
    print("ok  Drift card: signals, both paper books, demo state, history; no errors, fits a phone")


if __name__ == "__main__":
    main()
