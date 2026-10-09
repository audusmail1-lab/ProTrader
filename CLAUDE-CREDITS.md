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
  context and the full output limit. Plain text/client tools only; no extended
  thinking, prompt caching, server tools, batches or priced add-ons are requested.
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
| `CLAUDE_CREDIT_EXPIRES_AT` | Verified conservative UTC Unix expiry timestamp |
| `CLAUDE_CREDIT_VERIFIED_AT` | UTC Unix timestamp of latest owner verification; expires after 24h |
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
period and ledger. Render's existing private `/var/data` disk is a candidate;
verify it is actually mounted and keep the database outside public assets.

After approved configuration, provision the ledger once in an offline owner
maintenance session before starting the application. This operation makes
no network calls:

```python
from claude_credits import CreditConfig, CreditLedger
CreditLedger(CreditConfig.from_environment("")).provision()
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

The UI states the active provider and its privacy notice. Configured fallback
is disclosed in advance because Google's free-tier inputs may be used for
product improvement. Claude does not provide Gemini Live tokens. Standard
device speech remains available; ElevenLabs voice is outside this code change.

## Verification and rollout

49 mocked tests passed; the final reviewed test count is also recorded
in the accompanying integration review. Tests cover the existing ARIA behavior,
Claude wire/stream/tool conversion, secrets, activation/expiry, insufficient
budget, durable cap behavior, cross-process reservations, redirects, bounded
timeouts and fallback tool rounds. No live model intelligence, hosting
environment or provider credit consumption has been tested.

Run the scoped suites with `python3 -m pytest -q tests/test_aria_ai.py
tests/test_claude_credits.py`. All Claude/Gemini calls in them are mocked. The
new suite forbids real HTTP posts. Full app deployment and wider trading
regression tests are separate from this provider-only change. Roll back these
source changes if needed, or set `ARIA_CLAUDE_ENABLED=0` to stop Claude calls.
Stopping Claude must never delete its ledger.

Official references: [Messages API](https://platform.claude.com/docs/en/api/messages/create),
[streaming](https://platform.claude.com/docs/en/build-with-claude/streaming),
[models](https://platform.claude.com/docs/en/models/overview),
[pricing](https://platform.claude.com/docs/en/about-claude/pricing),
[API billing and Max credits](https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage).
