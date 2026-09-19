# Academy tutorial source — September 2026

Approved scope: seven calm, narrated mini-tutorials using the existing interface. Fictional paper examples only. No broker linking, real orders or student records.

`source.zip` contains 66 cropped interface images plus the visual manifest, seven Arthur narration references and speech-alignment data. These captures were produced in disposable local copies with fictional accounts and illustrative market candles. No account database, authentication token, environment settings or other private records are included.

SHA-256: `4a57ec69c0e7e38c344caca043a2e85f35626d34ddf7038aacad638f33a84e8b`

The public, versioned source archive lets the hosted editor fetch the approved assets over HTTPS without relaying file bytes through commands or sharing repository credentials. Rendered videos are served by the already permitted media CDN, not the Academy request server.

`render.jsx` is the editable native Higgsedit composition. `prepare.py` aligns speech at detected pauses. `finish.py` assembles 48 kHz narration, captions and final H.264/AAC files. `timed-manifest.json` and `quality-report.json` record the finished release. `previous-videos.json` retains the prior URLs for rollback.

Release requirements: complete all seven exports, verify speech and visual transitions, check phone/tablet/desktop layouts and video failures, preserve originals for rollback, and use the Academy deployment configuration only.
