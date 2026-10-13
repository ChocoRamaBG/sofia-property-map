#!/usr/bin/env python3
"""Capture complete Sofia apartment searches from public imot.bg HTML.

This replaces dozens of desktop Selenium loops, absolute XPaths and Excel writes.
One worker reads forty public list cards per page; no photographs, full advert
descriptions, telephone numbers or private accounts are collected. Native public
price filters divide capped searches into exhaustive overlapping price bands.
Every leaf must have an exact, stable visible total and matching unique IDs.
Any access challenge, incomplete leaf or changed catalogue stops publication.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

ROOT = "https://www.imot.bg"
COUNT = re.compile(r"^(\d+)\s*-\s*(\d+)\s+от общо\s+(\d+)(\+?)\s+обяв[аи]\s*-\s*Продава$")
ID = re.compile(r"^1[a-z][0-9]{12,20}$")
NEIGHBOR_PATH = re.compile(r"^/obiavi/prodazhbi/grad-sofiya/([a-z0-9-]+)$")
PRICE = re.compile(r"^([0-9][0-9\s.,]*)\s*(€|EUR|euro|лв\.?|BGN|\$)(?:\s+(на кв\.м|/m2|/m²))?$", re.I)


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".pending")
    temporary.write_bytes(encoded(value))
    temporary.replace(path)


def text(node):
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def public_url(url):
    parsed = urlparse(urljoin(ROOT, url))
    if parsed.scheme != "https" or parsed.hostname != "www.imot.bg" or parsed.username or parsed.password:
        raise ValueError("Unexpected off-site or insecure source URL")
    if parsed.fragment:
        raise ValueError("Unexpected source URL fragment")
    return parsed.geturl()


class AccessRestricted(RuntimeError):
    pass


class CaptureChanged(ValueError):
    pass


class Reader:
    def __init__(self, config):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config["user_agent"], "Accept": "text/html,text/plain;q=0.9"})
        self.started = time.monotonic()
        self.last_request = 0.0
        self.requests = 0
        self.robots = None

    def get(self, url, soup=True):
        url = public_url(url)
        if self.robots is not None and not self.robots.can_fetch(self.config["user_agent"], url):
            raise AccessRestricted("Current robots.txt disallows the requested public page")
        for attempt in range(3):
            if time.monotonic() - self.started > self.config["maximum_runtime_minutes"] * 60:
                raise RuntimeError("Capture exceeded its runtime bound; active snapshot must remain unchanged")
            if self.requests >= self.config["maximum_requests"]:
                raise RuntimeError("Capture exceeded its request bound")
            wait = self.config["minimum_request_interval_seconds"] - (time.monotonic() - self.last_request)
            if wait > 0:
                time.sleep(wait)
            self.last_request = time.monotonic()
            self.requests += 1
            try:
                response = self.session.get(url, timeout=(10, 35), allow_redirects=True)
                public_url(response.url)
                if response.status_code in (401, 403, 429):
                    raise AccessRestricted(f"Source restricts access (HTTP {response.status_code}); no bypass attempted")
                if response.status_code >= 500:
                    raise requests.RequestException(f"Transient HTTP {response.status_code}")
                response.raise_for_status()
                if len(response.content) > 2 * 1024 * 1024:
                    raise ValueError("Source page exceeds the 2 MiB bound")
                # Check challenge title/body, not incidental challenge JS URLs.
                # The source's malformed table/inline markup makes Python's
                # html.parser hide complete listing cards. libxml's HTML
                # recovery retains all visible stable-ID cards and headings.
                parsed = BeautifulSoup(response.content, "lxml")
                title = text(parsed.title).lower()
                body = text(parsed.body or parsed).lower()
                if any(term in title for term in ("just a moment", "access denied", "captcha")) or (
                    len(body) < 4000 and any(term in body for term in (
                        "verify you are human", "unusual traffic", "потвърдете, че не сте робот", "access denied", "captcha"
                    ))
                ):
                    raise AccessRestricted("Source returned an access challenge; no bypass attempted")
                return (parsed if soup else response.content), response.url
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(5 * 2 ** attempt)
        raise RuntimeError("Source request did not finish")

    def check_robots(self):
        payload, _ = self.get(self.config["robots_url"], soup=False)
        robot = RobotFileParser()
        robot.parse(payload.decode("utf-8", errors="strict").splitlines())
        self.robots = robot
        delay = robot.crawl_delay(self.config["user_agent"]) or robot.crawl_delay("*")
        if delay:
            self.config["minimum_request_interval_seconds"] = max(self.config["minimum_request_interval_seconds"], delay)
        if not robot.can_fetch(self.config["user_agent"], self.config["catalogue_url"]):
            raise AccessRestricted("Current robots.txt disallows the catalogue")
        return hashlib.sha256(payload).hexdigest()


def catalogue(soup, config):
    neighbors = {}
    type_slugs = {entry["slug"] for entry in config["property_types"]}
    for link in soup.select("a[href]"):
        candidate = urlparse(urljoin(ROOT, link["href"]))
        parsed = candidate if candidate.scheme == "https" and candidate.hostname == "www.imot.bg" else None
        match = NEIGHBOR_PATH.fullmatch(parsed.path) if parsed else None
        label = text(link)
        if not match or match[1] in type_slugs or not label.startswith("Имоти "):
            continue
        name_match = re.fullmatch(r"Имоти\s+(.+?)\s+\((\d+)\)", label)
        if not name_match:
            continue
        key = match[1]
        item = {"key": key, "label_bg": name_match[1], "url": parsed._replace(query="", fragment="").geturl()}
        if key in neighbors and neighbors[key] != item:
            raise ValueError("Catalogue has conflicting neighborhood labels")
        neighbors[key] = item
    if not 60 <= len(neighbors) <= config["maximum_neighborhoods"] or "banishora" not in neighbors:
        raise ValueError("Unexpected or incomplete Sofia neighborhood catalogue")
    return sorted(neighbors.values(), key=lambda entry: entry["key"])


def number(value):
    value = re.sub(r"\s+", "", value).replace(",", ".")
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def cards(soup, neighbor, kind, minimum, maximum):
    output = []
    seen = set()
    for card in soup.select("div.item[id^=ida1]"):
        identifier = card.get("id", "")[3:]
        if not ID.fullmatch(identifier) or identifier in seen:
            raise CaptureChanged("Invalid or repeated listing ID within a result page")
        seen.add(identifier)
        title = card.select_one("a.title[href]")
        location = title.select_one("location") if title else None
        if not title or not location or text(location).lower() != ("град София, " + neighbor["label_bg"]).lower():
            raise ValueError("Result card does not match the requested Sofia neighborhood")
        title_text = text(title).split("град София", 1)[0].strip()
        if title_text != "Продава " + kind["label_bg"]:
            raise ValueError("Result card does not match the requested sale/apartment type")
        url = public_url(title["href"])
        if not urlparse(url).path.startswith("/obiava-" + identifier + "-"):
            raise ValueError("Listing URL and stable ID differ")
        price_text = text(card.select_one(".price > div"))
        matched = PRICE.fullmatch(price_text)
        requested_price = price_text == "Цена при запитване"
        if not requested_price and (not matched or matched[2].upper() not in ("€", "EUR", "EURO")):
            raise ValueError(f"Listing {identifier} has unsupported displayed price {price_text!r}")
        price = None if requested_price else number(matched[1])
        if not requested_price and price is None:
            raise ValueError("Source price could not be parsed")
        info = text(card.select_one(".text .info"))
        area_match = re.match(r"([\d\s.,]+)\s+кв\.м(?:,|\s|$)", info)
        area = number(area_match[1]) if area_match else None
        if area is not None and area > 100000:
            raise ValueError("Apartment area exceeds the supported bounds")
        if matched and matched[3]:
            if area is None:
                raise ValueError("Per-area price lacks a stated area for its total price")
            price *= area
        if price is not None and (price < minimum - .01 or maximum is not None and price > maximum + .01):
            raise ValueError("Source ignored an active price-band filter")
        vat_text = text(card.select_one(".price"))
        vat = "excluded" if "Цената е без ДДС" in vat_text else (
            "included" if "включено ДДС" in vat_text else (
                "not_applicable" if "Не се начислява ДДС" in vat_text else "unknown"
            )
        )
        # Only structural card fields are retained; the advert teaser and phone
        # after them are deliberately not copied into the prepared dataset.
        construction = re.search(r"((?:Ще бъде въведен|Въведен) в експлоатация(?:\s+\d{4}(?:\s*-\s*\d{4})?\s*г\.)?)", info)
        construction_label = construction[1] if construction else None
        year_match = re.search(r"\b(\d{4})(?:\s*-\s*(\d{4}))?\s*г\.", construction_label or "")
        year = int(year_match[1]) if year_match and not year_match[2] else None
        floor = re.search(r"(?:^|,\s*)((?:\d+-\S+\s+ет\.|Партер|Сутерен)(?:\s+от\s+\d+)?)", info)
        address = re.match(r"[\d\s.,]+\s+кв\.м,\s*((?:ул\.|бул\.|пл\.|ж\.к\.|м-т)\s*[^,]{1,160}),", info)
        address_text = address[1].strip() if address else None
        if address_text and re.search(r"(?:@|тел\.?|телефон|gsm|\d{7,})", address_text, re.I):
            address_text = None
        agency = card.select_one(".agency a, .agencyName a, a.agency, .agency")
        if not agency:
            agency = next((link for link in card.select("a[href]") if urlparse(urljoin(ROOT, link["href"])).hostname not in ("www.imot.bg", "imot.bg", None) and urlparse(urljoin(ROOT, link["href"])).hostname.endswith(".imot.bg")), None)
        output.append({
            "id": identifier, "url": url, "neighborhood_bg": neighbor["label_bg"], "type_bg": kind["label_bg"],
            "price": round(price, 2) if price is not None else None, "price_currency": "EUR" if price is not None else None, "vat_basis": vat,
            "area_sqm": area, "construction_year": year, "construction_label_bg": construction_label,
            "floor_bg": floor[1] if floor else None, "address_bg": address_text, "agency_name": text(agency) or None,
            "observed_at": timestamp(), "last_modified_at": None,
        })
    return output


def page_info(soup, neighbor, kind, minimum, maximum):
    header = soup.select_one(".SearchInfoLine")
    status = text(header)
    if not header:
        raise ValueError("Source page lacks its visible results count")
    params = soup.select_one(".resultsInfoBox .params")
    if params:
        displayed = [re.sub(r"\s+", "", text(item)).casefold() for item in params.select("b")]
        expected = [kind["label_bg"], "град София", neighbor["label_bg"]]
        if minimum:
            expected.append(f"{minimum} EUR")
        if maximum is not None:
            expected.append(f"{maximum} EUR")
        if displayed != [re.sub(r"\s+", "", item).casefold() for item in expected]:
            raise ValueError("Visible result criteria do not match the requested scope/price band")
    else:
        # The desktop layout additionally carries its native criteria form;
        # responsive public pages show the same criteria as bold visible values.
        hidden = {item.get("name"): item.get("value", "") for item in soup.select("input[name]")}
        if hidden.get("f38") != "град София" or hidden.get("f40", "").casefold() != (neighbor["label_bg"] + "+").casefold() or hidden.get("f7") != kind["form_value"]:
            raise ValueError("Source result criteria do not match the requested scope")
        if hidden.get("f28", "") != (str(minimum) if minimum else "") or hidden.get("f29", "") != (str(maximum) if maximum is not None else ""):
            raise ValueError("Source did not retain the requested price criteria")
    if status == "Няма намерени обяви - Продава":
        if soup.select("div.item[id^=ida1]"):
            raise ValueError("Empty result status contains listing cards")
        return 0, 0, 0, False
    match = COUNT.fullmatch(status)
    if not match:
        raise ValueError(f"Unexpected visible result-count format: {status!r}")
    first, last, total = map(int, match.groups()[:3])
    if not 1 <= first <= last <= total or last - first + 1 > 40:
        raise ValueError("Invalid displayed page range")
    return first, last, total, bool(match[4])


def band_url(neighbor, kind, minimum, maximum):
    parameters = {"price_min": minimum} if minimum else {}
    if maximum is not None:
        parameters["price_max"] = maximum
    return neighbor["url"] + "/" + kind["slug"] + ("?" + urlencode(parameters) if parameters else "")


def leaf(reader, neighbor, kind, minimum, maximum, first_soup, first_url):
    start, end, total, capped = page_info(first_soup, neighbor, kind, minimum, maximum)
    if capped:
        raise ValueError("A capped search cannot be published as a complete leaf")
    pages = max(1, math.ceil(total / 40))
    if pages > reader.config["maximum_pages_per_search"]:
        raise ValueError("Exact source total exceeds the configured pagination limit")
    observed = {}
    evidence = []
    soup, url = first_soup, first_url
    for page in range(1, pages + 1):
        first, last, current, limited = page_info(soup, neighbor, kind, minimum, maximum)
        if current != total or limited or total and (first != (page - 1) * 40 + 1 or last != min(page * 40, total)):
            raise CaptureChanged("Source count/range changed during pagination")
        rows = cards(soup, neighbor, kind, minimum, maximum)
        if len(rows) != (last - first + 1 if total else 0):
            raise CaptureChanged("Visible result range and captured cards differ")
        for row in rows:
            if row["id"] in observed:
                raise CaptureChanged("Source repeated an earlier listing during pagination")
            observed[row["id"]] = row
        evidence.append({"url": url, "first": first, "last": last, "count": len(rows), "ids_sha256": hashlib.sha256(encoded([row["id"] for row in rows])).hexdigest()})
        next_links = {public_url(link["href"]) for link in soup.select("a[href]") if text(link) == "Напред"}
        if page < pages:
            if len(next_links) != 1:
                raise ValueError("Source lacks one unambiguous next-page link")
            next_url = next(iter(next_links))
            parsed = urlparse(next_url)
            expected_path = urlparse(neighbor["url"]).path + "/" + kind["slug"] + f"/p-{page + 1}"
            if parsed.path != expected_path or parse_qs(parsed.query) != parse_qs(urlparse(first_url).query):
                raise ValueError("Next-page link changes the requested criteria")
            soup, url = reader.get(next_url)
        elif next_links:
            raise CaptureChanged("Exact final page unexpectedly has a next-page link")
    if len(observed) != total:
        raise CaptureChanged("Complete leaf count differs from the source total")
    if pages > 1:
        recheck, _ = reader.get(first_url)
        if page_info(recheck, neighbor, kind, minimum, maximum) != (start, end, total, False) or [row["id"] for row in cards(recheck, neighbor, kind, minimum, maximum)] != [row["id"] for row in cards(first_soup, neighbor, kind, minimum, maximum)]:
            raise CaptureChanged("First page changed before the leaf completed")
    return list(observed.values()), {
        "key": f"{neighbor['key']}:{kind['slug']}:{minimum}:{maximum or 'any'}", "url": first_url,
        "neighborhood_bg": neighbor["label_bg"], "type_bg": kind["label_bg"],
        "price_min_eur": minimum, "price_max_eur": maximum, "expected_count": total,
        "captured_count": len(observed), "pages": evidence, "captured_at": timestamp(),
    }


def capture_band(reader, neighbor, kind, minimum, maximum, depth=0):
    if depth > 14:
        raise ValueError("Adaptive price partition limit reached")
    url = band_url(neighbor, kind, minimum, maximum)
    soup, effective_url = reader.get(url)
    first, last, total, capped = page_info(soup, neighbor, kind, minimum, maximum)
    if capped:
        midpoint = (minimum + maximum) // 2 if maximum is not None else max(minimum * 2, reader.config["initial_price_split_eur"])
        if midpoint <= minimum or maximum is not None and midpoint >= maximum:
            raise ValueError("Capped source cannot be divided into bounded price searches")
        # Inclusive adjacent bands overlap at the exact midpoint. Stable IDs
        # remove that boundary duplication without leaving fractional-price gaps.
        low_rows, low_sources = capture_band(reader, neighbor, kind, minimum, midpoint, depth + 1)
        high_rows, high_sources = capture_band(reader, neighbor, kind, midpoint, maximum, depth + 1)
        by_id = {}
        for row in low_rows + high_rows:
            if row["id"] in by_id and {key: value for key, value in row.items() if key != "observed_at"} != {key: value for key, value in by_id[row["id"]].items() if key != "observed_at"}:
                raise CaptureChanged("Listing changed across overlapping price bands")
            by_id[row["id"]] = row
        if len(by_id) <= total:
            raise CaptureChanged("Adaptive capture fails the capped parent's stated lower bound")
        return list(by_id.values()), low_sources + high_sources
    try:
        rows, evidence = leaf(reader, neighbor, kind, minimum, maximum, soup, effective_url)
    except CaptureChanged:
        time.sleep(5)
        fresh, fresh_url = reader.get(url)
        rows, evidence = leaf(reader, neighbor, kind, minimum, maximum, fresh, fresh_url)
    return rows, [evidence]


def run(args):
    config = json.loads(args.sources.read_text(encoding="utf-8"))
    if config.get("version") != 1 or config.get("minimum_price_eur") != 0:
        raise ValueError("Unsupported source configuration")
    if args.output.exists():
        raise ValueError("Use a fresh output file; existing captures are not replaced")
    reader = Reader(config)
    started = timestamp()
    robots_hash = reader.check_robots()
    catalog_page, _ = reader.get(config["catalogue_url"])
    neighbors = catalogue(catalog_page, config)
    all_rows, searches = {}, []
    for position, neighbor in enumerate(neighbors, 1):
        for kind in config["property_types"]:
            rows, leaves = capture_band(reader, neighbor, kind, 0, None)
            for row in rows:
                if row["id"] in all_rows:
                    raise CaptureChanged("A stable listing ID appears in two neighborhood/type searches")
                all_rows[row["id"]] = row
            if len(all_rows) > config["maximum_listings"]:
                raise ValueError("Capture exceeds its listing-count bound")
            searches.extend(leaves)
        print(f"Completed neighborhood {position}/{len(neighbors)}; {len(all_rows)} unique listings", flush=True)
    final_catalogue, _ = reader.get(config["catalogue_url"])
    if catalogue(final_catalogue, config) != neighbors:
        raise CaptureChanged("Sofia neighborhood catalogue changed during capture")
    result = {
        "version": 1,
        "capture": {"source": "imot.bg", "source_url": config["catalogue_url"], "started_at": started,
                    "finished_at": timestamp(), "complete": True, "expected_count": len(all_rows),
                    "captured_count": len(all_rows), "requested_neighborhood_count": len(neighbors),
                    "captured_neighborhood_count": len(neighbors), "scope_bg": config["scope_bg"],
                    "scope": {"city": "Sofia catalogue locations", "transaction": "sale", "types": [kind["label_bg"] for kind in config["property_types"]], "construction_year_min": None, "price_min_eur": None, "price_scope": "Includes price-on-request adverts; unknown prices excluded from financial comparisons"},
                    "robots_sha256": robots_hash, "request_count": reader.requests, "searches": searches,
                    "neighborhoods": neighbors},
        "listings": sorted(all_rows.values(), key=lambda row: row["id"]),
    }
    write_json(args.output, result)
    print(f"Complete public capture: {len(all_rows)} unique listings; {len(searches)} fully checked search leaves", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=Path(__file__).with_name("imot_sources.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args)
    except Exception as error:
        print(f"Capture stopped: {type(error).__name__}: {error}. Previously published market data remains active.", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
