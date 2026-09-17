# Pro Trader Academy: launch handoff

## Deployment status — September 17, 2026

The academy is deployed and responding at **https://protraderacademy.company**. HTTPS health checks pass; `www.protraderacademy.company` redirects to the canonical address. The public introduction and video guides are available. The hosted instructor account and email delivery are working. The owner received the live test notification in Gmail. The owner approved a free intake for adults 18+, public contact and policy pages, and the retention schedule. The launch release opens applications; class dates and joining links will be confirmed separately. See [the launch-copy release](LAUNCH-COPY-RELEASE.md).

- Repository: **audusmail1-lab/ProTrader**, branch **codex/academy-launch**.
- Blueprint: **academy_backend/render.yaml**. The root blueprint belongs to the separate trading app and now records the owner-approved Starter plan; do not mix the two service configurations.
- Render service: **protrader-academy**, ID **srv-dam1oklbedkc73abn56g**.
- Render blueprint: **exs-dam1n6rm8hqs73b9dfbg**.
- Hosting: Frankfurt, 0.5 CPU / 512 MB, persistent 1 GB disk mounted at `/var/data`; academy data is `/var/data/academy`.
- Owner approved **$7.25/month base** ($7 service plus $0.25 disk), before taxes and usage extras. The service and disk have already been created. Do not create duplicates or request the same approval again.
- Existing beta trading app: **https://protrader-jaoy.onrender.com/**. It is linked from academy navigation and was upgraded to the owner-approved $7/month Starter hosting on September 17; its application behavior was not changed. The two products have separate sign-in systems.
- Instructor notification recipient: **audusmail1@gmail.com**.
- First hosted instructor: created by the owner with their privately chosen password. Teaching dashboard access, session persistence and saved records were verified after a Render service restart. The one-time bootstrap is complete.

## DNS and email

Cloudflare has CNAME records for the root and `www`, both pointing to `protrader-academy.onrender.com`. At the launch-copy update, both were already proxied; this setting was preserved. Both passed Render verification; public HTTPS succeeds. The root certificate initially reported an error while provisioning, but a later certificate-validated HTTPS request succeeded.

Resend's dashboard originally showed a sending-region mismatch. The `rsend` CNAME was corrected from `rsend.forge.rmta.net` to the dashboard-required **rsend-euw1.forge.rmta.net**. The other sending CNAME remains `send.forge.rmta.net`; DKIM was already verified. After restarting verification, all three sending records showed Verified and the sending error banner disappeared. The overall domain later showed Partially Failed because of a separate receiving-MX failure. Receiving is not required for outbound academy notifications, and no root receiving MX was added. Outbound delivery has since passed the live test.

Non-secret SMTP settings are deployed: `smtp.resend.com`, port `587`, STARTTLS, username `resend`, sender **Pro Trader Academy <academy@protraderacademy.company>**. This sender is not a receiving mailbox.

The owner saved the Resend key directly as **ACADEMY_SMTP_PASSWORD** in the academy service. The deployed `check_email.py` command passed TLS and authentication on September 17. The outbox was empty before delivery was enabled. The blueprint now sets `ACADEMY_MAIL_ENABLED=true` and declares the password with `sync: false`, so its value remains managed privately in Render. Never place a key or password in chat or Git. One “Academy email delivery test” was sent from Teaching: the outbox recorded sent, Resend recorded Delivered, and the owner confirmed arrival in Gmail. No repeated test was sent.

## Completed setup and remaining launch details

- The owner saved the private Resend key and created the hosted instructor account. Do not ask them to repeat either step.
- Live email delivery is verified through the Teaching test button and the owner’s Gmail confirmation.
- The instructor account, signed-in session and sent notification remained available after the Render service restart.
- A private backup was created at `/var/data/academy/launch-backup-20260917.sqlite3`. A copy restored into an isolated temporary directory passed SQLite integrity checks and contained the instructor account; the live database was not replaced. This is an on-host backup, not off-host disaster recovery.

The approved public contact is **support@protraderacademy.company**, forwarded through Cloudflare Email Routing to **audusmail1@gmail.com**. The destination is verified, the support rule is active, and the owner confirmed receipt of “Academy support address test.” Cloudflare's incoming MX/SPF/DKIM records were added without replacing Resend's sending records. Notifications use the support address as Reply-To. The domain address is a forwarding alias; it does not create a new mailbox or a Gmail “send as” identity.

