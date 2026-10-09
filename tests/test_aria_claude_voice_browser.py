"""
ARIA with Claude reasoning and ElevenLabs voice, end to end in a real browser,
with BOTH providers replaced by local stand-ins (no real request, no credit):
  * Anthropic: ClaudeProvider's HTTP session is swapped for a scripted SSE stream
    in this process, so the real server code (ledger, gates, wire format) runs.
  * ElevenLabs: aria_voice.py talks to stub routes on this same test server
    (ARIA_ELEVEN_API_ROOT is honoured only when ARIA_AI_ALLOW_MOCK=1).
Chromium's fake microphone supplies audio; a real MP3 (ffmpeg) is played.
   python3 tests/test_aria_claude_voice_browser.py        (SHOTS=dir for screenshots)
"""
import json
import os
import subprocess
import sys
import tempfile
import time

import requests

TMP = tempfile.mkdtemp()
FAKE_ANTHROPIC = "sk-ant-FAKE-browser-only-00000000000000000000"
FAKE_ELEVEN = "sk_eleven_FAKE_browser_only_0000000000000000"
FAKE_GEMINI = "AIzaFAKE-browser-only-000000000000000"
OWNER = "owner-key-claude-voice-test"
os.environ.update({
    "ACCOUNTS_DB": os.path.join(TMP, "accounts.db"), "ARIA_AI_DB": os.path.join(TMP, "aria.db"),
    "ARIA_AI_ALLOW_MOCK": "1", "ARIA_AI_USER_PER_MIN": "200", "ARIA_AI_GUEST_PER_DAY": "500", "ARIA_AI_IP_PER_DAY": "500",
    "ARIA_AI_USER_PER_DAY": "500", "ARIA_AI_RPM_MAIN": "200", "ARIA_AI_RPM_LITE": "200", "ARIA_CLAUDE_RPM": "500", "SENTINEL_ADMIN_KEY": OWNER,
    # Claude, every check confirmed (in a test), on a provisioned persistent ledger
    "ARIA_AI_PROVIDER": "claude", "ARIA_CLAUDE_ENABLED": "1", "ANTHROPIC_API_KEY": FAKE_ANTHROPIC,
    "CLAUDE_PREPAID_ONLY_CONFIRMED": "1", "CLAUDE_AUTO_RELOAD_DISABLED_CONFIRMED": "1", "CLAUDE_NO_PURCHASED_CREDITS_CONFIRMED": "1",
    "CLAUDE_ISOLATED_ALLOCATION_CONFIRMED": "1", "CLAUDE_PRICING_CONFIRMED": "1", "CLAUDE_PERSISTENT_LEDGER_CONFIRMED": "1",
    "CLAUDE_CREDIT_VERIFIED_AT": str(time.time() - 10), "CLAUDE_CREDIT_EXPIRES_AT": str(time.time() + 86400),
    "CLAUDE_CREDIT_PERIOD": "browser-test-cycle", "ARIA_CLAUDE_CREDIT_BUDGET_USD": "20",
    "ARIA_CLAUDE_BUDGET_DB": os.path.join(TMP, "claude-ledger.db"),
    # the approved free-tier fallback exists, to prove it is never used after a Claude request went out
    "ARIA_AI_GEMINI_FALLBACK": "1", "GEMINI_API_KEY": FAKE_GEMINI, "GEMINI_FREE_TIER_CONFIRMED": "1",
    # ElevenLabs, every check confirmed (in a test)
    "ARIA_ELEVEN_ENABLED": "1", "ELEVEN_USAGE_BILLING_OFF_CONFIRMED": "1", "ELEVEN_PRICING_CONFIRMED": "1",
    "ELEVEN_PERSISTENT_LEDGER_CONFIRMED": "1", "ELEVENLABS_API_KEY": FAKE_ELEVEN, "ARIA_ELEVEN_VOICE_ID": "VoiceFakeBrowser0001",
    "ARIA_ELEVEN_ALLOWANCE_CREDITS": "100000", "ARIA_ELEVEN_RESERVE_CREDITS": "20000",
    "ARIA_ELEVEN_LEDGER_DB": os.path.join(TMP, "voice-ledger.db"), "ARIA_ELEVEN_STT_CREDITS_PER_MINUTE": "100",
    "ARIA_ELEVEN_TTS_PER_DAY": "500", "ARIA_ELEVEN_TTS_PER_MIN": "100", "ARIA_ELEVEN_TTS_GUEST_PER_DAY": "500",
})
ENV = {k: os.environ[k] for k in list(os.environ) if k.startswith(("ARIA_", "CLAUDE_", "ANTHROPIC_", "GEMINI_", "ELEVEN", "ACCOUNTS_", "SENTINEL_"))}
sys.path.insert(0, os.path.dirname(__file__))
from test_aria_ai_browser import app, serve, PROXY, SETUP     # noqa: E402
os.environ.update(ENV)                                          # that module sets the mock provider on import; ours wins
import aria_ai                                                  # noqa: E402
import aria_voice                                               # noqa: E402
from claude_credits import CreditLedger                         # noqa: E402
from fastapi import Request                                     # noqa: E402
from fastapi.responses import JSONResponse, Response            # noqa: E402
from playwright.sync_api import sync_playwright                 # noqa: E402

app.include_router(aria_voice.router)
CreditLedger(aria_ai.claude_config()).provision()
aria_voice.VoiceLedger(aria_voice.VoiceConfig()).provision()


