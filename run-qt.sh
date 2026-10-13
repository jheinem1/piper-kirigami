#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ -d .deps ]; then export PYTHONPATH="$PWD/.deps${PYTHONPATH:+:$PYTHONPATH}"; fi
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-/tmp/piper-qt-cache}"
mkdir -p "$XDG_CACHE_HOME"
exec python3 -m qt_piper "$@"
