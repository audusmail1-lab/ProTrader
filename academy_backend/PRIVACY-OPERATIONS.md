# Academy privacy operations

Owner: Joel Idoga Audu. Approved September 17, 2026. This is an operating procedure, not an automated deletion job.

## Published choices

- Free academy intake, adults 18+ only. Applicants acknowledge the privacy notice and agree to the terms/risk notice. The server records the version, timestamp and adult confirmation. This is a service acknowledgment, not bundled marketing consent.
- Public correspondence address: 391 Katampe, FCT Abuja, Nigeria.
- Public contact: support@protraderacademy.company, forwarded to audusmail1@gmail.com. The owner confirmed receiving the routing test. Target response: 1–2 business days. Email only; no phone or WhatsApp number was authorized.
- Incoming delivery has been verified through Cloudflare routing and the owner’s Gmail receipt. General emails remain in Gmail; lesson questions remain in Teaching.

## Monthly record review

The owner approved these maximum routine periods:

| Record | Removal due |
| --- | --- |
| Declined or withdrawn application | 90 days after final decision/withdrawal |
| Closed account and its learning records | 90 days after closure; earlier when an applicable erasure request requires it |
| Resolved support email | 12 months after closure |
| Backups containing deleted data | Within 30 days of active-system deletion |

Review outstanding privacy requests and records monthly. Record the date, category, completion and any specific legal hold in a private operations log; do not put student names/emails in Git. Pending applications should be followed up and resolved, not silently kept pending indefinitely.

For application decisions, the audit table records the decision time. Withdrawal and closure requests currently arrive by email: privately record the request/closure date, revoke access and arrange the corresponding deletion. No current production student account needs removal; do not delete real accounts as a test. Support-email retention must also be applied to Gmail (including its trash/recovery behavior).

## Requests for access, correction or erasure

1. Acknowledge the request and confirm the requester controls the account email. Avoid collecting identity documents unless proportionate and necessary.
2. Explain the scope and any lawful limits. Include account, application/decision notes, progress, questions/replies, agreements, relevant mail and audit records when applicable.
3. For closure, revoke sessions, reset/verification tokens and unexchanged app sign-in codes (`app_codes`) promptly and stop queued notifications. Record the closure date privately. The linked app maintains a separate session; coordinate any necessary app-session revocation through its own account procedure. Do not reset the whole database.
4. Before a requested deletion, identify only that user's records and confirm any specific hold. Use a reviewed maintenance script and one transaction, deleting child records before the user:
   - Delete `support_messages` for that user's `support_threads`, then those `support_threads`. Include their website support content in access/export requests too. Review guest conversations separately when ownership can be verified; never remove another visitor's conversation by assumption.
   - Delete replies to the user's questions and replies authored by the user, then the user's questions and progress.
   - Delete their sessions, reset/verification tokens, `app_codes`, agreements and application-note settings.
   - Delete associated `class_mail` references before deleting identifying queued/sent mail, and remove identifying audit references.
   - Delete the user record last. Confirm no linked records remain before committing; SQLite user IDs can be reused, so orphaned support rows must not survive account deletion.
   The normal dashboard does not provide this operation yet. This checklist is a maintenance procedure, not an automatic deletion job or evidence that a deletion has been performed.
5. Track all backups, including `/var/data/academy/launch-backup-20260917.sqlite3`. Remove or replace copies containing the deleted records within 30 days. If an older backup is restored in the meantime, reapply approved deletions before reopening access. The initial encrypted off-host export is now stored in the owner’s restricted Google Drive folder; apply this deletion deadline to every copy. Recurring automation is not yet enabled. See [OFFSITE-BACKUPS.md](OFFSITE-BACKUPS.md).
6. Confirm what was done to the requester and close the private request log. Keep only necessary evidence of handling the request.

## Providers and transfers

The current academy uses Render (Frankfurt), Resend (Ireland sending region), Google Gmail/Fonts, CloudFront videos and Cloudflare DNS/proxy services. Domain email forwarding adds Cloudflare routing. The separate Pro Trader app needs its own data inventory and notice; do not imply this academy notice covers broker or trading data.

Retain the applicable vendor terms/data-processing documents and assess international-transfer safeguards and any registration duties applicable to the operator. This page and the public copy are not a certification of compliance. Sources checked: [NDPC GAID 2025, articles 19, 27 and 45](https://ndpc.gov.ng/wp-content/uploads/2025/03/NDP-ACT-GAID-2025-MARCH-20TH.pdf) and [Nigeria Data Protection Act 2023](https://placng.org/i/wp-content/uploads/2023/06/Nigeria-Data-Protection-Act-2023.pdf).
