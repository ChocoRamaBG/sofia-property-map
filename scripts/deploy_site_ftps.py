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
import os
import posixpath
import re
import ssl
from ftplib import FTP_TLS, error_perm
from pathlib import Path, PurePosixPath
from uuid import uuid4


REMOTE_ROOT = "/htdocs"
MAX_FILE_BYTES = 10_000_000
MAX_TOTAL_BYTES = 64 * 1024 * 1024
STATIC_NAMES = frozenset({"about.html", "privacy.html", "robots.txt", "sitemap.xml"})
REFERENCE_NAME = "data/market-georeference.json"
ASSET_EXTENSIONS = frozenset({
    ".js", ".mjs", ".css", ".svg", ".png", ".jpg", ".jpeg", ".gif",
    ".webp", ".avif", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".wasm",
})
SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
GOOGLE_VERIFICATION = re.compile(r"google[A-Za-z0-9]+\.html")
FORBIDDEN_ASSET_PARTS = frozenset({"php", "phtml", "phar", "env"})


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def allowed_relative(relative: str) -> bool:
    if relative == "index.html" or relative == REFERENCE_NAME or relative in STATIC_NAMES or GOOGLE_VERIFICATION.fullmatch(relative) is not None:
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

    reference = root / REFERENCE_NAME
    if reference.exists():
        statics.append((REFERENCE_NAME, read_local(reference, root)))
    plan = sorted(assets) + sorted(statics) + [("index.html", entry_payload)]
    if sum(len(payload) for _, payload in plan) > MAX_TOTAL_BYTES:
        raise ValueError("Static deployment exceeds the 64 MiB total byte limit")
    return plan


def read_remote(ftp: FTP_TLS, remote: str, expected_bytes: int) -> bytes:
    output = io.BytesIO()

    def append(chunk: bytes) -> None:
        if output.tell() + len(chunk) > expected_bytes:
            raise ValueError("Uploaded file exceeds its expected byte count")
        output.write(chunk)

    ftp.retrbinary(f"RETR {remote}", append)
    return output.getvalue()


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
    if relative.startswith("assets/") or relative == REFERENCE_NAME:
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
    args = parser.parse_args()
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
        for relative, payload in plan:
            publish_file(ftp, relative, payload)
    print(f"Static site published: {len(plan)} approved files. Entry HTML switched last.", flush=True)


if __name__ == "__main__":
    main()
