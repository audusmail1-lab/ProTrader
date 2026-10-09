"""ARIA voice through ElevenLabs: zero-extra-spend gates, the reserve kept for the
Academy's other agents, privacy and the wire format. Every ElevenLabs call is mocked.
   python3 -m pytest -q tests/test_aria_voice.py
"""
import json
import os
import sqlite3
import sys
import threading
import time

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import aria_ai      # noqa: E402
import aria_voice   # noqa: E402

FAKE_KEY = "sk_eleven_FAKE_only_testing_000000000000000000"
VOICE_ID = "VoiceFake0123456789ab"
OWNER = "owner-key-voice-tests"
RESET = int(time.time()) + 20 * 86400
ALLOWED = ("GET /v1/user/subscription", "POST /v1/text-to-speech/", "POST /v1/speech-to-text", "DELETE /v1/history/",
           "DELETE /v1/speech-to-text/transcripts/")


def sub(**kw):
    base = {"tier": "creator", "character_count": 10_000, "character_limit": 121_000, "max_credit_limit_extension": 0,
            "can_extend_character_limit": True, "has_open_invoices": False, "current_overage": {"amount": 0, "currency": "usd"},
            "status": "active", "next_character_count_reset_unix": RESET}
    base.update(kw)
    return base


class Resp:
    def __init__(self, status=200, body=None, chunks=(b"ID3fake-mp3-",), headers=None):
        self.status_code, self._body, self._chunks, self.headers, self.closed = status, body, chunks, headers or {}, False
    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body
    def iter_content(self, chunk_size=8192):
        yield from self._chunks
    def close(self):
        self.closed = True


