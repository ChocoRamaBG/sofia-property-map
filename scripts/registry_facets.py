"""Compact filters derived from individual original register observations.

Districts come only from a stated district field. Addresses come only from an
address field or an explicit address marker in the scope. Description tags are
literal keyword matches in object descriptions, not cadastral classifications.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date

REFERENCE_FORMAT = "tuple-v2-facets"
MAX_FACET_VALUES = 100000
MAX_DISTRICTS = 2000
COVERAGE_KEYS = {"district_document_count", "dated_document_count", "address_document_count", "description_document_count", "total_document_count"}

DESCRIPTION_TAGS = (
    {"key": "housing", "label_bg": "В описанието: жилище", "label_en": "Description mentions housing", "bit": 1,
     "pattern": r"жилищ|еднофамил|многофамил|апартамент"},
    {"key": "business", "label_bg": "В описанието: бизнес", "label_en": "Description mentions business", "bit": 2,
     "pattern": r"офис|административ|магазин|търгов|ресторант|хотел"},
    {"key": "infrastructure", "label_bg": "В описанието: инфраструктура", "label_en": "Description mentions infrastructure", "bit": 4,
     "pattern": r"улиц|път|канализ|водопровод|кабел|трафопост|електр|газопровод"},
    {"key": "public", "label_bg": "В описанието: обществен обект", "label_en": "Description mentions a public facility", "bit": 8,
     "pattern": r"училищ|детск|болниц|спорт|образов|медицин"},
    {"key": "parking", "label_bg": "В описанието: гараж / паркинг", "label_en": "Description mentions garages / parking", "bit": 16,
     "pattern": r"гараж|паркинг"},
)
DESCRIPTION_MASK = 31

DISTRICT_FIELDS = {"район", "district"}
ADDRESS_FIELDS = {"адрес", "address"}
SCOPE_FIELDS = {"местоположение", "обхват", "обхват и идентификатори", "scope and identifiers", "scope", "location"}
OBJECT_FIELDS = {"обект", "строеж/обект", "строеж / обект", "object", "construction / object", "construction/object"}
ADDRESS_MARKER = re.compile(r"(?:^|[,;\n])\s*(?:адрес|address)(?:\s*:\s*|\s+)([^\n]+)", re.IGNORECASE)


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def normalized_key(value: str) -> str:
    return normalized_text(value).casefold()


def stated_text(value) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    return "" if text.casefold() in ("", "-", "—", "–", "n/a", "null", "няма") else text


def observation_facets(document: dict) -> tuple[str | None, str | None, str | None, int, int, bool]:
    """Return district key/label, issue date, address bit, tags and object coverage."""
    district = None
    address = False
    objects = []
    for field, value in document["raw_fields"].items():
        key = normalized_key(field)
        text = stated_text(value)
        if not text:
            continue
        if key in DISTRICT_FIELDS and district is None:
            district = normalized_text(text)
        if key in ADDRESS_FIELDS:
            address = True
        elif key in SCOPE_FIELDS:
            marker = ADDRESS_MARKER.search(text)
            if marker and stated_text(marker[1]):
                address = True
        if key in OBJECT_FIELDS:
            objects.append(text)
    object_text = "\n".join(objects).casefold()
    tag_mask = sum(tag["bit"] for tag in DESCRIPTION_TAGS if re.search(tag["pattern"], object_text))
    # Never use capture/import dates or effective dates as a document issue date.
    return normalized_key(district) if district else None, district, document.get("issued_at"), int(address), tag_mask, bool(objects)


def build_filter_facets(documents: list[dict]) -> tuple[dict, dict[tuple[str, str], int]]:
    """Deduplicate per-observation tuples; parcel refs store one dictionary index."""
    ordered = sorted(documents, key=lambda item: (item["source_code"], item["document_hash"]))
    observations = [(document, observation_facets(document)) for document in ordered]
    district_labels = {}
    district_counts = Counter()
    tag_counts = Counter()
    dates = []
    coverage = {"district_document_count": 0, "dated_document_count": 0, "address_document_count": 0,
                "description_document_count": 0, "total_document_count": len(ordered)}
    for _, (key, label, issued_at, address, tags, has_description) in observations:
        if key is not None:
            if len(key) > 200 or len(label) > 200:
                raise ValueError("A stated district exceeds the compact filter bounds")
            district_labels.setdefault(key, label)
            district_counts[key] += 1
            coverage["district_document_count"] += 1
        if issued_at is not None:
            dates.append(issued_at)
            coverage["dated_document_count"] += 1
        coverage["address_document_count"] += address
        coverage["description_document_count"] += int(has_description)
        for tag in DESCRIPTION_TAGS:
            if tags & tag["bit"]:
                tag_counts[tag["key"]] += 1
    districts = [{"key": key, "label": district_labels[key], "document_count": district_counts[key]} for key in sorted(district_labels)]
    district_positions = {row["key"]: position for position, row in enumerate(districts)}
    values = []
    positions = {}
    refs = {}
    for document, (key, _, issued_at, address, tags, _) in observations:
        value = (district_positions[key] if key is not None else None, issued_at, address, tags)
        if value not in positions:
            positions[value] = len(values)
            values.append(list(value))
        identity = (document["source_code"], document["document_hash"])
        if identity in refs:
            raise ValueError("Repeated source/document identity while preparing filters")
        refs[identity] = positions[value]
    facets = {"version": 1, "districts": districts, "values": values,
              "date_min": min(dates) if dates else None, "date_max": max(dates) if dates else None,
              "address_document_count": coverage["address_document_count"], "coverage": coverage,
              "description_tags": [{key: tag[key] for key in ("key", "label_bg", "label_en", "bit")} | {"document_count": tag_counts[tag["key"]]} for tag in DESCRIPTION_TAGS]}
    validate_filter_facets(facets)
    return facets, refs


def valid_date(value) -> bool:
    if value is None:
        return True
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def valid_count(value) -> bool:
    return type(value) is int and 0 <= value <= MAX_FACET_VALUES


def validate_filter_facets(facets) -> None:
    """Reject malformed or unbounded filter metadata before processing refs."""
    if not isinstance(facets, dict) or type(facets.get("version")) is not int or facets["version"] != 1:
        raise ValueError("Unsupported compact registry filter contract")
    districts = facets.get("districts")
    values = facets.get("values")
    if not isinstance(districts, list) or len(districts) > MAX_DISTRICTS or not isinstance(values, list) or len(values) > MAX_FACET_VALUES:
        raise ValueError("Compact registry filters exceed their dictionary bounds")
    seen = set()
    for district in districts:
        if not isinstance(district, dict) or not all(isinstance(district.get(key), str) and 1 <= len(district[key]) <= 200 for key in ("key", "label")) or district["key"] != normalized_key(district["label"]) or district["key"] in seen or not valid_count(district.get("document_count")):
            raise ValueError("Malformed or repeated stated district")
        seen.add(district["key"])
    seen_values = set()
    for value in values:
        if not isinstance(value, list) or len(value) != 4 or (value[0] is not None and (type(value[0]) is not int or not 0 <= value[0] < len(districts))) or not valid_date(value[1]) or type(value[2]) is not int or value[2] not in (0, 1) or type(value[3]) is not int or not 0 <= value[3] <= DESCRIPTION_MASK:
            raise ValueError("Malformed per-observation filter tuple")
        identity = tuple(value)
        if identity in seen_values:
            raise ValueError("Compact filter dictionary repeats a tuple")
        seen_values.add(identity)
    if not valid_date(facets.get("date_min")) or not valid_date(facets.get("date_max")) or ((facets.get("date_min") is None) != (facets.get("date_max") is None)) or (facets.get("date_min") is not None and facets["date_min"] > facets["date_max"]):
        raise ValueError("Compact filters have invalid issue-date bounds")
    coverage = facets.get("coverage")
    if not isinstance(coverage, dict) or set(coverage) != COVERAGE_KEYS or not all(valid_count(value) for value in coverage.values()) or any(value > coverage["total_document_count"] for value in coverage.values()) or facets.get("address_document_count") != coverage["address_document_count"]:
        raise ValueError("Compact filter coverage counts are invalid")
    tags = facets.get("description_tags")
    if not isinstance(tags, list) or len(tags) != len(DESCRIPTION_TAGS):
        raise ValueError("Compact description tags are invalid")
    for expected, tag in zip(DESCRIPTION_TAGS, tags):
        if not isinstance(tag, dict) or any(tag.get(key) != expected[key] for key in ("key", "label_bg", "label_en", "bit")) or not valid_count(tag.get("document_count")) or tag["document_count"] > coverage["total_document_count"]:
            raise ValueError("Compact description tag metadata is invalid")
