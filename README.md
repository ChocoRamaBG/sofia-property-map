# Sofia Property Map

An InfinityFree-compatible React + PHP + MySQL website for looking up cadastral identifiers in Sofia and viewing register rows linked to each identifier. The private GitHub repository uses this directory as its root.

## What the current data means

- Map markers are WGS84 points from the translated coordinate workbook. They are not parcel boundary polygons. The coordinate workbook does not record its original source URL or capture date.
- Register records are snapshots from supplied workbooks or completed register captures. Each plot page shows the official register and capture date; workbook filenames are retained only in the private import audit.
- A register row is linked only when the extracted row text contains an exact cadastral identifier. The importer does not match addresses or nearby points.
- A missing linked record does not establish that a document is absent from the original register. Use the linked municipal register for verification.
- The initial core workbooks are from May 2025. The legacy certificate workbook has an unknown capture date and contributes only rows containing exact parcel IDs. Certificate issue dates are preserved separately from capture dates.
- A linked certificate for putting a building into use is evidence recorded for the parcel. A missing record does not prove that a building has no permission, and a parcel can contain multiple buildings. The UI uses this distinction for the Act 16 filter.

## Data storage

MySQL stores the coordinate points and original imported records. The API reads newer register observations from htdocs/private/registry-data.json when a valid, complete snapshot is present. The private directory's .htaccess prevents public downloads. GitHub publishes only this prepared dataset; it does not connect to InfinityFree MySQL or invoke a hosted import/cron URL.

The snapshot retains all 335 unique records from the three initial workbooks, plus 2,652 legacy certificate rows with exact parcel IDs. Legacy rows without exact identifiers remain in the supplied workbook. Bootstrap output is about 3 MB and stays below the host's 10 MiB file limit.

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
3. Runs the supplied Selenium parser approach for permits, certificates, and design visas in headless Chrome. It reads visible official headings and cells, checks the filter and pagination, and requires the captured count to equal each register's total.
4. Merges every completed capture with earlier observations. It retains legacy evidence and changed versions of a record.
5. Uploads a temporary private JSON file, reads it back, verifies SHA-256, saves the previous snapshot privately, and replaces the live file with an atomic rename.

Partial runs, unexpected headings, repeated pages, missing totals, failed date filters, changed hosted data during a run, or files over 10 MiB stop publication. The existing hosted snapshot continues to serve users. A successful capture is retained as a private Actions artifact for 31 days. Job logs and the published dataset's completion date establish whether a run succeeded.

To run it immediately, open GitHub Actions, select **Monthly Sofia register refresh**, and choose **Run workflow**. Leave start_date blank for the gap-aware window, or enter an earlier DD.MM.YYYY date. For the initial May 2025 snapshots, the automatic window extends back to April 2025.

For a local refresh, provide the three FTP environment variables in the current shell and run from the website directory:

    python scripts/deploy_registry_ftps.py fetch --output seed/monthly/previous.json
    python scripts/build_registry_snapshot.py --previous seed/monthly/previous.json --choose-start-date
    python scripts/scrape_registers.py --source all --start-date DD.MM.YYYY --output seed/monthly/capture
    python scripts/build_registry_snapshot.py --previous seed/monthly/previous.json --capture seed/monthly/capture --output seed/monthly/registry-data.json
    python scripts/deploy_registry_ftps.py publish --input seed/monthly/registry-data.json --previous seed/monthly/previous.json

Use the printed date in the capture command. Set NAG_HEADLESS=0 for a visible local Chrome window. The three original Python entry points in the sibling parser folders delegate to the shared parser and write completed JSON captures into their exports folders. The historical archive parser is not scheduled; its linked workbook observations are retained in every merge.

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
