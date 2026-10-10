#!/usr/bin/env python3
"""Build and merge private register snapshots without removing earlier evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from build_seed import CADASTRAL_ID, CERTIFICATES_DEFAULT, PERMITS_DEFAULT, ROOT, VISAS_DEFAULT, source_documents
from registry_sources import CORE_CODES, SOURCES, labelled_fields

MAX_BYTES = 10 * 1024 * 1024
MAX_LOCAL_BYTES = 64 * 1024 * 1024
MAX_SHARD_BYTES = 1024 * 1024
MAX_INDEX_BYTES = 4 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_DOCUMENTS = 60000
KNOWN_DATES = {"building_permits": "2025-05-20", "exploitation_certificates": "2025-05-21", "projecting_visas": "2025-05-12", "exploitation_certificates_legacy": None}


def read_json(path: Path, limit: int = MAX_BYTES) -> dict:
    if path.stat().st_size > limit:
        raise ValueError(f"JSON file exceeds its {limit:,}-byte limit: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Snapshot must be a JSON object")
    return value


def validate_snapshot(snapshot: dict) -> None:
    if snapshot.get("version") != 1 or not isinstance(snapshot.get("sources"), list) or not isinstance(snapshot.get("documents"), list):
        raise ValueError("Unsupported registry snapshot contract")
    codes = {item.get("code") for item in snapshot["sources"]}
    if not set(CORE_CODES).issubset(codes):
        raise ValueError("Snapshot is missing a core register")
    if len(snapshot["documents"]) > MAX_DOCUMENTS:
        raise ValueError("Snapshot exceeds the API document limit")
    for document in snapshot["documents"]:
        if document.get("source_code") not in SOURCES or not re.fullmatch(r"[a-f0-9]{64}", document.get("document_hash", "")):
            raise ValueError("Invalid source or document hash")
        if not isinstance(document.get("raw_fields"), dict) or not isinstance(document.get("cadastral_ids"), list):
            raise ValueError("Invalid document fields or identifier list")
        if any(not isinstance(plot_id, str) or CADASTRAL_ID.fullmatch(plot_id) is None for plot_id in document["cadastral_ids"]):
            raise ValueError("Snapshot contains a malformed parcel identifier")
        if len(document["cadastral_ids"]) != len(set(document["cadastral_ids"])):
            raise ValueError("Snapshot repeats a parcel identifier within an observation")
    completion = snapshot.get("completion", {})
    if completion.get("status") != "complete" or not set(CORE_CODES).issubset(completion.get("sources", [])):
        raise ValueError("Snapshot lacks a completed core-source manifest")


def json_bytes(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + ".pending")
    pending.write_bytes(payload)
    pending.replace(path)


def write_sharded_snapshot(snapshot: dict, output: Path) -> tuple[dict, int]:
    """Prepare immutable bounded files and an active manifest, without FTP access."""
    validate_snapshot(snapshot)
    if (output / "registry-active.json").exists():
        raise ValueError("Publish output already has an active manifest; choose a fresh output directory")
    if len(json_bytes(snapshot)) > MAX_LOCAL_BYTES:
        raise ValueError("Reconstructed dataset exceeds the 64 MiB local processing limit")
    snapshot_id = uuid4().hex
    directory = output / "registry-snapshots" / snapshot_id
    if directory.exists():
        raise ValueError("Snapshot directory already exists; immutable files cannot be overwritten")
    completion = snapshot["completion"]
    index = {
        "version": 2, "snapshot_id": snapshot_id, "generated_at": snapshot["generated_at"],
        "sources": snapshot["sources"], "imports": snapshot.get("imports", []),
        "completion": completion, "document_counts": {source["code"]: 0 for source in snapshot["sources"]},
        "parcels": {},
    }
    shards: list[tuple[str, bytes, int]] = []
    payload = bytearray()
    records = 0
    seen = set()
    for document in sorted(snapshot["documents"], key=lambda item: (item["source_code"], item["document_hash"])):
        identity = (document["source_code"], document["document_hash"])
        if identity in seen:
            raise ValueError("Snapshot contains duplicate source/document observations")
        seen.add(identity)
        line = json_bytes(document) + b"\n"
        if len(line) > MAX_SHARD_BYTES:
            raise ValueError("A register observation exceeds the 1 MiB shard limit")
        if payload and len(payload) + len(line) > MAX_SHARD_BYTES:
            shards.append((f"documents-{len(shards):03d}.jsonl", bytes(payload), records))
            payload = bytearray()
            records = 0
        shard = f"documents-{len(shards):03d}.jsonl"
        payload.extend(line)
        records += 1
        index["document_counts"][document["source_code"]] += 1
        for parcel in sorted(set(document["cadastral_ids"])):
            index["parcels"].setdefault(parcel, {"documents": []})["documents"].append({
                "source_code": document["source_code"], "document_hash": document["document_hash"], "shard": shard,
            })
    if payload:
        shards.append((f"documents-{len(shards):03d}.jsonl", bytes(payload), records))
    index["parcels"] = dict(sorted(index["parcels"].items()))
    index_payload = json_bytes(index)
    if len(index_payload) > MAX_INDEX_BYTES:
        raise ValueError("Parcel lookup index exceeds 4 MiB; retain the hosted snapshot and review storage")
    manifest = {
        "version": 2, "snapshot_id": snapshot_id, "generated_at": snapshot["generated_at"],
        "index": {"file": "index.json", "bytes": len(index_payload), "sha256": hashlib.sha256(index_payload).hexdigest()},
        "documents": [{"file": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "records": count} for name, data, count in shards],
        "completion": completion,
    }
    manifest_payload = json_bytes(manifest)
    if len(manifest_payload) > MAX_MANIFEST_BYTES:
        raise ValueError("Active snapshot manifest exceeds 256 KiB")
    # Validate all bounds before creating any publishable local files. The active
    # manifest is written last, so an interrupted build lacks a completed pointer.
    total_bytes = len(index_payload) + len(manifest_payload)
    for name, data, _ in shards:
        write_atomic(directory / name, data)
        total_bytes += len(data)
    write_atomic(directory / "index.json", index_payload)
    write_atomic(output / "registry-active.json", manifest_payload)
    return manifest, total_bytes


def snapshot_date(code: str, filename: str) -> str | None:
    match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", filename)
    if match:
        return date(int(match[3]), int(match[2]), int(match[1])).isoformat()
    return KNOWN_DATES[code]


def issued_at(fields: dict) -> str | None:
    value = next((value for key, value in fields.items() if key.strip().casefold() in ("дата", "date")), None)
    if value is None:
        value = next((value for key, value in fields.items() if key.strip().casefold() in ("№", "номер", "удостоверение", "разрешение за строеж", "виза", "column 1")), "")
    match = re.search(r"(?<!\d)(\d{2})\.(\d{2})\.(\d{4})(?!\d)", str(value))
    if match:
        try:
            return date(int(match[3]), int(match[2]), int(match[1])).isoformat()
        except ValueError:
            return None
    return None


def record_key(fields: dict) -> str:
    # Use the actual document number, regardless of preceding icon/action cells.
    for key, value in fields.items():
        if key.strip().casefold() in ("№", "номер", "удостоверение", "разрешение за строеж", "виза"):
            return str(value)[:190]
    date_value = next((value for key, value in fields.items() if key.strip().casefold() in ("дата", "date")), None)
    if date_value is not None:
        return str(date_value)[:190]
    raise ValueError("A captured record has neither a document number nor a date")


def source_info(code: str, filename: str, captured_date: str | None) -> dict:
    info = SOURCES[code]
    return {"code": code, "label_bg": info["label_bg"], "label_en": info["label_en"], "source_url": info["source_url"], "snapshot_file": filename, "snapshot_date": captured_date}


def bootstrap(args) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    snapshot = {"version": 1, "generated_at": now, "sources": [], "documents": [], "imports": []}
    files = [("building_permits", args.permits), ("exploitation_certificates", args.certificates), ("projecting_visas", args.visas)]
    if not args.skip_legacy:
        files.append(("exploitation_certificates_legacy", args.legacy))
    for code, path in files:
        captured_date = snapshot_date(code, path.name)
        snapshot["sources"].append(source_info(code, path.name, captured_date))
        records, _ = source_documents(code, path)
        unique = {}
        for source, digest, key, serialized, filename, imported_at in records:
            fields = json.loads(serialized)
            ids = sorted(set(CADASTRAL_ID.findall(serialized)))
            if code.endswith("_legacy") and not ids:
                continue
            document = {"source_code": source, "document_hash": digest, "record_key": key, "raw_fields": labelled_fields(code, fields), "snapshot_file": filename, "snapshot_date": captured_date, "cadastral_ids": ids, "imported_at": imported_at}
            record_date = issued_at(fields)
            if record_date:
                document["issued_at"] = record_date
            unique[digest] = document
        snapshot["documents"].extend(unique.values())
        snapshot["imports"].append({"source_code": code, "source_file": path.name, "imported_at": now, "records_loaded": len(unique), "rows_seen": len(records), "snapshot_date": captured_date, "notes": "Supplied workbook snapshot. Legacy source retains only rows containing exact parcel IDs; no address or proximity matching." if code.endswith("_legacy") else "Supplied workbook snapshot; repeated rows deduplicated by original source-document hash."})
    snapshot["completion"] = {"status": "complete", "kind": "workbook-bootstrap", "sources": list(CORE_CODES), "finished_at": now}
    return snapshot


def merge(previous: dict, capture_dir: Path) -> dict:
    validate_snapshot(previous)
    captures = []
    for code in CORE_CODES:
        capture = read_json(capture_dir / f"{code}.json")
        if capture.get("source_code") != code or capture.get("source_url") != SOURCES[code]["source_url"] or capture.get("status") != "complete":
            raise ValueError(f"Capture identity or completion is invalid: {code}")
        if not isinstance(capture.get("records"), list) or len(capture["records"]) != capture.get("expected_rows") or capture.get("rows_seen") != capture.get("expected_rows"):
            raise ValueError(f"Capture is partial: {code}")
        date.fromisoformat(capture["snapshot_date"])
        date.fromisoformat(capture["start_date"])
        captures.append(capture)

    documents = {(item["source_code"], item["document_hash"]): item for item in previous["documents"]}
    sources = {item["code"]: item for item in previous["sources"]}
    imports = list(previous.get("imports", []))
    now = datetime.now(timezone.utc).isoformat()
    for capture in captures:
        code = capture["source_code"]
        filename = f"{code}-{capture['snapshot_date']}.json"
        sources[code] = source_info(code, filename, capture["snapshot_date"])
        for fields in capture["records"]:
            if not isinstance(fields, dict) or not fields:
                raise ValueError(f"Capture has an empty or malformed record: {code}")
            serialized = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            digest = hashlib.sha256((code + "\0" + serialized).encode("utf-8")).hexdigest()
            document = {"source_code": code, "document_hash": digest, "record_key": record_key(fields), "raw_fields": fields, "snapshot_file": filename, "snapshot_date": capture["snapshot_date"], "cadastral_ids": sorted(set(CADASTRAL_ID.findall(serialized))), "imported_at": capture["captured_at"]}
            record_date = issued_at(fields)
            if record_date:
                document["issued_at"] = record_date
            documents[(code, digest)] = document
        imports.append({"source_code": code, "source_file": filename, "imported_at": capture["captured_at"], "records_loaded": len(capture["records"]), "rows_seen": capture["rows_seen"], "snapshot_date": capture["snapshot_date"], "window_start": capture["start_date"], "notes": "Complete paginated register window. Earlier observations retained; document absence is not inferred."})
    result = {"version": 1, "generated_at": now, "sources": list(sources.values()), "documents": sorted(documents.values(), key=lambda item: (item["source_code"], item["document_hash"])), "imports": imports, "completion": {"status": "complete", "kind": "monthly-register-merge", "sources": list(CORE_CODES), "start_date": min(capture["start_date"] for capture in captures), "finished_at": now}}
    if not set((item["source_code"], item["document_hash"]) for item in previous["documents"]).issubset(documents):
        raise ValueError("Merge would remove earlier evidence")
    return result


def choose_start_date(snapshot: dict) -> str:
    validate_snapshot(snapshot)
    today = datetime.now(ZoneInfo("Europe/Sofia")).date()
    # A missed run or old workbook must not leave a gap. Keep at least 90 days of
    # overlap and extend back to the oldest core-source snapshot when necessary.
    starts = [today - timedelta(days=90)]
    for source in snapshot["sources"]:
        if source["code"] in CORE_CODES:
            if not source.get("snapshot_date"):
                raise ValueError("A core source lacks a date; choose a manual --start-date")
            starts.append(date.fromisoformat(source["snapshot_date"]) - timedelta(days=30))
    return min(starts).strftime("%d.%m.%Y")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--choose-start-date", action="store_true")
    parser.add_argument("--format", choices=("v1", "sharded"), default="v1", help="Sharded output is a directory containing a version-2 active manifest and bounded immutable files")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "seed" / "deploy" / "registry-data.json")
    parser.add_argument("--permits", type=Path, default=PERMITS_DEFAULT)
    parser.add_argument("--certificates", type=Path, default=CERTIFICATES_DEFAULT)
    parser.add_argument("--visas", type=Path, default=VISAS_DEFAULT)
    parser.add_argument("--legacy", type=Path, default=ROOT / "Udostoverenie za Vuvezhdane v Eksploataciya" / "Old Registry" / "All_Data_Old_Registry.xlsx")
    parser.add_argument("--skip-legacy", action="store_true")
    args = parser.parse_args()
    if args.choose_start_date:
        if not args.previous:
            parser.error("--choose-start-date requires --previous")
        print(choose_start_date(read_json(args.previous, MAX_LOCAL_BYTES)))
        return
    if args.bootstrap:
        result = bootstrap(args)
    elif args.previous and args.capture:
        result = merge(read_json(args.previous, MAX_LOCAL_BYTES), args.capture)
    else:
        parser.error("Use --bootstrap or provide --previous and --capture")
    validate_snapshot(result)
    payload = json_bytes(result)
    if args.format == "sharded":
        manifest, total_bytes = write_sharded_snapshot(result, args.output)
        print(f"Snapshot v2: {len(result['documents'])} documents, {len(manifest['documents'])} shards, {total_bytes:,} bytes; {args.output}")
    elif len(payload) > MAX_BYTES:
        raise ValueError("Single-file snapshot exceeds 10 MiB; use --format sharded instead")
    else:
        write_atomic(args.output, payload)
        print(f"Snapshot v1: {len(result['documents'])} documents, {len(payload):,} bytes; {args.output}")
    for code in SOURCES:
        docs = [item for item in result["documents"] if item["source_code"] == code]
        ids = {plot for item in docs for plot in item["cadastral_ids"]}
        print(f"{code}: {len(docs)} documents, {len(ids)} exact parcel IDs")


if __name__ == "__main__":
    main()
