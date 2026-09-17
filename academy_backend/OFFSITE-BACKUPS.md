# Off-site backup and paid hosting record

## Hosting — September 17, 2026

The owner approved the separate trading app's **$7/month Starter plan** (0.5 CPU, 512 MB, one instance). Render applied it successfully. The primary `main` branch now declares `plan: starter` in the root blueprint, so a future sync retains that choice. Render reports commit `8da0610` live. The Academy branch carries the matching configuration in `7cf8e40`.

The Academy remains on its previously approved $7 compute plan plus $0.25 persistent disk. Combined base hosting is **$14.25/month**, before taxes and usage extras. Both public sites and the trading app's health endpoint returned HTTP 200 after the change. The trading app's in-memory alerts were empty before its restart; paid hosting does not add a trading database or back up browser-local settings.

## Backup prepared

The September 17 snapshot was created at **21:02:42 UTC / 22:02:42 Nigeria time** directly from the live Academy service. It includes:

- The entire Academy branch source as `academy-source-latest.zip`, including this recovery record, plus `academy-source-7cf8e40.zip` for the exact source used during the restore test.
- The trading app's primary source as `trading-app-source-8da0610.zip`.
- A consistent SQLite snapshot made with the SQLite backup API, the previous launch snapshot and all 14 application environment settings, including the privately configured SMTP credential. These are inside `academy-data-settings-20260917.tar.gz.age`.
- Recovery instructions, SHA-256 checksums and a machine-readable restore report.

The data/settings archive was encrypted on Render with age v1.3.2 before transfer. Only the public encryption recipient was sent to Render; the recovery identity was generated privately on the owner's Mac. The official utility archives were checked against the SHA-256 digests published with the vendor release. The encrypted transfer's checksum matches the source.

The owner selected Google Drive. A folder named **Pro Trader Academy — Private Backups** was created in the owner's Drive, and its access dialog showed **Restricted**, with only the owner listed. Source/data archives, recovery instructions, checksums and the restore report were uploaded successfully after the owner enabled Chrome extension local-file access. Drive confirmed completed uploads.

Google Password Manager is the selected recovery-key store. The owner confirmed completing the private import of the recovery identity and existing SMTP credential. The temporary password-import file and decrypted test-data copies were removed after that confirmation. The private local recovery identity is retained temporarily while the optional cloud round-trip check is pending. Do not commit, upload to the backup folder, or print that import file or either secret. A Google passkey authenticates to Google; the separate age recovery identity decrypts the archive.

## Restore test completed

At **21:09:31 UTC on September 17**, a fresh isolated restore from the encrypted export passed:

- Archive checksum, decryption and restored database checksum.
- SQLite integrity, foreign-key checks and all 10 table counts.
- The saved instructor account and password record.
- Environment/SMTP configuration validation without contacting the mail provider.
- Restored service health, anonymous access restrictions and instructor access to the dashboard, lessons and question inbox.

The snapshot contains one instructor and two mail history rows; there were no student applications, learning-progress rows or questions at snapshot time. The live database was not replaced. Email and enrollment were disabled in the isolated restore; no email was sent. A download-and-restore check of the Google Drive copy remains pending: Drive reported “Can’t download file” and a Chrome-blocked frame during the automated download. The owner has been asked to download the encrypted file normally, without bypassing a security warning. The completed test used the exported encrypted archive before cloud upload.

## Retention and recurring backups

Recurring jobs are **not enabled**. Ask the owner to approve a schedule after the initial cloud copy and key storage are complete. A reasonable proposal is daily encrypted database/settings exports, a source snapshot after each release, and 30-day rolling retention, with periodic restore checks and failure alerts. Scheduling requires a reliable unattended transfer and private provider authentication; a calendar reminder alone is not a backup job.

Follow the approved privacy schedule in [PRIVACY-OPERATIONS.md](PRIVACY-OPERATIONS.md): remove every backup containing deleted personal data within 30 days of active-system deletion. Reapply deletions/revocations after restoring an older snapshot. Review queued mail before re-enabling delivery, and revoke restored session/reset tokens before reopening a production restore.

The recovery pack's `RESTORE-INSTRUCTIONS.txt` explains the isolated verification and production recovery sequence. Provider account logins, DNS-zone backups and users' browser-local trading settings are outside this Academy database snapshot.
