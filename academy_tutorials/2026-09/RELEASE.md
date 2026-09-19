# Phase 1 — Academy tutorial release

Prepared 19 September 2026. Status: release candidate complete; live deployment awaits the owner's maintenance-window approval required by the original brief.

## Delivered

| Tutorial | Duration | Narration |
|---|---:|---|
| Trade ticket | 1:06 | Arthur |
| Chart and one horizontal level | 1:00 | Arthur |
| Scanner and chart context | 1:00 | Arthur |
| Journal and saved Academy reflection | 1:00 | Arthur |
| Desktop shortcuts | 0:46 | Arthur |
| ARIA and its waiting verdict | 1:00 | Arthur |
| Oracle confluence percentage | 1:02 | Arthur |

All seven use 1080 × 1920, 24 fps H.264 video and 48 kHz AAC narration. Individual files are approximately 1.9–3.1 MB. Introductions last five seconds; subsequent steps hold for five seconds or longer. Trade ticket and Oracle receive additional time for their more involved explanations.

The homepage, video library and existing lesson associations use the new files. Accurate duration labels, readable poster images, optional English captions and complete timestamped transcripts are included. Closing a tutorial stops playback and restores keyboard focus. Opening a tutorial preserves unsaved lesson notes. Unavailable media displays a written fallback and opens the transcript.

Phone lessons contain wide practice tables inside horizontally scrollable, keyboard-focusable regions. The video retains a readable width on phones. Desktop media and controls fit the available dialog height, with a persistent close control. Editing saved practice notes clears the old success message until the next save.

## Capture transfer resolution

The hosted editor now retrieves a versioned, sanitized source ZIP from the existing public GitHub repository over HTTPS and verifies its SHA-256 hash. It contains only cropped tutorial images, narration references and edit metadata. No credentials, databases, environment settings or real student records are included. This replaces the blocked local-byte transfer route.

The Journal navigation crop was corrected to show Journal, and Oracle's empty final visual was replaced by a review checklist. Oracle uses the verified eight-of-nine/89% example; six-of-nine is explicitly a different setup. ARIA and Oracle share checks, and neither score is described as a probability of profit. No unbuilt Deriv linking is shown.

## Verification completed

- All seven files fully decoded with no errors; dimensions, frame rate, audio streams and duration checked. All-frame black-screen detection found zero black intervals.
- Every scene's keyframe reviewed, with additional before/after transition frames for chart placement, Patterns, ticket size, notes and navigation. Phone-size teaching captions and relevant UI crops checked.
- Narration transcribed for all seven and compared with the approved scripts. Apparent repetition at long pauses in the whole-file transcription was checked against individual speech segments; those segments contain the correct complete sentences.
- Integrated loudness ranges from −16.18 to −15.77 LUFS. All speech splits fall in detected silence; no quiet-window fallback was needed.
- All seven integrated entries loaded with the expected media duration. Oracle played to completion with English captions enabled. Journal transcript seeking reached 0:41.
- Browser checks at 360, 390, 768 and 1280 pixels found no page-wide horizontal overflow on the tested beginner, chart, ticket, journal, library and homepage routes. The 360-pixel journal table scrolls inside its 276-pixel region.
- Keyboard Escape closes the player, removes its video and returns focus to the opening button. Unsaved notes survive opening/closing; saved notes persist on refresh. A lesson question retained its session association and was saved in the disposable local account.
- Missing-video failure simulated in a disposable fixture; readable fallback and expanded transcript confirmed.
- 27 backend tests passed, including production HTTP serving, acceptance-email routing, private-content access, saved progress/questions, account isolation, and the exact public caption/poster allowlist. JavaScript syntax and diff whitespace checks passed.

Testing used a disposable local learner with outbound mail disabled. No live student records were edited for QA. Responsive testing used Chrome viewport sizes, not physical-device Safari testing.

## Release and rollback

Target only the existing Academy service `srv-dam1oklbedkc73abn56g`, using `academy_backend/requirements.txt` and `academy_backend/production.py`. The Academy deployment branch is `codex/academy-launch`, with automatic deployment disabled. Confirm the approved release commit in Render, deploy, then verify `/healthz`, public captions/posters, library playback and existing access gates.

The currently live Academy baseline is `b55eb4c3f5cd06ec1d8855486644614fd7e9be31`. Roll back to that commit if a post-deployment check fails. `previous-videos.json` also retains the original media URLs. This release contains no database migration or account, email, Telegram, broker or trading-engine changes.

The owner's app remains on main commit `678bf5c4aa0b2032801f585de9b17b87607962a9`; it is outside this deployment.

## Next work, outside this release

Confirm class dates and run one coached lesson with the first learners. Structured exercise submission, instructor review and retries remain a separate product decision. Student practice-account isolation, misleading funding controls and any Deriv integration require the separate architecture review before implementation. Keep backups manual unless the owner changes that preference.
