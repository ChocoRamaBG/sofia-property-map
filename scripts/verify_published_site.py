#!/usr/bin/env python3
"""Read deployed public website files over verified FTPS; never write to hosting."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import ssl
import time
from datetime import datetime, timezone
from ftplib import FTP_TLS
from pathlib import Path

from deploy_site_ftps import MAX_TRANSACTIONS_BYTES, REMOTE_ROOT, read_remote, validate_transactions

MAX_ASSET_BYTES = 3 * 1024 * 1024
ASSET = re.compile(r'assets/[A-Za-z0-9][A-Za-z0-9._-]*\.(?:js|css)\Z')


def asset_name(value: str) -> str:
    name = html.unescape(value).removeprefix('/')
    if ASSET.fullmatch(name) is None:
        raise ValueError('Deployed asset reference is outside the public allowlist')
    return name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--wait-business-map', type=int, default=0, help='Bounded wait for a staged legacy company snapshot to gain its point index')
    args = parser.parse_args()
    if not 0 <= args.wait_business_map <= 600:
        parser.error('--wait-business-map must be between 0 and 600 seconds')
    credentials = {key: os.environ.get(key, '') for key in ('FTP_HOST', 'FTP_USER', 'FTP_PASSWORD')}
    if not all(credentials.values()) or any('\r' in value or '\n' in value for value in credentials.values()):
        raise ValueError('Valid hosting credentials are required')
    report = {'verified_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'method': 'read_only_verified_ftps', 'files': {}}
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with FTP_TLS(context=context, timeout=45) as ftp:
        ftp.connect(credentials['FTP_HOST'], 21)
        ftp.login(credentials['FTP_USER'], credentials['FTP_PASSWORD'])
        ftp.prot_p()

        def read(name: str, limit: int) -> str:
            payload = read_remote(ftp, f'{REMOTE_ROOT}/{name}', limit)
            if not payload:
                raise ValueError(f'Deployed public file is empty: {name}')
            report['files'][name] = {'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
            return payload.decode('utf-8')

        entry_html = read('index.html', 64 * 1024)
        if '</html>' not in entry_html.lower() or '/aes.js' in entry_html:
            raise ValueError('Hosting entry file is not the deployed application HTML')
        scripts = re.findall(r'<script\b[^>]*\bsrc=[\"\x27]([^\"\x27]+)[\"\x27]', entry_html, re.I)
        entries = [asset_name(value) for value in scripts if value.startswith(('/assets/', 'assets/'))]
        if len(entries) != 1 or not entries[0].endswith('.js'):
            raise ValueError('Expected exactly one application entry module')
        module = read(entries[0], MAX_ASSET_BYTES)

        def chunk(prefix) -> str:
            prefixes = prefix if isinstance(prefix, (tuple, list)) else [prefix]
            pattern = '(?:' + '|'.join(re.escape(value) for value in prefixes) + ')'
            references = re.findall(r'(?:assets/)?' + pattern + r'-[A-Za-z0-9_-]+\.js', module)
            names = {asset_name(name if name.startswith('assets/') else 'assets/' + name) for name in references}
            if len(names) != 1:
                raise ValueError(f'Cannot identify deployed {prefix} module')
            name = names.pop()
            return read(name, MAX_ASSET_BYTES)

        dashboard = chunk('DevelopmentDashboard')
        details = chunk('DetailsPanel')
        registered = chunk(('RegisteredBusinesses', 'DetailPanels'))
        address_details = chunk('BusinessAddressDetails')
        if 'business-data.php' not in module or 'business-data.php' not in registered or 'Companies registered at this address' not in registered:
            raise ValueError('Deployed website does not include the company address finder and plot section')
        if 'company-map-levels' not in module or not all(code in registered for code in ('municipal_address', 'municipal_parcel')) or 'address_id' not in address_details:
            raise ValueError('Deployed website does not distinguish official addresses and parcel associations')
        if 'company-map-panel' not in module or 'map-dataset-switch' not in module:
            raise ValueError('Deployed website does not include the complete company map layer')
        if not all(marker in module for marker in ('map-sidebar-collapse', 'map-panel-opener', 'map-display-menu', 'filter-disclosure')) or 'source-additional-records' not in details:
            raise ValueError('Deployed website lacks the compact sidebar, map tools or evidence disclosures')
        if 'Ownership and registered acts' in details or 'Companies in documents' in details:
            raise ValueError('The removed ownership/document-company interface is still deployed')
        business_api = read('business-data.php', 128 * 1024)
        if 'registered_office_address_association' not in business_api or 'function business_search' not in business_api or 'function business_viewport' not in business_api:
            raise ValueError('Deployed read-only business API is missing')
        deadline = time.monotonic() + args.wait_business_map
        while True:
            pointer_raw = read_remote(ftp, f'{REMOTE_ROOT}/private/business-active.json', 1024)
            pointer = json.loads(pointer_raw)
            if set(pointer) != {'version', 'snapshot_id', 'manifest_sha256'} or pointer['version'] != 1 or not re.fullmatch(r'[a-f0-9]{32}', pointer['snapshot_id']) or not re.fullmatch(r'[a-f0-9]{64}', pointer['manifest_sha256']):
                raise ValueError('Deployed company pointer is invalid')
            manifest_raw = read_remote(ftp, f"{REMOTE_ROOT}/private/business-snapshots/{pointer['snapshot_id']}/manifest.json", 256 * 1024)
            if hashlib.sha256(manifest_raw).hexdigest() != pointer['manifest_sha256']:
                raise ValueError('Deployed company manifest hash is invalid')
            business_manifest = json.loads(manifest_raw)
            if business_manifest.get('version') == 2 or time.monotonic() >= deadline:
                break
            time.sleep(min(10, max(0, deadline - time.monotonic())))
        points = business_manifest.get('points_index')
        if not isinstance(points, dict) or points.get('file') != 'points-index.json' or type(points.get('bytes')) is not int or not 2 <= points['bytes'] <= 9_500_000 or not re.fullmatch(r'[a-f0-9]{64}', points.get('sha256', '')):
            raise ValueError('Deployed company map has no valid point index')
        point_raw = read_remote(ftp, f"{REMOTE_ROOT}/private/business-snapshots/{pointer['snapshot_id']}/points-index.json", 9_500_000)
        if len(point_raw) != points['bytes'] or hashlib.sha256(point_raw).hexdigest() != points['sha256'] or len(json.loads(point_raw)) != business_manifest['counts']['mapped_business_parcels']:
            raise ValueError('Deployed company map point index failed verification')
        addresses = business_manifest.get('address_index')
        if business_manifest.get('version') != 2 or not isinstance(addresses, dict) or addresses.get('file') != 'address-index.json' or type(addresses.get('bytes')) is not int or not 2 <= addresses['bytes'] <= 9_500_000 or not re.fullmatch(r'[a-f0-9]{64}', addresses.get('sha256', '')):
            raise ValueError('Deployed company snapshot lacks verified municipal address data')
        address_raw = read_remote(ftp, f"{REMOTE_ROOT}/private/business-snapshots/{pointer['snapshot_id']}/address-index.json", 9_500_000)
        address_index = json.loads(address_raw)
        if len(address_raw) != addresses['bytes'] or hashlib.sha256(address_raw).hexdigest() != addresses['sha256'] or len(address_index) != business_manifest['counts']['address_only_locations'] or sum(row['company_count'] for row in address_index.values()) != business_manifest['counts']['address_only_companies']:
            raise ValueError('Deployed official-address index failed verification')
        report['business_addresses'] = {'snapshot_id': pointer['snapshot_id'], 'generated_at': business_manifest['generated_at'], 'source_commit': business_manifest['source']['commit'], 'counts': business_manifest['counts']}
        if 'transactions-context.json' not in dashboard or 'registered_sales' not in dashboard:
            raise ValueError('Deployed dashboard does not include the transaction statistics feature')
        if 'section=transactions' not in dashboard or 'sales-statistics' not in dashboard:
            raise ValueError('Deployed dashboard does not include the direct statistics shortcut')
        styles = re.findall(r'<link\b[^>]*\bhref=[\"\x27]([^\"\x27]+\.css)[\"\x27]', entry_html, re.I)
        styles = [read(asset_name(name), MAX_ASSET_BYTES) for name in styles if name.startswith(('/assets/', 'assets/'))]
        if not any('overflow:clip' in css and re.search(r'\.app-header\{[^}]*position:sticky', css) for css in styles):
            raise ValueError('Deployed website does not include persistent workspace navigation')
        if not any('.leaflet-tooltip.parcel-fallback-tooltip' in css and 'overflow-wrap:anywhere' in css for css in styles):
            raise ValueError('Deployed stylesheet does not include the tooltip wrapping fix')
        if not any(all(re.search(r'(?<![A-Za-z0-9_-])width:min\(' + str(width) + r'px,', css) for width in (280, 310)) for css in styles):
            raise ValueError('Deployed tooltips do not have explicit responsive widths')
        payload = read_remote(ftp, f'{REMOTE_ROOT}/data/transactions-context.json', MAX_TRANSACTIONS_BYTES)
        data = validate_transactions(payload)
        report['files']['data/transactions-context.json'] = {'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
        report['transactions'] = {'coverage': data['coverage'], 'latest_period': data['series'][-1]['period'], 'latest_sales': data['series'][-1]['sales'], 'retrieved_at': data['retrieved_at']}
        report['features'] = {'registered_sales_dashboard': True, 'direct_statistics_link': True, 'tooltip_wrapping_fix': True, 'tooltip_explicit_widths': True, 'business_address_finder': True, 'business_plot_section': True, 'ownership_placeholder_removed': True, 'company_map_layer': True, 'persistent_workspace_navigation': True, 'municipal_address_enrichment': True, 'separate_location_evidence_levels': True, 'collapsible_map_sidebar': True, 'compact_map_tools': True, 'progressive_detail_disclosures': True}
        report['status'] = 'verified'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
