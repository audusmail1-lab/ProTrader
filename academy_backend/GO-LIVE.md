# Pro Trader Academy: launch handoff

## Deployment status — September 17, 2026

The academy is deployed and responding at **https://protraderacademy.company**. HTTPS health checks pass; `www.protraderacademy.company` redirects to the canonical address. The public introduction and video guides are available. Applications and email sending remain disabled while the owner completes private setup.

- Repository: **audusmail1-lab/ProTrader**, branch **codex/academy-launch**.
- Blueprint: **academy_backend/render.yaml**. The root blueprint belongs to the existing trading app; leave it unchanged.
- Render service: **protrader-academy**, ID **srv-dam1oklbedkc73abn56g**.
- Render blueprint: **exs-dam1n6rm8hqs73b9dfbg**.
- Hosting: Frankfurt, 0.5 CPU / 512 MB, persistent 1 GB disk mounted at `/var/data`; academy data is `/var/data/academy`.
- Owner approved **$7.25/month base** ($7 service plus $0.25 disk), before taxes and usage extras. The service and disk have already been created. Do not create duplicates or request the same approval again.
- Existing beta trading app: **https://protrader-jaoy.onrender.com/**. It remains unchanged and is linked from academy navigation. The two products have separate sign-in systems.
- Instructor notification recipient: **audusmail1@gmail.com**.
- First hosted instructor: not yet created at the latest public session check. Local accounts are not automatically copied to production.

## DNS and email

Cloudflare now has DNS-only CNAME records for the root and `www`, both pointing to `protrader-academy.onrender.com`. Both passed Render verification; public HTTPS succeeds. The root certificate initially reported an error while provisioning, but a later certificate-validated HTTPS request succeeded.

Resend's dashboard originally showed a sending-region mismatch. The `rsend` CNAME was corrected from `rsend.forge.rmta.net` to the dashboard-required **rsend-euw1.forge.rmta.net**. The other sending CNAME remains `send.forge.rmta.net`; DKIM was already verified. After restarting verification, all three sending records showed Verified and the sending error banner disappeared. The overall domain was still Pending, with a separate receiving-MX failure. Receiving is not required for outbound academy notifications, and no root receiving MX was added. Do not claim actual email delivery until tested.

Non-secret SMTP settings are deployed: `smtp.resend.com`, port `587`, STARTTLS, username `resend`, sender **Pro Trader Academy <academy@protraderacademy.company>**. This sender is not a receiving mailbox.

The owner is being handed the prepared Resend key form (Sending access, restricted to `protraderacademy.company`) and a blank Render environment value named **ACADEMY_SMTP_PASSWORD**. They must create/copy the key and save it directly in the academy service. Never place the key or a password in chat or Git. Keep `ACADEMY_MAIL_ENABLED=false` until checks pass.

## Remaining owner setup and launch checks

1. Finish secure entry of the Resend key in **Render → protrader-academy → Environment → ACADEMY_SMTP_PASSWORD**, then deploy/restart so the service receives the saved value. Avoid changing the existing trading app service.
2. Run `python academy_backend/check_email.py` in the academy's Render Shell. This checks TLS and authentication without sending any message. Check Resend's sending-domain status as well.
3. In Render's private shell, read `/var/data/academy/setup-token` yourself. Open **https://protraderacademy.company/#setup**, enter that key and your name/email, and choose your own 12+ character password. Do not send the key/password through chat. The token is removed after the first instructor is created.
4. Review the notification outbox. Set `ACADEMY_MAIL_ENABLED=true` in both the deployment configuration and the hosted environment, then deploy. From Teaching, use **Send a test to my notification address**. Verify provider acceptance and actual arrival in Gmail/spam; acceptance alone does not prove inbox delivery. Then check application-update, instructor-reply and password-reset messages with controlled accounts.
5. Before inviting students, confirm final privacy/contact/retention terms, session dates/timezone/join links, fees and admission operations. The privacy page explains stored data but still calls out unfinished final terms. Verify backup and restore, and agree secure off-host backup storage/frequency.
6. Open applications with `ACADEMY_ENROLLMENT_OPEN=true` only after these checks and decisions. The public interface now reads application availability from the server, so closed applications show an explanatory page instead of a form that cannot be submitted.

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

Run `python -m unittest discover -s academy_backend -p 'test_*.py' -v` after installing `academy_backend/requirements.txt` to include the production socket test. Automated tests use fake addresses and mocked SMTP, never real recipients. Public DNS, provider authentication, live email delivery and public-host restart persistence require the accounts/domain to complete verification.

## Latest verification: September 17, 2026

- Canonical academy `/healthz`: certificate-validated HTTPS, status 200, `{"ok": true}`.
- `www` academy URL: HTTPS 301 to the canonical domain.
- Anonymous `/api/session`: no signed-in user; first instructor setup still required.
- Anonymous `/api/lessons`: 401, sign-in required.
- Existing trading app: successful HTTPS GET, status 200; unchanged by this deployment.
- Ten automated account, enrollment, isolation, persistence, recovery, SMTP and production tests passed after adding application-availability checks. JavaScript syntax and patch formatting checks passed.
- Live SMTP authentication, actual inbox receipt, hosted account creation and restart persistence still require completion. No real notification has been sent by this task.
