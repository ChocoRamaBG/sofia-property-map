#!/usr/bin/env python3
"""Fetch or publish only the private register dataset over verified FTPS.

No public HTTP request, SQL import URL, or remote database connection is used.
Credentials are supplied in environment variables, never printed or persisted.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import posixpath
import ssl
from ftplib import FTP_TLS
from pathlib import Path
from uuid import uuid4

from build_registry_snapshot import MAX_BYTES, validate_snapshot


def read_remote(ftp: FTP_TLS, path: str, limit: int = MAX_BYTES) -> bytes:
    output = io.BytesIO()

    def append(chunk):
        if output.tell() + len(chunk) > limit:
            raise ValueError("Remote dataset exceeds the allowed file size")
        output.write(chunk)

    ftp.retrbinary(f"RETR {path}", append)
    return output.getvalue()


def check_payload(payload: bytes) -> dict:
    if len(payload) > MAX_BYTES:
        raise ValueError("Dataset exceeds 10 MiB")
    snapshot = json.loads(payload.decode("utf-8"))
    validate_snapshot(snapshot)
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("fetch", "publish"))
    parser.add_argument("--remote", default="/htdocs/private/registry-data.json")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    if args.remote != "/htdocs/private/registry-data.json":
        parser.error("This deployment is restricted to /htdocs/private/registry-data.json")
    if args.operation == "fetch" and not args.output:
        parser.error("fetch requires --output")
    if args.operation == "publish" and (not args.input or not args.previous):
        parser.error("publish requires --input and --previous")
    credentials = {key: os.environ.get(key) for key in ("FTP_HOST", "FTP_USER", "FTP_PASSWORD")}
    if any(not value for value in credentials.values()):
        raise ValueError("FTP_HOST, FTP_USER, and FTP_PASSWORD secrets are required")

    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with FTP_TLS(context=context, timeout=60) as ftp:
        ftp.connect(credentials["FTP_HOST"], 21)
        ftp.login(credentials["FTP_USER"], credentials["FTP_PASSWORD"])
        ftp.prot_p()
        protection = read_remote(ftp, "/htdocs/private/.htaccess", limit=16 * 1024).decode("utf-8")
        if "deny from all" not in protection.lower() and "require all denied" not in protection.lower():
            raise ValueError("Private directory lacks HTTP access protection")
        current = read_remote(ftp, args.remote)
        previous_snapshot = check_payload(current)
        if args.operation == "fetch":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            pending = args.output.with_suffix(".json.pending")
            pending.write_bytes(current)
            pending.replace(args.output)
            print(f"Fetched {len(previous_snapshot['documents'])} register observations ({len(current):,} bytes) by verified FTPS")
            return

        expected_previous = args.previous.read_bytes()
        if hashlib.sha256(expected_previous).digest() != hashlib.sha256(current).digest():
            raise ValueError("Hosted dataset changed after capture began; refusing to replace it")
        candidate = args.input.read_bytes()
        next_snapshot = check_payload(candidate)
        before = {(item["source_code"], item["document_hash"]) for item in previous_snapshot["documents"]}
        after = {(item["source_code"], item["document_hash"]) for item in next_snapshot["documents"]}
        if not before.issubset(after):
            raise ValueError("Candidate would remove an earlier register observation")

        directory = posixpath.dirname(args.remote)
        temporary = f"{directory}/registry-data.{uuid4().hex}.pending.json"
        backup = f"{directory}/registry-data.previous.json"
        uploaded = False
        try:
            ftp.storbinary(f"STOR {temporary}", io.BytesIO(candidate))
            uploaded = True
            uploaded_bytes = read_remote(ftp, temporary)
            if hashlib.sha256(uploaded_bytes).digest() != hashlib.sha256(candidate).digest():
                raise ValueError("Uploaded candidate failed SHA-256 verification")
            check_payload(uploaded_bytes)
            ftp.storbinary(f"STOR {backup}", io.BytesIO(current))
            if hashlib.sha256(read_remote(ftp, backup)).digest() != hashlib.sha256(current).digest():
                raise ValueError("Previous dataset backup failed verification")
            # RNTO atomically replaces the live file. If the server refuses an
            # overwrite, leave the live dataset untouched and report failure.
            ftp.rename(temporary, args.remote)
            uploaded = False
            published = read_remote(ftp, args.remote)
            if hashlib.sha256(published).digest() != hashlib.sha256(candidate).digest():
                restore = f"{directory}/registry-data.{uuid4().hex}.restore.json"
                ftp.storbinary(f"STOR {restore}", io.BytesIO(current))
                ftp.rename(restore, args.remote)
                raise ValueError("Published bytes differ; restored the previous snapshot")
        finally:
            if uploaded:
                ftp.delete(temporary)
        print(f"Published {len(next_snapshot['documents'])} observations ({len(candidate):,} bytes) by verified FTPS; previous snapshot retained privately")


if __name__ == "__main__":
    main()
