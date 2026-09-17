# Working academy

For the prepared public deployment, email setup and remaining owner choices, see [GO-LIVE.md](GO-LIVE.md). The optional academy Render blueprint is separate from the trading app’s root configuration. No public deployment or real email delivery has occurred.

Run from the repository root:

```sh
python3 academy_backend/server.py
```

Open http://127.0.0.1:8743. This serves the connected application; the static prototype on port 8742 remains separate.

## First instructor

Open Instructor setup in the footer. Use the private key in `.academy-data/setup-token`, enter your name and email, and choose a password of at least 12 characters. A local `/#setup/KEY` link can prefill the key. Setup closes after the first instructor is created. Never share that link or key.

## Daily use

Applications appear under Teaching. Review the details, verify the person's email ownership through trusted contact, check the verification box, and accept or request more information. Students see their status and your note in My account. Only accepted, verified accounts can open full lessons or submit questions.

Students save notes and completion from each lesson. Questions retain their lesson and replies. Teaching also manages the shared class schedule and notification outbox. Add the date, time, timezone and HTTPS joining link for each confirmed session.

SQLite stores users, sessions, applications, practice work, questions, replies and queued notifications in `.academy-data/academy.sqlite3`. Back up the data directory securely with the server stopped. Never place it in a public web directory or commit it. Passwords are salted and hashed; session and recovery tokens are hashed. The separate mail queue contains recovery links until removed under the operator's retention policy.

## Email setup

Alerts go to the recipient in the private, ignored `academy.config.local.json`. Sending is disabled by default. The service uses authenticated SMTP with STARTTLS, including Resend on port 587. See `.env.example` for environment variable names; this server does **not** automatically load dotenv files. Configure these values through your hosting secret settings or export them into the server's environment, then restart.

Resend requires a domain you own and have verified. The sender must use that domain; your Gmail address can remain the recipient. Follow https://resend.com/docs/send-with-smtp and https://resend.com/docs/dashboard/domains/introduction.

When enabled, queued messages are processed every ten seconds. `sent` means the SMTP server accepted the message, not guaranteed inbox delivery. Failed messages can be retried from Teaching after checking provider logs for uncertain acceptance. A test-email button is available only when sending is configured. Expired password reset messages are skipped; request a fresh reset after email is connected. Before enabling delivery, review any queued test messages. No actual email delivery has been tested in this build.

## Public launch still required

The current preview is a working local installation, not a publicly deployed service. The preview binds to 127.0.0.1; the prepared Waitress production entry point binds to the host’s injected port. A production deployment needs an HTTPS reverse proxy/managed host, persistent private storage and backups, the correct `ACADEMY_ORIGIN` public URL, a verified email sender, and an end-to-end delivery test. Configure account-abuse protection at the proxy; in-process throttling combines per-account and coarse connection-peer limits and is not suitable alone for broad public traffic. Confirm privacy/contact/retention terms, fees, actual session times and admission operations before inviting real learners. The existing local-only privacy page must be updated for the deployment.

## Verification

```sh
python3 -m unittest discover -s academy_backend -p 'test_*.py' -v
```

Tests use temporary databases and local ports. They cover instructor bootstrap, admission/verification gates, protected materials, cross-student isolation, persistence, requests from the wrong origin, questions and replies, application resubmission, schedule validation, and password recovery/session revocation. `qa_preview.py` is an isolated browser-test fixture with fictional accounts, never a production launcher.
