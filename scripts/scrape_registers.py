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
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from registry_sources import CORE_CODES, SOURCES

CURRENT_SOURCE = "initialization"
CURRENT_PHASE = "starting"

# Install before the municipal page's scripts run. Its initial zero-row grid is
# only a placeholder, and Search replaces it before issuing a separate /Read.
# Observe native request completion and the documented Kendo dataBound event;
# identical first rows are not evidence that a request finished.
CAPTURE_MONITOR_SCRIPT = r"""
(() => {
    if (window.__sofiaCapture) return;
    const monitor = window.__sofiaCapture = {
        sequence: 0, requestSequence: 0, gridSequence: 0,
        requests: [], grids: new WeakMap()
    };
    const tick = () => ++monitor.sequence;
    monitor.attach = () => {
        const element = document.querySelector('.k-grid');
        const widget = element && window.jQuery && window.jQuery(element).data('kendoGrid');
        if (!widget || !widget.dataSource) return null;
        let record = monitor.grids.get(element);
        if (!record || record.widget !== widget) {
            record = {token: ++monitor.gridSequence, widget, bound: 0, boundEvent: 0, error: null};
            monitor.grids.set(element, record);
            widget.bind('dataBound', () => {
                record.bound += 1;
                record.boundEvent = tick();
            });
            widget.dataSource.bind('error', () => { record.error = 'Kendo data source error'; });
        }
        return record;
    };
    const nativeOpen = XMLHttpRequest.prototype.open;
    const nativeSend = XMLHttpRequest.prototype.send;
    const requestUrls = new WeakMap();
    XMLHttpRequest.prototype.open = function(method, url) {
        requestUrls.set(this, {method: String(method), url: String(url)});
        return nativeOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function(body) {
        const details = requestUrls.get(this);
        if (details) {
            const url = new URL(details.url, location.href);
            const bodyParams = typeof body === 'string' ? new URLSearchParams(body) : null;
            const parameter = name => url.searchParams.get(name) || (bodyParams && bodyParams.get(name));
            const request = {
                id: ++monitor.requestSequence, startEvent: tick(),
                method: details.method, path: url.pathname, sameOrigin: url.origin === location.origin,
                fromDate: parameter('FromDate'), searchQueryId: parameter('searchQueryId'),
                complete: false, status: null
            };
            monitor.requests.push(request);
            if (monitor.requests.length > 256) monitor.requests.shift();
            this.addEventListener('loadend', () => {
                request.complete = true;
                request.status = this.status;
                request.endEvent = tick();
            }, {once: true});
            monitor.attach();
        }
        return nativeSend.apply(this, arguments);
    };
    new MutationObserver(() => monitor.attach()).observe(document, {childList: true, subtree: true});
    document.addEventListener('DOMContentLoaded', () => monitor.attach(), {once: true});
})();
"""


def phase(source_code: str, message: str) -> None:
    global CURRENT_SOURCE, CURRENT_PHASE
    CURRENT_SOURCE, CURRENT_PHASE = source_code, message
    print(f"[{source_code}] {message}", flush=True)


def state_summary(state: dict | None) -> dict:
    if not state:
        return {"grid_present": False}
    return {
        "grid_present": True,
        "pager": state["pager"][:300],
        "selected_page": state["selected_page"],
        "page_size": state["page_size"],
        "page_size_options": state["page_sizes"][:20],
        "headers": [header[:100] for header in state["headers"][:30]],
        "row_count": len(state["rows"]),
        "loading": state["loading"],
        "grid_token": state.get("grid_token"),
        "data_bound_count": state.get("data_bound_count"),
        "model_total": state.get("model_total"),
        "read_path": state.get("read_path"),
        "recent_requests": [
            {key: request.get(key) for key in ("id", "method", "path", "fromDate", "complete", "status")}
            for request in state.get("requests", [])[-5:]
        ],
    }


