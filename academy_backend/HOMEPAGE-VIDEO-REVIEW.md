# Homepage and video release candidate — 23 September 2026

Status: owner review required before production deployment. Do not deploy automatically.
Preview: http://127.0.0.1:8794/#home (mail disabled).

Includes the pending Contact page / Open app navigation commit 967bf4d, plus the homepage PROTrader showcase, actual app capture, and two optional narrated guides. The Academy introduction remains first. No change to the trading app itself.

## Media
- Guide 8: How the Academy and app work together — 46 seconds.
  https://d2ol7oe51mr4n9.cloudfront.net/user_3JK9HzQtMubHcINDjvbZuTRS9eo/fa99f9e9-8383-4dcb-ac67-d6d4f20c35de.mp4
- Guide 9: How to join your scheduled class — 52 seconds.
  https://d2ol7oe51mr4n9.cloudfront.net/user_3JK9HzQtMubHcINDjvbZuTRS9eo/84cfcaf0-7d96-4283-9302-d3d68a735499.mp4
- Narrator: Callan, preset d8061b90-ff25-5882-8384-7a6a28806f30, same voice as introduction. Default speech rate; no speed change. Narration only; no music.
- Audio jobs: 65fcbf1f-90c9-41c3-bd7d-f6824fafd4a1 and e81bde6b-efdf-4d23-a971-c1092f0fb25b.
- Production review archive: https://d2ol7oe51mr4n9.cloudfront.net/user_3JK9HzQtMubHcINDjvbZuTRS9eo/b487d73f-ffac-42af-940f-fc38c29b1634.zip
- Local captions in academy/captions are the corrected release versions. The archive retains first-pass ASR punctuation.
- Real UI captures: public app with default paper balance; Academy localhost preview using fictional class details; empty support conversation; Sample student email with example.com link. No real student messages or account details used.

## Placement
Homepage: How it fits together, beside Open app in the new showcase.
Classes and signed-in classroom: Watch: how to join your class.
Public library retains seven tool guides; introductory/attendance films remain contextual. Total films across site after launch: 10.

## Checks
- 43 existing backend tests: 42 passed, 1 existing skip.
- New JS parsed and diff whitespace checks passed.
- All new public asset routes return 200 with expected MIME types.
- At 390px, document width equals viewport width; Open app appears in mobile navigation.
- Both players load and play in Chrome: 46.016 and 52.01 seconds, no media error.
- H.264 1920x1080, AAC audio; full decode passed.
- Integrated loudness: -16.40 / -16.11 LUFS; true peaks -1.86 / -1.61 dBTP.
- Selectable English captions, transcripts and poster images included. No autoplay.
