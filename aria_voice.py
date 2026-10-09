"""
ARIA voice through ElevenLabs: ARIA's spoken replies (text to speech) and, for
the owner by default, transcription of a recording the student deliberately
starts and stops (speech to text). The browser's own speech stays the fallback.

  GET  /api/aria/voice/status       which voice features are on for this person
  POST /api/aria/voice/speak        ARIA's reply text -> MP3, streamed
  POST /api/aria/voice/transcribe   a short 16 kHz 16-bit mono PCM recording -> text

Zero extra spend (OFF until ARIA_ELEVEN_ENABLED=1 and the checks below pass)
  Before every billable request this module
   1. reads the account's live subscription (GET /v1/user/subscription, kept for
      at most SUB_TTL seconds) and refuses when usage-based billing could apply
      (max_credit_limit_extension != 0), when there is any overage or open
      invoice, or when the subscription is not active;
   2. keeps a RESERVE of credits in the shared pool for the account's other uses
      (the Academy's Alex and website-support agents): it refuses when
      remaining - cost < ARIA_ELEVEN_RESERVE_CREDITS;
   3. reserves the cost in ARIA's own capped allowance for the billing period, in
      a persistent SQLite ledger that the owner creates once, offline
      (python3 aria_voice.py provision). Reservations are never refunded.
  Only the TTS stream, speech-to-text convert and the two delete endpoints are
  called. No agent, voice, phone number, plan, payment or workspace setting is
  read for writing, created or changed. Agents, their LLM and telephony charges
  are separate ElevenLabs products and are neither covered nor touched here.

Privacy
  Speak sends ARIA's reply text only. Transcribe sends the speaker's voice; it is
  owner-only by default (ARIA_ELEVEN_STT=owner) because ElevenLabs' zero-retention
  mode is enterprise-only. Audio passes through this server's memory and is never
  written anywhere; transcripts are not logged. After each request ARIA asks
  ElevenLabs to delete the history item / transcript when the API returns its id.
  The key is sent only in the xi-api-key header and never reaches the browser.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

import aria_ai

log = logging.getLogger("aria_voice")
router = APIRouter()
API_ROOT = "https://api.elevenlabs.io"
SUB_TTL = 15                      # seconds a subscription reading may be reused
MAX_SECONDS_HARD = 60             # one recording, whatever the configuration says
PCM_RATE = 16000                  # 16 kHz, 16-bit, mono: 32 000 bytes per second
# Reviewed text-to-speech models (all on the low-latency or general path; none of
# them is an agent product). Credits per character come from the configuration.
TTS_MODELS = ("eleven_flash_v2_5", "eleven_turbo_v2_5", "eleven_multilingual_v2", "eleven_v3", "eleven_v4", "eleven_v4_turbo")
STT_MODELS = ("scribe_v2",)
_VOICE_ID = re.compile(r"^[A-Za-z0-9]{10,40}$")
_ITEM_ID = re.compile(r"^[A-Za-z0-9_-]{6,80}$")
ALLOWANCE_MAX = 2_000_000
NEW_PERIOD_DAYS = 25              # a monthly credit reset is further from the last one than this


class VoiceBlocked(Exception):
    """A safe reason suitable for the owner's status line."""


def _num(name: str, default: Optional[float] = None, lo: float = 0.0, hi: float = 1e12) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        if default is None:
            raise VoiceBlocked(f"Set {name}.")
        return default
    try:
        v = float(raw)
    except ValueError:
        raise VoiceBlocked(f"{name} must be a number.") from None
    if not (math.isfinite(v) and lo <= v <= hi):
        raise VoiceBlocked(f"{name} is outside its reviewed range.")
    return v


