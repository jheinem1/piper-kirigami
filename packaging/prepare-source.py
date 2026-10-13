#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Prepare an RPM source archive/spec from one immutable, committed Git snapshot.

Only committed files are included. Git preserves tracked SVG symlinks and modes;
gzip has neither a wall-clock timestamp nor an output-path-dependent filename.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args])


def prepare(root: Path, ref: str, output: Path) -> dict:
    commit = git(root, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
    epoch = int(git(root, "show", "-s", "--format=%ct", commit))
    meson = git(root, "show", f"{commit}:qt-build/meson.build").decode()
    match = re.search(r"\bversion\s*:\s*['\"]([0-9]+\.[0-9]+\.[0-9]+)['\"]", meson)
    if match is None:
        raise ValueError("qt-build/meson.build must contain a numeric X.Y.Z project version")
    version = match.group(1)
    moment = datetime.fromtimestamp(epoch, timezone.utc)
    release = f"0.{moment:%Y%m%d%H%M%S}.git{commit[:12]}"
    template = git(root, "show", f"{commit}:packaging/fedora/piper-kirigami.spec.in").decode()
    replacements = {
        "VERSION": version,
        "RELEASE": release,
        "SOURCE_DATE_EPOCH": str(epoch),
        "COMMIT": commit,
        "CHANGELOG_DATE": (
            f"{('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')[moment.weekday()]} "
            f"{('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')[moment.month - 1]} "
            f"{moment.day:02d} {moment.year}"
        ),
    }
    for name, value in replacements.items():
        template = template.replace(f"@{name}@", value)
    if re.search(r"@[A-Z_]+@", template):
        raise ValueError("Unresolved RPM template placeholder")

    output = output.resolve()
    for directory in ("SOURCES", "SPECS", "RPMS", "SRPMS", "BUILD", "BUILDROOT"):
        (output / directory).mkdir(parents=True, exist_ok=True)
    filename = f"piper-kirigami-{version}.tar.gz"
    archive = output / "SOURCES" / filename
    tar_bytes = git(root, "-c", "tar.umask=0022", "-c", "core.attributesFile=/dev/null", "archive", "--format=tar", f"--prefix=piper-kirigami-{version}/", commit)
    with archive.open("wb") as file:
        with gzip.GzipFile(filename="", mode="wb", fileobj=file, mtime=0) as compressed:
            compressed.write(tar_bytes)
    (output / "SPECS" / "piper-kirigami.spec").write_text(template)
    info = {
        "name": "piper-kirigami",
        "version": version,
        "release": release,
        "commit": commit,
        "source_date_epoch": epoch,
        "source_archive": filename,
        "source_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "channel": "unsigned-development-snapshot",
    }
    (output / "BUILD-INFO.json").write_text(json.dumps(info, indent=2, sort_keys=True) + "\n")
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD", help="Committed Git revision (default: HEAD)")
    parser.add_argument("--output", type=Path, required=True, help="RPM top directory; prefer outside checkout")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        info = prepare(root, args.ref, args.output)
    except (ValueError, subprocess.CalledProcessError) as error:
        print(f"Source preparation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(info, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
