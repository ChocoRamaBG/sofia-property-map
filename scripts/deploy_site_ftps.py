#!/usr/bin/env python3
"""Publish only approved static site files over certificate-verified FTPS.

The PHP API, private data, schema, hosting configuration and unrelated build
files are never uploaded. Credentials are read from the process environment.
Existing assets are retained, and the entry HTML is replaced last.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import posixpath
import re
import ssl
from datetime import date, datetime, timedelta, timezone
from ftplib import FTP_TLS, error_perm
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from uuid import uuid4


REMOTE_ROOT = "/htdocs"
MAX_FILE_BYTES = 10_000_000
MAX_TOTAL_BYTES = 64 * 1024 * 1024
STATIC_NAMES = frozenset({"about.html", "privacy.html", "robots.txt", "sitemap.xml"})
REFERENCE_NAME = "data/market-georeference.json"
CONTEXT_NAME = "data/housing-context.json"
MAX_CONTEXT_BYTES = 128 * 1024
TRANSACTIONS_NAME = "data/transactions-context.json"
MAX_TRANSACTIONS_BYTES = 256 * 1024
DATA_NAMES = frozenset({REFERENCE_NAME, CONTEXT_NAME, TRANSACTIONS_NAME})
ASSET_EXTENSIONS = frozenset({
    ".js", ".mjs", ".css", ".svg", ".png", ".jpg", ".jpeg", ".gif",
    ".webp", ".avif", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".wasm",
})
SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
GOOGLE_VERIFICATION = re.compile(r"google[A-Za-z0-9]+\.html")
FORBIDDEN_ASSET_PARTS = frozenset({"php", "phtml", "phar", "env"})


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def validate_transactions(payload: bytes) -> dict:
    # PDF dependencies are lazy in the collector: ordinary static publication
    # still uses only the standard library and cannot scrape owner data.
    from refresh_transaction_context import validate_payload
    return validate_payload(payload)


def preserve_transactions(old: dict, incoming: dict) -> bool:
    if old['geography'] != incoming['geography'] or old['metric'] != incoming['metric'] or old['unit'] != incoming['unit']:
        raise ValueError('Transaction context scope changed')
    old_rows = {row['period']: row for row in old['series']}
    new_rows = {row['period']: row for row in incoming['series']}
    if incoming['retrieved_at'] < old['retrieved_at'] or max(new_rows) < max(old_rows):
        return True
    if not set(old_rows).issubset(new_rows):
        raise ValueError('Transaction context would truncate previously published quarters')
    for period, row in old_rows.items():
        earlier = row['source'].get('published_at')
        newer = new_rows[period]['source'].get('published_at')
        if earlier and (not newer or newer < earlier):
            raise ValueError('Transaction context publication dates would regress')
    return False


def context_timestamp(value) -> datetime:
    if not isinstance(value, str) or re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value) is None:
        raise ValueError("Housing context timestamp is invalid")
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    if parsed > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("Housing context timestamp is in the future")
    return parsed


def context_date(value, retrieved: datetime) -> date:
    if not isinstance(value, str) or re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValueError("Housing context publication date is invalid")
    parsed = date.fromisoformat(value)
    if parsed > retrieved.date() or parsed > datetime.now(timezone.utc).date():
        raise ValueError("Housing context publication date is in the future")
    return parsed


def context_url(value) -> None:
    if not isinstance(value, str):
        raise ValueError("Housing context source URL is invalid")
    parts = urlsplit(value)
    if parts.scheme != "https" or parts.hostname != "www.nsi.bg" or parts.port not in (None, 443) or parts.username or parts.password:
        raise ValueError("Housing context source must use the official NSI HTTPS origin")


def context_period(value, published: date) -> str:
    if not isinstance(value, str) or re.fullmatch(r"20[0-9]{2}-Q[1-4]", value) is None:
        raise ValueError("Housing context quarter is invalid")
    year, quarter = int(value[:4]), int(value[-1])
    end = date(year + 1, 1, 1) - timedelta(days=1) if quarter == 4 else date(year, quarter * 3 + 1, 1) - timedelta(days=1)
    if end > published:
        raise ValueError("Housing context contains an unpublished future quarter")
    return value


def context_number(value, *, count=False) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Housing context contains an invalid numeric value")
    if count and (value < 0 or value > 1_000_000_000 or value != int(value)):
        raise ValueError("Housing context contains an invalid construction count")
    if not count and not -100 <= value <= 10000:
        raise ValueError("Housing context contains an out-of-range index or rate")


def context_series(block: dict, published: date, *, construction=False) -> None:
    series = block.get("series")
    if not isinstance(series, list) or not (4 if construction else 16) <= len(series) <= 200:
        raise ValueError("Housing context series is missing or exceeds its period limit")
    periods = []
    for row in series:
        if not isinstance(row, dict):
            raise ValueError("Housing context observation is invalid")
        periods.append(context_period(row.get("period"), published))
        if construction:
            for kind in ("permitted", "started"):
                item = row.get(kind)
                if not isinstance(item, dict) or not all(field in item for field in ("buildings", "dwellings", "floor_area_m2")):
                    raise ValueError("Housing context construction observation is incomplete")
                for field in ("buildings", "dwellings", "floor_area_m2"):
                    context_number(item[field], count=True)
                if all(item[field] is None for field in ("buildings", "dwellings", "floor_area_m2")):
                    raise ValueError("Housing context contains an unpublished construction observation")
                if re.fullmatch(r"[a-f0-9]{64}", str(item.get("source_sha256", ""))) is None:
                    raise ValueError("Housing context construction provenance is invalid")
                observed_published = context_date(item.get("source_published_at"), context_timestamp(block.get("retrieved_at")))
                context_period(row["period"], observed_published)
        else:
            if not all(field in row for field in ("index", "qoq_pct", "yoy_pct", "provisional")) or not isinstance(row["provisional"], bool):
                raise ValueError("Housing context price observation is incomplete")
            for field in ("index", "qoq_pct", "yoy_pct"):
                context_number(row[field])
            if row["index"] is not None and row["index"] <= 0:
                raise ValueError("Housing context price index must be positive")
    if periods != sorted(set(periods)):
        raise ValueError("Housing context quarters must be unique and ordered")
    if not construction and sum(row["index"] is not None for row in series) < 16:
        raise ValueError("Housing context has insufficient published price-index history")
    coverage = block.get("coverage")
    if not isinstance(coverage, dict) or coverage.get("from") != periods[0] or coverage.get("through") != periods[-1] or coverage.get("observations") != len(series):
        raise ValueError("Housing context coverage does not match its series")


def validate_context(payload: bytes) -> dict:
    if not 0 < len(payload) <= MAX_CONTEXT_BYTES:
        raise ValueError("Housing context is empty or exceeds its 128 KiB byte limit")
    def invalid_constant(value):
        raise ValueError("Housing context contains a non-finite JSON constant")
    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Housing context contains a duplicate JSON field")
            result[key] = value
        return result
    data = json.loads(payload.decode("utf-8"), parse_constant=invalid_constant, object_pairs_hook=unique_fields)
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1 or data.get("status") != "available":
        raise ValueError("Housing context must be a complete available schema-1 snapshot")
    retrieved = context_timestamp(data.get("retrieved_at"))
    source = data.get("source")
    if not isinstance(source, dict):
        raise ValueError("Housing context source is missing")
    context_url(source.get("url"))
    published = context_date(source.get("published_at"), retrieved)
    coverage = data.get("coverage")
    if not isinstance(coverage, dict) or coverage.get("geography_key") != "sofia_city" or coverage.get("frequency") != "quarterly" or coverage.get("unit") != "index":
        raise ValueError("Housing context price geography, frequency or unit is invalid")
    context_series(data, published)
    construction = data.get("construction")
    # Published pre-construction snapshots remain a valid initial fallback.
    if construction is not None:
        if not isinstance(construction, dict) or construction.get("status") != "available" or construction.get("geography_key") != "sofia_capital_province" or construction.get("frequency") != "quarterly":
            raise ValueError("Housing context construction scope is invalid")
        construction_retrieved = context_timestamp(construction.get("retrieved_at"))
        construction_published = context_date(construction.get("published_at"), construction_retrieved)
        context_series(construction, construction_published, construction=True)
    return data


def preserve_context(old: dict, incoming: dict) -> bool:
    if old["retrieved_at"] > incoming["retrieved_at"] or old["coverage"]["through"] > incoming["coverage"]["through"]:
        return True
    old_construction, new_construction = old.get("construction"), incoming.get("construction")
    if old_construction is None:
        return False
    if new_construction is None:
        return True
    return (
        old_construction["coverage"]["through"] > new_construction["coverage"]["through"]
        or old_construction["retrieved_at"] > new_construction["retrieved_at"]
        or old_construction["published_at"] > new_construction["published_at"]
        or not {row["period"] for row in old_construction["series"]}.issubset(row["period"] for row in new_construction["series"])
    )


def allowed_relative(relative: str) -> bool:
    if relative == "index.html" or relative in DATA_NAMES or relative in STATIC_NAMES or GOOGLE_VERIFICATION.fullmatch(relative) is not None:
        return True
    path = PurePosixPath(relative)
    parts = path.parts
    return (
        len(parts) >= 2
        and parts[0] == "assets"
        and all(SAFE_COMPONENT.fullmatch(part) is not None for part in parts[1:])
        and not FORBIDDEN_ASSET_PARTS.intersection(part.lower() for part in path.name.split("."))
        and path.suffix.lower() in ASSET_EXTENSIONS
        and path.as_posix() == relative
    )


def read_local(path: Path, root: Path) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Approved file is missing or linked: {path.name}")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Approved file resolves outside the build directory")
    size = path.stat().st_size
    if not 0 < size <= MAX_FILE_BYTES:
        raise ValueError(f"Approved file is empty or exceeds its byte limit: {path.name}")
    payload = path.read_bytes()
    if len(payload) != size:
        raise ValueError(f"Approved file changed while being read: {path.name}")
    return payload


def planned_files(directory: Path) -> list[tuple[str, bytes]]:
    """Read the complete allowlisted deployment before connecting to hosting."""
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Input must be an existing, unlinked static build directory")
    root = directory.resolve()
    entry_payload = read_local(root / "index.html", root)
    entry_text = entry_payload.decode("utf-8")
    if "<html" not in entry_text.lower() or "</html>" not in entry_text.lower():
        raise ValueError("index.html must be a complete UTF-8 HTML document")

    assets: list[tuple[str, bytes]] = []
    assets_directory = root / "assets"
    if not assets_directory.is_dir() or assets_directory.is_symlink():
        raise ValueError("Input must contain an unlinked assets directory")
    for current, directories, filenames in os.walk(assets_directory, followlinks=False):
        current_path = Path(current)
        for name in directories:
            if SAFE_COMPONENT.fullmatch(name) is None or (current_path / name).is_symlink():
                raise ValueError("Asset directories must have safe names and cannot be links")
        for name in filenames:
            path = current_path / name
            # Unrecognized files, including environment files and source maps,
            # remain local even when a build tool copied them into assets.
            relative = path.relative_to(root).as_posix()
            if not allowed_relative(relative):
                continue
            assets.append((relative, read_local(path, root)))
    if not assets:
        raise ValueError("Input must contain at least one approved compiled asset")

    statics: list[tuple[str, bytes]] = []
    for path in root.iterdir():
        name = path.name
        is_verification = GOOGLE_VERIFICATION.fullmatch(name) is not None
        if name not in STATIC_NAMES and not is_verification:
            continue
        payload = read_local(path, root)
        if is_verification:
            if len(payload) > 64 * 1024 or payload.decode("utf-8").strip() != f"google-site-verification: {name}":
                raise ValueError("Google verification file content does not match its filename")
        statics.append((name, payload))

    for name in sorted(DATA_NAMES):
        reference = root / name
        if reference.exists():
            payload = read_local(reference, root)
            if name == CONTEXT_NAME:
                validate_context(payload)
            elif name == TRANSACTIONS_NAME:
                validate_transactions(payload)
            statics.append((name, payload))
    plan = sorted(assets) + sorted(statics) + [("index.html", entry_payload)]
    if sum(len(payload) for _, payload in plan) > MAX_TOTAL_BYTES:
        raise ValueError("Static deployment exceeds the 64 MiB total byte limit")
    return plan


def read_remote(ftp: FTP_TLS, remote: str, expected_bytes: int) -> bytes:
    output = io.BytesIO()

    def append(chunk: bytes) -> None:
        if output.tell() + len(chunk) > expected_bytes:
            raise ValueError("Remote file exceeds its byte limit")
        output.write(chunk)

    ftp.retrbinary(f"RETR {remote}", append)
    return output.getvalue()


def listed_names(ftp: FTP_TLS, directory: str) -> set[str]:
    entries = []
    def append(entry: str) -> None:
        if len(entries) >= 5000 or len(entry) > 1000:
            raise ValueError("Remote directory listing exceeds its bounds")
        entries.append(entry)
    ftp.retrlines(f"NLST {directory}", append)
    return {posixpath.basename(entry.rstrip("/")) for entry in entries}


def read_hosted_context(ftp: FTP_TLS, name: str = CONTEXT_NAME, limit: int = MAX_CONTEXT_BYTES, validator=validate_context) -> bytes | None:
    try:
        payload = read_remote(ftp, f"{REMOTE_ROOT}/{name}", limit)
    except error_perm as error:
        if not str(error).startswith("550"):
            raise
        # 550 also means permission denied. Only an accessible directory
        # listing proving absence permits the committed fallback to remain.
        if "data" not in listed_names(ftp, REMOTE_ROOT):
            return None
        if posixpath.basename(name) not in listed_names(ftp, f"{REMOTE_ROOT}/data"):
            return None
        raise ValueError("Existing hosted official context is not readable") from error
    validator(payload)
    return payload


def context_output(directory: Path, name: str = CONTEXT_NAME) -> tuple[Path, Path]:
    if name not in (CONTEXT_NAME, TRANSACTIONS_NAME):
        raise ValueError('Unsupported official context filename')
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Context input must be an existing, unlinked directory")
    root = directory.resolve()
    parent = root / "data"
    if parent.is_symlink() or (parent.exists() and not parent.is_dir()) or not parent.resolve().is_relative_to(root):
        raise ValueError("Context output directory is linked or outside the input root")
    output = root / name
    if output.is_symlink() or (output.exists() and not output.is_file()) or not output.resolve().is_relative_to(root):
        raise ValueError("Context output must be an unlinked regular file under the input root")
    return root, output


def fetch_context(ftp: FTP_TLS, directory: Path, name: str = CONTEXT_NAME, limit: int = MAX_CONTEXT_BYTES, validator=validate_context) -> None:
    root, output = context_output(directory, name)
    payload = read_hosted_context(ftp, name, limit, validator)
    if payload is None:
        # An absent host file is acceptable only when a valid committed
        # fallback actually exists. Permission and integrity failures stop.
        validator(read_local(output, root))
        print("Hosted official context is confirmed absent; retained the validated local fallback", flush=True)
        return
    output.parent.mkdir(exist_ok=True)
    context_output(directory, name)
    temporary = output.with_name(output.name + "." + uuid4().hex + ".pending")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Fetched validated {name}: {len(payload)} bytes; SHA-256 {digest(payload)}", flush=True)


def verify_remote(ftp: FTP_TLS, remote: str, payload: bytes) -> None:
    actual = read_remote(ftp, remote, len(payload))
    if len(actual) != len(payload) or digest(actual) != digest(payload):
        raise ValueError("Uploaded file failed its byte-count or SHA-256 verification")


def ensure_directory(ftp: FTP_TLS, directory: str) -> None:
    """Create asset directories only, preserving all existing hosting files."""
    if directory != f"{REMOTE_ROOT}/data" and directory != f"{REMOTE_ROOT}/assets" and not directory.startswith(f"{REMOTE_ROOT}/assets/"):
        raise ValueError("Only approved asset directories can be created")
    parent = REMOTE_ROOT
    for component in directory[len(REMOTE_ROOT) + 1:].split("/"):
        if SAFE_COMPONENT.fullmatch(component) is None:
            raise ValueError("Unsafe remote asset directory")
        parent = f"{parent}/{component}"
        try:
            ftp.mkd(parent)
        except error_perm:
            # Permission denial must not be treated as an existing directory.
            # CWD proves the requested directory exists and is accessible.
            ftp.cwd(parent)


def publish_file(ftp: FTP_TLS, relative: str, payload: bytes) -> None:
    if not allowed_relative(relative):
        raise ValueError("Refusing to publish a file outside the static allowlist")
    remote = f"{REMOTE_ROOT}/{relative}"
    if relative.startswith("assets/") or relative in DATA_NAMES:
        ensure_directory(ftp, posixpath.dirname(remote))
    temporary = f"{remote}.{uuid4().hex}.pending"
    ftp.storbinary(f"STOR {temporary}", io.BytesIO(payload))
    verify_remote(ftp, temporary, payload)
    # No delete-and-replace fallback: a failed rename leaves the current file
    # intact and stops publication before the entry HTML is switched.
    ftp.rename(temporary, remote)
    verify_remote(ftp, remote, payload)
    print(f"Published {relative}: {len(payload)} bytes; SHA-256 verified", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("dist"), help="Static Vite build directory (default: dist)")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--context-only", action="store_true", help="Publish only the official housing-context JSON from the input directory")
    modes.add_argument("--fetch-context", action="store_true", help="Fetch the verified hosted housing context into the input directory before refreshing it")
    modes.add_argument("--transactions-only", action="store_true", help="Publish only the official transaction-count JSON")
    modes.add_argument("--fetch-transactions", action="store_true", help="Fetch the hosted transaction history before refreshing it")
    args = parser.parse_args()
    selected_name, selected_limit, selected_validator = (TRANSACTIONS_NAME, MAX_TRANSACTIONS_BYTES, validate_transactions) if args.fetch_transactions or args.transactions_only else (CONTEXT_NAME, MAX_CONTEXT_BYTES, validate_context)
    if args.fetch_context or args.fetch_transactions:
        context_output(args.input, selected_name)
        plan = []
    elif args.context_only or args.transactions_only:
        root, output = context_output(args.input, selected_name)
        payload = read_local(output, root)
        selected_validator(payload)
        plan = [(selected_name, payload)]
    else:
        plan = planned_files(args.input)
    credentials = {key: os.environ.get(key) for key in ("FTP_HOST", "FTP_USER", "FTP_PASSWORD")}
    if not all(credentials.values()):
        raise ValueError("FTP_HOST, FTP_USER, and FTP_PASSWORD secrets are required")
    if any("\r" in value or "\n" in value for value in credentials.values()):
        raise ValueError("FTP credentials contain an invalid line break")

    context = ssl.create_default_context()
    with FTP_TLS(context=context, timeout=60) as ftp:
        ftp.connect(credentials["FTP_HOST"], 21)
        ftp.login(credentials["FTP_USER"], credentials["FTP_PASSWORD"])
        ftp.prot_p()
        ftp.cwd(REMOTE_ROOT)
        if args.fetch_context or args.fetch_transactions:
            fetch_context(ftp, args.input, selected_name, selected_limit, selected_validator)
            return
        for relative, payload in plan:
            if relative == TRANSACTIONS_NAME:
                previous = read_hosted_context(ftp, TRANSACTIONS_NAME, MAX_TRANSACTIONS_BYTES, validate_transactions)
                if previous is not None:
                    # Frontend publication only bootstraps this dataset. The
                    # serialized dedicated refresh owns every later update.
                    if not args.transactions_only or preserve_transactions(validate_transactions(previous), validate_transactions(payload)):
                        print('Preserved the published official transaction context', flush=True)
                        continue
            if relative == CONTEXT_NAME:
                # A frontend checkout can be older than a monthly data refresh.
                # Do not replace a newer published context with an older file.
                previous = read_hosted_context(ftp)
                if previous is not None:
                    old = validate_context(previous)
                    incoming = validate_context(payload)
                    if preserve_context(old, incoming):
                        print('Preserved newer published official housing context', flush=True)
                        continue
            publish_file(ftp, relative, payload)
    print(f"Static site published: {len(plan)} approved files. Entry HTML switched last.", flush=True)


if __name__ == "__main__":
    main()
