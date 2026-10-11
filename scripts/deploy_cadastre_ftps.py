#!/usr/bin/env python3
"""Publish complete private cadastral snapshots through verified explicit FTPS.

Environment-only credentials, immutable directories, verified hashes and atomic
pointer replacement mirror the register publisher. No SQL or public writes.
"""

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

from deploy_registry_ftps import read_remote
from refresh_cadastre import (
    MAX_MANIFEST_BYTES, MAX_INDEX_BYTES, MAX_SHARD_BYTES,
    check_manifest, digest, file_digest, json_bytes, read_json,
    validate_publish_tree, write_new,
)

PRIVATE = "/htdocs/private"
ACTIVE = f"{PRIVATE}/cadastre-active.json"
SNAPSHOTS = f"{PRIVATE}/cadastre-snapshots"


def pointer(ftp: FTP_TLS) -> bytes | None:
    names = {posixpath.basename(name.rstrip("/")) for name in ftp.nlst(PRIVATE)}
    if "cadastre-active.json" not in names:
        return None
    payload = read_remote(ftp, ACTIVE, MAX_MANIFEST_BYTES)
    check_manifest(json.loads(payload.decode("utf-8")))
    return payload


def assert_pointer(ftp: FTP_TLS, expected: bytes | None) -> None:
    current = pointer(ftp)
    if current != expected:
        raise ValueError("Hosted cadastral pointer changed since fetch; refusing publication")


def previous_state(path: Path) -> tuple[bytes | None, dict | None]:
    state = read_json(path, MAX_MANIFEST_BYTES * 2)
    if not isinstance(state, dict) or type(state.get("version")) is not int or state["version"] != 1 or state.get("remote") != ACTIVE or type(state.get("present")) is not bool:
        raise ValueError("Invalid previously fetched cadastral pointer state")
    if not state["present"]:
        if state.get("manifest") is not None or state.get("sha256") is not None or state.get("bytes") != 0:
            raise ValueError("Absent pointer state has unexpected evidence")
        return None, None
    raw = state.get("raw_manifest")
    if not isinstance(raw, str):
        raise ValueError("Previous pointer state lacks its exact original bytes")
    payload = raw.encode("utf-8")
    manifest = check_manifest(json.loads(raw))
    if state.get("bytes") != len(payload) or state.get("sha256") != digest(payload) or state.get("manifest") != manifest:
        raise ValueError("Previously fetched cadastral state failed its hash check")
    return payload, manifest


def assert_capture_continuity(previous: dict | None, candidate: dict) -> None:
    if previous is None:
        return
    if [source["source_url"] for source in previous["sources"]] != [source["source_url"] for source in candidate["sources"]]:
        raise ValueError("District download catalogue changed; review the new source mapping")
    if candidate["parcel_count"] < previous["parcel_count"] * 0.8:
        raise ValueError("New cadastral capture loses more than 20% of earlier parcel coverage")
    for old, new in zip(previous["sources"], candidate["sources"]):
        if old["record_count"] >= 50 and new["record_count"] < old["record_count"] * 0.8:
            raise ValueError("One district loses more than 20% of its earlier parcel coverage")


def ensure_snapshot_root(ftp: FTP_TLS) -> None:
    original = ftp.pwd()
    try:
        try:
            ftp.cwd(SNAPSHOTS)
        except error_perm:
            ftp.mkd(SNAPSHOTS)
            ftp.cwd(SNAPSHOTS)
    finally:
        ftp.cwd(original)


def put_verified(ftp: FTP_TLS, remote: str, payload: bytes, limit: int) -> None:
    ftp.storbinary(f"STOR {remote}", io.BytesIO(payload))
    returned = read_remote(ftp, remote, limit)
    if len(returned) != len(payload) or digest(returned) != digest(payload):
        raise ValueError("Uploaded cadastral file failed its byte count or SHA-256 check")


