"""The phone's paper account becomes the account's, the desk's is kept and restorable,
and nothing else (journal, MT5 bridge) is touched.   python3 tests/test_account_paper_choice_browser.py"""
import json, os, socket, sys, tempfile, threading, time
from urllib.parse import parse_qs, urlsplit

os.environ["ACCOUNTS_DB"] = os.path.join(tempfile.mkdtemp(), "accounts.db")
os.environ["SENTINEL_ENABLED"] = "0"
os.environ["SENTINEL_DB"] = os.path.join(tempfile.mkdtemp(), "s.db")
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import requests, uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import sync_playwright
import accounts

TEACHER = {"id": 1, "name": "Joel", "email": "joel@example.com", "role": "teacher", "status": "accepted", "verified": True}
ACADEMY = {}
accounts._exchange = lambda code, verifier: ACADEMY.pop(code)
app = FastAPI()
app.include_router(accounts.router)
app.mount("/static", StaticFiles(directory=os.path.join(ROOT, "static")), name="static")
app.get("/")(lambda: FileResponse(os.path.join(ROOT, "protrader_mobile.html")))
PROXY = os.environ.get("HTTPS_PROXY", "")


def serve():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(100):
        try:
            requests.get(f"http://127.0.0.1:{port}/api/account/me", timeout=1); break
        except Exception:
            time.sleep(0.1)
    return srv, f"http://127.0.0.1:{port}"


def sign_in(base):
    s = requests.Session()
    r = s.get(base + "/auth/academy/start", allow_redirects=False)
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    code = "c" + os.urandom(8).hex(); ACADEMY[code] = TEACHER
    s.get(f"{base}/auth/academy/callback?code={code}&state={state}", allow_redirects=False)
    return s


def fill(i, t, pnl):
    return {"id": i, "sym": "1HZ50V", "pair": "Vol 50 (1s)", "type": "buy", "volume": 0.1, "entry": 100, "exit": 101, "pnl": pnl,
            "openTime": t, "closeTime": t + 60_000, "reason": "Manual", "final": True}


