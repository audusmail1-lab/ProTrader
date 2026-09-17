# Academy verification — September 17, 2026

## Verified

- Canonical HTTPS health endpoint: 200. `www` redirects to the canonical domain.
- Existing Pro Trader app: HTTPS GET 200; its service/configuration was not changed.
- Anonymous full lessons, practice material and instructor API: 401. Private database URL: 404.
- Hosted instructor setup, authenticated dashboard and session/data persistence after a Render restart: passed.
- Teaching test notification: sent in the academy outbox, Delivered in Resend, and receipt confirmed by the owner in Gmail. No repeat test was needed.
- Private on-host backup and isolated restore: SQLite integrity passed; instructor account recovered from the copy. Off-host storage is still an owner choice.
- Eleven automated tests passed: admission/verification gates, student isolation, progress/questions/replies, recovery token expiry and single use, session revocation, origin checks, TLS/authentication ordering, outbox success/failure/expiry, production request limits, backup, and notification recipients.
- Isolated browser journey: student sign-in, completed introduction, chart level interaction, saved notes/completion, lesson-linked question, instructor application approval, instructor reply, and learner reading the saved reply after signing in again.
- Fictional ticket: changing one unit to two updates loss/gain from 2/4 to 4/8 credits.
- All seven lessons load without browser errors. All seven video URLs return 200 with video/mp4; the ticket video played to its 30-second end without a media error.
- Desktop layout inspected. A fresh phone-width check could not be completed because the browser viewport control did not apply its requested dimensions. The override was reset; no mobile result is claimed for this pass.

## Repaired

- Beginner enrollment URLs containing `?path=beginner` now resolve instead of showing Page not found.
- The introduction now reads saved account progress and shows practiced status after reload. Its next-step wording distinguishes public introduction from classroom access.
- A stale sign-in in another tab returns to a usable sign-in form when the server rejects the old session.
- The live HTML shell shows loading/account wording rather than briefly displaying the old private-prototype labels.
- QA fixtures explicitly disable email before initialization and use fictional notification recipients. Workflow tests use a mocked transport; no real student notification was sent.

## Launch details still outstanding

Applications are deliberately closed. Public contact/privacy/retention wording and intake details (class dates, timezone, joining links and any fees) still need the owner's decisions. Do not invent them or treat the receiving-MX issue as an outbound-email failure: outbound delivery is verified; the sender address is not an incoming mailbox.
