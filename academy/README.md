# Academy: current working version

The connected local application now runs with `python3 academy_backend/server.py` at http://127.0.0.1:8743. It includes accounts, reviewed applications, saved learning progress, private questions/replies and an email queue. See [backend setup and launch requirements](../academy_backend/README.md). Instructor setup and external email/hosting configuration remain required.

The remainder of this document describes the earlier static prototype on port 8742; its limitations do not describe the connected version.

# Pro Trader Academy prototype

An independent, dependency-free static website. No existing trading app files are changed. Serve only this folder for the preview:

```sh
python3 -m http.server 8742 --bind 127.0.0.1 --directory academy
```

Open http://127.0.0.1:8742. Navigation uses hash routes, so any static server works without rewrite rules.

## Content and maintenance

- `content.js`: all seven video URLs, written guides and seven proposed week-one lessons.
- `app.js`: page templates and prototype interactions.
- `practice.js`: beginner introduction, glossary, fictional chart/ticket/journal examples, answer reveals and practice interactions.
- The Start here route is public within the prototype and requires no enrollment or trading account. All example prices, units and credits are fictional; they do not reproduce live instrument specifications.
- `styles.css`: responsive theme and components.
- Teaching preview includes a printable HTML export generated from the current week-one examples, glossary and worked answers.

Videos are the seven completed Higgsfield exports from “Create Pro Trader Feature Storyboard”, dated September 15, 2026. Originals remain unchanged on their existing CDN. Each is 30 seconds. Six have narration and burned-in captions; Oracle is caption-only. Cards use editorial title treatments, not fabricated video stills. The home page embeds the actual trade-ticket walkthrough. Guides were checked against the repository's Pro Trader controls and Oracle's `gates.score / 9` calculation.

## Prototype boundaries

- Enrollment uses browser validation plus custom messages, then shows a truthful confirmation. It sends no request and stores no contact details.
- Practice progress and sample questions live in memory only and disappear on refresh.
- Student and teacher pages are **not authenticated or private**. Do not put real learner data or restricted material here.
- No payments, notifications, real enrollment, live class links or trading execution.
- Video playback and web fonts require internet access. System font fallbacks and written guides remain available.

## Before public launch

1. Confirm dates, time zone, session times, class capacity, fees/payment model and admissions process.
2. Choose an enrollment destination, consent/privacy wording, retention policy and notifications; implement server-side validation and storage.
3. Implement production authentication and server-side authorization for students and teachers before adding private content.
4. Configure class joining links and access delivery. Review the proposed teaching content and establish ongoing ownership.
5. Move video references to approved durable media hosting if needed; keep original exports and source materials. Confirm accessibility and caption accuracy against final videos.

## Verification

JavaScript syntax checks; browser tests of invalid and valid demo enrollment, lesson progress, sample question display in teaching preview, topic filtering, guide dialog open/close; responsive visual inspection and overflow checks at phone and desktop widths. All video URLs checked for HTTP availability. No existing trading app code changed.

## Beginner update verification

Checked the workspace explanations, corrective quiz feedback, chart level reveal, example-answer expansion, one/two-unit ticket calculation, and all seven lesson routes. Checked phone overflow at 390px. Original clips remain supporting recaps, ordered from chart basics through analysis, with shortcuts labeled optional desktop material. The teaching-packet export uses the same supplied examples and answers in `practice.js`, with controls converted to printable explanations.

## September 17 usability update

The mobile introduction is compact and has a focus-aware jump to the workspace map. An explicit Complete introduction button marks orientation practiced in the current page session. Classroom resume skips completed lessons, with a final review state when all seven are practiced. Visiting a page alone never marks it complete.

Verified completion-to-classroom flow, progression from chart to ticket, all-seven completion, and downloaded packet contents (seven sessions and seven worked answers). At 390 × 844, the activity jump appears within the first screen with no horizontal overflow. Progress still resets on refresh; production persistence remains pending.
