# Sofia Property Map

An InfinityFree-compatible React + PHP + MySQL website for looking up cadastral identifiers in Sofia and viewing register rows linked to each identifier. The private GitHub repository uses this directory as its root.

## What the current data means

- Map markers are WGS84 points from the translated coordinate workbook. They are not parcel boundary polygons. The coordinate workbook does not record its original source URL or capture date.
- Register records are snapshots from supplied workbooks or completed register captures. Each plot page shows the official register and capture date; workbook filenames are retained only in the private import audit.
- A register row is linked only when the extracted row text contains an exact cadastral identifier. The importer does not match addresses or nearby points.
- A missing linked record does not establish that a document is absent from the original register. Use the linked municipal register for verification.
- The initial core workbooks are from May 2025. The legacy certificate workbook has an unknown capture date and contributes only rows containing exact parcel IDs. Certificate issue dates are preserved separately from capture dates.
- A linked certificate for putting a building into use is evidence recorded for the parcel. A missing record does not prove that a building has no permission, and a parcel can contain multiple buildings. The UI uses this distinction for the Act 16 filter.
- Clicking a plot shows the stated addresses, districts, construction descriptions and scopes from all linked sources, followed by every original field and retained observation. Register navigation includes permits, design visas, certificates and archived certificates. Act 16 is a supplemental summary. The coordinate source contains no cadastral area, ownership or land-use attributes.

## Data storage

MySQL stores the coordinate points and original imported records. The API prefers htdocs/private/registry-active.json, a small manifest pointing to a complete immutable snapshot under htdocs/private/registry-snapshots/<snapshot_id>/. If the active manifest is absent, the API continues to support the original htdocs/private/registry-data.json format. An invalid active manifest stops the request; it is not silently replaced with older evidence. The private directory's .htaccess prevents public downloads. GitHub publishes prepared files; it does not connect to InfinityFree MySQL or invoke a hosted import/cron URL.

The snapshot retains all 335 unique records from the three initial workbooks, plus 2,652 legacy certificate rows with exact parcel IDs. Legacy rows without exact identifiers remain in the supplied workbook. Bootstrap output is about 3 MB and remains supported as a single file. Monthly publication uses version 2 so accumulated observations do not need to fit in one hosted file.

Version-2 snapshots have a manifest of at most 256 KiB, a parcel lookup index of at most 8 MiB, and JSONL document shards of at most 1 MiB each. Their maximum document count is 100,000. Local reconstruction and total published files have a 128 MiB limit; the larger reconstructed local file is never uploaded to the host. Reaching any index, shard, manifest, document-count or processing limit stops publication and preserves the currently hosted snapshot. Capacity depends on record size and the number of exact parcel links, as well as document count. The PHP reader releases decoded index entries as it builds compact internal lookups to reduce memory use.

To add supplied historical workbooks to an existing hosted snapshot, fetch it first and keep the fetch metadata sidecar. Run the local archive importer from the website directory:

    python scripts/bootstrap_registry_sources.py --previous seed/deploy/previous.json --output seed/deploy/archive-merged.json --audit seed/deploy/archive-audit.json

The importer recognizes the historical column layouts, skips exact duplicate workbook copies and spreadsheet QA counters, adds only records with exact parcel identifiers, and preserves all existing observations. Changed record values remain separate observations. Archive capture dates remain unknown when the filename does not record a full year. Build the merged result as a fresh sharded snapshot and publish using the original fetched previous.json and its sidecar:

    python scripts/build_registry_snapshot.py --reshard --previous seed/deploy/archive-merged.json --format sharded --output seed/deploy/archive-publish
    python scripts/deploy_registry_ftps.py publish --input seed/deploy/archive-publish --previous seed/deploy/previous.json

Subsequent monthly merges retain these archive observations.

## Local development

Requirements: Node.js, Python 3.12, Chrome, PHP, and MySQL. Install the parser dependencies from the website directory:

    python -m pip install -r scripts/requirements-monthly.txt

    npm install

Start the local PHP API in one terminal:

    php -S 127.0.0.1:8000 -t public

Start Vite in a second terminal:

    npm run dev

Vite proxies API requests to PHP. Configure public/private/config.php from public/private/config.example.php and use a local MySQL database.

