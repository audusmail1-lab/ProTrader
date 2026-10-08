"""
Gemini Live voice in a real browser, against a LOCAL stand-in for the Live API
(tests only). Chromium's fake microphone supplies audio. Checks the whole
lifecycle: owner-only token, setup message, 16 kHz PCM going up, transcripts,
a tool call answered through the app's allowlist, 24 kHz audio played,
interruption flushing queued audio, and a clean stop with no orphaned session.
   python3 tests/test_aria_live_browser.py
"""
import asyncio
import base64
import json
import math
import os
import socket
import struct
import sys
import tempfile
import threading
import time

import websockets

WS_PORT = (lambda s: (s.bind(("127.0.0.1", 0)), s.getsockname()[1], s.close())[1])(socket.socket())
os.environ["ACCOUNTS_DB"] = os.path.join(tempfile.mkdtemp(), "accounts.db")
os.environ["ARIA_AI_DB"] = os.path.join(tempfile.mkdtemp(), "aria.db")
os.environ["ARIA_AI_PROVIDER"] = "mock"
os.environ["ARIA_AI_ALLOW_MOCK"] = "1"
os.environ["SENTINEL_ADMIN_KEY"] = "owner-key-live-test"
os.environ["ARIA_LIVE_WS_URL"] = f"ws://127.0.0.1:{WS_PORT}/live"
sys.path.insert(0, os.path.dirname(__file__))
from test_aria_ai_browser import app, serve, PROXY, SETUP     # noqa: E402
from playwright.sync_api import sync_playwright               # noqa: E402

SEEN = {"setup": None, "audio": 0, "rates": set(), "ctx": 0, "tool": None, "end": False, "closed": False, "token": None, "phase": 0}


def pcm24(seconds, freq=440):
    n = int(24000 * seconds)
    return struct.pack("<%dh" % n, *(int(9000 * math.sin(2 * math.pi * freq * i / 24000)) for i in range(n)))


async def handler(ws):
    SEEN["token"] = ws.request.path.split("access_token=")[-1]
    SEEN["setup"] = json.loads(await ws.recv()).get("setup")
    await ws.send(json.dumps({"setupComplete": {}}))
    try:
        async for raw in ws:
            m = json.loads(raw)
            if "clientContent" in m:
                SEEN["ctx"] += 1
                SEEN["last_ctx"] = m
            ri = m.get("realtimeInput") or {}
            if ri.get("audio"):
                SEEN["audio"] += 1
                SEEN["rates"].add(ri["audio"]["mimeType"])
                SEEN["bytes"] = len(base64.b64decode(ri["audio"]["data"]))
                if SEEN["audio"] == 5 and SEEN["phase"] == 0:
                    SEEN["phase"] = 1
                    await ws.send(json.dumps({"serverContent": {"inputTranscription": {"text": "draw the zones"}}}))
                    await ws.send(json.dumps({"toolCall": {"functionCalls": [{"id": "call-1", "name": "draw_analysis", "args": {"layers": ["zones"]}}]}}))
                if SEEN["audio"] >= 25 and SEEN["phase"] == 2:
                    SEEN["phase"] = 3
                    await ws.send(json.dumps({"serverContent": {"inputTranscription": {"text": "tell me everything"}}}))
                    audio = pcm24(3.0)
                    step = len(audio) // 10
                    for i in range(10):
                        await ws.send(json.dumps({"serverContent": {"modelTurn": {"parts": [{"inlineData": {"mimeType": "audio/pcm;rate=24000", "data": base64.b64encode(audio[i * step:(i + 1) * step]).decode()}}]},
                                                                    "outputTranscription": {"text": "This is a long answer " if i == 0 else ""}}}))
                    await asyncio.sleep(0.4)
                    SEEN["phase"] = 4
                    await ws.send(json.dumps({"serverContent": {"interrupted": True}}))
            if ri.get("audioStreamEnd"):
                SEEN["end"] = True
            if "toolResponse" in m and SEEN["phase"] == 1:
                SEEN["tool"] = m["toolResponse"]
                audio = pcm24(0.5)
                for i in range(5):
                    await ws.send(json.dumps({"serverContent": {"modelTurn": {"parts": [{"inlineData": {"mimeType": "audio/pcm;rate=24000", "data": base64.b64encode(audio[i * 2400 * 2:(i + 1) * 2400 * 2]).decode()}}]}}}))
                await ws.send(json.dumps({"serverContent": {"outputTranscription": {"text": "I've marked the nearest zones."}}}))
                await ws.send(json.dumps({"serverContent": {"turnComplete": True}}))
                SEEN["phase"] = 2
    except websockets.ConnectionClosed:
        pass
    SEEN["closed"] = True


def run_ws():
    async def main():
        async with websockets.serve(handler, "127.0.0.1", WS_PORT):
            await asyncio.Future()
    asyncio.run(main())


