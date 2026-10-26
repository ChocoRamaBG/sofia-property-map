#!/usr/bin/env python3
"""Capture official quarterly registered sales for Registry Office Sofia.

Counts cover all types of real estate in the office's jurisdiction. They are
neither unique homes nor prices. No private person or parcel records are read.
Schema validation deliberately imports only Python's standard library so the
ordinary static website publisher can reuse it without PDF dependencies.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import html
import io
import json
import os
import re
import ssl
import time
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from uuid import uuid4

ORIGIN = 'https://www.registryagency.bg'
CATALOGUE_URL = ORIGIN + '/bg/registri/imoten-registar/statistika/'
MAX_OUTPUT_BYTES = 256 * 1024
MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_CATALOGUE_BYTES = 2 * 1024 * 1024
MAX_PERIODS = 160
MAX_REVISIONS = 8
MAX_DOWNLOAD_ATTEMPTS = 3
MAX_RETRY_WAIT_SECONDS = 45
RETRY_HTTP_STATUS = {408, 429, 500, 502, 503, 504, 521, 522, 523, 524}
ACCESS_CHALLENGE_MARKERS = (b'captcha', b'cf-chl-', b'challenge-platform', b'cf-browser-verification',
                            b'just a moment', b'verify you are human')
START_YEAR = 2015
GEOGRAPHY = {'code': 'registry-office-sofia', 'name_bg': 'Служба по вписванията — София',
             'name_en': 'Registry Office — Sofia', 'scope': 'registration_office_jurisdiction'}
SOURCE_NAME = 'Агенция по вписванията — тримесечни справки на Имотния регистър'
METHODOLOGY_BG = ('Брой вписани продажби на всички видове недвижими имоти в района на Служба по вписванията — София. '
                  'Не е брой уникални жилища, сделки само с апартаменти или квартална статистика. '
                  'Договорните и законните ипотеки са отделни видове вписвания и не измерват дела покупки с кредит. '
                  'Липсващите тримесечия не са заместени с нули или интерполация. Данните не съдържат продажни цени или собственици.')
METHODOLOGY_EN = ('Registered sales of all real-estate types in the jurisdiction of Registry Office Sofia. '
                  'These are not unique homes, apartment-only transactions or neighborhood statistics. '
                  'Contractual and legal mortgages are separate registration types, not the share of purchases financed by a mortgage. '
                  'Missing quarters are not replaced with zero or interpolation. No sale prices or owners are included.')
# The 2018 Q4 report prints "Четгвърто"; retain this exact known source typo,
# with the catalogue period and PDF year still required to agree.
QUARTER_WORDS = {'първо': 1, 'второ': 2, 'трето': 3, 'четвърто': 4, 'четгвърто': 4}
QUARTER_MONTHS = {'януари': 1, 'април': 2, 'юли': 3, 'октомври': 4}


def normalized(value) -> str:
    return re.sub(r'\s+', '', str(value or '')).casefold()


def checked_url(value: str, *, pdf: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 512 or any(ord(character) < 32 for character in value):
        raise ValueError('Invalid official statistics URL')
    parts = urlsplit(value)
    if (parts.scheme != 'https' or parts.hostname != 'www.registryagency.bg'
            or parts.port not in (None, 443) or parts.username or parts.password or parts.query or parts.fragment
            or (pdf and (not parts.path.startswith('/media/filer_public/') or not parts.path.lower().endswith('.pdf')))):
        raise ValueError('Only official Registry Agency HTTPS source URLs are allowed')
    return value


class OfficialRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def retry_delay(retry_after: str | None, attempt: int) -> float | None:
    delay = float(5 * (3 ** attempt))
    if retry_after:
        try:
            if re.fullmatch(r'[0-9]+', retry_after.strip()):
                requested = float(retry_after.strip())
            else:
                pause_until = parsedate_to_datetime(retry_after)
                if pause_until.tzinfo is None:
                    return None
                requested = max(0.0, (pause_until - datetime.now(timezone.utc)).total_seconds())
            # A longer server-requested pause stops this capture; retrying
            # sooner would ignore its pacing instruction.
            if requested > MAX_RETRY_WAIT_SECONDS:
                return None
            delay = max(delay, requested)
        except (ValueError, TypeError, OverflowError):
            pass  # A malformed header leaves the ordinary polite backoff.
    return min(delay, MAX_RETRY_WAIT_SECONDS)


def download(url: str, limit: int) -> bytes:
    checked_url(url)
    opener = build_opener(OfficialRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(url, headers={'User-Agent': 'SofiaPermits-official-statistics/1.0'})
    for attempt in range(MAX_DOWNLOAD_ATTEMPTS):
        try:
            with opener.open(request, timeout=45) as response:
                checked_url(response.url)
                payload = response.read(limit + 1)
            if not payload or len(payload) > limit:
                raise ValueError('Official statistics response is empty or exceeds its byte limit')
            return payload
        except HTTPError as error:
            if error.code not in RETRY_HTTP_STATUS or attempt == MAX_DOWNLOAD_ATTEMPTS - 1:
                raise
            if (error.headers.get('cf-mitigated', '').casefold() == 'challenge'
                    or error.headers.get('Content-Encoding', 'identity').casefold() not in ('', 'identity')):
                raise
            # Access challenges are terminal even when returned with a 429 or
            # 503 status. Never retry authentication failures or CAPTCHA.
            try:
                body = error.read(32 * 1024).lower()
            finally:
                error.close()
            if any(marker in body for marker in ACCESS_CHALLENGE_MARKERS):
                raise
            delay = retry_delay(error.headers.get('Retry-After'), attempt)
            if delay is None:
                raise
            reason = f'HTTP {error.code}'
        except URLError as error:
            # Certificate/TLS errors and other transport failures are not
            # generalized into retries. Only an actual timeout is transient.
            if isinstance(error.reason, ssl.SSLError) or not isinstance(error.reason, TimeoutError) or attempt == MAX_DOWNLOAD_ATTEMPTS - 1:
                raise
            delay = retry_delay(None, attempt)
            reason = 'network timeout'
        except TimeoutError:
            if attempt == MAX_DOWNLOAD_ATTEMPTS - 1:
                raise
            delay = retry_delay(None, attempt)
            reason = 'network timeout'
        print(f'Official statistics {reason}; retry {attempt + 2}/{MAX_DOWNLOAD_ATTEMPTS} after {delay:g} seconds', flush=True)
        time.sleep(delay)
    raise RuntimeError('Official statistics download exhausted its bounded attempts')


def timestamp(value) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(r'20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', value):
        raise ValueError('Invalid transaction statistics UTC timestamp')
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)


def date_value(value) -> date:
    if not isinstance(value, str) or not re.fullmatch(r'20\d{2}-\d{2}-\d{2}', value):
        raise ValueError('Invalid transaction statistics source date')
    return date.fromisoformat(value)


def period_number(value: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r'20\d{2}-Q[1-4]', value) or int(value[:4]) < START_YEAR:
        raise ValueError('Invalid transaction statistics quarter')
    return int(value[:4]) * 4 + int(value[-1]) - 1


def period_label(value: int) -> str:
    return f'{value // 4}-Q{value % 4 + 1}'


def period_end(value: str) -> date:
    period_number(value)
    year, month = int(value[:4]), int(value[-1]) * 3
    return date(year, month, calendar.monthrange(year, month)[1])


def integer(value, label: str) -> int:
    if type(value) is not int or not 0 <= value <= 10_000_000:
        raise ValueError(f'Invalid transaction statistics {label}')
    return value


def validate_observation(row: dict, captured: datetime, *, revision: bool = False) -> None:
    if not isinstance(row, dict) or set(row) - {'period', 'sales', 'contractual_mortgages', 'legal_mortgages', 'source', 'revisions'}:
        raise ValueError('Invalid quarterly registered-sales observation')
    end = period_end(row.get('period'))
    if end >= captured.date():
        raise ValueError('Statistics cannot include an unfinished quarter')
    for metric in ('sales', 'contractual_mortgages', 'legal_mortgages'):
        integer(row.get(metric), metric)
    source = row.get('source')
    if (not isinstance(source, dict) or set(source) != {'url', 'page_url', 'published_at', 'catalogue_uploaded_at', 'sha256', 'retrieved_at'}
            or source.get('page_url') != CATALOGUE_URL
            or not isinstance(source.get('sha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', source['sha256'])):
        raise ValueError('Quarterly source provenance is incomplete')
    checked_url(source.get('url', ''), pdf=True)
    retrieved = timestamp(source.get('retrieved_at'))
    if retrieved > captured or retrieved.date() <= end:
        raise ValueError('Quarterly source capture date is inconsistent')
    uploaded = date_value(source.get('catalogue_uploaded_at'))
    if uploaded > retrieved.date():
        raise ValueError('Quarterly catalogue upload date lies after capture')
    published = source.get('published_at')
    if published is not None and (date_value(published) != uploaded or date_value(published) <= end):
        raise ValueError('Quarterly publication date is inconsistent with its period')
    if published is None and uploaded > end:
        raise ValueError('Known valid catalogue publication date was discarded')
    revisions = row.get('revisions', [])
    if not isinstance(revisions, list) or len(revisions) > (0 if revision else MAX_REVISIONS):
        raise ValueError('Quarterly revisions exceed their limit')
    for earlier in revisions:
        if not isinstance(earlier, dict) or earlier.get('period') != row['period']:
            raise ValueError('Quarterly revision refers to a different period')
        validate_observation(earlier, captured, revision=True)


def validate_snapshot(data: dict) -> dict:
    if (not isinstance(data, dict) or set(data) != {'schema_version', 'status', 'retrieved_at', 'source', 'geography', 'metric', 'unit', 'series', 'coverage', 'methodology_bg', 'methodology_en'}
            or data.get('schema_version') != 1 or type(data.get('schema_version')) is not int
            or data.get('status') != 'available' or data.get('metric') != 'registered_sales'
            or data.get('unit') != 'registrations' or data.get('geography') != GEOGRAPHY):
        raise ValueError('Unsupported registered-sales snapshot schema or geography')
    captured = timestamp(data.get('retrieved_at'))
    if captured > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError('Registered-sales capture date lies in the future')
    source = data.get('source')
    if not isinstance(source, dict) or set(source) != {'name', 'url', 'published_at', 'catalogue_sha256'} or source.get('url') != CATALOGUE_URL or source.get('name') != SOURCE_NAME:
        raise ValueError('Snapshot source is not the official Registry Agency catalogue')
    for field in ('methodology_bg', 'methodology_en'):
        if not isinstance(data.get(field), str) or not 20 <= len(data[field]) <= 2000:
            raise ValueError('Registered-sales methodology is missing')
    series = data.get('series')
    if not isinstance(series, list) or not 1 <= len(series) <= MAX_PERIODS:
        raise ValueError('Registered-sales quarterly history is empty or exceeds its limit')
    previous = -1
    dates = []
    numbers = []
    for row in series:
        validate_observation(row, captured)
        number = period_number(row['period'])
        if number <= previous:
            raise ValueError('Registered-sales quarters are duplicated or unsorted')
        previous = number
        numbers.append(number)
        if row['source']['published_at'] is not None:
            dates.append(row['source']['published_at'])
    if numbers[-1] - numbers[0] >= MAX_PERIODS:
        raise ValueError('Registered-sales history span exceeds its limit')
    missing = [period_label(number) for number in range(numbers[0], numbers[-1] + 1) if number not in set(numbers)]
    coverage = data.get('coverage')
    if (not isinstance(coverage, dict) or set(coverage) != {'from', 'to', 'periods', 'missing_periods'} or coverage.get('from') != series[0]['period']
            or coverage.get('to') != series[-1]['period'] or type(coverage.get('periods')) is not int
            or coverage['periods'] != len(series) or coverage.get('missing_periods') != missing):
        raise ValueError('Registered-sales history coverage is inconsistent')
    if source.get('published_at') != (max(dates) if dates else None):
        raise ValueError('Snapshot publication date does not match its source history')
    if not isinstance(source.get('catalogue_sha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', source['catalogue_sha256']):
        raise ValueError('Snapshot catalogue hash is missing')
    return data


def validate_payload(payload: bytes) -> dict:
    if not isinstance(payload, bytes) or not payload or len(payload) > MAX_OUTPUT_BYTES:
        raise ValueError('Registered-sales JSON exceeds its byte limit')
    return validate_snapshot(json.loads(payload.decode('utf-8')))


def catalogue_sources(payload: bytes) -> list[dict]:
    page = payload.decode('utf-8')
    sources = {}
    for block in re.findall(r'<div\s+class="document"\s*>(.*?)</div>', page, re.S | re.I):
        anchor = re.search(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S | re.I)
        if anchor is None:
            continue
        label = ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', anchor[2])).split()).casefold()
        year = re.search(r'\b(20\d{2})\b', label)
        if not year or int(year[1]) < START_YEAR or 'тримесечие' not in label:
            continue
        quarters = [quarter for name, quarter in QUARTER_MONTHS.items() if name in label]
        uploaded = re.search(r'качен\s+на\s+([0-3]\d\.[01]\d\.20\d{2})', block, re.I)
        if len(quarters) != 1 or uploaded is None:
            raise ValueError('Official quarterly link has an unknown quarter or upload date')
        period = f'{year[1]}-Q{quarters[0]}'
        if period in sources:
            raise ValueError('Official catalogue contains duplicate quarterly reports')
        end = period_end(period)
        if end >= datetime.now(timezone.utc).date():
            raise ValueError('Official catalogue contains an unfinished transaction quarter')
        upload_date = datetime.strptime(uploaded[1], '%d.%m.%Y').date().isoformat()
        sources[period] = {'period': period, 'url': checked_url(urljoin(ORIGIN, html.unescape(anchor[1])), pdf=True),
                           'catalogue_uploaded_at': upload_date, 'published_at': upload_date if date.fromisoformat(upload_date) > end else None}
    if not 20 <= len(sources) <= MAX_PERIODS:
        raise ValueError('Official catalogue has unexpectedly few or too many quarterly reports')
    return [sources[period] for period in sorted(sources)]


def count_cell(value) -> int:
    compact = normalized(value)
    if not re.fullmatch(r'[0-9]+', compact):
        raise ValueError('Official statistics table contains a missing or noninteger count')
    return integer(int(compact), 'table count')


def parse_report(payload: bytes, expected_period: str) -> dict:
    import pdfplumber  # Lazy: schema consumers and FTPS publishers use stdlib only.

    if not payload.startswith(b'%PDF-') or len(payload) > MAX_PDF_BYTES:
        raise ValueError('Official report is not a bounded PDF document')
    with pdfplumber.open(io.BytesIO(payload)) as document:
        if not 1 <= len(document.pages) <= 12:
            raise ValueError('Official report has an unexpected page count')
        title = ' '.join((document.pages[0].extract_text() or '').split())
        period = re.search(r'за\s*(първо|второ|трето|четвърто|четгвърто)\s*тримесечие\s*,?\s*(20\d{2})\s*година', title, re.I)
        if period is None or f'{period[2]}-Q{QUARTER_WORDS[period[1].casefold()]}' != expected_period:
            raise ValueError(f'PDF title does not confirm the requested quarter: {expected_period}')
        rows = []
        totals = None
        header = False
        for page in document.pages:
            if not 100 <= page.width <= 4000 or not 100 <= page.height <= 4000:
                raise ValueError('Official report page dimensions exceed their limit')
            for table in page.extract_tables():
                for row in table:
                    # Some legacy tables draw an extra, wholly empty border
                    # column. It carries no metric and is not a missing value.
                    if len(row) > 23 and all(normalized(cell) == '' for cell in row[23:]):
                        row = row[:23]
                    if len(row) != 23:
                        if header and totals is None and any('София' in str(cell) for cell in row):
                            raise ValueError('Sofia row has a changed statistics table layout')
                        continue
                    if normalized(row[2]) == 'продажби':
                        if (normalized(row[0]) not in ('№', 'no') or (normalized(row[1]) != 'св' and 'службапо' not in normalized(row[1]))
                                or normalized(row[8]) != 'законниипотеки' or normalized(row[9]) != 'договорниипотеки'
                                or normalized(row[18]) != 'общовписвания'):
                            raise ValueError('Official report columns changed their meaning')
                        header = True
                        continue
                    if not header:
                        continue
                    if normalized(row[0]) in ('общо:', 'общо'):
                        totals = row
                        break
                    if normalized(row[0]).isdigit():
                        values = [count_cell(cell) for cell in row[2:]]
                        if sum(values[:16]) != values[16]:
                            raise ValueError('Official registry office total does not reconcile')
                        rows.append({'number': count_cell(row[0]), 'office': normalized(row[1]), 'values': values})
                if totals is not None:
                    break
            if totals is not None:
                break
        if not header or totals is None or not 100 <= len(rows) <= 150:
            raise ValueError('Complete official sales table and its total were not found')
        if count_cell(totals[1]) != len(rows) or [row['number'] for row in rows] != list(range(1, len(rows) + 1)):
            raise ValueError('Official office row numbers or declared total do not reconcile')
        expected = [count_cell(cell) for cell in totals[2:]]
        actual = [sum(row['values'][column] for row in rows) for column in range(21)]
        if expected != actual:
            raise ValueError('Official national column totals do not reconcile')
        sofia = [row for row in rows if row['office'] in ('св-софия', 'св–софия', 'св—софия')]
        if len(sofia) != 1:
            raise ValueError('Exactly one Registry Office Sofia row is required')
        values = sofia[0]['values']
        return {'sales': values[0], 'legal_mortgages': values[6], 'contractual_mortgages': values[7]}


def collect(*, archives: Path | None = None, resume_capture: bool = False) -> dict:
    catalogue = download(CATALOGUE_URL, MAX_CATALOGUE_BYTES)
    sources = catalogue_sources(catalogue)
    if archives is not None:
        archives.mkdir(parents=True, exist_ok=True)
        (archives / 'catalogue.html').write_bytes(catalogue)
    series = []
    for position, source in enumerate(sources, 1):
        if resume_capture and archives is not None:
            record_path = archives / (source['period'] + '.json')
            pdf_path = archives / (source['period'] + '.pdf')
            if record_path.exists() and pdf_path.exists():
                if record_path.stat().st_size > MAX_OUTPUT_BYTES or pdf_path.stat().st_size > MAX_PDF_BYTES:
                    raise ValueError('Resume evidence exceeds its byte limit')
                row = json.loads(record_path.read_text(encoding='utf-8'))
                now = datetime.now(timezone.utc)
                validate_observation(row, now)
                payload = pdf_path.read_bytes()
                if (row['period'] != source['period'] or row['source']['url'] != source['url']
                        or row['source']['published_at'] != source['published_at']
                        or row['source']['catalogue_uploaded_at'] != source['catalogue_uploaded_at']
                        or timestamp(row['source']['retrieved_at']).date() != now.date()
                        or hashlib.sha256(payload).hexdigest() != row['source']['sha256']):
                    raise ValueError('Resume evidence differs from the same-day official capture')
                values = parse_report(payload, source['period'])
                if any(row[key] != value for key, value in values.items()):
                    raise ValueError('Resume PDF and recorded statistics differ')
                series.append(row)
                print(f"Resumed {position}/{len(sources)} verified same-day capture: {source['period']}", flush=True)
                continue
        # One worker; the brief interval also applies when network extraction is fast.
        if position > 1:
            time.sleep(0.65)
        payload = download(source['url'], MAX_PDF_BYTES)
        if archives is not None:
            (archives / (source['period'] + '.pdf')).write_bytes(payload)
        values = parse_report(payload, source['period'])
        captured = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        row = {'period': source['period'], **values, 'source': {
            'url': source['url'], 'page_url': CATALOGUE_URL, 'published_at': source['published_at'],
            'catalogue_uploaded_at': source['catalogue_uploaded_at'],
            'sha256': hashlib.sha256(payload).hexdigest(), 'retrieved_at': captured}}
        series.append(row)
        if archives is not None:
            (archives / (source['period'] + '.json')).write_text(json.dumps(row, ensure_ascii=False), encoding='utf-8')
        print(f"Captured {position}/{len(sources)} official quarters: {source['period']} - {values['sales']:,} Sofia registered sales", flush=True)
    data = {'schema_version': 1, 'status': 'available', 'retrieved_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'source': {'name': SOURCE_NAME, 'url': CATALOGUE_URL, 'published_at': None,
                       'catalogue_sha256': hashlib.sha256(catalogue).hexdigest()},
            'geography': GEOGRAPHY.copy(), 'metric': 'registered_sales', 'unit': 'registrations', 'series': series,
            'methodology_bg': METHODOLOGY_BG, 'methodology_en': METHODOLOGY_EN}
    update_coverage(data)
    return validate_snapshot(data)


def update_coverage(data: dict) -> None:
    series = data['series']
    numbers = {period_number(row['period']) for row in series}
    data['coverage'] = {'from': series[0]['period'], 'to': series[-1]['period'], 'periods': len(series),
                        'missing_periods': [period_label(number) for number in range(min(numbers), max(numbers) + 1) if number not in numbers]}
    dates = [row['source']['published_at'] for row in series if row['source']['published_at'] is not None]
    data['source']['published_at'] = max(dates) if dates else None


def merge_previous(data: dict, previous: dict) -> dict:
    validate_snapshot(previous)
    if data['retrieved_at'] < previous['retrieved_at'] or data['coverage']['to'] < previous['coverage']['to']:
        raise ValueError('Fresh transaction capture would regress its date or latest quarter')
    merged = {row['period']: row for row in previous['series']}
    for current in data['series']:
        earlier = merged.get(current['period'])
        if earlier is not None:
            revisions = list(earlier.get('revisions', []))
            changed = (any(earlier[key] != current[key] for key in ('sales', 'legal_mortgages', 'contractual_mortgages'))
                       or earlier['source']['sha256'] != current['source']['sha256'])
            if changed:
                revisions.append({key: value for key, value in earlier.items() if key != 'revisions'})
            if revisions:
                current['revisions'] = revisions
        merged[current['period']] = current
    data['series'] = [merged[period] for period in sorted(merged)]
    update_coverage(data)
    return validate_snapshot(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('public/data/transactions-context.json'))
    parser.add_argument('--previous', type=Path, help='Earlier validated JSON; defaults to existing output when present')
    parser.add_argument('--archives', type=Path, help='Optional local capture evidence directory for official PDFs')
    parser.add_argument('--resume-capture', action='store_true', help='Resume only hash-verified same-day PDF/record pairs in --archives')
    args = parser.parse_args()
    if args.resume_capture and args.archives is None:
        parser.error('--resume-capture requires --archives')
    previous_path = args.previous if args.previous is not None else args.output if args.output.exists() else None
    previous = None
    if previous_path is not None:
        with previous_path.open('rb') as source:
            previous = validate_payload(source.read(MAX_OUTPUT_BYTES + 1))
    data = collect(archives=args.archives, resume_capture=args.resume_capture)
    if previous is not None:
        data = merge_previous(data, previous)
    payload = (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    validate_payload(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + f'.{uuid4().hex}.pending')
    try:
        with temporary.open('xb') as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, args.output)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Prepared {len(data['series'])} official sales quarters, {data['coverage']['from']}–{data['coverage']['to']}; {len(data['coverage']['missing_periods'])} explicit missing quarters")


if __name__ == '__main__':
    main()
