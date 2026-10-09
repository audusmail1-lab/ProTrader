"""
ARIA AI end to end in a real browser: the app, the real FastAPI routes (aria_ai.py)
and the TEST provider (scripted; never used in production). This proves the
plumbing between the copilot, the server and the chart — the context the model
would receive, the tools it can call, limits, failures, replay integrity, voice.
The live model is verified separately once GEMINI_API_KEY is configured.
   python3 tests/test_aria_ai_browser.py
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time

os.environ["ACCOUNTS_DB"] = os.path.join(tempfile.mkdtemp(), "accounts.db")
os.environ["ARIA_AI_DB"] = os.path.join(tempfile.mkdtemp(), "aria.db")
os.environ["ARIA_AI_PROVIDER"] = "mock"
os.environ["ARIA_AI_ALLOW_MOCK"] = "1"
os.environ["ARIA_AI_USER_PER_MIN"] = "200"
os.environ["ARIA_AI_GUEST_PER_DAY"] = "500"
os.environ["ARIA_AI_IP_PER_DAY"] = "500"
os.environ["ARIA_AI_RPM_MAIN"] = "200"
os.environ["ARIA_AI_RPM_LITE"] = "200"
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))

import requests                                      # noqa: E402
import uvicorn                                       # noqa: E402
from fastapi import FastAPI                          # noqa: E402
from fastapi.responses import FileResponse          # noqa: E402
from fastapi.staticfiles import StaticFiles          # noqa: E402
from playwright.sync_api import sync_playwright      # noqa: E402

import accounts                                      # noqa: E402
import aria_ai                                       # noqa: E402
from test_voice_browser import PROXY, SETUP          # noqa: E402

M = aria_ai.MockProvider
app = FastAPI()
app.include_router(accounts.router)
app.include_router(aria_ai.router)
app.get("/api/sentinel/board")(lambda: {"updated": 0, "rows": [{"market": "R_75", "tf": "15m", "dir": "buy", "score": 7, "verdict": "WAITING", "mcc": "RANGE",
                                                                  "pattern": None, "trend_4h": "up", "block": None, "evidence": "unproven", "age_seconds": 120, "entry_eligible": False}]})
app.mount("/vendor", StaticFiles(directory=os.path.join(ROOT, "vendor")), name="vendor")
app.mount("/static", StaticFiles(directory=os.path.join(ROOT, "static")), name="static")
app.get("/app")(lambda: FileResponse(os.path.join(ROOT, "protrader_mobile.html")))


def serve():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(100):
        try:
            requests.get(f"http://127.0.0.1:{port}/api/aria/ai/status", timeout=1); break
        except Exception:
            time.sleep(0.1)
    return srv, f"http://127.0.0.1:{port}"


def ctx_of(req):
    """The workspace snapshot exactly as the model would have received it."""
    for p in req["contents"][-1]["parts"]:
        if p.get("text", "").startswith("[WORKSPACE CONTEXT"):
            return json.loads(p["text"].split("\n", 1)[1])
    return None


def say(page, text, wait_done=True):
    page.evaluate("window.__said = []")
    n = len(M.seen)
    page.fill("#vxInput", text)
    page.press("#vxInput", "Enter")
    if wait_done:
        page.wait_for_function("!AI.busy && VOICE.state !== 'thinking'", timeout=15000)
        page.wait_for_timeout(150)
    return M.seen[n:]


def last_ai(page):
    return page.evaluate("(() => { const m = VOICE.log.filter(x => x.ai).slice(-1)[0]; return m ? { text: m.text, tools: m.tools, model: m.model, status: m.status } : null; })()")


def call(name, args, text=None):
    M.script.append({"parts": [{"functionCall": {"name": name, "args": args}, "thoughtSignature": "c2ln"}]})
    if text:
        M.script.append({"parts": [{"text": text}]})


def check_conversation(page):
    reqs = say(page, "Hello.")
    a = last_ai(page)
    assert a and a["text"].startswith("[mock] Hello!") and "not sure what to do" not in a["text"], a
    assert reqs[0]["model"] == "gemini-3.1-flash-lite" and "gemini-3.1-flash-lite" in a["model"]
    assert any("Hello!" in s for s in page.evaluate("window.__said")), "the reply is spoken"
    assert page.evaluate("VOICE.log.filter(x => x.ai).length") == 1, "one bubble per answer"
    print("ok  hello: natural reply from the AI path, lightweight model, spoken, one bubble")


def check_pine(page):
    code = "//@version=6\nstrategy('EMA RSI', overlay=true)\nema200 = ta.ema(close, 200)\nif close > ema200 and ta.crossover(ta.rsi(close, 14), 50)\n    strategy.entry('L', strategy.long)"
    M.script.append({"parts": [{"text": "[mock] Here is the strategy:\n```pine\n" + code + "\n```\nIt has not been compiled."}]})
    reqs = say(page, "Create a Pine Script strategy using a 200 EMA trend filter and RSI confirmation")
    assert reqs[0]["model"] == "gemini-3.8-flash" and reqs[0]["thinking"] == "medium" and reqs[0]["max_out"] == aria_ai.CFG.max_out_code
    box = page.evaluate("(() => { const b = [...document.querySelectorAll('#vxLog .ai-code')].pop(); return b && { code: b.querySelector('code').innerText, note: b.querySelector('.ai-code-n') && b.querySelector('.ai-code-n').innerText }; })()")
    assert box and box["code"] == code and "Not compiled" in box["note"], box
    spoken = " ".join(page.evaluate("window.__said"))
    assert "strategy.entry" not in spoken and "code in the chat" in spoken, spoken
    print("ok  pine: code shown with copy and a not-compiled warning, never read aloud, main model with more room")


def check_context(page):
    reqs = say(page, "What chart am I looking at?")
    ctx = ctx_of(reqs[0])
    ch = ctx["chart"]
    truth = page.evaluate("({ sym: S.sym, tf: S.tf, px: window.__px, closed: TA.split(S.candles, S.tf).closed.slice(-20).map(c => c.time), forming: TA.split(S.candles, S.tf).forming })")
    assert ch["available"] and ch["symbol"] == truth["sym"] == "R_75" and ch["timeframe"] == truth["tf"] == "15m", ch
    assert ch["lastPrice"] == truth["px"]
    assert [c[0] for c in ch["candles"]["closed"]] == truth["closed"], "the last 20 CLOSED candles, exactly"
    assert ch["formingCandle"] and ch["formingCandle"]["note"].startswith("not closed")
    assert ch["indicators"]["rsi14"] is not None and ch["structure"]["method"].startswith("swings")
    assert ch["synthetic"] is True and "synthetic" in ch["marketSession"]
    blob = json.dumps(reqs[0])
    for word in ("balance", "equity", "positions", "email", "decisions", "Joel"):
        assert f'"{word}"' not in blob, f"{word} must not leave the device"
    a = last_ai(page)
    assert page.evaluate("VOICE.name(S.sym)") in a["text"] and "15m" in a["text"] and "44000" in a["text"], a
    print("ok  context: the model gets the real symbol, timeframe, price, closed candles and no private data")


def check_analysis(page):
    reqs = say(page, "Analyze the last 20 candles")
    assert reqs[0]["model"] == "gemini-3.8-flash" and reqs[0]["thinking"] == "low"
    ctx = ctx_of(reqs[0])
    drawn = page.evaluate("COPILOT.ours().length")
    assert drawn > 0 and len(ctx.get("justDrawn") or []) == min(drawn, 12), (drawn, ctx.get("justDrawn"))
    assert any("Drew" in t for t in last_ai(page)["tools"])
    print(f"ok  analyze: the app measured and drew {drawn} verified objects; the model got them with the data")


def check_tools(page):
    page.evaluate("COPILOT.clear()")
    call("draw_analysis", {"layers": ["zones"]})
    reqs = say(page, "Draw the key support and resistance zones")
    assert len(reqs) == 2, "a tool round goes back to the model"
    fr = reqs[1]["contents"][-1]["parts"][0]["functionResponse"]
    assert fr["name"] == "draw_analysis" and fr["response"]["ok"] and fr["response"]["verifiedOnChart"] >= 1, fr
    assert reqs[1]["contents"][-2]["parts"][0]["thoughtSignature"] == "c2ln", "the model's turn goes back with its signature"
    ids = [d["id"] for d in fr["response"]["drawn"]]
    assert page.evaluate(f"{json.dumps(ids)}.every(id => !!DT.manager().get(id) && COPILOT.mine(DT.manager().get(id)))")
    assert any("Drew" in t for t in last_ai(page)["tools"])
    # a level the chart does not contain is refused, and nothing is drawn
    n = page.evaluate("COPILOT.ours().length")
    call("draw_horizontal_level", {"price": 99999999, "label": "Moon", "reason": "x"})
    reqs = say(page, "draw a level at the moon")
    fr = reqs[1]["contents"][-1]["parts"][0]["functionResponse"]["response"]
    assert fr["ok"] is False and "outside" in fr["error"] and page.evaluate("COPILOT.ours().length") == n
    # indicators: two calls in one turn
    M.script.append({"parts": [{"functionCall": {"name": "set_indicator", "args": {"indicator": "rsi", "visible": True}}},
                               {"functionCall": {"name": "set_indicator", "args": {"indicator": "ema", "visible": True}}}]})
    reqs = say(page, "Add RSI and the 200 EMA")
    frs = [p["functionResponse"]["response"] for p in reqs[1]["contents"][-1]["parts"]]
    assert page.evaluate("S.ind.rsi && S.ind.ema") and frs[0]["values"]["rsi14"] is not None and "ema200" in frs[1]["values"], frs
    # multi-timeframe from each timeframe's own candles
    page.evaluate("""(() => { const mk = (tf, slope) => { const s = TF_SEC[tf], t0 = Math.floor(Date.now()/1000/s)*s - 200*s;
        return Array.from({length: 200}, (_, i) => { const o = 44000 + i*slope + Math.sin(i/4)*30, c = o + slope; return {time: t0+i*s, open: o, close: c, high: Math.max(o,c)+10, low: Math.min(o,c)-10}; }); };
      MTF.data['R_75'] = { '4h': mk('4h', 4), '5m': mk('5m', -4) }; })()""")
    call("compare_timeframes", {"timeframes": ["4h", "5m"]})
    reqs = say(page, "Compare the 4H structure to the 5M chart")
    tf = reqs[1]["contents"][-1]["parts"][0]["functionResponse"]["response"]["timeframes"]
    assert [t["timeframe"] for t in tf] == ["4h", "5m"] and tf[0]["trend"] == "up" and tf[1]["trend"] == "down", tf
    assert reqs[0]["thinking"] == "medium"
    # ORACLE: the verdict is the app's, logged as a practice decision
    page.evaluate("localStorage.removeItem('protrader.learning.v1')")
    call("check_plan_with_oracle", {"side": "sell", "stop": 44010, "target": 43900})
    reqs = say(page, "Ask ORACLE to challenge my sell idea")
    o = reqs[1]["contents"][-1]["parts"][0]["functionResponse"]["response"]
    real = page.evaluate("ORACLE.check({ side: 'sell', entry: window.__px, stop: 44010, target: 43900, sym: 'R_75', synthetic: true }, COPILOT.read(), null).status")
    assert o["oracle"] == real and o["evidence"], o
    d = page.evaluate("COPILOT.load().decisions.slice(-1)[0]")
    assert d["via"] == "ai" and d["status"] == real
    assert any(t.startswith("ORACLE:") for t in last_ai(page)["tools"])
    # SENTINEL: observations, labelled unproven
    call("get_sentinel_observation", {})
    reqs = say(page, "What is SENTINEL seeing here?")
    sres = reqs[1]["contents"][-1]["parts"][0]["functionResponse"]["response"]
    assert sres["observed"] and sres["rows"][0]["verdict"] == "WAITING" and "unproven" in sres["note"]
    print("ok  tools: zones drawn and verified, bad level refused, RSI + EMA on, 4H vs 5M compared, ORACLE's own verdict, SENTINEL observation")


def check_memory(page):
    n0 = page.evaluate("AI.convo.length")
    r1 = say(page, "Analyze this chart.")
    r2 = say(page, "What would invalidate that idea?")
    r3 = say(page, "Explain that more simply.")
    c3 = r3[0]["contents"]
    texts = [p.get("text", "") for c in c3 for p in c["parts"]]
    assert any(t == "Analyze this chart." for t in texts) and any(t == "What would invalidate that idea?" for t in texts), "the history travels with the question"
    assert sum(1 for t in texts if t.startswith("[WORKSPACE CONTEXT")) == 1, "only the newest message carries a snapshot"
    assert r3[0]["model"] == "gemini-3.1-flash-lite", "a simplification is a light task"
    stored = page.evaluate("JSON.parse(localStorage.getItem('protrader.aria.chat.v1')).contents.length")
    assert stored >= 6
    print("ok  memory: follow-ups carry the conversation; one snapshot per request; kept on the device")


def check_risk_and_isolation(page):
    page.evaluate("TR.positions = []; TR.orders = []; VOICE.pending = null")
    call("propose_demo_order", {"side": "buy", "order_type": "market", "stop": 20000, "risk_percent": 5})
    reqs = say(page, "set that up for me please")
    res = reqs[1]["contents"][-1]["parts"][0]["functionResponse"]["response"]
    assert res["ok"] is False and res["status"] == "rejected_by_risk_rules", res
    assert page.evaluate("TR.positions.length") == 0 and not page.evaluate("VOICE.pending && VOICE.pending.kind === 'order'")
    # a sound plan is only PREPARED; the AI has no way to confirm it
    call("propose_demo_order", {"side": "buy", "order_type": "market", "stop": 43900, "target": 44200, "risk_percent": 3})
    reqs = say(page, "ok prepare the idea we discussed")
    res = reqs[1]["contents"][-1]["parts"][0]["functionResponse"]["response"]
    assert res["ok"] and res["status"] == "awaiting_student_confirmation", res
    risk = page.evaluate("(() => { const p = VOICE.pending; return p && p.rows.find(r => r[0] === 'Stop')[1]; })()")
    assert "(1%)" in risk, f"sized by the rules at 1%, not the 3% asked: {risk}"
    assert page.evaluate("TR.positions.length") == 0, "nothing is placed without the student"
    page.evaluate("VOICE.pending = null; VOICE.renderCard()")
    # no live route exists: an unknown tool never reaches the app, and MT5 routing blocks even demo proposals
    M.script.append({"parts": [{"functionCall": {"name": "place_live_order", "args": {"symbol": "R_75"}}}, {"text": "[mock] I can't do that."}]})
    say(page, "execute this for real on the live platform")
    assert page.evaluate("TR.positions.length") == 0 and last_ai(page)["tools"] == []
    page.evaluate("VOICE._mt5 = VOICE.mt5; VOICE.mt5 = () => true")
    call("propose_demo_order", {"side": "buy", "stop": 43900})
    reqs = say(page, "go ahead and prepare it")
    res = reqs[1]["contents"][-1]["parts"][0]["functionResponse"]["response"]
    assert res["ok"] is False and "demo only" in res["error"]
    page.evaluate("VOICE.mt5 = VOICE._mt5")
    print("ok  risk + isolation: over-risk rejected by the rules, sizing capped at the plan, nothing placed by the AI, no live route")


def check_no_data(page):
    page.evaluate("window.__keep = S.candles; S.candles = []")
    reqs = say(page, "What chart am I looking at?")
    ch = ctx_of(reqs[0])["chart"]
    assert ch["available"] is False and "no candles" in ch["unavailable"] and "candles" not in ch and "lastPrice" not in ch, ch
    assert "not available" in last_ai(page)["text"]
    page.evaluate("S.candles = window.__keep")
    print("ok  no data: the model is told the chart is unavailable and receives no prices to invent from")


def check_replay(page):
    page.evaluate("(() => { FEEDX.request = () => Promise.reject(new Error('offline')); })()")
    page.evaluate("REPLAY.start({})")
    page.wait_for_function("REPLAY.active", timeout=8000)
    page.evaluate("VOICE.open(false)")
    cursor = page.evaluate("REPLAY.visible().slice(-1)[0].time")
    reqs = say(page, "What's the structure here?")
    ctx = ctx_of(reqs[0])
    assert ctx and ctx["chart"].get("available"), (page.evaluate("VOICE.log.slice(-3).map(m => m.text.slice(0, 160))"), page.evaluate("AI.st"))
    times = [c[0] for c in ctx["chart"]["candles"]["closed"]]
    assert max(times) <= cursor and ctx["copilot"]["replay"]["active"] and ctx["chart"]["formingCandle"] is None, (max(times), cursor)
    assert "aria" not in ctx["chart"] and "higherTimeframe" not in ctx["chart"], "nothing computed from the live chart leaks into a replay"
    call("get_candles", {"count": 120})
    reqs = say(page, "show me the last candles")
    gr = reqs[1]["contents"][-1]["parts"][0]["functionResponse"]["response"]
    assert gr.get("ok"), gr
    got = gr["closed"]
    assert max(c[0] for c in got) <= cursor
    call("compare_timeframes", {"timeframes": ["4h"]})
    reqs = say(page, "compare to the 4h")
    assert reqs[1]["contents"][-1]["parts"][0]["functionResponse"]["response"]["ok"] is False
    blob = json.dumps(M.seen[-4:])
    future = page.evaluate("REPLAY.total() > REPLAY.cursor()")
    assert future
    page.evaluate("REPLAY.exit()")
    print("ok  replay: snapshot, candles and tools stop at the cursor; other timeframes refused")


def check_quota(page):
    page.evaluate("VOICE.open(false)")
    M.script.append({"status": 429, "body": {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}}})
    say(page, "Analyze this chart")
    log = page.evaluate("VOICE.log.slice(-3).map(m => m.text)")
    assert any("reached its current AI usage allowance" in t for t in log), log
    assert any("Structure" in t or "structure" in t for t in log), "the app's own analysis still answered"
    n = len(M.seen)
    page.evaluate("AI.st.paused = false")
    say(page, "Analyze this chart")            # the server holds the pause: the main model is not called again today
    assert all(r["model"] != "gemini-3.8-flash" for r in M.seen[n:])
    aria_ai.set_cooldown("main", 0); aria_ai.set_cooldown("lite", 0)
    page.evaluate("AI.refresh(true)")
    print("ok  quota: the allowance message, local analysis still works, the provider is not retried, no paid fallback")


def check_voice(page):
    page.evaluate("AI.st.paused = false; AI.st.enabled = true")
    page.evaluate("window.__said = []; VOICE.cfg.handsFree = false")
    page.evaluate("VOICE.listen()")
    page.wait_for_function("window.__recs.length && VOICE.state === 'listening'")
    page.evaluate("window.__recs[window.__recs.length - 1].say('hello aria')")
    page.wait_for_function("!AI.busy && window.__said.length > 0", timeout=10000)
    page.wait_for_timeout(200)
    assert any("Hello!" in s for s in page.evaluate("window.__said"))
    new = page.evaluate("VOICE.log.slice(-3).map(m => m.who + ':' + m.text.slice(0, 20))")
    assert new[-2:] == ["you:hello aria", "vx:[mock] Hello! Would "] and new[0] != "you:hello aria", new
    # interruption: talking over a streaming answer stops it cleanly
    M.script.append({"parts": [{"text": "[mock] " + "A long careful answer about structure. " * 12}], "delay": 0.08})
    page.evaluate("window.__cancels = 0; const c = speechSynthesis.cancel; speechSynthesis.cancel = () => { window.__cancels++; }")
    say(page, "explain the structure in detail", wait_done=False)
    page.wait_for_function("AI.busy && VOICE.log.slice(-1)[0].text.length > 20", timeout=8000)
    page.evaluate("VOICE.listen()")
    page.wait_for_function("!AI.busy", timeout=8000)
    page.wait_for_timeout(300)
    st = page.evaluate("({ state: VOICE.state, last: VOICE.log.slice(-1)[0].text, convoEnd: AI.convo.slice(-1)[0], cancels: window.__cancels, recs: window.__recs.length })")
    assert st["state"] == "listening" and st["last"].endswith("…") and st["cancels"] >= 1, st
    assert st["convoEnd"]["role"] == "model" and "functionCall" not in json.dumps(st["convoEnd"]), "no dangling turn"
    page.evaluate("VOICE.stopListening(true)")
    page.wait_for_function("VOICE.state !== 'listening'")
    page.evaluate("window.__recs[window.__recs.length - 1].onend && window.__recs[window.__recs.length - 1].onend()")
    assert page.evaluate("VOICE.rec") is None, "no recognizer left running"
    print("ok  voice: speech in, AI answer spoken, interruption stops the stream and speech without duplicates or orphans")


def main():
    srv, base = serve()
    args = ["--ignore-certificate-errors"] + ([f"--proxy-server={PROXY}", "--proxy-bypass-list=127.0.0.1;localhost;<local>"] if PROXY else [])
    with sync_playwright() as p:
        b = p.chromium.launch(args=args)
        page = b.new_context(viewport={"width": 1280, "height": 860}).new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(base + "/app", wait_until="domcontentloaded")
        page.wait_for_function("typeof AI !== 'undefined' && typeof COPILOT !== 'undefined' && typeof OT !== 'undefined'")
        page.wait_for_timeout(1500)
        page.evaluate(SETUP)
        page.evaluate("CH.setData ? CH.setData(S.candles) : CH.candle.setData(S.candles.map(c => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close })))")
        page.evaluate("localStorage.removeItem('protrader.aria.chat.v1'); AI.convo = []")
        page.evaluate("VOICE.open(false)")
        page.wait_for_function("AI.st && AI.st.enabled", timeout=5000)
        assert page.evaluate("document.getElementById('cpAiNote').textContent").startswith("AI Test provider (no AI model)")
        check_conversation(page)
        check_context(page)
        check_pine(page)
        check_analysis(page)
        check_tools(page)
        check_memory(page)
        check_risk_and_isolation(page)
        check_no_data(page)
        check_quota(page)
        check_replay(page)
        check_voice(page)
        if os.environ.get("SHOTS"):
            page.evaluate("VOICE.open(false); COPILOT.setMode('talk')")
            call("draw_analysis", {"layers": ["zones", "structure"]}, "[mock] I've marked the nearest support and resistance and the last swings.")
            say(page, "Draw key levels")
            page.screenshot(path=os.path.join(os.environ["SHOTS"], "aria_ai_desktop.png"))
        assert not errs, errs
        b.close()
    srv.should_exit = True
    print("all ARIA AI browser checks passed")


if __name__ == "__main__":
    main()
