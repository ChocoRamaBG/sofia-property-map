#!/usr/bin/env python3
"""Import the 24 published Sofia parcel ZIPs into a bounded private snapshot.

Only official catalogue download links are used. DBF AREA is preserved as the
publisher's square-metre value; geometry, owners and rights are never imported.
The downloaded catalogue's listing dates are historical evidence, not refreshed
dates. Current HTTP Last-Modified is recorded separately when supplied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import ssl
import struct
import time
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, quote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, HTTPSHandler
from uuid import uuid4
from zipfile import ZipFile

CATALOGUE_URL = "https://kais.cadastre.bg/bg/OpenData"
LEGACY_REFERENCE_FORMAT = "area-source-shard-tsv-v1"
REFERENCE_FORMAT = "area-source-shard-facets-tsv-v2"
AREA_METHOD = "published_AREA_BGS2005_LCC"
MAX_MANIFEST_BYTES = 256 * 1024
MAX_INDEX_BYTES = 16 * 1024 * 1024
MAX_SHARD_BYTES = 1024 * 1024
MAX_DATASET_BYTES = 128 * 1024 * 1024
MAX_PARCELS = 500000
MAX_AMBIGUOUS_PARCELS = 5000
MAX_FACET_ENTRIES = 1000
MAX_ZIP_BYTES = 64 * 1024 * 1024
MAX_DBF_BYTES = 512 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
MAX_AREA = Decimal("1000000000")
CADASTRAL_ID = re.compile(r"68134\.[0-9]{1,6}\.[0-9]{1,6}")
HEX32 = re.compile(r"[a-f0-9]{32}")
HEX64 = re.compile(r"[a-f0-9]{64}")
SHARD_NAME = re.compile(r"parcels-[0-9]{3}\.json")
AREA_DECIMAL = re.compile(r"[0-9]+(?:\.[0-9]+)?")
EXPECTED_DBF_FIELDS = {
    "AREA", "PERIM", "cadimm", "cadnum", "cadreg", "cattype", "ekatte",
    "ekattefn", "immaddr", "oldident", "parcel", "place", "propcode",
    "proptype", "purpcode", "purptype", "quarname", "quarter", "regname",
    "strename", "strnum", "usecode", "usetype", "validate",
}
DETAIL_FIELDS = {
    "address": "immaddr", "district_name": "regname",
    "purpose_code": "purpcode", "purpose": "purptype",
    "use_code": "usecode", "use": "usetype",
    "property_type_code": "propcode", "property_type": "proptype",
    "approval_act": "validate",
}
FACET_FIELDS = {
    "purposes": ("purpose", "purpose_code", "purpose"),
    "uses": ("use", "use_code", "use"),
    "property_types": ("property_type", "property_type_code", "property"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def file_digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(128 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def read_json(path: Path, limit: int = MAX_MANIFEST_BYTES):
    if not path.is_file() or path.is_symlink() or path.stat().st_size > limit:
        raise ValueError("JSON file is absent, linked, or exceeds its byte limit")
    def bad_constant(_):
        raise ValueError("Nonstandard JSON number")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=bad_constant)


def write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)


def timestamp_valid(value) -> bool:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value) is None:
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def official_download_url(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 4096 or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid official download URL")
    url = urljoin(CATALOGUE_URL, value)
    parts = urlsplit(url)
    query = parse_qs(parts.query, strict_parsing=True)
    if parts.scheme != "https" or parts.netloc != "kais.cadastre.bg" or parts.path != "/bg/OpenData/Download" or parts.fragment or set(query) != {"path"} or len(query["path"]) != 1 or not query["path"][0]:
        raise ValueError("Download must be the exact published KAIS OpenData link")
    return quote(url, safe=":/?&=%")


def load_catalogue(path: Path) -> tuple[dict, str]:
    catalogue = read_json(path)
    if not isinstance(catalogue, dict) or type(catalogue.get("version")) is not int or catalogue["version"] != 1 or catalogue.get("catalogue_url") != CATALOGUE_URL or not isinstance(catalogue.get("sources"), list) or len(catalogue["sources"]) != 24:
        raise ValueError("A complete official catalogue of 24 Sofia district exports is required")
    seen_urls, seen_labels = set(), set()
    for source in catalogue["sources"]:
        if not isinstance(source, dict) or not isinstance(source.get("label_bg"), str) or not source["label_bg"].startswith("гр. София (68134) - район ") or len(source["label_bg"]) > 200:
            raise ValueError("Invalid official Sofia district label")
        url = official_download_url(source.get("download_path"))
        if url in seen_urls or source["label_bg"] in seen_labels:
            raise ValueError("Repeated official district download link")
        listing_date = source.get("published_at")
        if listing_date is not None and (not isinstance(listing_date, str) or len(listing_date) > 80):
            raise ValueError("Invalid historical catalogue publication date")
        seen_urls.add(url)
        seen_labels.add(source["label_bg"])
    return catalogue, file_digest(path)


class OfficialRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        official_download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_archive(url: str, path: Path, reuse: bool) -> dict:
    metadata_path = path.with_suffix(".download.json")
    if reuse and path.is_file() and metadata_path.is_file():
        metadata = read_json(metadata_path)
        if isinstance(metadata, dict) and type(metadata.get("version")) is int and metadata["version"] == 1 and metadata.get("source_url") == url and metadata.get("zip_bytes") == path.stat().st_size and metadata.get("zip_sha256") == file_digest(path) and timestamp_valid(metadata.get("captured_at")) and (metadata.get("published_at") is None or timestamp_valid(metadata["published_at"])):
            return metadata
        raise ValueError("Cached archive no longer matches its download evidence")
    if path.exists() or metadata_path.exists():
        raise ValueError("Archive cache already exists; use a new cache directory or --reuse-cache")
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".pending.zip")
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    opener = build_opener(OfficialRedirects(), HTTPSHandler(context=context))
    request = Request(quote(url, safe=":/?&=%"), headers={"User-Agent": "SofiaPermits-open-data-refresh/1.0", "Accept": "application/zip, application/octet-stream"})
    try:
        with opener.open(request, timeout=60) as response:
            official_download_url(response.url)
            declared = response.headers.get("Content-Length")
            if declared is not None and (not declared.isdigit() or not 1 <= int(declared) <= MAX_ZIP_BYTES):
                raise ValueError("Archive response has an invalid byte count")
            modified = response.headers.get("Last-Modified")
            published_at = None
            if modified:
                try:
                    value = parsedate_to_datetime(modified)
                    if value.tzinfo is None:
                        raise ValueError("Last-Modified lacks a timezone")
                    published_at = value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
                except (ValueError, TypeError, OverflowError):
                    raise ValueError("Archive returned an invalid Last-Modified timestamp")
            count = 0
            with pending.open("xb") as handle:
                for chunk in iter(lambda: response.read(128 * 1024), b""):
                    count += len(chunk)
                    if count > MAX_ZIP_BYTES:
                        raise ValueError("Archive exceeds its 64 MiB byte limit")
                    handle.write(chunk)
            if count == 0 or (declared is not None and count != int(declared)):
                raise ValueError("Archive download is empty or incomplete")
        metadata = {"version": 1, "source_url": url, "zip_bytes": count, "zip_sha256": file_digest(pending), "captured_at": utc_now(), "published_at": published_at}
        pending.replace(path)
        write_new(metadata_path, json_bytes(metadata))
        return metadata
    finally:
        if pending.exists():
            pending.unlink()


def read_exact(handle, size: int) -> bytes:
    payload = handle.read(size)
    if len(payload) != size:
        raise ValueError("Published DBF is truncated")
    return payload


def archive_records(path: Path, expected_district: str):
    """Stream only the UTF-8 DBF, and verify its declared row/byte structure."""
    with ZipFile(path) as archive:
        entries = archive.infolist()
        if not 1 <= len(entries) <= 256:
            raise ValueError("Unexpected archive entry count")
        names = set()
        for item in entries:
            name = PurePosixPath(item.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in item.filename or item.filename in names or item.flag_bits & 1 or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Unsafe, repeated, linked or encrypted archive entry")
            names.add(item.filename)
        dbfs = [item for item in entries if item.filename.lower().endswith(".dbf")]
        if len(dbfs) != 1 or not 33 <= dbfs[0].file_size <= MAX_DBF_BYTES:
            raise ValueError("One bounded parcel DBF is required")
        dbf = dbfs[0]
        stem = dbf.filename[:-4]
        lookup = {item.filename: item for item in entries}
        if stem + ".cpg" not in lookup or stem + ".prj" not in lookup or not 1 <= lookup[stem + ".cpg"].file_size <= 64 or not 1 <= lookup[stem + ".prj"].file_size <= 8192:
            raise ValueError("Published encoding/projection metadata is absent or exceeds its bounds")
        cpg = archive.read(stem + ".cpg").decode("ascii").strip().upper()
        if cpg not in ("UTF-8", "UTF8", "65001"):
            raise ValueError("Unexpected parcel DBF encoding")
        prj = archive.read(stem + ".prj").decode("utf-8")
        if len(prj) > 8192 or 'PROJCS["BGS2005"' not in prj or 'PROJECTION["Lambert_Conformal_Conic"' not in prj or not prj.rstrip().endswith('UNIT["Meter",1.0]]'):
            raise ValueError("AREA units require the published BGS2005 metre projection")
        with archive.open(dbf) as handle:
            header = read_exact(handle, 32)
            count = struct.unpack("<I", header[4:8])[0]
            header_length, record_length = struct.unpack("<HH", header[8:12])
            if count > MAX_PARCELS or not 33 <= header_length <= 8192 or (header_length - 33) % 32 or not 2 <= record_length <= 32768 or dbf.file_size not in (header_length + count * record_length, header_length + count * record_length + 1):
                raise ValueError("Unexpected DBF row/length declaration")
            fields = []
            for _ in range((header_length - 33) // 32):
                raw = read_exact(handle, 32)
                name = raw[:11].split(b"\0")[0].decode("ascii")
                if not raw[16] or raw[11] not in (ord("C"), ord("N")):
                    raise ValueError("Unexpected DBF field format")
                fields.append((name, raw[16]))
            if {name for name, _ in fields} != EXPECTED_DBF_FIELDS or len(fields) != len(EXPECTED_DBF_FIELDS) or 1 + sum(length for _, length in fields) != record_length or read_exact(handle, 1) != b"\r":
                raise ValueError("Published parcel DBF headings changed")
            for _ in range(count):
                row = read_exact(handle, record_length)
                if row[0:1] != b" ":
                    raise ValueError("Deleted or malformed DBF row requires inspection")
                values, position = {}, 1
                for name, length in fields:
                    values[name] = row[position:position + length].decode("utf-8").strip(" \x00")
                    position += length
                cadastral_id = values["cadnum"]
                area_text = values["AREA"]
                if CADASTRAL_ID.fullmatch(cadastral_id) is None or AREA_DECIMAL.fullmatch(area_text) is None:
                    raise ValueError("Invalid cadastral ID or published numeric AREA")
                area = Decimal(area_text)
                if not area.is_finite() or not 0 < area <= MAX_AREA:
                    raise ValueError("Published AREA is outside the supported positive square-metre bounds")
                if values["regname"].casefold() != expected_district.casefold():
                    raise ValueError("DBF district differs from its published catalogue link")
                record = {"cadastral_id": cadastral_id, "area_m2": float(area)}
                for public_name, dbf_name in DETAIL_FIELDS.items():
                    record[public_name] = values[dbf_name] or None
                yield cadastral_id, format(area, "f"), record
            suffix = handle.read()
            if suffix not in (b"", b"\x1a"):
                raise ValueError("Unexpected DBF trailing data")


def integer(value, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def facet_identity(record: dict, group: str) -> tuple[str | None, str] | None:
    """Unknown official values stay in details, but are not selectable facets."""
    label_field, code_field, _ = FACET_FIELDS[group]
    label, code = record[label_field], record[code_field]
    if label is None:
        return None
    if not isinstance(label, str) or len(label) > 2000 or (code is not None and (not isinstance(code, str) or len(code) > 50)):
        raise ValueError("Cadastral facet label or code exceeds its text bounds")
    if not label.strip() or label.strip().casefold() == "няма данни":
        return None
    return code, label


def facet_key(group: str, identity: tuple[str | None, str]) -> str:
    # Exact labels remain distinct even if the authority reuses the same code.
    return FACET_FIELDS[group][2] + "-" + digest(json_bytes(list(identity)))[:16]


def source_district_label(source: dict) -> str:
    prefix = "гр. София (68134) - "
    if not source["label_bg"].startswith(prefix + "район "):
        raise ValueError("Official district caption lacks its Sofia district label")
    return source["label_bg"][len(prefix):]


def build_facets(records, sources: list[dict]) -> tuple[dict, dict]:
    counts = {group: Counter() for group in FACET_FIELDS}
    districts = {}
    for record in records:
        source = record["source_index"]
        label = record["district_name"]
        if not isinstance(label, str) or label.casefold() != source_district_label(sources[source]).casefold():
            raise ValueError("Cadastral district differs from its official source")
        if source in districts and districts[source] != label:
            raise ValueError("One source contains conflicting exact district labels")
        districts[source] = label
        for group in FACET_FIELDS:
            identity = facet_identity(record, group)
            if identity is not None:
                counts[group][identity] += 1
    facets = {"districts": [{"key": source["code"], "label_bg": districts.get(position, source_district_label(source)), "code": None, "count": source["usable_parcel_count"]} for position, source in enumerate(sources)]}
    lookups = {}
    for group, observed in counts.items():
        if len(observed) > MAX_FACET_ENTRIES:
            raise ValueError("Cadastral facet dictionary exceeds 1,000 exact code/label pairs")
        ordered = sorted(observed, key=lambda identity: facet_key(group, identity))
        keys = [facet_key(group, identity) for identity in ordered]
        if len(set(keys)) != len(keys):
            raise ValueError("Cadastral facet key hash collision requires format review")
        facets[group] = [{"key": key, "label_bg": identity[1], "code": identity[0], "count": observed[identity]} for key, identity in zip(keys, ordered)]
        lookups[group] = {identity: position for position, identity in enumerate(ordered)}
    return facets, lookups


def check_facets(manifest: dict) -> None:
    facets = manifest.get("facets")
    if not isinstance(facets, dict) or set(facets) != {"districts", *FACET_FIELDS}:
        raise ValueError("Cadastral v2 manifest lacks its four facet dictionaries")
    districts = facets["districts"]
    if not isinstance(districts, list) or len(districts) != 24:
        raise ValueError("Cadastral district facets must preserve all 24 source positions")
    for position, row in enumerate(districts):
        source = manifest["sources"][position]
        if not isinstance(row, dict) or set(row) != {"key", "label_bg", "code", "count"} or row["key"] != source["code"] or not isinstance(row["label_bg"], str) or row["label_bg"].casefold() != source_district_label(source).casefold() or row["code"] is not None or not integer(row["count"], 0, manifest["parcel_count"]) or row["count"] != source["usable_parcel_count"]:
            raise ValueError("Invalid cadastral district facet or usable count")
    for group in FACET_FIELDS:
        rows = facets[group]
        if not isinstance(rows, list) or len(rows) > MAX_FACET_ENTRIES:
            raise ValueError("Invalid bounded cadastral facet dictionary")
        previous = ""
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"key", "label_bg", "code", "count"} or not isinstance(row["label_bg"], str) or not row["label_bg"].strip() or len(row["label_bg"]) > 2000 or row["label_bg"].strip().casefold() == "няма данни" or (row["code"] is not None and (not isinstance(row["code"], str) or len(row["code"]) > 50)) or not integer(row["count"], 1, manifest["parcel_count"]):
                raise ValueError("Invalid cadastral facet label, code or usable count")
            key = facet_key(group, (row["code"], row["label_bg"]))
            if row["key"] != key or key <= previous:
                raise ValueError("Cadastral facets must have sorted unique exact code/label keys")
            previous = key
        if sum(row["count"] for row in rows) > manifest["parcel_count"]:
            raise ValueError("Cadastral facet counts exceed usable unambiguous parcels")


def check_manifest(value: dict) -> dict:
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] not in (1, 2) or not isinstance(value.get("snapshot_id"), str) or HEX32.fullmatch(value["snapshot_id"]) is None or not timestamp_valid(value.get("generated_at")) or value.get("reference_format") != (REFERENCE_FORMAT if value["version"] == 2 else LEGACY_REFERENCE_FORMAT) or value.get("area_unit") != "m2" or value.get("area_method") != AREA_METHOD:
        raise ValueError("Invalid cadastral snapshot identity or area method")
    completion = value.get("completion")
    if not isinstance(completion, dict) or completion.get("status") != "complete" or completion.get("district_count") != 24 or not isinstance(completion.get("catalogue_sha256"), str) or HEX64.fullmatch(completion["catalogue_sha256"]) is None:
        raise ValueError("Cadastral snapshot lacks all 24 completed district exports")
    if not integer(value.get("parcel_count"), 1, MAX_PARCELS):
        raise ValueError("Invalid cadastral parcel count")
    for name in ("area_min_m2", "area_max_m2"):
        area = value.get(name)
        if isinstance(area, bool) or not isinstance(area, (int, float)) or not math.isfinite(area) or not 0 < area <= float(MAX_AREA):
            raise ValueError("Invalid cadastral area range")
    if value["area_min_m2"] > value["area_max_m2"]:
        raise ValueError("Reversed cadastral area range")
    sources = value.get("sources")
    if not isinstance(sources, list) or len(sources) != 24:
        raise ValueError("Invalid cadastral source list")
    seen = set()
    for position, source in enumerate(sources):
        if not isinstance(source, dict) or source.get("code") != f"sofia-district-{position:02d}" or not isinstance(source.get("label_bg"), str) or not 1 <= len(source["label_bg"]) <= 200 or source.get("catalogue_url") != CATALOGUE_URL or not timestamp_valid(source.get("captured_at")) or (source.get("published_at") is not None and not timestamp_valid(source["published_at"])) or not isinstance(source.get("zip_sha256"), str) or HEX64.fullmatch(source["zip_sha256"]) is None or not integer(source.get("zip_bytes"), 1, MAX_ZIP_BYTES) or not integer(source.get("record_count"), 0, MAX_PARCELS) or not integer(source.get("usable_parcel_count"), 0, source["record_count"]):
            raise ValueError("Invalid cadastral source provenance")
        listing_date = source.get("catalogue_published_at")
        if listing_date is not None and (not isinstance(listing_date, str) or len(listing_date) > 80):
            raise ValueError("Invalid historical catalogue date")
        url = official_download_url(source.get("source_url"))
        if url in seen:
            raise ValueError("Repeated cadastral source URL")
        seen.add(url)
    if not integer(value.get("source_record_total"), value["parcel_count"], MAX_PARCELS) or sum(source["record_count"] for source in sources) != value["source_record_total"] or sum(source["usable_parcel_count"] for source in sources) != value["parcel_count"]:
        raise ValueError("Cadastral source counts disagree with the captured and usable parcel counts")
    ambiguous_ids = value.get("ambiguous_ids")
    if not integer(value.get("ambiguous_parcel_count"), 0, MAX_AMBIGUOUS_PARCELS) or not isinstance(ambiguous_ids, list) or len(ambiguous_ids) != value["ambiguous_parcel_count"] or any(not isinstance(cadastral_id, str) or CADASTRAL_ID.fullmatch(cadastral_id) is None for cadastral_id in ambiguous_ids) or ambiguous_ids != sorted(set(ambiguous_ids)):
        raise ValueError("Invalid ambiguous cadastral ID quarantine")
    def descriptor(item, pattern, byte_limit):
        if not isinstance(item, dict) or not isinstance(item.get("file"), str) or pattern.fullmatch(item["file"]) is None or not integer(item.get("bytes"), 1, byte_limit) or not isinstance(item.get("sha256"), str) or HEX64.fullmatch(item["sha256"]) is None:
            raise ValueError("Invalid bounded cadastral file descriptor")
    descriptor(value.get("index"), re.compile(r"index\.tsv"), MAX_INDEX_BYTES)
    conflict_descriptor = value.get("conflicts")
    if ambiguous_ids:
        descriptor(conflict_descriptor, re.compile(r"conflicts\.json"), MAX_SHARD_BYTES)
        if not integer(conflict_descriptor.get("records"), 1, MAX_AMBIGUOUS_PARCELS) or conflict_descriptor["records"] != len(ambiguous_ids):
            raise ValueError("Conflict descriptor disagrees with its quarantined ID count")
    elif conflict_descriptor is not None:
        raise ValueError("An empty quarantine must not contain a conflict descriptor")
    shards = value.get("records")
    if not isinstance(shards, list) or not 1 <= len(shards) <= 1000:
        raise ValueError("Invalid cadastral shard list")
    for position, shard in enumerate(shards):
        descriptor(shard, SHARD_NAME, MAX_SHARD_BYTES)
        if shard["file"] != f"parcels-{position:03d}.json" or not integer(shard.get("records"), 1, MAX_PARCELS):
            raise ValueError("Invalid cadastral shard order or row count")
    if sum(row["records"] for row in shards) != value["parcel_count"] or sum(row["bytes"] for row in shards) + value["index"]["bytes"] + (conflict_descriptor["bytes"] if conflict_descriptor else 0) > MAX_DATASET_BYTES:
        raise ValueError("Cadastral snapshot exceeds or disagrees with its format bounds")
    if value["version"] == 2:
        check_facets(value)
    return value


def validate_publish_tree(root: Path) -> dict:
    manifest = check_manifest(read_json(root / "cadastre-active.json"))
    directory = root / "cadastre-snapshots" / manifest["snapshot_id"]
    if directory.is_symlink() or not directory.resolve().is_relative_to(root.resolve()):
        raise ValueError("Cadastral snapshot directory escapes the publish root")
    def checked_path(item):
        path = directory / item["file"]
        if not path.is_file() or path.is_symlink() or path.stat().st_size != item["bytes"] or file_digest(path) != item["sha256"]:
            raise ValueError("Cadastral file failed its byte count or SHA-256 check")
        return path
    refs, source_counts = {}, Counter()
    v2 = manifest["version"] == 2
    facet_counts = {group: Counter() for group in FACET_FIELDS}
    previous = ""
    with checked_path(manifest["index"]).open("r", encoding="ascii", newline="") as handle:
        for line in handle:
            if not line.endswith("\n") or "\r" in line or len(line) > (160 if v2 else 120):
                raise ValueError("Malformed cadastral TSV line")
            cells = line[:-1].split("\t")
            if len(cells) != (7 if v2 else 4) or CADASTRAL_ID.fullmatch(cells[0]) is None or cells[0] <= previous or AREA_DECIMAL.fullmatch(cells[1]) is None or not cells[2].isdigit() or not cells[3].isdigit():
                raise ValueError("Cadastral TSV is not sorted, unique and correctly typed")
            area, source, shard = Decimal(cells[1]), int(cells[2]), int(cells[3])
            if not 0 < area <= MAX_AREA or not 0 <= source < 24 or not 0 <= shard < len(manifest["records"]):
                raise ValueError("Cadastral TSV area or file reference is invalid")
            facet_indices = ()
            if v2:
                if any(re.fullmatch(r"-1|[0-9]+", cell) is None for cell in cells[4:]):
                    raise ValueError("Malformed cadastral facet index")
                facet_indices = tuple(int(cell) for cell in cells[4:])
                for group, position in zip(FACET_FIELDS, facet_indices):
                    if not -1 <= position < len(manifest["facets"][group]):
                        raise ValueError("Cadastral facet index is outside its dictionary")
                    if position >= 0:
                        facet_counts[group][position] += 1
            previous = cells[0]
            refs[cells[0]] = (area, source, shard, *facet_indices)
            source_counts[source] += 1
            if len(refs) > MAX_PARCELS:
                raise ValueError("Cadastral TSV exceeds its parcel count bound")
    if len(refs) != manifest["parcel_count"] or any(source_counts[position] != source["usable_parcel_count"] for position, source in enumerate(manifest["sources"])) or set(refs).intersection(manifest["ambiguous_ids"]):
        raise ValueError("Cadastral TSV counts disagree with source provenance")
    if v2 and any(facet_counts[group][position] != row["count"] for group in FACET_FIELDS for position, row in enumerate(manifest["facets"][group])):
        raise ValueError("Cadastral TSV facet counts disagree with their dictionaries")
    seen = set()
    for position, descriptor in enumerate(manifest["records"]):
        rows = read_json(checked_path(descriptor), MAX_SHARD_BYTES)
        if not isinstance(rows, dict) or len(rows) != descriptor["records"]:
            raise ValueError("Cadastral detail shard count differs from its descriptor")
        for cadastral_id, row in rows.items():
            ref = refs.get(cadastral_id)
            if ref is None or cadastral_id in seen or ref[2] != position or not isinstance(row, dict) or row.get("cadastral_id") != cadastral_id or not integer(row.get("source_index"), 0, 23) or row["source_index"] != ref[1] or isinstance(row.get("area_m2"), bool) or not isinstance(row.get("area_m2"), (int, float)) or float(ref[0]) != row["area_m2"] or set(row) != {"cadastral_id", "area_m2", "source_index", *DETAIL_FIELDS}:
                raise ValueError("Cadastral detail row disagrees with its exact index reference")
            if any(row[field] is not None and (not isinstance(row[field], str) or len(row[field]) > 2000) for field in DETAIL_FIELDS):
                raise ValueError("Cadastral attribute exceeds its stated text bounds")
            if v2:
                if row["district_name"] != manifest["facets"]["districts"][ref[1]]["label_bg"]:
                    raise ValueError("Cadastral district facet differs from its original record")
                for group, facet_index in zip(FACET_FIELDS, ref[3:]):
                    identity = facet_identity(row, group)
                    if identity is None:
                        if facet_index != -1:
                            raise ValueError("Unknown cadastral attribute acquired a selectable facet")
                    elif facet_index == -1 or (manifest["facets"][group][facet_index]["code"], manifest["facets"][group][facet_index]["label_bg"]) != identity:
                        raise ValueError("Cadastral facet differs from its exact original code and label")
            seen.add(cadastral_id)
    if len(seen) != len(refs) or float(min(row[0] for row in refs.values())) != manifest["area_min_m2"] or float(max(row[0] for row in refs.values())) != manifest["area_max_m2"]:
        raise ValueError("Cadastral detail coverage or area bounds disagree with the TSV")
    if manifest["conflicts"] is not None:
        conflicts = read_json(checked_path(manifest["conflicts"]), MAX_SHARD_BYTES)
        if not isinstance(conflicts, dict) or sorted(conflicts) != manifest["ambiguous_ids"]:
            raise ValueError("Quarantined variants disagree with their manifest IDs")
        variant_counts = Counter()
        for cadastral_id, variants in conflicts.items():
            if not isinstance(variants, list) or not 2 <= len(variants) <= 100:
                raise ValueError("Quarantined cadastral ID lacks distinct bounded variants")
            distinct = set()
            for row in variants:
                if not isinstance(row, dict) or row.get("cadastral_id") != cadastral_id or not integer(row.get("source_index"), 0, 23) or isinstance(row.get("area_m2"), bool) or not isinstance(row.get("area_m2"), (int, float)) or not math.isfinite(row["area_m2"]) or not 0 < row["area_m2"] <= float(MAX_AREA) or set(row) != {"cadastral_id", "area_m2", "source_index", *DETAIL_FIELDS} or any(row[field] is not None and (not isinstance(row[field], str) or len(row[field]) > 2000) for field in DETAIL_FIELDS):
                    raise ValueError("Malformed original cadastral conflict variant")
                variant_counts[row["source_index"]] += 1
                distinct.add(json_bytes(row))
            if len(distinct) != len(variants):
                raise ValueError("Quarantined variants contain identical duplicates")
        if any(source["record_count"] < source["usable_parcel_count"] + variant_counts[position] for position, source in enumerate(manifest["sources"])):
            raise ValueError("Quarantine variants exceed their original source row counts")
    return manifest


def create_snapshot(catalogue_path: Path, archives: Path, output: Path, reuse: bool, delay: float) -> dict:
    catalogue, catalogue_sha = load_catalogue(catalogue_path)
    if (output / "cadastre-active.json").exists():
        raise ValueError("Use a fresh output directory; existing snapshots are immutable")
    sources, rows, conflicts = [], {}, {}
    downloaded = 0
    for position, source in enumerate(catalogue["sources"]):
        url = official_download_url(source["download_path"])
        path = archives / f"sofia-district-{position:02d}.zip"
        evidence = download_archive(url, path, reuse)
        downloaded += evidence["zip_bytes"]
        if downloaded > MAX_DOWNLOAD_BYTES:
            raise ValueError("Complete capture exceeds its 512 MiB download limit")
        district = source["label_bg"].split(" - ", 1)[1]
        count = 0
        for cadastral_id, area_text, record in archive_records(path, district):
            record["source_index"] = position
            count += 1
            if cadastral_id in conflicts:
                if record not in conflicts[cadastral_id]:
                    conflicts[cadastral_id].append(record)
                continue
            if cadastral_id in rows:
                if record == rows[cadastral_id][1]:
                    continue
                conflicts[cadastral_id] = [rows.pop(cadastral_id)[1], record]
                if len(conflicts) > MAX_AMBIGUOUS_PARCELS:
                    raise ValueError("Too many conflicting cadastral IDs require source inspection")
                continue
            if len(rows) >= MAX_PARCELS:
                raise ValueError("Capture exceeds 500,000 cadastral parcels")
            rows[cadastral_id] = (area_text, record)
        sources.append({"code": f"sofia-district-{position:02d}", "label_bg": source["label_bg"], "catalogue_url": CATALOGUE_URL, "catalogue_published_at": source.get("published_at"), "record_count": count, **{key: evidence[key] for key in ("source_url", "zip_bytes", "zip_sha256", "captured_at", "published_at")}})
        print(f"Captured district {position + 1}/24: {count:,} stated parcel areas", flush=True)
        if position < 23:
            time.sleep(delay)
    usable_counts = Counter(record["source_index"] for _, record in rows.values())
    for position, source in enumerate(sources):
        source["usable_parcel_count"] = usable_counts[position]
    if len(rows) < 1000:
        raise ValueError("Complete Sofia capture has an unexpectedly small parcel count")
    completion = {"status": "complete", "district_count": 24, "catalogue_sha256": catalogue_sha}
    return write_snapshot(rows, conflicts, sources, completion, output)


def write_snapshot(rows: dict, conflicts: dict, sources: list[dict], completion: dict, output: Path) -> dict:
    """Write an immutable v2 derivative without altering source capture evidence."""
    if (output / "cadastre-active.json").exists():
        raise ValueError("Use a fresh output directory; existing snapshots are immutable")
    facets, facet_lookups = build_facets((record for _, record in rows.values()), sources)
    snapshot_id, generated_at = uuid4().hex, utc_now()
    directory = output / "cadastre-snapshots" / snapshot_id
    directory.mkdir(parents=True, exist_ok=False)
    descriptors, entries, size, tsv = [], [], 2, []
    def flush():
        nonlocal entries, size
        if not entries:
            return
        payload = b"{" + b",".join(entries) + b"}"
        name = f"parcels-{len(descriptors):03d}.json"
        if len(descriptors) >= 1000 or len(payload) > MAX_SHARD_BYTES:
            raise ValueError("Cadastral detail shards exceed their limits")
        write_new(directory / name, payload)
        descriptors.append({"file": name, "bytes": len(payload), "sha256": digest(payload), "records": len(entries)})
        entries, size = [], 2
    for cadastral_id in sorted(rows):
        area_text, record = rows[cadastral_id]
        entry = json_bytes(cadastral_id) + b":" + json_bytes(record)
        if entries and size + 1 + len(entry) > MAX_SHARD_BYTES:
            flush()
        shard = len(descriptors)
        indices = [facet_lookups[group].get(facet_identity(record, group), -1) for group in FACET_FIELDS]
        tsv.append((f"{cadastral_id}\t{area_text}\t{record['source_index']}\t{shard}\t" + "\t".join(str(position) for position in indices) + "\n").encode("ascii"))
        size += len(entry) + int(bool(entries))
        entries.append(entry)
    flush()
    index_payload = b"".join(tsv)
    conflict_payload = json_bytes({key: conflicts[key] for key in sorted(conflicts)}) if conflicts else None
    if conflict_payload is not None and len(conflict_payload) > MAX_SHARD_BYTES:
        raise ValueError("Conflicting original observations exceed their one MiB quarantine bound")
    if len(index_payload) > MAX_INDEX_BYTES or len(index_payload) + sum(item["bytes"] for item in descriptors) + (len(conflict_payload) if conflict_payload else 0) > MAX_DATASET_BYTES:
        raise ValueError("Cadastral snapshot exceeds its processing byte limit")
    write_new(directory / "index.tsv", index_payload)
    conflict_descriptor = None
    if conflict_payload is not None:
        write_new(directory / "conflicts.json", conflict_payload)
        conflict_descriptor = {"file": "conflicts.json", "bytes": len(conflict_payload), "sha256": digest(conflict_payload), "records": len(conflicts)}
    areas = [Decimal(row[0]) for row in rows.values()]
    manifest = {"version": 2, "snapshot_id": snapshot_id, "generated_at": generated_at, "reference_format": REFERENCE_FORMAT, "area_unit": "m2", "area_method": AREA_METHOD, "completion": completion, "sources": sources, "source_record_total": sum(source["record_count"] for source in sources), "parcel_count": len(rows), "ambiguous_parcel_count": len(conflicts), "ambiguous_ids": sorted(conflicts), "conflicts": conflict_descriptor, "area_min_m2": float(min(areas)), "area_max_m2": float(max(areas)), "index": {"file": "index.tsv", "bytes": len(index_payload), "sha256": digest(index_payload)}, "records": descriptors, "facets": facets}
    check_manifest(manifest)
    payload = json_bytes(manifest)
    if len(payload) > MAX_MANIFEST_BYTES:
        raise ValueError("Cadastral manifest exceeds 256 KiB")
    write_new(output / "cadastre-active.json", payload)
    validate_publish_tree(output)
    return manifest


def upgrade_existing(existing: Path, output: Path) -> dict:
    """Derive current-format facets from a fully verified v1/v2 private snapshot.

    Source timestamps, ZIP hashes/counts and the historical catalogue evidence
    are copied exactly. generated_at describes this derivative, not a download.
    The original Decimal text in the TSV is kept without float round-tripping.
    """
    if existing.resolve() == output.resolve():
        raise ValueError("An upgrade requires a separate fresh output directory")
    original_pointer = existing / "cadastre-active.json"
    if not original_pointer.is_file() or original_pointer.is_symlink() or original_pointer.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("Original cadastral pointer is absent, linked, or exceeds its byte limit")
    original_payload = original_pointer.read_bytes()
    manifest = validate_publish_tree(existing)
    directory = existing / "cadastre-snapshots" / manifest["snapshot_id"]
    def original_path(descriptor):
        path = directory / descriptor["file"]
        if not path.is_file() or path.is_symlink() or path.stat().st_size != descriptor["bytes"] or file_digest(path) != descriptor["sha256"]:
            raise ValueError("Original cadastral snapshot changed during upgrade")
        return path
    areas = {}
    with original_path(manifest["index"]).open("r", encoding="ascii", newline="") as handle:
        for line in handle:
            cells = line[:-1].split("\t")
            areas[cells[0]] = cells[1]
    rows = {}
    for descriptor in manifest["records"]:
        records = read_json(original_path(descriptor), MAX_SHARD_BYTES)
        for cadastral_id, record in records.items():
            rows[cadastral_id] = (areas[cadastral_id], record)
    conflicts = read_json(original_path(manifest["conflicts"]), MAX_SHARD_BYTES) if manifest["conflicts"] is not None else {}
    if (existing / "cadastre-active.json").read_bytes() != original_payload:
        raise ValueError("Original cadastral pointer changed during upgrade")
    return write_snapshot(rows, conflicts, manifest["sources"], manifest["completion"], output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", type=Path, default=Path(__file__).with_name("cadastre-sofia-sources.json"))
    parser.add_argument("--archives", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--upgrade-existing", type=Path, help="Upgrade a fully validated private snapshot without downloading or changing its source capture evidence")
    parser.add_argument("--reuse-cache", action="store_true", help="Reuse only archives whose URL, bytes, hash and capture sidecar all agree")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between the 24 sequential published ZIP downloads (minimum 1)")
    args = parser.parse_args()
    if not math.isfinite(args.delay) or args.delay < 1:
        parser.error("--delay must be at least one second")
    if args.upgrade_existing is not None:
        if args.archives is not None or args.reuse_cache:
            parser.error("--upgrade-existing cannot be combined with archive download/cache options")
        manifest = upgrade_existing(args.upgrade_existing, args.output)
    else:
        if args.archives is None:
            parser.error("--archives is required for a fresh official capture")
        manifest = create_snapshot(args.catalogue, args.archives, args.output, args.reuse_cache, args.delay)
    print(f"Prepared complete private cadastre v2 snapshot: {manifest['parcel_count']:,} parcels, {len(manifest['records'])} bounded detail shards, {manifest['index']['bytes']:,} TSV bytes; " + ", ".join(f"{group}={len(options)}" for group, options in manifest['facets'].items()))


if __name__ == "__main__":
    main()