def save_failure_diagnostics(driver, directory: Path) -> None:
    """Keep bounded diagnostics from the public register, without row logs."""
    directory.mkdir(parents=True, exist_ok=True)
    prefix = f"{CURRENT_SOURCE}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    details = {"source": CURRENT_SOURCE, "phase": CURRENT_PHASE}
    try:
        details["url"] = driver.current_url
        details["grid"] = state_summary(grid_state(driver))
    except Exception as error:
        details["grid_read_error"] = type(error).__name__
    print("Failure diagnostics: " + json.dumps(details, ensure_ascii=False), file=sys.stderr, flush=True)
    (directory / f"{prefix}.json").write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")
    # This browser visits only the public municipal register. Limit the HTML
    # retained in the private Actions artifact to 256 KiB.
    try:
        source = driver.page_source.encode("utf-8")[:256 * 1024].decode("utf-8", errors="ignore")
        (directory / f"{prefix}.html").write_text(source, encoding="utf-8")
    except Exception as error:
        print(f"Could not save bounded register HTML: {type(error).__name__}", file=sys.stderr, flush=True)
    try:
        driver.save_screenshot(str(directory / f"{prefix}.png"))
    except Exception as error:
        print(f"Could not save register screenshot: {type(error).__name__}", file=sys.stderr, flush=True)


def sofia_now() -> datetime:
    return datetime.now(ZoneInfo("Europe/Sofia"))


def grid_state(driver) -> dict | None:
    """Read one coherent DOM render without holding stale WebElements."""
    return driver.execute_script("""
        const grid = document.querySelector('.k-grid');
        if (!grid) return null;
        const visible = element => {
            const style = getComputedStyle(element);
            return style.display !== 'none' && style.visibility !== 'hidden'
                && style.visibility !== 'collapse' && element.getClientRects().length > 0;
        };
        const pager = Array.from(grid.querySelectorAll('.k-pager-info')).find(visible);
        const selected = grid.querySelector('.k-pager-numbers .k-state-selected, .k-pager-numbers .k-selected, .k-pager-numbers [aria-current="page"]');
        const pageText = selected ? selected.innerText.trim() : '';
        const sizeSelect = grid.querySelector('.k-pager-sizes select');
        const monitor = window.__sofiaCapture;
        const record = monitor && monitor.attach();
        const widget = record && record.widget;
        const source = widget && widget.dataSource;
        const transportRead = source && source.options.transport && source.options.transport.read;
        const readUrl = typeof transportRead === 'string' ? transportRead : transportRead && transportRead.url;
        return {
            loading: Array.from(document.querySelectorAll('.k-loading-mask')).some(visible),
            pager: pager ? pager.innerText.trim() : '',
            selected_page: /^\\d+$/.test(pageText) ? Number(pageText) : null,
            headers: Array.from(grid.querySelectorAll('thead tr:not(.k-filter-row) th'))
                .filter(visible).map(cell => cell.innerText.trim().replace(/\\s+/g, ' ')),
            rows: Array.from(grid.querySelectorAll('tbody tr[role="row"]'))
                .filter(row => visible(row) && !/k-grouping-row|k-nodata|k-no-data/.test(row.className))
                .map(row => Array.from(row.querySelectorAll('td')).filter(visible).map(cell => cell.innerText.trim()))
                .filter(cells => cells.length > 0),
            page_size: sizeSelect ? sizeSelect.value : null,
            page_sizes: sizeSelect ? Array.from(sizeSelect.options).map(option => option.value) : [],
            grid_token: record ? record.token : null,
            data_bound_count: record ? record.bound : 0,
            bound_event: record ? record.boundEvent : 0,
            source_error: record ? record.error : null,
            model_total: source ? source.total() : null,
            model_page: source ? source.page() : null,
            model_page_size: source ? source.pageSize() : null,
            model_rows: source ? source.view().length : null,
            read_path: typeof readUrl === 'string' ? new URL(readUrl, location.href).pathname : null,
            request_sequence: monitor ? monitor.requestSequence : null,
            requests: monitor ? monitor.requests : []
        };
    """)


