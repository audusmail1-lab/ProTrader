# Pro Trader Academy: launch handoff

## Recommended setup

The owner has purchased **protraderacademy.company** through Cloudflare and already has a Render account with the existing Pro Trader beta app at **https://protrader-jaoy.onrender.com/**. The owner confirms Resend shows **Verified** for this domain and confirms **no academy Render service has been created yet**. The SMTP key still needs secure entry into the new academy service.

- Academy canonical URL: **https://protraderacademy.company**.
- Existing beta app: **https://protrader-jaoy.onrender.com/**; use it for “Open Pro Trader” now.
- Optional later alias: **app.protraderacademy.company**, attached to the existing app service after approval. Do not create or charge for another trading-app server.
- Proposed sender: **Pro Trader Academy <academy@protraderacademy.company>**, usable only once Resend reports the domain verified. This is a sending identity, not a newly created receiving mailbox.

A separate **paid Render Python web service with a persistent disk**, plus the existing prepared SMTP integration, fits the academy. The optional blueprint is `academy_backend/render.yaml`; **do not apply or change the root `render.yaml` or existing trading service**. Configuring the academy incurs a new cost and requires the owner's approval of the concrete service below. The purchased domain does not need to be purchased again.

Official requirements checked September 17, 2026:

- Render requires paid services for persistent disks; its ordinary filesystem is ephemeral: https://render.com/docs/disks.
- Render free services also block common SMTP ports and are not recommended by Render for production: https://render.com/docs/free.
- Resend SMTP needs an API key and verified owned domain: https://resend.com/docs/send-with-smtp.
- Resend's current free transactional allowance is 3,000 emails/month, capped at 100/day: https://resend.com/pricing. This is an email allowance, not domain registration or mailbox hosting.

## Initial budget

The owner prefers US$10–15/month in incremental hosting. The proposed academy service is **0.5 CPU / 512 MB RAM ($7/month) plus 1 GB persistent disk ($0.25/month): $7.25/month base**, before taxes, usage overages and any paid backup storage. The already-running app's existing bill is separate and unchanged. Keep the current Render workspace unless an actual required feature needs an upgrade. Confirm the checkout price and receive explicit approval before creating the new paid service.

## Minimum next step for the owner

Approve the concrete $7.25/month academy configuration above, then create that service in the existing Render account. No new domain or trading-app service is needed. Never paste a password or API key in chat.

## Prepared deployment procedure

1. Use the academy launch branch **codex/academy-launch** in **audusmail1-lab/ProTrader**. The academy blueprint path is **academy_backend/render.yaml**. Verify that this branch/path is visible in GitHub before starting Render setup. Do not select the root blueprint or change the existing trading service. Private local config, databases, setup keys and credentials remain excluded from Git.
2. In the existing Render account choose **New → Blueprint**, select **audusmail1-lab/ProTrader**, choose **codex/academy-launch**, and set Blueprint Path to **academy_backend/render.yaml**. Review only one new service named **protrader-academy**, the paid 512 MB instance, 1 GB disk and the checkout total before applying. Enter **audusmail1@gmail.com** when prompted for the notification recipient. Use the **academy** blueprint path or create a Python service with its build/start commands. It has manual deployments, one process, a private persistent disk at `/var/data`, and health checks at `/healthz`. Never scale this SQLite deployment to multiple instances.
3. The prepared `ACADEMY_ORIGIN` is `https://protraderacademy.company`. Connect that custom domain and HTTPS before signing in. If testing the assigned Render URL first, temporarily set the origin to that exact URL, then restore the academy domain before sending email. Login requests from a different origin are rejected; use the canonical URL for all links.
4. Set `ACADEMY_NOTIFICATION_RECIPIENT` to `audusmail1@gmail.com`. Keep `ACADEMY_MAIL_ENABLED=false` and `ACADEMY_ENROLLMENT_OPEN=false` during setup.
5. In Render's private shell, read `/var/data/academy/setup-token` yourself. Enter it on `/#setup`, set your name/email and your own 12+ character password. Do not send that key/password through chat. The key is removed after bootstrap. The first public instructor account must be created separately unless the existing local database is deliberately migrated through a secure transfer.
6. Add `protraderacademy.company` as a custom domain on the academy service and enter the exact records supplied by that service in Cloudflare. Set `ACADEMY_APP_URL=https://protrader-jaoy.onrender.com/`; “Open Pro Trader” then appears in its navigation. This links the products; it does not combine their login systems or grant broker/trading access. Add an academy backlink to the app once its final URL and app deployment owner are confirmed.
7. The owner has confirmed that Resend shows `protraderacademy.company` as Verified. Create a sending API key restricted to that domain where supported, or reuse an existing appropriate sending key through secure entry.
8. In Render → academy service → Environment, enter SMTP settings directly: host `smtp.resend.com`, port `587`, security `starttls`, user `resend`, password the private API key, and proposed sender `Pro Trader Academy <academy@protraderacademy.company>` after that domain is verified. Use `ACADEMY_SMTP_*` names from `.env.example`. Do not put secrets in GitHub code or chat.
9. With sending still disabled, run `python academy_backend/check_email.py` in the host shell. It checks TLS and authentication only; no email is sent. Review the queued messages before enabling the worker.
10. Set `ACADEMY_MAIL_ENABLED=true` and restart. In Teaching, press “Send a test to my notification address.” Verify both provider acceptance in the outbox and actual arrival in Gmail/spam. Then test one application update, reply and reset message with controlled accounts. SMTP acceptance alone does not prove inbox delivery; no live delivery has been verified yet.
11. Before inviting students, confirm final contact/privacy/retention wording and replace the local-only privacy text, class dates/timezone/join links, fees/admission wording and support process. Verify a backup and restore. Open applications with `ACADEMY_ENROLLMENT_OPEN=true` only after these choices and launch checks are complete.

