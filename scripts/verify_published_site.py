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
    args = parser.parse_args()
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

        def chunk(prefix: str) -> str:
            names = set(re.findall(r'(?:assets/)?' + re.escape(prefix) + r'-[A-Za-z0-9_-]+\.js', module))
            if len(names) != 1:
                raise ValueError(f'Cannot identify deployed {prefix} module')
            name = names.pop()
            return read(asset_name(name if name.startswith('assets/') else 'assets/' + name), MAX_ASSET_BYTES)

        dashboard = chunk('DevelopmentDashboard')
        details = chunk('DetailsPanel')
        if 'transactions-context.json' not in dashboard or 'registered_sales' not in dashboard:
            raise ValueError('Deployed dashboard does not include the transaction statistics feature')
        if 'Ownership and registered acts' not in details or 'portal.registryagency.bg/home-pr' not in details:
            raise ValueError('Deployed details do not include ownership-source guidance')
        styles = re.findall(r'<link\b[^>]*\bhref=[\"\x27]([^\"\x27]+\.css)[\"\x27]', entry_html, re.I)
        styles = [read(asset_name(name), MAX_ASSET_BYTES) for name in styles if name.startswith(('/assets/', 'assets/'))]
        if not any('.leaflet-tooltip.parcel-fallback-tooltip' in css and 'overflow-wrap:anywhere' in css for css in styles):
            raise ValueError('Deployed stylesheet does not include the tooltip wrapping fix')
        payload = read_remote(ftp, f'{REMOTE_ROOT}/data/transactions-context.json', MAX_TRANSACTIONS_BYTES)
        data = validate_transactions(payload)
        report['files']['data/transactions-context.json'] = {'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
        report['transactions'] = {'coverage': data['coverage'], 'latest_period': data['series'][-1]['period'], 'latest_sales': data['series'][-1]['sales'], 'retrieved_at': data['retrieved_at']}
        report['features'] = {'registered_sales_dashboard': True, 'ownership_source_guidance': True, 'tooltip_wrapping_fix': True}
        report['status'] = 'verified'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