def total_rows(driver, state: dict | None = None) -> int:
    state = state if state is not None else grid_state(driver)
    pager = state["pager"] if state else ""
    match = re.search(r"(?:от|of)\s+([\d\s\u00a0.,]+)", pager, re.IGNORECASE)
    if match:
        return int(re.sub(r"\D", "", match.group(1)))
    if re.search(r"няма\s+(?:данни|записи)|no\s+(?:items|records|data)", pager, re.IGNORECASE):
        return 0
    raise RuntimeError(f"Cannot establish the register total from pager: {pager!r}")


def page_values(driver) -> list[list[str]]:
    state = grid_state(driver)
    return state["rows"] if state else []


def fingerprint(values: list[list[str]]) -> str:
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode("utf-8")).hexdigest()


def wait_idle(driver, wait, page_number: int | None = None) -> dict:
    def rendered(browser):
        state = grid_state(browser)
        if not state or not completed_read(state):
            return False
        return ready_state(browser, state, page_number)

    return wait.until(rendered)


def request_marker(state: dict) -> dict:
    if state.get("request_sequence") is None or state.get("grid_token") is None:
        raise RuntimeError("The request/dataBound observer was not installed")
    return {"request_id": state["request_sequence"], "grid_token": state["grid_token"], "bound_event": state["bound_event"]}


def completed_read(state: dict, after_request: int = 0, after_bound: int = 0) -> bool:
    """Require a successful grid read and its subsequent data binding."""
    if not state.get("read_path"):
        return False
    reads = [request for request in state["requests"] if request["sameOrigin"] and request["path"] == state["read_path"] and request["id"] > after_request]
    if not reads or any(not request["complete"] for request in reads):
        return False
    request = reads[-1]
    if not 200 <= request["status"] < 300:
        raise RuntimeError(f"The register read failed with HTTP {request['status']}")
    return state["bound_event"] > max(after_bound, request["startEvent"])


def wait_read_render(driver, wait, marker: dict | None = None, page_number: int | None = None, page_size: str | None = None) -> dict:
    def rendered(browser):
        state = grid_state(browser)
        if not state or not completed_read(state, marker["request_id"] if marker else 0, marker["bound_event"] if marker else 0):
            return False
        if marker and state["grid_token"] != marker["grid_token"]:
            raise RuntimeError("The grid was unexpectedly replaced during a pager request")
        if page_size is not None and (state["page_size"] != page_size or state["model_page_size"] != int(page_size)):
            return False
        return ready_state(browser, state, page_number)

    return wait.until(rendered)


def ready_state(driver, state: dict, page_number: int | None = None) -> dict | bool:
    """Accept genuine empty results only after request completion is established."""
    if state.get("source_error"):
        raise RuntimeError(state["source_error"])
    if state["loading"] or not state["pager"] or not state["headers"]:
        return False
    expected = total_rows(driver, state)
    if state["model_total"] != expected or state["model_rows"] != len(state["rows"]):
        return False
    if expected and page_number is not None and (state["selected_page"] != page_number or state["model_page"] != page_number):
        return False
    return state


def wait_filter_render(driver, wait, marker: dict, form: dict, start_date: str) -> dict:
    def rendered(browser):
        state = grid_state(browser)
        if not state:
            return False
        searches = [request for request in state["requests"] if request["sameOrigin"] and request["id"] > marker["request_id"] and request["path"] == form["path"] and request["searchQueryId"] == form["search_query_id"]]
        if not searches or any(not request["complete"] for request in searches):
            return False
        search = searches[-1]
        if not 200 <= search["status"] < 300:
            raise RuntimeError(f"The date-filter request failed with HTTP {search['status']}")
        if search["fromDate"] != start_date:
            raise RuntimeError("The search request did not submit the requested start date")
        # The form's data-ajax-update replaces the result container. Its new
        # grid then performs another asynchronous /Read before results exist.
        if state["grid_token"] == marker["grid_token"] or not completed_read(state, search["id"]):
            return False
        return ready_state(browser, state, page_number=1)

    return wait.until(rendered)


