# Academy review and connection backlog

Recorded September 16, 2026, while the owner reviews the first prototype.

The owner agreed to include enrollment approval, a saved question inbox, larger app demonstrations, an instructor introduction and a schedule-aware next-class card in a future update. Record these now; implementation timing and remaining details will follow the owner's site review. Persistent practice notes and touch/readability improvements remain additional recommendations.

## Confirmed needs from the owner

### Enrollment review and approval

- Save real applications securely, including contact details, experience, main difficulty and learning goal.
- Provide a private instructor application list and individual application detail.
- Support pending, accepted and needs-more-information states; define any other outcomes before implementation.
- Allow the instructor to verify and accept a sign-up.
- Deliver the appropriate status message, classroom access and joining details after approval.
- Notification channel and destination remain undecided. No live collection is enabled yet.

### Student questions and instructor replies

- Save questions beyond refresh and across devices.
- Associate each question with its student and lesson.
- Show questions in a private instructor inbox, with unanswered/answered status.
- Let the instructor reply and the student read the response in their classroom.
- Decide whether notifications should supplement the inbox. Questions are not public class discussions by default.

## Supporting work before live use

- Secure student and instructor accounts with server-side access checks.
- Persistent lesson progress and practice notes; distinguish a learner marking practice done from an instructor assessing understanding.
- Confirm cohort start date, session dates/times and time zone, joining links, capacity, fees/payment model and enrollment terms.
- Decide privacy/consent wording, data retention, contact destination and who administers the academy.

## Review findings and recommendations (not implemented)

The dark surfaces, lime accents, two starting paths and consistent lesson structure form a coherent first version. Live classes are clearly central, and video guides provide useful support without implying the self-paced course is finished.

1. **Make app demonstrations easier to read.** The current vertical video sits inside a wide homepage frame, so interface text is small on desktop. Give it a taller portrait presentation or a prominent full-size viewing action; verify readability with the final media. Existing library cards are editorial title cards, not actual footage thumbnails.
2. **Introduce the instructor.** Add an owner-approved name, photo and short teaching introduction. People enrolling in live classes should know who teaches them. Do not invent credentials, results or testimonials.
3. **Connect the next-class and current-lesson cards to real state.** The next-class card currently always says “Get oriented,” and current lesson means the last opened lesson. Use the approved cohort schedule and saved progress in the live version.
4. **Make practice notes durable.** Notes currently disappear when navigating away; progress and questions disappear on refresh. Once accounts are connected, show clear save status and retain drafts.
5. **Improve small-screen reading and touch targets.** Several secondary labels are 10–13px; circular play/close controls are around 29–32px. Increase essential labels and use roughly 44px touch areas. This is a targeted review, not a completed accessibility audit.

## Scope boundary

These are recorded requirements and suggestions. No backend, public deployment, payment collection, real registrations or student messaging has been activated. Continue collecting the owner's review before choosing the next implementation scope.

## Implemented beginner sample update

Added the Start here introduction and workspace diagram, glossary, a supplied fictional candle chart with level reveal and 15-minute comparison, an adjustable educational ticket, sample analysis and Journal rows, worked answers in all seven lessons, and beginner-first video ordering. Foundation links now open the introduction. Registration includes a completely-new/not-sure option. Live account/enrollment/question infrastructure remains pending.

## Second walkthrough after the beginner update

Verified home → Start here → chart practice → next ticket lesson → question route. The question form correctly selected the ticket lesson. Verified the seven-video order and the completely-new/not-sure enrollment option. The introduction fitted a 390px phone viewport without horizontal overflow.

Remaining recommendations (review only; not implemented):

1. **Bring the first activity closer on mobile.** The header and large introductory text occupy most of the first phone screen. Reduce vertical space on learning pages or add a direct “Try the workspace map” jump. Keep the marketing homepage's visual style.
2. **Unify introduction and lesson progress.** The introduction leads straight into session 2; it does not mark session 1 practiced, and the classroom's current lesson is merely the last opened page. Add an explicit introduction-complete action and sensible resume behavior. Do not infer understanding just from page visits.
3. **Improve the handoff from sample to real app.** The new diagram works well as a safe concept map, but it is deliberately not the real Pro Trader interface. Before live classes, add approved app access/setup instructions, a real annotated screen and the exact method for confirming paper mode.
4. **Keep class information easy to find.** Add the previously agreed instructor introduction plus a concise “How classes work / What you need” section when details are approved. Dates, fees and access steps remain unconfirmed.
5. **Keep exported materials in sync.** The current teaching-notes download still uses original lesson summaries/exercises, while new examples and answers live in the practice module. Update the export before instructors rely on it as the full lesson packet.

Previously recorded needs remain: secure accounts, application approval, saved questions/replies and notes, schedule-aware next class, and clearer full-size app video viewing. The close control has been enlarged; other small metadata/touch areas still merit a dedicated accessibility pass. A real beginner test is still needed to validate comprehension. No new feature changes were made in this second review.

## September 17 completed follow-up

Implemented the compact mobile introduction and direct activity jump, explicit introduction completion linked to session-one practice, classroom resume that skips completed lessons, and the finished-week review state. Replaced the stale Markdown teaching export with printable HTML generated from the same current examples and answers. Verified in the browser and checked the downloaded file. These resolve second-walkthrough recommendations 1, 2 and 5 within prototype scope. Production accounts, persistence, instructor details, real app setup and schedule remain pending.