class VoiceConfig:
    """Everything is read from the environment on every call; nothing secret in source."""

    def __init__(self) -> None:
        if os.getenv("ARIA_ELEVEN_ENABLED", "").strip() != "1":
            raise VoiceBlocked("ElevenLabs voice is off until ARIA_ELEVEN_ENABLED=1 is approved.")
        checks = ("ELEVEN_USAGE_BILLING_OFF_CONFIRMED", "ELEVEN_PRICING_CONFIRMED", "ELEVEN_PERSISTENT_LEDGER_CONFIRMED")
        if any(os.getenv(k, "").strip() != "1" for k in checks):
            raise VoiceBlocked("ElevenLabs billing, pricing and ledger checks are not confirmed.")
        self.key = os.getenv("ELEVENLABS_API_KEY", "").strip()
        if not self.key:
            raise VoiceBlocked("No ElevenLabs key is configured in the server environment.")
        self.voice = os.getenv("ARIA_ELEVEN_VOICE_ID", "").strip()
        if not _VOICE_ID.fullmatch(self.voice):
            raise VoiceBlocked("Set ARIA_ELEVEN_VOICE_ID to an existing voice from the account (it is never changed).")
        self.model = os.getenv("ARIA_ELEVEN_TTS_MODEL", "eleven_flash_v2_5").strip()
        if self.model not in TTS_MODELS:
            raise VoiceBlocked("The ElevenLabs speech model has no reviewed credit rate.")
        self.tts_rate = _num("ARIA_ELEVEN_TTS_CREDITS_PER_CHAR", 1.0, 0.1, 10)
        self.allowance = int(_num("ARIA_ELEVEN_ALLOWANCE_CREDITS", None, 1, ALLOWANCE_MAX))
        self.reserve = int(_num("ARIA_ELEVEN_RESERVE_CREDITS", None, 1, 1e9))
        self.max_chars = int(_num("ARIA_ELEVEN_MAX_CHARS", 900, 50, 2500))
        self.path = os.getenv("ARIA_ELEVEN_LEDGER_DB", "").strip()
        if not self.path or not os.path.isabs(self.path) or not os.path.isdir(os.path.dirname(self.path)):
            raise VoiceBlocked("Set ARIA_ELEVEN_LEDGER_DB on verified persistent private storage.")
        self.stt_mode = os.getenv("ARIA_ELEVEN_STT", "owner").strip().lower()
        if self.stt_mode not in ("off", "owner", "all"):
            self.stt_mode = "owner"
        self.stt_model = os.getenv("ARIA_ELEVEN_STT_MODEL", "scribe_v2").strip()
        raw_rate = os.getenv("ARIA_ELEVEN_STT_CREDITS_PER_MINUTE", "").strip()
        self.stt_rate = _num("ARIA_ELEVEN_STT_CREDITS_PER_MINUTE", None, 1, 1e6) if raw_rate else None
        self.max_seconds = int(_num("ARIA_ELEVEN_STT_MAX_SECONDS", 30, 2, MAX_SECONDS_HARD))
        self.tts_user_day = int(_num("ARIA_ELEVEN_TTS_PER_DAY", 40, 0, 1000))
        self.tts_guest_day = int(_num("ARIA_ELEVEN_TTS_GUEST_PER_DAY", 10, 0, 1000))
        self.tts_all_day = int(_num("ARIA_ELEVEN_TTS_ALL_PER_DAY", 400, 0, 100000))
        self.stt_day = int(_num("ARIA_ELEVEN_STT_PER_DAY", 60, 0, 1000))
        self.tts_per_min = int(_num("ARIA_ELEVEN_TTS_PER_MIN", 8, 1, 120))
        # Spoken replies for people who are not signed in are off by default: a guest
        # identity is cheap to rotate, so only signed-in accounts and the owner draw on it.
        self.guests = os.getenv("ARIA_ELEVEN_GUESTS", "0").strip() == "1"
        self.user_chars_day = int(_num("ARIA_ELEVEN_USER_CHARS_PER_DAY", 8000, 0, 1e6))
        self.ip_per_day = int(_num("ARIA_ELEVEN_IP_PER_DAY", 80, 0, 100000))
        self.delete_after = os.getenv("ARIA_ELEVEN_DELETE_AFTER_USE", "1").strip() != "0"

    def stt_blocked(self) -> Optional[str]:
        if self.stt_mode == "off":
            return "ElevenLabs transcription is off (ARIA_ELEVEN_STT=off)."
        if self.stt_model not in STT_MODELS:
            return "The ElevenLabs transcription model has no reviewed credit rate."
        if self.stt_rate is None:
            return "Set ARIA_ELEVEN_STT_CREDITS_PER_MINUTE from the plan's reviewed rate to enable transcription."
        return None

    def tts_cost(self, text: str) -> int:
        return max(1, math.ceil(len(text) * self.tts_rate))

    def stt_cost(self, seconds: float) -> int:
        return max(1, math.ceil(seconds / 60.0 * (self.stt_rate or 0)))