def mp3(seconds):
    return subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}",
                           "-ac", "1", "-ar", "22050", "-b:a", "48k", "-f", "mp3", "pipe:1"], capture_output=True, check=True).stdout


SHORT, LONG = mp3(0.8), mp3(6)

# ── the Anthropic stand-in ────────────────────────────────────────────────────
CLAUDE = {"script": [], "bodies": [], "headers": []}


class Stream:
    def __init__(self, events):
        self.status_code, self.events = 200, events
    def iter_lines(self, decode_unicode=False):
        for e in self.events:
            yield ("data: " + json.dumps(e)).encode()
    def close(self):
        pass


def events_for(step):
    ev, i = [{"type": "message_start", "message": {"usage": {"input_tokens": 900}}}], 0
    if step.get("thinking"):
        ev += [{"type": "content_block_start", "index": i, "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
               {"type": "content_block_delta", "index": i, "delta": {"type": "thinking_delta", "thinking": step["thinking"]}},
               {"type": "content_block_delta", "index": i, "delta": {"type": "signature_delta", "signature": step["signature"]}},
               {"type": "content_block_stop", "index": i}]
        i += 1
    if step.get("text"):
        ev += [{"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}}]
        for k in range(0, len(step["text"]), 40):
            ev.append({"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": step["text"][k:k + 40]}})
        ev.append({"type": "content_block_stop", "index": i}); i += 1
    if step.get("tool"):
        name, args, tid = step["tool"]
        ev += [{"type": "content_block_start", "index": i, "content_block": {"type": "tool_use", "id": tid, "name": name, "input": {}}},
               {"type": "content_block_delta", "index": i, "delta": {"type": "input_json_delta", "partial_json": json.dumps(args)}},
               {"type": "content_block_stop", "index": i}]
    ev += [{"type": "message_delta", "delta": {"stop_reason": "tool_use" if step.get("tool") else "end_turn"}, "usage": {"output_tokens": 120}},
           {"type": "message_stop"}]
    return ev


class FakeAnthropic:
    def post(self, url, json=None, headers=None, **kw):
        assert url == "https://api.anthropic.com/v1/messages" and kw.get("allow_redirects") is False
        CLAUDE["bodies"].append(json); CLAUDE["headers"].append(headers)
        step = CLAUDE["script"].pop(0) if CLAUDE["script"] else {"text": "Observed: the chart loaded. What would you like to look at?"}
        if step.get("timeout"):
            raise requests.Timeout("upstream timeout " + FAKE_ANTHROPIC)
        return Stream(events_for(step))


_init = aria_ai.ClaudeProvider.__init__
def _fake_init(self, key):
    _init(self, key)
    self._http = FakeAnthropic()
aria_ai.ClaudeProvider.__init__ = _fake_init

GEMINI_CALLS = []
def _gemini_stream(self, **kw):
    GEMINI_CALLS.append(kw["model"])
    yield {"type": "text", "text": "Gemini fallback answer."}
    yield {"type": "done", "content": {"role": "model", "parts": [{"text": "Gemini fallback answer."}]}, "finish": "STOP", "usage": {}}
aria_ai.GeminiProvider.stream_response = _gemini_stream

# ── the ElevenLabs stand-in (routes on this server) ───────────────────────────
STUB = {"sub": {}, "tts": [], "stt": [], "deleted": [], "tts_status": 200, "audio": SHORT, "transcript": "what is the trend on this chart"}


def subscription(**kw):
    s = {"tier": "creator", "character_count": 20000, "character_limit": 121000, "max_credit_limit_extension": 0,
         "has_open_invoices": False, "current_overage": {"amount": 0, "currency": "usd"}, "status": "active",
         "next_character_count_reset_unix": int(time.time()) + 20 * 86400}
    s.update(kw)
    return s


STUB["sub"] = subscription()


@app.get("/stub-eleven/v1/user/subscription")
def _stub_sub(request: Request):
    assert request.headers.get("xi-api-key") == FAKE_ELEVEN
    return STUB["sub"]


@app.post("/stub-eleven/v1/text-to-speech/{voice}/stream")
async def _stub_tts(voice: str, request: Request):
    body = await request.json()
    STUB["tts"].append({"voice": voice, "body": body, "query": dict(request.query_params), "key": request.headers.get("xi-api-key")})
    if STUB["tts_status"] != 200:
        return JSONResponse({"detail": {"status": "quota_exceeded"}}, status_code=STUB["tts_status"])
    return Response(STUB["audio"], media_type="audio/mpeg", headers={"history-item-id": f"hist{len(STUB['tts']):04d}x"})


@app.post("/stub-eleven/v1/speech-to-text")
async def _stub_stt(request: Request):
    if STUB.get("stt_delay"):
        import asyncio
        await asyncio.sleep(STUB["stt_delay"])
    form = await request.form()
    f = form["file"]
    data = await f.read()
    STUB["stt"].append({"bytes": len(data), "model": form.get("model_id"), "format": form.get("file_format"), "lang": form.get("language_code"),
                        "key": request.headers.get("xi-api-key")})
    return {"text": STUB["transcript"], "language_code": "en", "transcription_id": f"tr{len(STUB['stt']):04d}x"}


@app.delete("/stub-eleven/v1/history/{item}")
@app.delete("/stub-eleven/v1/speech-to-text/transcripts/{item}")
def _stub_delete(item: str):
    STUB["deleted"].append(item)
    return {"status": "ok"}


# ── helpers ───────────────────────────────────────────────────────────────────

def ctx_of(body):
    """The workspace snapshot exactly as Claude received it (the newest user message)."""
    for m in reversed(body["messages"]):
        if m["role"] == "user":
            for b in m["content"]:
                if b.get("type") == "text" and b["text"].startswith("[WORKSPACE CONTEXT"):
                    return json.loads(b["text"].split("\n", 1)[1])
    return None


def ask(page, text):
    n = len(CLAUDE["bodies"])
    page.evaluate("window.__said = []")
    page.fill("#vxInput", text)
    page.press("#vxInput", "Enter")
    page.wait_for_function("!AI.busy && VOICE.state !== 'thinking'", timeout=20000)
    return CLAUDE["bodies"][n:]


def wait_quiet(page):
    page.wait_for_function("VOICE.state === 'idle' && !ELV._resolve", timeout=20000)


def last_ai(page):
    return page.evaluate("(() => { const m = VOICE.log.filter(x => x.ai).slice(-1)[0]; return m ? { text: m.text, model: m.model, tools: m.tools } : null; })()")


def until(cond, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


def ok(msg):
    print("ok ", msg)


HTF = """
(() => {
  const tf = 14400, t0 = Math.floor(Date.now() / 1000 / tf) * tf - 179 * tf;
  const cd = Array.from({ length: 180 }, (_, i) => { const base = 43000 + i * 9, o = base + Math.sin(i / 5) * 60, c = base + 9 + Math.sin((i + 1) / 5) * 60;
    return { time: t0 + i * tf, open: o, high: Math.max(o, c) + 25, low: Math.min(o, c) - 25, close: c, vol: 0 }; });
  MTF.data[S.sym] = Object.assign(MTF.data[S.sym] || {}, { '4h': cd });
  MTF.refresh = () => {};
  S.wsConnected = true;          // the cloud test browser cannot reach Deriv; the feed state is set by the test
  return true;
})()
"""


# ── checks ────────────────────────────────────────────────────────────────────

def check_guest_default(page):
    # natural voice is for signed-in accounts and the owner unless guests are explicitly allowed
    os.environ.pop("ARIA_ELEVEN_GUESTS", None)
    page.evaluate("ELV.refresh(true).then(() => AI.renderNote())")
    page.wait_for_function("ELV.st && ELV.st.tts === false")
    assert "voice: ElevenLabs" not in page.evaluate("document.getElementById('cpAiNote').textContent")
    os.environ["ARIA_ELEVEN_GUESTS"] = "1"                         # the rest of this run plays a permitted user
    page.evaluate("ELV.refresh(true).then(() => AI.renderNote())")
    page.wait_for_function("ELV.st && ELV.st.tts === true && document.getElementById('cpAiNote').textContent.includes('voice: ElevenLabs')")
    ok("guests: no natural voice unless ARIA_ELEVEN_GUESTS=1; the notice only names ElevenLabs when it is really on")


def check_account_stays_on_device(page):
    n = len(STUB["tts"])
    page.evaluate("window.__said = []")
    page.fill("#vxInput", "what is my balance")
    page.press("#vxInput", "Enter")
    page.wait_for_function("window.__said.some(t => t.includes('balance'))", timeout=8000)
    assert len(STUB["tts"]) == n, "an account answer must never be sent to ElevenLabs"
    page.evaluate("VOICE.cfg.voice = ''")
    page.evaluate("VOICE.say('This is how I sound.')")                 # the voice-picker preview: device voice, no credit
    time.sleep(0.3)
    assert len(STUB["tts"]) == n
    # a lesson is ARIA teaching: it may use the natural voice
    page.evaluate("COPILOT.openLesson('structure', {})")
    until(lambda: len(STUB["tts"]) == n + 1)
    assert STUB["tts"][-1]["body"]["text"].startswith("Market structure. Price moves in swings")
    wait_quiet(page)
    ok("privacy: balances and other account answers, and the voice preview, use the device voice only; lessons use the natural voice")


def check_mic_races(page):
    page.evaluate("""(() => { window.__streams = []; const g = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      navigator.mediaDevices.getUserMedia = async c => { await new Promise(r => setTimeout(r, 400)); const s = await g(c); window.__streams.push(s); return s; }; })()""")
    live = "window.__streams.reduce((n, s) => n + s.getTracks().filter(t => t.readyState === 'live').length, 0)"
    n = len(STUB["stt"])
    # two quick taps while the mic is still opening: one recording, then Cancel releases every track
    page.evaluate("ELV.record(); ELV.record()")
    page.wait_for_function("!!ELV.rec", timeout=5000)
    assert page.evaluate("window.__streams.length") == 1
    page.click("#vxCancel")
    page.wait_for_function(f"{live} === 0", timeout=3000)
    # closing the sheet while the mic opens: no recording starts, nothing is sent, the mic is released
    page.evaluate("ELV.record(); setTimeout(() => VOICE.close(), 50)")
    page.wait_for_timeout(1500)
    assert page.evaluate("ELV.rec") is None and page.evaluate(live) == 0 and len(STUB["stt"]) == n
    assert page.evaluate("VOICE.open_") is False
    page.evaluate("VOICE.open(false)")
    # cancelling while the words are on their way back: they are not used
    STUB["stt_delay"] = 1.5
    logs = page.evaluate("VOICE.log.filter(m => m.who === 'you').length")
    page.click("#vxOrb")
    page.wait_for_function("ELV.rec && ELV.rec.len > 16000 * 0.8", timeout=8000)
    page.click("#vxOrb")
    page.wait_for_function("!!ELV.tctrl", timeout=3000)
    page.evaluate("ELV.cancelRec()")
    page.wait_for_timeout(2200)
    assert page.evaluate("VOICE.log.filter(m => m.who === 'you').length") == logs and page.evaluate("VOICE.state") == "idle"
    STUB["stt_delay"] = 0
    page.evaluate("(() => { delete navigator.mediaDevices.getUserMedia; return true; })()")
    ok("mic: taps while it opens start one recording; Cancel or closing releases every track and sends nothing; a cancelled transcript is not used")


def check_notice(page):
    note = page.evaluate("document.getElementById('cpAiNote').textContent")
    assert "Claude Sonnet 5.5 (Anthropic API, promotional credits)" in note and "voice: ElevenLabs" in note, note
    assert "does not use API inputs or outputs to train" in note and "no name, email, balance" in note, note
    page.evaluate("VOICE.toggleSettings()")
    html = page.evaluate("document.getElementById('vxSettings').innerHTML")
    assert "natural voice (ElevenLabs)" in html and "vxElevenMic" not in html            # a guest: spoken replies, never their voice
    assert "ARIA sends the text of its own reply" in html
    page.evaluate("VOICE.toggleSettings()")
    ok("notice: Claude Sonnet 5.5 on promotional credits, its training/privacy terms, ElevenLabs voice named; guests get no voice upload")


def check_reasoning_and_tools(page):
    page.evaluate(HTF)
    CLAUDE["script"] = [
        {"thinking": "Start from structure, then invalidation.", "signature": "c2lnLW9uZQ==",
         "tool": ("draw_analysis", {"layers": ["structure", "invalidation"]}, "toolu_struct1")},
        {"text": "**Observed:** the last swings are drawn on your chart. **Interpretation:** structure leans up, but the 15m and 4h disagree, so conviction is low. "
                 "**Scenarios (hypothetical):** if price closes above the last swing high the trend continues; if it closes below the last swing low the idea is wrong. "
                 "**Risk:** the stop belongs beyond that low. **Uncertainty:** the forming candle can still change. Which swing would you use as invalidation?"},
    ]
    before = CreditLedger(aria_ai.claude_config()).available()
    bodies = ask(page, "Walk me through the evidence on this chart")
    assert len(bodies) == 2, len(bodies)
    b0, b1 = bodies
    assert b0["model"] == "claude-sonnet-5-5" and b0["thinking"] == {"type": "between_tools"} and b0["output_config"]["effort"] in ("low", "medium")
    assert "**Observed:**" in b0["system"] and "Scenarios (hypothetical)" in b0["system"] and {t["name"] for t in b0["tools"]} == aria_ai.TOOL_NAMES
    ctx = ctx_of(b0)
    ch = ctx["chart"]
    assert ch["symbol"] == "R_75" and ch["dataQuality"]["closedCandles"] >= 200 and ch["dataQuality"]["formingCandleIncluded"] is True
    assert ch["dataQuality"]["feedConnected"] is True and ch["dataQuality"]["higherTimeframeLoaded"] is True, ch["dataQuality"]
    assert ch["higherTimeframe"]["timeframe"] == "4h" and ch["higherTimeframe"]["trend"] in ("up", "down", "none")
    assert ch["timeframeAgreement"].split(":")[0] in ("aligned", "conflict", "unclear")
    gates = ch["aria"]["gates"]
    assert len(gates) == ch["aria"]["gatesTotal"] and {"gate", "pass", "detail"} <= set(gates[0]) and not any("✓" in g["detail"] or "✗" in g["detail"] for g in gates)
    assert "balance" not in json.dumps(ctx) and "10000" not in json.dumps(ctx["chart"].get("aria", {}))
    # the tool round carries Claude's reasoning block back unchanged, then the verified tool result
    a = [m for m in b1["messages"] if m["role"] == "assistant"][-1]
    assert a["content"][0] == {"type": "thinking", "thinking": "Start from structure, then invalidation.", "signature": "c2lnLW9uZQ=="}
    assert a["content"][1]["type"] == "tool_use" and a["content"][1]["id"] == "toolu_struct1"
    tr = b1["messages"][-1]["content"][0]
    assert tr["type"] == "tool_result" and tr["tool_use_id"] == "toolu_struct1" and json.loads(tr["content"])["verifiedOnChart"] >= 2
    rules = page.evaluate("COPILOT.ours().map(d => d.aria.rule)")
    assert "structure" in rules and "invalidation" in rules, rules
    m = last_ai(page)
    assert m["text"].startswith("**Observed:**") and m["model"] == "Claude Sonnet 5.5 · promotional credits", m
    assert "Checking" not in m["text"] and "Start from structure" not in page.evaluate("document.getElementById('vxLog').textContent")
    html = page.evaluate("document.getElementById('vxLog').innerHTML")
    assert "<b>Observed:</b>" in html and "<b>Scenarios (hypothetical):</b>" in html
    # two Claude requests, two reservations from the persistent ledger
    after = CreditLedger(aria_ai.claude_config()).available()
    assert after < before
    for h in CLAUDE["headers"]:
        assert h["x-api-key"] == FAKE_ANTHROPIC and h["anthropic-version"] == "2023-06-01"
    ok(f"reasoning: Sonnet 5.5 at between_tools, context with data quality, {len(gates)} ARIA gates, 4h agreement; drew structure + invalidation; "
       f"reasoning block returned verbatim; labelled Observed/Interpretation/Scenarios; {before - after} micro-USD reserved")
    return m


def check_spoken_reply(page):
    wait_quiet(page)
    t = STUB["tts"][-1]
    assert t["voice"] == "VoiceFakeBrowser0001" and t["key"] == FAKE_ELEVEN and t["body"]["model_id"] == "eleven_flash_v2_5"
    assert t["query"] == {"output_format": "mp3_44100_64"} and "**" not in t["body"]["text"] and t["body"]["text"].startswith("Observed:")
    assert page.evaluate("window.__said") == []                       # the device voice was not used
    time.sleep(0.3)
    assert STUB["deleted"] and STUB["deleted"][-1].startswith("hist")
    ok("spoken: the reply (markdown stripped) became ElevenLabs speech with the configured voice; device voice silent; history item deleted after use")


def check_continuity(page):
    page.evaluate("ELV.failedAt = 0")
    CLAUDE["script"] = [{"text": "Following on from the swing low we marked: a close below it invalidates the long idea. What would you do if it held?"}]
    page.evaluate("AI._lastChart = 'frxXAUUSD 1h'")                     # as if the student had come from another chart
    bodies = ask(page, "What would invalidate that?")
    msgs = bodies[0]["messages"]
    texts = [b.get("text", "") for m in msgs for b in m["content"] if b.get("type") == "text"]
    assert any("Walk me through the evidence" in t for t in texts) and any(t.startswith("**Observed:**") for t in texts)
    assert not any(b.get("type") == "thinking" for m in msgs for b in m["content"])        # older reasoning omitted (allowed; saves credit)
    assert ctx_of(bodies[0])["chart"]["changedSinceLastTurn"] == {"from": "frxXAUUSD 1h", "to": "R_75 15m"}
    assert sum(1 for m in msgs if m["role"] == "user" and any(b.get("text", "").startswith("[WORKSPACE") for b in m["content"])) == 1
    wait_quiet(page)
    ok("continuity: earlier turns go back, old reasoning blocks omitted, one snapshot, a chart change is flagged")


def check_oracle(page):
    px = page.evaluate("S.candles[S.candles.length - 2].close")
    CLAUDE["script"] = [{"tool": ("check_plan_with_oracle", {"side": "buy", "stop": round(px - 150, 2), "target": round(px + 250, 2), "reason": "trend"}, "toulu_or1")},
                        {"text": "ORACLE says it plainly; here is what its evidence means."}]
    bodies = ask(page, "Ask ORACLE about a long with a stop 150 below")
    res = json.loads(bodies[1]["messages"][-1]["content"][0]["content"])
    assert res["ok"] and res["oracle"] in ("SUPPORTED", "INCOMPLETE", "CONTRADICTED"), res
    assert res["higherTimeframe"]["timeframe"] == "4h"                                  # ORACLE now weighs the higher timeframe here too
    assert any("4h chart" in e["text"] for e in res["evidence"]), res["evidence"]
    wait_quiet(page)
    CLAUDE["script"] = [{"text": "Your last check stands."}]
    ctx = ctx_of(ask(page, "Remind me what the last verdict was")[0])
    assert ctx["chart"]["lastOracleCheck"]["verdict"] == res["oracle"] and ctx["chart"]["lastOracleCheck"]["side"] == "buy"
    wait_quiet(page)
    ok(f"ORACLE: {res['oracle']} with the 4h evidence; the verdict stays in the session context for follow-ups")


def check_stop_and_barge_in(page, shots):
    STUB["audio"] = LONG
    CLAUDE["script"] = [{"text": "This is a long spoken explanation of market structure. " * 6}]
    ask(page, "Talk me through this slowly")
    page.wait_for_function("VOICE.state === 'speaking' && ELV.el && !ELV.el.paused && ELV.el.currentTime > 0.2", timeout=15000)
    assert page.is_visible("#vxStop") and page.evaluate("document.getElementById('vxPill').textContent") == "Speaking · ElevenLabs"
    if shots:
        page.screenshot(path=os.path.join(shots, "aria_speaking_desktop.png"))
    page.click("#vxStop")
    page.wait_for_function("VOICE.state === 'idle'", timeout=3000)
    assert page.evaluate("ELV.el.paused") and not page.is_visible("#vxStop") and page.evaluate("window.__said") == []
    assert "Stopped speaking" in page.evaluate("document.getElementById('vxHeard').textContent")
    # interrupting by talking: tap the orb while ARIA speaks → speech stops, listening starts (device speech input)
    CLAUDE["script"] = [{"text": "Another long answer that will be interrupted. " * 6}, {"text": "You asked about the trend: it is shown on the chart."}]
    ask(page, "Keep going, I am listening")
    page.wait_for_function("VOICE.state === 'speaking' && ELV.el && !ELV.el.paused", timeout=15000)
    recs = page.evaluate("window.__recs.length")
    page.click("#vxOrb")
    page.wait_for_function(f"VOICE.state === 'listening' && window.__recs.length === {recs + 1}", timeout=3000)
    assert page.evaluate("ELV.el.paused") and not page.evaluate("ELV._resolve")
    n = len(CLAUDE["bodies"])
    page.evaluate("window.__recs[window.__recs.length - 1].say('what is the trend')")
    page.wait_for_function("VOICE.log.some(m => m.who === 'you' && m.text === 'what is the trend')", timeout=15000)
    try:
        until(lambda: len(CLAUDE["bodies"]) == n + 1)
    except AssertionError:
        print(page.evaluate("JSON.stringify({log: VOICE.log.slice(-4).map(m => [m.who, m.text.slice(0, 80)]), st: AI.st, state: VOICE.state, parse: VOICE.parse('what is the trend')})"))
        raise
    page.wait_for_function("!AI.busy && VOICE.log.some(m => m.ai && m.text.startsWith('You asked about the trend'))", timeout=15000)
    wait_quiet(page)
    STUB["audio"] = SHORT
    ok("controls: Stop speaking halts the audio at once; tapping the orb interrupts ARIA and listens; the new question is answered")


def check_voice_failures(page):
    # ElevenLabs refuses → this device's voice reads the reply, with a one-time note; no retry
    STUB["tts_status"] = 500
    n = len(STUB["tts"])
    CLAUDE["script"] = [{"text": "Short answer while the natural voice is down."}]
    ask(page, "Make that shorter for me")
    page.wait_for_function("window.__said.length > 0", timeout=10000)
    assert page.evaluate("window.__said")[0].startswith("Short answer") and len(STUB["tts"]) == n + 1, (page.evaluate("window.__said"), len(STUB["tts"]), n)
    assert page.evaluate("VOICE.log.some(m => m.note && m.text.includes('natural voice is unavailable'))"), page.evaluate("JSON.stringify({w: ELV.warned, log: VOICE.log.slice(-5).map(m => [m.who, !!m.note, m.text.slice(0, 70)])})")
    STUB["tts_status"] = 200
    wait_quiet(page)
    # usage-based billing switched on in the account → refused BEFORE any speech request; device voice instead
    page.evaluate("ELV.failedAt = 0")
    aria_voice._sub.update(at=0.0, data=None, spent=0)
    STUB["sub"] = subscription(max_credit_limit_extension="unlimited")
    n = len(STUB["tts"])
    CLAUDE["script"] = [{"text": "Overage would be possible, so I am using the device voice."}]
    ask(page, "And one more line")
    page.wait_for_function("window.__said.length > 0", timeout=10000)
    assert len(STUB["tts"]) == n
    # the reserve for Alex and the website agent: too little left in the shared pool → refused before speaking
    page.evaluate("ELV.failedAt = 0")
    aria_voice._sub.update(at=0.0, data=None, spent=0)
    STUB["sub"] = subscription(character_count=121000 - 20010)
    CLAUDE["script"] = [{"text": "This sentence is longer than the ten credits left above the reserve."}]
    ask(page, "Once more please")
    page.wait_for_function("window.__said.length > 0", timeout=10000)
    assert len(STUB["tts"]) == n
    aria_voice._sub.update(at=0.0, data=None, spent=0)
    STUB["sub"] = subscription()
    page.evaluate("ELV.failedAt = 0")
    wait_quiet(page)
    ok("voice failures: an ElevenLabs error falls back to the device voice (noted once, not retried); overage-capable billing or the agents' reserve stop speech before any request")


def check_recording(page, shots):
    # a student cannot send their voice; the owner can, after choosing it
    r = page.evaluate("fetch('/api/aria/voice/transcribe', { method: 'POST', headers: Object.assign(AI.headers(), { 'X-Audio-Format': 'pcm_s16le_16' }), body: new Uint8Array(32000) }).then(r => r.status)")
    assert r == 403
    page.evaluate(f"localStorage.setItem('protrader.sentinelKey', '{OWNER}')")
    page.evaluate("ELV.refresh(true)")
    page.wait_for_function("ELV.st && ELV.st.stt === true")
    page.evaluate("VOICE.toggleSettings()")
    page.check("#vxElevenMic")
    assert "records only between your two taps" in page.evaluate("document.getElementById('vxSettings').textContent")
    assert "PROTrader stores no audio" in page.evaluate("document.getElementById('vxSettings').textContent")
    page.evaluate("VOICE.toggleSettings()")
    # deliberate: an ARIA question never starts a recording by itself
    page.evaluate("VOICE.cfg.handsFree = true; VOICE.reply('Which swing would you use?', { ask: true, spoken: true })")
    page.wait_for_timeout(900)
    assert page.evaluate("ELV.rec") is None and page.evaluate("VOICE.state") != "listening"
    # tap → recording (visible), cancel → nothing sent, mic released
    n = len(STUB["stt"])
    page.click("#vxOrb")
    page.wait_for_function("ELV.rec && VOICE.state === 'listening'", timeout=8000)
    assert page.is_visible("#vxRec") and page.is_visible("#vxCancel") and page.evaluate("document.getElementById('vxPill').textContent") == "Recording"
    if shots:
        page.wait_for_timeout(1200)
        page.screenshot(path=os.path.join(shots, "aria_recording_desktop.png"))
    page.click("#vxCancel")
    page.wait_for_function("!ELV.rec && VOICE.state === 'idle'")
    assert len(STUB["stt"]) == n and "Nothing was sent" in page.evaluate("document.getElementById('vxHeard').textContent")
    assert not page.is_visible("#vxRec")
    # tap → speak → tap: one upload of 16 kHz PCM, the transcript becomes the question
    CLAUDE["script"] = [{"text": "On this chart the structure is drawn; the 4h decides the bias."}]
    b = len(CLAUDE["bodies"])
    page.click("#vxOrb")
    page.wait_for_function("ELV.rec && ELV.rec.len > 16000 * 1.5", timeout=10000)
    page.click("#vxOrb")
    page.wait_for_function(f"VOICE.log.some(m => m.who === 'you' && m.text === '{STUB['transcript']}')", timeout=15000)
    page.wait_for_function("!AI.busy", timeout=15000)
    s = STUB["stt"][-1]
    assert len(STUB["stt"]) == n + 1 and s["model"] == "scribe_v2" and s["format"] == "pcm_s16le_16" and s["lang"] == "en" and s["key"] == FAKE_ELEVEN
    assert 16000 * 2 * 1.4 <= s["bytes"] <= 16000 * 2 * 6, s["bytes"]
    assert len(CLAUDE["bodies"]) == b + 1
    first_user = [m for m in CLAUDE["bodies"][-1]["messages"] if m["role"] == "user"][-1]["content"][0]["text"]
    assert first_user == STUB["transcript"]
    assert page.evaluate("ELV.rec") is None
    time.sleep(0.3)
    assert any(d.startswith("tr") for d in STUB["deleted"])
    wait_quiet(page)
    page.evaluate("VOICE.cfg.elevenMic = false; VOICE.cfg.handsFree = false; localStorage.removeItem('protrader.sentinelKey'); ELV.refresh(true)")
    ok(f"recording: owner-only, opt-in, starts and ends with a tap, visible REC + timer + Cancel (nothing sent), {s['bytes']} bytes of PCM once, transcript deleted, answered by Claude")


def check_no_retry_or_switch(page):
    # an ambiguous Claude failure: reported, not retried, and NOT handed to the Gemini fallback
    g = len(GEMINI_CALLS)
    CLAUDE["script"] = [{"timeout": True}]
    n = len(CLAUDE["bodies"])
    ask(page, "Talk me through what could go wrong here")
    assert len(CLAUDE["bodies"]) == n + 1 and len(GEMINI_CALLS) == g
    log = page.evaluate("document.getElementById('vxLog').textContent")
    assert "did not answer in time" in log and FAKE_ANTHROPIC not in log
    wait_quiet(page)
    # credits used up BEFORE a request: the approved free-tier fallback answers, labelled as such
    cfg = aria_ai.claude_config()
    CreditLedger(cfg).reserve(CreditLedger(cfg).available())
    page.evaluate("AI.refresh(true)")
    page.wait_for_function("AI.st && AI.st.fallback === true")
    note = page.evaluate("document.getElementById('cpAiNote').textContent")
    assert "Gemini (free-tier fallback)" in note and "standing in for Claude" in note, note
    n = len(CLAUDE["bodies"])
    ask(page, "Say something about this chart")
    assert len(CLAUDE["bodies"]) == n and len(GEMINI_CALLS) == g + 1
    assert last_ai(page)["model"].endswith("(Gemini free-tier fallback for Claude)")
    wait_quiet(page)
    ok("failures: a Claude timeout is shown once, never retried or switched; with no credit left the labelled Gemini fallback answers before any Claude request")


def check_step_limit(page):
    # a turn that keeps asking for tools stops after its steps and leaves no unanswered call behind
    CLAUDE["script"] = [{"tool": ("draw_analysis", {"layers": ["zones"]}, f"toolu_loop{i}")} for i in range(4)] + [{"text": "Fresh answer after the limit."}]
    ask(page, "Keep marking things for me")
    assert "stopped after several steps" in last_ai(page)["text"]
    convo = page.evaluate("AI.convo")
    calls = [p for c in convo for p in c["parts"] if "functionCall" in p]
    resps = [p for c in convo for p in c["parts"] if "functionResponse" in p]
    assert len(calls) == len(resps), (len(calls), len(resps))
    wait_quiet(page)
    bodies = ask(page, "And now a plain question")
    assert len(bodies) == 1 and last_ai(page)["text"] == "Fresh answer after the limit."
    wait_quiet(page)
    ok("step limit: a turn stops after its tool steps without leaving an unanswered call; the next question works")


def check_new_question_mid_tool(page):
    # a new question while a tool is still running replaces the old turn cleanly: the old turn never posts again
    page.evaluate("(() => { const d = MTF.data[S.sym]; if (d) delete d['4h']; return true; })()")   # ORACLE now waits ~3 s for the 4h
    px = page.evaluate("S.candles[S.candles.length - 2].close")
    CLAUDE["script"] = [{"tool": ("check_plan_with_oracle", {"side": "buy", "stop": round(px - 150, 2), "target": round(px + 250, 2)}, "toolu_slow")},
                        {"text": "Answer to the new question."}]
    n = len(CLAUDE["bodies"])
    page.fill("#vxInput", "Ask ORACLE about a long with a stop 150 below")
    page.press("#vxInput", "Enter")
    page.wait_for_function("AI.busy && VOICE.log.some(m => m.ai && (m.status || '').startsWith('ORACLE is validating'))", timeout=8000)
    ask(page, "Never mind, what is the structure now?")
    page.wait_for_timeout(3600)                                       # the old turn's tool finishes meanwhile
    assert len(CLAUDE["bodies"]) == n + 2, len(CLAUDE["bodies"]) - n
    convo = page.evaluate("AI.convo")
    calls = [p for c in convo for p in c["parts"] if "functionCall" in p]
    resps = [p for c in convo for p in c["parts"] if "functionResponse" in p]
    assert len(calls) == len(resps) and last_ai(page)["text"] == "Answer to the new question."
    assert page.evaluate("VOICE.log.filter(m => m.ai).slice(-2)[0].text").endswith(("…", "(interrupted)"))
    assert page.evaluate("AI.busy") is False
    wait_quiet(page)
    # the same, but the new question fails: ARIA shows why and is never left spinning
    CLAUDE["script"] = [{"tool": ("check_plan_with_oracle", {"side": "buy", "stop": round(px - 150, 2), "target": round(px + 250, 2)}, "toolu_slow2")},
                        {"timeout": True}]
    page.fill("#vxInput", "Ask ORACLE about a long with a stop 150 below")
    page.press("#vxInput", "Enter")
    page.wait_for_function("AI.busy && VOICE.log.some(m => m.ai && (m.status || '').startsWith('ORACLE is validating'))", timeout=8000)
    page.fill("#vxInput", "Never mind, what is the structure now?")
    page.press("#vxInput", "Enter")
    page.wait_for_function("!AI.busy && VOICE.state === 'idle' && document.getElementById('vxLog').textContent.includes('did not answer in time')", timeout=15000)
    page.wait_for_timeout(3600)
    assert page.evaluate("VOICE.state") == "idle"
    page.evaluate(HTF)
    ok("interrupting: a new question during a tool step ends the old turn there; it never posts again or corrupts the history; a failure never leaves ARIA spinning")


def check_secrets(page):
    html = page.content()
    store = page.evaluate("JSON.stringify(Object.assign({}, localStorage))")
    for k in (FAKE_ANTHROPIC, FAKE_ELEVEN, FAKE_GEMINI):
        assert k not in html and k not in store
    for path in ("/api/aria/ai/status", "/api/aria/voice/status"):
        for h in ({}, {"X-Sentinel-Key": OWNER}):
            t = page.evaluate(f"fetch('{path}', {{ headers: {json.dumps(h)} }}).then(r => r.text())")
            assert not any(k in t for k in (FAKE_ANTHROPIC, FAKE_ELEVEN, FAKE_GEMINI))
    ok("credentials: no key in the page, storage or any status response; keys travel only in server-side headers")


def check_phone(page, shots):
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(300)
    w = page.evaluate("document.documentElement.scrollWidth")
    assert w <= 392, w
    STUB["audio"] = LONG
    CLAUDE["script"] = [{"text": "**Observed:** on the phone, the same reply. **Interpretation:** structure first. Which level matters most to you?"}]
    ask(page, "Explain this chart to me again")
    try:
        page.wait_for_function("VOICE.state === 'speaking' && ELV.el && !ELV.el.paused", timeout=15000)
    except Exception:
        print(page.evaluate("JSON.stringify({st: VOICE.state, said: window.__said, failed: ELV.failedAt, err: ELV.lastError, tts: ELV.ttsOn(), est: ELV.st, log: VOICE.log.slice(-3).map(m => [m.who, m.text.slice(0, 60)])})"), len(STUB["tts"]))
        raise
    box = page.locator("#vxStop").bounding_box()
    assert box and box["height"] >= 32 and box["x"] >= 0 and box["x"] + box["width"] <= 390
    if shots:
        page.screenshot(path=os.path.join(shots, "aria_speaking_phone.png"))
    page.click("#vxStop")
    STUB["audio"] = SHORT
    wait_quiet(page)
    ok("phone: no sideways scroll; the Stop control is visible and tappable while ARIA speaks")


def main():
    shots = os.environ.get("SHOTS")
    srv, base = serve()
    os.environ["ARIA_ELEVEN_API_ROOT"] = base + "/stub-eleven"
    args = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"] \
        + ([f"--proxy-server={PROXY}", "--proxy-bypass-list=127.0.0.1;localhost;<local>"] if PROXY else [])
    with sync_playwright() as p:
        b = p.chromium.launch(args=args)
        ctx = b.new_context(viewport={"width": 1280, "height": 860}, permissions=["microphone"])
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(base + "/app", wait_until="domcontentloaded")
        page.wait_for_function("typeof AI !== 'undefined' && typeof ELV !== 'undefined' && typeof COPILOT !== 'undefined'")
        page.wait_for_timeout(1200)
        page.evaluate(SETUP)
        page.evaluate("CH.setData ? CH.setData(S.candles) : CH.candle.setData(S.candles.map(c => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close })))")
        page.evaluate("localStorage.removeItem('protrader.aria.chat.v1'); AI.convo = []")
        page.evaluate("VOICE.open(false)")
        page.wait_for_function("AI.st && AI.st.enabled && ELV.st", timeout=8000)
        check_guest_default(page)
        check_notice(page)
        check_account_stays_on_device(page)
        check_reasoning_and_tools(page)
        check_spoken_reply(page)
        if shots:
            page.screenshot(path=os.path.join(shots, "aria_claude_answer_desktop.png"))
        check_continuity(page)
        check_oracle(page)
        check_stop_and_barge_in(page, shots)
        check_voice_failures(page)
        check_recording(page, shots)
        page.evaluate(f"localStorage.setItem('protrader.sentinelKey', '{OWNER}'); VOICE.cfg.elevenMic = true")
        page.evaluate("ELV.refresh(true)")
        page.wait_for_function("ELV.st && ELV.st.stt === true")
        check_mic_races(page)
        page.evaluate("VOICE.cfg.elevenMic = false; localStorage.removeItem('protrader.sentinelKey'); ELV.refresh(true)")
        check_phone(page, shots)
        page.set_viewport_size({"width": 1280, "height": 860})
        check_step_limit(page)
        check_new_question_mid_tool(page)
        check_no_retry_or_switch(page)
        check_secrets(page)
        assert not errs, errs
        b.close()
    srv.should_exit = True
    print("all Claude + ElevenLabs browser checks passed")


if __name__ == "__main__":
    main()
