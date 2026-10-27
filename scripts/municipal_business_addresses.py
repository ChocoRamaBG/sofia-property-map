"""Bounded municipal address evidence. Never infers a parcel or property owner.

The resolver returns every exact municipal address candidate. Its caller must
independently check all retained points against official parcel geometry; a
candidate is not permission to select the first/nearest parcel.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
import ssl
import unicodedata
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from zipfile import ZipFile

from imot_location import street_name

HOST = "urbandata.sofia.bg"
POLICY_URL = "https://www.sofia.bg/bg/web/guest/urbanization-data"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
MAX_METADATA_BYTES = 1024 * 1024
MAX_ZIP_BYTES = 8 * 1024 * 1024
MAX_ADDRESS_BYTES = 64 * 1024 * 1024
MAX_ALIAS_BYTES = 2 * 1024 * 1024
MAX_FEATURES = 250000
MAX_ALIAS_ROWS = 20000
SOURCES = {
    "addresses": {"dataset": "address_sofia-zip", "resource_id": "7b32c5f8-5f25-4b24-92f9-43e265275587", "format": "GeoJSON", "zip_name": "addresses.zip", "member": "address_sofia.geojson"},
    "aliases": {"dataset": "streets_names_new_old-zip", "resource_id": "c3ec6293-b1b0-48b7-98ae-9693ae7abd77", "format": "CSV", "zip_name": "street-renamings.zip", "member": "streets_names_new_old.csv"},
}
CONTACT = re.compile(r"@|https?://|www\.|(?<!\w)(?:тел(?:ефон)?|факс|email|e-mail|е-мейл|егн|лнч)\s*[:.]", re.I)
STREET = re.compile(r"(?<![а-яa-z])(?P<kind>улица|ул|булевард|бул|площад|пл)\.?\s+", re.I)
GENERIC = re.compile(r"(?<![а-яa-z])(?:бул\.?\s*/\s*ул\.?|ул\.?\s*/\s*бул\.?)\s+", re.I)
HOUSE = re.compile(r"[0-9]{1,5}(?:\s?[а-яa-z])?", re.I)
NUMBER = re.compile(r"(?:№|(?<!\w)(?:номер|No\.?|N)(?!\w))\s*", re.I)
QUARTER = re.compile(r"(?<!\w)(?:ж\s*\.?\s*к\.?|кв(?:артал)?\.?|жилищен\s+комплекс)\s*", re.I)
BLOCK = re.compile(r"(?<!\w)(?:бл(?:ок)?\.?)\s*", re.I)
ENTRANCE = re.compile(r"(?<!\w)(?:вх(?:од)?\.?)\s*[:№]?\s*([а-яa-z0-9]{1,4})(?!\w)", re.I)
REGION = re.compile(r"(?<!\w)(?:район|р-н)\s+([^,;\r\n]{1,100})", re.I)


def normalized(value):
    value = unicodedata.normalize("NFC", str(value or "")).casefold()
    value = re.sub(r'[„“”"«»]', '', value)
    return re.sub(r"\s+", " ", value).strip(" ,;.")


def scope_name(value, quarter=False):
    value = normalized(value)
    value = (QUARTER if quarter else re.compile(r"^(?:район|р-н)\s+", re.I)).sub("", value, count=1)
    return re.sub(r"[^а-яa-z0-9 -]+", " ", value).strip()


def number_key(value):
    value = normalized(value)
    return re.sub(r"\s", "", value) if HOUSE.fullmatch(value) else None


def _reference_street(value):
    typed = street_name(value)
    if typed:
        return tuple(typed)
    if not safe_label(value, 160):
        return None
    bare = street_name("ул. " + value)
    return (None, bare[1]) if bare else None


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def safe_label(value, limit=240):
    return isinstance(value, str) and 0 < len(value) <= limit and not CONTACT.search(value) and not re.search(r"[<>\x00-\x1f]|(?<!\d)\d{9,}(?!\d)", value)


def trusted_url(url, resource_id=None):
    if not isinstance(url, str) or len(url) > 2048:
        return False
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != HOST or parts.username or parts.password or parts.port or parts.fragment:
        return False
    if resource_id is None:
        return parts.path == "/api/3/action/package_show" and parts.query in {"id=" + x["dataset"] for x in SOURCES.values()}
    return not parts.query and re.fullmatch(r"/dataset/[a-f0-9-]{36}/resource/" + re.escape(resource_id) + r"/download/[a-z_]+\.zip", parts.path) is not None


class _Redirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old = urlsplit(req.full_url)
        new = urlsplit(newurl)
        if new.scheme != "https" or new.hostname != HOST or new.username or new.password or new.port or new.fragment or new.path != old.path or new.query != old.query:
            raise ValueError("Municipal source redirected outside its fixed resource")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_bytes(url, maximum):
    opener = build_opener(_Redirect(), HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(Request(url, headers={"User-Agent": "SofiaPermits-municipal-reference/1.0"}), timeout=45) as response:
        chunks, total = [], 0
        while True:
            chunk = response.read(min(65536, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk); total += len(chunk)
            if total > maximum:
                raise ValueError("Municipal source exceeds its byte limit")
    return b"".join(chunks)


def package_resource(raw, key):
    if len(raw) > MAX_METADATA_BYTES:
        raise ValueError("Municipal metadata exceeds its byte limit")
    data = json.loads(raw)
    package = data.get("result") if data.get("success") is True else None
    spec = SOURCES[key]
    if not isinstance(package, dict) or package.get("name") != spec["dataset"] or package.get("license_id") != "cc-by" or package.get("private") is True:
        raise ValueError("Municipal dataset identity or published license changed")
    resources = [r for r in package.get("resources", []) if isinstance(r, dict) and r.get("id") == spec["resource_id"]]
    if len(resources) != 1:
        raise ValueError("Municipal resource is absent or repeated")
    resource = resources[0]
    if resource.get("format", "").casefold() != spec["format"].casefold() or not trusted_url(resource.get("url"), spec["resource_id"]):
        raise ValueError("Municipal resource URL or format changed")
    date_text = next((x.get("value", "") for x in package.get("extras", []) if x.get("key") == "Актуален към"), "")
    match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", date_text)
    as_of = ""
    if match:
        day, month, year = map(int, match.groups())
        as_of = datetime(year, month, day).date().isoformat()
    return resource, as_of


def _read(path, maximum):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 1 <= path.stat().st_size <= maximum:
        raise ValueError("Municipal cache file missing, linked or oversized")
    with path.open("rb") as handle:
        result = handle.read(maximum + 1)
    if len(result) > maximum:
        raise ValueError("Municipal cache changed while reading")
    return result


def capture_reference(cache, offline=False):
    """Capture fixed public resources, or load a previously captured local cache.

    The earlier read-only audit directory is also accepted offline. Its retrieval
    timestamp remains unknown rather than being manufactured from file mtime.
    """
    cache = Path(cache)
    if cache.is_symlink():
        raise ValueError("Municipal cache may not be a symlink")
    captured = datetime.now(timezone.utc).isoformat() if not offline else None
    payloads, sources = {}, []
    old = json.loads(_read(cache / "municipal-capture.json", MAX_METADATA_BYTES)) if offline and (cache / "municipal-capture.json").exists() else None
    for key, spec in SOURCES.items():
        metadata_name = spec["dataset"] + "-package.json"
        api = "https://" + HOST + "/api/3/action/package_show?id=" + spec["dataset"]
        metadata = _read(cache / metadata_name, MAX_METADATA_BYTES) if offline else fetch_bytes(api, MAX_METADATA_BYTES)
        resource, as_of = package_resource(metadata, key)
        payload = _read(cache / spec["zip_name"], MAX_ZIP_BYTES) if offline else fetch_bytes(resource["url"], MAX_ZIP_BYTES)
        if isinstance(resource.get("size"), int) and resource["size"] != len(payload):
            raise ValueError("Municipal resource size does not match CKAN metadata")
        evidence = {"dataset": spec["dataset"], "resource_id": spec["resource_id"], "url": resource["url"], "format": spec["format"],
                    "data_as_of": as_of, "retrieved_at": captured, "bytes": len(payload), "sha256": digest(payload), "metadata_sha256": digest(metadata),
                    "license_id": "CC-BY-4.0", "license_url": LICENSE_URL, "policy_url": POLICY_URL}
        if old:
            previous = next((x for x in old.get("sources", []) if x.get("resource_id") == spec["resource_id"]), None)
            if not previous or any(previous.get(k) != evidence[k] for k in ("url", "bytes", "sha256", "metadata_sha256")):
                raise ValueError("Municipal offline cache differs from its capture evidence")
            evidence["retrieved_at"] = previous.get("retrieved_at")
        payloads[key] = payload
        payloads[metadata_name] = metadata
        sources.append(evidence)
    provenance = {"version": 1, "sources": sources, "coordinate_crs": "OGC:CRS84", "crs_basis": "GeoJSON_default_CRS84", "publisher_crs_explicit": False}
    provenance["source_revision"] = digest(json_bytes([{k: x[k] for k in ("resource_id", "sha256", "metadata_sha256")} for x in sources]))
    reference = load_reference(payloads["addresses"], payloads["aliases"], provenance)
    if not offline:
        cache.mkdir(parents=True, exist_ok=True)
        # Commit capture evidence last. A failed capture never replaces that
        # evidence with a claim that incomplete input is a valid reference.
        for key, spec in SOURCES.items():
            (cache / spec["zip_name"]).write_bytes(payloads[key])
            name = spec["dataset"] + "-package.json"
            (cache / name).write_bytes(payloads[name])
        (cache / "municipal-capture.json").write_bytes(json_bytes(provenance))
    return reference, reference.provenance


def zip_member(payload, expected, maximum):
    with ZipFile(io.BytesIO(payload)) as archive:
        entries = archive.infolist()
        if len(entries) != 1 or entries[0].filename != expected or entries[0].is_dir() or entries[0].flag_bits & 1 or not 1 <= entries[0].file_size <= maximum:
            raise ValueError("Unexpected municipal archive members or uncompressed size")
        with archive.open(entries[0]) as handle:
            result = handle.read(maximum + 1)
        if len(result) != entries[0].file_size or len(result) > maximum:
            raise ValueError("Municipal archive failed its bounded read")
        return result


class MunicipalReference:
    def __init__(self, provenance):
        self.provenance = provenance
        self.records = []
        self.streets = defaultdict(list)
        self.blocks = defaultdict(list)
        self.aliases = defaultdict(list)
        self.street_kinds = defaultdict(set)
        self.counts = Counter()


def load_reference(address_zip, aliases_zip, provenance=None):
    address_zip = _read(address_zip, MAX_ZIP_BYTES) if isinstance(address_zip, (str, Path)) else address_zip
    aliases_zip = _read(aliases_zip, MAX_ZIP_BYTES) if isinstance(aliases_zip, (str, Path)) else aliases_zip
    if not isinstance(address_zip, bytes) or not isinstance(aliases_zip, bytes) or max(len(address_zip), len(aliases_zip)) > MAX_ZIP_BYTES:
        raise ValueError("Municipal ZIP input exceeds its byte limit")
    provenance = dict(provenance or {"version": 1, "source_revision": digest(address_zip + aliases_zip), "coordinate_crs": "OGC:CRS84", "crs_basis": "GeoJSON_default_CRS84", "publisher_crs_explicit": False, "sources": []})
    data = json.loads(zip_member(address_zip, SOURCES["addresses"]["member"], MAX_ADDRESS_BYTES))
    if data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list) or not 1 <= len(data["features"]) <= MAX_FEATURES:
        raise ValueError("Municipal GeoJSON collection is invalid")
    if "crs" in data:
        crs = data["crs"]
        if not isinstance(crs, dict) or crs.get("type") != "name" or crs.get("properties", {}).get("name") not in {"urn:ogc:def:crs:OGC:1.3:CRS84", "OGC:CRS84"}:
            raise ValueError("Municipal coordinate reference system is unsupported")
        provenance.update({"crs_basis": "publisher_explicit_geographic_crs", "publisher_crs_explicit": True})
    result = MunicipalReference(provenance)
    seen_ids = set()
    for feature in data["features"]:
        result.counts["features"] += 1
        p, geometry = feature.get("properties"), feature.get("geometry")
        if not isinstance(p, dict) or set(p) != {"rn", "region", "settlement", "lareaunit", "block", "street", "streetnum", "entrance"} or any(not isinstance(x, str) for x in p.values()):
            raise ValueError("Municipal address property schema changed")
        if not re.fullmatch(r"(?:гр\.?\s*)?софия", normalized(p["settlement"])):
            continue
        result.counts["sofia_city_features"] += 1
        coordinates = geometry.get("coordinates") if isinstance(geometry, dict) and geometry.get("type") == "Point" else None
        if not isinstance(coordinates, list) or len(coordinates) != 2 or any(type(x) not in (float, int) or not math.isfinite(x) for x in coordinates) or not (22.8 <= coordinates[0] <= 24 and 42.4 <= coordinates[1] <= 43.1):
            raise ValueError("Municipal address coordinate geometry is invalid")
        if not re.fullmatch(r"[a-zA-Z0-9._:-]{1,80}", p["rn"]) or p["rn"] in seen_ids:
            raise ValueError("Municipal reference ID is invalid")
        seen_ids.add(p["rn"])
        street = street_name(p["street"]); number = number_key(p["streetnum"])
        quarter, block, region = scope_name(p["lareaunit"], True), number_key(p["block"]), scope_name(p["region"])
        entrance = normalized(p["entrance"])
        if entrance and not re.fullmatch(r"[а-яa-z0-9]{1,4}", entrance):
            entrance = ""
        record = {"reference_id": p["rn"], "lat": float(coordinates[1]), "lng": float(coordinates[0]), "street": tuple(street) if street else None,
                  "number": number, "quarter": quarter, "block": block, "region": region, "entrance": entrance}
        index = len(result.records); result.records.append(record)
        if street and number:
            result.streets[(*street, number)].append(index)
            result.street_kinds[street[1]].add(street[0])
        if quarter and block:
            result.blocks[(quarter, block)].append(index)
    text = zip_member(aliases_zip, SOURCES["aliases"]["member"], MAX_ALIAS_BYTES).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text), dialect=csv.Sniffer().sniff(text[:4096]))
    if set(reader.fieldnames or []) != {"rn", "new_name", "name", "resolution_renaming"}:
        raise ValueError("Municipal street-renaming schema changed")
    for position, row in enumerate(reader, 1):
        if position > MAX_ALIAS_ROWS:
            raise ValueError("Municipal street-renaming row limit exceeded")
        old, new = _reference_street(row["name"]), _reference_street(row["new_name"])
        if old and new:
            if not re.fullmatch(r"[a-zA-Z0-9._:-]{1,80}", str(row["rn"])):
                raise ValueError("Municipal alias reference ID is invalid")
            result.aliases[tuple(old)].append({"street": tuple(new), "reference_id": str(row["rn"]), "resolution_sha256": digest(row["resolution_renaming"].encode("utf-8"))})
    result.counts["street_keys"] = len(result.streets); result.counts["quarter_block_keys"] = len(result.blocks)
    result.counts["ambiguous_alias_names"] = sum(len({x["street"] for x in rows}) > 1 for rows in result.aliases.values())
    return result


def street_variants(street, reference):
    """Keep every one-step historical variant; never pick an ambiguous name."""
    kind, name = street
    variants = [{"street": (actual, name), "alias_reference_ids": []} for actual in ([kind] if kind else sorted(reference.street_kinds.get(name, [])))]
    grouped = defaultdict(set)
    rows = reference.aliases.get(tuple(street), []) + (reference.aliases.get((None, name), []) if kind else [])
    for row in rows:
        new_kind, new_name = row["street"]
        for actual in ([new_kind] if new_kind else sorted(reference.street_kinds.get(new_name, []))):
            grouped[(actual, new_name)].add(row["reference_id"])
    variants.extend({"street": key, "alias_reference_ids": sorted(ids)} for key, ids in sorted(grouped.items()) if key != tuple(street))
    return variants


def _parse_street(raw):
    raw = GENERIC.sub(" ", raw)
    markers = list(STREET.finditer(raw))
    if len(markers) != 1:
        return None
    marker = markers[0]; tail = raw[marker.end():]
    numbers = list(NUMBER.finditer(tail))
    if len(numbers) == 1:
        label = tail[:numbers[0].start()].strip(" ,;\r\n")
        number_tail = tail[numbers[0].end():]
        match = HOUSE.match(number_tail)
        if not match or (number_tail[match.end():] and not re.match(r"^\s*(?:[,;\r\n]|$)", number_tail[match.end():])):
            return None
        number = number_key(match.group())
    elif not numbers:
        clause = re.split(r"[,;\r\n]", tail, 1)[0]
        match = re.fullmatch(r"(.+?)\s+([0-9]{1,5}(?:\s?[а-яa-z])?)", clause)
        if not match:
            return None
        label, number = match[1], number_key(match[2])
    else:
        return None
    if not safe_label(label, 160) or re.search(r"[,;\r\n]", label):
        return None
    kind = marker["kind"].casefold()
    prefix = "бул." if kind.startswith("бул") else "пл." if kind.startswith("пл") else "ул."
    street = street_name(prefix + " " + label)
    return (tuple(street), number) if street and number else None


def resolve_company_address(raw_registered_address, reference):
    """Return all exact typed address candidates with safe, source-only labels."""
    if not isinstance(raw_registered_address, str) or not 1 <= len(raw_registered_address) <= 16384:
        return []
    raw = unicodedata.normalize("NFC", raw_registered_address)
    contact = CONTACT.search(raw)
    if contact:
        raw = raw[:contact.start()]
    region_match = REGION.search(raw); region = scope_name(region_match[1]) if region_match else ""
    quarter_matches = list(QUARTER.finditer(raw)); block_matches = list(BLOCK.finditer(raw)); entrance_matches = list(ENTRANCE.finditer(raw))
    if len(quarter_matches) > 1 or len(block_matches) > 1 or len(entrance_matches) > 1:
        return []
    quarter = ""
    if quarter_matches:
        tail = raw[quarter_matches[0].end():]
        quarter = scope_name(re.split(r"[,;\r\n]|(?<!\w)бл(?:ок)?\.?(?=\s|[0-9])", tail, 1, re.I)[0], True)
    block = None
    if block_matches:
        tail = raw[block_matches[0].end():]; match = HOUSE.match(tail)
        if match and (not tail[match.end():] or re.match(r"^\s*(?:[,;\r\n]|$)", tail[match.end():])):
            block = number_key(match.group())
    entrance = normalized(entrance_matches[0][1]) if entrance_matches else ""
    parsed = _parse_street(raw); groups = []
    # The builder's pure parser additionally recognizes its generic street
    # labels and known unit delimiters. Import lazily to avoid module cycles.
    if not parsed:
        try:
            from refresh_business_addresses import address_key
            key = address_key(raw)
            if key and len(key) == 4:
                parsed = ((key[1], key[2]), key[3])
        except ImportError:
            pass
    if not parsed and STREET.search(raw):
        return []
    if parsed:
        street, number = parsed
        for variant in street_variants(street, reference):
            groups.append((reference.streets.get((*variant["street"], number), []), "municipal_historical_street_number" if variant["alias_reference_ids"] else "municipal_street_number", variant))
    elif quarter and block:
        groups.append((reference.blocks.get((quarter, block), []), "municipal_quarter_block", None))
    else:
        return []
    candidates = []
    for indices, method, variant in groups:
        records = [reference.records[i] for i in indices]
        records = [r for r in records if (not region or r["region"] == region) and (not quarter or r["quarter"] == quarter) and (not block or r["block"] == block) and (not entrance or r["entrance"] == entrance)]
        if not records:
            continue
        if len({r["reference_id"] for r in records}) > 32 or (variant and len(variant["alias_reference_ids"]) > 32):
            continue
        if variant:
            kind, name = variant["street"]; prefix = {"street": "ул.", "boulevard": "бул.", "square": "пл."}[kind]
            label = f"гр. София, {prefix} {name} № {parsed[1]}"
            matched = ["street", kind, name, parsed[1], region, quarter, entrance]
        else:
            label = f"гр. София, ж.к. {quarter}, бл. {block}" + (f", вх. {entrance}" if entrance else "")
            matched = ["quarter_block", quarter, block, region, entrance]
        if not safe_label(label):
            continue
        candidates.append({"address_label": label, "points": [{"lat": r["lat"], "lng": r["lng"], "reference_id": r["reference_id"]} for r in records],
                           "reference_ids": sorted({r["reference_id"] for r in records}), "matched_key": matched, "method": method,
                           "alias_reference_ids": variant["alias_reference_ids"] if variant else [], "source_revision": reference.provenance["source_revision"]})
    return candidates if len({identifier for candidate in candidates for identifier in candidate["reference_ids"]}) <= 32 else []
