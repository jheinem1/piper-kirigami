#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Build only. Runtime/SDK/BaseApp prerequisites must already be installed.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OUT=${1:?Usage: packaging/flatpak/build.sh OUTPUT_DIRECTORY [GIT_REF]}
REF=${2:-HEAD}
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
# The sandboxed Builder can access host-mounted output paths, but its /tmp is
# private. Keep the source, build tree and repository beside the artifacts.
WORK=$(mktemp -d "$OUT/.build.XXXXXXXX")
trap 'rm -rf "$WORK"' EXIT
APP_ID=io.github.jheinem1.PiperKirigami
BRANCH=development
ARCH=x86_64

# Native popup input needs an actual display. CI supplies an isolated Xvfb.
[[ -n "${DISPLAY:-}" ]] || { echo 'Run this build inside xvfb-run; native UI checks require an X display.' >&2; exit 1; }

for tool in flatpak flatpak-builder git python3; do command -v "$tool" >/dev/null; done
python3 "$ROOT/packaging/prepare-source.py" --ref "$REF" --output "$WORK/source"
cp "$WORK/source/BUILD-INFO.json" "$OUT/source-info.json"
cp "$WORK/source/SOURCES/"*.tar.gz "$OUT/"
mkdir "$WORK/src"
tar -xzf "$WORK/source/SOURCES/"*.tar.gz --strip-components=1 -C "$WORK/src"
MANIFEST="$WORK/src/packaging/flatpak/$APP_ID.json"

# Record the exact installed refs used by this build, not just moving branches.
python3 - "$OUT" <<'PY'
import json
from pathlib import Path
import subprocess
import sys
out = Path(sys.argv[1])
refs = {}
for ref in ('org.kde.Platform/x86_64/6.11', 'org.kde.Sdk/x86_64/6.11', 'io.qt.PySide.BaseApp/x86_64/6.11'):
    refs[ref] = subprocess.check_output(['flatpak', 'info', '--user', '--show-commit', ref], text=True).strip()
info = json.loads((out / 'source-info.json').read_text())
info.update({'app_id': 'io.github.jheinem1.PiperKirigami', 'arch': 'x86_64', 'branch': 'development',
             'flatpak_refs': refs, 'flatpak_version': subprocess.check_output(['flatpak', '--version'], text=True).strip(),
             'builder_version': subprocess.check_output(['flatpak-builder', '--version'], text=True).strip()})
(out / 'build-info.json').write_text(json.dumps(info, indent=2, sort_keys=True) + '\n')
PY
flatpak-builder --user --arch="$ARCH" --force-clean \
  --state-dir="$WORK/state" --repo="$WORK/repo" \
  "$WORK/build" "$MANIFEST"
test ! -e "$WORK/build/files/test-tools"
test -f "$WORK/build/files/share/applications/$APP_ID.desktop"
test -f "$WORK/build/files/share/icons/hicolor/scalable/apps/$APP_ID.svg"
cp "$WORK/build/metadata" "$OUT/flatpak-metadata.ini"
cp "$MANIFEST" "$OUT/manifest.json"
BUNDLE="$OUT/$APP_ID-$ARCH-$BRANCH.flatpak"
flatpak build-bundle --arch="$ARCH" \
  --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo \
  "$WORK/repo" "$BUNDLE" "$APP_ID" "$BRANCH"
(cd "$OUT" && sha256sum -- *.flatpak *.tar.gz *info.json flatpak-metadata.ini manifest.json > SHA256SUMS)
printf 'Built development bundle: %s\n' "$BUNDLE"