def api_root() -> str:
    # A local stand-in is honoured only in the test configuration.
    if aria_ai.CFG.allow_mock and os.getenv("ARIA_ELEVEN_API_ROOT"):
        return os.getenv("ARIA_ELEVEN_API_ROOT", "").rstrip("/")
    return API_ROOT


# ── the subscription: overage off, active, and enough left over for everyone else ──

_sub_lock = threading.Lock()
_sub: dict = {"at": 0.0, "data": None, "spent": 0}
_recent: list = []                 # (time, credits) ARIA spent lately; the account's count may lag
RECENT_S = 90


def _fetch_subscription(cfg: VoiceConfig) -> dict:
    try:
        r = requests.get(api_root() + "/v1/user/subscription", headers={"xi-api-key": cfg.key}, timeout=10, allow_redirects=False)
    except requests.RequestException:
        raise VoiceBlocked("The ElevenLabs account could not be checked.") from None
    if r.status_code != 200:
        raise VoiceBlocked(f"The ElevenLabs account check failed ({r.status_code}).")
    try:
        data = r.json()
    except ValueError:
        raise VoiceBlocked("The ElevenLabs account check returned no data.") from None
    if not isinstance(data, dict):
        raise VoiceBlocked("The ElevenLabs account check returned no data.")
    return data


def check_subscription(data: dict) -> tuple[int, str]:
    """(credits remaining this period, period key) or VoiceBlocked. Fails closed on anything unexpected."""
    # max_credit_limit_extension: 0 means usage-based billing is disabled ("unlimited" or >0 means it could bill)
    ext = data.get("max_credit_limit_extension")
    if ext != 0 or type(ext) is not int:
        raise VoiceBlocked("Usage-based billing could apply on the ElevenLabs account (max_credit_limit_extension is not 0).")
    if data.get("allowed_to_extend_character_limit") is True:          # the deprecated flag, checked as well
        raise VoiceBlocked("Usage-based billing is allowed on the ElevenLabs account.")
    if data.get("has_open_invoices") is not False or data.get("open_invoices"):
        raise VoiceBlocked("The ElevenLabs account has open invoices or does not report them.")
    over = data.get("current_overage")
    if not isinstance(over, dict):
        raise VoiceBlocked("The ElevenLabs overage could not be read.")
    try:
        amount = float(over.get("amount", 0) or 0)
    except (TypeError, ValueError):
        raise VoiceBlocked("The ElevenLabs overage could not be read.") from None
    if amount != 0:
        raise VoiceBlocked("The ElevenLabs account shows an overage.")
    if data.get("status") not in ("active", "free", "trialing"):
        raise VoiceBlocked("The ElevenLabs subscription is not active.")
    used, limit, reset = data.get("character_count"), data.get("character_limit"), data.get("next_character_count_reset_unix")
    if type(used) is not int or type(limit) is not int or type(reset) is not int or limit <= 0 or reset < time.time() - 86400:
        raise VoiceBlocked("The ElevenLabs credit balance or billing period could not be read.")
    return limit - used, f"eleven-{reset}"


def account(cfg: VoiceConfig, cost: int) -> str:
    """Refuse unless the shared pool keeps its reserve after this request; returns the period key."""
    with _sub_lock:
        now = time.time()
        if not _sub["data"] or now - _sub["at"] > SUB_TTL:
            _sub.update(data=None, at=0.0)
            _sub.update(data=_fetch_subscription(cfg), at=now)
        remaining, period = check_subscription(_sub["data"])
        # ARIA's own recent spend is subtracted again even after a fresh reading: the account's
        # count can lag a request that is still streaming. Double counting only errs on the safe side.
        _recent[:] = [(t, c) for t, c in _recent if now - t < RECENT_S]
        if remaining - sum(c for _, c in _recent) - cost < cfg.reserve:
            raise VoiceBlocked("ElevenLabs credits are at the reserve kept for the Academy's other voice agents.")
        _recent.append((now, cost))
        return period


# ── ARIA's own allowance: persistent, created offline, never refunded ─────────

