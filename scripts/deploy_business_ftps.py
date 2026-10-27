#!/usr/bin/env python3
"""Publish validated business-address snapshots through verified explicit FTPS.

Fetch captures the exact previous pointer. Validate is entirely local and calls
the builder's full integrity validator. Publish uploads a new immutable tree,
verifies every upload and atomically switches a small pointer last.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import io
import json
import os
import posixpath
import re
import ssl
from ftplib import FTP_TLS, error_perm
from pathlib import Path
from uuid import uuid4

from deploy_site_ftps import read_remote

PRIVATE = "/htdocs/private"
ACTIVE = f"{PRIVATE}/business-active.json"
SNAPSHOTS = f"{PRIVATE}/business-snapshots"
MAX_POINTER_BYTES = 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_STATE_BYTES = 2 * 1024 * 1024
MAX_INDEX_BYTES = 9_500_000
MAX_SHARD_BYTES = 1024 * 1024
MAX_DATASET_BYTES = 128 * 1024 * 1024
SOURCE_REPO = "ChocoRamaBG/register-of-outpatient-care-facilities-and-hospices"
SOURCE_PATH = "registry_agency_scraper/registry_agency_outputs"


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def read_local(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file() or not 1 <= path.stat().st_size <= maximum:
        raise ValueError("Local business publication file is missing or exceeds its limit")
    with path.open("rb") as handle:
        payload = handle.read(maximum + 1)
    if not 1 <= len(payload) <= maximum:
        raise ValueError("Local business publication file changed while reading")
    return payload


def write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise ValueError("Pointer state parent may not be a symlink")
    with path.open("xb") as handle:
        handle.write(payload)


def check_pointer(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"version", "snapshot_id", "manifest_sha256"} or type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Business pointer format is invalid")
    if not isinstance(value["snapshot_id"], str) or re.fullmatch(r"[a-f0-9]{32}", value["snapshot_id"]) is None:
        raise ValueError("Business snapshot ID is invalid")
    if not isinstance(value["manifest_sha256"], str) or re.fullmatch(r"[a-f0-9]{64}", value["manifest_sha256"]) is None:
        raise ValueError("Business manifest digest is invalid")
    return value


def descriptor(value: object, name: str, maximum: int, with_file: bool = True) -> dict:
    keys = {"file", "bytes", "sha256"} if with_file else {"bytes", "sha256"}
    if not isinstance(value, dict) or set(value) != keys or (with_file and value["file"] != name):
        raise ValueError("Business file descriptor format is invalid")
    if type(value["bytes"]) is not int or not 2 <= value["bytes"] <= maximum:
        raise ValueError("Business file descriptor byte count is invalid")
    if not isinstance(value["sha256"], str) or re.fullmatch(r"[a-f0-9]{64}", value["sha256"]) is None:
        raise ValueError("Business file descriptor digest is invalid")
    return {"file": name, "bytes": value["bytes"], "sha256": value["sha256"]}


def check_manifest(value: object, pointer_value: dict) -> dict:
    keys = {"version", "snapshot_id", "generated_at", "source", "cadastre", "counts", "shards", "parcel_index", "search_index"}
    if not isinstance(value, dict) or set(value) != keys or type(value["version"]) is not int or value["version"] != 1 or value["snapshot_id"] != pointer_value["snapshot_id"]:
        raise ValueError("Business manifest format is invalid")
    source = value["source"]
    if not isinstance(source, dict) or set(source) != {"repo", "commit", "path", "files"} or source["repo"] != SOURCE_REPO or source["path"] != SOURCE_PATH:
        raise ValueError("Business source repository is invalid")
    if not isinstance(source["commit"], str) or not re.fullmatch(r"[a-f0-9]{40}", source["commit"]) or not isinstance(source["files"], list) or not 1 <= len(source["files"]) <= 64:
        raise ValueError("Business source revision or parts are invalid")
    seen = set()
    source_bytes = 0
    for part in source["files"]:
        if not isinstance(part, dict) or set(part) != {"name", "bytes", "git_blob_sha1", "sha256"}:
            raise ValueError("Business source part format is invalid")
        name = part["name"]
        if not isinstance(name, str) or not re.fullmatch(r"registry_agency_data_mega(?:_part(?:[2-9]|[1-9][0-9]+))?\.csv", name) or name in seen:
            raise ValueError("Business source part name is invalid")
        if type(part["bytes"]) is not int or not 1 <= part["bytes"] <= 134_217_728 or not isinstance(part["git_blob_sha1"], str) or not re.fullmatch(r"[a-f0-9]{40}", part["git_blob_sha1"]) or not isinstance(part["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", part["sha256"]):
            raise ValueError("Business source part evidence is invalid")
        seen.add(name)
        source_bytes += part["bytes"]
    if source_bytes > 1024 * 1024 * 1024:
        raise ValueError("Business source parts exceed their total byte limit")
    counts = value["counts"]
    if not isinstance(counts, dict) or not 1 <= len(counts) <= 100 or any(not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key) or type(count) is not int or not 0 <= count <= 10_000_000 for key, count in counts.items()):
        raise ValueError("Business coverage counts are invalid")
    for key in ("matched_companies", "matched_parcels", "sofia_candidates"):
        if type(counts.get(key)) is not int or not 1 <= counts[key] <= 2_000_000:
            raise ValueError("Business publication lacks positive validated coverage")
    if not counts["matched_parcels"] <= counts["matched_companies"] <= counts["sofia_candidates"]:
        raise ValueError("Business coverage counts are inconsistent")
    descriptors(value)
    return value


def descriptors(manifest: dict) -> list[dict]:
    result = [descriptor(manifest["parcel_index"], "parcel-index.json", MAX_INDEX_BYTES), descriptor(manifest["search_index"], "search-index.json", MAX_INDEX_BYTES)]
    shards = manifest["shards"]
    if not isinstance(shards, dict) or not 1 <= len(shards) <= 512:
        raise ValueError("Business shard collection is invalid")
    for name, evidence in sorted(shards.items()):
        if not isinstance(name, str) or not re.fullmatch(r"companies-[0-9]{3}\.json", name):
            raise ValueError("Business shard filename is invalid")
        result.append(descriptor(evidence, name, MAX_SHARD_BYTES, with_file=False))
    if sum(item["bytes"] for item in result) > MAX_DATASET_BYTES:
        raise ValueError("Business snapshot exceeds its total byte limit")
    return result


def local_candidate(root: Path) -> tuple[dict, dict, bytes, bytes, Path]:
    # Import only at runtime: validate/prepare runs the same complete validator
    # as the builder and needs neither credentials nor network access.
    builder = importlib.import_module("refresh_business_addresses")
    manifest = builder.validate_snapshot(root)
    pointer_raw = read_local(root / "business-active.json", MAX_POINTER_BYTES)
    pointer_value = check_pointer(json.loads(pointer_raw))
    check_manifest(manifest, pointer_value)
    directory = root / "business-snapshots" / pointer_value["snapshot_id"]
    if root.is_symlink() or (root / "business-snapshots").is_symlink() or directory.is_symlink():
        raise ValueError("Business publication directories may not be symlinks")
    manifest_raw = read_local(directory / "manifest.json", MAX_MANIFEST_BYTES)
    if digest(manifest_raw) != pointer_value["manifest_sha256"] or json.loads(manifest_raw) != manifest:
        raise ValueError("Local business pointer and manifest differ")
    return pointer_value, manifest, pointer_raw, manifest_raw, directory


def pointer(ftp: FTP_TLS) -> bytes | None:
    names = {posixpath.basename(name.rstrip("/")) for name in ftp.nlst(PRIVATE)}
    if "business-active.json" not in names:
        return None
    payload = read_remote(ftp, ACTIVE, MAX_POINTER_BYTES)
    check_pointer(json.loads(payload))
    return payload


def assert_pointer(ftp: FTP_TLS, expected: bytes | None) -> None:
    if pointer(ftp) != expected:
        raise ValueError("Hosted business pointer changed since fetch; refusing publication")


def remote_manifest(ftp: FTP_TLS, raw: bytes) -> tuple[dict, bytes]:
    value = check_pointer(json.loads(raw))
    manifest_raw = read_remote(ftp, f"{SNAPSHOTS}/{value['snapshot_id']}/manifest.json", MAX_MANIFEST_BYTES)
    if digest(manifest_raw) != value["manifest_sha256"]:
        raise ValueError("Hosted immutable business manifest failed its digest check")
    return check_manifest(json.loads(manifest_raw), value), manifest_raw


def previous_state(path: Path) -> tuple[bytes | None, dict | None]:
    state = json.loads(read_local(path, MAX_STATE_BYTES))
    expected = {"version", "remote", "present", "bytes", "sha256", "pointer", "raw_pointer", "manifest", "raw_manifest"}
    if not isinstance(state, dict) or set(state) != expected or type(state["version"]) is not int or state["version"] != 1 or state["remote"] != ACTIVE or type(state["present"]) is not bool:
        raise ValueError("Previous business pointer state is invalid")
    if not state["present"]:
        if state["bytes"] != 0 or any(state[key] is not None for key in ("sha256", "pointer", "raw_pointer", "manifest", "raw_manifest")):
            raise ValueError("Absent business pointer state contains unexpected evidence")
        return None, None
    if not isinstance(state["raw_pointer"], str):
        raise ValueError("Previous business pointer lacks exact original bytes")
    raw = state["raw_pointer"].encode("utf-8")
    if len(raw) > MAX_POINTER_BYTES or state["bytes"] != len(raw) or state["sha256"] != digest(raw):
        raise ValueError("Previous business pointer state failed its digest check")
    value = check_pointer(json.loads(raw))
    if value != state["pointer"]:
        raise ValueError("Previous business pointer evidence differs")
    if not isinstance(state["raw_manifest"], str):
        raise ValueError("Previous business manifest lacks exact original bytes")
    manifest_raw = state["raw_manifest"].encode("utf-8")
    if len(manifest_raw) > MAX_MANIFEST_BYTES or digest(manifest_raw) != value["manifest_sha256"] or json.loads(manifest_raw) != state["manifest"]:
        raise ValueError("Previous business manifest failed its pointer digest check")
    return raw, check_manifest(state["manifest"], value)


def continuity(previous: dict | None, candidate: dict) -> None:
    if previous is None:
        return
    if any(previous["source"][key] != candidate["source"][key] for key in ("repo", "path")):
        raise ValueError("Business source mapping changed; review it before publication")
    old_parts = {part["name"] for part in previous["source"]["files"]}
    if not old_parts.issubset({part["name"] for part in candidate["source"]["files"]}):
        raise ValueError("Business source part disappeared; refusing incomplete refresh")
    for key in ("matched_companies", "matched_parcels"):
        if previous["counts"][key] >= 50 and candidate["counts"][key] < previous["counts"][key] * 0.8:
            raise ValueError("Business refresh loses over 20% of earlier matched coverage")


def put_verified(ftp: FTP_TLS, remote: str, payload: bytes, maximum: int) -> None:
    if len(payload) > maximum:
        raise ValueError("Business upload exceeds its byte limit")
    ftp.storbinary(f"STOR {remote}", io.BytesIO(payload))
    returned = read_remote(ftp, remote, maximum)
    if len(returned) != len(payload) or digest(returned) != digest(payload):
        raise ValueError("Uploaded business file failed its byte count or digest check")


def activate(ftp: FTP_TLS, candidate: bytes, previous: bytes | None) -> None:
    temporary = f"{PRIVATE}/business-active.{uuid4().hex}.pending.json"
    pending = True
    try:
        put_verified(ftp, temporary, candidate, MAX_POINTER_BYTES)
        assert_pointer(ftp, previous)
        if previous is not None:
            # Unique backups preserve earlier pointers without overwriting one.
            backup = f"{PRIVATE}/business-active.{uuid4().hex}.previous.json"
            put_verified(ftp, backup, previous, MAX_POINTER_BYTES)
        assert_pointer(ftp, previous)
        ftp.rename(temporary, ACTIVE)
        pending = False
        try:
            assert_pointer(ftp, candidate)
            remote_manifest(ftp, candidate)
        except Exception as verification_error:
            try:
                if previous is None:
                    ftp.delete(ACTIVE)
                    assert_pointer(ftp, None)
                else:
                    restore = f"{PRIVATE}/business-active.{uuid4().hex}.restore.json"
                    put_verified(ftp, restore, previous, MAX_POINTER_BYTES)
                    ftp.rename(restore, ACTIVE)
                    assert_pointer(ftp, previous)
            except Exception as rollback_error:
                raise RuntimeError("Business pointer verification and rollback failed; inspect private state before another publication") from rollback_error
            raise ValueError("Business pointer verification failed; previous state restored") from verification_error
    finally:
        if pending:
            try:
                ftp.delete(temporary)
            except error_perm:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("fetch", "validate", "publish"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    if args.operation == "fetch" and args.output is None:
        parser.error("fetch requires --output")
    if args.operation != "fetch" and args.input is None:
        parser.error("validate/publish require --input")
    if args.operation == "publish" and args.previous is None:
        parser.error("publish requires --previous")
    candidate = local_candidate(args.input) if args.operation != "fetch" else None
    previous, earlier = previous_state(args.previous) if args.previous is not None else (None, None)
    if candidate is not None:
        continuity(earlier, candidate[1])
    if args.operation == "validate":
        print(f"Validated {candidate[1]['counts']['matched_companies']:,} business-address associations and every immutable snapshot file")
        return
    credentials = {key: os.environ.get(key, "") for key in ("FTP_HOST", "FTP_USER", "FTP_PASSWORD")}
    if not all(credentials.values()) or any("\r" in value or "\n" in value for value in credentials.values()):
        raise ValueError("Valid FTP_HOST, FTP_USER and FTP_PASSWORD secrets are required")
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with FTP_TLS(context=context, timeout=90) as ftp:
        ftp.connect(credentials["FTP_HOST"], 21)
        ftp.login(credentials["FTP_USER"], credentials["FTP_PASSWORD"])
        ftp.prot_p()
        protection = read_remote(ftp, f"{PRIVATE}/.htaccess", 16 * 1024).decode("utf-8")
        if not any(re.fullmatch(r"(?:deny\s+from\s+all|require\s+all\s+denied)", line.strip(), re.I) for line in protection.splitlines()):
            raise ValueError("Private hosting directory lacks HTTP access protection")
        if args.operation == "fetch":
            raw = pointer(ftp)
            value = check_pointer(json.loads(raw)) if raw is not None else None
            manifest, manifest_raw = remote_manifest(ftp, raw) if raw is not None else (None, None)
            state = {"version": 1, "remote": ACTIVE, "present": raw is not None, "bytes": len(raw) if raw is not None else 0,
                     "sha256": digest(raw) if raw is not None else None, "pointer": value,
                     "raw_pointer": raw.decode("utf-8") if raw is not None else None, "manifest": manifest,
                     "raw_manifest": manifest_raw.decode("utf-8") if manifest_raw is not None else None}
            payload = encoded(state)
            if len(payload) > MAX_STATE_BYTES:
                raise ValueError("Business pointer state exceeds its byte limit")
            write_new(args.output, payload)
            print("Fetched verified business pointer" if raw is not None else "Confirmed no business snapshot is active")
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
        value, manifest, pointer_raw, manifest_raw, local = candidate
        directory = f"{SNAPSHOTS}/{value['snapshot_id']}"
        # A reused/partial snapshot directory is deliberately never overwritten.
        ftp.mkd(directory)
        files = descriptors(manifest)
        for position, evidence in enumerate(files, 1):
            maximum = MAX_INDEX_BYTES if evidence["file"] in ("parcel-index.json", "search-index.json") else MAX_SHARD_BYTES
            payload = read_local(local / evidence["file"], maximum)
            if len(payload) != evidence["bytes"] or digest(payload) != evidence["sha256"]:
                raise ValueError("Local business snapshot changed before upload")
            put_verified(ftp, f"{directory}/{evidence['file']}", payload, maximum)
            if position % 20 == 0 or position == len(files):
                print(f"Uploaded and verified {position}/{len(files)} immutable business files", flush=True)
        # Verify the exact local pointer/manifest again after all data transfers.
        if read_local(local / "manifest.json", MAX_MANIFEST_BYTES) != manifest_raw or read_local(args.input / "business-active.json", MAX_POINTER_BYTES) != pointer_raw:
            raise ValueError("Local business activation metadata changed during upload")
        put_verified(ftp, f"{directory}/manifest.json", manifest_raw, MAX_MANIFEST_BYTES)
        activate(ftp, pointer_raw, previous)
        print(f"Published {manifest['counts']['matched_companies']:,} company registered-address associations; earlier immutable snapshots retained")


if __name__ == "__main__":
    main()
