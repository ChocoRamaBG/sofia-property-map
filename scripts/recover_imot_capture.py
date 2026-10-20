#!/usr/bin/env python3
"""Recover a recently completed daily capture from this private repository.

Only same-repository daily-imot-refresh.yml runs are accepted, and only exact
capture.json is read from a bounded ZIP. No archive code or paths are executed
or extracted. The token is used only with api.github.com; artifact storage uses
a separate unauthenticated HTTPS request. Capture time is preserved.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from imot_market_format import MAX_CAPTURE_BYTES, MAX_LISTINGS, canonical_offer_id

REPOSITORY = "ChocoRamaBG/sofia-property-map"
API = "https://api.github.com/repos/" + REPOSITORY
WORKFLOW_PATH = ".github/workflows/daily-imot-refresh.yml"
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_AGE_SECONDS = 6 * 3600


def utc(value):
    if not isinstance(value, str):
        raise ValueError("Recovery evidence lacks a timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Recovery timestamp lacks a timezone")
    return parsed.astimezone(timezone.utc)


def client():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN with repository Actions read permission is required")
    current_repository = os.environ.get("GITHUB_REPOSITORY", REPOSITORY)
    if current_repository.casefold() != REPOSITORY.casefold():
        raise ValueError("Capture recovery is restricted to the configured private repository")
    session = requests.Session()
    session.headers.update({"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10"})
    return session


def get_json(session, path):
    response = session.get(API + path, timeout=(10, 30), allow_redirects=False)
    if response.status_code != 200:
        raise ValueError(f"Private GitHub API request failed with HTTP {response.status_code}")
    if len(response.content) > 2 * 1024 * 1024:
        raise ValueError("GitHub metadata exceeds its response bound")
    return response.json()


def capture_bytes(session, artifact):
    if type(artifact.get("size_in_bytes")) is not int or not 1 <= artifact["size_in_bytes"] <= MAX_ARCHIVE_BYTES:
        raise ValueError("Source artifact exceeds its archive byte bound")
    reply = session.get(f"{API}/actions/artifacts/{artifact['id']}/zip", timeout=(10, 30), allow_redirects=False)
    if reply.status_code != 302:
        raise ValueError(f"Artifact download did not provide a temporary redirect (HTTP {reply.status_code})")
    location = reply.headers.get("Location", "")
    parsed = urlparse(location)
    hostname = parsed.hostname or ""
    allowed_host = hostname.endswith(".blob.core.windows.net") or hostname.endswith(".blob.storage.azure.net") or hostname.endswith(".actions.githubusercontent.com") or hostname.endswith(".s3.amazonaws.com")
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment or not allowed_host:
        raise ValueError("Unexpected artifact storage redirect")
    archive = io.BytesIO()
    # Do not reuse the authenticated session with external artifact storage.
    with requests.get(location, timeout=(10, 60), stream=True, allow_redirects=False) as response:
        if response.status_code != 200:
            raise ValueError(f"Artifact storage request failed with HTTP {response.status_code}")
        length = response.headers.get("Content-Length", "")
        if length.isdigit() and int(length) > MAX_ARCHIVE_BYTES:
            raise ValueError("Artifact response exceeds its byte bound")
        for chunk in response.iter_content(64 * 1024):
            if archive.tell() + len(chunk) > MAX_ARCHIVE_BYTES:
                raise ValueError("Artifact stream exceeds its byte bound")
            archive.write(chunk)
    archive_payload = archive.getvalue()
    declared_digest = artifact.get("digest")
    if declared_digest is not None:
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", declared_digest) or declared_digest != "sha256:" + hashlib.sha256(archive_payload).hexdigest():
            raise ValueError("Downloaded artifact does not match its declared SHA-256 digest")
    archive.seek(0)
    with zipfile.ZipFile(archive) as zipped:
        names = [member.filename for member in zipped.infolist()]
        allowed_names = {"capture.json", "capture-progress.json", "capture-enriched.json"}
        if len(names) != len(set(names)) or set(names) - allowed_names or names.count("capture.json") != 1:
            raise ValueError("Artifact contains unexpected, duplicate or unsafe ZIP members")
        for candidate in zipped.infolist():
            if candidate.is_dir() or stat.S_ISLNK(candidate.external_attr >> 16) or candidate.flag_bits & 1 or not 1 <= candidate.file_size <= MAX_CAPTURE_BYTES:
                raise ValueError("Artifact member is linked, encrypted or oversized")
        # Optional derived enrichment is permitted as evidence but never reused:
        # recovery always runs the current enrichment pass on the source census.
        member = zipped.getinfo("capture.json")
        if member.is_dir() or stat.S_ISLNK(member.external_attr >> 16) or member.flag_bits & 1 or not 1 <= member.file_size <= MAX_CAPTURE_BYTES:
            raise ValueError("Exact capture.json member is linked, encrypted or oversized")
        with zipped.open(member) as stream:
            payload = stream.read(MAX_CAPTURE_BYTES + 1)
        if len(payload) != member.file_size or len(payload) > MAX_CAPTURE_BYTES:
            raise ValueError("Capture member exceeds its declared byte bound")
    return payload


def validate_capture(payload):
    capture = json.loads(payload)
    if not isinstance(capture, dict):
        raise ValueError("Recovered capture is not a JSON object")
    context, rows = capture.get("capture", {}), capture.get("listings")
    if not isinstance(context, dict):
        raise ValueError("Recovered capture lacks its capture evidence")
    count = context.get("captured_count")
    if capture.get("version") != 1 or context.get("source") != "imot.bg" or context.get("complete") is not True or type(count) is not int or not 1 <= count <= MAX_LISTINGS or context.get("expected_count") != count or not isinstance(rows, list) or len(rows) != count:
        raise ValueError("Recovered capture is incomplete or its global totals do not reconcile")
    finished, started = utc(context.get("finished_at")), utc(context.get("started_at"))
    age = (datetime.now(timezone.utc) - finished).total_seconds()
    if not 0 <= age <= MAX_AGE_SECONDS or started > finished or (finished - started).total_seconds() > 6 * 3600:
        raise ValueError("Recovered source capture is more than six hours old or has invalid capture times")
    scope = context.get("scope", {})
    if scope.get("transaction") != "sale" or scope.get("types") != ["2-СТАЕН", "3-СТАЕН", "4-СТАЕН"] or scope.get("construction_year_min") is not None:
        raise ValueError("Recovered capture has a different source scope")
    requested, covered = context.get("requested_neighborhood_count"), context.get("captured_neighborhood_count")
    neighborhoods = context.get("neighborhoods")
    if type(requested) is not int or not 60 <= requested <= 250 or covered != requested or not isinstance(neighborhoods, list) or len(neighborhoods) != requested:
        raise ValueError("Recovered capture does not cover every requested neighborhood")
    identifiers = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Recovered listing is malformed")
        identifier, _ = canonical_offer_id(row.get("url"), row.get("id"))
        if identifier in identifiers:
            raise ValueError("Recovered capture contains repeated source IDs")
        identifiers.add(identifier)
    sources = context.get("searches")
    if not isinstance(sources, list) or not sources:
        raise ValueError("Recovered capture lacks its completed search evidence")
    source_keys = set()
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("key"), str) or source["key"] in source_keys or type(source.get("expected_count")) is not int or source["expected_count"] != source.get("captured_count") or not 0 <= source["expected_count"] <= 1000:
            raise ValueError("Recovered search counts or identities do not reconcile")
        pages = source.get("pages")
        if not isinstance(pages, list) or not 1 <= len(pages) <= 25 or any(not isinstance(page, dict) or type(page.get("count")) is not int or not 0 <= page["count"] <= 40 for page in pages) or sum(page["count"] for page in pages) != source["expected_count"]:
            raise ValueError("Recovered search pagination does not reconcile")
        source_keys.add(source["key"])
    for neighborhood in neighborhoods:
        if not isinstance(neighborhood, dict) or not isinstance(neighborhood.get("key"), str):
            raise ValueError("Recovered neighborhood evidence is malformed")
        for kind in ("dvustaen", "tristaen", "chetiristaen"):
            if not any(key.startswith(neighborhood["key"] + ":" + kind + ":") for key in source_keys):
                raise ValueError("Recovered capture omits a requested apartment category")
    return context


def recover(args):
    if args.output.exists():
        raise ValueError("Recovery output exists; choose a fresh capture path")
    session = client()
    run = get_json(session, f"/actions/runs/{args.run}")
    run_path = run.get("path")
    if run.get("status") != "completed" or not isinstance(run_path, str) or run_path.split("@", 1)[0] != WORKFLOW_PATH or run.get("event") not in {"schedule", "workflow_dispatch"} or run.get("head_repository", {}).get("full_name", "").casefold() != REPOSITORY.casefold() or run.get("repository", {}).get("full_name", "").casefold() != REPOSITORY.casefold():
        raise ValueError("Recovery requires a finished same-repository daily market workflow")
    artifacts = get_json(session, f"/actions/runs/{args.run}/artifacts?per_page=100")
    expected_names = {f"imot-complete-capture-{args.run}", f"imot-source-evidence-{args.run}"}
    selected = [entry for entry in artifacts.get("artifacts", []) if entry.get("name") in expected_names and not entry.get("expired") and entry.get("workflow_run", {}).get("id") == args.run]
    if len(selected) != 1:
        raise ValueError("No unambiguous retained source capture exists for that daily run")
    artifact = selected[0]
    if artifact.get("workflow_run", {}).get("head_sha") != run.get("head_sha"):
        raise ValueError("Artifact and original workflow revision differ")
    payload = capture_bytes(session, artifact)
    context = validate_capture(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as output:
        output.write(payload)
    print(json.dumps({"reused_run_id": args.run, "artifact_id": artifact["id"], "capture_bytes": len(payload), "capture_sha256": hashlib.sha256(payload).hexdigest(), "listing_count": context["captured_count"], "captured_at": context["finished_at"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.run <= 10 ** 18:
        parser.error("--run must be a positive numeric workflow run ID")
    try:
        recover(args)
    except Exception as error:
        # Avoid printing signed storage URLs or request objects in error text.
        print(f"Capture recovery stopped: {type(error).__name__}", file=sys.stderr)
        if isinstance(error, ValueError) and not isinstance(error, requests.RequestException):
            print(str(error), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