class Upstream:
    """Stands in for api.elevenlabs.io and records every call."""
    def __init__(self):
        self.calls, self.subscription, self.tts, self.stt = [], sub(), Resp(headers={"history-item-id": "hist_abc123"}), \
            Resp(body={"text": "draw the zones", "language_code": "en", "transcription_id": "tr_abc123"})
        self.deleted = threading.Event()
    def get(self, url, **kw):
        self.calls.append(("GET", url, kw)); return Resp(body=self.subscription)
    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        if isinstance(self.tts, Exception) and "/text-to-speech/" in url:
            raise self.tts
        return self.tts if "/text-to-speech/" in url else self.stt
    def delete(self, url, **kw):
        self.calls.append(("DELETE", url, kw)); self.deleted.set(); return Resp(body={"status": "ok"})
    def paths(self, method=None):
        return [(m, u.replace(aria_voice.API_ROOT, "")) for m, u, _ in self.calls if not method or m == method]


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    for key in list(os.environ):
        if key.startswith(("ARIA_", "ELEVEN", "SENTINEL_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ARIA_AI_DB", str(tmp_path / "usage.db"))
    monkeypatch.setenv("SENTINEL_ADMIN_KEY", OWNER)
    aria_ai._minute.clear()
    aria_voice._sub.update(at=0.0, data=None, spent=0)
    aria_voice._recent.clear()
    orig = aria_ai.identity
    def identity(request):                       # a signed-in student, without the accounts database
        i = orig(request)
        u = request.headers.get("x-test-user")
        return dict(i, key="u:" + u, guest=False) if u else i
    monkeypatch.setattr(aria_ai, "identity", identity)
    up = Upstream()
    monkeypatch.setattr(aria_voice.requests, "get", up.get)
    monkeypatch.setattr(aria_voice.requests, "post", up.post)
    monkeypatch.setattr(aria_voice.requests, "delete", up.delete)
    def forbid(*a, **k):
        raise AssertionError("no other network call is allowed")
    monkeypatch.setattr(requests.Session, "post", forbid)
    monkeypatch.setattr(requests.Session, "get", forbid)
    return up


@pytest.fixture
def up(isolated):
    return isolated


def enable(monkeypatch, tmp_path, provision=True, **extra):
    env = {"ARIA_ELEVEN_ENABLED": "1", "ELEVEN_USAGE_BILLING_OFF_CONFIRMED": "1", "ELEVEN_PRICING_CONFIRMED": "1",
           "ELEVEN_PERSISTENT_LEDGER_CONFIRMED": "1", "ELEVENLABS_API_KEY": FAKE_KEY, "ARIA_ELEVEN_VOICE_ID": VOICE_ID,
           "ARIA_ELEVEN_ALLOWANCE_CREDITS": "5000", "ARIA_ELEVEN_RESERVE_CREDITS": "20000",
           "ARIA_ELEVEN_LEDGER_DB": str(tmp_path / "voice-ledger.db"), "ARIA_ELEVEN_STT_CREDITS_PER_MINUTE": "100"}
    env.update(extra)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    if provision:
        aria_voice.VoiceLedger(aria_voice.VoiceConfig()).provision()


def client():
    app = FastAPI()
    app.include_router(aria_voice.router)
    return TestClient(app)


def speak(c, text="Price broke structure at 44,593.2.", owner=False, user="student-1", device=None):
    h = {"x-sentinel-key": OWNER} if owner else ({"x-test-user": user} if user else {})
    if device:
        h["x-aria-device"] = device
    return c.post("/api/aria/voice/speak", json={"text": text}, headers=h)


T100 = ("abcd " * 20).strip() + "z"      # exactly 100 characters that the privacy scrubber leaves alone


def pcm(seconds):
    return b"\x01\x00" * int(16000 * seconds)


def transcribe(c, audio, owner=True, fmt="pcm_s16le_16"):
    h = {"x-audio-format": fmt, "content-type": "application/octet-stream"}
    if owner:
        h["x-sentinel-key"] = OWNER
    return c.post("/api/aria/voice/transcribe", content=audio, headers=h)


def used(tmp_path):
    with sqlite3.connect(tmp_path / "voice-ledger.db") as db:
        return dict(db.execute("SELECT period, used FROM voice_allowance").fetchall())


# ── off by default; every check must pass ─────────────────────────────────────

def test_key_alone_never_enables_voice(monkeypatch, tmp_path, up):
    monkeypatch.setenv("ELEVENLABS_API_KEY", FAKE_KEY)
    c = client()
    st = c.get("/api/aria/voice/status").json()
    assert st["tts"] is False and st["stt"] is False and "reason" not in st
    assert speak(c).status_code == 503 and up.calls == []


@pytest.mark.parametrize("missing", ["ARIA_ELEVEN_ENABLED", "ELEVEN_USAGE_BILLING_OFF_CONFIRMED", "ELEVEN_PRICING_CONFIRMED",
                                     "ELEVEN_PERSISTENT_LEDGER_CONFIRMED", "ELEVENLABS_API_KEY", "ARIA_ELEVEN_VOICE_ID",
                                     "ARIA_ELEVEN_ALLOWANCE_CREDITS", "ARIA_ELEVEN_RESERVE_CREDITS", "ARIA_ELEVEN_LEDGER_DB"])
def test_each_missing_check_keeps_voice_off(monkeypatch, tmp_path, up, missing):
    enable(monkeypatch, tmp_path)
    monkeypatch.delenv(missing)
    c = client()
    assert c.get("/api/aria/voice/status").json()["tts"] is False
    assert speak(c).status_code == 503 and up.calls == []


@pytest.mark.parametrize("key,value", [("ARIA_ELEVEN_TTS_MODEL", "eleven_agents_v9"), ("ARIA_ELEVEN_VOICE_ID", "../voices/x"),
                                       ("ARIA_ELEVEN_ALLOWANCE_CREDITS", "0"), ("ARIA_ELEVEN_ALLOWANCE_CREDITS", "nan"),
                                       ("ARIA_ELEVEN_ALLOWANCE_CREDITS", "99999999"), ("ARIA_ELEVEN_LEDGER_DB", "relative.db"),
                                       ("ARIA_ELEVEN_TTS_CREDITS_PER_CHAR", "0")])
def test_bad_configuration_fails_closed(monkeypatch, tmp_path, up, key, value):
    enable(monkeypatch, tmp_path)
    monkeypatch.setenv(key, value)
    assert speak(client()).status_code == 503 and up.calls == []


def test_missing_ledger_is_never_recreated_by_a_request(monkeypatch, tmp_path, up):
    enable(monkeypatch, tmp_path, provision=False)
    c = client()
    st = c.get("/api/aria/voice/status", headers={"x-sentinel-key": OWNER}).json()
    assert st["tts"] is False and "ledger" in st["reason"]
    assert speak(c).status_code == 503
    assert not (tmp_path / "voice-ledger.db").exists() and up.calls == []


# ── the live account check: no overage, active, reserve kept for Alex and support ──

@pytest.mark.parametrize("bad", [{"max_credit_limit_extension": "unlimited"}, {"max_credit_limit_extension": 5000},
                                 {"max_credit_limit_extension": None}, {"has_open_invoices": True}, {"has_open_invoices": None},
                                 {"current_overage": {"amount": 3, "currency": "usd"}}, {"status": "past_due"},
                                 {"character_count": None}, {"next_character_count_reset_unix": None},
                                 {"current_overage": None}, {"current_overage": "0"}, {"allowed_to_extend_character_limit": True},
                                 {"open_invoices": [{"amount_due_cents": 500}]}])
def test_any_chance_of_extra_billing_refuses_before_speaking(monkeypatch, tmp_path, up, bad):
    enable(monkeypatch, tmp_path)
    up.subscription = sub(**bad)
    r = speak(client(), owner=True)
    assert r.status_code == 429 and r.json()["reason"]
    assert up.paths() == [("GET", "/v1/user/subscription")]     # checked, never spoken
    assert used(tmp_path) == {}


def test_reserve_for_the_other_agents_is_never_spent(monkeypatch, tmp_path, up):
    enable(monkeypatch, tmp_path, ARIA_ELEVEN_RESERVE_CREDITS="1000")
    text = T100                                                # 100 credits at 1 per character
    up.subscription = sub(character_count=121_000 - 1099)     # 1,099 left: 100 would leave 999 < 1,000
    r = speak(client(), text, owner=True)
    assert r.status_code == 429 and "reserve" in r.json()["reason"]
    aria_voice._sub.update(at=0.0, data=None, spent=0)
    up.subscription = sub(character_count=121_000 - 1100)     # exactly enough: leaves the reserve intact
    assert speak(client(), text).status_code == 200
    # spend since the last reading counts too, so a burst cannot dip into the reserve
    assert speak(client(), text, owner=True).status_code == 429
    # ...even right after a fresh reading that may not include it yet
    aria_voice._sub.update(at=0.0, data=None, spent=0)
    assert speak(client(), text, owner=True).status_code == 429
    aria_voice._recent.clear()
    up.subscription = sub(character_count=121_000 - 1200)
    aria_voice._sub.update(at=0.0, data=None, spent=0)
    assert speak(client(), text).status_code == 200


def test_aria_allowance_is_capped_per_billing_period_and_cannot_grow(monkeypatch, tmp_path, up):
    enable(monkeypatch, tmp_path, ARIA_ELEVEN_ALLOWANCE_CREDITS="150")
    c = client()
    assert speak(c, T100).status_code == 200
    r = speak(c, T100, owner=True)
    assert r.status_code == 429 and "allowance" in r.json()["reason"]
    monkeypatch.setenv("ARIA_ELEVEN_ALLOWANCE_CREDITS", "100000")      # raising the setting mid-period changes nothing
    assert speak(c, T100).status_code == 429
    assert used(tmp_path) == {f"eleven-{RESET}": 100}
    # the reset time changes mid-cycle (a plan change, say): it counts as the same period, no fresh allowance
    aria_voice._sub.update(at=0.0, data=None, spent=0)
    up.subscription = sub(next_character_count_reset_unix=RESET + 3 * 86400)
    assert speak(c, T100, owner=True).status_code == 429
    # a period may never go back to an earlier reset time
    aria_voice._sub.update(at=0.0, data=None, spent=0)
    up.subscription = sub(next_character_count_reset_unix=RESET - 86400)
    r = speak(c, T100, owner=True)
    assert r.status_code == 429 and "backwards" in r.json()["reason"]
    # a real monthly rollover starts a new allowance at once, however late in the last period ARIA spent it
    aria_voice._sub.update(at=0.0, data=None, spent=0)
    up.subscription = sub(next_character_count_reset_unix=RESET + 30 * 86400)
    assert speak(c, T100).status_code == 200
    assert used(tmp_path) == {f"eleven-{RESET}": 100, f"eleven-{RESET + 30 * 86400}": 100}


def test_concurrent_reservations_never_exceed_the_allowance(monkeypatch, tmp_path, up):
    enable(monkeypatch, tmp_path, ARIA_ELEVEN_ALLOWANCE_CREDITS="1000")
    cfg = aria_voice.VoiceConfig()
    ok = []
    def one():
        try:
            aria_voice.VoiceLedger(cfg).reserve(f"eleven-{RESET}", 300); ok.append(1)
        except aria_voice.VoiceBlocked:
            pass
    threads = [threading.Thread(target=one) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert len(ok) == 3


# ── speaking ──────────────────────────────────────────────────────────────────

def test_speak_wire_format_privacy_and_cleanup(monkeypatch, tmp_path, up):
    enable(monkeypatch, tmp_path)
    r = speak(client(), "Observed: a BOS at 44593.2. Email me at joel@example.com " + "zz " * 700)
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and r.content == b"ID3fake-mp3-"
    assert r.headers["cache-control"] == "no-store"
    method, url, kw = [c for c in up.calls if c[0] == "POST"][0]
    assert url == f"{aria_voice.API_ROOT}/v1/text-to-speech/{VOICE_ID}/stream" and FAKE_KEY not in url
    assert kw["headers"]["xi-api-key"] == FAKE_KEY and kw["allow_redirects"] is False
    assert kw["params"] == {"output_format": "mp3_44100_64"}
    assert kw["json"]["model_id"] == "eleven_flash_v2_5" and set(kw["json"]) == {"text", "model_id"}   # no voice settings sent: the voice is never changed
    sent = kw["json"]["text"]
    assert "joel@example.com" not in sent and len(sent) == 900
    assert up.deleted.wait(2) and ("DELETE", "/v1/history/hist_abc123") in up.paths()
    assert used(tmp_path) == {f"eleven-{RESET}": 900}
    assert FAKE_KEY not in r.text


def test_only_reviewed_endpoints_are_ever_called(monkeypatch, tmp_path, up):
    enable(monkeypatch, tmp_path)
    c = client()
    speak(c); transcribe(c, pcm(2)); up.deleted.wait(2); time.sleep(0.2)
    for method, path in up.paths():
        assert any(f"{method} {path}".startswith(a) for a in ALLOWED), (method, path)
    assert not any("convai" in p or "/voices" in p or "agents" in p or "workspace" in p for _, p in up.paths())


def test_upstream_refusal_pauses_voice_and_is_never_retried(monkeypatch, tmp_path, up):
    enable(monkeypatch, tmp_path)
    up.tts = Resp(status=401)
    c = client()
    assert speak(c).status_code == 429
    assert len(up.paths("POST")) == 1
    assert speak(c).status_code == 429 and len(up.paths("POST")) == 1        # paused: no second knock
    assert aria_ai.cooldown("eleven") > 500


def test_a_dropped_connection_keeps_its_reservation_and_is_not_retried(monkeypatch, tmp_path, up):
    enable(monkeypatch, tmp_path)
    up.tts = requests.ConnectionError("reset " + FAKE_KEY)
    r = speak(client(), "abc")
    assert r.status_code == 502 and FAKE_KEY not in r.text
    assert len(up.paths("POST")) == 1 and used(tmp_path) == {f"eleven-{RESET}": 3}


def test_daily_and_per_minute_caps(monkeypatch, tmp_path, up):
    enable(monkeypatch, tmp_path, ARIA_ELEVEN_TTS_PER_DAY="2")
    c = client()
    assert [speak(c, "a").status_code for _ in range(3)] == [200, 200, 429]
    aria_ai._minute.clear()
    monkeypatch.setenv("ARIA_ELEVEN_TTS_PER_DAY", "50")
    monkeypatch.setenv("ARIA_ELEVEN_TTS_PER_MIN", "2")
    r = [speak(c, "b", user="student-2") for _ in range(3)]
    assert [x.status_code for x in r] == [200, 200, 429] and r[2].json()["error"] == "busy"


def test_characters_per_day_cap(monkeypatch, tmp_path, up):
    enable(monkeypatch, tmp_path, ARIA_ELEVEN_USER_CHARS_PER_DAY="150")
    c = client()
    assert [speak(c, T100).status_code for _ in range(2)] == [200, 429]
    assert speak(c, T100, user="student-9").status_code == 200        # another person's day is separate


def test_guests_get_no_natural_voice_by_default_and_rotating_devices_hits_the_ip_cap(monkeypatch, tmp_path, up):
    enable(monkeypatch, tmp_path)
    c = client()
    assert c.get("/api/aria/voice/status").json()["tts"] is False
    assert speak(c, user=None).status_code == 503 and up.calls == []
    assert speak(c, owner=True).status_code == 200                       # the owner key works without signing in
    monkeypatch.setenv("ARIA_ELEVEN_GUESTS", "1")
    monkeypatch.setenv("ARIA_ELEVEN_IP_PER_DAY", "3")
    codes = [speak(c, "hi", user=None, device=f"device-{i:02d}-rotated-id").status_code for i in range(5)]
    assert codes == [200, 200, 429, 429, 429]                              # the owner's call above already used one of the IP's three


def test_oversized_bodies_are_refused_before_reading_them_all(monkeypatch, tmp_path, up):
    enable(monkeypatch, tmp_path)
    c = client()
    def chunks():
        for _ in range(30):
            yield b"x" * 1000
    assert c.post("/api/aria/voice/speak", content=chunks(), headers={"x-test-user": "s"}).status_code == 413
    big = (b"\x00\x00" * 16000 * 40)
    assert transcribe(c, big).status_code == 413
    assert up.paths("POST") == []


def test_requests_must_come_from_the_app(monkeypatch, tmp_path, up):
    enable(monkeypatch, tmp_path)
    r = client().post("/api/aria/voice/speak", json={"text": "hi"}, headers={"origin": "https://evil.example", "host": "testserver"})
    assert r.status_code == 403 and up.calls == []


# ── transcription: deliberate, owner-only by default, nothing kept ───────────

def test_transcription_is_owner_only_and_needs_a_reviewed_rate(monkeypatch, tmp_path, up):
    enable(monkeypatch, tmp_path)
    c = client()
    st = c.get("/api/aria/voice/status", headers={"x-test-user": "student-1"}).json()
    assert st["tts"] is True and st["stt"] is False                  # a student: spoken replies yes, their voice no
    assert transcribe(c, pcm(2), owner=False).status_code == 403
    assert c.get("/api/aria/voice/status", headers={"x-sentinel-key": OWNER}).json()["stt"] is True
    monkeypatch.delenv("ARIA_ELEVEN_STT_CREDITS_PER_MINUTE")
    st = c.get("/api/aria/voice/status", headers={"x-sentinel-key": OWNER}).json()
    assert st["stt"] is False and "ARIA_ELEVEN_STT_CREDITS_PER_MINUTE" in st["stt_reason"]
    assert transcribe(c, pcm(2)).status_code == 403
    assert up.calls == []


def test_transcription_wire_format_and_transcript_deletion(monkeypatch, tmp_path, up):
    enable(monkeypatch, tmp_path)
    audio = pcm(3)
    r = transcribe(client(), audio)
    assert r.status_code == 200 and r.json() == {"text": "draw the zones", "language": "en", "seconds": 3.0}
    method, url, kw = [c for c in up.calls if c[0] == "POST"][0]
    assert url == f"{aria_voice.API_ROOT}/v1/speech-to-text" and kw["headers"] == {"xi-api-key": FAKE_KEY}
    assert kw["data"]["model_id"] == "scribe_v2" and kw["data"]["file_format"] == "pcm_s16le_16" and kw["data"]["language_code"] == "en"
    assert kw["files"]["file"][1] == audio and kw["allow_redirects"] is False
    assert up.deleted.wait(2) and ("DELETE", "/v1/speech-to-text/transcripts/tr_abc123") in up.paths()
    assert used(tmp_path) == {f"eleven-{RESET}": 5}              # 3 s at 100 credits a minute, rounded up
    # nothing of the recording was written to disk
    for root, _, files in os.walk(tmp_path):
        for f in files:
            assert audio[:64] * 4 not in open(os.path.join(root, f), "rb").read()


@pytest.mark.parametrize("audio,fmt,code", [(pcm(0.1), "pcm_s16le_16", 413), (pcm(31), "pcm_s16le_16", 413),
                                            (pcm(2) + b"\x00", "pcm_s16le_16", 413), (pcm(2), "webm", 400)])
def test_recording_bounds(monkeypatch, tmp_path, up, audio, fmt, code):
    enable(monkeypatch, tmp_path)
    assert transcribe(client(), audio, fmt=fmt).status_code == code
    assert up.paths("POST") == []


def test_status_never_exposes_the_key_and_reasons_are_owner_only(monkeypatch, tmp_path, up):
    enable(monkeypatch, tmp_path)
    c = client()
    for h in ({}, {"x-test-user": "s"}, {"x-sentinel-key": OWNER}):
        st = c.get("/api/aria/voice/status", headers=h).json()
        assert FAKE_KEY not in json.dumps(st) and VOICE_ID not in json.dumps(st)
    assert "reason" not in c.get("/api/aria/voice/status").json()
    assert "ElevenLabs" in c.get("/api/aria/voice/status").json()["privacy_stt"]


def test_test_stand_in_is_ignored_outside_the_test_configuration(monkeypatch, tmp_path, up):
    monkeypatch.setenv("ARIA_ELEVEN_API_ROOT", "http://127.0.0.1:9/stub")
    assert aria_voice.api_root() == aria_voice.API_ROOT
    monkeypatch.setenv("ARIA_AI_ALLOW_MOCK", "1")
    assert aria_voice.api_root() == "http://127.0.0.1:9/stub"


def test_an_older_ledger_is_migrated_by_provisioning(monkeypatch, tmp_path, up):
    enable(monkeypatch, tmp_path, provision=False)
    with sqlite3.connect(tmp_path / "voice-ledger.db") as db:
        db.execute("CREATE TABLE voice_allowance (period TEXT PRIMARY KEY, cap INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0)")
    aria_voice.VoiceLedger(aria_voice.VoiceConfig()).provision()
    assert speak(client()).status_code == 200


def test_check_command_reads_the_account_and_spends_nothing(monkeypatch, tmp_path, up, capsys):
    assert aria_voice.main(["x", "check"]) == 1 and "off" in capsys.readouterr().out
    enable(monkeypatch, tmp_path)
    assert aria_voice.main(["x", "check"]) == 0
    out = capsys.readouterr().out
    assert "110,000" not in out and "111,000 kept" not in out
    assert "Left in the shared pool: 111,000" in out and "ARIA may use up to 91,000" in out and "5,000 of 5,000" in out
    assert up.paths() == [("GET", "/v1/user/subscription")] and FAKE_KEY not in out
    up.subscription = sub(max_credit_limit_extension="unlimited")
    assert aria_voice.main(["x", "check"]) == 1 and "Usage-based billing" in capsys.readouterr().out


def test_status_says_whether_voice_is_set_up_without_saying_why(monkeypatch, tmp_path, up):
    c = client()
    assert c.get("/api/aria/voice/status").json()["configured"] is False
    enable(monkeypatch, tmp_path)
    st = c.get("/api/aria/voice/status").json()                       # a guest: set up, but not for them
    assert st["configured"] is True and st["tts"] is False and "reason" not in st
    assert up.calls == []