def activate(ftp: FTP_TLS, candidate: bytes, previous: bytes | None) -> None:
    temporary = f"{PRIVATE}/cadastre-active.{uuid4().hex}.pending.json"
    pending = False
    try:
        # Mark the temporary name before uploading so an interrupted STOR is
        # cleaned up without affecting any active or immutable snapshot file.
        pending = True
        put_verified(ftp, temporary, candidate, MAX_MANIFEST_BYTES)
        assert_pointer(ftp, previous)
        if previous is not None:
            put_verified(ftp, f"{PRIVATE}/cadastre-active.previous.json", previous, MAX_MANIFEST_BYTES)
        assert_pointer(ftp, previous)
        ftp.rename(temporary, ACTIVE)
        pending = False
        returned = read_remote(ftp, ACTIVE, MAX_MANIFEST_BYTES)
        if returned != candidate:
            if previous is None:
                ftp.delete(ACTIVE)
            else:
                restore = f"{PRIVATE}/cadastre-active.{uuid4().hex}.restore.json"
                put_verified(ftp, restore, previous, MAX_MANIFEST_BYTES)
                ftp.rename(restore, ACTIVE)
            raise ValueError("Cadastral activation failed verification; restored the previous state")
    finally:
        if pending:
            try:
                ftp.delete(temporary)
            except error_perm:
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("fetch", "publish", "validate"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    if args.operation == "fetch" and args.output is None:
        parser.error("fetch requires --output")
    if args.operation in ("publish", "validate") and args.input is None:
        parser.error("publish/validate require --input")
    if args.operation == "publish" and args.previous is None:
        parser.error("publish requires --previous")
    candidate = validate_publish_tree(args.input) if args.operation != "fetch" else None
    if args.operation == "validate":
        if args.previous is not None:
            _, earlier = previous_state(args.previous)
            assert_capture_continuity(earlier, candidate)
        print(f"Validated {candidate['parcel_count']:,} exact cadastral area references and all immutable detail shards")
        return
    previous, previous_manifest = previous_state(args.previous) if args.operation == "publish" else (None, None)
    if candidate is not None:
        assert_capture_continuity(previous_manifest, candidate)
    credentials = {name: os.environ.get(name) for name in ("FTP_HOST", "FTP_USER", "FTP_PASSWORD")}
    if any(not value for value in credentials.values()):
        raise ValueError("FTP_HOST, FTP_USER and FTP_PASSWORD secrets are required")
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with FTP_TLS(context=context, timeout=60) as ftp:
        ftp.connect(credentials["FTP_HOST"], 21)
        ftp.login(credentials["FTP_USER"], credentials["FTP_PASSWORD"])
        ftp.prot_p()
        protection = read_remote(ftp, f"{PRIVATE}/.htaccess", 16 * 1024).decode("utf-8")
        if not any(re.fullmatch(r"(?:deny\s+from\s+all|require\s+all\s+denied)", line.strip(), re.IGNORECASE) for line in protection.splitlines()):
            raise ValueError("Private directory lacks HTTP access protection")
        if args.operation == "fetch":
            raw = pointer(ftp)
            manifest = check_manifest(json.loads(raw.decode("utf-8"))) if raw is not None else None
            state = {"version": 1, "remote": ACTIVE, "present": raw is not None, "bytes": len(raw) if raw is not None else 0, "sha256": digest(raw) if raw is not None else None, "manifest": manifest, "raw_manifest": raw.decode("utf-8") if raw is not None else None}
            write_new(args.output, json_bytes(state))
            print("Fetched verified cadastral pointer" if raw is not None else "Confirmed no cadastral snapshot is active yet")
            return
        assert_pointer(ftp, previous)
        ensure_snapshot_root(ftp)
        directory = f"{SNAPSHOTS}/{candidate['snapshot_id']}"
        # Never overwrite an immutable directory, even after a failed upload.
        ftp.mkd(directory)
        local = args.input / "cadastre-snapshots" / candidate["snapshot_id"]
        descriptors = [candidate["index"], *candidate["records"]]
        if candidate["conflicts"] is not None:
            descriptors.append(candidate["conflicts"])
        for descriptor in descriptors:
            path = local / descriptor["file"]
            if path.stat().st_size != descriptor["bytes"] or file_digest(path) != descriptor["sha256"]:
                raise ValueError("Local cadastral snapshot changed during publication")
            payload = path.read_bytes()
            if len(payload) != descriptor["bytes"] or digest(payload) != descriptor["sha256"]:
                raise ValueError("Local cadastral file changed while reading publication bytes")
            put_verified(ftp, f"{directory}/{descriptor['file']}", payload, MAX_INDEX_BYTES if descriptor["file"] == "index.tsv" else MAX_SHARD_BYTES)
        manifest_path = args.input / "cadastre-active.json"
        manifest_payload = manifest_path.read_bytes()
        if len(manifest_payload) > MAX_MANIFEST_BYTES or check_manifest(json.loads(manifest_payload.decode("utf-8"))) != candidate:
            raise ValueError("Local cadastral manifest changed during publication")
        activate(ftp, manifest_payload, previous)
        print(f"Published complete cadastral snapshot: {candidate['parcel_count']:,} parcels from 24 official exports; earlier immutable files retained privately")


if __name__ == "__main__":
    main()
