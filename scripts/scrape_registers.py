#!/usr/bin/env python3
"""Capture complete, bounded register windows with the supplied Selenium approach.

A changed page, incomplete pagination, unknown total, or failed date filter is a
failure. Files are published only after every page matches the register's total.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from registry_sources import CORE_CODES, SOURCES


def sofia_now() -> datetime:
    return datetime.now(ZoneInfo("Europe/Sofia"))


def total_rows(driver) -> int:
    pager = driver.find_element(By.CSS_SELECTOR, ".k-pager-info").text.strip()
    match = re.search(r"(?:от|of)\s+([\d\s\u00a0.,]+)", pager, re.IGNORECASE)
    if match:
        return int(re.sub(r"\D", "", match.group(1)))
    if re.search(r"няма\s+(?:данни|записи)|no\s+(?:items|records|data)", pager, re.IGNORECASE):
        return 0
    raise RuntimeError(f"Cannot establish the register total from pager: {pager!r}")


def data_rows(driver):
    # The existing parsers use role=row. Restrict the capture to the grid body.
    grids = driver.find_elements(By.CSS_SELECTOR, ".k-grid tbody tr[role='row']")
    return [row for row in grids if row.find_elements(By.CSS_SELECTOR, "td") and not re.search(r"k-grouping-row|k-nodata|k-no-data", row.get_attribute("class") or "")]


def page_values(driver) -> list[list[str]]:
    return [[cell.text.strip() for cell in row.find_elements(By.CSS_SELECTOR, "td") if cell.is_displayed()] for row in data_rows(driver)]


def fingerprint(values: list[list[str]]) -> str:
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode("utf-8")).hexdigest()


def wait_idle(driver, wait):
    wait.until(lambda browser: not any(element.is_displayed() for element in browser.find_elements(By.CSS_SELECTOR, ".k-loading-mask")))


def read_source(driver, code: str, start_date: str, max_pages: int) -> dict:
    info = SOURCES[code]
    wait = WebDriverWait(driver, 35)
    driver.get(info["source_url"])
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".k-grid .k-pager-info")))
    wait_idle(driver, wait)

    # Consent is optional; all functional failures below are raised.
    consent_links = driver.find_elements(By.CSS_SELECTOR, ".cc-dismiss, .cc-btn.cc-allow, a[title='Приемам']")
    consent_links.extend(driver.find_elements(By.XPATH, '//a[normalize-space(.)="Съгласен съм"]'))
    for element in consent_links:
        if element.is_displayed():
            element.click()
            break

    original_rows = data_rows(driver)
    original_fingerprint = fingerprint(page_values(driver))
    original_total = total_rows(driver)
    form_selector = f'#{info["form_id"]}'
    date_selector = (By.CSS_SELECTOR, f'{form_selector} input[name="FromDate"]')
    if not driver.find_elements(*date_selector):
        date_selector = (By.XPATH, f'//*[@id="{info["form_id"]}"]/div/div[2]/span/span/input')
    date_field = wait.until(EC.visibility_of_element_located(date_selector))
    date_field.clear()
    date_field.send_keys(start_date)
    date_field.send_keys(Keys.TAB)
    search = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, f'{form_selector} input[type="submit"]')))
    search.click()

    def filter_applied(browser):
        try:
            stale = bool(original_rows) and not original_rows[0].is_enabled()
        except StaleElementReferenceException:
            stale = True
        return stale or total_rows(browser) != original_total or fingerprint(page_values(browser)) != original_fingerprint

    # Do not proceed on an unchanged unfiltered grid and call it a monthly capture.
    wait.until(filter_applied)
    wait_idle(driver, wait)
    date_field = wait.until(EC.presence_of_element_located(date_selector))
    if date_field.get_attribute("value") != start_date:
        raise RuntimeError("The register did not retain the requested start date")

    expected = total_rows(driver)
    headers = [" ".join(cell.text.split()) for cell in driver.find_elements(By.CSS_SELECTOR, ".k-grid thead tr:not(.k-filter-row) th") if cell.is_displayed()]
    normalized_headers = {header.casefold() for header in headers}
    if not {header.casefold() for header in info["required_headers"]}.issubset(normalized_headers):
        raise RuntimeError(f"Required register headings changed: {headers!r}")
    rows: list[list[str]] = []
    seen_pages = set()
    for page_number in range(1, max_pages + 1):
        wait_idle(driver, wait)
        current = page_values(driver)
        if expected == 0:
            if current:
                raise RuntimeError("Zero total conflicts with visible data rows")
            break
        if not current:
            raise RuntimeError(f"No rows on expected page {page_number}")
        page_hash = fingerprint(current)
        if page_hash in seen_pages:
            raise RuntimeError(f"Pagination repeated a captured page ({page_number})")
        seen_pages.add(page_hash)
        rows.extend(current)
        print(f"{code}: page {page_number}, {len(rows)}/{expected} rows", flush=True)
        if len(rows) == expected:
            break
        if len(rows) > expected:
            raise RuntimeError("Captured rows exceed the register total")
        next_links = driver.find_elements(By.CSS_SELECTOR, f'.k-grid [data-page="{page_number + 1}"]')
        enabled = [element for element in next_links if element.is_displayed() and element.get_attribute("aria-disabled") != "true" and not re.search(r"(?:k-state-disabled|k-disabled)", element.get_attribute("class") or "")]
        if not enabled:
            raise RuntimeError(f"Next page {page_number + 1} is absent before all rows were read")
        enabled[-1].click()
        wait.until(lambda browser: fingerprint(page_values(browser)) != page_hash)
    else:
        raise RuntimeError(f"Exceeded the {max_pages}-page safety limit")

    if len(rows) != expected:
        raise RuntimeError(f"Incomplete capture: {len(rows)} of {expected} rows")
    column_count = max((len(row) for row in rows), default=len(headers))
    if rows and any(len(row) != column_count for row in rows):
        raise RuntimeError("The column count changed within the register window")
    if len(headers) != column_count:
        raise RuntimeError("Register header count differs from the data column count")
    labels = [header or f"Поле {index + 1}" for index, header in enumerate(headers)]
    # Duplicate headers must not overwrite cell values in a dict.
    labels = [label if labels.count(label) == 1 else f"{label} ({index + 1})" for index, label in enumerate(labels)]
    return {
        "source_code": code,
        "source_url": info["source_url"],
        "snapshot_date": sofia_now().date().isoformat(),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "start_date": datetime.strptime(start_date, "%d.%m.%Y").date().isoformat(),
        "expected_rows": expected,
        "rows_seen": len(rows),
        "status": "complete",
        "records": [{label: value for label, value in zip(labels, row) if value} for row in rows],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=(*CORE_CODES, "all"), default="all")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "seed" / "monthly-capture")
    parser.add_argument("--start-date", default=os.environ.get("NAG_START_DATE") or (sofia_now() - timedelta(days=90)).strftime("%d.%m.%Y"))
    parser.add_argument("--max-pages", type=int, default=1000)
    args = parser.parse_args()
    datetime.strptime(args.start_date, "%d.%m.%Y")
    if args.max_pages < 1 or args.max_pages > 1000:
        parser.error("--max-pages must be between 1 and 1000")
    args.output.mkdir(parents=True, exist_ok=True)
    options = webdriver.ChromeOptions()
    if os.environ.get("NAG_HEADLESS", "1") != "0":
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1440,1000")
    options.add_argument("--disable-dev-shm-usage")
    if os.environ.get("CHROME_BINARY"):
        options.binary_location = os.environ["CHROME_BINARY"]
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    codes = CORE_CODES if args.source == "all" else (args.source,)
    captures = []
    try:
        for code in codes:
            captures.append(read_source(driver, code, args.start_date, args.max_pages))
    finally:
        driver.quit()
    for capture in captures:
        path = args.output / f"{capture['source_code']}.json"
        pending = path.with_suffix(".json.pending")
        pending.write_text(json.dumps(capture, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        pending.replace(path)
    print(f"Completed {len(captures)} source captures in {args.output}")


if __name__ == "__main__":
    try:
        main()
    except (TimeoutException, RuntimeError, ValueError) as error:
        print(f"Register capture failed: {error}", file=sys.stderr)
        sys.exit(1)
