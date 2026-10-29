#!/usr/bin/env python3
"""Recover a fresh, completed census and its verified minimal enrichment.

Only original same-repository/main daily runs with successful capture and
enrichment steps qualify. No ZIP paths are extracted, source times are never
rewritten, and recovery never contacts the advert website.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import stat
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from imot_enrichment import ANALYSIS_METHOD_VERSION, CACHE_FIELDS, CLAIM_FIELDS, _valid_cache
from imot_market_format import MAX_CAPTURE_BYTES, validate_public_enrichment
from recover_imot_capture import API, REPOSITORY, WORKFLOW_PATH, MAX_ARCHIVE_BYTES, client, get_json, utc, validate_capture

CAPTURE_STEP = 'Capture all apartment search leaves'
ENRICHMENT_STEP = 'Analyze seller and property text with a bounded incremental detail pass'
SOURCE_CATALOGUE = 'https://www.imot.bg/obiavi/prodazhbi/grad-sofiya'
REPORT_COUNTS = {'attempted', 'analyzed', 'reused', 'unavailable', 'failed', 'listing_count',
                 'description_analyzed_count', 'agency_named_count', 'professional_contact_count',
                 'construction_type_known_count', 'furnishing_known_count', 'building_year_known_count',
                 'elevator_known_count', 'pending_count'}
REPORT_FIELDS = REPORT_COUNTS | {'version', 'started_at', 'finished_at', 'limit', 'stopped_reason',
                                 'description_storage', 'maximum_cache_age_days'}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def strict_json(payload):
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= MAX_CAPTURE_BYTES:
        raise ValueError('Recovered evidence exceeds its member byte bound')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Recovered evidence contains duplicate JSON keys')
            result[key] = value
        return result
    def constant(_):
        raise ValueError('Recovered evidence contains a non-finite JSON value')
    return json.loads(payload, object_pairs_hook=pairs, parse_constant=constant)


def read_evidence_zip(payload):
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= MAX_ARCHIVE_BYTES:
        raise ValueError('Source artifact exceeds its archive byte bound')
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = archive.infolist()
        names = [item.filename for item in members]
        allowed = {'capture.json', 'capture-enriched.json', 'capture-progress.json'}
        if len(names) != len(set(names)) or set(names) - allowed or not {'capture.json', 'capture-enriched.json'} <= set(names):
            raise ValueError('Artifact contains unexpected, duplicate or missing ZIP members')
        for item in members:
            if item.is_dir() or stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1 or not 1 <= item.file_size <= MAX_CAPTURE_BYTES:
                raise ValueError('Artifact member is linked, encrypted or oversized')
        result = {}
        for name in ('capture.json', 'capture-enriched.json'):
            item = archive.getinfo(name)
            with archive.open(item) as stream:
                member = stream.read(MAX_CAPTURE_BYTES + 1)
            if len(member) != item.file_size or len(member) > MAX_CAPTURE_BYTES:
                raise ValueError('Artifact member differs from its declared bound')
            result[name] = member
    return result['capture.json'], result['capture-enriched.json']


def download_evidence(session, artifact):
    if type(artifact.get('id')) is not int or not 1 <= artifact['id'] <= 10 ** 18 or type(artifact.get('size_in_bytes')) is not int or not 1 <= artifact['size_in_bytes'] <= MAX_ARCHIVE_BYTES:
        raise ValueError('Invalid bounded source artifact metadata')
    digest = artifact.get('digest')
    if not isinstance(digest, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
        raise ValueError('Source artifact lacks a declared SHA-256 digest')
    reply = session.get(f"{API}/actions/artifacts/{artifact['id']}/zip", timeout=(10, 30), allow_redirects=False)
    if reply.status_code != 302:
        raise ValueError(f'Artifact request failed with HTTP {reply.status_code}')
    location = reply.headers.get('Location', '')
    parsed = urlparse(location)
    host = parsed.hostname or ''
    allowed = any(host.endswith(suffix) for suffix in ('.blob.core.windows.net', '.blob.storage.azure.net', '.actions.githubusercontent.com', '.s3.amazonaws.com'))
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.fragment or parsed.port not in {None, 443} or not allowed:
        raise ValueError('Unexpected artifact storage redirect')
    output = io.BytesIO()
    # An authenticated GitHub session must never follow the storage redirect.
    with requests.get(location, timeout=(10, 60), stream=True, allow_redirects=False) as response:
        if response.status_code != 200:
            raise ValueError(f'Artifact storage request failed with HTTP {response.status_code}')
        declared = response.headers.get('Content-Length', '')
        if declared.isdigit() and int(declared) > MAX_ARCHIVE_BYTES:
            raise ValueError('Artifact response exceeds its byte bound')
        for chunk in response.iter_content(64 * 1024):
            if output.tell() + len(chunk) > MAX_ARCHIVE_BYTES:
                raise ValueError('Artifact stream exceeds its byte bound')
            output.write(chunk)
    payload = output.getvalue()
    if 'sha256:' + hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError('Downloaded source artifact failed its SHA-256 check')
    return read_evidence_zip(payload)


def validate_origin(run, jobs, artifact, run_id):
    if (run.get('id') != run_id or run.get('status') != 'completed' or run.get('head_branch') != 'main'
            or not isinstance(run.get('head_sha'), str) or not re.fullmatch(r'(?:[a-f0-9]{40}|[a-f0-9]{64})', run['head_sha'])
            or not isinstance(run.get('path'), str) or run['path'].split('@', 1)[0] != WORKFLOW_PATH
            or run.get('event') not in {'schedule', 'workflow_dispatch'}
            or run.get('head_repository', {}).get('full_name', '').casefold() != REPOSITORY.casefold()
            or run.get('repository', {}).get('full_name', '').casefold() != REPOSITORY.casefold()):
        raise ValueError('Recovery requires a completed same-repository main daily workflow')
    if (artifact.get('name') != f'imot-source-evidence-{run_id}' or artifact.get('expired') is not False
            or artifact.get('workflow_run', {}).get('id') != run_id
            or artifact.get('workflow_run', {}).get('head_sha') != run.get('head_sha')):
        raise ValueError('Source artifact provenance differs from its original daily run')
    qualified = []
    for job in jobs.get('jobs', []):
        if job.get('run_id') != run_id:
            raise ValueError('Recovered job belongs to a different workflow run')
        steps = job.get('steps', [])
        capture = [step for step in steps if step.get('name') == CAPTURE_STEP and step.get('conclusion') == 'success']
        enrichment = [step for step in steps if step.get('name') == ENRICHMENT_STEP and step.get('conclusion') == 'success']
        if len(capture) == len(enrichment) == 1:
            if utc(capture[0]['completed_at']) > utc(enrichment[0]['started_at']):
                raise ValueError('Recovered job steps have contradictory times')
            qualified.append((capture[0], enrichment[0]))
    if len(qualified) != 1:
        raise ValueError('Original capture and enrichment steps must both have succeeded')
    return qualified[0]


def validate_source_ids(capture):
    rows = {row['id']: row for row in capture['listings']}
    retained = set()
    for source in capture['capture']['searches']:
        seen = set()
        for page in source['pages']:
            identifiers = page.get('ids')
            if (not isinstance(identifiers, list) or len(identifiers) != page['count']
                    or any(not isinstance(value, str) or not re.fullmatch(r'1[a-z][0-9]{12,20}', value) for value in identifiers)
                    or len(set(identifiers)) != len(identifiers)
                    or hashlib.sha256(json.dumps(identifiers, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest() != page.get('ids_sha256')
                    or seen.intersection(identifiers)):
                raise ValueError('Source pagination IDs, counts or hashes do not reconcile')
            seen.update(identifiers)
        if len(seen) != source['captured_count']:
            raise ValueError('Recovered search ID total does not reconcile')
        for identifier in seen:
            row = rows.get(identifier)
            if row is None or row.get('neighborhood_bg') != source.get('neighborhood_bg') or row.get('type_bg') != source.get('type_bg'):
                raise ValueError('Listing does not belong to its recorded neighborhood/type search')
        retained.update(seen)
    if retained != set(rows):
        raise ValueError('Source census differs from its exact search ID union')


def validate_enriched_capture(raw_payload, enriched_payload):
    raw, enriched = strict_json(raw_payload), strict_json(enriched_payload)
    context = validate_capture(raw_payload)  # Original six-hour complete-census checks.
    if context.get('source_url') != SOURCE_CATALOGUE:
        raise ValueError('Recovered census does not use the configured Sofia source catalogue')
    validate_source_ids(raw)
    if (not isinstance(enriched, dict) or set(enriched) != set(raw) | {'enrichment_cache', 'enrichment'}
            or encoded({key: value for key, value in enriched.items() if key not in {'listings', 'enrichment_cache', 'enrichment'}})
            != encoded({key: value for key, value in raw.items() if key != 'listings'})
            or not isinstance(enriched.get('listings'), list) or len(enriched['listings']) != len(raw['listings'])):
        raise ValueError('Enrichment altered the original capture context or census')
    now = datetime.now(timezone.utc)
    rows = {}
    for original, row in zip(raw['listings'], enriched['listings']):
        if (not isinstance(row, dict) or set(row) != set(original) or row.get('id') != original['id']
                or encoded({key: value for key, value in row.items() if key not in CLAIM_FIELDS})
                != encoded({key: value for key, value in original.items() if key not in CLAIM_FIELDS})
                or row.get('analysis_method_version') != ANALYSIS_METHOD_VERSION
                or not set(CLAIM_FIELDS) <= set(row) or not re.fullmatch(r'[a-f0-9]{64}', str(row.get('enrichment_card_sha256', '')))):
            raise ValueError('Enrichment altered source listing facts or has incompatible claims')
        validate_public_enrichment(row)
        for value in [row['seller_checked_at'], row['analysis']['checked_at'], row['property_features']['checked_at'], (row.get('agency') or {}).get('checked_at')]:
            if value is not None and not 0 <= (now - utc(value)).total_seconds() <= 30 * 86400:
                raise ValueError('Enriched claim has an invalid evidence date')
        hints = row['location_hints']
        if (not isinstance(hints, list) or len(hints) > 3 or any(not isinstance(hint, dict)
                or set(hint) != {'kind', 'name', 'house_number', 'nearby', 'source'} or hint['kind'] != 'street'
                or not isinstance(hint['name'], str) or not 1 <= len(hint['name']) <= 80 or type(hint['nearby']) is not bool
                or hint['source'] not in {'card', 'description'} or (hint['house_number'] is not None and (not isinstance(hint['house_number'], str) or len(hint['house_number']) > 20)) for hint in hints)):
            raise ValueError('Recovered enrichment contains unsupported location hints')
        rows[row['id']] = row
    cache, report = enriched['enrichment_cache'], enriched['enrichment']
    if not isinstance(cache, dict) or len(cache) > len(rows) or not isinstance(report, dict) or set(report) != REPORT_FIELDS:
        raise ValueError('Recovered enrichment cache or coverage report is invalid')
    for identifier, entry in cache.items():
        row = rows.get(identifier)
        if (row is None or not isinstance(entry, dict) or set(entry) != set(CACHE_FIELDS)
                or not _valid_cache(entry, row['enrichment_card_sha256'], now)
                or encoded({key: entry[key] for key in CLAIM_FIELDS}) != encoded({key: row[key] for key in CLAIM_FIELDS})
                or (entry['status'] == 'analyzed') != (entry['analysis']['description_analyzed'] is True)
                or (entry['status'] == 'analyzed' and entry['description_sha256'] is None)):
            raise ValueError('Recovered enrichment cache is stale, incompatible or belongs to another listing')
    if (report['version'] != 1 or report['description_storage'] != 'derived_claims_only' or report['maximum_cache_age_days'] != 30
            or type(report['limit']) is not int or not 0 <= report['limit'] <= 1200
            or any(type(report[key]) is not int or not 0 <= report[key] <= len(rows) + 1200 for key in REPORT_COUNTS)
            or report['listing_count'] != len(rows) or report['attempted'] > report['limit']
            or report['analyzed'] + report['unavailable'] + report['failed'] > report['attempted']
            or report['reused'] + report['analyzed'] + report['unavailable'] != len(cache)
            or report['pending_count'] != len(rows) - len(cache)
            or report['stopped_reason'] not in {None, 'access_restricted', 'source_unavailable', 'runtime_budget', 'request_budget'}):
        raise ValueError('Recovered enrichment coverage does not reconcile')
    expected_counts = {
        'description_analyzed_count': sum(row['analysis']['description_analyzed'] is True for row in rows.values()),
        'agency_named_count': sum(bool(row.get('agency')) for row in rows.values()),
        'professional_contact_count': sum(bool((row.get('agency') or {}).get('phone')) for row in rows.values()),
        'construction_type_known_count': sum(row['property_features']['construction_type'] != 'unknown' for row in rows.values()),
        'furnishing_known_count': sum(row['property_features']['furnishing'] != 'unknown' for row in rows.values()),
        'building_year_known_count': sum(row['property_features']['building_year'] is not None for row in rows.values()),
        'elevator_known_count': sum(row['property_features']['elevator'] != 'unknown' for row in rows.values()),
    }
    if any(report[key] != count for key, count in expected_counts.items()):
        raise ValueError('Recovered property coverage counts do not match its listing evidence')
    started, finished = utc(report['started_at']), utc(report['finished_at'])
    if not utc(context['finished_at']) <= started <= finished <= now or (finished - started).total_seconds() > 3600:
        raise ValueError('Recovered enrichment has inconsistent source times')
    return context, report


def validate_output_paths(output, source_output=None):
    paths = [output] + ([source_output] if source_output is not None else [])
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError('Raw and enriched recovery outputs must be distinct')
    if any(path.exists() or path.is_symlink() for path in paths):
        raise ValueError('Recovery output exists; choose fresh paths')


def write_outputs(output, enriched, source_output=None, raw=None):
    validate_output_paths(output, source_output)
    payloads = [(output, enriched)] + ([(source_output, raw)] if source_output is not None else [])
    created = []
    try:
        for path, payload in payloads:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                created.append(path)
                stream.write(payload)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)  # Only files created by this recovery.
        raise


def recover(args):
    source_output = getattr(args, 'source_output', None)
    validate_output_paths(args.output, source_output)
    session = client()
    run = get_json(session, f'/actions/runs/{args.run}')
    jobs = get_json(session, f'/actions/runs/{args.run}/jobs?per_page=100')
    artifacts = get_json(session, f'/actions/runs/{args.run}/artifacts?per_page=100')
    selected = [item for item in artifacts.get('artifacts', []) if item.get('name') == f'imot-source-evidence-{args.run}' and item.get('expired') is False]
    if len(selected) != 1:
        raise ValueError('No unambiguous original enriched source artifact remains')
    artifact = selected[0]
    capture_step, enrichment_step = validate_origin(run, jobs, artifact, args.run)
    raw, enriched = download_evidence(session, artifact)
    context, report = validate_enriched_capture(raw, enriched)
    if not (utc(capture_step['started_at']) <= utc(context['started_at']) <= utc(context['finished_at']) <= utc(capture_step['completed_at'])
            and utc(enrichment_step['started_at']) <= utc(report['started_at']) <= utc(report['finished_at']) <= utc(enrichment_step['completed_at'])):
        raise ValueError('Recovered evidence times do not belong to its successful source steps')
    write_outputs(args.output, enriched, source_output, raw)
    print(json.dumps({'reused_run_id': args.run, 'artifact_id': artifact['id'], 'enriched_bytes': len(enriched),
                      'enriched_sha256': hashlib.sha256(enriched).hexdigest(), 'source_sha256': hashlib.sha256(raw).hexdigest(),
                      'listing_count': context['captured_count'], 'captured_at': context['finished_at'],
                      'enrichment_finished_at': report['finished_at'], 'description_analyzed_count': report['description_analyzed_count']}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-output', type=Path, help='Also preserve the exact validated original census bytes')
    args = parser.parse_args()
    if not 1 <= args.run <= 10 ** 18:
        parser.error('--run must be a positive original workflow run ID')
    try:
        recover(args)
    except Exception as error:
        print(f'Enriched capture recovery stopped: {type(error).__name__}', file=sys.stderr)
        if isinstance(error, ValueError) and not isinstance(error, requests.RequestException):
            print(str(error), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