## Operating limits and verification

The production entry point uses Waitress rather than the local preview HTTP server, behind Render's managed HTTPS proxy. Request body/header/connection limits are configured. Cookies use Secure for HTTPS origins. Forwarded client-IP headers are not trusted automatically; in-process throttling applies both account-specific and coarse peer limits. Before a broad public campaign, configure host/edge abuse controls and load-test against expected traffic.

SMTP requires certificate-verified TLS. Outbox rows are claimed before sending, have stable message identifiers and Resend idempotency keys, and record safe actionable failures without credentials. Sent message bodies are cleared. Interrupted deliveries require provider-log review before manual retry; arbitrary SMTP providers do not guarantee exactly-once delivery, and Resend deduplication has a provider-defined time window. Password reset links remain single-use and expire after 30 minutes.

Use `python academy_backend/backup.py /private-backup-location/new-name.sqlite3` on the host for a consistent SQLite backup, then copy it to secure off-host storage. The file is created with owner-only permissions and validated. Restore only with the service stopped, preserving correct ownership/permissions; keep the previous database until the restored installation passes checks. Decide backup frequency/retention with the owner. The backup contains personal data and recovery/session records; treat it as confidential.

Run `python -m unittest discover -s academy_backend -p 'test_*.py' -v` after installing `academy_backend/requirements.txt` to include the production socket test. Automated tests use fake addresses and mocked SMTP, never real recipients. Public DNS, provider authentication, live email delivery and public-host restart persistence require the accounts/domain to complete verification.

## Latest verification: September 17, 2026

- Existing beta app `https://protrader-jaoy.onrender.com/`: successful HTTPS GET, status 200. It rejects HEAD with 405, so use GET for reachability checks.
- Local academy `http://127.0.0.1:8743`: restarted with actual app URL; rendered Open Pro Trader navigation points to the beta app.
- `protraderacademy.company`: did not resolve through this machine's DNS resolver during the check. Domain registration is confirmed by the owner, but a live academy site is not established by that purchase or by email DNS records.
- The owner has since confirmed Resend Verified status and that there is no academy service yet. This task’s browser exposes only the local academy tab. No SMTP credentials are configured locally; enter them directly into the new hosted service.
- Existing nine tests passed; a test-fixture shutdown race was corrected and the five deployment/email tests passed again cleanly. No real message was sent.

### Concrete next dashboard action

After approving the $7.25/month base cost, use **New → Blueprint**, repository **audusmail1-lab/ProTrader**, branch **codex/academy-launch**, path **academy_backend/render.yaml**. Confirm the new service is named **protrader-academy** and does not modify the existing trading service. The launch branch must be visible remotely before applying.

Once the academy service exists, enter the Resend API key directly into **that service → Environment → Add environment variable**, with the name **ACADEMY_SMTP_PASSWORD**. Use the remaining non-secret SMTP settings from `.env.example`. Do not put the key in the existing trading app service or send it through chat. Keep mail off until the secure connection check passes and queue contents are reviewed. Confirm the Resend domain says **Verified**, then enable email and use Teaching's test button to verify actual receipt in Gmail.
