#!/usr/bin/env python3
"""Fetch or publish bounded private register snapshots over verified FTPS.

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
import re
import ssl
from collections import Counter
from datetime import datetime
from ftplib import FTP_TLS, error_perm
from pathlib import Path
from uuid import uuid4

from build_registry_snapshot import (
    CADASTRAL_ID, CORE_CODES, MAX_BYTES, MAX_DOCUMENTS, MAX_INDEX_BYTES,
    MAX_LOCAL_BYTES, MAX_MANIFEST_BYTES, MAX_SHARD_BYTES, SOURCES,
    json_bytes, validate_snapshot, write_atomic,
)

PRIVATE = "/htdocs/private"
V1_REMOTE = f"{PRIVATE}/registry-data.json"
ACTIVE_REMOTE = f"{PRIVATE}/registry-active.json"
SNAPSHOT_ROOT = f"{PRIVATE}/registry-snapshots"
HEX64 = re.compile(r"[a-f0-9]{64}")
HEX32 = re.compile(r"[a-f0-9]{32}")
SHARD_NAME = re.compile(r"documents-[0-9]{3}\.jsonl")


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def integer(value, minimum: int, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum


def read_remote(ftp: FTP_TLS, path: str, limit: int = MAX_BYTES) -> bytes:
    output = io.BytesIO()

    def append(chunk):
        if output.tell() + len(chunk) > limit:
            raise ValueError("Remote file exceeds its allowed byte limit")
        output.write(chunk)

    ftp.retrbinary(f"RETR {path}", append)
    return output.getvalue()


def read_local(path: Path, limit: int) -> bytes:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > limit:
        raise ValueError("Local snapshot file is absent, linked, or exceeds its byte limit")
    return path.read_bytes()


def check_payload(payload: bytes, limit: int = MAX_BYTES) -> dict:
    if len(payload) > limit:
        raise ValueError("Version-1 dataset exceeds its allowed byte limit")
    snapshot = json.loads(payload.decode("utf-8"))
    if not isinstance(snapshot, dict):
        raise ValueError("Dataset must be a JSON object")
    validate_snapshot(snapshot)
    return snapshot


def completed(value) -> bool:
    return isinstance(value, dict) and value.get("status") == "complete" and isinstance(value.get("sources"), list) and set(CORE_CODES).issubset(value["sources"])


def check_manifest(payload: bytes) -> dict:
    if len(payload) > MAX_MANIFEST_BYTES:
        raise ValueError("Active manifest exceeds 256 KiB")
    manifest = json.loads(payload.decode("utf-8"))
    if not isinstance(manifest, dict) or manifest.get("version") != 2 or not HEX32.fullmatch(str(manifest.get("snapshot_id", ""))):
        raise ValueError("Invalid version-2 snapshot identity")
    if not completed(manifest.get("completion")):
        raise ValueError("Active manifest lacks a completed core-source capture")
    if not isinstance(manifest.get("generated_at"), str) or len(manifest["generated_at"]) > 50:
        raise ValueError("Active manifest lacks a valid generation timestamp")
    generated = datetime.fromisoformat(manifest["generated_at"].replace("Z", "+00:00"))
    if generated.tzinfo is None:
        raise ValueError("Generation timestamp must include a timezone")
    index = manifest.get("index")
    if not isinstance(index, dict) or index.get("file") != "index.json" or not integer(index.get("bytes"), 1, MAX_INDEX_BYTES) or not HEX64.fullmatch(str(index.get("sha256", ""))):
        raise ValueError("Invalid bounded index descriptor")
    descriptors = manifest.get("documents")
    if not isinstance(descriptors, list) or len(descriptors) > MAX_DOCUMENTS:
        raise ValueError("Invalid shard descriptor list")
    names = set()
    for descriptor in descriptors:
        if not isinstance(descriptor, dict) or not SHARD_NAME.fullmatch(str(descriptor.get("file", ""))) or descriptor["file"] in names:
            raise ValueError("Invalid or repeated immutable shard name")
        if not integer(descriptor.get("bytes"), 1, MAX_SHARD_BYTES) or not integer(descriptor.get("records"), 1, MAX_DOCUMENTS) or not HEX64.fullmatch(str(descriptor.get("sha256", ""))):
            raise ValueError("Invalid bounded shard descriptor")
        names.add(descriptor["file"])
    if sum(item["records"] for item in descriptors) > MAX_DOCUMENTS:
        raise ValueError("Snapshot exceeds 60,000 observations")
    if sum(item["bytes"] for item in descriptors) + index["bytes"] > MAX_LOCAL_BYTES:
        raise ValueError("Snapshot exceeds the 64 MiB processing limit")
    return manifest


def checked_file(reader, descriptor: dict, limit: int) -> bytes:
    payload = reader(descriptor["file"], limit)
    if len(payload) != descriptor["bytes"] or digest(payload) != descriptor["sha256"]:
        raise ValueError("Snapshot file failed its byte-count or SHA-256 check")
    return payload


def reconstruct(manifest_payload: bytes, reader, keep_payloads: bool = False) -> tuple[dict, dict, dict[str, bytes]]:
    """Validate every bounded file and rebuild v1 only for local merge processing."""
    manifest = check_manifest(manifest_payload)
    index_payload = checked_file(reader, manifest["index"], MAX_INDEX_BYTES)
    index = json.loads(index_payload.decode("utf-8"))
    if not isinstance(index, dict) or index.get("version") != 2 or index.get("snapshot_id") != manifest["snapshot_id"] or index.get("generated_at") != manifest["generated_at"] or index.get("completion") != manifest["completion"]:
        raise ValueError("Index does not match the active manifest")
    sources = index.get("sources")
    imports = index.get("imports")
    if not isinstance(sources, list) or not isinstance(imports, list):
        raise ValueError("Index lacks source/import metadata")
    codes = []
    for source in sources:
        if not isinstance(source, dict) or source.get("code") not in SOURCES:
            raise ValueError("Index contains an unknown source")
        codes.append(source["code"])
    if len(codes) != len(set(codes)) or not set(CORE_CODES).issubset(codes):
        raise ValueError("Index repeats a source or omits a core register")
    counts = index.get("document_counts")
    if not isinstance(counts, dict) or set(counts) != set(codes) or any(not integer(value, 0, MAX_DOCUMENTS) for value in counts.values()):
        raise ValueError("Index has invalid source observation counts")
    if sum(counts.values()) != sum(item["records"] for item in manifest["documents"]):
        raise ValueError("Index and shard record counts differ")
    parcels = index.get("parcels")
    if not isinstance(parcels, dict):
        raise ValueError("Index lacks parcel lookup entries")
    shard_names = {descriptor["file"] for descriptor in manifest["documents"]}
    expected_refs = {}
    for parcel, entry in parcels.items():
        if not isinstance(parcel, str) or CADASTRAL_ID.fullmatch(parcel) is None or not isinstance(entry, dict) or not isinstance(entry.get("documents"), list) or not entry["documents"]:
            raise ValueError("Malformed parcel lookup entry")
        refs = set()
        for ref in entry["documents"]:
            if not isinstance(ref, dict) or ref.get("source_code") not in codes or not HEX64.fullmatch(str(ref.get("document_hash", ""))) or ref.get("shard") not in shard_names:
                raise ValueError("Malformed parcel observation reference")
            identity = (ref["source_code"], ref["document_hash"], ref["shard"])
            if identity in refs:
                raise ValueError("Repeated observation reference for a parcel")
            refs.add(identity)
        expected_refs[parcel] = refs
    payloads = {"index.json": index_payload} if keep_payloads else {}
    documents = []
    identities = set()
    actual_refs = {}
    actual_counts = Counter({code: 0 for code in codes})
    for descriptor in manifest["documents"]:
        payload = checked_file(reader, descriptor, MAX_SHARD_BYTES)
        if not payload.endswith(b"\n"):
            raise ValueError("JSONL shard lacks its final newline")
        lines = payload.splitlines()
        if len(lines) != descriptor["records"]:
            raise ValueError("Shard record count differs from its descriptor")
        if keep_payloads:
            payloads[descriptor["file"]] = payload
        for line in lines:
            document = json.loads(line.decode("utf-8"))
            if not isinstance(document, dict) or document.get("source_code") not in codes or not HEX64.fullmatch(str(document.get("document_hash", ""))):
                raise ValueError("Malformed shard observation")
            if not isinstance(document.get("cadastral_ids"), list) or any(not isinstance(parcel, str) or CADASTRAL_ID.fullmatch(parcel) is None for parcel in document["cadastral_ids"]):
                raise ValueError("Malformed shard parcel identifiers")
            if len(document["cadastral_ids"]) != len(set(document["cadastral_ids"])):
                raise ValueError("Shard observation repeats a parcel identifier")
            identity = (document["source_code"], document["document_hash"])
            if identity in identities:
                raise ValueError("Repeated source/document observation")
            identities.add(identity)
            actual_counts[document["source_code"]] += 1
            for parcel in set(document["cadastral_ids"]):
                actual_refs.setdefault(parcel, set()).add((*identity, descriptor["file"]))
            documents.append(document)
    if dict(actual_counts) != counts or actual_refs != expected_refs:
        raise ValueError("Parcel references or source counts disagree with the immutable observations")
    snapshot = {"version": 1, "generated_at": manifest["generated_at"], "sources": sources, "documents": documents, "imports": imports, "completion": manifest["completion"]}
    validate_snapshot(snapshot)
    if len(json_bytes(snapshot)) > MAX_LOCAL_BYTES:
        raise ValueError("Reconstructed local dataset exceeds 64 MiB")
    return snapshot, manifest, payloads


def has_active(ftp: FTP_TLS) -> bool:
    # A failed directory listing is an error. Do not mistake a permission problem
    # for an absent pointer and silently fall back to obsolete evidence.
    return any(posixpath.basename(item.rstrip("/")) == "registry-active.json" for item in ftp.nlst(PRIVATE))


def hosted_state(ftp: FTP_TLS, remote: str = "auto") -> tuple[str, bytes, dict]:
    active = has_active(ftp)
    if remote == ACTIVE_REMOTE or (remote == "auto" and active):
        raw = read_remote(ftp, ACTIVE_REMOTE, MAX_MANIFEST_BYTES)
        manifest = check_manifest(raw)
        directory = f"{SNAPSHOT_ROOT}/{manifest['snapshot_id']}"
        snapshot, _, _ = reconstruct(raw, lambda name, limit: read_remote(ftp, f"{directory}/{name}", limit))
        return ACTIVE_REMOTE, raw, snapshot
    if remote == V1_REMOTE and active:
        raise ValueError("A version-2 snapshot is active; use auto rather than replacing the ignored fallback")
    raw = read_remote(ftp, V1_REMOTE, MAX_BYTES)
    return V1_REMOTE, raw, check_payload(raw)


def previous_metadata(previous: Path) -> dict:
    return json.loads(previous.with_name(previous.name + ".fetch-meta.json").read_text(encoding="utf-8"))


def assert_previous(remote: str, raw: bytes, previous: Path) -> None:
    previous_raw = read_local(previous, MAX_LOCAL_BYTES)
    metadata_path = previous.with_name(previous.name + ".fetch-meta.json")
    if metadata_path.exists():
        metadata = previous_metadata(previous)
        if not isinstance(metadata, dict) or metadata.get("version") != 1 or metadata.get("remote") != remote or metadata.get("sha256") != digest(raw) or metadata.get("bytes") != len(raw) or metadata.get("local_sha256") != digest(previous_raw):
            raise ValueError("Hosted pointer or local previous snapshot changed after fetch; refusing publication")
    elif remote != V1_REMOTE or digest(previous_raw) != digest(raw):
        raise ValueError("Version-2 publication requires the fetch metadata sidecar; refetch the current snapshot")


def verify_current_pointer(ftp: FTP_TLS, expected_remote: str, expected_raw: bytes) -> None:
    remote = ACTIVE_REMOTE if has_active(ftp) else V1_REMOTE
    if remote != expected_remote:
        raise ValueError("Hosted active snapshot changed while publication was preparing")
    raw = read_remote(ftp, remote, MAX_MANIFEST_BYTES if remote == ACTIVE_REMOTE else MAX_BYTES)
    if digest(raw) != digest(expected_raw):
        raise ValueError("Hosted active snapshot changed while publication was preparing")


def ensure_snapshot_root(ftp: FTP_TLS) -> None:
    original = ftp.pwd()
    try:
        try:
            ftp.cwd(SNAPSHOT_ROOT)
        except error_perm:
            ftp.mkd(SNAPSHOT_ROOT)
            ftp.cwd(SNAPSHOT_ROOT)
    finally:
        ftp.cwd(original)


def backup_previous(ftp: FTP_TLS, remote: str, raw: bytes) -> None:
    backup = f"{PRIVATE}/registry-active.previous.json" if remote == ACTIVE_REMOTE else f"{PRIVATE}/registry-data.previous.json"
    ftp.storbinary(f"STOR {backup}", io.BytesIO(raw))
    if digest(read_remote(ftp, backup, MAX_MANIFEST_BYTES if remote == ACTIVE_REMOTE else MAX_BYTES)) != digest(raw):
        raise ValueError("Previous snapshot backup failed SHA-256 verification")


def publish_pointer(ftp: FTP_TLS, candidate: bytes, old_remote: str, old_raw: bytes) -> None:
    temporary = f"{PRIVATE}/registry-active.{uuid4().hex}.pending.json"
    uploaded = False
    try:
        ftp.storbinary(f"STOR {temporary}", io.BytesIO(candidate))
        uploaded = True
        if digest(read_remote(ftp, temporary, MAX_MANIFEST_BYTES)) != digest(candidate):
            raise ValueError("Temporary active manifest failed SHA-256 verification")
        backup_previous(ftp, old_remote, old_raw)
        verify_current_pointer(ftp, old_remote, old_raw)
        # RNTO must replace without deleting the old pointer first. If overwrite
        # is refused, the existing dataset remains active and the run fails.
        ftp.rename(temporary, ACTIVE_REMOTE)
        uploaded = False
        if digest(read_remote(ftp, ACTIVE_REMOTE, MAX_MANIFEST_BYTES)) != digest(candidate):
            if old_remote == ACTIVE_REMOTE:
                restore = f"{PRIVATE}/registry-active.{uuid4().hex}.restore.json"
                ftp.storbinary(f"STOR {restore}", io.BytesIO(old_raw))
                if digest(read_remote(ftp, restore, MAX_MANIFEST_BYTES)) != digest(old_raw):
                    raise ValueError("Published manifest differs and restoration could not be verified")
                ftp.rename(restore, ACTIVE_REMOTE)
            else:
                ftp.delete(ACTIVE_REMOTE)  # Migration rollback reactivates the untouched v1 file.
            raise ValueError("Published manifest differs; restored the previous active snapshot")
    finally:
        if uploaded:
            ftp.delete(temporary)


def publish_v1(ftp: FTP_TLS, candidate: bytes, current: bytes) -> None:
    temporary = f"{PRIVATE}/registry-data.{uuid4().hex}.pending.json"
    uploaded = False
    try:
        ftp.storbinary(f"STOR {temporary}", io.BytesIO(candidate))
        uploaded = True
        if digest(read_remote(ftp, temporary)) != digest(candidate):
            raise ValueError("Uploaded version-1 dataset failed SHA-256 verification")
        backup_previous(ftp, V1_REMOTE, current)
        verify_current_pointer(ftp, V1_REMOTE, current)
        ftp.rename(temporary, V1_REMOTE)
        uploaded = False
        if digest(read_remote(ftp, V1_REMOTE)) != digest(candidate):
            restore = f"{PRIVATE}/registry-data.{uuid4().hex}.restore.json"
            ftp.storbinary(f"STOR {restore}", io.BytesIO(current))
            if digest(read_remote(ftp, restore)) != digest(current):
                raise ValueError("Version-1 restoration could not be verified")
            ftp.rename(restore, V1_REMOTE)
            raise ValueError("Published dataset differs; restored the previous version")
    finally:
        if uploaded:
            ftp.delete(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("fetch", "publish"))
    parser.add_argument("--remote", choices=("auto", V1_REMOTE, ACTIVE_REMOTE), default="auto")
    parser.add_argument("--input", type=Path, help="Version-1 JSON file, or version-2 publish directory")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
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
        protection = read_remote(ftp, f"{PRIVATE}/.htaccess", limit=16 * 1024).decode("utf-8")
        if not any(re.fullmatch(r"(?:deny\s+from\s+all|require\s+all\s+denied)", line.strip(), re.IGNORECASE) for line in protection.splitlines()):
            raise ValueError("Private directory lacks HTTP access protection")
        remote, current, previous_snapshot = hosted_state(ftp, args.remote)
        if args.operation == "fetch":
            local = current if remote == V1_REMOTE else json_bytes(previous_snapshot)
            write_atomic(args.output, local)
            metadata = {"version": 1, "remote": remote, "sha256": digest(current), "bytes": len(current), "local_sha256": digest(local), "source_version": 1 if remote == V1_REMOTE else 2}
            write_atomic(args.output.with_name(args.output.name + ".fetch-meta.json"), json_bytes(metadata))
            print(f"Fetched {len(previous_snapshot['documents'])} register observations ({len(local):,} reconstructed bytes) by verified FTPS")
            return
        assert_previous(remote, current, args.previous)
        if args.input.is_dir():
            manifest_payload = read_local(args.input / "registry-active.json", MAX_MANIFEST_BYTES)
            manifest = check_manifest(manifest_payload)
            candidate_root = (args.input / "registry-snapshots" / manifest["snapshot_id"]).resolve()
            output_root = args.input.resolve()
            if not candidate_root.is_relative_to(output_root) or candidate_root != output_root / "registry-snapshots" / manifest["snapshot_id"]:
                raise ValueError("Local immutable snapshot directory escapes the publish root")
            next_snapshot, _, payloads = reconstruct(manifest_payload, lambda name, limit: read_local(candidate_root / name, limit), keep_payloads=True)
        else:
            if remote != V1_REMOTE:
                raise ValueError("An active sharded snapshot requires --input pointing to a version-2 directory")
            candidate = read_local(args.input, MAX_BYTES)
            next_snapshot = check_payload(candidate)
            payloads = None
        before = {(item["source_code"], item["document_hash"]) for item in previous_snapshot["documents"]}
        after = {(item["source_code"], item["document_hash"]) for item in next_snapshot["documents"]}
        if not before.issubset(after):
            raise ValueError("Candidate would remove an earlier register observation")
        next_documents = {(item["source_code"], item["document_hash"]): item for item in next_snapshot["documents"]}
        for observation in previous_snapshot["documents"]:
            candidate_observation = next_documents[(observation["source_code"], observation["document_hash"])]
            if candidate_observation["raw_fields"] != observation["raw_fields"] or set(candidate_observation["cadastral_ids"]) != set(observation["cadastral_ids"]):
                raise ValueError("Candidate would alter the content of an earlier register observation")
        if payloads is not None:
            ensure_snapshot_root(ftp)
            directory = f"{SNAPSHOT_ROOT}/{manifest['snapshot_id']}"
            # A snapshot directory is immutable. A collision or failed earlier
            # attempt needs a fresh build; existing children are never overwritten.
            ftp.mkd(directory)
            for name, payload in payloads.items():
                ftp.storbinary(f"STOR {directory}/{name}", io.BytesIO(payload))
                if digest(read_remote(ftp, f"{directory}/{name}", MAX_INDEX_BYTES if name == "index.json" else MAX_SHARD_BYTES)) != digest(payload):
                    raise ValueError("Uploaded immutable snapshot file failed SHA-256 verification")
            publish_pointer(ftp, manifest_payload, remote, current)
            print(f"Published version-2 snapshot: {len(next_snapshot['documents'])} observations in {len(manifest['documents'])} bounded shards; previous active snapshot retained privately")
        else:
            publish_v1(ftp, candidate, current)
            print(f"Published version-1 snapshot: {len(next_snapshot['documents'])} observations; previous snapshot retained privately")


if __name__ == "__main__":
    main()
