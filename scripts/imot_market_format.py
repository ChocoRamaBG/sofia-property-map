#!/usr/bin/env python3
"""Bounded immutable asking-price market format shared by producer/publisher.

Only allowlisted factual listing fields and public professional agency contact
details are public. Descriptions, private-seller contacts and photos stay out.
"""
from __future__ import annotations

import hashlib
import gzip
import io
import json
import math
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlsplit

VERSION = 1
MAX_LISTINGS = 50000
MAX_SHARDS = 512
SHARD_ROWS = 250
MAX_SHARD_BYTES = 256 * 1024
MAX_SUMMARY_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_STATE_BYTES = 64 * 1024 * 1024
MAX_STATE_COMPRESSED_BYTES = 9 * 1024 * 1024
MAX_CAPTURE_BYTES = 96 * 1024 * 1024
TOP_OFFERS_PREVIEW_LIMIT = 30
DAILY_CANDIDATES_PREVIEW_LIMIT = 50
HEX32 = re.compile(r"[a-f0-9]{32}")
HEX64 = re.compile(r"[a-f0-9]{64}")
OFFER_ID = re.compile(r"[a-z0-9]{6,64}")
PUBLIC_FIELDS = frozenset({
    "id", "url", "neighborhood_key", "neighborhood_bg", "type_key", "type_bg",
    "area_sqm", "price_eur", "eur_per_sqm", "price_currency", "vat_basis",
    "construction_year", "construction_cohort", "last_modified_at", "observed_at",
    "first_seen_at", "comparison", "change", "historical", "quality_flags",
    "floor_bg", "construction_label_bg", "address_bg",
    "price_total_derived", "quoted_eur_per_sqm",
    "seller_type", "seller_evidence", "seller_checked_at", "location", "analysis", "asking_estimate", "agency", "property_features",
})
EVIDENCE_FIELDS = frozenset({"neighborhood", "type", "vat_basis", "construction_age", "construction_type", "completion_stage", "area_basis", "floor", "furnishing", "condition", "elevator", "area_tolerance", "street"})


def safe_public_url(value, *, profile=False):
    if not isinstance(value, str) or not 1 <= len(value.encode('utf-8')) <= 500 or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        return False
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.port is not None:
        return False
    return bool(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.imot\.bg", host) and host != "www.imot.bg") if profile else bool(re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}", host))


