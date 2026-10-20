#!/usr/bin/env python3
"""Resolve advert location hints against a local, aggregated public reference.

This module never sends queries to a geocoder and never returns parcel IDs.
An approximate street/quarter location is not a property or cadastral match.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata

SOURCE_URL = "https://kais.cadastre.bg/bg/OpenData"
MAX_REFERENCE_BYTES = 4 * 1024 * 1024
DEFAULT_REFERENCE = Path(__file__).resolve().parents[1] / "public/data/market-georeference.json"
STREET_PREFIX = re.compile(r"(?<!\w)(улица|ул\.|ул\b|булевард|бул\.|бул\b|площад|пл\.|пл\b)\s*", re.I)
NEARBY = re.compile(r"\b(?:до|близо|близост|срещу|между|около|покрай|непосредствено|района|районът|лице|изглед|гледка|пресечка|пресечката|пресечки|отстояние|разстояние|пешеходно|метра|метри)\b", re.I)
OFFICE = re.compile(r"\b(?:офис|офисът|офиса|кантора|кантората|агенцията|агенция|представителство|контакти|адрес\s+за\s+контакт)\b", re.I)
DIRECT_PROPERTY = re.compile(r"(?:\b(?:на|в)\s*$|(?:намира|разположен|разположена|разположено|находящ|находяща|находящо|адрес)\b[^.!?;]{0,45}$)", re.I)


def stable_key(prefix, value):
    return prefix + "-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def plain(value):
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    value = value.replace("ѝ", "и").replace("–", "-").replace("—", "-")
    value = re.sub(r"[\"'„“”‘’`]+", "", value)
    return re.sub(r"\s+", " ", value).strip()


def neighborhood_name(value):
    """Only spelling/prefix equivalence; never infer a neighboring district."""
    value = plain(value).strip(" .,-")
    if not value or len(value) > 140 or re.search(r"\b(?:район|р-н|улица|булевард|грао|упи|парцел)\b|\b(?:ул|бул)\.", value):
        return None
    value = re.sub(r"^(?:(?:квартал|кв\.|кв\b|жилищна\s+група|ж\.?\s*гр\.?|ж\.?\s*к\.?|м-т|местност|м\.)\s*)+", "", value)
    value = re.sub(r"^в\.?\s*з\.?\s*", "вилна зона ", value)
    value = value.replace("і", "i")
    value = re.sub(r"\b(люлин|младост|надежда|обеля|връбница|красна поляна|овча купел)\s*[- ]?\s*(iv|iii|ii|i|v)\b", lambda m: m[1] + " " + {"i":"1","ii":"2","iii":"3","iv":"4","v":"5"}[m[2]], value)
    value = re.sub(r"(?<=\d)\s*a\b", "а", value)
    value = re.sub(r"(?<=\d)\s*(?:ч\.?|част|м\.?\s*р\.?)$", "", value)
    value = re.sub(r"[^а-яa-z0-9]+", " ", value).strip()
    value = re.sub(r"(?<=[а-я])(?=\d)", " ", value)
    if not re.search(r"[а-я]{2}", value) or re.search(r"\d{5,}", value):
        return None
    value = re.sub(r"\s+", " ", value)
    aliases = {"суха река":"сухата река", "лев толстой":"толстой", "толостой":"толстой", "илиенци":"илиянци", "левски зона в":"левски в", "левски зона г":"левски г", "разсадник коньовица":"разсадника", "разсадника коньовица":"разсадника"}
    return aliases.get(value, value)


def street_name(value):
    value = plain(value)
    match = STREET_PREFIX.match(value)
    if not match:
        return None
    prefix = match[1]
    kind = "boulevard" if prefix.startswith("бул") else "square" if prefix.startswith("пл") else "street"
    name = value[match.end():].strip(" .,-")
    # A reference street must be a street, not a concatenated address/locality.
    if not name or len(name) > 120 or re.search(r"[,@;№]|\b(?:неизвестн\w*|няма|без име|без наименование|грао|упи|квартал|кв\.|ж\.)\b|\d{6,}", name):
        return None
    name = re.sub(r"[^а-яa-z0-9]+", " ", name).strip()
    if not re.search(r"[а-я]{2}", name):
        return None
    return kind, re.sub(r"\s+", " ", name)


def distance_m(lat, lng, other_lat, other_lng):
    rad = math.pi / 180
    a = math.sin((other_lat - lat) * rad / 2) ** 2 + math.cos(lat * rad) * math.cos(other_lat * rad) * math.sin((other_lng - lng) * rad / 2) ** 2
    return 6371000 * 2 * math.atan2(math.sqrt(min(1, a)), math.sqrt(max(0, 1 - a)))


class LocationResolver:
    """Load once per snapshot and call resolve() for each normalized advert."""
    def __init__(self, reference=DEFAULT_REFERENCE):
        if isinstance(reference, dict):
            data = reference
        else:
            path = Path(reference)
            if path.is_symlink() or not 1 <= path.stat().st_size <= MAX_REFERENCE_BYTES:
                raise ValueError("Unsafe or oversized market location reference")
            data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != 1 or data.get("source_url") != SOURCE_URL or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data.get("reference_date", "")):
            raise ValueError("Unsupported market location reference")
        self.reference_date = data["reference_date"]
        self.places = {}
        self.streets = {}
        self.street_tokens = {}
        for group in ("places", "streets"):
            entries = data.get(group)
            if not isinstance(entries, list) or len(entries) > 12000:
                raise ValueError("Invalid market reference entry count")
            for item in entries:
                if not isinstance(item, dict) or not re.fullmatch(r"(?:place|street)-[a-f0-9]{16}", item.get("key", "")) or not isinstance(item.get("label_bg"), str) or len(item["label_bg"]) > 180:
                    raise ValueError("Invalid market reference label/key")
                if any(not isinstance(item.get(k), (float, int)) or isinstance(item.get(k), bool) or not math.isfinite(item[k]) for k in ("lat", "lng", "radius_m")) or not (42.4 <= item["lat"] <= 43 and 22.8 <= item["lng"] <= 24 and 200 <= item["radius_m"] <= 12000):
                    raise ValueError("Invalid market reference bounds")
                if group == "places":
                    name = neighborhood_name(item["label_bg"])
                    if name:
                        self.places.setdefault(name, []).append(item)
                else:
                    name = street_name(item["label_bg"])
                    if not name or not isinstance(item.get("place_keys"), list):
                        raise ValueError("Invalid market reference street")
                    self.streets.setdefault(name, []).append(item)
        for kind, name in self.streets:
            self.street_tokens.setdefault((kind, name.split()[0]), []).append(name)
        for names in self.street_tokens.values():
            names.sort(key=len, reverse=True)

    def _place(self, neighborhood):
        matches = self.places.get(neighborhood_name(neighborhood), [])
        return matches[0] if len(matches) == 1 else None

    def _street_hints(self, value, description=False):
        value = str(value or "")[:30000]
        hints = set()
        for match in STREET_PREFIX.finditer(value):
            # A clause may contain a property address or an office/nearby cue.
            preceding = value[max(0, match.start() - 110):match.start()]
            clause = re.split(r"[!?;\n]", preceding)[-1]
            if OFFICE.search(clause) or NEARBY.search(clause[-65:]):
                continue
            if description and not DIRECT_PROPERTY.search(clause):
                continue
            kind = "boulevard" if match[1].casefold().startswith("бул") else "square" if match[1].casefold().startswith("пл") else "street"
            following = value[match.end():match.end() + 140]
            normalized = re.sub(r"[^а-яa-z0-9]+", " ", plain(following)).strip()
            if not normalized:
                continue
            for name in self.street_tokens.get((kind, normalized.split()[0]), []):
                if normalized == name or normalized.startswith(name + " "):
                    # Longest known exact street name; never fuzzy-match names.
                    hints.add((kind, name))
                    break
        return hints

    def _resolve_street(self, hint, place):
        candidates = self.streets.get(hint, [])
        if place:
            local = [x for x in candidates if place["key"] in x["place_keys"]]
            if local:
                candidates = local
            else:
                # A contradictory/unsubstantiated street must not override the
                # stated neighborhood with a different part of the city.
                return None
        if len(candidates) != 1:
            return None
        return candidates[0]

    def _result(self, item, precision, evidence):
        return {"key": item["key"], "lat": item["lat"], "lng": item["lng"], "precision": precision,
                "label_bg": item["label_bg"], "radius_m": item["radius_m"],
                "method": "cadastre_street_reference" if precision == "street" else "cadastre_neighborhood_reference",
                "source_url": SOURCE_URL, "reference_date": self.reference_date, "evidence": evidence}

    def _typed_hints(self, values, source):
        hints = set()
        if not isinstance(values, list):
            return hints
        for item in values[:3]:
            if not isinstance(item, dict) or item.get("kind") != "street" or item.get("nearby") is not False or item.get("source") != source:
                continue
            value = item.get("name")
            if not isinstance(value, str) or not 2 <= len(value) <= 120 or OFFICE.search(value):
                continue
            typed = street_name(value)
            if typed:
                if typed in self.streets:
                    hints.add(typed)
                continue
            name = re.sub(r"[^а-яa-z0-9]+", " ", plain(value)).strip()
            # Extractors can preserve the street name without its original
            # ул/бул/пл prefix. All observed kinds remain candidates; ambiguous
            # kinds are not guessed, and house_number is deliberately ignored.
            hints.update((kind, name) for kind in ("street", "boulevard", "square") if (kind, name) in self.streets)
        return hints

    def resolve(self, *, neighborhood_bg=None, address_bg=None, description=None, location_hints=None):
        place = self._place(neighborhood_bg)
        if not place and re.match(r"^\s*(?:гр\.|град\b|с\.|село\b|в\.?\s*з\.)", str(neighborhood_bg or ""), re.I):
            # This reference is cadastral territory 68134. An unrepresented
            # nearby settlement/villa area must never inherit a homonymous
            # Sofia street merely because that street is unique in this file.
            return None
        for value, is_description, evidence, hint_source in ((address_bg, False, "listed_address", "card"), (description, True, "description_street", "description")):
            hints = self._street_hints(value, is_description) | self._typed_hints(location_hints, hint_source)
            if len(hints) == 1:
                street = self._resolve_street(next(iter(hints)), place)
                if street:
                    return self._result(street, "street", evidence)
            elif len(hints) > 1:
                # Two streets/intersections need an independently supported
                # intersection model; a guessed midpoint would be misleading.
                break
        return self._result(place, "neighborhood", "listed_neighborhood") if place else None


def resolve_location(reference, **kwargs):
    """Convenience interface; batch callers should reuse LocationResolver."""
    return LocationResolver(reference).resolve(**kwargs)