def choose_largest_page_size(driver, wait):
    """Use only an existing numeric option in the register's pager select."""
    phase(CURRENT_SOURCE, "page size: waiting for a quiet first-page render")
    before = wait_idle(driver, wait, page_number=1)
    print("Page size before: " + json.dumps(state_summary(before), ensure_ascii=False), flush=True)
    choices = [(int(value), value) for value in before["page_sizes"] if value.isdigit() and int(value) > 0]
    if not choices:
        print("No existing numeric page-size option; retaining the current size", flush=True)
        return
    size, value = max(choices)
    if before["page_size"] == value:
        print(f"Largest existing page size {size} already selected", flush=True)
        return
    expected = total_rows(driver, before)
    marker = request_marker(before)
    # Resolve the current SELECT inside this one script: a grid rerender cannot
    # invalidate a saved WebElement between option inspection and selection.
    phase(CURRENT_SOURCE, f"page size: selecting existing option {value}")
    changed = driver.execute_script("""
        const value = arguments[0];
        const element = document.querySelector('.k-grid .k-pager-sizes select');
        if (!element || !Array.from(element.options).some(option => option.value === value)) return false;
        const widget = window.jQuery && window.jQuery(element).data('kendoDropDownList');
        if (widget) {
            widget.value(value);
            widget.trigger('change');
            return true;
        }
        if (!element.getClientRects().length) return false;
        element.value = value;
        element.dispatchEvent(new Event('change', {bubbles: true}));
        return true;
    """, value)
    if not changed:
        print("Existing page-size control has no usable widget; retaining the current size", flush=True)
        return
    phase(CURRENT_SOURCE, f"page size: waiting for option {value} to render rows")
    after = wait_read_render(driver, wait, marker=marker, page_number=1, page_size=value)
    print("Page size after: " + json.dumps(state_summary(after), ensure_ascii=False), flush=True)
    if total_rows(driver, after) != expected:
        raise RuntimeError("Register total changed while selecting page size")
    print(f"Using the register's existing {size}-row page-size option", flush=True)


