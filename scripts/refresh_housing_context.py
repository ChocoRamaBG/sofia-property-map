#!/usr/bin/env python3
"""Refresh official NSI housing prices and Sofia-capital construction context.

The publisher's quarterly index, published percentage changes and residential
construction totals are retained without interpolation, forecasts or
substitution with advertised prices. A failed download/validation never
replaces an existing valid output.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import math
import os
import re
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from uuid import uuid4
from zipfile import ZipFile

import openpyxl


ORIGIN = "https://www.nsi.bg"
TABLES = {
    "index": ("/en/statistical-data/98/328", "HPI_2.4-en.xlsx"),
    "qoq_pct": ("/en/statistical-data/98/327", "HPI_2.5-en.xlsx"),
    "yoy_pct": ("/en/statistical-data/98/326", "HPI_2.6-en.xlsx"),
}
CONSTRUCTION_TABLES = {
    "permitted": ("/statistical-data/414/927", "Construction_1_2.xlsx", "ИЗДАДЕНИ РАЗРЕШИТЕЛНИ ЗА СТРОЕЖ НА НОВИ СГРАДИ ПО ОБЛАСТИ"),
    "started": ("/statistical-data/415/926", "Construction_1_3.xlsx", "ЗАПОЧНАТО СТРОИТЕЛСТВО НА НОВИ СГРАДИ ПО ОБЛАСТИ"),
}
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024
MAX_XML_BYTES = 12 * 1024 * 1024
MAX_OUTPUT_BYTES = 128 * 1024
SOURCE_NAME = "НСИ — индекси на цените на жилищата, гр. София"
MISSING = {"", "/", "..", ":", "-"}
ROMAN_QUARTERS = {"I": 1, "II": 2, "III": 3, "IV": 4}
QUARTER_NAMES = {"first": 1, "second": 2, "third": 3, "fourth": 4}


def checked_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != "www.nsi.bg" or parts.port not in (None, 443) or parts.username or parts.password:
        raise ValueError("Only the official NSI HTTPS origin is permitted")
    return url


class OfficialRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url: str) -> bytes:
    checked_url(url)
    opener = build_opener(OfficialRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    request = Request(url, headers={"User-Agent": "SofiaPermits-official-statistics/1.0"})
    with opener.open(request, timeout=45) as response:
        checked_url(response.url)
        payload = response.read(MAX_DOWNLOAD_BYTES + 1)
    if not payload or len(payload) > MAX_DOWNLOAD_BYTES:
        raise ValueError("NSI response is empty or exceeds its byte limit")
    return payload


def source_date(page: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    before_series = re.split(r"Time series|Динамични редове", text, maxsplit=1)[0]
    dates = re.findall(r"\b([0-3][0-9])\.([01][0-9])\.(20[0-9]{2})\b", before_series)
    if not dates:
        raise ValueError("NSI table publication date is missing")
    day, month, year = dates[-1]
    return datetime(int(year), int(month), int(day)).date().isoformat()


def cell_number(value, *, metric: str):
    if value is None or (isinstance(value, str) and value.strip() in MISSING):
        return None
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"Unexpected nonnumeric NSI {metric} cell")
    if (metric == "index" and not 0 < value <= 10000) or (metric != "index" and not -100 <= value <= 10000):
        raise ValueError(f"Out-of-range NSI {metric} cell")
    return value


def parse_table(payload: bytes, metric: str) -> tuple[dict, str | None, set[str]]:
    with ZipFile(io.BytesIO(payload)) as archive:
        if len(archive.infolist()) > 100 or sum(item.file_size for item in archive.infolist()) > MAX_XML_BYTES:
            raise ValueError("NSI workbook exceeds its extraction limits")
    book = openpyxl.load_workbook(io.BytesIO(payload), read_only=True, data_only=True, keep_links=False)
    try:
        if len(book.sheetnames) != 1:
            raise ValueError("Unexpected NSI workbook sheet layout")
        sheet = book.active
        if not 6 <= sheet.max_row <= 250 or not 7 <= sheet.max_column <= 256:
            raise ValueError("Unexpected NSI workbook dimensions")
        rows = list(sheet.values)
        title = str(rows[0][0] or "")
        if "HPI for the six cities" not in title:
            raise ValueError("Workbook is not the official six-city HPI table")
        base = None
        if metric == "index":
            match = re.search(r"(20[0-9]{2})\s*=\s*100", title)
            if not match:
                raise ValueError("NSI index reference base is missing")
            base = match.group(1)
        elif metric == "qoq_pct" and "previous quarter=100" not in title:
            raise ValueError("Unexpected NSI quarterly-change title")
        elif metric == "yoy_pct" and "corresponding quarter of the previous year=100" not in title:
            raise ValueError("Unexpected NSI yearly-change title")

        headers = [index for index, row in enumerate(rows) if tuple(str(v).strip() for v in row[:3]) == ("Cities", "Code", "Type of purchase")]
        if len(headers) != 1:
            raise ValueError("NSI city-table header is missing or ambiguous")
        header = headers[0]
        candidates = [row for row in rows[header + 2:] if tuple(str(v).strip() for v in row[:3]) == ("Sofia", "H.1.", "Total HPI")]
        if len(candidates) != 1:
            raise ValueError("Exactly one Sofia-city Total HPI row is required")
        values = candidates[0]
        periods = {}
        year = None
        seen_quarters = set()
        header_years = set()
        for column in range(3, sheet.max_column):
            year_text = str(rows[header][column] or "").strip()
            if year_text:
                match = re.fullmatch(r"(20[0-9]{2})(?:[0-9,\s]*)", year_text)
                if not match:
                    raise ValueError("Unexpected NSI year header")
                if year is not None and seen_quarters != {1, 2, 3, 4}:
                    raise ValueError("Incomplete NSI quarter header block")
                year = int(match.group(1))
                if year in header_years:
                    raise ValueError("Duplicate NSI year header")
                header_years.add(year)
                seen_quarters = set()
            quarter_text = str(rows[header + 1][column] or "").strip().replace("І", "I")
            quarter_text = re.sub(r"[0-9,\s]+", "", quarter_text)
            if not quarter_text and values[column] is None:
                continue
            if year is None or quarter_text not in ROMAN_QUARTERS:
                raise ValueError("Unexpected NSI quarter header")
            quarter = ROMAN_QUARTERS[quarter_text]
            if quarter in seen_quarters:
                raise ValueError("Duplicate NSI quarter header")
            seen_quarters.add(quarter)
            periods[f"{year}-Q{quarter}"] = cell_number(values[column], metric=metric)
        if seen_quarters != {1, 2, 3, 4}:
            raise ValueError("Incomplete final NSI quarter header block")
        if not periods or len(periods) > 200:
            raise ValueError("Unexpected NSI quarterly coverage")

        # NSI labels a current-year quarter as preliminary in its footnotes.
        # An unrecognized preliminary annotation stops instead of guessing.
        notes = [str(row[0] or "") for row in rows[header + 2:]]
        preliminary = set()
        for note in notes:
            if "preliminary data" not in note.lower():
                continue
            match = re.search(r"Preliminary data for the (first|second|third|fourth) quarter", note, re.I)
            if not match:
                raise ValueError("Unrecognized NSI provisional-period footnote")
            preliminary.add(f"{max(header_years)}-Q{QUARTER_NAMES[match.group(1).lower()]}")
        return periods, base, preliminary
    finally:
        book.close()


def normalized(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def construction_number(value):
    # NSI explicitly uses '-' for no occurrence, '..' for confidential data.
    # Empty/unpublished cells and suppressed cells must never become zero.
    if isinstance(value, str):
        if value.strip() == "-":
            return 0
        if value.strip() in {"", "..", ":", "/"}:
            return None
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or value > 1_000_000_000 or value != int(value):
        raise ValueError("Unexpected NSI residential construction total")
    return int(value)


def parse_construction_table(payload: bytes, kind: str) -> dict:
    with ZipFile(io.BytesIO(payload)) as archive:
        if len(archive.infolist()) > 100 or sum(item.file_size for item in archive.infolist()) > MAX_XML_BYTES:
            raise ValueError("NSI construction workbook exceeds its extraction limits")
    book = openpyxl.load_workbook(io.BytesIO(payload), read_only=True, data_only=True, keep_links=False)
    try:
        if not 1 <= len(book.sheetnames) <= 10:
            raise ValueError("Unexpected NSI construction workbook sheet count")
        sheet = book.worksheets[0]
        if not 9 <= sheet.max_row <= 200 or not 29 <= sheet.max_column <= 1_401 or (sheet.max_column - 1) % 7:
            raise ValueError("Unexpected NSI construction time-series dimensions")
        rows = list(sheet.values)
        if normalized(rows[1][0]) != normalized(CONSTRUCTION_TABLES[kind][2]) or normalized(rows[2][0]) != "области":
            raise ValueError("Unexpected NSI residential construction table title")
        candidates = [row for row in rows[7:] if normalized(row[0]) == "софия (столица)"]
        if len(candidates) != 1:
            raise ValueError("Exactly one Sofia-capital construction row is required")
        values = candidates[0]
        series = {}
        previous = None
        for column in range(1, sheet.max_column, 7):
            header = normalized(rows[2][column])
            match = re.fullmatch(r"(i{1,3}|iv)\s*-\s*(?:во|ро|то)\s+тримесечие\s+(20[0-9]{2})", header)
            if not match:
                raise ValueError("Unrecognized NSI construction quarter header")
            quarter = ROMAN_QUARTERS[match.group(1).upper()]
            year = int(match.group(2))
            ordinal = year * 4 + quarter - 1
            if previous is not None and ordinal != previous + 1:
                raise ValueError("NSI construction quarters are duplicated or discontinuous")
            previous = ordinal
            if any(rows[2][position] is not None for position in range(column + 1, column + 7)):
                raise ValueError("Unexpected NSI construction quarter block")
            if normalized(rows[3][column]) != "жилищни сгради" or normalized(rows[5][column]) != "брой" or normalized(rows[5][column + 1]) != "брой" or normalized(rows[6][column + 1]) != "жилища":
                raise ValueError("NSI residential count columns changed")
            area_unit = normalized(" ".join(str(rows[row][column + 2] or "") for row in (4, 5, 6)))
            if not re.fullmatch(r"разгъната застроена площ\s*-\s*кв\s*\.\s*м", area_unit):
                raise ValueError("NSI gross residential floor-area unit changed")
            item = dict(zip(("buildings", "dwellings", "floor_area_m2"), (construction_number(values[column + offset]) for offset in range(3))))
            if all(value is None for value in item.values()):
                raise ValueError("NSI construction header includes an unpublished quarter")
            series[f"{year}-Q{quarter}"] = item
        if not 4 <= len(series) <= 200:
            raise ValueError("Unexpected NSI residential construction coverage")
        return series
    finally:
        book.close()


def collect_construction() -> dict:
    tables = {}
    sources = []
    dates = set()
    for kind, (page_path, filename, _) in CONSTRUCTION_TABLES.items():
        page_url = ORIGIN + page_path
        page = download(page_url).decode("utf-8")
        file_path = f"sites/default/files/files/data/timeseries/{filename}"
        if not re.search(r"href=[\"']/?" + re.escape(file_path) + r"[\"']", page):
            raise ValueError("Expected official construction time-series link is absent")
        published_at = source_date(page)
        file_url = ORIGIN + "/" + file_path
        payload = download(file_url)
        source_hash = hashlib.sha256(payload).hexdigest()
        tables[kind] = {
            period: {**values, "source_published_at": published_at, "source_sha256": source_hash}
            for period, values in parse_construction_table(payload, kind).items()
        }
        sources.append({"kind": kind, "name": "НСИ — " + ("издадени разрешителни за строеж на нови сгради" if kind == "permitted" else "започнато строителство на нови сгради"), "url": file_url, "page_url": page_url, "published_at": published_at, "sha256": source_hash})
        dates.add(published_at)
    if len(dates) != 1 or tuple(tables["permitted"]) != tuple(tables["started"]):
        raise ValueError("Official permitted/started tables have inconsistent dates or quarters")
    periods = sorted(tables["permitted"])
    return {
        "status": "available",
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "published_at": dates.pop(),
        "geography": "София (столица)",
        "geography_key": "sofia_capital_province",
        "frequency": "quarterly",
        "coverage": {"from": periods[0], "through": periods[-1], "observations": len(periods), "building_type": "Жилищни сгради", "seasonally_adjusted": False},
        "sources": sources,
        "series": [{"period": period, **{kind: table[period] for kind, table in tables.items()}} for period in periods],
        "notes": [
            "Официални тримесечни данни на НСИ за жилищните сгради в област София (столица). Това е различен обхват от индекса на жилищните цени за град София и от свързаното кадастрално подмножество на общинските регистри.",
            "Брой сгради, брой жилища и разгъната застроена площ са различни показатели. Броят сгради не е брой документи. По-малко разрешени сгради може да съдържат повече жилища и по-голяма разгъната застроена площ.",
            "Разрешеното и започнатото строителство са отделни наблюдения за тримесечието. Те не проследяват еднакви индивидуални проекти и отношението между тях не е процент на реализация.",
            "НСИ публикува текущ динамичен ред с ограничен период. Вече извлечените валидирани по-стари тримесечия се запазват с датата и хеша на техния източник. По-новите публикации заменят припокриващите се периоди.",
            "Не се добавят непубликувани тримесечия. Празните и конфиденциалните стойности остават неизвестни. Знакът „-“ в оригиналните таблици означава, че няма случай, и се отчита като нула.",
            "Това са агрегирани сигнали за строителна активност, без разбивка по квартали. Те не доказват покупка на конкретен терен, финансово затруднение, завършване на жилища или посока на цените след 12 месеца.",
        ],
    }


def collect() -> dict:
    tables = {}
    source_files = []
    dates = set()
    base_year = None
    provisional = set()
    for metric, (page_path, name) in TABLES.items():
        page_url = ORIGIN + page_path
        page = download(page_url).decode("utf-8")
        # NSI currently publishes a root-relative path without its leading /.
        # Use only the exact allowlisted official workbook name/path.
        file_path = f"sites/default/files/files/data/timeseries/{name}"
        if not re.search(r"href=[\"']/?" + re.escape(file_path) + r"[\"']", page):
            raise ValueError("Expected official NSI time-series link is absent")
        published_at = source_date(page)
        file_url = ORIGIN + "/" + file_path
        payload = download(file_url)
        tables[metric], base, preliminary = parse_table(payload, metric)
        if base:
            base_year = int(base)
        provisional.update(preliminary)
        dates.add(published_at)
        source_files.append({"metric": metric, "url": file_url, "page_url": page_url, "sha256": hashlib.sha256(payload).hexdigest(), "published_at": published_at})
    if len(dates) != 1 or len({tuple(table.keys()) for table in tables.values()}) != 1:
        raise ValueError("NSI tables have inconsistent publication dates or quarter columns")
    if not base_year:
        raise ValueError("Missing NSI reference base")
    published_periods = [period for period, value in tables["index"].items() if value is not None]
    if len(published_periods) < 16:
        raise ValueError("Too little published Sofia-city HPI history")
    through = max(published_periods)
    periods = [period for period in tables["index"] if period <= through]
    series = [{"period": period, **{key: table[period] for key, table in tables.items()}, "provisional": period in provisional} for period in periods]
    # Changes are taken directly from NSI, not recomputed from rounded indices.
    # This reconciliation only guards shifted rows, columns and units.
    for position, item in enumerate(series):
        for metric, lag in (("qoq_pct", 1), ("yoy_pct", 4)):
            if position < lag or item["index"] is None or series[position - lag]["index"] is None or item[metric] is None:
                continue
            implied = (item["index"] / series[position - lag]["index"] - 1) * 100
            if abs(implied - item[metric]) > 0.12:
                raise ValueError("Published NSI rate does not reconcile with its index period")
    base_values = [item["index"] for item in series if item["period"].startswith(f"{base_year}-")]
    if len(base_values) != 4 or any(value is None for value in base_values) or abs(sum(base_values) / 4 - 100) > 0.03:
        raise ValueError("NSI index does not reconcile with its stated base year")
    return {
        "schema_version": 1,
        "status": "available",
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "base_label": f"{base_year} = 100",
        "source": {"name": SOURCE_NAME, "url": ORIGIN + TABLES["index"][0], "published_at": dates.pop(), "files": source_files},
        "coverage": {"geography": "гр. София", "geography_key": "sofia_city", "frequency": "quarterly", "from": periods[0], "through": through, "observations": len(series), "dwelling_type": "Всички жилища — нови и съществуващи", "unit": "index", "seasonally_adjusted": False},
        "series": series,
        "construction": collect_construction(),
        "notes": [
            "Официален индекс на цените по сделки с жилища, закупени от домакинства, за град София. Не е цена в евро/м² и не е оценка на конкретен имот.",
            "Тримесечни наблюдения. Месечни стойности не се изчисляват, липсващите стойности остават неизвестни. По-нови непубликувани тримесечия не се добавят.",
            "Процентните изменения са публикуваните от НСИ стойности. Историческите данни могат да се ревизират. Последното отбелязано предварително тримесечие е означено отделно.",
            "От началото на 2022 г. НСИ използва административни данни от Имотния регистър вместо извадково наблюдение. От 2024 г. се променя основата на годишните тегла. От 2026 г. серията е преизчислена при база 2025 = 100.",
            "Индексът не е сезонно изгладен. Данните са за целия град, без разбивка по квартали, и не доказват причинна връзка с броя разрешения за строеж.",
            "Промяна в броя разрешения сама по себе си не позволява прогноза за посоката на цените след 12 месеца. Нужни са съпоставими данни за започнати и завършени жилища, обем сделки, кредитиране и търсене.",
        ],
    }


def merge_construction_history(data: dict, previous: dict) -> None:
    old = previous.get("construction")
    if old is None:
        return
    new = data["construction"]
    if not isinstance(old, dict) or old.get("status") != "available" or not isinstance(old.get("series"), list) or not 4 <= len(old["series"]) <= 200:
        raise ValueError("Previous construction context is invalid")
    if old.get("geography_key") != new["geography_key"]:
        raise ValueError("Previous construction geography changed")
    if str(old.get("coverage", {}).get("through", "")) > new["coverage"]["through"]:
        raise ValueError("NSI response would shorten the published construction history")
    combined = {}
    for row in old["series"]:
        if not isinstance(row, dict) or re.fullmatch(r"20[0-9]{2}-Q[1-4]", str(row.get("period", ""))) is None or row["period"] in combined:
            raise ValueError("Previous construction periods are invalid")
        for kind in CONSTRUCTION_TABLES:
            item = row.get(kind)
            if not isinstance(item, dict) or not all(field in item for field in ("buildings", "dwellings", "floor_area_m2")):
                raise ValueError("Previous construction values are incomplete")
            for field in ("buildings", "dwellings", "floor_area_m2"):
                construction_number(item[field])
            if re.fullmatch(r"[0-9a-f]{64}", str(item.get("source_sha256", ""))) is None:
                raise ValueError("Previous construction provenance is missing")
            datetime.strptime(str(item.get("source_published_at", "")), "%Y-%m-%d")
        combined[row["period"]] = row
    old_periods = sorted(combined)
    if old.get("coverage", {}).get("from") != old_periods[0] or old.get("coverage", {}).get("through") != old_periods[-1] or old.get("coverage", {}).get("observations") != len(old_periods):
        raise ValueError("Previous construction coverage does not match its periods")
    combined.update({row["period"]: row for row in new["series"]})
    if len(combined) > 200:
        raise ValueError("Accumulated construction history exceeds its period limit")
    periods = sorted(combined)
    ordinals = [int(period[:4]) * 4 + int(period[-1]) - 1 for period in periods]
    if any(current != previous + 1 for previous, current in zip(ordinals, ordinals[1:])):
        raise ValueError("Accumulated construction history contains a gap; fetch the latest previous context first")
    new["series"] = [combined[period] for period in periods]
    new["coverage"].update({"from": new["series"][0]["period"], "observations": len(combined)})


def publish_local(output: Path, data: dict) -> None:
    if output.is_symlink():
        raise ValueError("Output cannot be a symbolic link")
    if output.exists():
        if output.stat().st_size > MAX_OUTPUT_BYTES:
            raise ValueError("Existing context exceeds its byte limit")
        previous = json.loads(output.read_text(encoding="utf-8"))
        if previous.get("status") == "available" and previous.get("coverage", {}).get("through", "") > data["coverage"]["through"]:
            raise ValueError("NSI response would shorten the published quarterly history")
        merge_construction_history(data, previous)
    payload = (json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
    if len(payload) > MAX_OUTPUT_BYTES:
        raise ValueError("Derived public context exceeds its byte limit")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + "." + uuid4().hex + ".pending")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("public/data/housing-context.json"))
    args = parser.parse_args()
    try:
        context = collect()
        publish_local(args.output, context)
    except Exception as error:
        print(f"NSI housing context was not replaced: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    coverage = context["coverage"]
    print(f"Published official NSI Sofia-city HPI: {coverage['observations']} quarters, {coverage['from']}–{coverage['through']}; source {context['source']['published_at']}")
    construction = context["construction"]
    print(f"Published official NSI Sofia-capital residential construction: {construction['coverage']['observations']} quarters, {construction['coverage']['from']}–{construction['coverage']['through']}; source {construction['published_at']}")


if __name__ == "__main__":
    main()
