#!/usr/bin/env python3
"""Bounded immutable asking-price market format shared by producer/publisher.

Only small, factual listing fields are public. The source advert remains the
place to read descriptions, agency contacts, photos and actual availability.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlsplit

VERSION = 1
MAX_LISTINGS = 50000
MAX_SHARDS = 256
SHARD_ROWS = 250
MAX_SHARD_BYTES = 256 * 1024
MAX_SUMMARY_BYTES = 512 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_STATE_BYTES = 64 * 1024 * 1024
MAX_CAPTURE_BYTES = 96 * 1024 * 1024
HEX32 = re.compile(r"[a-f0-9]{32}")
HEX64 = re.compile(r"[a-f0-9]{64}")
OFFER_ID = re.compile(r"[a-z0-9]{6,64}")
PUBLIC_FIELDS = frozenset({
    "id", "url", "neighborhood_key", "neighborhood_bg", "type_key", "type_bg",
    "area_sqm", "price_eur", "eur_per_sqm", "price_currency", "vat_basis",
    "construction_year", "construction_cohort", "last_modified_at", "observed_at",
    "first_seen_at", "comparison", "change", "historical", "quality_flags",
    "floor_bg", "construction_label_bg", "address_bg",
})


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def text(value, limit=160):
    if value is None:
        return None
    cleaned = " ".join(unicodedata.normalize("NFKC", str(value)).split())
    if not cleaned or cleaned.lower() in {"none", "nan", "null", "няма данни"}:
        return None
    return cleaned[:limit]


def stable_key(prefix, value):
    return prefix + "-" + digest(value.casefold().encode("utf-8"))[:16]


def canonical_offer_id(url, identifier=None):
    """Use the stable source ID, never tracking parameters or a row number."""
    if not isinstance(url, str):
        raise ValueError("Offer has no source URL")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"imot.bg", "www.imot.bg"} or parsed.username or parsed.password:
        raise ValueError("Offer URL is not an imot.bg source")
    values = parse_qs(parsed.query).get("adv", [])
    found = values[0].lower() if len(values) == 1 else None
    match = re.match(r"/obiava-([a-z0-9]{6,64})(?:[-/]|$)", parsed.path.lower())
    if match:
        found = match.group(1)
    supplied = str(identifier).lower().removeprefix("imot-") if identifier else None
    if found is None:
        raise ValueError("Offer URL has no recognized stable source ID")
    if not OFFER_ID.fullmatch(found) or (supplied and supplied != found):
        raise ValueError("Conflicting offer URL and identifier")
    # Preserve an observed modern source path; do not invent a slug-less route.
    # For legacy links retain the documented act/adv URL while dropping trackers.
    canonical = "https://www.imot.bg" + parsed.path if match else f"https://www.imot.bg/pcgi/imot.cgi?act=5&adv={found}"
    return found, canonical


def timestamp(value, *, date_only=False):
    if value is None:
        return None
    if isinstance(value, datetime):
        item = value
    else:
        raw = str(value).strip()
        try:
            item = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    # Naive workbook modification dates describe a local source date, not UTC.
    if date_only or item.tzinfo is None:
        return item.date().isoformat()
    return item.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (float, int)):
        answer = float(value)
    else:
        value = str(value).replace("\xa0", "").replace(" ", "").strip()
        if not re.fullmatch(r"\d+(?:[.,]\d+)?", value):
            return None
        answer = float(value.replace(",", "."))
    return answer if math.isfinite(answer) and answer > 0 else None


def validate_descriptor(item, maximum):
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        raise ValueError("Missing bounded file descriptor")
    path = PurePosixPath(item["path"])
    if path.is_absolute() or len(path.parts) != 1 or path.name in {".", ".."}:
        raise ValueError("Unsafe snapshot file path")
    if type(item.get("bytes")) is not int or not 1 <= item["bytes"] <= maximum or not HEX64.fullmatch(str(item.get("sha256", ""))):
        raise ValueError("Invalid snapshot descriptor size or hash")


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or type(manifest.get("version")) is not int or manifest["version"] != VERSION or not HEX32.fullmatch(str(manifest.get("snapshot_id", ""))):
        raise ValueError("Unsupported market snapshot")
    if manifest.get("mode") not in {"historical_bootstrap", "daily"} or timestamp(manifest.get("generated_at")) is None:
        raise ValueError("Invalid market capture mode or time")
    if manifest["mode"] == "daily" and manifest.get("capture", {}).get("complete") is not True:
        raise ValueError("Incomplete daily capture must not be published")
    if manifest["mode"] == "daily":
        completion = manifest.get("capture", {}).get("completion", {})
        integers = [completion.get(key) for key in ("source_count", "completed_source_count", "expected_row_count", "captured_row_count", "total_unique")]
        if any(type(value) is not int or value < 0 for value in integers) or integers[0] < 1 or integers[0] != integers[1] or integers[2] != integers[3] or integers[4] != manifest.get("counts", {}).get("listing_count"):
            raise ValueError("Daily market completion counts do not reconcile")
        if completion.get("evidence_location") != "state.audit.completion" or not HEX64.fullmatch(str(completion.get("evidence_sha256", ""))):
            raise ValueError("Daily market completion evidence is missing")
    validate_descriptor(manifest.get("summary_file"), MAX_SUMMARY_BYTES)
    validate_descriptor(manifest.get("state_file"), MAX_STATE_BYTES)
    shards = manifest.get("listing_shards")
    if not isinstance(shards, list) or not 1 <= len(shards) <= MAX_SHARDS:
        raise ValueError("Invalid bounded listing shard count")
    paths = set()
    count = 0
    for item in shards:
        validate_descriptor(item, MAX_SHARD_BYTES)
        if not re.fullmatch(r"listings-\d{3}\.json", item["path"]) or item["path"] in paths or type(item.get("count")) is not int or not 0 <= item["count"] <= SHARD_ROWS:
            raise ValueError("Invalid listing shard descriptor")
        paths.add(item["path"])
        count += item["count"]
    if not 0 <= count <= MAX_LISTINGS or count != manifest.get("counts", {}).get("listing_count"):
        raise ValueError("Listing counts do not reconcile")


def validate_snapshot(output):
    """Normal producer validation: all hashes, counts, identity and public schema."""
    root = Path(output)
    pointer = json.loads((root / "market-active.json").read_text(encoding="utf-8"))
    identifier = pointer.get("snapshot_id")
    if type(pointer.get("version")) is not int or pointer["version"] != VERSION or not HEX32.fullmatch(str(identifier)) or pointer.get("manifest_path") != f"market-snapshots/{identifier}/manifest.json":
        raise ValueError("Invalid market active pointer")
    folder = root / "market-snapshots" / identifier
    payload = (folder / "manifest.json").read_bytes()
    if len(payload) > MAX_MANIFEST_BYTES or digest(payload) != pointer.get("manifest_sha256"):
        raise ValueError("Market manifest hash or size mismatch")
    manifest = json.loads(payload)
    validate_manifest(manifest)
    if manifest["snapshot_id"] != identifier:
        raise ValueError("Snapshot identity mismatch")
    identifiers = set()
    for desc in [manifest["summary_file"], manifest["state_file"], *manifest["listing_shards"]]:
        data = (folder / desc["path"]).read_bytes()
        if len(data) != desc["bytes"] or digest(data) != desc["sha256"]:
            raise ValueError("Market snapshot file mismatch")
        content = json.loads(data)
        if content.get("snapshot_id") != identifier:
            raise ValueError("Market file belongs to another snapshot")
        if desc["path"] == manifest["state_file"]["path"] and manifest["mode"] == "daily":
            completion = manifest["capture"]["completion"]
            evidence = content.get("audit", {}).get("completion")
            if not isinstance(evidence, dict) or digest(json_bytes(evidence)) != completion["evidence_sha256"]:
                raise ValueError("Private daily completion evidence hash mismatch")
            sources = evidence.get("sources")
            if not isinstance(sources, list) or len(sources) != completion["source_count"] or evidence.get("total_unique") != completion["total_unique"]:
                raise ValueError("Private daily completion source count mismatch")
            if any(type(x.get("expected_count")) is not int or type(x.get("captured_count")) is not int or x["expected_count"] != x["captured_count"] or x["expected_count"] < 0 for x in sources):
                raise ValueError("Private daily completion contains incomplete source evidence")
            if sum(x["expected_count"] for x in sources) != completion["expected_row_count"] or sum(x["captured_count"] for x in sources) != completion["captured_row_count"]:
                raise ValueError("Private daily source totals mismatch")
        if "count" in desc:
            offers = content.get("listings")
            if not isinstance(offers, list) or len(offers) != desc["count"]:
                raise ValueError("Shard row count mismatch")
            for offer in offers:
                if not isinstance(offer, dict) or set(offer) - PUBLIC_FIELDS or not OFFER_ID.fullmatch(str(offer.get("id", ""))) or offer["id"] in identifiers:
                    raise ValueError("Invalid, duplicate or overbroad public offer")
                identifiers.add(offer["id"])
                if canonical_offer_id(offer.get("url"), offer["id"])[0] != offer["id"]:
                    raise ValueError("Canonical offer URL mismatch")
    if len(identifiers) != manifest["counts"]["listing_count"]:
        raise ValueError("Market listing count mismatch")
    return pointer, manifest
