#!/usr/bin/env python3
"""Publish complete official parcel boundary snapshots over verified FTPS."""
from __future__ import annotations

import argparse
import io
import json
import os
import posixpath
import re
import ssl
from ftplib import FTP_TLS, error_perm
from pathlib import Path
from uuid import uuid4

from build_boundary_snapshot import (
    MAX_MANIFEST_BYTES, MAX_INDEX_BYTES, MAX_SHARD_BYTES,
    check_manifest, validate_publish_tree, digest, file_digest,
    json_bytes, read_json, write_new,
)
from deploy_site_ftps import read_remote

PRIVATE = '/htdocs/private'
ACTIVE = f'{PRIVATE}/boundaries-active.json'
SNAPSHOTS = f'{PRIVATE}/boundary-snapshots'
MAX_STATE_BYTES = MAX_MANIFEST_BYTES * 4
MAX_HOST_FILE_BYTES = 10_000_000


def pointer(ftp: FTP_TLS) -> bytes | None:
    names = {posixpath.basename(name.rstrip('/')) for name in ftp.nlst(PRIVATE)}
    if 'boundaries-active.json' not in names:
        return None
    raw = read_remote(ftp, ACTIVE, MAX_MANIFEST_BYTES)
    check_manifest(json.loads(raw.decode('utf-8')))
    return raw


def assert_pointer(ftp: FTP_TLS, expected: bytes | None) -> None:
    if pointer(ftp) != expected:
        raise ValueError('Hosted boundary pointer changed since fetch; publication stopped')


def previous_state(path: Path) -> tuple[bytes | None, dict | None]:
    state = read_json(path, MAX_STATE_BYTES)
    if not isinstance(state, dict) or state.get('version') != 1 or state.get('remote') != ACTIVE or type(state.get('present')) is not bool:
        raise ValueError('Invalid previous boundary pointer envelope')
    if not state['present']:
        if state.get('raw_manifest') is not None or state.get('manifest') is not None or state.get('sha256') is not None or state.get('bytes') != 0:
            raise ValueError('Absent boundary state has unexpected evidence')
        return None, None
    raw = state.get('raw_manifest')
    if not isinstance(raw, str):
        raise ValueError('Previous boundary state lacks original bytes')
    payload = raw.encode('utf-8')
    if len(payload) > MAX_MANIFEST_BYTES or state.get('bytes') != len(payload) or state.get('sha256') != digest(payload):
        raise ValueError('Previous boundary state failed byte/hash validation')
    manifest = check_manifest(json.loads(raw))
    if state.get('manifest') != manifest:
        raise ValueError('Previous parsed boundary pointer differs from its original bytes')
    return payload, manifest


def continuity(previous: dict | None, candidate: dict) -> None:
    if previous is None:
        return
    old_sources = previous['sources']
    new_sources = candidate['sources']
    if [source['source_url'] for source in old_sources] != [source['source_url'] for source in new_sources]:
        raise ValueError('Official boundary catalogue changed; review the source mapping')
    if candidate['captured_at'] < previous['captured_at'] or candidate['parcel_count'] < previous['parcel_count'] * 0.8:
        raise ValueError('Boundary capture would regress its date or lose over 20% of coverage')
    for old, new in zip(old_sources, new_sources):
        if new['captured_at'] < old['captured_at'] or (old['record_count'] >= 50 and new['record_count'] < old['record_count'] * 0.8):
            raise ValueError('One official boundary district regresses its capture or coverage')


def put_verified(ftp: FTP_TLS, remote: str, payload: bytes, limit: int) -> None:
    if len(payload) > min(limit, MAX_HOST_FILE_BYTES):
        raise ValueError('Boundary upload exceeds the hosting file limit')
    ftp.storbinary(f'STOR {remote}', io.BytesIO(payload))
    actual = read_remote(ftp, remote, limit)
    if len(actual) != len(payload) or digest(actual) != digest(payload):
        raise ValueError('Boundary upload failed its byte count or SHA-256 verification')


