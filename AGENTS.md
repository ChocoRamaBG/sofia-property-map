# Project guidance

This is a static React/Vite frontend with a PHP JSON API and MySQL database for InfinityFree. Read README.md for development, import, monthly refresh, and deployment instructions.

## Data handling

- Keep the distinction between coordinate markers and official parcel boundaries explicit. The current coordinate workbook has points only.
- Preserve workbook names internally for import audit. Public plot provenance shows the official register name/URL, snapshot date when known, and exact-ID matching method, without Excel filenames (user preference).
- Do not join documents by address or geographic proximity.
- Do not describe workbook snapshots as live or complete government data.
- Do not add credentials to frontend code, generated SQL, source control, or public files. Use public/private/config.php only on the host; it is excluded from git.

## Hosting

- Target InfinityFree's static-file, PHP, and MySQL environment. Do not add Base44 auth, entities, or deploy dependencies.
- The user authorized monthly GitHub Actions parsing and verified FTPS deployment of a prepared private register dataset. GitHub performs the parsing; hosted PHP reads the completed file. Do not simulate cron by calling public write URLs or expose a SQL importer.
- Keep the public PHP API read-only. MySQL retains coordinate data and the original imported observations; new register evidence lives in private/registry-data.json. Import coordinate changes through phpMyAdmin using the documented generated SQL flow.
- A refresh must match each register's stated row total and finish all three core sources before publication. Merge observations by source/document hash without deleting earlier evidence. Preserve legacy certificate evidence separately, with an unknown snapshot date where none is recorded.
- FTPS must verify certificates and encrypt data transfers. Upload a temporary file, verify its SHA-256, preserve the previous private snapshot, and replace the live file by rename. Stop on failed verification, unexpected layout, an incomplete capture, or a file exceeding 10 MiB.
