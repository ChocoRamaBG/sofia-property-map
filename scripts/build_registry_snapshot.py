#!/usr/bin/env python3
"""Build and merge private register snapshots without removing earlier evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from build_seed import CADASTRAL_ID, CERTIFICATES_DEFAULT, PERMITS_DEFAULT, ROOT, VISAS_DEFAULT, source_documents
from registry_sources import CORE_CODES, SOURCES, labelled_fields
from registry_facets import REFERENCE_FORMAT, build_filter_facets

MAX_BYTES = 10 * 1024 * 1024
MAX_LOCAL_BYTES = 128 * 1024 * 1024
MAX_SHARD_BYTES = 1024 * 1024
MAX_INDEX_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_DOCUMENTS = 100000
MAX_INDEX_PARCELS = 50000
SOURCE_CODES = {"coordinates", *SOURCES}
KNOWN_DATES = {"building_permits": "2025-05-20", "exploitation_certificates": "2025-05-21", "projecting_visas": "2025-05-12", "exploitation_certificates_legacy": None}


def parse_json(payload: str | bytes):
    """Reject JSON extensions/encoding/depth that the hosted PHP decoder rejects."""
    def invalid_number(token):
        raise ValueError(f"Non-standard JSON numeric constant: {token}")

    value = json.loads(payload, parse_constant=invalid_number)

    def inspect(item, depth=0):
        if isinstance(item, (dict, list)):
            if depth >= 31:
                raise ValueError("JSON exceeds the hosted decoder's depth limit")
            for child in (item.values() if isinstance(item, dict) else item):
                inspect(child, depth + 1)
            if isinstance(item, dict):
                for key in item:
                    key.encode("utf-8")
        elif isinstance(item, str):
            item.encode("utf-8")
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError("JSON contains an overflowing numeric value")

    inspect(value)
    return value


def read_json(path: Path, limit: int = MAX_BYTES) -> dict:
    if path.stat().st_size > limit:
        raise ValueError(f"JSON file exceeds its {limit:,}-byte limit: {path}")
    value = parse_json(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Snapshot must be a JSON object")
    return value


def string_valid(value, limit: int, nullable: bool = False) -> bool:
    return (nullable and value is None) or (isinstance(value, str) and len(value) <= limit)


def date_valid(value) -> bool:
    if value is None:
        return True
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def timestamp_valid(value, allow_sql: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    iso = re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value)
    sql = allow_sql and re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value)
    if not iso and not sql:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate_sources(rows) -> dict:
    if not isinstance(rows, list) or len(rows) > 5:
        raise ValueError("Registry source list is invalid")
    sources = {}
    for source in rows:
        if not isinstance(source, dict) or not isinstance(source.get("code"), str) or source["code"] not in SOURCE_CODES or source["code"] in sources:
            raise ValueError("Unknown or repeated registry source")
        if not string_valid(source.get("label_bg"), 190) or not string_valid(source.get("label_en"), 190) or "source_url" not in source or not string_valid(source["source_url"], 500, True) or "snapshot_date" not in source or not date_valid(source["snapshot_date"]) or not string_valid(source.get("snapshot_file"), 255, True):
            raise ValueError("Registry source metadata exceeds the API bounds")
        url = source["source_url"]
        legacy = source["code"] == "exploitation_certificates_legacy" and url in ("http://up.gis-sofia.bg/", "https://up.gis-sofia.bg/")
        if url is not None and not legacy:
            try:
                parts = urlsplit(url)
                port = parts.port
                if not url.startswith("https://") or parts.scheme != "https" or parts.netloc.split("@")[-1].split(":")[0] != "nag.sofia.bg" or any(ord(char) <= 32 for char in url) or parts.username is not None or parts.password is not None or (port is not None and not 1 <= port <= 65535):
                    raise ValueError("Registry source URL is outside the official HTTPS host")
            except ValueError as error:
                raise ValueError("Registry source URL is invalid") from error
        sources[source["code"]] = source
    if not set(CORE_CODES).issubset(sources):
        raise ValueError("Snapshot is missing a core register")
    return sources


def validate_completion(completion) -> None:
    if not isinstance(completion, dict) or completion.get("status") != "complete" or not isinstance(completion.get("sources"), list):
        raise ValueError("Snapshot lacks a completed core-source manifest")
    if any(not isinstance(code, str) or code not in SOURCE_CODES for code in completion["sources"]) or not set(CORE_CODES).issubset(completion["sources"]):
        raise ValueError("Completion manifest contains an unknown or missing source")
    if not date_valid(completion.get("start_date")) or (completion.get("finished_at") is not None and not timestamp_valid(completion["finished_at"])):
        raise ValueError("Completion manifest has an invalid date or timestamp")


def validate_imports(rows, sources: dict) -> None:
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError("Registry import list exceeds the API bounds")
    for item in rows:
        if not isinstance(item, dict) or not isinstance(item.get("source_code"), str) or item["source_code"] not in sources or not string_valid(item.get("source_file"), 255, True) or not timestamp_valid(item.get("imported_at"), allow_sql=True):
            raise ValueError("Registry import metadata is invalid")
        count = item.get("records_loaded")
        if not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= 9223372036854775807 or not date_valid(item.get("snapshot_date")):
            raise ValueError("Registry import count or snapshot date is invalid")


def validate_document(document, sources: dict) -> None:
    if not isinstance(document, dict) or not isinstance(document.get("source_code"), str) or document["source_code"] not in sources or document["source_code"] == "coordinates" or not isinstance(document.get("document_hash"), str) or re.fullmatch(r"[a-f0-9]{64}", document["document_hash"]) is None:
        raise ValueError("Invalid source or document hash")
    fields = document.get("raw_fields")
    ids = document.get("cadastral_ids")
    if not string_valid(document.get("record_key"), 190, True) or not isinstance(fields, dict) or len(fields) > 100 or not isinstance(ids, list) or len(ids) > 10000 or not string_valid(document.get("snapshot_file"), 255, True) or not date_valid(document.get("snapshot_date")) or not date_valid(document.get("issued_at")):
        raise ValueError("Registry observation metadata exceeds the API bounds")
    for field, value in fields.items():
        if not string_valid(field, 200) or (value is not None and not isinstance(value, (str, int, float, bool))) or (isinstance(value, str) and len(value.encode("utf-8")) > 500000) or (isinstance(value, float) and not math.isfinite(value)):
            raise ValueError("Registry fields exceed the scalar/key/value API bounds")
    if any(not isinstance(plot_id, str) or CADASTRAL_ID.fullmatch(plot_id) is None for plot_id in ids):
        raise ValueError("Snapshot contains a malformed parcel identifier")
    if len(ids) != len(set(ids)):
        raise ValueError("Snapshot repeats a parcel identifier within an observation")


def validate_snapshot(snapshot: dict) -> None:
    if not isinstance(snapshot, dict) or type(snapshot.get("version")) is not int or snapshot["version"] != 1 or not isinstance(snapshot.get("documents"), list):
        raise ValueError("Unsupported registry snapshot contract")
    if not timestamp_valid(snapshot.get("generated_at")):
        raise ValueError("Snapshot has an invalid generation timestamp")
    sources = validate_sources(snapshot.get("sources"))
    validate_completion(snapshot.get("completion"))
    validate_imports(snapshot.get("imports"), sources)
    if len(snapshot["documents"]) > MAX_DOCUMENTS:
        raise ValueError("Snapshot exceeds the API document limit")
    seen = set()
    for document in snapshot["documents"]:
        validate_document(document, sources)
        identity = (document["source_code"], document["document_hash"])
        if identity in seen:
            raise ValueError("Snapshot repeats a source/document observation")
        seen.add(identity)


def json_bytes(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


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
        raise ValueError("Reconstructed dataset exceeds the 128 MiB local processing limit")
    snapshot_id = uuid4().hex
    directory = output / "registry-snapshots" / snapshot_id
    if directory.exists():
        raise ValueError("Snapshot directory already exists; immutable files cannot be overwritten")
    completion = snapshot["completion"]
    index = {
        "version": 2, "snapshot_id": snapshot_id, "generated_at": snapshot["generated_at"],
        "sources": snapshot["sources"], "imports": snapshot.get("imports", []),
        "completion": completion, "document_counts": {source["code"]: 0 for source in snapshot["sources"]},
        "reference_format": REFERENCE_FORMAT,
        "parcels": {},
    }
    source_positions = {source["code"]: position for position, source in enumerate(snapshot["sources"])}
    index["filter_facets"], facet_positions = build_filter_facets(snapshot["documents"])
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
        shard_position = len(shards)
        payload.extend(line)
        records += 1
        index["document_counts"][document["source_code"]] += 1
        for parcel in sorted(set(document["cadastral_ids"])):
            # Positions refer to the ordered sources and manifest shard lists.
            index["parcels"].setdefault(parcel, {"documents": []})["documents"].append([
                source_positions[document["source_code"]], document["document_hash"], shard_position,
                facet_positions[identity],
            ])
    if payload:
        shards.append((f"documents-{len(shards):03d}.jsonl", bytes(payload), records))
    index["parcels"] = dict(sorted(index["parcels"].items()))
    if len(index["parcels"]) > MAX_INDEX_PARCELS:
        raise ValueError("Parcel lookup index exceeds the API limit of 50,000 identifiers")
    index_payload = json_bytes(index)
    if len(index_payload) > MAX_INDEX_BYTES:
        raise ValueError("Parcel lookup index exceeds 8 MiB; retain the hosted snapshot and review storage")
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
    total_bytes = len(index_payload) + len(manifest_payload) + sum(len(data) for _, data, _ in shards)
    if total_bytes > MAX_LOCAL_BYTES:
        raise ValueError("Publishable snapshot files exceed the 128 MiB processing limit")
    for name, data, _ in shards:
        write_atomic(directory / name, data)
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
    parser.add_argument("--reshard", action="store_true", help="Write an existing complete version-1 dataset as bounded version-2 files without changing observations")
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
    if args.reshard:
        if not args.previous or args.format != "sharded":
            parser.error("--reshard requires --previous and --format sharded")
        if args.bootstrap or args.capture or args.choose_start_date:
            parser.error("--reshard cannot be combined with --bootstrap, --capture, or --choose-start-date")
    if args.choose_start_date:
        if not args.previous:
            parser.error("--choose-start-date requires --previous")
        print(choose_start_date(read_json(args.previous, MAX_LOCAL_BYTES)))
        return
    if args.reshard:
        result = read_json(args.previous, MAX_LOCAL_BYTES)
    elif args.bootstrap:
        result = bootstrap(args)
    elif args.previous and args.capture:
        result = merge(read_json(args.previous, MAX_LOCAL_BYTES), args.capture)
    else:
        parser.error("Use --bootstrap, --reshard with --previous and --format sharded, or provide --previous and --capture")
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