def main():
    srv, base = serve()
    desk = sign_in(base)
    put = lambda key, data, v: desk.put(f"{base}/api/account/workspace/{key}", json={"data": data, "version": v}, headers={"Origin": base}).json()
    put("trade", {"balance": 9782.69, "trades": [fill(1, 1_000_000, -217.31)], "positions": [], "orders": [{"id": 9, "state": "working"}]}, 0)
    put("mgmt", {"recs": {"mt5:1": {"key": "mt5:1", "setup": "TCL"}}}, 0)
    put("mt5bridge", {"key": "desk-bridge", "shown": True}, 0)
    phone_trade = {"balance": 40124.0, "trades": [fill(500 + i, 2_000_000 + i * 100_000, 300.0) for i in range(5)], "positions": [], "orders": []}
    args = ["--ignore-certificate-errors"] + ([f"--proxy-server={PROXY}", "--proxy-bypass-list=127.0.0.1;localhost;<local>"] if PROXY else [])
    with sync_playwright() as p:
        b = p.chromium.launch(args=args)
        host = base.split("//")[1].split(":")[0]
        cookies = [{"name": c.name, "value": c.value, "domain": host, "path": "/"} for c in desk.cookies]
        dctx = b.new_context(viewport={"width": 1280, "height": 900})           # the desk, signed in, open the whole time
        dctx.add_cookies(cookies)
        dpage = dctx.new_page()
        dpage.goto(base + "/", wait_until="domcontentloaded")
        dpage.wait_for_function("() => { try { return JSON.parse(localStorage.getItem('protrader.trade.v2')).balance === 9782.69 } catch (_) { return false } }", timeout=20000)
        dpage.wait_for_timeout(1500)
        ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3)
        page = ctx.new_page()
        page.goto(base + "/", wait_until="domcontentloaded")          # the phone, as a guest
        page.evaluate(f"""() => {{ localStorage.setItem('protrader.trade.v2', {json.dumps(json.dumps(phone_trade))});
                                  localStorage.setItem('protrader.drawings.v1', JSON.stringify({{'1HZ50V': [{{id: 'phone-line'}}]}})); }}""")
        ctx.add_cookies(cookies)                                                  # signs in on the phone
        page.goto(base + "/", wait_until="domcontentloaded")
        page.wait_for_selector("#acctAdopt", timeout=20000)
        txt = page.inner_text("#acctAdopt")
        if os.environ.get("SHOT_DIR"):
            page.locator("#acctAdopt").screenshot(path=os.path.join(os.environ["SHOT_DIR"], "phone_signin_choice.png"))
        assert "$9,782.69" in txt and "$40,124.00" in txt, txt
        with page.expect_navigation(timeout=20000):
            page.click("#acctAdopt [data-a=paper]")
        page.wait_for_timeout(1500)
        docs = desk.get(base + "/api/account/workspace").json()["docs"]
        assert docs["trade"]["data"]["balance"] == 40124.0, docs["trade"]["data"]["balance"]
        assert docs["mgmt"]["data"]["recs"]["mt5:1"]["setup"] == "TCL" and docs["mt5bridge"]["data"]["key"] == "desk-bridge"
        assert "drawings" not in docs                                             # the phone's drawings were not pushed
        local = page.evaluate("() => ({t: JSON.parse(localStorage.getItem('protrader.trade.v2')).balance, m: localStorage.getItem('protrader.mgmt.v1'), d: localStorage.getItem('protrader.drawings.v1'), bk: Object.keys(JSON.parse(localStorage.getItem('protrader.backup.v1') || '{}'))})")
        assert local["t"] == 40124.0 and "TCL" in (local["m"] or "") and local["d"] is None and "drawings" in local["bk"] and "trade" in local["bk"], local
        hist = desk.get(base + "/api/account/workspace/trade/history").json()["copies"]
        assert hist and hist[0]["summary"]["balance"] == 9782.69 and hist[0]["summary"]["pending"] == 1, hist
        print("ok  phone's paper account saved to the account; journal and MT5 bridge untouched; desk's kept on the server")
        # the desk is in use and saves its old account: it must not overwrite the phone's, it takes it instead
        dpage.mouse.click(5, 5)
        with dpage.expect_navigation(timeout=30000):
            dpage.evaluate("() => { const d = JSON.parse(localStorage.getItem('protrader.trade.v2')); d.balance = 9790.0; localStorage.setItem('protrader.trade.v2', JSON.stringify(d)); }")
        dpage.wait_for_timeout(1000)
        assert desk.get(base + "/api/account/workspace").json()["docs"]["trade"]["data"]["balance"] == 40124.0
        assert dpage.evaluate("() => JSON.parse(localStorage.getItem('protrader.trade.v2')).balance") == 40124.0
        bk = dpage.evaluate("() => { const b = JSON.parse(localStorage.getItem('protrader.backup.v1') || '{}'); return Object.fromEntries(Object.entries(b).map(([k, v]) => [k, (() => { try { return JSON.parse(v.raw).balance } catch (_) { return null } })()])) }")
        assert bk.get("trade") in (9790.0, 9782.69), bk
        print("ok  an active desk takes the phone's account instead of overwriting it, and keeps its own copy")
        # the backup list and a restore, from the phone's account sheet
        page.evaluate("ACCOUNT.open()")
        page.wait_for_selector("#acctBackups [data-restore]", timeout=10000)
        assert "$9,782.69" in page.inner_text("#acctBackups")
        if os.environ.get("SHOT_DIR"):
            page.locator("#acctBackups").screenshot(path=os.path.join(os.environ["SHOT_DIR"], "paper_backups.png"))
        page.click("#acctBackups [data-restore]")
        page.wait_for_selector("#acctRestore", timeout=5000)
        assert "$40,124.00" in page.inner_text("#acctRestore")
        with page.expect_navigation(timeout=20000):
            page.click("#acctRestore [data-a=yes]")
        page.wait_for_timeout(1500)
        assert page.evaluate("() => JSON.parse(localStorage.getItem('protrader.trade.v2')).balance") == 9782.69
        hist = desk.get(base + "/api/account/workspace/trade/history").json()["copies"]
        assert hist[0]["summary"]["balance"] == 40124.0, hist
        print("ok  restore brings the desk's account back and keeps the phone's")
        b.close()
    srv.should_exit = True
    print("all account paper-choice checks passed")


if __name__ == "__main__":
    main()
