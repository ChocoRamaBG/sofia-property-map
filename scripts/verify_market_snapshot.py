"""Read back the active market snapshot over verified FTPS and report freshness."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import ssl
from ftplib import FTP_TLS

from deploy_imot_ftps import pointer, manifest_for, descriptor_payload, validate_pointer, protected
from imot_market_format import MAX_SUMMARY_BYTES, validate_public_enrichment, validate_summary_projection


def verify_active_market(ftp, *, require_fresh=False, expected_pointer=None, now=None):
    raw = pointer(ftp)
    if raw is None:
        if require_fresh or expected_pointer is not None:
            raise ValueError('No verified market snapshot is active')
        return {'available': False, 'freshness_status': 'unpublished'}
    active, manifest = manifest_for(ftp, raw)
    if expected_pointer is not None and active != validate_pointer(expected_pointer):
        raise ValueError('Active market pointer does not match the prepared publication')
    summary_raw = descriptor_payload(ftp, active['snapshot_id'], manifest['summary_file'], MAX_SUMMARY_BYTES)
    summary = json.loads(summary_raw)
    counts = summary.get('counts', {})
    if (summary.get('mode') != manifest['mode'] or summary.get('captured_at') != manifest.get('captured_at')
            or counts.get('listing_count') != manifest['counts']['listing_count'] or counts != manifest['counts']):
        raise ValueError('Active market summary does not reconcile with its manifest')
    validate_summary_projection(summary)
    for offer in [*summary.get('top_offers', []), *summary.get('daily_candidates', [])]:
        validate_public_enrichment(offer)
    captured = summary.get('captured_at')
    if not isinstance(captured, str):
        raise ValueError('Active market capture time is missing')
    captured_time = datetime.fromisoformat(captured.replace('Z', '+00:00'))
    if captured_time.tzinfo is None:
        if manifest['mode'] == 'daily' or len(captured) != 10:
            raise ValueError('Daily market capture time lacks a timezone')
        captured_time = captured_time.replace(tzinfo=timezone.utc)
    checked = now or datetime.now(timezone.utc)
    age = (checked - captured_time).total_seconds()
    if age < -300:
        raise ValueError('Active market capture time is in the future')
    freshness = 'historical' if manifest['mode'] != 'daily' else 'fresh' if age <= 48 * 3600 else 'stale'
    if require_fresh and freshness != 'fresh':
        raise ValueError('The active market snapshot is not a daily capture within the last 48 hours')
    report = {'available': True, 'snapshot_id': active['snapshot_id'], 'mode': manifest['mode'],
              'captured_at': captured, 'verified_at': checked.isoformat(timespec='seconds').replace('+00:00', 'Z'),
              'freshness_status': freshness, 'age_hours': round(max(age, 0) / 3600, 2),
              'listing_count': counts['listing_count'], 'summary_bytes': len(summary_raw),
              'comparison_method_version': summary.get('methodology', {}).get('method_version'),
              'agency_identity_count': counts.get('agency_identity_count', 0), 'agency_phone_count': counts.get('agency_phone_count', 0),
              'description_analyzed_count': counts.get('description_analyzed_count', 0),
              'listing_shard_count': len(manifest['listing_shards'])}
    if pointer(ftp) != raw:
        raise ValueError('Active market pointer changed during verification; repeat the check')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-pointer', type=Path)
    parser.add_argument('--require-fresh', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    expected = None
    if args.expected_pointer:
        if args.expected_pointer.is_symlink() or not 1 <= args.expected_pointer.stat().st_size <= 4096:
            raise ValueError('Prepared market pointer is absent, linked or oversized')
        expected = args.expected_pointer.read_bytes()
        validate_pointer(expected)
    credentials = [os.environ.get(name, '') for name in ('FTP_HOST', 'FTP_USER', 'FTP_PASSWORD')]
    if any(not value or '\r' in value or '\n' in value for value in credentials):
        raise ValueError('Valid hosting credentials are required')
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with FTP_TLS(context=context, timeout=90) as ftp:
        ftp.connect(credentials[0], 21)
        ftp.login(credentials[1], credentials[2])
        ftp.prot_p()
        protected(ftp)
        report = verify_active_market(ftp, require_fresh=args.require_fresh, expected_pointer=expected)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as output:
            output.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__': main()