def main():
    threading.Thread(target=run_ws, daemon=True).start()
    srv, base = serve()
    time.sleep(0.3)
    args = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"] \
        + ([f"--proxy-server={PROXY}", "--proxy-bypass-list=127.0.0.1;localhost;<local>"] if PROXY else [])
    with sync_playwright() as p:
        b = p.chromium.launch(args=args)
        ctx = b.new_context(viewport={"width": 1280, "height": 860}, permissions=["microphone"])
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(base + "/app", wait_until="domcontentloaded")
        page.wait_for_function("typeof LIVEV !== 'undefined' && typeof COPILOT !== 'undefined'")
        page.wait_for_timeout(1200)
        page.evaluate(SETUP)
        page.evaluate("CH.setData ? CH.setData(S.candles) : CH.candle.setData(S.candles.map(c => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close })))")
        # a student (no owner key) is not offered Live voice and cannot get a token
        page.evaluate("VOICE.open(false)")
        page.wait_for_function("AI.st && AI.st.enabled")
        assert page.evaluate("AI.st.live_voice") is False
        r = page.evaluate("fetch('/api/aria/ai/voice/session', { method: 'POST', headers: AI.headers() }).then(r => r.status)")
        assert r == 403
        # the owner
        page.evaluate("localStorage.setItem('protrader.sentinelKey', 'owner-key-live-test'); AI.refresh(true)")
        page.wait_for_function("AI.st && AI.st.live_voice === true")
        page.evaluate("LIVEV.setWanted(true); VOICE.cfg.talk = true")
        page.evaluate("VOICE.listen()")
        page.wait_for_function("LIVEV.state === 'listening'", timeout=10000)
        assert SEEN["token"].startswith("auth_tokens") and "owner-key" not in SEEN["token"]
        su = SEEN["setup"]
        assert su["model"] == "models/gemini-3.8-live" and su["generationConfig"]["responseModalities"] == ["AUDIO"] and "inputAudioTranscription" in su, su
        assert {t["name"] for t in su["tools"][0]["functionDeclarations"]} >= {"draw_analysis", "check_plan_with_oracle"}
        # audio goes up; the model asks for a tool; the app runs it and answers
        page.wait_for_function("LIVEV.frames >= 6", timeout=10000)
        assert SEEN["rates"] == {"audio/pcm;rate=16000"} and SEEN["bytes"] >= 3200, SEEN
        page.wait_for_function("VOICE.log.some(m => m.ai && m.text.includes(\"marked the nearest zones\"))", timeout=10000)
        tr = SEEN["tool"]["functionResponses"][0]
        assert tr["id"] == "call-1" and tr["response"]["ok"] and tr["response"]["verifiedOnChart"] >= 1, tr
        assert page.evaluate("COPILOT.ours().filter(d => d.aria.rule === 'zones').length") >= 1
        assert page.evaluate("VOICE.log.some(m => m.who === 'you' && m.text === 'draw the zones')")
        assert SEEN["ctx"] >= 2, "a fresh chart snapshot goes up at the start and after each turn"
        sent = json.loads(SEEN["last_ctx"]["clientContent"]["turns"][0]["parts"][0]["text"].split("\n", 1)[1])
        assert sent["chart"]["symbol"] == "R_75" and "balance" not in json.dumps(sent)
        page.wait_for_function("AI.convo.length >= 2")
        # interruption: queued speech is dropped at once
        page.wait_for_function("VOICE.log.some(m => m.ai && m.text.startsWith('This is a long answer')) && LIVEV.sources.length >= 3", timeout=20000)
        page.wait_for_function("VOICE.log.some(m => m.ai && m.text.startsWith('This is a long answer') && m.text.endsWith('…'))", timeout=10000)
        assert page.evaluate("LIVEV.sources.length") == 0
        assert page.evaluate("VOICE.log.filter(m => m.ai && m.text.startsWith('This is a long answer')).length") == 1, page.evaluate("VOICE.log.slice(-4).map(m => [m.who, m.text])")
        assert page.evaluate("VOICE.log.find(m => m.ai && m.text.startsWith('This is a long answer')).text.endsWith('…')")
        # ending the session leaves nothing running
        page.evaluate("VOICE.close()")
        page.wait_for_timeout(500)
        st = page.evaluate("({ ws: !!LIVEV.ws, mic: !!LIVEV.mic, ctx: !!LIVEV.inCtx, state: LIVEV.state })")
        assert st == {"ws": False, "mic": False, "ctx": False, "state": "idle"}, st
        for _ in range(20):
            if SEEN["closed"]:
                break
            time.sleep(0.1)
        assert SEEN["end"] and SEEN["closed"]
        assert not errs, errs
        b.close()
    srv.should_exit = True
    print("ok  live voice: owner-only token, setup, 16 kHz audio up, tool through the allowlist, 24 kHz audio down, interruption, clean stop")


if __name__ == "__main__":
    main()
