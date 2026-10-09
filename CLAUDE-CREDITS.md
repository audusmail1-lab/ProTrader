# Claude reasoning for ARIA

This change adds a configurable server-side Claude Messages provider to the
existing ARIA chart copilot. Gemini behavior remains available. Claude is off
by default. Installing this code does not activate a provider, change billing,
purchase credits, or contact Anthropic.

## Verified account facts and remaining activation work

The owner reported claiming Max API credits. Read-only Console inspection on
9 October 2026 confirmed Max 5x promotional credits of $100/$100, a displayed
expiry date of 17 October 2026, purchased credits of $0, no payment method on
file, and auto-reload currently off. Monthly invoicing was not active. The
account is Joel's Individual Org. These are inspection-time facts, not an
ongoing balance guarantee. No Claude API call has been made for this change.

Before live use, obtain the owner's approval to consume promotional credits,
verify those facts again, allocate a small budget below the remaining credit,
confirm the isolated allocation cannot be consumed by other workloads, and
provision a private persistent ledger. $20 of the verified $100 is an initial
budget proposal, not an approved allocation. Use 17 October 2026 00:00 UTC as a
conservative cutoff unless the exact Console expiry time is verified; stop
five minutes before that cutoff. The displayed date did not establish an
exact expiry time.

## What the controls enforce

- Every Claude generation/tool round requires a fresh account attestation
  less than 24 hours old, explicit activation, a known-priced model, a positive
  budget, and a credit expiry more than five minutes away.
- A SQLite `BEGIN IMMEDIATE` transaction reserves a conservative maximum
  request allowance before sending it. All workers use the same persistent
  ledger. The cap and expiry cannot increase for an existing credit period.
- No request handler creates a ledger or credit-period row. Missing storage
  or an unprovisioned period stops requests. Repeated offline provisioning of
  the same period does not reset its counters. Back up the ledger and do not
  restore an older ledger over a newer one.
- Reservations include system prompt, history, tool schemas/results, chart
  context and the full output limit. Client tools only; no prompt caching,
  server tools, batches or priced add-ons are requested.
- Thinking (checked 9 Oct 2026 against the thinking docs): Claude Sonnet 5.5
  rejects `thinking: {type: "disabled"}` with a 400, so ARIA sends its lowest
  setting, `{type: "between_tools"}` (no up-front thinking; short progress notes
  between tool calls), with `output_config.effort` `low` or `medium` (never
  `xhigh`/`max`, which turn that setting into a 400). Haiku 5.5 gets
  `{type: "disabled"}`; the 4.x models get neither field. Thinking tokens are
  billed as output and count toward `max_tokens`, so the reservation (which
  prices every allowed output token) still covers them.
  `ARIA_CLAUDE_THINKING=adaptive` lets Claude decide how much to think, inside
  the same limit.
- Claude's reasoning blocks (encrypted, with a signature) go back to the API
  unchanged inside a tool-use turn, as the API requires. They are never shown,
  older turns' blocks are omitted (allowed; saves input credit), and the app
  drops them from the device once a turn is finished.
  Output is limited to 4,096 tokens, serialized input to 120,000 UTF-8 bytes,
  and each Claude connection/read/stream timeout to 60 seconds.
- Reservations remain consumed on success, error, interruption or timeout.
  There is no automatic retry, refund or fallback after a Claude request starts.
- Upstream redirects are rejected. API credentials appear only in server-side
  environment variables and HTTPS request headers. They are never returned by
  status/chat responses, placed in URLs, or logged by this code.
- System grounding, tool allowlist, privacy scrubbing, chart validation and
  student confirmation of paper orders remain the existing ARIA behavior.

The local allowance is deliberately conservative: twice the full UTF-8 JSON
request size plus 2,048 tokens for provider-side overhead, priced at the reviewed
input rate, plus all allowed output tokens at the reviewed output rate. It is
not an exact tokenizer or an atomic reservation against Anthropic's balance.
The application cannot independently ensure promotional-only billing when an
organization also has purchased credits, invoicing or auto-reload. Prepaid
account controls, no purchased balance, disabled auto-reload and an isolated
allocation are therefore mandatory owner attestations. If those facts cannot
be maintained, leave Claude disabled. No billing-control API is called.

## Configuration through the server's secret settings

Do not paste API keys into chat, source code, browser settings or `.env` files
committed to Git. Set `ANTHROPIC_API_KEY` through the host's protected secret
configuration after activation is authorized. A dedicated Academy-scoped key
is preferable; verify its organization and workspace before use.

