#!/usr/bin/env python3
"""Build a private, bounded company registered-address/parcel association.

This is address evidence, never ownership evidence. Only corporate registered
offices are considered. Person/role fields, contacts and raw address strings are
transient input and are never copied into the snapshot. No geocoder is used.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
import re
import ssl
import struct
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from uuid import uuid4
from zipfile import ZipFile

from imot_location import street_name
from refresh_cadastre import archive_records, file_digest, json_bytes, read_json, timestamp_valid, utc_now, write_new

REPO = "ChocoRamaBG/register-of-outpatient-care-facilities-and-hospices"
SOURCE_PATH = "registry_agency_scraper/registry_agency_outputs"
CSV_NAME = re.compile(r"registry_agency_data_mega(?:_part((?:[2-9]|[1-9][0-9]+)))?\.csv")
HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
HEX32 = re.compile(r"[0-9a-f]{32}")
CAD_ID = re.compile(r"68134\.[0-9]{1,6}\.[0-9]{1,6}")
SHARD_NAME = re.compile(r"companies-[0-9]{3}\.json")
MAX_FILE_BYTES = 10_000_000
MAX_INDEX_BYTES = 9_500_000
MAX_POINTS_BYTES = MAX_INDEX_BYTES
MAX_MANIFEST_BYTES = 256 * 1024
MAX_SHARD_BYTES = 1024 * 1024
MAX_SNAPSHOT_BYTES = 128 * 1024 * 1024
MAX_CSV_BYTES = 128 * 1024 * 1024
MAX_SOURCE_BYTES = 8 * 1024 * 1024 * 1024
MAX_FILES = 64
MAX_ROWS = 2_000_000
MAX_HTTP_ATTEMPTS = 3
RETRY_HTTP_CODES = {408, 429, 500, 502, 503, 504}
FIELD_MAP = {"uic": "ЕИК/ПИК", "query": "UIC_Query", "name": "Фирма/Наименование",
             "legal_form": "Правна форма", "country": "Държава", "settlement": "Населено място",
             "address": "Адрес", "activity": "Предмет на дейност", "natural_person": "Физическо лице",
             "as_of": "Състояние към дата"}
COMPANY_FIELDS = {"uic", "name", "legal_form", "activity", "registered_address", "status", "as_of", "source_url"}
TEXT_LIMITS = {"name": 300, "legal_form": 160, "activity": 500, "registered_address": 240}
CONTACT = re.compile(r"@|https?://|www\.|(?<!\w)(?:тел(?:ефон)?|факс|email|e-mail|е-мейл|електронна\s+поща)\s*[:.]|(?<!\d)\+?\d[\d ()/-]{7,}\d(?!\d)", re.I)
PERSON_ROLE = re.compile(r"(?<!\w)(?:егн|лнч|управител(?:и)?|съдружни(?:к|ци)|собственик\s+на\s+капитала|дата\s+на\s+раждане)(?!\w)", re.I)
STREET_MARKER = re.compile(r"(?<![а-яa-z])(?P<kind>улица|ул|булевард|бул|площад|пл)\.?\s+", re.I)
NUMBER_MARKER = re.compile(r"(?:№|(?<!\w)(?:номер|No\.?|N)(?!\w))\s*", re.I)
HOUSE_NUMBER = re.compile(r"[0-9]{1,5}(?:\s?[а-яa-z])?", re.I)
GENERIC_STREET_LABEL = re.compile(r"(?<![а-яa-z])(?:бул\.?\s*/\s*ул\.?|ул\.?\s*/\s*бул\.?)\s+", re.I)
HOUSE_TOKEN = re.compile(r"(?P<number>[0-9]{1,5})(?:\s?(?P<suffix>[а-яa-z])(?![а-яa-z]))?", re.I)
UNIT_OR_CONTACT_TAIL = re.compile(r"^(?:ет(?:аж)?|вх(?:од)?|ап(?:артамент)?|офис|бл(?:ок)?|тел(?:ефон)?|факс|e-?mail|имейл)\.?\s*[:№0-9\s]", re.I)
EXTRA_UNIT_NUMBER = re.compile(r"(?<!\w)(?:ет(?:аж)?|вх(?:од)?|ап(?:артамент)?|офис|бл(?:ок)?)\.?\s*:?\s*$", re.I)


def clean(value):
    return unicodedata.normalize("NFC", (value or "").strip())


def safe_text(value, limit, activity=False):
    value = " ".join(clean(value).split())
    if not value or len(value) > limit or any(unicodedata.category(c).startswith("C") for c in value) or re.search(r"[<>]", value) or CONTACT.search(value) or PERSON_ROLE.search(value):
        return ""
    # Long digit sequences are identifiers/contacts, not needed public activity.
    if re.search(r"(?<!\d)\d{9,}(?!\d)", value):
        return ""
    return value


def valid_uic(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{9}", value) is None:
        return False
    digits = [int(c) for c in value]
    check = sum((i + 1) * digits[i] for i in range(8)) % 11
    if check == 10:
        check = sum((i + 3) * digits[i] for i in range(8)) % 11
        if check == 10:
            check = 0
    return check == digits[8]


def as_of_date(value):
    matches = re.findall(r"(?<!\d)(\d{2})\.(\d{2})\.(\d{4})(?!\d)", clean(value))
    if len(matches) != 1:
        return ""
    try:
        day, month, year = map(int, matches[0])
        result = date(year, month, day)
        return result.isoformat() if date(2000, 1, 1) <= result <= date.today() else ""
    except ValueError:
        return ""


def source_url(uic):
    return "https://portal.registryagency.bg/CR/Reports/ActiveConditionTabResult?uic=" + uic


def street_key(value):
    value = clean(value)
    if len(value) > 220 or CONTACT.search(value) or PERSON_ROLE.search(value):
        return None
    result = street_name(value)
    if not result or not 1 <= len(result[1]) <= 160:
        return None
    return tuple(result)


def number_key(value):
    value = clean(value)
    if HOUSE_NUMBER.fullmatch(value) is None:
        return None
    return re.sub(r"\s", "", value).casefold()


def address_key(value):
    """Return (EKATTE, kind|'unknown', full street name, exact simple number).

    Unknown street kind is evidence of a generic source field label, never an
    assumed street. It may resolve only against all official kinds together.
    """
    value = clean(value)
    if not value or len(value) > 16384:
        return None
    original = value
    generic = bool(GENERIC_STREET_LABEL.search(value))
    value = GENERIC_STREET_LABEL.sub(" ", value)
    markers = list(STREET_MARKER.finditer(value))
    unknown_kind = not markers and generic
    if unknown_kind:
        # The synthetic prefix only invokes the existing full-name normalizer;
        # it is never used as a claimed official kind or public address.
        value = GENERIC_STREET_LABEL.sub("ул. ", original)
        markers = list(STREET_MARKER.finditer(value))
    if len(markers) != 1:
        return None
    marker = markers[0]
    if generic and NUMBER_MARKER.search(value[:marker.start()]):
        # Do not ignore an earlier generically labelled address in favor of a
        # later, explicitly typed second street.
        return None
    following = value[marker.end():]
    numbers = list(NUMBER_MARKER.finditer(following))
    if numbers:
        number_start = numbers[0]
        street = following[:number_start.start()].strip(" ,;\n\r")
        tail = re.sub(r"^:\s*", "", following[number_start.end():])
    else:
        # A house number without № must be a separate final token following a
        # named street. Street numbers and apartment/block numbers are not used.
        unmarked = re.match(r"^(?P<street>[^,;\n\r]+?)\s+(?P<tail>[0-9]{1,5}(?:\s?[а-яa-z])?(?:\s*[,;].*)?)$", following, re.I)
        if not unmarked:
            return None
        street, tail = unmarked["street"], unmarked["tail"]
    # A single source street label must not absorb quarter/unit/contact text.
    if not street or re.search(r"[,;\n\r]", street):
        return None
    if re.search(r"(?<!\w)(?:ет(?:аж)?|вх(?:од)?|ап(?:артамент)?|офис|бл(?:ок)?|тел(?:ефон)?|факс)\.?\s*(?:[:0-9]|$)", street, re.I):
        return None
    prefix = marker.group("kind").casefold()
    prefix = "ул." if prefix in {"ул", "улица"} else "бул." if prefix in {"бул", "булевард"} else "пл."
    normalized = street_key(prefix + " " + street)
    match = HOUSE_TOKEN.match(tail)
    if not normalized or not match:
        return None
    remainder = tail[match.end():]
    clean_remainder = remainder.lstrip()
    if clean_remainder and clean_remainder[0] not in ",;\r\n" and not UNIT_OR_CONTACT_TAIL.match(clean_remainder):
        return None
    # A second № belongs only to an explicitly named unit, never a second
    # house number or an unqualified number appearing in a contact remainder.
    for extra in NUMBER_MARKER.finditer(remainder):
        if not EXTRA_UNIT_NUMBER.search(remainder[:extra.start()]):
            return None
    if re.match(r"^\s*[,;]\s*[0-9]", remainder):
        return None
    number = number_key(match.group("number") + (match.group("suffix") or ""))
    return ("68134", "unknown" if unknown_kind else normalized[0], normalized[1], number) if number else None


def canonical_address(key):
    if key[1] == "unknown":
        raise ValueError("An unresolved street kind cannot form a public address")
    prefix = {"street": "ул.", "boulevard": "бул.", "square": "пл."}[key[1]]
    return f"гр. София, {prefix} {key[2]} № {key[3]}"


def explicit_sofia(country, settlement):
    if clean(country).casefold() not in {"българия", "република българия", "bulgaria"}:
        return False
    return re.fullmatch(r"(?:гр\.?\s*)?софия(?:\s*,\s*п\.?\s*к\.?\s*[^,\r\n]{1,12})?", clean(settlement).casefold()) is not None


def corporate_form(value, natural_person=""):
    value = safe_text(value, TEXT_LIMITS["legal_form"])
    if not value or clean(natural_person) or re.search(r"едноличен\s+търговец|физическо\s+лице|(?:^|\W)ет(?:$|\W)", value, re.I):
        return ""
    if re.search(r"[0-9]", value):
        return ""
    return value


def part_number(name):
    match = CSV_NAME.fullmatch(name)
    if not match:
        raise ValueError("Unexpected company export filename")
    return int(match.group(1) or 1)


def validate_source(source):
    if not isinstance(source, dict) or source.get("repo") != REPO or source.get("path") != SOURCE_PATH or not isinstance(source.get("commit"), str) or not HEX40.fullmatch(source["commit"]):
        raise ValueError("Invalid pinned company source")
    files = source.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError("Invalid company source file count")
    parts = []
    total = 0
    for item in files:
        if not isinstance(item, dict) or set(item) != {"name", "bytes", "git_blob_sha1", "sha256"} or type(item["bytes"]) is not int or not 1 <= item["bytes"] <= MAX_CSV_BYTES or not isinstance(item["git_blob_sha1"], str) or not HEX40.fullmatch(item["git_blob_sha1"]) or not isinstance(item["sha256"], str) or not HEX64.fullmatch(item["sha256"]):
            raise ValueError("Invalid company export evidence")
        parts.append(part_number(item["name"]))
        total += item["bytes"]
    if sorted(parts) != list(range(1, len(files) + 1)) or total > MAX_SOURCE_BYTES:
        raise ValueError("Missing, repeated or oversized company export parts")


def verify_blob(path, item):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != item["bytes"]:
        raise ValueError("Company export size mismatch")
    sha1 = hashlib.sha1(f"blob {item['bytes']}\0".encode("ascii"))
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(128 * 1024), b""):
            sha1.update(block)
            sha256.update(block)
    if sha1.hexdigest() != item["git_blob_sha1"] or sha256.hexdigest() != item["sha256"]:
        raise ValueError("Company export hash mismatch")


def local_source(directory):
    raw = read_json(directory / "source-manifest.json", MAX_MANIFEST_BYTES)
    source = {"repo": raw.get("repo", raw.get("repository")), "commit": raw.get("commit", raw.get("revision")), "path": raw.get("path", SOURCE_PATH), "files": [{k: item[k] for k in ("name", "bytes", "git_blob_sha1", "sha256")} for item in raw.get("files", [])]}
    validate_source(source)
    if {p.name for p in directory.glob("*.csv")} != {item["name"] for item in source["files"]}:
        raise ValueError("Local CSV set does not match pinned source manifest")
    for item in source["files"]:
        verify_blob(directory / item["name"], item)
    return source


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Company source redirected unexpectedly")


def fetch_bytes(url, limit, token=None):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"api.github.com", "raw.githubusercontent.com"} or parsed.username or parsed.password or parsed.port or parsed.fragment:
        raise ValueError("Unexpected company source endpoint")
    headers = {"User-Agent": "SofiaPermits-business-address-refresh/1.0", "Accept": "application/vnd.github+json" if parsed.hostname == "api.github.com" else "text/csv"}
    if token and parsed.hostname == "api.github.com":
        headers["Authorization"] = "Bearer " + token
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    opener = build_opener(NoRedirect(), HTTPSHandler(context=context))
    for attempt in range(MAX_HTTP_ATTEMPTS):
        retry_after = None
        try:
            with opener.open(Request(url, headers=headers), timeout=90) as response:
                declared = response.headers.get("Content-Length")
                if declared is not None and (not declared.isdigit() or not 1 <= int(declared) <= limit):
                    raise ValueError("Invalid company source content length")
                payload = response.read(limit + 1)
                if not payload or len(payload) > limit or declared is not None and len(payload) != int(declared):
                    raise ValueError("Company source download exceeded limit or was incomplete")
                return payload
        except HTTPError as error:
            if error.code not in RETRY_HTTP_CODES or attempt + 1 == MAX_HTTP_ATTEMPTS:
                raise
            value = (error.headers.get("Retry-After", "") if error.headers else "").strip()
            if value.isdigit():
                retry_after = min(10, int(value)) if len(value) < 4 else 10
            error.close()
        except (URLError, TimeoutError):
            if attempt + 1 == MAX_HTTP_ATTEMPTS:
                raise
        time.sleep(retry_after if retry_after is not None else attempt + 1)


def source_entries(api, commit, token):
    """Walk only the immutable directory trees, never the entire recursive repo."""
    def tree(identifier):
        value = json.loads(fetch_bytes(api + "/git/trees/" + identifier, 4 * 1024 * 1024, token))
        if not isinstance(value, dict) or value.get("truncated") is not False or not isinstance(value.get("tree"), list) or not isinstance(value.get("sha"), str) or not HEX40.fullmatch(value["sha"]):
            raise ValueError("Incomplete company repository tree")
        entries, names = value["tree"], set()
        for item in entries:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not item["path"] or "/" in item["path"] or item["path"] in {".", ".."} or item["path"] in names:
                raise ValueError("Unexpected direct company tree entry")
            names.add(item["path"])
        return entries
    identifier = commit
    for component in SOURCE_PATH.split("/"):
        matches = [entry for entry in tree(identifier) if entry["path"] == component]
        if len(matches) != 1 or matches[0].get("type") != "tree" or matches[0].get("mode") != "040000" or not isinstance(matches[0].get("sha"), str) or not HEX40.fullmatch(matches[0]["sha"]):
            raise ValueError("Pinned company source directory is absent or malformed")
        identifier = matches[0]["sha"]
    entries = []
    for item in tree(identifier):
        if CSV_NAME.fullmatch(item["path"]):
            if item.get("type") != "blob" or item.get("mode") != "100644" or type(item.get("size")) is not int or not 1 <= item["size"] <= MAX_CSV_BYTES or not isinstance(item.get("sha"), str) or not HEX40.fullmatch(item["sha"]):
                raise ValueError("Unexpected company export blob")
            entries.append(item)
    return sorted(entries, key=lambda item: part_number(item["path"]))


def capture_source(cache, commit=None, token=None):
    api = "https://api.github.com/repos/" + REPO
    if commit is None:
        rows = json.loads(fetch_bytes(api + "/commits?per_page=1", 1024 * 1024, token))
        if not isinstance(rows, list) or len(rows) != 1:
            raise ValueError("Cannot resolve company source commit")
        commit = rows[0].get("sha")
    if not isinstance(commit, str) or not HEX40.fullmatch(commit):
        raise ValueError("Company source must use a full pinned commit")
    entries = source_entries(api, commit, token)
    source = {"repo": REPO, "commit": commit, "path": SOURCE_PATH, "files": [{"name": item["path"].rsplit("/", 1)[-1], "bytes": item["size"], "git_blob_sha1": item["sha"], "sha256": "0" * 64} for item in entries]}
    validate_source(source)
    directory = cache / commit
    if (directory / "source-manifest.json").exists():
        cached = local_source(directory)
        expected = [(x["name"], x["bytes"], x["git_blob_sha1"]) for x in source["files"]]
        if [(x["name"], x["bytes"], x["git_blob_sha1"]) for x in cached["files"]] != expected:
            raise ValueError("Cached pinned company source differs from repository")
        return directory, cached
    directory.mkdir(parents=True, exist_ok=False)
    for item in source["files"]:
        url = "https://raw.githubusercontent.com/" + REPO + "/" + commit + "/" + quote(SOURCE_PATH + "/" + item["name"], safe="/")
        payload = fetch_bytes(url, item["bytes"])  # Never forward the API token to raw URLs.
        item["sha256"] = hashlib.sha256(payload).hexdigest()
        path = directory / item["name"]
        write_new(path, payload)
        verify_blob(path, item)
    write_new(directory / "source-manifest.json", json_bytes(source))
    return directory, source


def structured_rows(path):
    """Only called alongside archive_records, which verifies the full DBF schema."""
    with ZipFile(path) as archive:
        name = next(n for n in archive.namelist() if n.lower().endswith(".dbf"))
        with archive.open(name) as handle:
            header = handle.read(32)
            count = struct.unpack("<I", header[4:8])[0]
            header_length, record_length = struct.unpack("<HH", header[8:12])
            fields = []
            for _ in range((header_length - 33) // 32):
                field = handle.read(32)
                fields.append((field[:11].split(b"\0")[0].decode("ascii"), field[16]))
            handle.read(1)
            for _ in range(count):
                raw, position, values = handle.read(record_length), 1, {}
                for name, length in fields:
                    if name in {"cadnum", "ekatte", "strename", "strnum"}:
                        values[name] = raw[position:position + length].decode("utf-8").strip(" \x00")
                    position += length
                yield values


def cadastral_reference(manifest_path, archives):
    manifest = read_json(manifest_path, MAX_MANIFEST_BYTES)
    if manifest.get("version") not in (1, 2) or manifest.get("completion", {}).get("district_count") != 24 or manifest.get("completion", {}).get("status") != "complete" or len(manifest.get("sources", [])) != 24:
        raise ValueError("A complete verified 24-district cadastral manifest is required")
    excluded = set(manifest.get("ambiguous_ids", []))
    if len(excluded) > 5000 or any(not isinstance(x, str) or not CAD_ID.fullmatch(x) for x in excluded):
        raise ValueError("Invalid cadastral ambiguous-ID set")
    by_id = defaultdict(set)
    counts, evidence = Counter(), []
    seen_codes, seen_urls = set(), set()
    for index, source in enumerate(manifest["sources"]):
        code = f"sofia-district-{index:02d}"
        if source.get("code") != code or code in seen_codes or source.get("source_url") in seen_urls or not timestamp_valid(source.get("captured_at")):
            raise ValueError("Invalid or repeated cadastral evidence")
        seen_codes.add(code); seen_urls.add(source["source_url"])
        path = archives / (code + ".zip")
        if path.is_symlink() or not path.is_file() or path.stat().st_size != source.get("zip_bytes") or file_digest(path) != source.get("zip_sha256"):
            raise ValueError("Cadastral archive does not match its source hash")
        label = source.get("label_bg", "")
        if not label.startswith("гр. София (68134) - район "):
            raise ValueError("Unexpected cadastral district")
        count = 0
        for verified, row in zip(archive_records(path, label.split(" - ", 1)[1]), structured_rows(path), strict=True):
            count += 1
            identifier = verified[0]
            if identifier != row["cadnum"] or row["ekatte"] != "68134":
                raise ValueError("Structured cadastral address does not match verified row")
            if identifier in excluded:
                continue
            street, number = street_key(row["strename"]), number_key(row["strnum"])
            if street and number:
                by_id[identifier].add(("68134", *street, number))
        if count != source.get("record_count"):
            raise ValueError("Cadastral archive count mismatch")
        counts["cadastre_rows"] += count
        evidence.append({k: source[k] for k in ("code", "source_url", "zip_sha256", "captured_at")})
    keys = defaultdict(set)
    for identifier, addresses in by_id.items():
        if len(addresses) == 1:
            keys[next(iter(addresses))].add(identifier)
        else:
            counts["cadastre_conflicting_address_ids"] += 1
    counts.update({"cadastre_address_keys": len(keys), "cadastre_unique_address_keys": sum(len(v) == 1 for v in keys.values()), "cadastre_ambiguous_address_keys": sum(len(v) > 1 for v in keys.values()), "cadastre_excluded_ids": len(excluded)})
    return keys, {"manifest_sha256": file_digest(manifest_path), "snapshot_id": manifest["snapshot_id"], "captured_from": min(x["captured_at"] for x in evidence), "captured_to": max(x["captured_at"] for x in evidence), "sources": evidence}, counts


def candidate(row, counts):
    values = {key: clean(row.get(column)) for key, column in FIELD_MAP.items()}
    counts["rows"] += 1
    uic = values["uic"]
    if not valid_uic(uic) or uic != values["query"]:
        counts["invalid_or_unconfirmed_uic"] += 1
        return None
    as_of = as_of_date(values["as_of"])
    if not as_of:
        counts["missing_or_invalid_as_of"] += 1
    name = safe_text(values["name"], TEXT_LIMITS["name"])
    form = corporate_form(values["legal_form"], values["natural_person"])
    key = address_key(values["address"])
    reason = ""
    if not name:
        reason = "missing_or_unsafe_name"
    elif not form:
        reason = "natural_person_or_unsupported_form"
    elif not explicit_sofia(values["country"], values["settlement"]):
        reason = "outside_explicit_bulgaria_sofia"
    elif not key:
        reason = "missing_or_unparseable_street_number"
    activity = safe_text(values["activity"], TEXT_LIMITS["activity"], True)
    company = {"uic": uic, "name": name, "legal_form": form, "activity": activity, "registered_address": canonical_address(key) if key and key[1] != "unknown" else "", "status": "not_verified", "as_of": as_of, "source_url": source_url(uic)}
    # Only a digest is retained for rejected raw address variants; never publish it.
    signature = hashlib.sha256(json_bytes([company, reason, key, clean(values["country"]).casefold(), clean(values["settlement"]).casefold(), hashlib.sha256(values["address"].encode()).hexdigest() if not key else ""])).hexdigest()
    return uic, as_of, signature, company, key, reason


def select_companies(directory, source):
    csv.field_size_limit(4 * 1024 * 1024)
    selected, conflicting, counts = {}, set(), Counter()
    for item in sorted(source["files"], key=lambda x: part_number(x["name"])):
        with (directory / item["name"]).open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)) or not set(FIELD_MAP.values()).issubset(reader.fieldnames):
                raise ValueError("Company export headings changed")
            for row in reader:
                if None in row or any(v is None for v in row.values()):
                    raise ValueError("Malformed company CSV row")
                item_candidate = candidate(row, counts)
                if counts["rows"] > MAX_ROWS:
                    raise ValueError("Company processing row limit exceeded")
                if item_candidate is None:
                    continue
                uic, as_of, signature, company, key, reason = item_candidate
                previous = selected.get(uic)
                if previous is None or as_of > previous[0]:
                    selected[uic] = (as_of, signature, company, key, reason)
                    conflicting.discard(uic)
                elif as_of == previous[0]:
                    counts["same_date_duplicate_rows"] += 1
                    if signature != previous[1]:
                        conflicting.add(uic)
                else:
                    counts["older_observation_rows"] += 1
    counts["latest_date_conflicting_companies"] = len(conflicting)
    counts["dated_confirmed_companies"] = sum(bool(value[0]) for value in selected.values())
    counts["undated_confirmed_companies"] = sum(not value[0] for value in selected.values())
    for uic in conflicting:
        selected.pop(uic)
    return selected, counts


def address_kind_index(reference):
    """Full-name/number lookup across ALL official kinds, retaining each key."""
    result = defaultdict(dict)
    for key, identifiers in reference.items():
        for identifier in identifiers:
            result[(key[0], key[2], key[3])].setdefault(identifier, set()).add(key)
    return result


def address_matches(key, reference, across_kinds=None):
    """Return {parcel ID: set(official keys)}; caller must require ONE ID."""
    if key[1] == "unknown":
        across_kinds = address_kind_index(reference) if across_kinds is None else across_kinds
        return across_kinds.get((key[0], key[2], key[3]), {})
    return {identifier: {key} for identifier in reference.get(key, set())}


def match_companies(selected, reference, counts):
    parcels = defaultdict(list)
    across_kinds = address_kind_index(reference)
    for _, _, company, key, reason in selected.values():
        # Count city corporate candidates even when their street/number is absent.
        if not reason or reason == "missing_or_unparseable_street_number":
            counts["sofia_candidates"] += 1
        if reason:
            counts[reason] += 1
            continue
        if key[1] == "unknown":
            counts["unknown_kind_sofia_candidates"] += 1
        matches = address_matches(key, reference, across_kinds)
        if not matches:
            counts["address_not_in_cadastre"] += 1
        elif len(matches) != 1:
            counts["ambiguous_cadastral_address"] += 1
        else:
            identifier = next(iter(matches))
            official_keys = matches[identifier]
            # A unique parcel with conflicting official address kinds still
            # lacks a canonical address; do not pick an arbitrary variant.
            if len(official_keys) != 1:
                counts["ambiguous_cadastral_address"] += 1
                continue
            official_key = next(iter(official_keys))
            published = dict(company, registered_address=canonical_address(official_key))
            if key[1] == "unknown":
                counts["matched_unknown_kind_companies"] += 1
            parcels[identifier].append(published)
    for companies in parcels.values():
        companies.sort(key=lambda x: x["uic"])
    counts["matched_companies"] = sum(len(v) for v in parcels.values())
    counts["matched_parcels"] = len(parcels)
    counts["matched_unique_addresses"] = len({c["registered_address"] for values in parcels.values() for c in values})
    for required in ("sofia_candidates", "matched_companies", "matched_parcels"):
        counts.setdefault(required, 0)
    return dict(parcels)


def valid_map_point(value):
    return isinstance(value, dict) and set(value) == {"lat", "lng"} and all(type(v) in (int, float) and math.isfinite(v) for v in value.values()) and 42.4 <= value["lat"] <= 43.1 and 22.8 <= value["lng"] <= 24


def parcel_representative_point(native_geojson, transformer):
    """One point inside the actual polygon, including its holes; no repair/snap."""
    from shapely.geometry import Point, shape
    from build_boundary_snapshot import geometry_vertices, transform_geometry
    if not isinstance(native_geojson, dict) or native_geojson.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("unsupported_point_geometry")
    native = shape(native_geojson)
    if native.is_empty or not native.is_valid:
        raise ValueError("invalid_native_point_geometry")
    transformed = transform_geometry(native_geojson, transformer)
    geometry_vertices(transformed)
    display = shape(transformed)
    if display.is_empty or not display.is_valid:
        raise ValueError("invalid_transformed_point_geometry")
    interior = native.representative_point()
    if not native.contains(interior):
        raise ValueError("native_representative_not_inside")
    lng, lat = transformer.transform(interior.x, interior.y, errcheck=True)
    point = {"lat": lat, "lng": lng}
    # Keep full precision: decimal rounding can move a narrow parcel's point
    # outside it. Also require it to remain inside the published display rings.
    if not valid_map_point(point) or not display.contains(Point(lng, lat)):
        raise ValueError("transformed_representative_not_inside")
    return point, hashlib.sha256(native.normalize().wkb).hexdigest()


def cadastral_points(parcels, archives, cadastre, counts):
    """Read matched official shapes from the same verified 24-archive capture."""
    import shapefile
    from pyproj.exceptions import ProjError
    from shapely.errors import GEOSException
    from build_boundary_snapshot import MAX_FEATURE_VERTICES, projection
    requested, points, identities, unusable, seen = set(parcels), {}, {}, set(), set()
    for source in cadastre["sources"]:
        path = archives / (source["code"] + ".zip")
        if path.is_symlink() or not path.is_file() or file_digest(path) != source["zip_sha256"]:
            raise ValueError("Point archive differs from verified cadastral capture")
        with ZipFile(path) as archive:
            entries = archive.infolist()
            candidates = [entry for entry in entries if entry.filename.lower().endswith(".shp")]
            if len(candidates) != 1:
                raise ValueError("One official parcel SHP is required for points")
            shp = candidates[0]
            stem = shp.filename[:-4]
            lookup = {entry.filename: entry for entry in entries}
            if any(stem + suffix not in lookup for suffix in (".shx", ".prj", ".dbf", ".cpg")) or shp.file_size > 256 * 1024 * 1024 or lookup[stem + ".shx"].file_size > 8 * 1024 * 1024 or lookup[stem + ".prj"].file_size > 8192:
                raise ValueError("Official point geometry companions exceed bounds or are missing")
            transformer = projection(archive.read(stem + ".prj").decode("utf-8"))
            with archive.open(shp) as shp_handle, archive.open(stem + ".shx") as shx_handle:
                reader = shapefile.Reader(shp=shp_handle, shx=shx_handle)
                shapes = reader.iterShapes()
                # structured_rows is safe here because cadastral_reference has
                # already verified every DBF and this pass rechecks its ZIP hash.
                for row, native_shape in zip(structured_rows(path), shapes, strict=True):
                    identifier = row["cadnum"]
                    if identifier not in requested:
                        continue
                    seen.add(identifier)
                    try:
                        if native_shape.shapeType != shapefile.POLYGON or not 4 <= len(native_shape.points) <= MAX_FEATURE_VERTICES:
                            raise ValueError("unsupported_point_shape")
                        point, identity = parcel_representative_point(native_shape.__geo_interface__, transformer)
                        if identifier in identities and identities[identifier] != identity:
                            raise ValueError("conflicting_point_geometry")
                        if identifier not in unusable:
                            identities[identifier], points[identifier] = identity, point
                    except (ValueError, TypeError, IndexError, OverflowError, GEOSException, ProjError):
                        unusable.add(identifier)
                        points.pop(identifier, None)
                reader.close()
    counts["unusable_point_geometry_parcels"] = len(unusable)
    counts["missing_point_geometry_parcels"] = len(requested - seen)
    return dict(sorted(points.items()))


def descriptor(payload, filename=None):
    result = {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    if filename:
        result["file"] = filename
    return result


def write_snapshot(output, parcels, source, cadastre, counts, points=None):
    snapshot_id = uuid4().hex
    directory = output / "business-snapshots" / snapshot_id
    if directory.exists():
        raise ValueError("Immutable business snapshot already exists")
    directory.mkdir(parents=True)
    shards, parcel_index, search = {}, {}, []
    group, group_size, shard_number = {}, 2, 0
    def flush():
        nonlocal group, group_size, shard_number
        if not group:
            return
        name = f"companies-{shard_number:03d}.json"
        if shard_number >= 512:
            raise ValueError("Business shard count exceeds limit")
        payload = json_bytes(group)
        if len(payload) > MAX_SHARD_BYTES:
            raise ValueError("Business shard exceeds limit")
        write_new(directory / name, payload)
        shards[name] = descriptor(payload)
        for identifier in group:
            parcel_index[identifier] = name
        group, group_size = {}, 2
        shard_number += 1
    for identifier in sorted(parcels):
        companies = parcels[identifier]
        entry_size = len(json_bytes({identifier: companies})) - 2
        if entry_size + 2 > MAX_SHARD_BYTES:
            raise ValueError("One parcel's company list exceeds shard limit")
        if group and group_size + entry_size + 1 > MAX_SHARD_BYTES:
            flush()
        group[identifier] = companies
        group_size += entry_size + int(len(group) > 1)
        for company in companies:
            search.append({k: company[k] for k in ("uic", "name", "registered_address")} | {"cadastral_id": identifier})
    flush()
    index_payload, search_payload = json_bytes(parcel_index), json_bytes(search)
    if len(index_payload) > MAX_INDEX_BYTES or len(search_payload) > MAX_INDEX_BYTES:
        raise ValueError("Business index exceeds hosting limit")
    write_new(directory / "parcel-index.json", index_payload)
    write_new(directory / "search-index.json", search_payload)
    manifest = {"version": 1, "snapshot_id": snapshot_id, "generated_at": utc_now(), "source": source, "cadastre": cadastre, "counts": dict(counts), "shards": shards, "parcel_index": descriptor(index_payload, "parcel-index.json"), "search_index": descriptor(search_payload, "search-index.json")}
    if points is not None:
        point_payload = json_bytes(points)
        if len(point_payload) > MAX_POINTS_BYTES:
            raise ValueError("Business points index exceeds hosting limit")
        write_new(directory / "points-index.json", point_payload)
        manifest["points_index"] = descriptor(point_payload, "points-index.json")
        mapped_companies = sum(len(parcels.get(identifier, [])) for identifier in points)
        manifest["counts"].update({"mapped_business_parcels": len(points), "unmapped_business_parcels": len(parcels) - len(points), "mapped_companies": mapped_companies, "unmapped_companies": counts["matched_companies"] - mapped_companies})
    payload = json_bytes(manifest)
    if len(payload) > MAX_MANIFEST_BYTES:
        raise ValueError("Business manifest exceeds limit")
    write_new(directory / "manifest.json", payload)
    pointer = {"version": 1, "snapshot_id": snapshot_id, "manifest_sha256": hashlib.sha256(payload).hexdigest()}
    # Validate the immutable tree before replacing any active local pointer.
    validate_snapshot(output, snapshot_id)
    pending = output / (".business-active-" + snapshot_id + ".json")
    write_new(pending, json_bytes(pointer))
    pending.replace(output / "business-active.json")
    return validate_snapshot(output)


def validate_company(company):
    if not isinstance(company, dict) or set(company) != COMPANY_FIELDS or any(not isinstance(v, str) for v in company.values()) or not valid_uic(company["uic"]):
        raise ValueError("Invalid public business record")
    if not company["name"] or not company["legal_form"] or company["status"] != "not_verified" or company["source_url"] != source_url(company["uic"]) or company["as_of"] and re.fullmatch(r"\d{4}-\d{2}-\d{2}", company["as_of"]) is None:
        raise ValueError("Invalid public business evidence")
    if company["as_of"]:
        date.fromisoformat(company["as_of"])
    for key, limit in TEXT_LIMITS.items():
        if len(company[key]) > limit or company[key] and safe_text(company[key], limit) != company[key]:
            raise ValueError("Unsafe public business field")
    key = address_key(company["registered_address"])
    if not key or canonical_address(key) != company["registered_address"] or not corporate_form(company["legal_form"]):
        raise ValueError("Invalid canonical business address or corporate form")


def validate_snapshot(output_root, snapshot_id=None):
    """Validate all allowlisted files/hashes and cross-index links; return manifest."""
    output_root = Path(output_root)
    pointer = None
    if snapshot_id is None:
        pointer = read_json(output_root / "business-active.json", 1024)
        if not isinstance(pointer, dict) or set(pointer) != {"version", "snapshot_id", "manifest_sha256"} or pointer.get("version") != 1 or not isinstance(pointer.get("manifest_sha256"), str) or not HEX64.fullmatch(pointer["manifest_sha256"]):
            raise ValueError("Invalid active business pointer")
        snapshot_id = pointer.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not HEX32.fullmatch(snapshot_id):
        raise ValueError("Invalid business snapshot identifier")
    directory = output_root / "business-snapshots" / snapshot_id
    if output_root.is_symlink() or (output_root / "business-snapshots").is_symlink() or directory.is_symlink():
        raise ValueError("Linked business snapshot path")
    manifest_path = directory / "manifest.json"
    manifest = read_json(manifest_path, MAX_MANIFEST_BYTES)
    if pointer is not None and file_digest(manifest_path) != pointer["manifest_sha256"]:
        raise ValueError("Business manifest pointer hash mismatch")
    if isinstance(manifest, dict) and manifest.get('version') == 2:
        from business_snapshot_v2 import validate_snapshot as validate_v2
        return validate_v2(output_root, snapshot_id)
    required_manifest = {"version", "snapshot_id", "generated_at", "source", "cadastre", "counts", "shards", "parcel_index", "search_index"}
    if not isinstance(manifest, dict) or set(manifest) not in (required_manifest, required_manifest | {"points_index"}) or manifest.get("version") != 1 or manifest.get("snapshot_id") != snapshot_id or not timestamp_valid(manifest.get("generated_at")):
        raise ValueError("Invalid business manifest")
    validate_source(manifest["source"])
    cadastre = manifest["cadastre"]
    if not isinstance(cadastre, dict) or set(cadastre) != {"manifest_sha256", "snapshot_id", "captured_from", "captured_to", "sources"} or not HEX64.fullmatch(cadastre.get("manifest_sha256", "")) or not HEX32.fullmatch(cadastre.get("snapshot_id", "")) or not all(timestamp_valid(cadastre.get(k)) for k in ("captured_from", "captured_to")) or not isinstance(cadastre.get("sources"), list) or len(cadastre["sources"]) != 24:
        raise ValueError("Invalid cadastral business evidence")
    for i, source in enumerate(cadastre["sources"]):
        if set(source) != {"code", "source_url", "zip_sha256", "captured_at"} or source["code"] != f"sofia-district-{i:02d}" or not isinstance(source["source_url"], str) or not source["source_url"].startswith("https://kais.cadastre.bg/bg/OpenData/Download?path=") or not HEX64.fullmatch(source["zip_sha256"]) or not timestamp_valid(source["captured_at"]):
            raise ValueError("Invalid cadastral source evidence")
    counts, shards = manifest["counts"], manifest["shards"]
    if not isinstance(counts, dict) or len(counts) > 80 or any(not isinstance(k, str) or re.fullmatch(r"[a-z_]+", k) is None or type(v) is not int or not 0 <= v <= 5_000_000 for k, v in counts.items()) or not {"matched_companies", "matched_parcels", "sofia_candidates"}.issubset(counts):
        raise ValueError("Invalid business coverage counts")
    if not isinstance(shards, dict) or len(shards) > 512 or any(not SHARD_NAME.fullmatch(k) for k in shards):
        raise ValueError("Invalid business shard names")
    total = manifest_path.stat().st_size
    def load_descriptor(metadata, filename=None, limit=MAX_INDEX_BYTES):
        nonlocal total
        expected = {"bytes", "sha256"} | ({"file"} if filename else set())
        if not isinstance(metadata, dict) or set(metadata) != expected or type(metadata.get("bytes")) is not int or not 1 <= metadata["bytes"] <= min(limit, MAX_FILE_BYTES) or not isinstance(metadata.get("sha256"), str) or not HEX64.fullmatch(metadata["sha256"]) or filename is not None and metadata.get("file") != filename:
            raise ValueError("Invalid business file descriptor")
        name = filename or current_name
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != metadata["bytes"] or file_digest(path) != metadata["sha256"]:
            raise ValueError("Business file hash or length mismatch")
        total += metadata["bytes"]
        if total > MAX_SNAPSHOT_BYTES:
            raise ValueError("Business snapshot exceeds total byte limit")
        return read_json(path, limit)
    parcel_index = load_descriptor(manifest["parcel_index"], "parcel-index.json")
    search = load_descriptor(manifest["search_index"], "search-index.json")
    if not isinstance(parcel_index, dict) or len(parcel_index) > 500_000 or any(not CAD_ID.fullmatch(k) or v not in shards for k, v in parcel_index.items()) or not isinstance(search, list) or len(search) > 1_000_000:
        raise ValueError("Invalid business indexes")
    points = None
    if "points_index" in manifest:
        points = load_descriptor(manifest["points_index"], "points-index.json", MAX_POINTS_BYTES)
        if not isinstance(points, dict) or any(identifier not in parcel_index or not valid_map_point(value) for identifier, value in points.items()):
            raise ValueError("Invalid business point membership or coordinates")
    seen_ids, seen_uics, expected_search = set(), set(), []
    mapped_companies = 0
    for current_name, metadata in shards.items():
        shard = load_descriptor(metadata, limit=MAX_SHARD_BYTES)
        if not isinstance(shard, dict) or not shard:
            raise ValueError("Empty or malformed business shard")
        for identifier, companies in shard.items():
            if not CAD_ID.fullmatch(identifier) or identifier in seen_ids or parcel_index.get(identifier) != current_name or not isinstance(companies, list) or not companies:
                raise ValueError("Invalid business parcel link")
            seen_ids.add(identifier)
            if points is not None and identifier in points:
                mapped_companies += len(companies)
            for company in companies:
                validate_company(company)
                if company["uic"] in seen_uics:
                    raise ValueError("Duplicate business UIC")
                seen_uics.add(company["uic"])
                expected_search.append({k: company[k] for k in ("uic", "name", "registered_address")} | {"cadastral_id": identifier})
    if set(parcel_index) != seen_ids or search != expected_search or counts["matched_companies"] != len(seen_uics) or counts["matched_parcels"] != len(seen_ids) or counts["sofia_candidates"] < len(seen_uics):
        raise ValueError("Business indexes/counts do not reconcile")
    allowed = {"manifest.json", "parcel-index.json", "search-index.json", *shards}
    if points is not None:
        expected_counts = {"mapped_business_parcels": len(points), "unmapped_business_parcels": len(parcel_index) - len(points), "mapped_companies": mapped_companies, "unmapped_companies": len(seen_uics) - mapped_companies}
        if any(counts.get(key) != value for key, value in expected_counts.items()):
            raise ValueError("Business point coverage counts do not reconcile")
        allowed.add("points-index.json")
    if {p.name for p in directory.iterdir()} != allowed:
        raise ValueError("Unexpected business snapshot files")
    return manifest


def build(args):
    if args.company_dir:
        directory = args.company_dir
        source = local_source(directory)
    else:
        import os
        directory, source = capture_source(args.cache, args.commit, os.environ.get("GITHUB_TOKEN"))
    reference, cadastre, counts = cadastral_reference(args.cadastre_manifest, args.cadastre_archives)
    selected, company_counts = select_companies(directory, source)
    counts.update(company_counts)
    parcels = match_companies(selected, reference, counts)
    if not args.without_municipal:
        from business_snapshot_v2 import enrich, write_snapshot as write_v2
        parcels, addresses, municipal_source = enrich(directory, source, selected, parcels, args, counts)
    points = cadastral_points(parcels, args.cadastre_archives, cadastre, counts)
    if args.without_municipal:
        manifest = write_snapshot(args.output, parcels, source, cadastre, counts, points)
    else:
        manifest = write_v2(args.output, parcels, addresses, source, cadastre, counts, points, municipal_source)
    print(json.dumps({"snapshot_id": manifest["snapshot_id"], "source_commit": source["commit"], "counts": manifest["counts"]}, ensure_ascii=True))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company-dir", type=Path, help="Verified pinned CSV directory; no network used")
    parser.add_argument("--cache", type=Path, default=Path("seed/deploy/company-exports"))
    parser.add_argument("--commit", help="Optional full source commit; default resolves current default-branch head")
    parser.add_argument("--cadastre-manifest", type=Path)
    parser.add_argument("--cadastre-archives", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--municipal-cache", type=Path, default=Path("seed/business/municipal"))
    parser.add_argument("--municipal-offline", action="store_true", help="Use only a previously verified municipal source capture")
    parser.add_argument("--without-municipal", action="store_true", help="Prepare legacy cadastral-address evidence only")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.validate_only:
        value = validate_snapshot(args.output)
        print(json.dumps({"snapshot_id": value["snapshot_id"], "counts": value["counts"]}, ensure_ascii=True))
    else:
        if args.cadastre_manifest is None or args.cadastre_archives is None:
            parser.error("--cadastre-manifest and --cadastre-archives are required when building")
        build(args)


if __name__ == "__main__":
    main()
