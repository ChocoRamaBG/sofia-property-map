#!/usr/bin/env python3
"""Verify and publish private asking-price market snapshots over explicit FTPS.

Only /htdocs/private/market-* paths are written. Official registry/cadastral
snapshots and MySQL are separate. Current plus previous pointers and the latest
seven complete market snapshots are retained. Removal requires a validated
allowlisted immutable tree; incomplete/unexpected directories are left intact.
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
from imot_market_format import (
    HEX32, MAX_MANIFEST_BYTES, MAX_SHARD_BYTES, MAX_STATE_BYTES, MAX_STATE_COMPRESSED_BYTES,
    MAX_SUMMARY_BYTES, VERSION, digest, json_bytes, timestamp,
    read_state_payload, validate_manifest, validate_snapshot,
)

PRIVATE = "/htdocs/private"
ACTIVE = PRIVATE + "/market-active.json"
PREVIOUS = PRIVATE + "/market-active.previous.json"
SNAPSHOTS = PRIVATE + "/market-snapshots"
MAX_POINTER_BYTES = 4096
MAX_FETCH_META_BYTES = 16 * 1024


def state_file_limit(descriptor):
    return MAX_STATE_COMPRESSED_BYTES if descriptor.get("path") == "state.json.gz" else MAX_STATE_BYTES


def validate_pointer(payload):
    if not 1 <= len(payload) <= MAX_POINTER_BYTES:
        raise ValueError("Invalid market pointer size")
    pointer = json.loads(payload)
    identifier = pointer.get("snapshot_id")
    if pointer.get("version") != VERSION or not HEX32.fullmatch(str(identifier)) or pointer.get("manifest_path") != f"market-snapshots/{identifier}/manifest.json" or not re.fullmatch(r"[a-f0-9]{64}", str(pointer.get("manifest_sha256"))):
        raise ValueError("Invalid market pointer identity/path/hash")
    return pointer


def names(ftp, directory):
    result = ftp.nlst(directory)
    return {posixpath.basename(item.rstrip("/")) for item in result if posixpath.basename(item.rstrip("/")) not in {".", ".."}}


def pointer(ftp, remote=ACTIVE):
    if posixpath.basename(remote) not in names(ftp, PRIVATE):
        return None
    raw = read_remote(ftp, remote, MAX_POINTER_BYTES)
    validate_pointer(raw)
    return raw


def protected(ftp):
    content = read_remote(ftp, PRIVATE + "/.htaccess", 16 * 1024).decode("utf-8")
    if not any(re.fullmatch(r"(?:deny\s+from\s+all|require\s+all\s+denied)", line.strip(), re.I) for line in content.splitlines()):
        raise ValueError("Private directory does not deny public HTTP downloads")


def manifest_for(ftp, pointer_payload):
    ptr = validate_pointer(pointer_payload)
    raw = read_remote(ftp, PRIVATE + "/" + ptr["manifest_path"], MAX_MANIFEST_BYTES)
    if digest(raw) != ptr["manifest_sha256"]:
        raise ValueError("Hosted market manifest differs from its pointer hash")
    manifest = json.loads(raw)
    validate_manifest(manifest)
    if manifest["snapshot_id"] != ptr["snapshot_id"]:
        raise ValueError("Hosted manifest has another snapshot identity")
    if manifest["summary_file"]["path"] != "summary.json" or manifest["state_file"]["path"] not in {"state.json", "state.json.gz"}:
        raise ValueError("Hosted market tree uses unexpected summary/state filenames")
    return ptr, manifest


def descriptor_payload(ftp, identifier, descriptor, limit):
    raw = read_remote(ftp, f"{SNAPSHOTS}/{identifier}/{descriptor['path']}", limit)
    if len(raw) != descriptor["bytes"] or digest(raw) != descriptor["sha256"]:
        raise ValueError("Hosted market file failed its byte count or SHA-256 check")
    content = json.loads(read_state_payload(raw, descriptor)) if descriptor["path"] in {"state.json", "state.json.gz"} else json.loads(raw)
    if content.get("snapshot_id") != identifier:
        raise ValueError("Hosted market file has another snapshot identity")
    return raw


def put(ftp, remote, raw, limit):
    ftp.storbinary("STOR " + remote, io.BytesIO(raw))
    returned = read_remote(ftp, remote, limit)
    if returned != raw or digest(returned) != digest(raw):
        raise ValueError("Uploaded market file failed readback verification")


def local_state(path):
    if path.stat().st_size > MAX_FETCH_META_BYTES:
        raise ValueError("Fetched pointer envelope exceeds its bound")
    meta = json.loads(path.read_bytes())
    if meta.get("version") != 1 or meta.get("remote") != ACTIVE or type(meta.get("present")) is not bool:
        raise ValueError("Invalid fetched pointer metadata")
    raw = meta.get("raw_pointer")
    if not meta["present"]:
        if raw is not None or meta.get("bytes") != 0 or meta.get("sha256") is not None:
            raise ValueError("Absent pointer metadata has unexpected evidence")
        return None, meta
    if not isinstance(raw, str):
        raise ValueError("Fetched pointer lacks its original bytes")
    payload = raw.encode("utf-8")
    validate_pointer(payload)
    if len(payload) != meta.get("bytes") or digest(payload) != meta.get("sha256"):
        raise ValueError("Fetched market pointer metadata failed verification")
    return payload, meta


def assert_current(ftp, expected):
    if pointer(ftp) != expected:
        raise ValueError("Hosted market pointer changed after fetch; candidate not activated")


def activate(ftp, candidate, previous):
    assert_current(ftp, previous)
    if previous is not None:
        pending_backup = f"{PRIVATE}/market-active.previous.{uuid4().hex}.pending"
        put(ftp, pending_backup, previous, MAX_POINTER_BYTES)
        ftp.rename(pending_backup, PREVIOUS)
        if pointer(ftp, PREVIOUS) != previous:
            raise ValueError("Previous market pointer backup failed verification")
    pending = f"{PRIVATE}/market-active.{uuid4().hex}.pending"
    put(ftp, pending, candidate, MAX_POINTER_BYTES)
    assert_current(ftp, previous)
    ftp.rename(pending, ACTIVE)
    if pointer(ftp) != candidate:
        raise ValueError("Activated market pointer failed verification")


def continuity(previous, candidate):
    if previous is None or previous.get("mode") != "daily":
        return
    if candidate["mode"] != "daily":
        raise ValueError("Historical bootstrap cannot replace an active daily capture")
    if candidate["counts"]["listing_count"] < previous["counts"]["listing_count"] * .8:
        raise ValueError("Daily capture loses more than 20% of prior listing coverage; review required")
    old_scope = previous.get("capture", {}).get("scope", {})
    new_scope = candidate.get("capture", {}).get("scope", {})
    if old_scope != new_scope:
        raise ValueError("Daily scope changed; review before publishing a new baseline")


def prune(ftp, active_raw, keep=7):
    """Delete only old complete validated market trees after guarded activation."""
    assert_current(ftp, active_raw)
    protected(ftp)
    current_ptr, _ = manifest_for(ftp, active_raw)
    previous_raw = pointer(ftp, PREVIOUS)
    previous_ptr, _ = manifest_for(ftp, previous_raw) if previous_raw else (None, None)
    retained = {current_ptr["snapshot_id"]}
    if previous_ptr:
        retained.add(previous_ptr["snapshot_id"])
    directories = names(ftp, SNAPSHOTS)
    if any(not HEX32.fullmatch(name) for name in directories):
        raise ValueError("Unexpected market snapshot directory; retention stopped")
    completed = []
    for identifier in sorted(directories):
        members = names(ftp, f"{SNAPSHOTS}/{identifier}")
        if "manifest.json" not in members:
            # Inactive upload leftovers have no complete manifest and cannot
            # be treated as a verified immutable dataset or removed here.
            continue
        raw = read_remote(ftp, f"{SNAPSHOTS}/{identifier}/manifest.json", MAX_MANIFEST_BYTES)
        manifest = json.loads(raw)
        validate_manifest(manifest)
        if manifest["snapshot_id"] != identifier or manifest["summary_file"]["path"] != "summary.json" or manifest["state_file"]["path"] not in {"state.json", "state.json.gz"}:
            raise ValueError("Unexpected immutable market tree identity")
        captured = timestamp(manifest.get("captured_at"))
        if captured is None:
            raise ValueError("Market retention lacks a valid capture timestamp")
        completed.append((captured, identifier, manifest, members))
    completed.sort(reverse=True, key=lambda entry: (entry[0], entry[1]))
    retained.update(entry[1] for entry in completed[:keep])
    removed = 0
    for _, identifier, manifest, members in completed:
        if identifier in retained:
            continue
        descriptors = [(manifest["summary_file"], MAX_SUMMARY_BYTES), (manifest["state_file"], state_file_limit(manifest["state_file"])), *[(desc, MAX_SHARD_BYTES) for desc in manifest["listing_shards"]]]
        expected = {"manifest.json", *(desc["path"] for desc, _ in descriptors)}
        if members != expected:
            raise ValueError("Unexpected contents in old market tree; retention stopped")
        for descriptor, limit in descriptors:
            descriptor_payload(ftp, identifier, descriptor, limit)
        assert_current(ftp, active_raw)
        if pointer(ftp, PREVIOUS) != previous_raw:
            raise ValueError("Previous market pointer changed during retention")
        # Absolute targets are derived only from checked IDs and descriptor
        # basenames, and stay inside this market-only immutable directory.
        for filename in sorted(expected - {"manifest.json"}):
            if "/" in filename or filename in {".", ".."}:
                raise ValueError("Unsafe market retention filename")
            ftp.delete(f"{SNAPSHOTS}/{identifier}/{filename}")
        ftp.delete(f"{SNAPSHOTS}/{identifier}/manifest.json")
        ftp.rmd(f"{SNAPSHOTS}/{identifier}")
        removed += 1
    return removed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("fetch", "validate", "publish"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--state-output", type=Path)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    if args.operation == "fetch" and (args.output is None or args.state_output is None):
        parser.error("fetch requires --output and --state-output")
    if args.operation != "fetch" and args.input is None:
        parser.error("validate/publish require --input")
    if args.operation == "publish" and args.previous is None:
        parser.error("publish requires the --previous fetched pointer metadata")
    candidate = validate_snapshot(args.input) if args.operation != "fetch" else None
    if candidate and (candidate[1]["summary_file"]["path"] != "summary.json" or candidate[1]["state_file"]["path"] not in {"state.json", "state.json.gz"}):
        raise ValueError("Unexpected candidate summary/state file names")
    if args.operation == "validate":
        print(f"Validated complete market files and {candidate[1]['counts']['listing_count']} stable source IDs")
        return
    credentials = [os.environ.get(name) for name in ("FTP_HOST", "FTP_USER", "FTP_PASSWORD")]
    if any(not value for value in credentials):
        raise ValueError("FTP_HOST, FTP_USER and FTP_PASSWORD secrets are required")
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with FTP_TLS(context=context, timeout=90) as ftp:
        ftp.connect(credentials[0], 21)
        ftp.login(credentials[1], credentials[2])
        ftp.prot_p()
        protected(ftp)
        if args.operation == "fetch":
            if args.output.exists() or args.state_output.exists():
                raise ValueError("Fetch output exists; use fresh output files")
            raw = pointer(ftp)
            state_payload = json_bytes({"version": VERSION, "mode": "none", "listings": {}})
            if raw:
                ptr, manifest = manifest_for(ftp, raw)
                encoded_state = descriptor_payload(ftp, ptr["snapshot_id"], manifest["state_file"], state_file_limit(manifest["state_file"]))
                state_payload = read_state_payload(encoded_state, manifest["state_file"])
            meta = {"version": 1, "remote": ACTIVE, "present": raw is not None, "raw_pointer": raw.decode("utf-8") if raw else None, "bytes": len(raw) if raw else 0, "sha256": digest(raw) if raw else None, "state_sha256": digest(state_payload)}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.state_output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(json_bytes(meta))
            args.state_output.write_bytes(state_payload)
            print("Fetched verified previous market state" if raw else "Confirmed no market snapshot active; first daily capture establishes its baseline")
            return
        previous_raw, _ = local_state(args.previous)
        previous_manifest = manifest_for(ftp, previous_raw)[1] if previous_raw else None
        ptr, manifest = candidate
        continuity(previous_manifest, manifest)
        assert_current(ftp, previous_raw)
        try:
            ftp.cwd(SNAPSHOTS)
        except error_perm:
            ftp.mkd(SNAPSHOTS)
        ftp.cwd(PRIVATE)
        directory = f"{SNAPSHOTS}/{ptr['snapshot_id']}"
        ftp.mkd(directory)  # Refuse an existing immutable tree, including leftovers.
        local = args.input / "market-snapshots" / ptr["snapshot_id"]
        descriptors = [(manifest["summary_file"], MAX_SUMMARY_BYTES), (manifest["state_file"], state_file_limit(manifest["state_file"])), *[(desc, MAX_SHARD_BYTES) for desc in manifest["listing_shards"]]]
        for descriptor, limit in descriptors:
            path = local / descriptor["path"]
            if path.is_symlink():
                raise ValueError("Candidate market file is a filesystem link")
            payload = path.read_bytes()
            if len(payload) != descriptor["bytes"] or digest(payload) != descriptor["sha256"]:
                raise ValueError("Local market file changed during publication")
            put(ftp, directory + "/" + descriptor["path"], payload, limit)
        manifest_payload = (local / "manifest.json").read_bytes()
        if digest(manifest_payload) != ptr["manifest_sha256"]:
            raise ValueError("Local market manifest changed during publication")
        put(ftp, directory + "/manifest.json", manifest_payload, MAX_MANIFEST_BYTES)
        active_payload = (args.input / "market-active.json").read_bytes()
        if validate_pointer(active_payload) != ptr:
            raise ValueError("Local market pointer changed during publication")
        activate(ftp, active_payload, previous_raw)
        print(f"Published verified {manifest['mode']} market snapshot: {manifest['counts']['listing_count']} listings")
        removed = prune(ftp, active_payload)
        print(f"Market retention completed: {removed} older verified unreferenced snapshots removed; latest seven plus current/previous retained")


if __name__ == "__main__":
    main()