def validate_public_enrichment(offer):
    """Closed schemas exclude descriptions and private-seller contact details."""
    if "seller_type" in offer:
        if (offer.get("seller_type"), offer.get("seller_evidence")) not in {
            ("agency", "agency_profile"), ("private", "explicit_private_claim"),
            ("unknown", "not_reported"), ("unknown", "conflicting_signals"),
        }:
            raise ValueError("Invalid public seller evidence")
        if offer.get("seller_checked_at") is not None and timestamp(offer["seller_checked_at"]) is None:
            raise ValueError("Invalid seller evidence date")
    agency = offer.get("agency")
    if agency is not None:
        if not isinstance(agency, dict) or set(agency) != {"name", "profile_url", "phone", "website", "checked_at", "evidence"} or offer.get("seller_type") != "agency" or agency["evidence"] != "professional_profile":
            raise ValueError("Invalid professional agency schema")
        if not isinstance(agency["name"], str) or not 1 <= len(agency["name"]) <= 120 or not safe_public_url(agency["profile_url"], profile=True) or (agency["website"] is not None and not safe_public_url(agency["website"])):
            raise ValueError("Invalid professional agency identity")
        if agency["phone"] is not None and (not isinstance(agency["phone"], str) or not re.fullmatch(r"\+?\d{7,15}", agency["phone"])):
            raise ValueError("Invalid professional agency phone")
        if timestamp(agency["checked_at"]) is None:
            raise ValueError("Invalid professional agency evidence date")
    features = offer.get("property_features")
    if features is not None:
        if not isinstance(features, dict) or set(features) != {"construction_type", "furnishing", "building_year", "year_basis", "floor_number", "total_floors", "elevator", "checked_at", "source"}:
            raise ValueError("Invalid advertised property features")
        allowed = {"construction_type": {"brick", "panel", "epk", "monolithic", "other", "unknown"}, "furnishing": {"furnished", "partial", "unfurnished", "unknown"}, "year_basis": {"built", "commissioned", "planned", "unknown"}, "elevator": {"yes", "no", "unknown"}, "source": {"card", "description"}}
        if any(features[key] not in values for key, values in allowed.items()):
            raise ValueError("Invalid advertised feature values")
        for field, minimum, maximum in (("building_year", 1800, 2100), ("floor_number", -5, 100), ("total_floors", 1, 100)):
            value = features[field]
            if value is not None and (type(value) is not int or not minimum <= value <= maximum):
                raise ValueError("Invalid advertised feature number")
        if (features["building_year"] is None and features["year_basis"] != "unknown") or (features["floor_number"] is not None and features["total_floors"] is not None and features["floor_number"] > features["total_floors"]):
            raise ValueError("Conflicting advertised feature numbers")
        if features["checked_at"] is not None and timestamp(features["checked_at"]) is None:
            raise ValueError("Invalid advertised features date")
    location = offer.get("location")
    if location is not None:
        fields = {"key", "lat", "lng", "precision", "label_bg", "radius_m", "method", "source_url", "reference_date", "evidence"}
        if not isinstance(location, dict) or set(location) != fields or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", str(location["key"])):
            raise ValueError("Invalid public location schema")
        numbers = (location["lat"], location["lng"], location["radius_m"])
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in numbers) or not (42.4 <= numbers[0] <= 43 and 22.8 <= numbers[1] <= 24 and 200 <= numbers[2] <= 12000):
            raise ValueError("Invalid approximate location bounds")
        if location["precision"] not in {"street", "neighborhood"} or location["method"] != "cadastre_" + location["precision"] + "_reference" or location["source_url"] != "https://kais.cadastre.bg/bg/OpenData" or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(location["reference_date"])) or location["evidence"] not in {"listed_address", "description_street", "listed_neighborhood"} or not isinstance(location["label_bg"], str) or not 1 <= len(location["label_bg"]) <= 180:
            raise ValueError("Invalid public location provenance")
    analysis = offer.get("analysis")
    if analysis is not None:
        fields = {"completion_stage", "condition", "area_basis", "risk_flags", "checked_at", "description_analyzed"}
        if not isinstance(analysis, dict) or set(analysis) != fields or analysis["completion_stage"] not in {"planned", "completed", "unknown"} or analysis["condition"] not in {"renovated", "needs_renovation", "unknown"} or analysis["area_basis"] not in {"net", "gross", "terrace_included", "unknown"} or type(analysis["description_analyzed"]) is not bool:
            raise ValueError("Invalid advertised analysis schema")
        risks = analysis["risk_flags"]
        if not isinstance(risks, list) or len(risks) > 5 or any(not isinstance(x, str) or x not in {"share_sale", "auction", "tenanted", "nonresidential", "mandatory_extra_cost"} for x in risks) or len(set(risks)) != len(risks):
            raise ValueError("Invalid advertised risk flags")
        if analysis["checked_at"] is not None and timestamp(analysis["checked_at"]) is None:
            raise ValueError("Invalid analysis date")
    estimate = offer.get("asking_estimate")
    if estimate is not None:
        numeric_fields = {"median_eur_per_sqm", "p25_eur_per_sqm", "p75_eur_per_sqm", "indicated_price_eur", "range_low_eur", "range_high_eur"}
        expected = numeric_fields | {"status", "method_version", "peer_count", "location_basis"}
        if isinstance(estimate, dict) and estimate.get("method_version") == 3:
            expected |= {"evidence"}
        if not isinstance(estimate, dict) or set(estimate) != expected or estimate["method_version"] not in {2, 3} or estimate["status"] not in {"available", "insufficient_comparables", "needs_review", "invalid_inputs"} or estimate["location_basis"] not in {"street", "neighborhood"} or type(estimate["peer_count"]) is not int or not 0 <= estimate["peer_count"] <= MAX_LISTINGS:
            raise ValueError("Invalid asking estimate schema")
        if any(estimate[k] is not None and number(estimate[k]) is None for k in numeric_fields):
            raise ValueError("Invalid asking estimate numbers")
        if estimate["status"] == "available" and (estimate["peer_count"] < 8 or any(estimate[k] is None for k in numeric_fields)):
            raise ValueError("Unsupported available estimate")
        if estimate["range_low_eur"] is not None and not estimate["range_low_eur"] <= estimate["indicated_price_eur"] <= estimate["range_high_eur"]:
            raise ValueError("Inconsistent asking estimate range")
        if estimate["method_version"] == 3:
            evidence = estimate["evidence"]
            if not isinstance(evidence, dict) or set(evidence) != {"quality", "matched_fields", "missing_fields", "spread_pct", "price_position", "duplicate_peer_count", "unknown_physical_duplicates"} or evidence["quality"] not in {"detailed", "limited", "insufficient"} or evidence["price_position"] not in {"below_range", "within_range", "above_range", "unavailable"} or evidence["unknown_physical_duplicates"] is not True:
                raise ValueError("Invalid asking estimate evidence")
            sets = []
            for field in ("matched_fields", "missing_fields"):
                values = evidence[field]
                if not isinstance(values, list) or any(not isinstance(value, str) or value not in EVIDENCE_FIELDS for value in values) or len(values) != len(set(values)):
                    raise ValueError("Invalid estimate evidence fields")
                sets.append(set(values))
            if sets[0] & sets[1] or sets[0] | sets[1] != EVIDENCE_FIELDS:
                raise ValueError("Incomplete estimate evidence fields")
            spread = evidence["spread_pct"]
            if spread is not None and (type(spread) not in {int, float} or not math.isfinite(spread) or spread < 0):
                raise ValueError("Invalid estimate spread")
            if type(evidence["duplicate_peer_count"]) is not int or not 0 <= evidence["duplicate_peer_count"] <= MAX_LISTINGS:
                raise ValueError("Invalid estimate duplicate count")
            if estimate["status"] != "available" and evidence["price_position"] != "unavailable":
                raise ValueError("Unsupported estimate price position")


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


