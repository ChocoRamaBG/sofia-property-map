#!/usr/bin/env python3
"""Derive bounded advert claims without retaining descriptions/private contacts.

List-card clues are cheap and cover the complete census. A separate paced,
optional pass reads up to 1,200 public detail pages per day (400 by default). Its partial coverage
never changes whether the underlying price capture is complete.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import urljoin, urlparse

MAX_LISTINGS = 50000
MAX_INPUT_BYTES = 96 * 1024 * 1024
SELLER_TYPES = {"agency", "private", "unknown"}
SELLER_EVIDENCE = {"agency_profile", "explicit_private_claim", "not_reported", "conflicting_signals"}
RISK_FLAGS = {"share_sale", "auction", "tenanted", "nonresidential", "mandatory_extra_cost"}
PRIVATE_CLAIM = re.compile(r"(?:частно\s+лице\s+(?:продава|предлага)|(?:продава|продавам)\s+(?:като\s+)?собственик|(?:директно\s+)?от\s+собственик(?:а)?\b)", re.I)
STREET = re.compile(r"\b(улица\b|ул\.|ул\b|булевард\b|бул\.|бул\b|площад\b|пл\.|пл\b)\s*[„\"'«]?", re.I)
ANALYSIS_METHOD_VERSION = 3
CACHE_VERSION = 3
CLAIM_FIELDS = ("seller_type", "seller_evidence", "seller_checked_at", "agency", "property_features", "analysis", "location_hints", "analysis_method_version")
CACHE_FIELDS = ("version", "card_sha256", "checked_at", "status", "description_sha256", *CLAIM_FIELDS)
FEATURE_FIELDS = {"construction_type", "furnishing", "building_year", "year_basis", "floor_number", "total_floors", "elevator", "checked_at", "source"}
AGENCY_FIELDS = {"name", "profile_url", "phone", "website", "checked_at", "evidence"}


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def clean(value, maximum=16000):
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).split())[:maximum]


def private_claim(value):
    for match in PRIVATE_CLAIM.finditer(value):
        before = value[max(0, match.start() - 20):match.start()].casefold()
        if not re.search(r"(?:не\s+е|не\s+съм|не\s+като|не)\s*$", before):
            return True
    return False


def seller_claim(agency_profile, value, checked_at=None):
    direct = private_claim(clean(value))
    if agency_profile and direct:
        kind, evidence = "unknown", "conflicting_signals"
    elif agency_profile:
        kind, evidence = "agency", "agency_profile"
    elif direct:
        kind, evidence = "private", "explicit_private_claim"
    else:
        kind, evidence = "unknown", "not_reported"
    return {"seller_type": kind, "seller_evidence": evidence, "seller_checked_at": checked_at or timestamp()}


def agency_profile(card, *, detail=False):
    """The profile proves a professional advertiser, never a property address."""
    selector = ".AG a.name[href]" if detail else ".seller .sInfo .name a[href], .AG a.name[href]"
    for link in card.select(selector):
        parsed = urlparse(urljoin("https://www.imot.bg", link["href"]))
        host = (parsed.hostname or "").casefold()
        try:
            if (parsed.scheme == "https" and host.endswith(".imot.bg") and host not in {"www.imot.bg", "imot.bg"}
                    and not parsed.username and not parsed.password and parsed.port in (None, 443)):
                return True
        except ValueError:
            continue
    return False


def professional_url(value):
    """Accept only a named professional subdomain, with no credentials/port."""
    value = str(value or "")
    if re.search(r"[\x00-\x20\x7f]", value):
        return None
    parsed = urlparse(urljoin("https://www.imot.bg", value))
    host = (parsed.hostname or "").casefold()
    try:
        valid = (parsed.scheme == "https" and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.imot\.bg", host) and host != "www.imot.bg"
                 and not parsed.username and not parsed.password and parsed.port is None)
    except ValueError:
        return None
    if not valid or len(parsed.geturl()) > 500:
        return None
    return parsed._replace(netloc=host, fragment="").geturl()


def public_website(value):
    value = str(value or "")
    if re.search(r"[\x00-\x20\x7f]", value):
        return None
    parsed = urlparse(value)
    host = (parsed.hostname or "").casefold()
    labels = host.split(".")
    valid_host = (len(labels) >= 2 and len(host) <= 253 and re.fullmatch(r"[a-z]{2,63}", labels[-1])
                  and all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels))
    try:
        valid = (parsed.scheme == "https" and valid_host
                 and host not in {"localhost", "imot.bg"} and not host.endswith(".imot.bg")
                 and not parsed.username and not parsed.password and parsed.port is None)
    except ValueError:
        return None
    return parsed._replace(netloc=host, fragment="").geturl() if valid and len(parsed.geturl()) <= 500 else None


def public_phone(value):
    value = str(value or "").removeprefix("tel:")
    # An advertised extension or several concatenated numbers is not one phone.
    if not re.fullmatch(r"\+?[\d\s().-]{7,30}", value.strip()):
        return None
    number = re.sub(r"[\s().-]", "", value)
    digits = number.lstrip("+")
    return number if 7 <= len(digits) <= 15 and digits.isascii() and digits.isdigit() else None


def agency_details(card, *, detail=False, checked_at=None, known_agency=None):
    """Read contacts only inside a proven professional seller DOM block.

    Property descriptions, generic page footer contacts and private sellers are
    deliberately outside this selector. No broker's personal name is copied.
    """
    selector = ".AG a.name[href]" if detail else ".seller .sInfo .name a[href], .AG a.name[href]"
    candidates = []
    links = [(link, None) for link in card.select(selector)]
    # Current detail pages use a dealer2023 broker block instead of legacy AG.
    # Its profile links have generic labels; reuse only the already observed
    # professional card identity and require that same hostname in this block.
    if detail and isinstance(known_agency, dict) and professional_url(known_agency.get("profile_url")):
        expected_host = urlparse(known_agency["profile_url"]).hostname
        for block in card.select(".dealer2023.broker"):
            profile_links = [link for link in block.select("a[href]") if professional_url(link.get("href"))]
            hosts = {urlparse(professional_url(link["href"])).hostname for link in profile_links}
            if hosts == {expected_host} and profile_links:
                links.append((profile_links[0], block))
    for link, modern_scope in links:
        profile = professional_url(link.get("href"))
        name = clean(known_agency.get("name") if modern_scope is not None else link.get_text(" ", strip=True), 120)
        if modern_scope is not None:
            profile = known_agency["profile_url"]
        if not profile or not name or re.search(r"@|https?://|\d{7,}", name):
            continue
        scope = modern_scope if modern_scope is not None else link.find_parent(class_="AG") or link.find_parent(class_="seller")
        if scope is None:
            continue
        phone, website = None, None
        for contact in scope.select('a[href^="tel:"]'):
            phone = public_phone(contact.get("href"))
            if phone:
                break
        # Many source cards print the number instead of a tel link. Restrict
        # fallback to an explicitly named phone element in the seller block.
        if phone is None:
            for contact in scope.select(".phone, .phones, .tel, .telephone"):
                phone = public_phone(clean(contact.get_text(" ", strip=True), 40))
                if phone:
                    break
        for contact in scope.select("a[href]"):
            candidate_url = public_website(contact.get("href"))
            label = clean(" ".join([contact.get_text(" ", strip=True), contact.get("title", ""), " ".join(contact.get("class", []))])).casefold()
            candidate_host = (urlparse(candidate_url).hostname or "").removeprefix("www.") if candidate_url else ""
            if candidate_url and (candidate_host in label or re.search(r"\b(?:website|site|web|сайт)\b", label)):
                website = candidate_url
                break
        candidate = {"name": name, "profile_url": profile, "phone": phone, "website": website,
                     "checked_at": checked_at or timestamp(), "evidence": "professional_profile"}
        candidates.append(candidate)
    identities = {(item["name"].casefold(), item["profile_url"]) for item in candidates}
    return candidates[0] if len(identities) == 1 else None


def _positive_matches(value, pattern):
    return [match for match in re.finditer(pattern, value, re.I)
            if not re.search(r"(?:не\s+е|не\s+са|няма|без|не)\s*$", value[max(0, match.start() - 16):match.start()], re.I)]


def property_features(value, *, source="card", checked_at=None, completion_label=None, floor_label=None):
    """Explicit advertiser claims only; conflicting facts remain unknown."""
    value = clean(value)
    structure = {
        "brick": r"\bтухл(?:а|ен|ена|ено|ени)\b",
        "panel": r"\bпанел(?:ен|на|но|ни)?\b",
        "epk": r"\b[ЕE][ПP][КK]\b|едроплощен\s+кофраж",
        "monolithic": r"\bмонолит(?:ен|на|но|ни)?\b|стоманобетон(?:на|ен|но)?\s+конструкци",
        "other": r"\bгредоред\b|\bкирпич\b|\bсглобяем(?:а|о)?\s+конструкци|\bдървен(?:а|о)?\s+конструкци",
    }
    kinds = {kind for kind, pattern in structure.items() if _positive_matches(value, pattern)}
    # Brick infill and a monolithic frame describe one common structure; the
    # explicit brick category is more useful than treating that as a conflict.
    if kinds == {"brick", "monolithic"}:
        kinds = {"brick"}
    construction = next(iter(kinds)) if len(kinds) == 1 else "unknown"
    partial = list(re.finditer(r"\bчастично\s+обзаведен(?:а|о|и)?\b", value, re.I))
    furnished = [match for match in _positive_matches(value, r"\bобзаведен(?:а|о|и)?\b|\bс\s+(?:цялото\s+)?обзавеждане\b")
                 if not any(part.start() <= match.start() < part.end() for part in partial)]
    unfurnished = list(re.finditer(r"\bнеобзаведен(?:а|о|и)?\b|\bбез\s+(?:мебели|обзавеждане)\b|\bне\s+е\s+обзаведен(?:а|о)?\b", value, re.I))
    furnishings = ({"partial"} if partial else set()) | ({"furnished"} if furnished else set()) | ({"unfurnished"} if unfurnished else set())
    furnishing = next(iter(furnishings)) if len(furnishings) == 1 else "unknown"
    year_claims = set()
    stage = clean(completion_label)
    for text_value in (stage, value):
        for match in re.finditer(r"(ще\s+бъде\s+въведен(?:а|о)?\s+в\s+експлоатация|въведен(?:а|о)?\s+в\s+експлоатация|(?:година\s+на\s+строителство|строителство|построен(?:а|о)?|завършен(?:а|о)?))\s*[:–—-]?\s*(?:(?:тухла|панел|епк|монолит(?:на|но|ен)?)\s*[,;]?\s*)?(\d{4})(?!\s*[-–]\s*\d{4})\s*(?:г\.?|год(?:ина)?\b)?", text_value, re.I):
            year = int(match[2])
            if 1800 <= year <= datetime.now(timezone.utc).year + 15:
                basis = "planned" if match[1].casefold().startswith("ще") else "commissioned" if "експлоатация" in match[1].casefold() else "built"
                year_claims.add((year, basis))
    years = {year for year, _ in year_claims}
    basis_set = {basis for _, basis in year_claims}
    year = next(iter(years)) if len(years) == 1 and not {"planned", "commissioned"}.issubset(basis_set) and not {"planned", "built"}.issubset(basis_set) else None
    year_basis = "commissioned" if year is not None and "commissioned" in basis_set else next(iter(basis_set)) if year is not None else "unknown"
    floor_text = clean(floor_label) or value
    floor_match = re.search(r"(?:^|[,;\s])(?:етаж\s*:?\s*)?(-?\d{1,3})(?:\s*[-–]?\s*(?:ви|ри|ти|ми|и))?\s*(?:ет\.?|етаж)(?:\s+от\s+(\d{1,3}))?\b", floor_text, re.I)
    if not floor_match:
        floor_match = re.search(r"\b(?:етаж|ет\.)\s*:?\s*(-?\d{1,3})(?:\s+от\s+(\d{1,3}))?\b", floor_text, re.I)
    floor = int(floor_match[1]) if floor_match and -5 <= int(floor_match[1]) <= 100 else None
    total = int(floor_match[2]) if floor_match and floor_match[2] and 1 <= int(floor_match[2]) <= 100 else None
    if floor is None and re.search(r"\bпартер\b", floor_text, re.I):
        floor = 0
    if floor is None and re.search(r"\bсутерен\b", floor_text, re.I):
        floor = -1
    if floor is not None and total is not None and floor > total:
        floor, total = None, None
    no_lift = bool(re.search(r"\bбез\s+асансьор|\bняма\s+асансьор", value, re.I))
    has_lift = bool(_positive_matches(value, r"\b(?:с(?:ъс)?|има|наличен|работещ|нов)\s+асансьор\b|\bасансьор\s*:\s*да\b"))
    return {"construction_type": construction, "furnishing": furnishing, "building_year": year, "year_basis": year_basis,
            "floor_number": floor, "total_floors": total, "elevator": "unknown" if no_lift == has_lift else "no" if no_lift else "yes",
            "checked_at": checked_at or timestamp(), "source": source}


def merge_features(card, detail):
    if not isinstance(card, dict):
        return detail
    result = dict(detail)
    for key in ("construction_type", "furnishing", "elevator", "floor_number", "total_floors"):
        unknown = None if key in {"floor_number", "total_floors"} else "unknown"
        left, right = card.get(key, unknown), detail.get(key, unknown)
        result[key] = left if right == unknown else right if left == unknown or left == right else unknown
    left, right = (card.get("building_year"), card.get("year_basis")), (detail.get("building_year"), detail.get("year_basis"))
    if right[0] is None:
        result["building_year"], result["year_basis"] = left
    elif left[0] is not None and left != right:
        result["building_year"], result["year_basis"] = None, "unknown"
    if result.get("floor_number") is not None and result.get("total_floors") is not None and result["floor_number"] > result["total_floors"]:
        result["floor_number"], result["total_floors"] = None, None
    return result


def merge_agency(card, detail):
    if not isinstance(card, dict):
        return detail
    if not isinstance(detail, dict):
        return card
    if card.get("profile_url") != detail.get("profile_url") or card.get("name", "").casefold() != detail.get("name", "").casefold():
        return None
    result = dict(detail)
    for key in ("phone", "website"):
        result[key] = detail.get(key) or card.get(key)
    return result


def location_hints(value, source="card"):
    """Only explicit street introductions; office blocks never reach this input."""
    answer, seen = [], set()
    for match in STREET.finditer(value):
        context = value[max(0, match.start() - 110):match.start()].casefold()
        clause = re.split(r"[!?;]", context)[-1]
        if re.search(r"\b(?:офис|офисът|офиса|кантора|кантората|агенцията|агенция|представителство|контакти)\b", clause):
            continue
        # A street mentioned in marketing text can be an amenity or an office.
        # Structural property addresses also resolve independently from address_bg.
        if not re.search(r"(?:\b(?:на|в)\s*$|(?:намира|разположен|разположена|разположено|находящ|находяща|находящо|адрес)\b[^.!?;]{0,45}$)", clause):
            continue
        tail = value[match.end():match.end() + 140]
        # Stop before a new sentence, prose clause, a contact or another fact.
        name = re.split(r"[,;:()\n\r!?\"„“”«»]|\s+(?:№|номер|на|до|се|с|е|в|от|етаж|ет\.|тел\.?|телефон|апартамент|където|която|който)\b", tail, maxsplit=1, flags=re.I)[0]
        name = name.strip(" .'-–—")
        house = re.search(r"(?:\s+№?\s*)(\d{1,4}[А-Яа-яA-Za-z]?(?:\s*[-–]\s*\d{1,4}[А-Яа-яA-Za-z]?)?)\s*$", name)
        house_number = house[1].replace(" ", "") if house else None
        if house:
            name = name[:house.start()].strip(" .'-–—")
        if not name or len(name) > 80 or len(name.split()) > 7 or re.search(r"@|\d{5,}|https?://|телефон|gsm", name, re.I):
            continue
        after_name = value[match.end() + len(name):match.end() + len(name) + 24]
        if house_number is None:
            numbered = re.match(r"[\s„\"'«»“”]*\s*(?:№|номер)\s*(\d{1,4}[А-Яа-яA-Za-z]?)\b", after_name, re.I)
            house_number = numbered[1] if numbered else None
        nearby = bool(re.search(r"(?:близо|близост|метр[аи]|минути|пеша|пешеход|непосредствено\s+до|(?:^|\s)до|около|срещу|недалеч|между|пресечка|лице|изглед|гледка)\b", context[-70:]))
        key = (name.casefold(), house_number, nearby)
        if key not in seen:
            seen.add(key)
            answer.append({"kind": "street", "name": name, "house_number": house_number, "nearby": nearby, "source": source})
        if len(answer) == 3:
            break
    return answer


def matched_area_basis(value, area_sqm):
    """Associate the advertised area only with matching, explicitly labeled m².

    Mentioning another net area, or simply having a terrace, says nothing about
    the basis of the price-card area. Ambiguous matching labels remain unknown.
    """
    try:
        area = float(area_sqm)
    except (TypeError, ValueError):
        return "unknown"
    if not math.isfinite(area) or area <= 0:
        return "unknown"
    # Both absolute and relative differences must be small.
    tolerance = min(0.5, area * 0.01)
    amount = r"(?P<area>\d{1,4}(?:[.,]\d{1,3})?)"
    unit = r"(?:кв\.?\s*м\.?|м[2²]|m[2²])"
    gap = r"\s*(?:\([^\d()]{0,20}\)\s*)?(?:(?:е|от|около|приблизително|в\s+размер\s+на)\s*)?[:=\-–—]?\s*"
    labels = {
        "net": r"(?:чиста|нетна|застроена)\s+(?:жилищна\s+)?площ|(?:чиста|нетна)\s+квадратура",
        "gross": r"(?:обща|брутна)\s+(?:застроена\s+)?площ|площ\s+с\s+общи(?:те)?\s+части|(?:обща|брутна)\s+квадратура|с\s+общи(?:те)?\s+части",
        "terrace_included": r"(?:площ|квадратура)\s+(?:заедно\s+)?с\s+(?:включени(?:те)?\s+)?(?:терас(?:а|и|ите)|балкон(?:а|и|ите)?)",
    }
    found = set()
    for basis, label in labels.items():
        patterns = [r"(?:" + label + r")" + gap + amount + r"\s*" + unit + r"(?!\w)",
                    r"(?<![\d.,])" + amount + r"\s*" + unit + r"\s*[,;:=\-–—]?\s*\(?\s*(?:" + label + r")\b"]
        if basis == "terrace_included":
            # An explicit inclusion attached directly to the matching total;
            # 'с тераса' as a generic amenity deliberately does not qualify.
            patterns.append(r"(?<![\d.,])" + amount + r"\s*" + unit + r"\s*[,;:]?\s*(?:с\s+включен(?:а|и|и\s+те)|включващ(?:а|и|о)?|която\s+включва)\s+(?:терас(?:а|и|ите)|балкон(?:а|и|ите)?)\b")
        for pattern in patterns:
            for match in re.finditer(pattern, value, re.I):
                if basis == "net" and re.search(r"(?:обща|брутна)\s+$", value[max(0, match.start() - 15):match.start()], re.I):
                    continue
                stated = float(match["area"].replace(",", "."))
                if abs(stated - area) <= tolerance + 1e-9:
                    found.add(basis)
    return next(iter(found)) if len(found) == 1 else "unknown"


def analyze_text(value, *, source="card", checked_at=None, completion_label=None, area_sqm=None):
    value = clean(value)
    lower = value.casefold()
    stage_text = clean(completion_label) + " " + value
    planned = re.search(r"не\s+(?:е\s+)?въведен|ще\s+бъде\s+въведен|предстои.{0,35}акт\s*16|акт\s*16.{0,25}предстои|без\s+акт\s*16|в\s+строеж|на\s+проект", stage_text, re.I)
    completed = re.search(r"(?<!бъде )въведен(?:а|о)?\s+в\s+експлоатация|(?:със?|получен|има)\s+акт\s*16", stage_text, re.I)
    completion = "planned" if planned else "completed" if completed else "unknown"
    needs = re.search(r"(?:нуждае\s+се\s+от|за|нужен\s+е|предстои)\s+(?:основен\s+)?ремонт|за\s+освежаване|нуждае\s+се\s+от\s+освежаване", lower)
    renovated = re.search(r"след\s+(?:основен\s+|цялостен\s+)?ремонт|напълно\s+ремонтиран|новоремонтиран|изцяло\s+реновиран", lower)
    condition = "needs_renovation" if needs else "renovated" if renovated else "unknown"
    basis = matched_area_basis(lower, area_sqm)
    risks = []
    patterns = {
        "share_sale": r"(?:продава(?:т\s+се)?|продажба\s+на)\s+(?:само\s+)?(?:\d+\s*/\s*\d+\s+)?идеални\s+части|(?:продава|продажба).{0,25}\d+\s*/\s*\d+\s+(?:от\s+)?(?:имота|апартамента)|дял\s+от\s+(?:имот|апартамент)",
        "auction": r"публична\s+продан|съдебен\s+изпълнител|\bчси\b",
        "tenanted": r"(?:с\s+|има\s+|настанен\s+)наемател|отдаден\s+под\s+наем",
        "nonresidential": r"(?:статут|статус)\s*(?:на|:)?\s*(?:ателие|офис|кабинет)|със?\s+статут\s+(?:на\s+)?(?:ателие|офис)",
        "mandatory_extra_cost": r"задължително.{0,45}(?:паркомясто|гараж|закупуване|такса)|(?:паркомясто|гараж).{0,35}задължително|такса\s+поддръжка",
    }
    for name, pattern in patterns.items():
        if any(not re.search(r"(?:без|няма|не\s+е|не\s+се|не\s+е\s+отдаден)\s*$", lower[max(0, match.start() - 22):match.start()])
               for match in re.finditer(pattern, lower)):
            risks.append(name)
    return {
        "analysis": {"completion_stage": completion, "condition": condition, "area_basis": basis,
                     "risk_flags": risks, "checked_at": checked_at or timestamp(), "description_analyzed": source == "description"},
        "location_hints": location_hints(value, source),
        "analysis_method_version": ANALYSIS_METHOD_VERSION,
    }


def card_fingerprint(row, teaser, profile):
    # Dates and contact suffixes do not turn unchanged claims into cache misses.
    scrubbed = re.split(r"(?:тел\.?\s*:|телефон|gsm\s*:|e-?mail\s*:)", clean(teaser), maxsplit=1, flags=re.I)[0]
    fields = {key: row.get(key) for key in ("id", "url", "neighborhood_bg", "type_bg", "price", "price_currency", "vat_basis", "area_sqm", "construction_year", "construction_label_bg", "floor_bg", "address_bg")}
    if isinstance(row.get("agency"), dict):
        fields["agency"] = {key: value for key, value in row["agency"].items() if key != "checked_at"}
    if isinstance(row.get("property_features"), dict):
        fields["property_features"] = {key: value for key, value in row["property_features"].items() if key != "checked_at"}
    fields.update({"teaser": scrubbed, "agency_profile": bool(profile), "analysis_method_version": ANALYSIS_METHOD_VERSION})
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def detail_description(soup):
    # Modern source heading is necessary: other .text blocks include offices.
    for block in soup.select("div.moreInfo"):
        heading = block.select_one("span.blockTitle h2, h2")
        if heading and re.fullmatch(r"Описание\s+на\s+имота\s*:?​?", clean(heading.get_text(" ", strip=True)), re.I):
            node = block.select_one(":scope > .text")
            if node:
                return clean(node.get_text(" ", strip=True))
    legacy = soup.select_one("#description_div")
    return clean(legacy.get_text(" ", strip=True)) if legacy else None


def detail_property_facts(soup):
    """Dedicated property fields/amenities, excluding offices and contacts."""
    parts = [clean(node.get_text(" ", strip=True), 2000) for node in soup.select(".adParams, .carExtri")]
    for node in soup.select(".carExtri .items > div, .carExtri .items > span"):
        if re.fullmatch(r"Асансьор", clean(node.get_text(" ", strip=True)), re.I):
            parts.append("С асансьор")
    return clean(" ; ".join(parts), 6000)


def _valid_cache(entry, fingerprint, now):
    if not isinstance(entry, dict) or not set(CLAIM_FIELDS).issubset(entry) or entry.get("version") != CACHE_VERSION or entry.get("analysis_method_version") != ANALYSIS_METHOD_VERSION or entry.get("card_sha256") != fingerprint or entry.get("seller_type") not in SELLER_TYPES or entry.get("seller_evidence") not in SELLER_EVIDENCE:
        return False
    try:
        age = (now - datetime.fromisoformat(entry["checked_at"].replace("Z", "+00:00"))).total_seconds()
    except (KeyError, TypeError, ValueError):
        return False
    analysis = entry.get("analysis")
    hints = entry.get("location_hints")
    features = entry.get("property_features")
    agency = entry.get("agency")
    valid_features = (isinstance(features, dict) and set(features) == FEATURE_FIELDS
                      and features.get("construction_type") in {"brick", "panel", "epk", "monolithic", "other", "unknown"}
                      and features.get("furnishing") in {"furnished", "partial", "unfurnished", "unknown"}
                      and features.get("year_basis") in {"built", "commissioned", "planned", "unknown"}
                      and (features.get("building_year") is None and features.get("year_basis") == "unknown" or type(features.get("building_year")) is int and 1800 <= features["building_year"] <= now.year + 15 and features.get("year_basis") != "unknown")
                      and (features.get("floor_number") is None or type(features.get("floor_number")) is int and -5 <= features["floor_number"] <= 100)
                      and (features.get("total_floors") is None or type(features.get("total_floors")) is int and 1 <= features["total_floors"] <= 100)
                      and (features.get("total_floors") is None or features.get("floor_number") is None or features["floor_number"] <= features["total_floors"])
                      and features.get("elevator") in {"yes", "no", "unknown"}
                      and features.get("source") in {"card", "description"} and isinstance(features.get("checked_at"), str))
    valid_agency = (agency is None or isinstance(agency, dict) and set(agency) == AGENCY_FIELDS
                    and entry.get("seller_type") == "agency" and agency.get("evidence") == "professional_profile"
                    and isinstance(agency.get("name"), str) and 1 <= len(agency["name"]) <= 120
                    and isinstance(agency.get("profile_url"), str)
                    and professional_url(agency.get("profile_url")) == agency.get("profile_url")
                    and (agency.get("phone") is None or public_phone(agency["phone"]) == agency["phone"])
                    and (agency.get("website") is None or public_website(agency["website"]) == agency["website"])
                    and isinstance(agency.get("checked_at"), str))
    maximum_age = 2 * 86400 if entry.get("status") == "description_unavailable" else 30 * 86400
    return (0 <= age <= maximum_age and entry.get("status") in {"analyzed", "description_unavailable"} and valid_features and valid_agency
            and isinstance(entry.get("seller_checked_at"), str)
            and (entry.get("description_sha256") is None or isinstance(entry["description_sha256"], str) and re.fullmatch(r"[a-f0-9]{64}", entry["description_sha256"]))
            and isinstance(analysis, dict) and analysis.get("completion_stage") in {"planned", "completed", "unknown"}
            and analysis.get("condition") in {"renovated", "needs_renovation", "unknown"}
            and analysis.get("area_basis") in {"net", "gross", "terrace_included", "unknown"}
            and isinstance(analysis.get("description_analyzed"), bool)
            and isinstance(analysis.get("checked_at"), str)
            and isinstance(analysis.get("risk_flags"), list) and len(analysis["risk_flags"]) <= 5 and all(isinstance(flag, str) and flag in RISK_FLAGS for flag in analysis["risk_flags"])
            and isinstance(hints, list) and len(hints) <= 3
            and all(isinstance(h, dict) and h.get("kind") == "street" and isinstance(h.get("name"), str) and 1 <= len(h["name"]) <= 80 and isinstance(h.get("nearby"), bool) and h.get("source") in {"card", "description"} and (h.get("house_number") is None or isinstance(h.get("house_number"), str) and len(h["house_number"]) <= 20) for h in hints)
            and len(json.dumps(entry)) <= 6000)


def enrich_capture(capture, previous_state=None, *, limit=400, maximum_seconds=900, config=None):
    """Return (capture, minimal private cache, coverage report), never raw text."""
    if not isinstance(capture, dict) or capture.get("version") != 1 or not isinstance(capture.get("listings"), list) or not 1 <= len(capture["listings"]) <= MAX_LISTINGS or capture.get("capture", {}).get("complete") is not True:
        raise ValueError("Enrichment requires a bounded, completed listing capture")
    if type(limit) is not int or not 0 <= limit <= 1200 or type(maximum_seconds) is not int or not 1 <= maximum_seconds <= 3600:
        raise ValueError("Optional detail enrichment exceeds its request/runtime limit")
    enriched = deepcopy(capture)
    previous_state = previous_state or {}
    prior = previous_state.get("enrichment_cache", {})
    prior_listings = previous_state.get("listings", {})
    if not isinstance(prior, dict) or len(prior) > MAX_LISTINGS or not isinstance(prior_listings, dict):
        raise ValueError("Invalid previous minimal enrichment cache")
    cache, pending = {}, []
    now = datetime.now(timezone.utc)
    report = {"version": 1, "started_at": timestamp(), "limit": limit, "attempted": 0, "analyzed": 0,
              "reused": 0, "unavailable": 0, "failed": 0, "stopped_reason": None,
              "description_storage": "derived_claims_only", "maximum_cache_age_days": 30}
    for row in enriched["listings"]:
        if row.get("analysis_method_version") not in {2, ANALYSIS_METHOD_VERSION}:
            # A recovered old capture has no discarded text to re-evaluate.
            # Keep its other claims, but never upgrade the old area inference.
            row["analysis_method_version"] = 1
            if isinstance(row.get("analysis"), dict):
                row["analysis"]["area_basis"] = "unknown"
        # Legacy captures contain no discarded description, but their retained
        # structural labels can still produce explicit year/floor facts.
        if not isinstance(row.get("property_features"), dict):
            row["property_features"] = property_features("", completion_label=row.get("construction_label_bg"), floor_label=row.get("floor_bg"), checked_at=row.get("observed_at"))
        if row.get("seller_type") != "agency" or not isinstance(row.get("agency"), dict):
            row["agency"] = None
        identifier = row.get("id")
        fingerprint = row.get("enrichment_card_sha256")
        if not isinstance(identifier, str) or not re.fullmatch(r"1[a-z][0-9]{12,20}", identifier) or not isinstance(fingerprint, str) or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            # Old captures have no text fingerprint. They retain structural facts
            # but cannot safely borrow enrichment or initiate unseen detail URLs.
            continue
        entry = prior.get(identifier)
        entry = entry if isinstance(entry, dict) else None
        if _valid_cache(entry, fingerprint, now):
            cache[identifier] = {field: deepcopy(entry.get(field)) for field in CACHE_FIELDS}
            row.update({field: deepcopy(entry[field]) for field in CLAIM_FIELDS})
            report["reused"] += 1
        else:
            old = prior_listings.get(identifier, {})
            priority = 0 if not old else 1 if entry and entry.get("card_sha256") != fingerprint else 2 if old.get("eligible") else 3
            pending.append((priority, (entry or {}).get("checked_at", ""), identifier, row))
    pending.sort(key=lambda item: item[:3])
    if limit and pending:
        # Reuse the exact source allowlist, pacing, TLS and robots behavior.
        from imot_scraper import AccessRestricted, Reader
        config = dict(config or json.loads(Path(__file__).with_name("imot_sources.json").read_bytes()))
        config["maximum_runtime_minutes"] = min(config.get("maximum_runtime_minutes", 150), maximum_seconds / 60)
        config["maximum_requests"] = min(config.get("maximum_requests", 4000), limit + 4)
        config["minimum_request_interval_seconds"] = max(2, config.get("minimum_request_interval_seconds", 2))
        reader = Reader(config)
        start = time.monotonic()
        try:
            reader.check_robots()
        except Exception as error:
            report["stopped_reason"] = "access_restricted" if isinstance(error, AccessRestricted) else "source_unavailable"
        else:
            for _, _, identifier, row in pending[:limit]:
                # Reader can spend three bounded network attempts plus backoff
                # on one page. Reserve that tail before starting the next one.
                if time.monotonic() - start >= max(0, maximum_seconds - 180):
                    report["stopped_reason"] = "runtime_budget"
                    break
                if reader.requests >= config["maximum_requests"]:
                    report["stopped_reason"] = "request_budget"
                    break
                report["attempted"] += 1
                checked = timestamp()
                try:
                    soup, effective_url = reader.get(row["url"])
                    # Confirm this is the observed property page, not a listing
                    # redirect, by its canonical URL before reading claims.
                    if not urlparse(effective_url).path.startswith("/obiava-" + identifier + "-"):
                        raise ValueError("Detail response identity differs")
                    canonical = soup.select_one('link[rel="canonical"][href]')
                    if canonical and not urlparse(urljoin("https://www.imot.bg", canonical["href"])).path.startswith("/obiava-" + identifier + "-"):
                        raise ValueError("Detail canonical identity differs")
                    description = detail_description(soup)
                    status = "analyzed" if description else "description_unavailable"
                    claims = analyze_text(description, source="description", checked_at=checked, completion_label=row.get("construction_label_bg"), area_sqm=row.get("area_sqm")) if description else {key: deepcopy(row.get(key)) for key in ("analysis", "location_hints", "analysis_method_version")}
                    if description and not claims["location_hints"]:
                        claims["location_hints"] = deepcopy(row.get("location_hints", []))
                    profile = agency_profile(soup, detail=True) or row.get("seller_evidence") == "agency_profile"
                    seller = seller_claim(profile, description, checked)
                    if seller["seller_evidence"] == "not_reported" and row.get("seller_evidence") in {"explicit_private_claim", "conflicting_signals"}:
                        seller = {key: row[key] for key in ("seller_type", "seller_evidence", "seller_checked_at")}
                    elif profile and row.get("seller_evidence") in {"explicit_private_claim", "conflicting_signals"}:
                        seller = {"seller_type": "unknown", "seller_evidence": "conflicting_signals", "seller_checked_at": checked}
                    agency = merge_agency(row.get("agency"), agency_details(soup, detail=True, checked_at=checked, known_agency=row.get("agency")))
                    if seller["seller_type"] != "agency":
                        agency = None
                    fact_text = detail_property_facts(soup)
                    feature_text = " ; ".join(part for part in (fact_text, description) if part)
                    features = property_features(feature_text, source="description", checked_at=checked, completion_label=row.get("construction_label_bg"), floor_label=row.get("floor_bg")) if feature_text else row["property_features"]
                    claims["property_features"] = merge_features(row["property_features"], features)
                    claims["agency"] = agency
                    row.update(claims)
                    row.update(seller)
                    entry = {"version": CACHE_VERSION, "card_sha256": row["enrichment_card_sha256"], "checked_at": checked, "status": status,
                             "description_sha256": hashlib.sha256(description.encode()).hexdigest() if description else None,
                             **{field: deepcopy(row[field]) for field in CLAIM_FIELDS}}
                    cache[identifier] = entry
                    report["analyzed" if description else "unavailable"] += 1
                    # The source text exists only in this iteration's memory.
                    description = None
                    feature_text = fact_text = None
                except AccessRestricted:
                    report["stopped_reason"] = "access_restricted"
                    break
                except Exception:
                    report["failed"] += 1
                    # Never display stale claims after the observed card changed.
                    continue
    report.update({"finished_at": timestamp(), "listing_count": len(enriched["listings"]),
                   "description_analyzed_count": sum(row.get("analysis", {}).get("description_analyzed") is True for row in enriched["listings"]),
                   "agency_named_count": sum(bool(row.get("agency")) for row in enriched["listings"]),
                   "professional_contact_count": sum(bool((row.get("agency") or {}).get("phone")) for row in enriched["listings"]),
                   "construction_type_known_count": sum(row["property_features"]["construction_type"] != "unknown" for row in enriched["listings"]),
                   "furnishing_known_count": sum(row["property_features"]["furnishing"] != "unknown" for row in enriched["listings"]),
                   "building_year_known_count": sum(row["property_features"]["building_year"] is not None for row in enriched["listings"]),
                   "elevator_known_count": sum(row["property_features"]["elevator"] != "unknown" for row in enriched["listings"]),
                   "pending_count": max(0, len(pending) - report["analyzed"] - report["unavailable"])})
    enriched["enrichment_cache"] = cache
    enriched["enrichment"] = report
    return enriched, cache, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--previous-state", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=400)
    parser.add_argument("--maximum-seconds", type=int, default=900)
    args = parser.parse_args()
    if args.input.is_symlink() or not 1 <= args.input.stat().st_size <= MAX_INPUT_BYTES:
        raise ValueError("Input capture exceeds its bounds")
    if args.output.exists():
        raise ValueError("Use a fresh enrichment output path")
    previous = None
    if args.previous_state and args.previous_state.exists():
        if args.previous_state.is_symlink() or args.previous_state.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("Previous state exceeds its bounds")
        previous = json.loads(args.previous_state.read_bytes())
    result, _, report = enrich_capture(json.loads(args.input.read_bytes()), previous, limit=args.limit, maximum_seconds=args.maximum_seconds)
    payload = (json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    if len(payload) > MAX_INPUT_BYTES:
        raise ValueError("Enriched capture exceeds its bounds")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".pending")
    temporary.write_bytes(payload)
    temporary.replace(args.output)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