## Initial database import

1. Create a MySQL database and user in the hosting control panel. Copy public/private/config.example.php to public/private/config.php and fill it on the server. Never commit the real config file.
2. In phpMyAdmin, select the database and import public/schema.sql once.
3. From the project root, build the compressed seed files:

       python "Website Template/scripts/build_seed.py"

   The script reads the translated coordinate workbook and the three current source workbooks. It excludes coordinates outside the broad Sofia area (and invalid 1,1 sentinel rows), preserves source workbook names, and creates 5,000-row gzip SQL chunks under Website Template/seed/generated/.
4. Import the generated .sql.gz files in filename order: 00_sources..., every 01_parcels... chunk, then 02_documents.... If phpMyAdmin rejects a chunk because of its upload or execution limit, the script's FILE_ROWS setting can be lowered and the seed rebuilt.
5. Build and deploy the static app plus PHP API described below.

For later exports, pass the new workbook paths to the same builder:

    python "Website Template/scripts/build_seed.py" --coordinates "Coordinates/Translated_Coordinates/Translated_Sofia_Coords_Excel.xlsx" --permits "Razresheniya za Stroezh/exports/Building_Permits_ListAllDataFinalDD.MM.YYYY.xlsx" --certificates "Udostoverenie za Vuvezhdane v Eksploataciya/exports/Exploatation_ApprovalsAllDataFinalDD.MM.YYYY.xlsx" --visas "Vizi za Proektirane/exports/Projecting_Visas_DD.MM.YYYY.xlsx"

For a manual MySQL import from later Excel snapshots, use the documents-only option so you do not reimport the 155,000 coordinate rows. Use --permits, --certificates, or --visas to select the new workbook files:

    python "Website Template/scripts/build_seed.py" --documents-only --output "Website Template/seed/monthly"

Import the monthly files in filename order. The SQL uses upserts and does not delete older register observations; inspect source changes and database counts before each import.

## Monthly refresh through GitHub

