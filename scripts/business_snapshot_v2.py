"""Bounded address/parcel business evidence with explicitly distinct match levels."""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import date
import hashlib
import json
import re
from pathlib import Path
from uuid import uuid4

ADDRESS_ID = re.compile(r"address-[a-f0-9]{24}")
ADDRESS_SHARD = re.compile(r"addresses-[0-9]{3}\.json")
REFERENCE_ID = re.compile(r"[a-zA-Z0-9._:-]{1,80}")
METHODS = {"cadastre_address", "municipal_parcel", "municipal_address"}


def base_module():
    import refresh_business_addresses
    return refresh_business_addresses


def validate_municipal_source(value):
    from municipal_business_addresses import SOURCES, trusted_url, json_bytes, LICENSE_URL, POLICY_URL
    b = base_module()
    required = {"version", "sources", "coordinate_crs", "crs_basis", "publisher_crs_explicit", "source_revision"}
    if not isinstance(value, dict) or set(value) != required or type(value["version"]) is not int or value["version"] != 1 or value["coordinate_crs"] != "OGC:CRS84" or value["crs_basis"] != "GeoJSON_default_CRS84" or value["publisher_crs_explicit"] is not False or not isinstance(value.get('source_revision'), str) or not b.HEX64.fullmatch(value["source_revision"]):
        raise ValueError("Invalid municipal source provenance")
    if not isinstance(value["sources"], list) or len(value["sources"]) != 2:
        raise ValueError("Both municipal sources are required")
    fields = {"dataset", "resource_id", "url", "format", "data_as_of", "retrieved_at", "bytes", "sha256", "metadata_sha256", "license_id", "license_url", "policy_url"}
    for source, spec in zip(value["sources"], SOURCES.values(), strict=True):
        if not isinstance(source, dict) or set(source) != fields or source["dataset"] != spec["dataset"] or source["resource_id"] != spec["resource_id"] or source["format"] != spec["format"] or not trusted_url(source["url"], spec["resource_id"]):
            raise ValueError("Municipal source identity changed")
        if source["license_id"] != "CC-BY-4.0" or source["license_url"] != LICENSE_URL or source["policy_url"] != POLICY_URL or type(source["bytes"]) is not int or not 1 <= source["bytes"] <= 8 * 1024 * 1024 or not all(isinstance(source.get(k), str) and b.HEX64.fullmatch(source[k]) for k in ("sha256", "metadata_sha256")):
            raise ValueError("Municipal source evidence invalid")
        if source["retrieved_at"] is not None and not b.timestamp_valid(source["retrieved_at"]):
            raise ValueError("Invalid municipal retrieval date")
        if not isinstance(source["data_as_of"], str) or (source["data_as_of"] and not re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", source["data_as_of"])):
            raise ValueError("Invalid municipal source date")
        if source['data_as_of']:
            date.fromisoformat(source['data_as_of'])
    expected = hashlib.sha256(json_bytes([{k: x[k] for k in ("resource_id", "sha256", "metadata_sha256")} for x in value["sources"]])).hexdigest()
    if expected != value["source_revision"]:
        raise ValueError("Municipal source revision mismatch")
    return value


def validate_company(value, address_only=False):
    b = base_module()
    if not isinstance(value, dict) or set(value) != b.COMPANY_FIELDS | {"match_method", "reference_ids"}:
        raise ValueError("Invalid public v2 company fields")
    if any(not isinstance(value[key], str) for key in b.COMPANY_FIELDS):
        raise ValueError('Public company fields must be text')
    if not b.valid_uic(value["uic"]) or not all(isinstance(value[k], str) and b.safe_text(value[k], b.TEXT_LIMITS[k]) == value[k] for k in ("name", "legal_form", "registered_address")):
        raise ValueError("Invalid public company text/identity")
    if not b.corporate_form(value["legal_form"]) or (value["activity"] and b.safe_text(value["activity"], 500, True) != value["activity"]) or value["status"] != "not_verified" or (value["as_of"] and (not re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", value["as_of"]) or b.as_of_date('.'.join(reversed(value["as_of"].split('-')))) != value["as_of"])) or value["source_url"] != b.source_url(value["uic"]):
        raise ValueError("Invalid public company evidence")
    if not isinstance(value['match_method'], str) or value["match_method"] not in METHODS or (value["match_method"] == "municipal_address") != address_only:
        raise ValueError("Company match level differs from its location")
    refs = value["reference_ids"]
    if not isinstance(refs, list) or len(refs) > 32 or any(not isinstance(x, str) or not REFERENCE_ID.fullmatch(x) for x in refs) or len(set(refs)) != len(refs) or (bool(refs) != (value["match_method"] != "cadastre_address")):
        raise ValueError("Invalid municipal reference identifiers")


def selected_raw_addresses(directory, source, selected, included):
    """Recover only registered-office text for selected observations, transiently."""
    b = base_module()
    eligible = {uic for uic, (_, _, _, _, reason) in selected.items() if reason in ("", "missing_or_unparseable_street_number") and uic not in included}
    result = defaultdict(set)
    for part in source["files"]:
        with (directory / part["name"]).open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                uic = b.clean(row.get(b.FIELD_MAP["uic"]))
                if uic not in eligible:
                    continue
                candidate = b.candidate(row, Counter())
                if candidate is not None and candidate[1:3] == selected[uic][:2]:
                    result[uic].add(b.clean(row.get(b.FIELD_MAP["address"])))
    return result


def enrich(directory, source, selected, parcels, args, counts):
    from municipal_business_addresses import capture_reference, resolve_company_address, safe_label
    from business_parcel_linker import build_index
    b = base_module()
    reference, provenance = capture_reference(args.municipal_cache, offline=args.municipal_offline)
    validate_municipal_source(provenance)
    included = {c["uic"] for companies in parcels.values() for c in companies}
    counts["exact_cadastral_address_companies"] = len(included)
    for identifier in parcels:
        parcels[identifier] = [dict(c, match_method="cadastre_address", reference_ids=[]) for c in parcels[identifier]]
    raw = selected_raw_addresses(directory, source, selected, included)
    print("Building verified municipal-to-parcel spatial index", flush=True)
    linker = build_index(args.cadastre_manifest, args.cadastre_archives)
    addresses = {}
    cached = {}
    for uic, variants in sorted(raw.items()):
        counts["municipal_lookup_companies"] += 1
        if not variants or len(variants) > 4:
            counts["municipal_ambiguous_company_variants"] += 1
            continue
        variant_candidates = [resolve_company_address(variant, reference) for variant in variants]
        if any(not rows for rows in variant_candidates):
            counts['municipal_address_not_found'] += 1
            continue
        candidates = [candidate for rows in variant_candidates for candidate in rows]
        if not candidates:
            counts["municipal_address_not_found"] += 1
            continue
        labels = {c["address_label"] for c in candidates}
        refs = sorted({x for c in candidates for x in c["reference_ids"]})
        if len(labels) != 1 or not refs or len(refs) > 32 or any(not isinstance(x, str) or not REFERENCE_ID.fullmatch(x) for x in refs):
            counts["municipal_ambiguous_address"] += 1
            continue
        label = next(iter(labels))
        if not safe_label(label) or b.safe_text(label, 240) != label:
            counts["municipal_unsafe_address_label"] += 1
            continue
        point_rows = { (float(p["lat"]), float(p["lng"]), str(p["reference_id"])): p for c in candidates for p in c["points"] }
        coordinates = {(key[0], key[1]) for key in point_rows}
        cache_key = tuple(sorted(point_rows))
        if cache_key not in cached:
            cached[cache_key] = linker.resolve(list(point_rows.values()))
        link = cached[cache_key]
        company = dict(selected[uic][2], registered_address=label, reference_ids=refs)
        if any(c["method"] == "municipal_historical_street_number" for c in candidates):
            counts["municipal_historical_alias_companies"] += 1
        if any(c["method"] == "municipal_quarter_block" for c in candidates):
            counts["municipal_block_companies"] += 1
        if link["status"] == "unique":
            company["match_method"] = "municipal_parcel"
            validate_company(company)
            parcels.setdefault(link["cadastral_id"], []).append(company)
            counts["municipal_parcel_companies"] += 1
        elif len(coordinates) == 1:
            # The official address remains useful even on a boundary/street;
            # no parcel identifier or construction record is attached to it.
            lat, lng = next(iter(coordinates))
            if not b.valid_map_point({"lat": lat, "lng": lng}):
                raise ValueError("Municipal address point outside Sofia bounds")
            identifier = "address-" + hashlib.sha256(b.json_bytes([label, lat, lng])).hexdigest()[:24]
            company["match_method"] = "municipal_address"
            validate_company(company, True)
            group = addresses.setdefault(identifier, {"address_label": label, "lat": lat, "lng": lng, "companies": []})
            if group["address_label"] != label or group["lat"] != lat or group["lng"] != lng:
                raise ValueError("Address group hash collision")
            group["companies"].append(company)
            counts["municipal_address_only_" + re.sub(r'[^a-z_]', '_', link["status"])] += 1
        else:
            counts["municipal_multilocation_unresolved"] += 1
    for companies in parcels.values():
        companies.sort(key=lambda c: c["uic"])
    for group in addresses.values():
        group["companies"].sort(key=lambda c: c["uic"])
    counts["matched_companies"] = sum(len(c) for c in parcels.values())
    counts["matched_parcels"] = len(parcels)
    counts["matched_unique_addresses"] = len({c["registered_address"] for rows in parcels.values() for c in rows})
    counts.setdefault("municipal_parcel_companies", 0)
    counts["address_only_companies"] = sum(len(g["companies"]) for g in addresses.values())
    counts["address_only_locations"] = len(addresses)
    return parcels, addresses, provenance


def write_snapshot(output, parcels, addresses, source, cadastre, counts, points, provenance):
    b = base_module()
    snapshot_id = uuid4().hex
    directory = output / "business-snapshots" / snapshot_id
    directory.mkdir(parents=True, exist_ok=False)
    shards, parcel_index, address_shards, address_index, search = {}, {}, {}, {}, []
    def write_groups(groups, prefix, descriptors, add_index):
        current, size, number = {}, 2, 0
        def flush():
            nonlocal current, size, number
            if not current:
                return
            if number >= 512:
                raise ValueError("Business shard count limit exceeded")
            filename = f"{prefix}-{number:03d}.json"
            payload = b.json_bytes(current)
            if len(payload) > b.MAX_SHARD_BYTES:
                raise ValueError("Business shard size limit exceeded")
            b.write_new(directory / filename, payload)
            descriptors[filename] = b.descriptor(payload)
            for key, value in current.items():
                add_index(key, value, filename)
            current, size, number = {}, 2, number + 1
        for key, value in sorted(groups.items()):
            entry = len(b.json_bytes({key: value})) - 2
            if entry + 2 > b.MAX_SHARD_BYTES:
                raise ValueError("One business location exceeds its shard limit")
            if current and size + entry + 1 > b.MAX_SHARD_BYTES:
                flush()
            current[key] = value
            size += entry + int(len(current) > 1)
        flush()
    def parcel_entry(key, companies, filename):
        parcel_index[key] = filename
        search.extend({k: c[k] for k in ("uic", "name", "registered_address")} | {"cadastral_id": key} for c in companies)
    def address_entry(key, group, filename):
        address_index[key] = {"file": filename, "lat": group["lat"], "lng": group["lng"], "label": group["address_label"], "company_count": len(group["companies"])}
        search.extend({k: c[k] for k in ("uic", "name", "registered_address")} | {"address_id": key} for c in group["companies"])
    write_groups(parcels, "companies", shards, parcel_entry)
    write_groups(addresses, "addresses", address_shards, address_entry)
    manifest = {"version": 2, "snapshot_id": snapshot_id, "generated_at": b.utc_now(), "source": source, "cadastre": cadastre, "municipal_source": provenance,
                "counts": dict(counts), "shards": shards, "address_shards": address_shards}
    for key, filename, value in (("parcel_index", "parcel-index.json", parcel_index), ("search_index", "search-index.json", search), ("points_index", "points-index.json", points), ("address_index", "address-index.json", address_index)):
        payload = b.json_bytes(value)
        if len(payload) > b.MAX_INDEX_BYTES:
            raise ValueError(f"Business {key} exceeds its index byte limit: {len(payload)}")
        b.write_new(directory / filename, payload)
        manifest[key] = b.descriptor(payload, filename)
    mapped = sum(len(parcels[cid]) for cid in points)
    manifest["counts"].update({"mapped_business_parcels": len(points), "unmapped_business_parcels": len(parcels) - len(points), "mapped_companies": mapped,
        "unmapped_companies": counts["matched_companies"] - mapped, "located_companies": mapped + counts["address_only_companies"], "located_locations": len(points) + len(addresses)})
    payload = b.json_bytes(manifest)
    if len(payload) > b.MAX_MANIFEST_BYTES:
        raise ValueError("Business v2 manifest byte limit exceeded")
    b.write_new(directory / "manifest.json", payload)
    pointer = {"version": 1, "snapshot_id": snapshot_id, "manifest_sha256": hashlib.sha256(payload).hexdigest()}
    validate_snapshot(output, snapshot_id, pointer_override=pointer)
    pointer_path = output / "business-active.json"
    if pointer_path.exists():
        temporary = output / f"business-active.{snapshot_id}.pending.json"
        b.write_new(temporary, b.json_bytes(pointer))
        temporary.replace(pointer_path)
    else:
        b.write_new(pointer_path, b.json_bytes(pointer))
    return manifest


def validate_snapshot(root, snapshot_id=None, *, pointer_override=None):
    b = base_module()
    pointer = pointer_override if pointer_override is not None else b.read_json(root / "business-active.json", 1024)
    if not isinstance(pointer, dict) or set(pointer) != {"version", "snapshot_id", "manifest_sha256"} or type(pointer['version']) is not int or pointer["version"] != 1 or not isinstance(pointer["snapshot_id"], str) or not b.HEX32.fullmatch(pointer["snapshot_id"]) or not isinstance(pointer.get('manifest_sha256'), str) or not b.HEX64.fullmatch(pointer["manifest_sha256"]):
        raise ValueError("Invalid business v2 pointer")
    snapshot_id = snapshot_id or pointer["snapshot_id"]
    if not isinstance(snapshot_id, str) or not b.HEX32.fullmatch(snapshot_id):
        raise ValueError("Invalid business snapshot identifier")
    directory = root / "business-snapshots" / snapshot_id
    if root.is_symlink() or (root / "business-snapshots").is_symlink() or directory.is_symlink():
        raise ValueError("Linked business snapshot directory")
    path = directory / "manifest.json"
    manifest = b.read_json(path, b.MAX_MANIFEST_BYTES)
    if snapshot_id == pointer["snapshot_id"] and b.file_digest(path) != pointer["manifest_sha256"]:
        raise ValueError("Business manifest pointer hash mismatch")
    fields = {"version", "snapshot_id", "generated_at", "source", "cadastre", "municipal_source", "counts", "shards", "address_shards", "parcel_index", "search_index", "points_index", "address_index"}
    if not isinstance(manifest, dict) or set(manifest) != fields or manifest["version"] != 2 or manifest["snapshot_id"] != snapshot_id or not b.timestamp_valid(manifest["generated_at"]):
        raise ValueError("Invalid business v2 manifest")
    b.validate_source(manifest["source"])
    validate_municipal_source(manifest["municipal_source"])
    cadastre = manifest["cadastre"]
    if not isinstance(cadastre, dict) or set(cadastre) != {"manifest_sha256", "snapshot_id", "captured_from", "captured_to", "sources"} or not b.HEX64.fullmatch(cadastre.get("manifest_sha256", "")) or not b.HEX32.fullmatch(cadastre.get("snapshot_id", "")) or not all(b.timestamp_valid(cadastre.get(k)) for k in ("captured_from", "captured_to")) or not isinstance(cadastre["sources"], list) or len(cadastre["sources"]) != 24:
        raise ValueError("Invalid cadastral source provenance")
    for index, source in enumerate(cadastre["sources"]):
        if not isinstance(source, dict) or set(source) != {"code", "source_url", "zip_sha256", "captured_at"} or source["code"] != f"sofia-district-{index:02d}" or not isinstance(source["source_url"], str) or not source["source_url"].startswith('https://kais.cadastre.bg/bg/OpenData/Download?path=') or not b.HEX64.fullmatch(source.get("zip_sha256", "")) or not b.timestamp_valid(source.get("captured_at")):
            raise ValueError("Invalid cadastral source")
    counts = manifest["counts"]
    if not isinstance(counts, dict) or len(counts) > 120 or any(not re.fullmatch(r"[a-z_]{1,80}", key) or type(value) is not int or not 0 <= value <= 5_000_000 for key, value in counts.items()):
        raise ValueError("Invalid business coverage counts")
    allowed, total_bytes = {"manifest.json"}, path.stat().st_size
    def load(meta, name, maximum, with_file=True):
        nonlocal total_bytes
        expected = {"bytes", "sha256"} | ({"file"} if with_file else set())
        if not isinstance(meta, dict) or set(meta) != expected or (with_file and meta["file"] != name) or type(meta.get("bytes")) is not int or not 2 <= meta["bytes"] <= min(maximum, b.MAX_FILE_BYTES) or not b.HEX64.fullmatch(meta.get("sha256", "")):
            raise ValueError("Invalid business v2 file descriptor")
        target = directory / name
        if target.is_symlink() or not target.is_file() or target.stat().st_size != meta["bytes"] or b.file_digest(target) != meta["sha256"]:
            raise ValueError("Business v2 file hash or length mismatch")
        total_bytes += meta["bytes"]
        if total_bytes > b.MAX_SNAPSHOT_BYTES:
            raise ValueError("Business v2 snapshot total byte limit exceeded")
        allowed.add(name)
        return b.read_json(target, maximum)
    parcel_index = load(manifest["parcel_index"], "parcel-index.json", b.MAX_INDEX_BYTES)
    address_index = load(manifest["address_index"], "address-index.json", b.MAX_INDEX_BYTES)
    search = load(manifest["search_index"], "search-index.json", b.MAX_INDEX_BYTES)
    points = load(manifest["points_index"], "points-index.json", b.MAX_POINTS_BYTES)
    if not isinstance(parcel_index, dict) or not isinstance(address_index, dict) or not isinstance(search, list) or not isinstance(points, dict) or len(search) > 2_000_000 or any(cid not in parcel_index or not b.valid_map_point(point) for cid, point in points.items()):
        raise ValueError("Invalid business v2 indices")
    seen, expected_search, parcel_ids, address_ids = set(), [], set(), set()
    actual = Counter()
    for group_name, pattern, is_address in (("shards", b.SHARD_NAME, False), ("address_shards", ADDRESS_SHARD, True)):
        descriptors = manifest[group_name]
        if not isinstance(descriptors, dict) or len(descriptors) > 512:
            raise ValueError("Invalid v2 shard collection")
        for filename, metadata in descriptors.items():
            if not isinstance(filename, str) or not pattern.fullmatch(filename):
                raise ValueError("Invalid v2 shard name")
            groups = load(metadata, filename, b.MAX_SHARD_BYTES, False)
            if not isinstance(groups, dict) or not groups:
                raise ValueError("Empty v2 shard")
            for identifier, group in groups.items():
                if is_address:
                    if not ADDRESS_ID.fullmatch(identifier) or identifier in address_ids or not isinstance(group, dict) or set(group) != {"address_label", "lat", "lng", "companies"} or not b.valid_map_point({k: group[k] for k in ("lat", "lng")}):
                        raise ValueError("Invalid official address group")
                    address_ids.add(identifier)
                    companies = group["companies"]
                    expected_index = {"file": filename, "lat": group["lat"], "lng": group["lng"], "label": group["address_label"], "company_count": len(companies)}
                    if address_index.get(identifier) != expected_index:
                        raise ValueError("Official address index differs from shard")
                else:
                    if not b.CAD_ID.fullmatch(identifier) or identifier in parcel_ids or parcel_index.get(identifier) != filename:
                        raise ValueError("Invalid parcel index membership")
                    parcel_ids.add(identifier)
                    companies = group
                if not isinstance(companies, list) or not companies:
                    raise ValueError("Invalid v2 company list")
                for company in companies:
                    validate_company(company, is_address)
                    if company["uic"] in seen or (is_address and company["registered_address"] != group["address_label"]):
                        raise ValueError("Duplicate or incorrectly grouped company")
                    seen.add(company["uic"])
                    actual["address_only_companies" if is_address else "matched_companies"] += 1
                    if not is_address:
                        actual["exact_cadastral_address_companies" if company["match_method"] == "cadastre_address" else "municipal_parcel_companies"] += 1
                        if identifier in points:
                            actual["mapped_companies"] += 1
                    expected_search.append({k: company[k] for k in ("uic", "name", "registered_address")} | {"address_id" if is_address else "cadastral_id": identifier})
    if set(parcel_index) != parcel_ids or set(address_index) != address_ids or search != expected_search or counts.get("sofia_candidates", 0) < len(seen):
        raise ValueError("Business v2 search/count/index mismatch")
    expected_counts = {"matched_parcels": len(parcel_ids), "address_only_locations": len(address_ids), "mapped_business_parcels": len(points), "unmapped_business_parcels": len(parcel_ids) - len(points),
        "unmapped_companies": actual["matched_companies"] - actual["mapped_companies"], "located_companies": actual["mapped_companies"] + actual["address_only_companies"], "located_locations": len(points) + len(address_ids)}
    for key in ("matched_companies", "mapped_companies", "address_only_companies", "exact_cadastral_address_companies", "municipal_parcel_companies"):
        expected_counts[key] = actual[key]
    if any(counts.get(key) != value for key, value in expected_counts.items()) or {p.name for p in directory.iterdir()} != allowed:
        raise ValueError("Business v2 coverage/files do not reconcile")
    return manifest
