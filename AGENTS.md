# Project guidance

This is a static React/Vite frontend with a PHP JSON API and MySQL database for InfinityFree. Read README.md for development, import, monthly refresh, and deployment instructions.

## Data handling

- Keep the distinction between coordinate markers and official parcel boundaries explicit. The current coordinate workbook has points only.
- Preserve workbook names internally for import audit. Public plot provenance shows the official register name/URL, snapshot date when known, and exact-ID matching method, without Excel filenames (user preference).
- Do not join documents by address or geographic proximity.
- Cadastral area and basic attributes come from the 24 official Sofia land-parcel ZIP exports in KAIS Open Data and join only by exact ID. Preserve published AREA as geometry area in m²; never substitute a building area or claim certified sketch area. Do not import owner names. Preserve conflicting IDs with all safe variants and exclude them from area filters.
- Cadastral district, purpose, permanent use and property category are separate from document district and description keywords. Facet selections are OR within one field and AND across fields, area and document conditions. Preserve exact official labels/codes with stable keys; exclude unknown values only in an actively constrained field. Cadastral conditions remain usable with no linked construction record.
- Do not describe workbook snapshots as live or complete government data.
- Submitted search phrases must constrain every matching viewport point and cluster, independently of the forty-result preview. Match original scalar field values and identifiers case-insensitively, exclude workbook/source audit names from text search, and combine phrases at parcel level with all/any modes. Keep search values out of analytics. Preserve submitted phrases when opening results or selecting no-linked-records.
- Do not add credentials to frontend code, generated SQL, source control, or public files. Use public/private/config.php only on the host; it is excluded from git.

## Hosting

- Target InfinityFree's static-file, PHP, and MySQL environment. Do not add Base44 auth, entities, or deploy dependencies.
- The user authorized monthly GitHub Actions parsing and verified FTPS deployment of a prepared private register dataset. GitHub performs the parsing; hosted PHP reads the completed file. Do not simulate cron by calling public write URLs or expose a SQL importer.
- Keep the public PHP API read-only. MySQL retains coordinate data and the original imported observations. New register evidence lives in immutable private/registry-snapshots/ directories selected by private/registry-active.json; private/registry-data.json is the original fallback. Import coordinate changes through phpMyAdmin using the documented generated SQL flow.
- A refresh must match each register's stated row total and finish all three core sources before publication. Merge observations by source/document hash without deleting earlier evidence. Preserve legacy certificate evidence separately, with an unknown snapshot date where none is recorded.
- The monthly/manual workflow also captures and validates all 24 cadastral exports before publication. Cadastral files are immutable under private/cadastre-snapshots/, selected by private/cadastre-active.json. Register and cadastral activation are individually atomic; do not describe them as one transaction. Coordinates remain a separate MySQL import.
- FTPS must verify certificates and encrypt data transfers. Verify each uploaded immutable file's SHA-256, preserve the previous private pointer or fallback, and replace the active pointer by rename. Stop on failed verification, unexpected layout, an incomplete capture, or the documented manifest/index/shard/processing limits. Never delete or overwrite an existing immutable snapshot directory.
