# Academy Telegram operations

## Status — 18 September 2026

Preparation is in progress. Public launch has not been approved.

| Surface | State |
| --- | --- |
| Main account | Premium active. Existing account name/username unchanged. |
| Pro Trader Academy Updates | Private channel created; Academy logo, description and linked welcome post saved and pinned. |
| Pro Trader Academy Community | Private group created and linked to the channel; logo, description, posting permissions and linked community rules saved and pinned. |
| Pro Trader Academy Bot | Created as **@protrader_support_bot**. Name, description, short biography, logo and 10 commands saved through BotFather. Group invitations disabled. |
| Bot automation | Deployed on the Academy service in owner-only preview. Real support request, image, reply and duplicate-submit tests passed. |
| Academy entry points | Contact/footer links and Telegram privacy section deployed behind the public-launch switch; still hidden from visitors. |
| Business automation | All seven native Business quick replies saved and verified: app, join, support, faq, community, updates, start. Owner opens forms because automated mouse clicks fail; keyboard entry and saving work. Greeting text and settings saved successfully: enabled, Always Send, excluding Existing Chats and Contacts. Opening hours saved and verified: Monday–Friday 09:00–17:00, weekends closed, Africa/Lagos UTC+1. Away message saved and verified: enabled outside business hours, Only if Offline off, excluding Existing Chats and Contacts. Start page copy is entered and verified but not yet saved; main profile branding and public launch remain pending. |
| Secrets | Owner saved the token in Render Environment. The running bot successfully authenticated. No token is in these files, Git or local configuration. |

The first username choice, `protraderacademy_bot`, was already taken. Do not direct users there.

## Map

- Website: https://protraderacademy.company
- App: https://app.protraderacademy.company
- Application: https://protraderacademy.company/#enroll
- Beginner route: https://protraderacademy.company/#start
- Support bot (active for owner testing): https://t.me/protrader_support_bot
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

Saved support hours: Monday–Friday, 09:00–17:00 WAT (Africa/Lagos); response target 1–2 business days. The bot's menu is available whenever hosting is online; these hours describe human support.

The owner has opened Business settings on the phone. Four private Saved Messages contain the full copy pack and setup defaults. The official macOS client is installed and signed in, but its content controls cannot currently be operated through the available automation; keyboard navigation can open Settings. The owner can open each native form; keyboard entry and Return then work. All seven shortcuts have been created with the approved copy and verified in the native Quick Replies list: `/app`, `/join`, `/support`, `/faq`, `/community`, `/updates` and `/start`. The greeting switch is on and its Existing Chats / Contacts exclusions are saved and verified. After verifying the exclusions, the prepared greeting text was saved. The final settings submission showed “Your Telegram Business has been updated.” The initial automatic approval block was resolved by checking the recipient scope first. Set greeting/away recipients to new support contacts, excluding existing personal chats and contacts. Do not connect the bot to all account conversations. Standalone bot support needs no access to the operator's unrelated chats.

Community permits text, photos, voice messages, link previews and reactions. Member file/video/music/sticker/GIF/poll posting is disabled. Member invitations, pinning and changing group information are disabled. No paid messaging was enabled. Owner moderation remains manual.

## Data and maintenance

Before launch, obtain approval for the drafted Telegram privacy section. Proposed retention: unfinished drafts up to 24 hours; closed support requests up to 12 months; monthly review of open requests and operator inbox copies. Screenshot files remain on Telegram; the server retains references. Automatic database cleanup does not delete Telegram inbox copies. Honor deletion requests in both locations.

Daily when launched: review support requests, failures and community activity. Monthly: review unresolved tickets, inbox retention, links, contact copy and permissions. Renew Premium if native Business features are required; account currently shows a September 2027 renewal date.

Back up the new database with `academy_backend/backup.py --source /var/data/academy/telegram.sqlite3 PRIVATE_DESTINATION`. Encrypt the export with the existing age public recipient before sending it off-site. Include the bot settings in the encrypted configuration archive. The September 17 off-site restore predates this Telegram database and does not cover it. On September 18, a fresh encrypted snapshot of both databases and all Academy environment settings was created with the existing age recipient. Both database exports passed integrity checks; its encrypted transfer checksum matched. Drive upload is in progress. A decryption/restore of this new encrypted archive remains pending owner access to the recovery key. Reapply deletions after restoring an older copy. Keep the bot disabled while checking restored data; inspect its outbox before reactivation.

## Validation

Private release: commit `1c6be06117b70672d38943e871107c4a835875ec`, Render deploy `dep-dam7ektbedkc73abrtrg`, live 18 September 2026 at 00:27:52 WAT. `ACADEMY_TELEGRAM_ENABLED=true`; `ACADEMY_TELEGRAM_PUBLIC=false`.


The full Academy suite passes 24 checks (one optional SMTP integration check skipped), including eleven bot checks covering launch gating, ticket persistence, owner-only replies, duplicate submission, delivery retry and a consistent database export/restore. The 390 px Contact layout fits without horizontal scrolling. Live Telegram verification on 18 September 2026 also passed: welcome menu, privacy introduction, category/device/description collection, optional image forwarding, review/submit, owner notification, private reply and repeat-submit protection. Ticket #1 is a clearly labelled owner setup test and is now closed. A consistent copy of the production Telegram database restored with integrity_check=ok and one ticket; all 19 deliveries at that check were sent. This restore check ran in a temporary isolated file on Render and did not replace live data or create an off-site backup.

## Completion gates

1. DONE — Owner privately saved token in Render.
2. DONE — Owner identity verified from Saved Messages; private bot chat started; owner-only configuration applied.
3. Real menu, ticket, optional image, reply, duplicate-submit protection and live database restore passed. Service restart at 00:35 WAT also passed: the saved request accepted another reply at 00:37 WAT, then was marked closed.
4. Private pinned posts and invitation links are prepared and verified; retain private access until launch approval.
5. Complete native Business settings where browser support is unavailable.
6. Owner approves public entry points, profile branding, hours and Telegram data notice; update the published policy date for that release.
7. Enable public mode; verify website/mobile flows and create an encrypted off-site snapshot of the new database/settings.

## Phase 2

Add a private teaching-dashboard view of Telegram tickets if needed; keep replies tied to the correct Telegram chat. Add a small FAQ editor, ticket tags and approved announcement scheduling only when usage justifies them. Set up daily encrypted backups after owner approves the recurring schedule and private cloud credentials. A reminder alone is not a backup job.

References: [Telegram Bot API](https://core.telegram.org/bots/api#getupdates), [Telegram Business](https://telegram.org/blog/telegram-business), [Telegram Privacy Policy](https://telegram.org/privacy).