def validate_state_descriptor(item):
    if not isinstance(item, dict):
        raise ValueError("Missing private state descriptor")
    if item.get("path") == "state.json":
        validate_descriptor(item, MAX_STATE_BYTES)
        return
    if item.get("path") != "state.json.gz" or item.get("encoding") != "gzip":
        raise ValueError("Unsupported private state encoding")
    validate_descriptor(item, MAX_STATE_COMPRESSED_BYTES)
    if type(item.get("expanded_bytes")) is not int or not 1 <= item["expanded_bytes"] <= MAX_STATE_BYTES or not HEX64.fullmatch(str(item.get("expanded_sha256", ""))):
        raise ValueError("Invalid bounded expanded-state descriptor")


def read_state_payload(payload, descriptor):
    """Verify stored bytes then inflate at most 64 MiB for private processing."""
    validate_state_descriptor(descriptor)
    if len(payload) != descriptor["bytes"] or digest(payload) != descriptor["sha256"]:
        raise ValueError("Private state stored bytes mismatch")
    if descriptor["path"] == "state.json":
        return payload
    result, total = [], 0
    with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as stream:
        while True:
            chunk = stream.read(min(1024 * 1024, MAX_STATE_BYTES - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_STATE_BYTES:
                raise ValueError("Expanded private state exceeds its byte limit")
            result.append(chunk)
    expanded = b"".join(result)
    if len(expanded) != descriptor["expanded_bytes"] or digest(expanded) != descriptor["expanded_sha256"]:
        raise ValueError("Expanded private state integrity failed")
    return expanded


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
    validate_state_descriptor(manifest.get("state_file"))
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


def validate_summary_projection(summary):
    """The overview is a bounded projection, never the complete listing feed.

    Earlier immutable summaries have no projection marker and remain readable.
    New summaries make preview sizes and complete retrieval explicit, without
    duplicating every fine-grained comparison partition inside the overview.
    """
    projection = summary.get("methodology", {}).get("summary_projection")
    if projection is None:
        return
    expected = {"version": 2, "neighborhood_cohorts": "count_only", "listing_details_action": "listings",
                "top_offers_limit": TOP_OFFERS_PREVIEW_LIMIT,
                "daily_candidates_limit": DAILY_CANDIDATES_PREVIEW_LIMIT,
                "daily_candidates_filter": "daily_only=1"}
    if projection != expected:
        raise ValueError("Invalid summary projection contract")
    counts = summary.get("counts", {})
    total = counts.get("listing_count")
    if type(total) is not int or not 1 <= total <= MAX_LISTINGS:
        raise ValueError("Invalid summary listing count")
    for field in ("eligible_count", "daily_candidate_count"):
        if type(counts.get(field)) is not int or not 0 <= counts[field] <= total:
            raise ValueError("Invalid complete summary candidate count")
    if summary.get("daily_candidates_total") != counts["daily_candidate_count"]:
        raise ValueError("Daily candidate totals do not reconcile")
    for field, total_field, preview_field, limit in (
        ("top_offers", "eligible_count", "top_offers_preview_count", TOP_OFFERS_PREVIEW_LIMIT),
        ("daily_candidates", "daily_candidate_count", "daily_candidates_preview_count", DAILY_CANDIDATES_PREVIEW_LIMIT),
    ):
        rows = summary.get(field)
        expected_count = min(counts[total_field], limit)
        if not isinstance(rows, list) or len(rows) != expected_count or counts.get(preview_field) != expected_count:
            raise ValueError("Summary preview counts do not reconcile")
        seen = set()
        for offer in rows:
            if not isinstance(offer, dict) or set(offer) - PUBLIC_FIELDS or not OFFER_ID.fullmatch(str(offer.get("id", ""))) or offer["id"] in seen:
                raise ValueError("Invalid summary preview offer")
            validate_public_enrichment(offer)
            canonical_offer_id(offer.get("url"), offer["id"])
            seen.add(offer["id"])
    neighborhoods = summary.get("neighborhoods")
    if not isinstance(neighborhoods, list):
        raise ValueError("Invalid summary neighborhood statistics")
    cohorts = 0
    for row in neighborhoods:
        if (not isinstance(row, dict) or "cohorts" in row or type(row.get("cohort_count")) is not int
                or type(row.get("comparable_count")) is not int or not 0 <= row["cohort_count"] <= row["comparable_count"]):
            raise ValueError("Invalid compact neighborhood cohort count")
        cohorts += row["cohort_count"]
    if counts.get("comparison_cohort_count") != cohorts:
        raise ValueError("Summary cohort counts do not reconcile")


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
        decoded = read_state_payload(data, desc) if desc["path"] == manifest["state_file"]["path"] else data
        content = json.loads(decoded)
        if content.get("snapshot_id") != identifier:
            raise ValueError("Market file belongs to another snapshot")
        if desc["path"] == manifest["summary_file"]["path"]:
            validate_summary_projection(content)
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
                validate_public_enrichment(offer)
                identifiers.add(offer["id"])
                if canonical_offer_id(offer.get("url"), offer["id"])[0] != offer["id"]:
                    raise ValueError("Canonical offer URL mismatch")
    if len(identifiers) != manifest["counts"]["listing_count"]:
        raise ValueError("Market listing count mismatch")
    return pointer, manifest
