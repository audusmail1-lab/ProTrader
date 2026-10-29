# Oracle workspace integration

The independent Oracle review, ARIA ten-condition checklist, saved-review Journal and guided Learn practice are integrated with the existing ProTrader app. Sentinel, drawing tools, accounts, voice services, paper trading and the live bridge retain their existing roles.

Oracle opens with the saved interpretation, four timeframe readings and separate setup/context invalidation. Its composer remains visible while the reading scrolls. More options holds detailed evidence, connection information, Journal saves and earlier discussions. New model-supplied frame directions are optional; older records show explicitly named calculated swing descriptions instead.

## Local review

From this repository, run:

```sh
python3 scripts/start_oracle_preview.py --port 8042 --agent-config .preview-state/oracle-agent.json
```

The local `.preview-state/oracle-agent.json` stores only the nonsecret private-agent reference; it is ignored by Git and Docker. Other installations may supply their own `--agent-config` or `ORACLE_ELEVENLABS_AGENT_ID`. The launcher reuses the Mac Keychain entry when available. The API key never belongs in this JSON file. It binds to loopback, isolates seven local state paths, disables background execution/notification workers and keeps public Oracle access off. An explicit `--state-dir` may retain an existing isolated preview's server state. Browser data remains scoped to its origin; changing the port creates a separate browser workspace.

Do not set `PROTRADER_LOCAL_PREVIEW=1` on ordinary production startup: it deliberately blocks bridge, notification and live-strategy mutations. The normal app startup and existing execution logic are unchanged.

## Release configuration

Public Oracle access is disabled by default. Enabling it requires server-side provider credentials, an authenticated accepted account, an exact HTTPS origin, an explicit account allowlist and provider usage/duration review. API keys must never be put in the browser bundle. Session/image attempt limits do not cap the duration or cost of an already connected conversation.

Account documents retain the existing 1,500,000-byte limit. Oversized histories remain local with an explicit synchronization error and export/removal recovery. Image uploads work, but visual interpretations require checking against the original chart. Passing software checks does not establish trading accuracy or profitability.

## Verification

Run the Node suites with:

```sh
node --test tests/*.test.cjs tests/order_math.test.js tests/stop_out.test.js
```

Run backend unit tests with `python3 -m pytest -q` after installing development-only pytest, httpx and pytest-subtests in an isolated environment. Disable background services and use temporary database paths for tests. `tests/conftest.py` excludes standalone browser scripts from pytest; passing unit tests is not a claim that those browser journeys ran. The updated interactions also require hands-on browser verification.

The dedicated stylesheet-endpoint test protects the CSS Content-Type and nosniff contract, which is essential for the external Oracle, Journal and Learn stylesheets to render.