def activate(ftp: FTP_TLS, payload: bytes, previous: bytes | None) -> None:
    temporary = f'{PRIVATE}/boundaries-active.{uuid4().hex}.pending.json'
    pending = True
    try:
        put_verified(ftp, temporary, payload, MAX_MANIFEST_BYTES)
        assert_pointer(ftp, previous)
        if previous is not None:
            put_verified(ftp, f'{PRIVATE}/boundaries-active.previous.json', previous, MAX_MANIFEST_BYTES)
        assert_pointer(ftp, previous)
        ftp.rename(temporary, ACTIVE)
        pending = False
        if read_remote(ftp, ACTIVE, MAX_MANIFEST_BYTES) != payload:
            if previous is None:
                ftp.delete(ACTIVE)
            else:
                restore = f'{PRIVATE}/boundaries-active.{uuid4().hex}.restore.json'
                put_verified(ftp, restore, previous, MAX_MANIFEST_BYTES)
                ftp.rename(restore, ACTIVE)
            raise ValueError('Boundary activation failed; the previous state was restored')
    finally:
        if pending:
            try:
                ftp.delete(temporary)
            except error_perm:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('fetch', 'validate', 'publish'))
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--previous', type=Path)
    args = parser.parse_args()
    if args.operation == 'fetch' and args.output is None:
        parser.error('fetch requires --output')
    if args.operation != 'fetch' and args.input is None:
        parser.error('validate/publish require --input')
    if args.operation == 'publish' and args.previous is None:
        parser.error('publish requires --previous')
    candidate = validate_publish_tree(args.input) if args.operation != 'fetch' else None
    previous, earlier = previous_state(args.previous) if args.previous is not None else (None, None)
    if candidate is not None:
        continuity(earlier, candidate)
        descriptors = [candidate['index'], candidate['ambiguous_index'], *candidate['shards']]
        if any(item['bytes'] > MAX_HOST_FILE_BYTES for item in descriptors):
            raise ValueError('Prepared boundary file exceeds the hosting file limit')
    if args.operation == 'validate':
        print(f"Validated {candidate['parcel_count']:,} complete published parcel polygons")
        return
    credentials = {key: os.environ.get(key, '') for key in ('FTP_HOST', 'FTP_USER', 'FTP_PASSWORD')}
    if not all(credentials.values()) or any('\r' in value or '\n' in value for value in credentials.values()):
        raise ValueError('Valid FTP_HOST, FTP_USER and FTP_PASSWORD are required')
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with FTP_TLS(context=context, timeout=90) as ftp:
        ftp.connect(credentials['FTP_HOST'], 21)
        ftp.login(credentials['FTP_USER'], credentials['FTP_PASSWORD'])
        ftp.prot_p()
        protection = read_remote(ftp, f'{PRIVATE}/.htaccess', 16 * 1024).decode('utf-8')
        if not any(re.fullmatch(r'(?:deny\s+from\s+all|require\s+all\s+denied)', line.strip(), re.I) for line in protection.splitlines()):
            raise ValueError('Private hosting directory lacks HTTP access protection')
        if args.operation == 'fetch':
            raw = pointer(ftp)
            state = {'version': 1, 'remote': ACTIVE, 'present': raw is not None,
                     'bytes': len(raw) if raw is not None else 0,
                     'sha256': digest(raw) if raw is not None else None,
                     'manifest': check_manifest(json.loads(raw)) if raw is not None else None,
                     'raw_manifest': raw.decode('utf-8') if raw is not None else None}
            payload = json_bytes(state)
            if len(payload) > MAX_STATE_BYTES:
                raise ValueError('Boundary pointer envelope exceeds its limit')
            write_new(args.output, payload)
            print('Fetched verified boundary pointer' if raw is not None else 'Confirmed no boundary snapshot is active')
            return
        assert_pointer(ftp, previous)
        original = ftp.pwd()
        try:
            try:
                ftp.cwd(SNAPSHOTS)
            except error_perm:
                ftp.mkd(SNAPSHOTS)
                ftp.cwd(SNAPSHOTS)
        finally:
            ftp.cwd(original)
        directory = f"{SNAPSHOTS}/{candidate['snapshot_id']}"
        ftp.mkd(directory)
        for position, descriptor in enumerate(descriptors, 1):
            path = args.input / descriptor['file']
            if path.is_symlink() or not path.is_file() or path.stat().st_size != descriptor['bytes'] or file_digest(path) != descriptor['sha256']:
                raise ValueError('Prepared boundary file changed before upload')
            payload = path.read_bytes()
            if len(payload) != descriptor['bytes'] or digest(payload) != descriptor['sha256']:
                raise ValueError('Prepared boundary file changed while reading')
            limit = MAX_INDEX_BYTES if descriptor['file'].endswith('.tsv') else MAX_SHARD_BYTES
            put_verified(ftp, f"{directory}/{descriptor['file']}", payload, limit)
            if position % 20 == 0 or position == len(descriptors):
                print(f'Uploaded and verified {position}/{len(descriptors)} immutable boundary files', flush=True)
        payload = (args.input / 'manifest.json').read_bytes()
        if len(payload) > MAX_MANIFEST_BYTES or check_manifest(json.loads(payload)) != candidate:
            raise ValueError('Boundary manifest changed before activation')
        put_verified(ftp, f'{directory}/manifest.json', payload, MAX_MANIFEST_BYTES)
        activate(ftp, payload, previous)
        print(f"Published {candidate['parcel_count']:,} official parcel boundaries; previous snapshots retained")


if __name__ == '__main__':
    main()
