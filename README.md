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
- A separate exact-ID cadastral snapshot comes from the published land-parcel ZIP exports in [KAIS Open Data](https://kais.cadastre.bg/bg/OpenData), covering the 24 Sofia districts under EKATTE 68134. Its `AREA` field describes geometry in BGS2005 Lambert Conformal Conic with metre units, so the area is expressed in m². It is shown as geometry area rather than the legally certified area of a cadastral sketch. Stated address, district, territorial purpose, permanent use, property category and approval order are retained separately from construction-register evidence. No owner names are imported.

## Map and search filters

Submitting a search phrase adds a removable map condition. Up to eight phrases (120 Unicode characters each) can be combined with **All phrases** (the default) or **Any phrase**. Company names, addresses and other original scalar register-field values are searched case-insensitively, together with cadastral identifiers and available official cadastral district/purpose/use/property-category labels and codes. Phrases stay intact; spaces and commas do not split company names. Every matching mapped plot enters the viewport and normal cluster aggregation; the list is a forty-result preview, not the map's limit. Search totals distinguish matches with and without coordinates. Adding or removing phrases or changing their mode fits the map to all mapped matches. Draft typing does not replace submitted conditions, and opening a result retains them. Search phrases combine with the other selected filters and survive the no-linked-record choice; that choice cannot match construction-register text. Search values are kept in the shareable page URL and are never sent to analytics.

Opening a property while search is active keeps the submitted phrases, mode, filters and result list. **Back to search results** and closing the details restore the map centre/zoom from before opening the first property, along with the result-list scroll/focus. On mobile they reopen the search sheet; Escape and backdrop dismissal follow the same return path. Switching properties preserves the original search map view. Changing filters starts a new search context.

Document types are independent selections. The default mode matches at least one selected type; **All selected** requires each selected type. District, a stated address and construction-description keywords can be combined with those selections. These conditions must match one original observation; in All selected mode, each document type must have a qualifying observation. The no-linked-records choice is exclusive and clears conditions that require a document.

Each document type has its own issue-date period: `permits_date_from/to`, `visas_date_from/to`, and `certificates_date_from/to`. Every active period is a required condition, even in **Any selected type** mode. Its matching observation must also meet the shared district/address/description conditions. Unknown document dates cannot satisfy a period. Certificates include the retained legacy source. Metadata exposes the available dates of unique observations linked by exact cadastral IDs, rather than claiming dates for the full original register. Old shared `date_from/to` links remain supported and show a visibly removable common period; editing a new scoped period clears that old period.

Parcel-area filters use `area_min_m2` and `area_max_m2`, inclusive bounds on the published cadastral geometry area. They combine with all document conditions and can also be used with **No linked record**. Only exact-ID matches with a known, unambiguous area can satisfy an active area range; other map points remain visible when no area condition is set. Conflicting records for one identifier are retained as separate variants and excluded from area conditions; no version is selected and their areas are not summed. Construction footprint, gross floor area, sports surfaces, and regulated plot descriptions are never substituted for land-parcel area. The private immutable cadastral snapshot has its own validated manifest, streamable TSV index and bounded details shards, selected by `private/cadastre-active.json`.

The primary cadastral section filters official district, territorial purpose, permanent use and property type. Each dimension supports multiple selected values with OR matching; dimensions combine with AND, together with area and all active document conditions. `cadastre_districts`, `cadastre_purposes`, `cadastre_uses` and `cadastre_property_types` accept comma-separated stable keys. These conditions also work with **No linked record** and survive that selection. Missing exact cadastral matches, conflicting IDs and missing values in a selected dimension cannot satisfy the relevant condition. Unknown values in unselected dimensions do not exclude a parcel. Counts in cadastral option lists describe usable parcels in the full official snapshot; mapped results also require an existing coordinate point. Lists are searchable and retain the official labels and codes.

Districts and addresses in document filters come from explicit register fields. Housing, business, infrastructure, public facility and parking categories search literal words in the original construction/object description; they are not official cadastral land-use classifications. Counts beside document types describe the entire mapped dataset. Opening a property always returns all linked records, regardless of filters. Active filters are preserved in the page URL for sharing.

The map groups points into world-anchored Web Mercator cells of 128 screen pixels. Each additional zoom level divides a parent cell into four smaller cells. Bubble size reflects its full point count. Clicking a bubble fits its matching points' bounds with a maximum advance of two zoom levels. At zoom 17 or higher, views with up to 1,800 matching points show individual points; denser views retain complete aggregates. If an unusually large requested view exceeds 1,800 groups, the API uses a coarser level to keep every matching point in the response. Moving or zooming retains the previous groups while the new view loads; changing filters clears the previous results.

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

## Daily offers dashboard

The **Offers & prices** workspace reads a separate private imot.bg market snapshot through `market.php`. The original Master Summary supplies an explicitly dated September 2024 historical baseline; it never creates daily alerts. Daily collection covers public two-, three- and four-room apartment sale listings across the source's Sofia catalogue locations, including nearby settlements, without the old construction-year restriction. Other categories and rentals are outside this scope. An advert ID is not a unique property ID.

The consolidated collector replaces 73 desktop neighborhood scripts and 18 No Data scripts. It reads public list cards with a single worker paced at least two seconds apart, uses `lxml` to recover the source's malformed HTML, and divides capped searches using the source's native price bands. Exact stable totals must reconcile in every search leaf before publishing. Unknown prices remain visible but do not enter financial comparisons. Source challenges, a changed catalogue, incomplete counts or capacity limits stop publication and leave the active snapshot in place.

Price comparisons use **asking EUR/m²**. Method 2 groups by neighborhood, apartment type, VAT basis, advertised construction-age cohort (from 2021, before 2021, unknown), completion stage, area basis and floor band; peers have area within ±25%, and match condition when the candidate's condition is known. At least eight eligible peers on the same reference street take precedence over the neighborhood sample. The candidate is excluded. A potential bargain requires at least 20% below that median with at least eight other adverts. Differences >=60%, text-derived exceptional sale terms, and contradictory completion claims require review and cannot alert. Unknown VAT stays separate; default alerts require known VAT, with an explicit local opt-in for the unknown group. Area, price-basis or comparison-attribute edits suppress alerts. A new comparison method establishes a baseline while retaining prior first-seen dates and price history. Unknown currencies are never assumed. Neighborhood figures remain broad asking-price statistics, not transaction prices.

Individual **asking-price estimates** multiply peer median EUR/m² by advertised area. The displayed low/high range uses peer 25th/75th percentiles; it is not a confidence interval, sale-price prediction or professional market valuation. Sparse peer samples display an explicit unavailable state.

Area-basis claims require an explicitly labeled numeric m² value matching the card area within both 0.5 m² and 1%. Matching conflicting bases remain unknown. A description mentioning a different net area cannot relabel the card's gross area, and a terrace amenity cannot imply that terrace area is included. Analysis/cache versions distinguish this evidence rule from older captures; old unmatched claims are downgraded to unknown until reanalyzed.

The listings map uses `public/data/market-georeference.json`, an offline reference of grouped KAIS street/quarter points. `scripts/build_market_georeference.py` reads the verified 24 cadastral exports and existing coordinate workbook, associates exact official IDs internally, then discards IDs and house numbers from the generated output. Median centers are rounded; circles describe reference areas. Sparse, ambiguous and unsupported places remain unresolved. No advert is joined to an official parcel. Office addresses and nearby-road mentions cannot become property locations. The reference has its own capture date and remains unchanged until deliberately regenerated from updated verified source files; a daily ad capture does not refresh cadastral coordinates. The generated safe reference is committed in this same repository and published with the site.

The source card's professional profile supports the `agency` seller label. `private` requires an explicit ownership/seller claim, not merely an absent profile or commission-free wording; contradictory signals remain `unknown`. Cards derive minimal completion/condition/area-basis/risk claims. `imot_enrichment.py` optionally reads up to 400 full descriptions in a 15-minute budget, prioritizing new/changed/potential listings, then old evidence. Unchanged-card evidence can be reused for at most 30 days. The dashboard discloses partial coverage and per-ad dates. The full description, agency office, phones, contacts and photographs are never retained or published. No bulk geocoder or external language service is used.

The dashboard provides neighborhood mean/median and sample sizes, top comparisons, combined listing filters, a bounded market history and local alert preferences. Only factual fields and original advert links are public; no descriptions, photos or contacts are republished. Advertised Act 16 or construction status is an advertiser claim and is never joined to official records by address or proximity.

### Daily/manual GitHub update

All cloud code lives in the existing private `ChocoRamaBG/sofia-property-map` repository. `.github/workflows/daily-imot-refresh.yml` runs daily at **03:23 UTC** (06:23 Sofia in summer, 05:23 in winter). To run one complete refresh manually, open **Actions → Daily Sofia asking-price refresh → Run workflow** on `main`. The workflow fetches the verified previous state, captures every configured search, builds comparisons and changes, validates all hashes and counts, then uploads over verified FTPS using the existing `FTP_HOST`, `FTP_USER` and `FTP_PASSWORD` Actions secrets. A green completed publication automatically changes the website's dataset; no SQL import or second button is required. GitHub can delay scheduled jobs.

The first complete daily capture establishes an alert baseline. Later new adverts, reduced prices and newly eligible comparisons can generate website alerts. Users save their neighborhood/type/discount preferences inside the dashboard. Preferences and seen event keys remain in that browser. While the website's browser tab is visible, the summary refreshes every minute, including the map's alert badge. There are no emails or background browser push notifications. Historical captures and captures older than 48 hours cannot alert.

Advanced recovery: the optional **reuse_capture_run_id** field reprocesses a verified complete source capture from a finished daily workflow within the last six hours, preserving its original capture timestamps. Leave it blank for every ordinary fresh refresh. Recovery accepts only this private repository's daily workflow and exact allowlisted capture JSON from a bounded, verified artifact archive. Incomplete checkpoints remain private audit evidence and can be resumed by the local collector within six hours with matching configuration/catalogue/policy; they are never published as a completed market snapshot.

### Market storage and retention

`private/market-active.json` points to a verified immutable `private/market-snapshots/<uuid>/` tree, with a summary (<=2 MiB), manifest (<=256 KiB), <=256 public listing shards (<=250 rows and 256 KiB each) and a compressed private state (<=9 MiB uploaded, <=64 MiB expanded). Compression keeps each hosted file below InfinityFree's upload limit; both compressed and expanded sizes/hashes are verified. The original uncompressed historical state remains supported. The bound is 50,000 unique listings and a 96 MiB capture. Manifest completion counts and a hash are crosschecked with full search evidence in the private state. Public APIs never expose the state or private audit.

Activation uses verified upload/readback and atomic rename, retaining a verified previous pointer. After successful activation, market-only retention keeps the latest seven completed snapshots plus current/previous referenced snapshots. Only fully verified older unreferenced allowlisted market UUID trees can be removed; unexpected layouts stop cleanup and incomplete unverifiable directories remain. Registry and cadastral snapshots are preserved independently. Complete private captures/prepared snapshots are also retained as Actions artifacts for 31 days. Private price history is bounded to 90 days and 64 changes per listing; aggregate history keeps 180 completed captures. Missing adverts are not described as sold.

Install dependencies and run a local capture/prepare flow from this website directory:

    python -m pip install -r scripts/requirements-imot.txt
    python scripts/deploy_imot_ftps.py fetch --output seed/daily/previous-pointer.json --state-output seed/daily/previous-state.json
    python scripts/imot_scraper.py --output seed/daily/capture.json
    python scripts/imot_enrichment.py --input seed/daily/capture.json --previous-state seed/daily/previous-state.json --output seed/daily/capture-enriched.json --limit 400
    python scripts/imot_market.py --input seed/daily/capture-enriched.json --previous-state seed/daily/previous-state.json --output seed/daily/publish
    python scripts/deploy_imot_ftps.py publish --input seed/daily/publish --previous seed/daily/previous-pointer.json

The fetch/publish operations require FTPS credentials in the process environment. Never commit credentials or generated private output. Use fresh local fetch paths and do not publish concurrently with a cloud run.

## Street address navigation

The primary **Search** field recognizes street addresses and routes manual Enter/button submissions to map lookup. Cadastral IDs, document queries and company names keep their record-search behavior. Ambiguous names have an explicit **Search as a map address** action; recognized addresses also have a record-search override. Address queries are not added as parcel-filter phrases. Routing removes only an identical address phrase previously saved by the old record-only field. Address limits (3–160 characters) are independent of record-search limits. A single distinct location is centered automatically; multiple locations require selection. Queued requests are consumed once, including on mobile, and obsolete lookups cannot override a newer map navigation.

Manual address submission calls the same-origin `geocode.php` proxy, which uses OpenStreetMap Nominatim. No autocomplete or bulk parser geocoding is used. The proxy identifies the site, verifies TLS, restricts results to the Sofia area, globally paces requests to at least 1.1 seconds apart, applies conservative request limits, and keeps a private hashed-query response cache for at most seven days (150 entries/2 MiB). Trusted `private/geocode-config.php` can switch to an approved compatible HTTPS provider without a frontend release. The cache is incidental provider-policy state, not a dataset write endpoint.

Address selection moves the map and adds a distinct orange location marker above plot clusters. Results indicate address/street/area precision and attribution. Leading Bulgarian street-type prefixes are normalized for the provider. If a simple house number has no match, **Find street only** offers a separate manual lookup with the number removed; it never runs automatically. Address results never create parcel/document matches. Existing submitted property phrases, filters and search results remain available when switching search modes or visiting the offers dashboard. Active conditions stay visible in address mode with an explicit Show all properties choice. Address values and listing filters are never sent to analytics.

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

1. Fetches the previous private register snapshot and cadastral pointer over FTPS.
2. Selects a date window with at least 90 days of overlap, extending back to the oldest core-source capture minus 30 days when a run was missed or the initial workbooks are old.
3. Runs the supplied Selenium parser approach for permits, certificates, and design visas in headless Chrome. It reads visible official headings and cells, selects the largest existing numeric page-size option when available, checks the filter and pagination, and requires the captured count to equal a stable register total. Repeated individual rows stop the capture for inspection.
4. Merges every completed capture with earlier observations. It retains legacy evidence and changed versions of a record.
5. Downloads all 24 official land-parcel exports listed in `scripts/cadastre-sofia-sources.json`, checks their district, projected metre units, row totals and identifiers, and retains the published AREA field and basic cadastral attributes. Conflicting IDs are quarantined with all safe variants. A drop of more than 20% in overall or substantial district coverage stops publication for review.
6. Builds separate immutable register and cadastral snapshot directories with bounded index and detail files. Both captures must validate before either is published. Publishers verify every uploaded file's byte count and SHA-256 by downloading it again.
7. Checks that each hosted pointer still matches the one fetched at the beginning, backs up its previous pointer privately, and activates each manifest by atomic rename. Register and cadastral activation are separate operations: a later publication failure can leave one valid dataset updated while the other retains its previous version. During the first version-2 register publication, the original single-file snapshot stays in place as a fallback. Older immutable snapshot directories are retained for recovery; this workflow does not delete them.

Partial captures, unexpected headings, repeated rows or pages, changing or missing totals, failed date filters, changed hosted data during a run, invalid parcel references or files exceeding their format limits stop publication. Existing snapshots continue to serve until a complete candidate is activated. Each fully completed register capture is retained as a private Actions artifact for 31 days even if a later source or merge fails. Completed merged and cadastral snapshots are also retained privately for 31 days. Job logs and each published dataset's completion date establish whether a run succeeded.

To run it immediately, open GitHub Actions, select **Monthly Sofia register refresh**, and choose **Run workflow**. Leave start_date blank for the gap-aware window, or enter an earlier DD.MM.YYYY date. For the initial May 2025 snapshots, the automatic window extends back to April 2025.

For a local refresh, provide the three FTP environment variables in the current shell and run from the website directory:

    python scripts/deploy_registry_ftps.py fetch --output seed/monthly/previous.json
    python scripts/deploy_cadastre_ftps.py fetch --output seed/monthly/previous-cadastre.json
    python scripts/build_registry_snapshot.py --previous seed/monthly/previous.json --choose-start-date
    python scripts/scrape_registers.py --source all --start-date DD.MM.YYYY --output seed/monthly/capture
    python scripts/build_registry_snapshot.py --previous seed/monthly/previous.json --capture seed/monthly/capture --format sharded --output seed/monthly/publish
    python scripts/refresh_cadastre.py --archives seed/monthly/cadastre-archives --output seed/monthly/cadastre-publish
    python scripts/deploy_cadastre_ftps.py validate --input seed/monthly/cadastre-publish --previous seed/monthly/previous-cadastre.json
    python scripts/deploy_cadastre_ftps.py publish --input seed/monthly/cadastre-publish --previous seed/monthly/previous-cadastre.json
    python scripts/deploy_registry_ftps.py publish --input seed/monthly/publish --previous seed/monthly/previous.json

Use the printed date in the capture command. Set NAG_HEADLESS=0 for a visible local Chrome window. The three original Python entry points in the sibling parser folders delegate to the shared parser and write completed JSON captures into their exports folders. The historical archive parser is not scheduled; its linked workbook observations are retained in every merge.

The cadastral snapshot covers published Sofia district exports under EKATTE 68134. It is refreshed in full on each run; coordinate points in MySQL remain a separate imported dataset. Download timestamps are recorded from the actual capture. If the official server omits Last-Modified, current publication time stays unknown; the catalogue's initially observed publication time is retained separately. Archive hashes and byte counts are preserved as provenance. Use a fresh output directory for each capture. The private format contains `cadastre-active.json`, a TSV index, bounded JSON details shards and, when necessary, `conflicts.json` under `cadastre-snapshots/<snapshot_id>/`. Deploy the matching PHP reader before activating this dataset.

The fetch command automatically prefers the active version-2 manifest. It validates and reconstructs its observations as a local version-1 JSON file for the existing merge logic. It also writes previous.json.fetch-meta.json beside previous.json. This sidecar records the original hosted manifest or fallback file's path, byte count and SHA-256, plus the reconstructed local file's SHA-256. Keep both files together until publication; comparing the reconstructed JSON to a hosted manifest would otherwise give the wrong result. An existing malformed version-2 pointer fails the fetch rather than falling back.

The sharded output directory contains registry-active.json and registry-snapshots/<32-character lowercase hexadecimal snapshot_id>/. Use a fresh output directory for each build; the builder refuses to replace an existing local active manifest. The manifest names index.json and documents-000.jsonl, documents-001.jsonl, and subsequent shards. Each shard line is a complete observation. New indexes set reference_format to tuple-v2-facets and map exact parcel IDs to [source-list position, document hash, manifest-shard position, facet-dictionary position]. A deduplicated dictionary stores each observation's stated district, issue date, address flag and description keyword mask. This supports viewport filters without reading every document shard. The reader and publisher also accept earlier tuple-v1 and object references; advanced conditions require the facet format. Only validated relative names are accepted. Deploy the updated PHP reader before publishing a compact index. FTP writes are restricted to these immutable private files, the active pointer and its temporary/previous copies. The private .htaccess is checked before either fetching or publishing. A failed upload can leave an inactive snapshot directory; rebuild to get a fresh snapshot ID instead of overwriting its contents.

For compatibility before version 2 is active, --format v1 still writes the original JSON format and publish --input path/to/registry-data.json still accepts it when it is at most 10 MiB. Once an active version-2 snapshot exists, publication requires a sharded directory. To recover the immediately previous version-2 snapshot, restore the verified private registry-active.previous.json as registry-active.json through the hosting file manager or FTPS. During the first migration, removing the new active pointer reactivates the untouched original registry-data.json. Retain the protected immutable directory referenced by any pointer you may restore.

## Build and upload to InfinityFree

New cadastral captures use `area-source-shard-facets-tsv-v2`: the four original TSV cells (ID, area, source position, detail-shard position) followed by purpose, use and property-type dictionary positions. `-1` represents an unknown attribute. District matches the validated source position. The manifest's bounded `facets` lists retain exact official code/label pairs with deterministic keys and usable-parcel counts. The reader and publisher continue to accept v1 area-only snapshots; attribute conditions require v2. To upgrade a previously captured snapshot without changing its source download evidence, use `python scripts/refresh_cadastre.py --upgrade-existing seed/deploy/cadastre-open-data/publish --output seed/deploy/cadastre-facets/publish` with fresh output paths. Existing download timestamps, raw archive hashes and source counts are retained; preparation time describes the new format generation.

    npm install
    npm run build

Upload the contents of Website Template/dist/ to the domain's htdocs directory using FTP or the hosting file manager. Keep api.php, .htaccess, private/, and the built JavaScript/CSS files together at the web root. Keep the database config at htdocs/private/config.php; the included private/.htaccess denies direct web access to that directory. The schema.sql file is denied over HTTP after upload.

The Vite output is static HTML/JS/CSS; PHP runs separately on the host for the read-only JSON API. InfinityFree free MySQL is accessible from hosted PHP/phpMyAdmin, not directly from a desktop app. See [InfinityFree's MySQL connection guidance](https://forum.infinityfree.com/t/connecting-to-mysql-from-an-external-application/49339).

The root `public/.htaccess` sends `Cache-Control: no-cache, no-store, must-revalidate` for the homepage, about and privacy HTML so a cached entry does not keep using an earlier asset hash after publication. Hashed assets retain normal caching and are kept on the host. Apply this root configuration separately when it changes; the static publisher preserves existing hosting configuration. A visitor who already cached older HTML may need a one-time reload ignoring cache (`Ctrl+Shift+R` in Edge), or open a fresh version query URL such as `/?v=20261013`.

## API

- GET api.php?action=meta
- GET api.php?action=viewport&north=...&south=...&east=...&west=...&zoom=...
- GET api.php?action=search&q=...
- GET api.php?action=search&search_terms=["phrase one","phrase two"]&search_match=all
- GET api.php?action=plot&id=...

No write endpoint or public administrator screen is included.

`search_terms` is a URL-encoded JSON string array, accepted by both search and viewport actions; `search_match` is `all` or `any`. Legacy search `q` remains a single-phrase shorthand when `search_terms` is absent. The search response includes the forty-item preview, `total`, `mapped_total`, `unmapped_total`, `truncated` and the complete mapped-result `bounds`. Search and viewport apply the same phrase semantics; multiple phrases can match different observations of one parcel while document-specific conditions keep their existing same-observation requirements. Reading terms streams validated registry shards and uses the cadastral TSV/facet dictionaries without downloading all cadastral details. No new snapshot migration is required; monthly publication continues supplying the same complete evidence files.

## Search indexing and optional Analytics

The homepage, about.html and privacy.html have public canonical URLs and are listed in sitemap.xml. robots.txt allows the app assets and public pages while excluding the API, private data and schema. The homepage includes Bulgarian metadata, social metadata, WebSite/WebApplication structured data and a useful noscript fallback. Filter URL variants use the homepage canonical. Individual plot selections do not create separate indexable pages.

The google-site-verification meta tag in index.html belongs to the URL-prefix Search Console property https://sofiapermits.site.je/. Keep it in future builds so Google can maintain ownership verification. Submit sitemap.xml from the property. Verification and sitemap submission do not guarantee that Google will index a page or rank it for a query.

Analytics uses the public GA4 web-stream measurement ID G-ZY40ZKWMKC in src/lib/analyticsConfig.js, belonging to the SofiaPermits website stream in the authorized Google account. It can be overridden at build time with VITE_GA_MEASUREMENT_ID. Set that variable to an empty or invalid value to disable the integration and hide consent controls. Measurement IDs and Google verification tokens are public identifiers; account passwords and FTP credentials must stay out of the source and public output.

The Google tag loads only after the visitor allows analytics. Consent is kept in localStorage, and the Analytics control supports later refusal. Refusal blocks future measurement and clears the accessible _ga cookies. All custom events have allowlisted parameters: search_submit has no search text; property_open has only map/search entry point; filter_change has counts; cluster_open has a size bucket. Page location is the canonical homepage and referrer is empty. Do not add cadastral IDs, addresses, coordinates, query text, filter values or document fields to events.

In the GA4 stream, keep Enhanced Measurement disabled so automatic search, history and outbound-link events do not bypass these limits. Google Signals and advertising personalization remain disabled. See privacy.html for the current visitor-facing explanation. The monthly registry workflow updates register data and does not change analytics or indexing files.

For static publishing, build with the intended measurement ID, set the FTP_HOST, FTP_USER and FTP_PASSWORD process environment variables, then run:

    python scripts/deploy_site_ftps.py --input dist

The publisher allowlists compiled assets, index.html, about.html, privacy.html, robots.txt, sitemap.xml and matching Google verification files. It ignores the PHP API, private files, schema and environment files copied into dist. Every uploaded file is retrieved and checked by size and SHA-256; index.html is switched last. Existing assets are retained.