def read_source(driver, code: str, start_date: str, max_pages: int) -> dict:
    info = SOURCES[code]
    wait = WebDriverWait(driver, 35)
    phase(code, "navigating to the official register")
    driver.get(info["source_url"])
    phase(code, "waiting for the initial grid pager")
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".k-grid .k-pager-info")))
    phase(code, "waiting for the initial grid to finish rendering")
    wait_read_render(driver, wait)

    # Consent is optional; all functional failures below are raised.
    consent_links = driver.find_elements(By.CSS_SELECTOR, ".cc-dismiss, .cc-btn.cc-allow, a[title='Приемам']")
    consent_links.extend(driver.find_elements(By.XPATH, '//a[normalize-space(.)="Съгласен съм"]'))
    for element in consent_links:
        if element.is_displayed():
            element.click()
            break

    phase(code, "reading the initial grid and locating the date filter")
    original_state = wait_idle(driver, wait)
    print("Initial grid: " + json.dumps(state_summary(original_state), ensure_ascii=False), flush=True)
    form_selector = f'#{info["form_id"]}'
    date_selector = (By.CSS_SELECTOR, f'{form_selector} input[name="FromDate"]')
    if not driver.find_elements(*date_selector):
        date_selector = (By.XPATH, f'//*[@id="{info["form_id"]}"]/div/div[2]/span/span/input')
    date_field = wait.until(EC.visibility_of_element_located(date_selector))
    phase(code, f"entering start date {start_date}")
    date_field.clear()
    date_field.send_keys(start_date)
    date_field.send_keys(Keys.TAB)
    search = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, f'{form_selector} input[type="submit"]')))
    form = driver.execute_script("""
        const form = document.querySelector(arguments[0]);
        if (!form || form.getAttribute('data-ajax') !== 'true' || !form.getAttribute('data-ajax-update')) return null;
        const action = new URL(form.action, location.href);
        return {path: action.pathname, search_query_id: action.searchParams.get('searchQueryId')};
    """, form_selector)
    if not form:
        raise RuntimeError("The register search form no longer uses the expected AJAX replacement")
    marker = request_marker(grid_state(driver))
    phase(code, f"submitting the date filter from {start_date}")
    search.click()
    phase(code, "waiting for Search completion and the new grid's Read/dataBound")
    filtered_state = wait_filter_render(driver, wait, marker, form, start_date)
    print("Filtered grid: " + json.dumps(state_summary(filtered_state), ensure_ascii=False), flush=True)
    wait_idle(driver, wait, page_number=1)
    date_field = wait.until(EC.presence_of_element_located(date_selector))
    if date_field.get_attribute("value") != start_date:
        raise RuntimeError("The register did not retain the requested start date")

    choose_largest_page_size(driver, wait)
    phase(code, "reading the filtered first page and its headings")
    first_state = wait_idle(driver, wait, page_number=1)
    expected = total_rows(driver, first_state)
    headers = first_state["headers"]
    normalized_headers = {header.casefold() for header in headers}
    if not {header.casefold() for header in info["required_headers"]}.issubset(normalized_headers):
        raise RuntimeError(f"Required register headings changed: {headers!r}")
    rows: list[list[str]] = []
    seen_pages = set()
    seen_rows = set()
    for page_number in range(1, max_pages + 1):
        phase(code, f"reading page {page_number}")
        state = wait_idle(driver, wait, page_number=page_number)
        if total_rows(driver, state) != expected:
            raise RuntimeError("Register total changed during pagination; repeat the window")
        current = state["rows"]
        if total_rows(driver, wait_idle(driver, wait, page_number=page_number)) != expected:
            raise RuntimeError("Register total changed while reading a page; repeat the window")
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
        for row in current:
            row_hash = fingerprint([row])
            if row_hash in seen_rows:
                raise RuntimeError(f"Pagination repeated an individual record on page {page_number}; inspect the register before publication")
            seen_rows.add(row_hash)
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
        marker = request_marker(state)
        enabled[-1].click()
        phase(code, f"waiting for page {page_number + 1} to finish rendering")
        wait_read_render(driver, wait, marker=marker, page_number=page_number + 1)
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
    parser.add_argument("--diagnostics", type=Path, help="Private output for failed public-register screenshots, bounded HTML, and grid metadata")
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
    phase("initialization", "starting Chrome")
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": CAPTURE_MONITOR_SCRIPT})
    codes = CORE_CODES if args.source == "all" else (args.source,)
    captures = []
    try:
        for code in codes:
            capture = read_source(driver, code, args.start_date, args.max_pages)
            # Keep only a source that fully completed, even if a later source
            # fails. The merge/publication still requires all three core files.
            path = args.output / f"{capture['source_code']}.json"
            pending = path.with_suffix(".json.pending")
            pending.write_text(json.dumps(capture, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            pending.replace(path)
            captures.append(capture)
    except Exception:
        save_failure_diagnostics(driver, args.diagnostics or args.output.parent / "diagnostics")
        raise
    finally:
        driver.quit()
    print(f"Completed {len(captures)} source captures in {args.output}")


if __name__ == "__main__":
    try:
        main()
    except (TimeoutException, RuntimeError, ValueError) as error:
        print(f"Register capture failed in {CURRENT_SOURCE}, phase '{CURRENT_PHASE}': {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        traceback.print_exc(limit=8)
        sys.exit(1)