The owner approved the published identity, correspondence address, 18+ eligibility, response target and retention schedule in [PRIVACY-OPERATIONS.md](PRIVACY-OPERATIONS.md). Public privacy, terms, risk and contact pages are implemented. The current academy offering is free, so there is no checkout or refund policy to configure. `ACADEMY_ENROLLMENT_OPEN=true` is in the launch blueprint; server-side policy readiness is also required. Class dates, timezone and joining links still need to be entered when confirmed. The initial encrypted off-host export and source ZIPs are stored in the owner’s restricted Google Drive folder. An isolated restore passed and the owner confirmed key storage in Google Password Manager. Recurring backup frequency remains to be approved; see [OFFSITE-BACKUPS.md](OFFSITE-BACKUPS.md) for verification scope.

Applications appear under **Teaching → Applications**, including age and policy acknowledgment. Saved student questions and replies appear under **Teaching → Open question inbox**. Instructor alerts go to **audusmail1@gmail.com**. General support and privacy emails go to that same Gmail inbox through the support alias, not into the lesson question inbox.

Do not scale the SQLite service to multiple instances. Optional `app.protraderacademy.company` and an academy backlink in the trading app can be considered separately; no new trading service is needed.

## Provider references

Requirements checked September 17, 2026:

- Render persistent disks: https://render.com/docs/disks
- Render free-service restrictions (including SMTP ports): https://render.com/docs/free
- Render custom domains and Cloudflare DNS: https://render.com/docs/custom-domains and https://render.com/docs/configure-cloudflare-dns
- Resend SMTP: https://resend.com/docs/send-with-smtp
- Resend domain sending/receiving status: https://resend.com/docs/dashboard/domains/manage-domains
- Resend allowance: https://resend.com/pricing (free transactional plan: 3,000 emails/month, 100/day; not mailbox hosting).

## Operating limits and verification

The production entry point uses Waitress rather than the local preview HTTP server, behind Render's managed HTTPS proxy. Request body/header/connection limits are configured. Cookies use Secure for HTTPS origins. Forwarded client-IP headers are not trusted automatically; in-process throttling applies both account-specific and coarse peer limits. Before a broad public campaign, configure host/edge abuse controls and load-test against expected traffic.

SMTP requires certificate-verified TLS. Outbox rows are claimed before sending, have stable message identifiers and Resend idempotency keys, and record safe actionable failures without credentials. Sent message bodies are cleared. Interrupted deliveries require provider-log review before manual retry; arbitrary SMTP providers do not guarantee exactly-once delivery, and Resend deduplication has a provider-defined time window. Password reset links remain single-use and expire after 30 minutes.

Use `python academy_backend/backup.py /private-backup-location/new-name.sqlite3` on the host for a consistent SQLite backup, then copy it to secure off-host storage. The file is created with owner-only permissions and validated. Restore only with the service stopped, preserving correct ownership/permissions; keep the previous database until the restored installation passes checks. Decide backup frequency/retention with the owner. The backup contains personal data and recovery/session records; treat it as confidential.

Run `python -m unittest discover -s academy_backend -p 'test_*.py' -v` after installing `academy_backend/requirements.txt` to include the production socket test. Automated tests use fake addresses and mocked SMTP, never real recipients. Public DNS, SMTP authentication, a real notification and instructor-account persistence after a service restart have also been verified on the hosted installation.

## Latest verification: September 17, 2026

- Canonical academy `/healthz`: certificate-validated HTTPS, status 200, `{"ok": true}`.
- `www` academy URL: HTTPS 301 to the canonical domain.
- First instructor setup completed; authenticated Teaching access verified, including after a service restart.
- Anonymous `/api/lessons`: 401, sign-in required.
- Existing trading app: successful HTTPS GET, status 200; unchanged by this deployment.
- Eleven automated account, enrollment, isolation, persistence, recovery, SMTP and production tests passed, including notification recipient checks. JavaScript syntax and patch formatting checks passed.
- Live SMTP TLS/authentication check passed with the privately saved key. Email delivery has been enabled after an empty-outbox check.
- A real Teaching test notification was accepted, marked Delivered by Resend and confirmed received by the owner in Gmail.
- Private backup integrity and an isolated restore check passed; one hosted instructor account was present. The initial off-host copy is now in restricted Google Drive; recurring automation is not enabled. See [OFFSITE-BACKUPS.md](OFFSITE-BACKUPS.md).
- Navigation, saved introduction status and stale-session recovery repairs are live as commit `7234f595617b42cfc571047d9cb97ec3e96b5b7d`. Post-deployment health, access restrictions, served files and instructor records were verified. See [the detailed verification report](VERIFICATION.md), including the fresh mobile-check limitation.
