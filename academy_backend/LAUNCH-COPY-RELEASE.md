# Free intake launch update — 17 September 2026

**Live:** commit `88d8c35a3b80d8a5d69eedc8f82584b7094f6d37`, Render deployment `dep-dam4ustbedkc73amthlg` (41 seconds, succeeded), blueprint sync `exe-dam4usjncjis73cki5mg`.

Post-release checks: certificate-validated HTTPS health passed; served HTML, JavaScript and CSS match the tested release; the public session reports published policy, support address, adult-only eligibility and open applications. Anonymous private lesson/admin requests remain denied. The instructor session still works. All four live information pages and Teaching rendered without browser errors.

## Owner-approved details

- Operator: Joel Idoga Audu; public correspondence address: 391 Katampe, FCT Abuja, Nigeria.
- Current academy offering is free; no card, checkout, automatic subscription or retroactive charge.
- Intake is adults 18+ only. Class dates and joining links will be confirmed separately in the classroom; application does not guarantee admission.
- Public contact: support@protraderacademy.company. Cloudflare Email Routing forwards to audusmail1@gmail.com. The owner confirmed receiving “Academy support address test.” Existing Resend sending records were retained.
- Email-only contact. Target response: 1–2 business days. No WhatsApp/call number published.
- Retention schedule and manual monthly procedure: [PRIVACY-OPERATIONS.md](PRIVACY-OPERATIONS.md).

## Changes

Beginner-first homepage with free pricing, visible Open App and Join the Academy links; complete contact, privacy, terms and risk pages; legal footer and essential-cookie notice. The privacy notice describes the academy's actual fields and providers, and distinguishes the separate app. Removed speculative phone/payment/analytics collection, unsupported guaranteed security language and blanket exclusion of all liability. No fabricated domain inboxes or contact form submissions.

Registration requires adult confirmation, a privacy acknowledgment, agreement to the terms and the current policy version. The server records version and time; the instructor sees the acknowledgment alongside the application. A publication/details gate prevents incomplete policy configuration from opening registration. Existing accounts remain intact.

Deployment configuration opens applications and sets notification Reply-To to the tested support address. The dashboard remains the source for lesson questions/replies; general contact email goes to Gmail.

## Validation

- All 13 automated tests pass, including rejected missing age/terms/privacy checks, stale policy version, incomplete publication gate, stored acknowledgment, recipient routing, Reply-To and header-injection rejection.
- JavaScript syntax and patch formatting pass.
- Contact, privacy, terms and risk routes rendered in the browser with no console errors. Reviewed the application notice and unchecked confirmation fields. Contact page shows the tested support address and approved response target.
- Desktop screenshots reviewed. Phone-width preview was attempted, failed at the browser-control layer and was reset; no fresh mobile pass is claimed.
- Support forwarding: Cloudflare active rule to verified Gmail destination; one non-sensitive test sent from the existing Resend transport, receipt confirmed by owner.

The public policies reflect approved operating choices; they are not a certification of legal compliance. Provider-transfer assessment, routine retention reviews and off-host backup arrangements remain operating responsibilities. See the NDPC sources in the privacy operations document.