def _owned_by_app_user(path: str) -> None:
    """Provisioning from a host shell runs as root, but the server runs as the 'app' user:
    hand the private ledger to it, or the server could not open it until the next restart."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        try:
            import pwd
            entry = pwd.getpwnam("app")
            os.chown(path, entry.pw_uid, entry.pw_gid)
        except (KeyError, ImportError, OSError):
            pass


class VoiceLedger:
    def __init__(self, cfg: VoiceConfig):
        self.cfg = cfg

    def _connect(self):
        # mode=rw: a lost ledger (non-persistent disk) stops voice instead of resetting it
        return sqlite3.connect(Path(self.cfg.path).as_uri() + "?mode=rw", uri=True, timeout=10, isolation_level=None)

    def provision(self) -> None:
        """OFFLINE owner operation, once: creates the ledger file on the persistent disk."""
        with sqlite3.connect(self.cfg.path, timeout=10) as db:
            db.execute("CREATE TABLE IF NOT EXISTS voice_allowance (period TEXT PRIMARY KEY, cap INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0, "
                       "reset INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL DEFAULT 0)")
            have = {r[1] for r in db.execute("PRAGMA table_info(voice_allowance)")}
            for col, decl in (("reset", "INTEGER NOT NULL DEFAULT 0"), ("created", "REAL NOT NULL DEFAULT 0")):
                if col not in have:
                    db.execute(f"ALTER TABLE voice_allowance ADD COLUMN {col} {decl}")
        os.chmod(self.cfg.path, 0o600)
        _owned_by_app_user(self.cfg.path)

    def ready(self) -> bool:
        try:
            db = self._connect()
            try:
                return db.execute("SELECT 1 FROM sqlite_master WHERE name='voice_allowance'").fetchone() is not None
            finally:
                db.close()
        except sqlite3.Error:
            return False

    @staticmethod
    def _resolve(db, period: str) -> tuple[str, int, bool]:
        """(row to charge, reset time, is a new period). Raises when the reset time went backwards."""
        try:
            reset = int(period.rsplit("-", 1)[1])
        except (IndexError, ValueError):
            raise VoiceBlocked("Invalid ElevenLabs billing period.") from None
        newest = db.execute("SELECT period, reset FROM voice_allowance ORDER BY reset DESC LIMIT 1").fetchone()
        if newest and reset < newest[1]:
            raise VoiceBlocked("The ElevenLabs billing period moved backwards; voice stays off until the owner checks the account.")
        if newest and reset < newest[1] + NEW_PERIOD_DAYS * 86400:
            return newest[0], newest[1], False
        return period, reset, True

    def left(self, period: str) -> int:
        db = self._connect()
        try:
            key, _, new = self._resolve(db, period)
            row = None if new else db.execute("SELECT cap, used FROM voice_allowance WHERE period=?", (key,)).fetchone()
        finally:
            db.close()
        return self.cfg.allowance if not row else max(0, min(row[0], self.cfg.allowance) - row[1])

    def reserve(self, period: str, amount: int) -> None:
        """One allowance per billing period. The period is the account's own next reset time, guarded
        so that it cannot be gamed: it may never move backwards, and a reset time less than
        NEW_PERIOD_DAYS after the current period's counts as the SAME period (a plan change or a
        jitter mid-cycle does not bring a fresh allowance; a real monthly rollover does)."""
        if type(amount) is not int or amount <= 0:
            raise VoiceBlocked("Invalid voice reservation.")
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            period, reset, new = self._resolve(db, period)
            if new:
                # a period's cap is fixed when it starts and can only ever shrink, never grow
                db.execute("INSERT OR IGNORE INTO voice_allowance(period, cap, used, reset, created) VALUES(?, ?, 0, ?, ?)",
                           (period, self.cfg.allowance, reset, time.time()))
            cap, used = db.execute("SELECT cap, used FROM voice_allowance WHERE period=?", (period,)).fetchone()
            cap = min(cap, self.cfg.allowance)
            if used + amount > cap:
                raise VoiceBlocked("ARIA has used its ElevenLabs allowance for this billing period.")
            db.execute("UPDATE voice_allowance SET cap=?, used=used+? WHERE period=?", (cap, amount, period))
            db.execute("COMMIT")
        except Exception:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()


def _admit(cfg: VoiceConfig, cost: int) -> None:
    """Every gate, in order, before any billable call. Raises VoiceBlocked."""
    if aria_ai.cooldown("eleven") > 0:
        raise VoiceBlocked("ElevenLabs refused a recent request; voice is paused for a few minutes.")
    ledger = VoiceLedger(cfg)
    if not ledger.ready():
        raise VoiceBlocked("ARIA's ElevenLabs ledger is missing; provision it on the persistent disk.")
    period = account(cfg, cost)
    ledger.reserve(period, cost)


# ── after use: ask ElevenLabs to forget the item (best effort, never blocks) ──

def _forget(cfg: VoiceConfig, path: str) -> None:
    if not cfg.delete_after:
        return
    def run():
        try:
            requests.delete(api_root() + path, headers={"xi-api-key": cfg.key}, timeout=10, allow_redirects=False)
        except requests.RequestException:
            log.info("aria voice: delete after use did not complete")
    threading.Thread(target=run, daemon=True).start()


# ── who may use what ──────────────────────────────────────────────────────────

def _state(request: Request) -> dict:
    ident = aria_ai.identity(request)
    out = {"tts": False, "stt": False, "reason": "", "stt_reason": "", "ident": ident}
    try:
        cfg = VoiceConfig()
    except VoiceBlocked as e:
        out["reason"] = out["stt_reason"] = str(e)
        return out
    out["cfg"] = cfg
    if not VoiceLedger(cfg).ready():
        out["reason"] = out["stt_reason"] = "ARIA's ElevenLabs ledger is missing; provision it on the persistent disk."
        return out
    if ident["guest"] and not ident["owner"] and not cfg.guests:
        out["reason"] = out["stt_reason"] = "Sign in with your Academy account for ARIA's natural voice."
        return out
    out["tts"] = True
    why = cfg.stt_blocked()
    if not why and cfg.stt_mode == "owner" and not ident["owner"]:
        why = "Transcription by ElevenLabs is for the instructor account until student data protections are approved."
    out["stt"], out["stt_reason"] = (why is None), (why or "")
    return out


PRIVACY_TTS = ("Spoken replies use ElevenLabs: ARIA sends the text of its own reply, never your account details. "
               "ARIA asks ElevenLabs to delete each generated clip after it is sent.")
PRIVACY_STT = ("Transcription uses ElevenLabs: only after you tap the orb, your recording is sent to be turned into text. "
               "PROTrader stores no audio, and ARIA asks ElevenLabs to delete each transcript after use.")


@router.get("/api/aria/voice/status")
def status(request: Request) -> dict:
    st = _state(request)
    ident = st["ident"]
    out = {"provider": "elevenlabs", "tts": st["tts"], "stt": st["stt"], "privacy_tts": PRIVACY_TTS, "privacy_stt": PRIVACY_STT,
           "label": "ElevenLabs voice",
           # configured and provisioned on the server (says nothing about the account or who may use it)
           "configured": bool(st.get("cfg")) and (st["tts"] or "Sign in" in st["reason"])}
    cfg = st.get("cfg")
    if cfg:
        out.update(max_chars=cfg.max_chars, max_seconds=cfg.max_seconds)
    if ident["owner"]:                 # configuration reasons are for the owner, not students
        out["reason"], out["stt_reason"] = st["reason"], st["stt_reason"]
    return out


def _clean_text(raw) -> str:
    t = re.sub(r"[\u0000-\u001f\u007f]+", " ", str(raw or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return aria_ai.scrub_text(t)


_ERR = {
    "off": (503, "ARIA's natural voice is not available right now. This device's voice keeps working."),
    "quota": (429, "ARIA's natural voice has reached its allowance. This device's voice keeps working."),
    "busy": (429, "Too many voice requests at once. Try again in a minute."),
    "provider": (502, "ARIA's natural voice could not answer. This device's voice keeps working."),
    "bad": (400, "That voice request was not valid."),
}


def _fail(kind: str, owner_reason: str = "", owner: bool = False) -> JSONResponse:
    code, msg = _ERR[kind]
    body = {"error": kind, "message": msg}
    if owner and owner_reason:
        body["reason"] = owner_reason
    return JSONResponse(body, status_code=code)


def _upstream_error(status_code: int) -> str:
    """A refusal that may mean the account is out of credit or the key is wrong pauses
    ElevenLabs for ten minutes, so the app never keeps knocking on a closed door."""
    if status_code in (401, 402, 403, 429):
        aria_ai.set_cooldown("eleven", time.time() + 600)
        return "quota"
    return "provider"


async def _read_capped(request: Request, limit: int) -> Optional[bytes]:
    """The body, or None when it is larger than limit (whatever Content-Length claims)."""
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > limit:
            return None
    return bytes(buf)


@router.post("/api/aria/voice/speak")
async def speak(request: Request):
    aria_ai._same_origin(request)
    raw = await _read_capped(request, 20000)
    if raw is None:
        raise HTTPException(413, "Too long to speak.")
    # The account check and the upstream call block: never on the event loop.
    return await run_in_threadpool(_speak, request, raw)


def _speak(request: Request, raw: bytes):
    try:
        body = json.loads(raw)
    except ValueError:
        return _fail("bad")
    if not isinstance(body, dict):
        return _fail("bad")
    st = _state(request)
    ident = st["ident"]
    if not st["tts"]:
        return _fail("off", st["reason"], ident["owner"])
    cfg: VoiceConfig = st["cfg"]
    text = _clean_text(body.get("text"))
    if not text:
        return _fail("bad")
    text = text[:cfg.max_chars]
    per_day = cfg.tts_guest_day if ident["guest"] else cfg.tts_user_day
    keys = ["tts:all", "tts:" + ident["key"], "ttsc:" + ident["key"], "tts:" + ident["ip"]]
    c = aria_ai.count(keys)
    if c["tts:all"] >= cfg.tts_all_day or c["tts:" + ident["key"]] >= per_day or c["tts:" + ident["ip"]] >= cfg.ip_per_day \
            or (not ident["owner"] and c["ttsc:" + ident["key"]] + len(text) > cfg.user_chars_day):
        return _fail("quota", "Daily spoken-reply cap reached.", ident["owner"])
    now = time.time()
    if not aria_ai._per_minute_ok("tts:" + ident["key"], cfg.tts_per_min, now) or not aria_ai._per_minute_ok("tts:" + ident["ip"], cfg.tts_per_min * 2, now):
        return _fail("busy")
    aria_ai._per_minute_add(["tts:" + ident["key"], "tts:" + ident["ip"]], now)
    cost = cfg.tts_cost(text)
    try:
        _admit(cfg, cost)
    except VoiceBlocked as e:
        return _fail("quota", str(e), ident["owner"])
    except (sqlite3.Error, OSError):
        return _fail("off", "ARIA's ElevenLabs ledger could not be used.", ident["owner"])
    aria_ai.bump(["tts:all", "tts:" + ident["key"], "tts:" + ident["ip"]])
    aria_ai.bump(["ttsc:" + ident["key"]], len(text))
    url = f"{api_root()}/v1/text-to-speech/{cfg.voice}/stream"
    try:
        r = requests.post(url, params={"output_format": "mp3_44100_64"}, json={"text": text, "model_id": cfg.model},
                          headers={"xi-api-key": cfg.key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
                          stream=True, timeout=(10, 30), allow_redirects=False)
    except requests.RequestException:
        # Ambiguous: the request may have been billed. The reservation stands; no retry.
        return _fail("provider")
    if r.status_code != 200:
        r.close()
        log.warning("aria voice: speak refused upstream (status %s)", r.status_code)
        return _fail(_upstream_error(r.status_code))
    item = r.headers.get("history-item-id", "")

    def stream():
        try:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        except requests.RequestException:
            return
        finally:
            r.close()
            if _ITEM_ID.fullmatch(item or ""):
                _forget(cfg, f"/v1/history/{item}")

    return StreamingResponse(stream(), media_type="audio/mpeg",
                             headers={"Cache-Control": "no-store", "X-ARIA-Voice": "elevenlabs", "X-ARIA-Chars": str(len(text))})


@router.post("/api/aria/voice/transcribe")
async def transcribe(request: Request):
    aria_ai._same_origin(request)
    st = await run_in_threadpool(_state, request)        # who may send audio is decided before any is read
    if not st["stt"]:
        return JSONResponse({"error": "stt_off", "message": "Speech transcription by ElevenLabs is not enabled for this account. Use this device's speech input or type.",
                             **({"reason": st["stt_reason"]} if st["ident"]["owner"] else {})}, status_code=403)
    audio = await _read_capped(request, (st["cfg"].max_seconds + 1) * PCM_RATE * 2)   # in memory only; never written anywhere
    if audio is None:
        return JSONResponse({"error": "length", "message": "That recording is too long."}, status_code=413)
    return await run_in_threadpool(_transcribe, st, request, audio)


def _transcribe(st: dict, request: Request, audio: bytes):
    ident = st["ident"]
    cfg: VoiceConfig = st["cfg"]
    if request.headers.get("x-audio-format", "") != "pcm_s16le_16":
        return _fail("bad")
    seconds = len(audio) / (PCM_RATE * 2)
    if len(audio) % 2 or seconds < 0.3 or seconds > cfg.max_seconds:
        return JSONResponse({"error": "length", "message": f"Recordings must be between half a second and {cfg.max_seconds} seconds."}, status_code=413)
    c = aria_ai.count(["stt:" + ident["key"]])
    if c["stt:" + ident["key"]] >= cfg.stt_day:
        return _fail("quota", "Daily transcription cap reached.", ident["owner"])
    if not aria_ai._per_minute("stt:" + ident["key"], 6, time.time()):
        return _fail("busy")
    cost = cfg.stt_cost(seconds)
    try:
        _admit(cfg, cost)
    except VoiceBlocked as e:
        return _fail("quota", str(e), ident["owner"])
    except (sqlite3.Error, OSError):
        return _fail("off", "ARIA's ElevenLabs ledger could not be used.", ident["owner"])
    aria_ai.bump(["stt:" + ident["key"]])
    lang = str(request.headers.get("x-language", "en"))[:5]
    data = {"model_id": cfg.stt_model, "file_format": "pcm_s16le_16", "tag_audio_events": "false", "timestamps_granularity": "none"}
    if re.fullmatch(r"[a-z]{2,3}", lang):
        data["language_code"] = lang
    try:
        r = requests.post(api_root() + "/v1/speech-to-text", data=data, files={"file": ("aria.pcm", audio, "application/octet-stream")},
                          headers={"xi-api-key": cfg.key}, timeout=(10, 45), allow_redirects=False)
    except requests.RequestException:
        return _fail("provider")
    finally:
        audio = b""                              # drop our only copy as soon as it is sent
    if r.status_code != 200:
        log.warning("aria voice: transcribe refused upstream (status %s)", r.status_code)
        return _fail(_upstream_error(r.status_code))
    try:
        res = r.json()
    except ValueError:
        return _fail("provider")
    tid = str(res.get("transcription_id") or "")
    if _ITEM_ID.fullmatch(tid):
        _forget(cfg, f"/v1/speech-to-text/transcripts/{tid}")
    text = re.sub(r"\s+", " ", str(res.get("text") or "")).strip()[:2000]
    return {"text": text, "language": str(res.get("language_code") or "")[:8], "seconds": round(seconds, 1)}


def check() -> int:
    """Read-only: is voice ready, and what does the account look like? Makes one free account read."""
    try:
        cfg = VoiceConfig()
    except VoiceBlocked as e:
        print("Voice is off:", e)
        return 1
    ledger = VoiceLedger(cfg)
    if not ledger.ready():
        print("Voice is blocked: the ledger is missing. Run: python3 aria_voice.py provision")
        return 1
    try:
        data = _fetch_subscription(cfg)
        remaining, period = check_subscription(data)
    except VoiceBlocked as e:
        print("Voice is blocked by the account check:", e)
        return 1
    reset = int(period.rsplit("-", 1)[1])
    print(f"ElevenLabs {data.get('tier')} ({data.get('status')}): {data.get('character_count'):,} of {data.get('character_limit'):,} credits used;"
          f" resets {time.strftime('%Y-%m-%d', time.gmtime(reset))}; usage-based billing off.")
    print(f"Left in the shared pool: {remaining:,}; kept back for the other agents: {cfg.reserve:,};"
          f" ARIA may use up to {max(0, remaining - cfg.reserve):,} of it right now.")
    print(f"ARIA's own allowance this period: {ledger.left(period):,} of {cfg.allowance:,} credits"
          f" (speech counted at {cfg.tts_rate:g} credit per character, model {cfg.model}).")
    why = cfg.stt_blocked()
    print("Transcription:", f"on for {cfg.stt_mode}" if not why else why)
    return 0


def main(argv: list[str]) -> int:
    """python3 aria_voice.py provision   create ARIA's voice ledger (offline, once, on the persistent disk)
python3 aria_voice.py check       read-only: is voice ready, and what is left (one free account read)"""
    if argv[1:] == ["check"]:
        return check()
    if argv[1:] != ["provision"]:
        print(main.__doc__)
        return 2
    os.environ.setdefault("ARIA_ELEVEN_ENABLED", "1")
    try:
        cfg = VoiceConfig()
    except VoiceBlocked as e:
        print("not provisioned:", e)
        return 1
    VoiceLedger(cfg).provision()
    print("ARIA ElevenLabs ledger ready at", cfg.path)
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv))
