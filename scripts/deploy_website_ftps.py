#!/usr/bin/env python3
"""Publish the reviewed read-only development API, then the compiled website.

Only the explicit PHP source files below are allowed. Existing API versions are
retained as a private local backup before atomic verified replacements. No
configuration, datasets or host protection files are uploaded.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
from ftplib import FTP_TLS, error_perm
from uuid import uuid4

from deploy_site_ftps import MAX_FILE_BYTES, REMOTE_ROOT, read_local, read_remote, verify_remote

API_NAMES = ('development-data.php', 'boundary-data.php', 'business-data.php', 'market.php', 'api.php')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public', type=Path, default=Path('public'))
    parser.add_argument('--input', type=Path, default=Path('dist'))
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--api-only', action='store_true', help='Stage backward-compatible PHP readers before a dataset format migration')
    args = parser.parse_args()
    root = args.public.resolve()
    api_plan = [(name, read_local(root / name, root)) for name in API_NAMES]
    for name, payload in api_plan:
        if not payload.startswith(b'<?php') or b'\x00' in payload:
            raise ValueError(f'Invalid PHP source: {name}')
    credentials = {key: os.environ.get(key, '') for key in ('FTP_HOST', 'FTP_USER', 'FTP_PASSWORD')}
    if not all(credentials.values()) or any('\n' in value or '\r' in value for value in credentials.values()):
        raise ValueError('Valid FTP_HOST, FTP_USER and FTP_PASSWORD are required')
    if args.backup.exists():
        raise ValueError('Backup directory must be new')
    args.backup.mkdir(parents=True)
    with FTP_TLS(context=ssl.create_default_context(), timeout=60) as ftp:
        ftp.connect(credentials['FTP_HOST'], 21)
        ftp.login(credentials['FTP_USER'], credentials['FTP_PASSWORD'])
        ftp.prot_p()
        # All prior versions are saved before the first hosting write.
        for name, _ in api_plan:
            try:
                previous = read_remote(ftp, f'{REMOTE_ROOT}/{name}', MAX_FILE_BYTES)
            except error_perm as error:
                if name not in ('development-data.php', 'boundary-data.php', 'business-data.php') or not str(error).startswith('550'):
                    raise
            else:
                (args.backup / name).write_bytes(previous)
        for name, payload in api_plan:
            remote = f'{REMOTE_ROOT}/{name}'
            temporary = f'{remote}.{uuid4().hex}.pending'
            ftp.storbinary(f'STOR {temporary}', io.BytesIO(payload))
            verify_remote(ftp, temporary, payload)
            ftp.rename(temporary, remote)
            verify_remote(ftp, remote, payload)
            print(f'Published {name}: {len(payload)} bytes; SHA-256 verified', flush=True)
    if not args.api_only:
        subprocess.run([sys.executable, str(Path(__file__).with_name('deploy_site_ftps.py')), '--input', str(args.input)], check=True)


if __name__ == '__main__':
    main()
