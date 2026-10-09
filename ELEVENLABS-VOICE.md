# ARIA's natural voice (ElevenLabs)

`aria_voice.py` gives ARIA a natural voice for its own replies and lessons
(text to speech), and lets the owner talk to ARIA through ElevenLabs
transcription (speech to text). It is **off by default**. Installing this code
does not contact ElevenLabs, change the account, or spend credits.

## What it uses, and what it never touches

- Calls only: `GET /v1/user/subscription` (read the balance and billing
  settings), `POST /v1/text-to-speech/{voice}/stream`, `POST /v1/speech-to-text`,
  and the two deletes `DELETE /v1/history/{id}` and
  `DELETE /v1/speech-to-text/transcripts/{id}`.
- Never creates, edits or deletes an agent, voice, phone number, plan, payment
  method or workspace setting. The Academy's **Alex** agent
  (`agent_4801m3by5dhceh5rwx83ynt33ra3`) and the website-support agent are not
  read or changed. ARIA speaks with one existing voice chosen by id
  (`ARIA_ELEVEN_VOICE_ID`), and sends no voice settings, so the stored voice is
  unchanged.
- Agents, their LLM usage and telephony are separate ElevenLabs products with
  their own charges. They are not covered by, or used through, this module.
  The only link is the shared credit pool, protected by the reserve below.

## Zero extra spend: the gates, in order, before every billable request

1. Configuration: `ARIA_ELEVEN_ENABLED=1`, the three owner attestations, a key,
   a voice id, a reviewed model, an allowance, a reserve and a ledger path. Any
   missing or out-of-range value keeps voice off.
2. A pause after any refusal from ElevenLabs (401/402/403/429): 10 minutes, so
   the app never keeps knocking.
3. The live account (read fresh at most every 15 s). Voice is refused when:
   - usage-based billing could apply (`max_credit_limit_extension` is not `0`,
     or the deprecated `allowed_to_extend_character_limit` is true);
   - there is an overage, an open invoice, or either can't be read;
   - the subscription is not active, or the balance or reset time can't be read;
   - **the shared pool would fall below `ARIA_ELEVEN_RESERVE_CREDITS`**, the
     reserve kept for Alex and the website-support agent. ARIA's own spend in
     the last 90 s is subtracted again even after a fresh reading, because the
     account's count can lag.
4. ARIA's own allowance (`ARIA_ELEVEN_ALLOWANCE_CREDITS` per billing period) in
   a persistent SQLite ledger, reserved in one `BEGIN IMMEDIATE` transaction and
   never refunded. The period is the account's own next reset time. It may never
   move backwards, and a reset less than 25 days after the current one counts as
   the same period, so a plan change mid-cycle does not bring a fresh allowance.
   Raising the setting mid-period changes nothing.
5. Per-person limits: daily requests and characters per signed-in person, daily
   requests per network address, per-minute limits, a server-wide daily cap,
   900 characters per spoken reply (the rest stays on screen) and 30 s per
   recording.

No request handler creates the ledger: a lost disk stops voice instead of
resetting it. Credits are counted conservatively at
`ARIA_ELEVEN_TTS_CREDITS_PER_CHAR` (default 1 per character) and
`ARIA_ELEVEN_STT_CREDITS_PER_MINUTE` (no default: transcription stays off until
the owner enters the rate shown for the plan).

## Privacy and retention

- **Spoken replies.** Only text that opts in is sent: ARIA's AI replies and lesson
  text. Balances, positions, order read-backs, briefings and fill announcements
  always use the device's own voice and never leave it. The text is scrubbed of
  emails, phone and card numbers first.
- **Transcription.** This sends the speaker's voice, so it is **owner-only by
  default** (`ARIA_ELEVEN_STT=owner`). ElevenLabs' zero-retention mode is
  enterprise-only, so students keep using the browser's speech input until data
  protections for them are approved.
  - It records only between two taps on the orb. The orb, a red "Recording"
    badge and a timer show it is on.
  - Cancel, closing the sheet, or a tap while the mic is opening sends nothing
    and releases the microphone. ARIA never starts a recording by itself, even
    after asking a question.
  - Audio passes through server memory once as 16 kHz PCM. It is never written
    to disk or logged, and transcripts are not logged either.
