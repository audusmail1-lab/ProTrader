# Local cancellation patch to @elevenlabs/client 1.28.0

Patched 2026-10-22 for ProTrader's explicitly selected WebSocket voice/text transport. Upstream MIT license is retained unchanged in `elevenlabs-client-1.28.0.LICENSE`. This is a locally modified bundle, not an upstream ElevenLabs release.

- Original bundled SHA-256: `cfccb4799627b4966153ada964744d31fce3aa6d0e343e5931d3ab5ed1f30b79`
- Patched SHA-256: `8668558efef623234a4489b57f9b28aad82f20beebc0fc0c285f5271be771444`
- Patched SRI: `sha384-mInCClZWQbJIaDMZrLVzIBlTlQ6ua0aoWU8oDxD3BINiqsKYEttOx3lX95xUqA1a`
- Runtime marker: `oracleCancellationPatchVersion = 1`

## Why

Upstream voice startup awaited microphone permission before exposing a session object. Cancelling in the application could not stop that setup. A later permission grant could create a provider socket and retain a microphone stream after the UI had disconnected.

## Auditable change scope

1. Added small signal/resource helpers (`oracleAwait`, `oracleResources`, `oracleCheck`, stream cleanup) inside the bundle. A late resource is disposed even after its awaiting promise was cancelled.
2. WebSocket handshake startup accepts `options.signal`; cancellation closes its owned socket while metadata is pending. Text startup checks the same signal across its delay and socket handoff.
3. Web voice startup owns its wake lock, preliminary microphone, socket and audio controllers until the session is handed off. Cancellation checks occur across async boundaries. Late permission/wake-lock grants are disposed; they cannot restart startup. Stage callbacks distinguish microphone permission, provider connection and audio preparation.
4. Audio input/output startup own and clean their contexts/streams/elements during pending worklet loads, permission requests, resume and device selection. A failed peer controller aborts and closes the other. Late input-device changes cannot reactivate a closed microphone.
5. Voice shutdown initiates socket, microphone, playback and wake-lock cleanup independently so one slow/rejected cleanup cannot prevent the others. Playback elements and generated streams are explicitly stopped/removed. Wake-lock re-acquisition is guarded during shutdown.
6. The app transport supplies a 30-second startup deadline and AbortSignal, updates cancellation state immediately, and rejects a preloaded SDK missing the local cancellation marker. No order, market-analysis or model behavior changes.

The patch is exercised by `tests/oracle-sdk-cancellation.test.cjs` against this actual bundle with isolated browser-platform doubles, including late permission, denied permission, ignored permission, silent handshake, audio setup failure, repeated sessions, text recovery and draft-preserving mounted UI cancellation. Existing transport/analyst regression coverage remains in their respective test files. Real microphone permission prompts, audio output and provider connectivity still require browser acceptance checks.

Do not replace the SDK bundle without reapplying/re-evaluating cancellation support and updating the integrity constant in `oracle-conversation.js`. The patch does not claim cancellation coverage for ElevenLabs' unrelated WebRTC/Scribe paths; ProTrader uses WebSocket only.