InfinityFree permits [GitHub Actions FTP deployments](https://forum.infinityfree.com/t/using-github-actions-for-automatic-upload-to-infinityfree/111008). The workflow .github/workflows/monthly-registry-refresh.yml performs the work on GitHub's runner and uploads a completed dataset over verified FTPS. It runs on the first day of each month at 04:17 UTC (06:17 in Sofia in winter, 07:17 in summer). GitHub schedules can be delayed; dates shown on the website describe the actual completed capture, not the planned run.

Configure these repository Actions secrets:

| Secret | Value |
| --- | --- |
| FTP_HOST | ftpupload.net |
| FTP_USER | Hosting account FTP username |
| FTP_PASSWORD | Hosting account FTP password |

Seed htdocs/private/registry-data.json once before enabling the workflow. From the local workspace's website directory, the bootstrap builder reads the original sibling workbooks:

    python scripts/build_registry_snapshot.py --bootstrap --output seed/deploy/registry-data.json

Upload that file into the protected private directory. The monthly workflow then:

1. Fetches the previous private snapshot over FTPS.
2. Selects a date window with at least 90 days of overlap, extending back to the oldest core-source capture minus 30 days when a run was missed or the initial workbooks are old.
3. Runs the supplied Selenium parser approach for permits, certificates, and design visas in headless Chrome. It reads visible official headings and cells, selects the largest existing numeric page-size option when available, checks the filter and pagination, and requires the captured count to equal a stable register total. Repeated individual rows stop the capture for inspection.
4. Merges every completed capture with earlier observations. It retains legacy evidence and changed versions of a record.
5. Builds a new immutable snapshot directory with bounded index and document files. The publisher validates every parcel reference against the corresponding document and verifies every uploaded file's byte count and SHA-256 by downloading it again.
6. Checks that the hosted pointer still matches the one fetched at the beginning, backs up the previous pointer privately, and replaces the active manifest by atomic rename. During the first version-2 publication, the original single-file snapshot stays in place as a fallback. Older immutable snapshot directories are retained for recovery; this workflow does not delete them.

Partial runs, unexpected headings, repeated rows or pages, changing or missing totals, failed date filters, changed hosted data during a run, invalid parcel references or files exceeding their format limits stop publication. The existing hosted snapshot continues to serve users. Each fully completed source capture is retained as a private Actions artifact for 31 days even if a later source or merge fails. Job logs and the published dataset's completion date establish whether a run succeeded.

To run it immediately, open GitHub Actions, select **Monthly Sofia register refresh**, and choose **Run workflow**. Leave start_date blank for the gap-aware window, or enter an earlier DD.MM.YYYY date. For the initial May 2025 snapshots, the automatic window extends back to April 2025.

For a local refresh, provide the three FTP environment variables in the current shell and run from the website directory:

    python scripts/deploy_registry_ftps.py fetch --output seed/monthly/previous.json
    python scripts/build_registry_snapshot.py --previous seed/monthly/previous.json --choose-start-date
    python scripts/scrape_registers.py --source all --start-date DD.MM.YYYY --output seed/monthly/capture
    python scripts/build_registry_snapshot.py --previous seed/monthly/previous.json --capture seed/monthly/capture --format sharded --output seed/monthly/publish
    python scripts/deploy_registry_ftps.py publish --input seed/monthly/publish --previous seed/monthly/previous.json

Use the printed date in the capture command. Set NAG_HEADLESS=0 for a visible local Chrome window. The three original Python entry points in the sibling parser folders delegate to the shared parser and write completed JSON captures into their exports folders. The historical archive parser is not scheduled; its linked workbook observations are retained in every merge.

The fetch command automatically prefers the active version-2 manifest. It validates and reconstructs its observations as a local version-1 JSON file for the existing merge logic. It also writes previous.json.fetch-meta.json beside previous.json. This sidecar records the original hosted manifest or fallback file's path, byte count and SHA-256, plus the reconstructed local file's SHA-256. Keep both files together until publication; comparing the reconstructed JSON to a hosted manifest would otherwise give the wrong result. An existing malformed version-2 pointer fails the fetch rather than falling back.

The sharded output directory contains registry-active.json and registry-snapshots/<32-character lowercase hexadecimal snapshot_id>/. Use a fresh output directory for each build; the builder refuses to replace an existing local active manifest. The manifest names index.json and documents-000.jsonl, documents-001.jsonl, and subsequent shards. Each shard line is a complete observation. New indexes set reference_format to tuple-v1 and map exact parcel IDs to [source-list position, document hash, manifest-shard position]; the reader and publisher also accept earlier object references. Only validated relative names are accepted. Deploy the updated PHP reader before publishing a compact index. FTP writes are restricted to these immutable private files, the active pointer and its temporary/previous copies. The private .htaccess is checked before either fetching or publishing. A failed upload can leave an inactive snapshot directory; rebuild to get a fresh snapshot ID instead of overwriting its contents.

For compatibility before version 2 is active, --format v1 still writes the original JSON format and publish --input path/to/registry-data.json still accepts it when it is at most 10 MiB. Once an active version-2 snapshot exists, publication requires a sharded directory. To recover the immediately previous version-2 snapshot, restore the verified private registry-active.previous.json as registry-active.json through the hosting file manager or FTPS. During the first migration, removing the new active pointer reactivates the untouched original registry-data.json. Retain the protected immutable directory referenced by any pointer you may restore.

## Build and upload to InfinityFree

    npm install
    npm run build

Upload the contents of Website Template/dist/ to the domain's htdocs directory using FTP or the hosting file manager. Keep api.php, .htaccess, private/, and the built JavaScript/CSS files together at the web root. Keep the database config at htdocs/private/config.php; the included private/.htaccess denies direct web access to that directory. The schema.sql file is denied over HTTP after upload.

The Vite output is static HTML/JS/CSS; PHP runs separately on the host for the read-only JSON API. InfinityFree free MySQL is accessible from hosted PHP/phpMyAdmin, not directly from a desktop app. See [InfinityFree's MySQL connection guidance](https://forum.infinityfree.com/t/connecting-to-mysql-from-an-external-application/49339).

## API

- GET api.php?action=meta
- GET api.php?action=viewport&north=...&south=...&east=...&west=...&zoom=...
- GET api.php?action=search&q=...
- GET api.php?action=plot&id=...

No write endpoint or public administrator screen is included.