| Variable | Required value or purpose |
| --- | --- |
| `ARIA_AI_PROVIDER` | `claude` to select Claude; existing default is `gemini` |
| `ARIA_CLAUDE_ENABLED` | `1` only after live activation is approved; absent/default is off |
| `ARIA_CLAUDE_MODEL` | Reviewed exact model ID; default `claude-sonnet-5-5` |
| `ARIA_CLAUDE_CREDIT_BUDGET_USD` | Positive approved allowance, at most $200; default zero blocks calls |
| `CLAUDE_CREDIT_PERIOD` | Stable 8–80 character ID for this exact grant/billing-cycle allocation |
| `CLAUDE_CREDIT_EXPIRES_AT` | Verified conservative UTC expiry, e.g. `2026-10-17T00:00:00Z` (or a Unix timestamp) |
| `CLAUDE_CREDIT_VERIFIED_AT` | UTC time of the owner's latest Console check, e.g. `2026-10-09T16:00:00Z`; valid for 24 h by default |
| `CLAUDE_ATTESTATION_MAX_HOURS` | Optional, 1–168: how long that check stays valid (default 24) |
| `ARIA_CLAUDE_BUDGET_DB` | Absolute path on verified private persistent storage, shared by every worker |
| `CLAUDE_PREPAID_ONLY_CONFIRMED` | `1` only if monthly invoicing is absent |
| `CLAUDE_AUTO_RELOAD_DISABLED_CONFIRMED` | `1` only if auto-reload is off |
| `CLAUDE_NO_PURCHASED_CREDITS_CONFIRMED` | `1` only if purchased-credit balance is zero |
| `CLAUDE_ISOLATED_ALLOCATION_CONFIRMED` | `1` only if other workloads cannot spend this allocation |
| `CLAUDE_PRICING_CONFIRMED` | `1` after confirming current rates still match the code allowlist |
| `CLAUDE_PERSISTENT_LEDGER_CONFIRMED` | `1` after verifying deployment persistence and backups |
| `ARIA_AI_GEMINI_FALLBACK` | Optional `1`; default off. Also requires existing Gemini key and free-tier confirmation |

Changing these environment values does not itself prove account facts.
Recheck actual Console controls; never enable auto-reload or add a payment
method to satisfy setup. A new credit period must correspond to newly verified
credits, not an application restart. Renewal of an attestation uses the same
period and ledger. Render's existing private `/var/data` disk is a candidate
(`ARIA_CLAUDE_BUDGET_DB=/var/data/aria_claude_ledger.db`); verify it is
actually mounted and keep the database outside public assets.

The reservation is deliberately much larger than the real cost: in the browser
test a typical tool turn (two requests, about 16 turns of history plus the
chart snapshot) reserved about $0.24, roughly six to seven times what Sonnet 5.5
would bill for it. A $20 allowance therefore covers about 80 such turns before
Claude stops (or the labelled Gemini fallback answers). Loosening that margin
is an owner decision, not something this code does by itself.

After approved configuration, provision the ledger once from the host's
shell (Render → Shell). It makes no network calls, and hands the file to the
server's `app` user:

```
python3 claude_credits.py provision
python3 claude_credits.py check      # any time: may Claude run, and what is left
```

Known-price IDs checked on 9 October 2026: `claude-sonnet-5-5` ($2 input/$10
output per million), `claude-sonnet-4-6` ($3/$15), `claude-haiku-5-5` (the higher
context rate $0.50/$2.50 used conservatively), and `claude-haiku-4-5-20251001`
($1/$5). Unknown IDs fail closed until pricing and compatibility are reviewed.

## Gemini fallback and voice

Fallback needs explicit `ARIA_AI_GEMINI_FALLBACK=1` plus `GEMINI_API_KEY` and
the existing `GEMINI_FREE_TIER_CONFIRMED=1`. It can select Gemini before the
first Claude request if configuration, credits or the request-specific
allowance are unavailable. A fallback that requested a chart tool keeps its
Gemini model through the rest of that turn. It does not switch providers
after a Claude timeout/error or during Claude's tool exchange.

The UI states the active provider and its privacy notice ("Claude Sonnet 5.5
(Anthropic API, promotional credits)"; "Gemini (free-tier fallback)" when the
fallback answers). Configured fallback is disclosed in advance because
Google's free-tier inputs may be used for product improvement; Anthropic does
not use API inputs or outputs for training by default. Claude does not provide
Gemini Live tokens. ARIA's natural voice (ElevenLabs) is separate and has its
own gates: see ELEVENLABS-VOICE.md.

## Verification and rollout

Mocked tests (9 Oct 2026): `tests/test_claude_credits.py` (32),
`tests/test_aria_ai.py` (23), and the browser suite
`tests/test_aria_claude_voice_browser.py`, which runs the real server code
against a scripted Anthropic stream. Tests cover the existing ARIA behavior,
Claude wire/stream/tool conversion, secrets, activation/expiry, insufficient
budget, durable cap behavior, cross-process reservations, redirects, bounded
timeouts and fallback tool rounds. No live model intelligence, hosting
environment or provider credit consumption has been tested.

Run the scoped suites with `python3 -m pytest -q tests/test_aria_ai.py
tests/test_claude_credits.py` and `python3 tests/test_aria_claude_voice_browser.py`. All Claude/Gemini calls in them are mocked. The
new suite forbids real HTTP posts. Full app deployment and wider trading
regression tests are separate from this provider-only change. Roll back these
source changes if needed, or set `ARIA_CLAUDE_ENABLED=0` to stop Claude calls.
Stopping Claude must never delete its ledger.

Official references: [Messages API](https://platform.claude.com/docs/en/api/messages/create),
[streaming](https://platform.claude.com/docs/en/build-with-claude/streaming),
[models](https://platform.claude.com/docs/en/models/overview),
[pricing](https://platform.claude.com/docs/en/about-claude/pricing),
[API billing and Max credits](https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage).