- **After use.** ARIA asks ElevenLabs to delete each generated clip from the
  account's history, and each transcript, whenever the API returns its id. This
  is best effort; whether the live API returns those ids has not been verified.
- **Who gets it.** Guests (not signed in) get the device's voice unless the owner
  sets `ARIA_ELEVEN_GUESTS=1`. A guest identity is cheap to rotate, so it would
  let anyone drain ARIA's allowance.
- **Never in the browser.** The key stays in the server's environment and travels
  only in the `xi-api-key` header.

## Configuration (Render → Environment; never in chat, Git or the browser)

| Variable | Value |
| --- | --- |
| `ELEVENLABS_API_KEY` | A key for the account. A restricted key (text to speech, speech to text, history, user read) is preferable |
| `ARIA_ELEVEN_ENABLED` | `1` only after approval |
| `ELEVEN_USAGE_BILLING_OFF_CONFIRMED` | `1` after checking usage-based billing is off in the subscription settings |
| `ELEVEN_PRICING_CONFIRMED` | `1` after checking the credit rates below against the plan |
| `ELEVEN_PERSISTENT_LEDGER_CONFIRMED` | `1` after checking the disk is persistent and backed up |
| `ARIA_ELEVEN_VOICE_ID` | An existing voice id from the account (it is never changed) |
| `ARIA_ELEVEN_TTS_MODEL` | Default `eleven_flash_v2_5`; also `eleven_turbo_v2_5`, `eleven_multilingual_v2`, `eleven_v3`, `eleven_v4`, `eleven_v4_turbo` |
| `ARIA_ELEVEN_TTS_CREDITS_PER_CHAR` | Default `1` (conservative) |
| `ARIA_ELEVEN_ALLOWANCE_CREDITS` | ARIA's cap per billing period (proposal below) |
| `ARIA_ELEVEN_RESERVE_CREDITS` | Credits always left for Alex and website support |
| `ARIA_ELEVEN_LEDGER_DB` | `/var/data/aria_voice_ledger.db` |
| `ARIA_ELEVEN_STT` | `owner` (default), `off`, or `all` (only after student data protections) |
| `ARIA_ELEVEN_STT_CREDITS_PER_MINUTE` | The plan's speech-to-text rate in credits per minute; without it transcription stays off |
| Optional | `ARIA_ELEVEN_GUESTS`; `ARIA_ELEVEN_MAX_CHARS` (900); `ARIA_ELEVEN_STT_MAX_SECONDS` (30); `ARIA_ELEVEN_TTS_PER_DAY` (40); `ARIA_ELEVEN_USER_CHARS_PER_DAY` (8000); `ARIA_ELEVEN_IP_PER_DAY` (80); `ARIA_ELEVEN_TTS_ALL_PER_DAY` (400); `ARIA_ELEVEN_TTS_PER_MIN` (8); `ARIA_ELEVEN_STT_PER_DAY` (60); `ARIA_ELEVEN_DELETE_AFTER_USE` (1) |

Provision the ledger once, in Render's Shell, after the variables are set and
before voice is used. It makes no network call:

```
python3 aria_voice.py provision
```

**Sizing proposal (not approved).** Set the reserve to at least 1.5 times what
Alex and website support used in the busiest recent month (the usage page shows
this). Then set ARIA's allowance to no more than half of what is left after
that reserve. Start small, for example 15,000 credits a month: roughly 15
minutes of speech at 1 credit per character, or 30 minutes on Flash if the plan
bills it at half. Increase it only after reviewing real use.

## Rollback

Set `ARIA_ELEVEN_ENABLED=0`, or remove the key. The app falls back to the
device's voice and speech input at once. Never delete the ledger.

## Tests

- `python3 -m pytest -q tests/test_aria_voice.py`: 52 tests. Every gate above,
  the reserve, the allowance and its period guards, concurrency, wire format,
  deletion after use, owner-only transcription, body limits and secrets.
- `python3 tests/test_aria_claude_voice_browser.py`: a real browser, a fake
  microphone and real MP3 playback against a local ElevenLabs stand-in. Covers:
  - the spoken reply, Stop speaking, interrupting by tapping the orb;
  - recording, Cancel, mic races, failures and fallback;
  - account answers staying on the device, the guest default and phone layout.

All provider calls in these tests are local stand-ins. Nothing has been tested
against the real ElevenLabs API or account.
