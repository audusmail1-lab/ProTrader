# Academy Telegram operations

## Status — 18 September 2026

Preparation is in progress. Public launch has not been approved.

| Surface | State |
| --- | --- |
| Main account | Premium active. Existing account name/username unchanged. |
| Pro Trader Academy Updates | Private channel created; Academy logo, description and linked welcome post saved and pinned. |
| Pro Trader Academy Community | Private group created and linked to the channel; logo, description, posting permissions and linked community rules saved and pinned. |
| Pro Trader Academy Bot | Created as **@protrader_support_bot**. Name, description, short biography, logo and 10 commands saved through BotFather. Group invitations disabled. |
| Bot automation | Implemented and locally tested; not deployed or connected yet. |
| Academy entry points | Contact/footer links and Telegram privacy section implemented locally, hidden until explicit launch configuration. |
| Business automation | Copy ready. Hours, greeting, away message and quick replies are not configured: neither inspected Telegram Web client exposes these settings. |
| Secrets | BotFather generated a token. Render field prepared; awaiting owner entry and confirmation. No token is in these files or Git. |

The first username choice, `protraderacademy_bot`, was already taken. Do not direct users there.

## Map

- Website: https://protraderacademy.company
- App: https://app.protraderacademy.company
- Application: https://protraderacademy.company/#enroll
- Beginner route: https://protraderacademy.company/#start
- Support bot (created, awaiting activation): https://t.me/protrader_support_bot
- Operator support account: existing `@joels_t`, awaiting business profile rollout.
- Updates management: https://web.telegram.org/a/#-1003552340837
- Community management: https://web.telegram.org/a/#-1004349628698
- Support email: support@protraderacademy.company

Private invitations are kept in the ignored `links.local.json` and review document. Do not put them into a public source repository before launch approval.

Visitors → website Contact/footer → private bot, optional updates, optional community.
Bot → app / application / FAQs / private support request.
Support request → private database + operator's own Telegram inbox.
Operator `/reply ID message` → private answer in the visitor's bot chat.
Lesson questions → existing authenticated Academy classroom.

Telegram support does **not** automatically approve applications or appear in the teaching-dashboard question inbox. The two queues have different purposes.

## Bot operation

The existing Academy paid process polls Telegram using HTTPS. No extra hosting, no bot builder subscription and no public webhook are needed. Run exactly one process. The persistent file is `/var/data/academy/telegram.sqlite3`.

Configuration is private in Render → protrader-academy → Environment:

| Setting | Value |
| --- | --- |
| `ACADEMY_TELEGRAM_BOT_TOKEN` | Owner enters the BotFather token privately. Never commit or print it. |
| `ACADEMY_TELEGRAM_OWNER_ID` | Verified positive numeric ID of the operator's own private Telegram chat. Do not guess or use a group ID. |
| `ACADEMY_TELEGRAM_ENABLED` | `true` only after configuration is complete. |
| `ACADEMY_TELEGRAM_PUBLIC` | `false` for owner-only testing; `true` only after owner approves public launch and privacy wording. |
| `ACADEMY_TELEGRAM_COMMUNITY_URL` | Verified invitation from the private group. |
| `ACADEMY_TELEGRAM_UPDATES_URL` | Verified invitation from the private channel. |

The public session response contains only the three destination links when launch is enabled and all links validate. Secrets and the owner ID are never included. The bot ignores group messages and rejects non-owner administrative commands.

Owner tools, sent privately to the bot:

- `/tickets`: latest 20 open requests.
- `/reply 12 Please try opening the app in Chrome.`: queue an answer to request 12.
- `/close 12`: mark a resolved request closed.
- `/delivery`: counts of queued, sent and failed deliveries.

Check delivery failures before promising a response reached someone. Telegram can reject messages if the person blocks the bot. Queued deliveries retry temporary errors. A process crash just after a send can repeat an acknowledgment; request creation is deduplicated. Telegram holds undelivered updates for at most 24 hours, so extended hosting outages can lose incoming messages.

PROTrader app draft: `/private/tmp/protrader-paid-hosting/protrader_mobile.html` adds Help links to the private bot and Academy Contact page. Do not deploy it until public launch approval.

## Business profile and copy

`copy.json` is the canonical copy pack: profile biography, intro, greeting, away message, two pinned posts, all seven business quick replies, bot introduction and command descriptions. Resolve invitation placeholders from the approved links before use.

Proposed support hours: Monday–Friday, 09:00–17:00 WAT (Africa/Lagos); response target 1–2 business days. The bot's menu is available whenever hosting is online; these hours describe human support.

The main account's Business settings may require an official native Telegram client. Set greeting/away recipients to new support contacts, excluding existing personal chats and contacts. Do not connect the bot to all account conversations. Standalone bot support needs no access to the operator's unrelated chats.

Community permits text, photos, voice messages, link previews and reactions. Member file/video/music/sticker/GIF/poll posting is disabled. Member invitations, pinning and changing group information are disabled. No paid messaging was enabled. Owner moderation remains manual.

## Data and maintenance

Before launch, obtain approval for the drafted Telegram privacy section. Proposed retention: unfinished drafts up to 24 hours; closed support requests up to 12 months; monthly review of open requests and operator inbox copies. Screenshot files remain on Telegram; the server retains references. Automatic database cleanup does not delete Telegram inbox copies. Honor deletion requests in both locations.

Daily when launched: review support requests, failures and community activity. Monthly: review unresolved tickets, inbox retention, links, contact copy and permissions. Renew Premium if native Business features are required; account currently shows a September 2027 renewal date.

Back up the new database with `academy_backend/backup.py --source /var/data/academy/telegram.sqlite3 PRIVATE_DESTINATION`. Encrypt the export with the existing age public recipient before sending it off-site. Include the bot settings in the encrypted configuration archive. The September 17 off-site restore predates this Telegram database and does not cover it. Reapply deletions after restoring an older copy. Keep the bot disabled while checking restored data; inspect its outbox before reactivation.

## Validation

The full Academy suite passes 24 checks (one optional SMTP integration check skipped), including eleven bot checks covering launch gating, ticket persistence, owner-only replies, duplicate submission, delivery retry and a consistent database export/restore. The 390 px Contact layout fits without horizontal scrolling. This is local verification, not a live Telegram delivery test.

## Completion gates

1. Owner privately saves token in Render.
2. Owner identity verified from Saved Messages; private bot chat started. Apply the verified ID and owner-only configuration after token entry.
3. Deploy and test the real menu, ticket, optional screenshot, owner reply, duplicate-submit guard and restart persistence.
4. Private pinned posts and invitation links are prepared and verified; retain private access until launch approval.
5. Complete native Business settings where browser support is unavailable.
6. Owner approves public entry points, profile branding, hours and Telegram data notice; update the published policy date for that release.
7. Enable public mode; verify website/mobile flows and create an encrypted off-site snapshot of the new database/settings.

## Phase 2

Add a private teaching-dashboard view of Telegram tickets if needed; keep replies tied to the correct Telegram chat. Add a small FAQ editor, ticket tags and approved announcement scheduling only when usage justifies them. Set up daily encrypted backups after owner approves the recurring schedule and private cloud credentials. A reminder alone is not a backup job.

References: [Telegram Bot API](https://core.telegram.org/bots/api#getupdates), [Telegram Business](https://telegram.org/blog/telegram-business), [Telegram Privacy Policy](https://telegram.org/privacy).
