#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Only for an isolated CI/test account after installing the bundle there.
set -euo pipefail
OUT=${1:?Usage: smoke-installed.sh OUTPUT_DIRECTORY}
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
REF=io.github.jheinem1.PiperKirigami/x86_64/development
flatpak run --user --env=QT_QPA_PLATFORM=offscreen --env=QT_QUICK_BACKEND=software \
  --command=python3 "$REF" /app/share/piper-kirigami/check-runtime.py > "$OUT/runtime-check.json"
# Screenshots stay in the app's normal sandbox cache; no host filesystem grant.
flatpak run --user --command=sh "$REF" -c \
  'exec piper-kirigami --mock --headless --screenshot "$XDG_CACHE_HOME/piper-smoke.png"'
flatpak run --user --command=sh "$REF" -c \
  'test -s "$XDG_CACHE_HOME/piper-smoke.png" && cat "$XDG_CACHE_HOME/piper-smoke.png"' > "$OUT/installed-smoke.png"
python3 - "$OUT/installed-smoke.png" <<'PY'
from pathlib import Path
import struct
import sys
image = Path(sys.argv[1]).read_bytes()
assert image[:8] == b'\x89PNG\r\n\x1a\n', 'Missing PNG screenshot'
width, height = struct.unpack('>II', image[16:24])
assert width >= 960 and height >= 700, (width, height)
print(f'Installed bundle rendered {width} x {height}')
PY
flatpak info --user --show-commit "$REF" > "$OUT/flatpak-app-commit.txt"
flatpak info --user --show-permissions "$REF" > "$OUT/installed-permissions.ini"
(cd "$OUT" && sha256sum -- *.flatpak *.tar.gz *info.json flatpak-metadata.ini manifest.json \
  runtime-check.json installed-smoke.png flatpak-app-commit.txt installed-permissions.ini > SHA256SUMS)
