#!/usr/bin/env bash
# Disposable runner-only origin/update verification. Never run a real device app.
# Usage: smoke-update.sh STAGED_SITE [EVIDENCE_DIRECTORY]
# STAGED_SITE is build-repository.sh's output; GNUPGHOME still has signing access.
set -euo pipefail
if [[ -z ${DBUS_SESSION_BUS_ADDRESS:-} ]]; then
  exec dbus-run-session -- bash "$0" "$@"
fi
site=$(realpath "${1:?Usage: smoke-update.sh STAGED_SITE [EVIDENCE_DIRECTORY]}")
root=$(cd "$(dirname "$0")" && pwd)
: "${GNUPGHOME:?Use the isolated CI signing keyring}"
# Save before replacing HOME for isolated Flatpak clients.
export GNUPGHOME=$(realpath "$GNUPGHOME")
for tool in flatpak ostree gpg curl sha256sum python3 timeout; do command -v "$tool" >/dev/null; done
work=$(mktemp -d "${RUNNER_TEMP:-/tmp}/piper-update-smoke.XXXXXXXX")
server_pid=
cleanup() {
  if [[ -n $server_pid ]]; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  rm -rf -- "$work"
}
trap cleanup EXIT
key="$root/piper-repository.gpg"
fingerprint=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["gpg_fingerprint"])' "$root/config.json")
[[ $fingerprint =~ ^[A-F0-9]{40}$ ]]
actual=$(gpg --batch --show-keys --with-colons "$key" | awk -F: '$1 == "fpr" { print $10; exit }')
[[ "$actual" == "$fingerprint" ]]
app=io.github.jheinem1.PiperKirigami
ref="$app/x86_64/development"
ostree_ref="app/$ref"
remote=piper-kirigami
old_bundle="$work/old.flatpak"
curl --proto '=https' --tlsv1.2 --fail --location --retry 3 \
  'https://github.com/jheinem1/piper-kirigami/releases/download/v0.1.2/io.github.jheinem1.PiperKirigami-x86_64-development.flatpak' \
  -o "$old_bundle"
printf '%s  %s\n' '837d218f5ede80336c968af36641da99b114181cc5f99aa80abc9b353c7cf874' "$old_bundle" | sha256sum --check --status
old_commit=ed8be5acfc48963e0ccd3a04a5e1531638aec93c367b34fe9d52b37e7e95b3b7
new_commit=$(ostree --repo="$site/repo" rev-parse "$ostree_ref")
[[ "$new_commit" =~ ^[a-f0-9]{64}$ && "$new_commit" != "$old_commit" ]]

# The old commit predates collection binding. Do not assign a collection ID or
# rewrite its commit; sign its original identity in a separate test repository.
old_repo="$work/old-repo"
ostree --repo="$old_repo" init --mode=archive-z2
flatpak build-import-bundle --gpg-sign="$fingerprint" --gpg-homedir="$GNUPGHOME" "$old_repo" "$old_bundle"
[[ $(ostree --repo="$old_repo" rev-parse "$ostree_ref") == "$old_commit" ]]
flatpak build-update-repo --title='Piper migration fixture' --default-branch=development \
  --gpg-sign="$fingerprint" --gpg-homedir="$GNUPGHOME" --gpg-import="$key" "$old_repo"

# Bind an ephemeral loopback port, report it only after listening, and atomically
# switch one stable HTTP URL between old/new repositories. No public hosting.
mkdir "$work/http"
ln -s "$site/repo" "$work/http/repo"
python3 - "$work/http" "$work/port" <<'PY' &
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
handler = partial(SimpleHTTPRequestHandler, directory=sys.argv[1])
server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
Path(sys.argv[2]).write_text(str(server.server_port))
server.serve_forever()
PY
server_pid=$!
for attempt in $(seq 1 100); do
  [[ -s "$work/port" ]] && break
  kill -0 "$server_pid"
  sleep 0.1
done
test -s "$work/port"
url="http://127.0.0.1:$(cat "$work/port")/repo/"

client() {
  export HOME="$work/$1/home"
  export XDG_DATA_HOME="$work/$1/data"
  export XDG_CONFIG_HOME="$work/$1/config"
  export XDG_CACHE_HOME="$work/$1/cache"
  export XDG_RUNTIME_DIR="$work/$1/run"
  export FLATPAK_USER_DIR="$XDG_DATA_HOME/flatpak"
  mkdir -p "$HOME" "$XDG_DATA_HOME" "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" "$XDG_RUNTIME_DIR"
  chmod 700 "$XDG_RUNTIME_DIR"
}
marker_create() {
  mkdir -p "$HOME/.var/app/$app/data"
  printf 'private-profile-fixture-%s\n' "$1" > "$HOME/.var/app/$app/data/migration-sentinel"
}
marker_verify() {
  [[ $(cat "$HOME/.var/app/$app/data/migration-sentinel") == "private-profile-fixture-$1" ]]
}
check_install() {
  [[ $(flatpak info --user --show-origin "$ref") == "$remote" ]]
  [[ $(flatpak info --user --show-commit "$ref") == "$1" ]]
  # Flatpak must keep signature verification enabled; no unsigned test shortcut.
  [[ $(ostree --repo="$FLATPAK_USER_DIR/repo" config get "remote \"$remote\".gpg-verify") == true ]]
}
switch_repo() {
  python3 - "$work/http/repo" "$1" <<'PY'
import os, sys
link, target = sys.argv[1:]
os.symlink(target, link + '.next')
os.replace(link + '.next', link)
PY
}

refresh_summary_timestamps() {
  # This fixture builds the old repository after the new one. Make the later
  # HTTP deployment strictly newer at Last-Modified's whole-second precision,
  # without changing any signed bytes, so conditional requests cannot reuse it.
  sleep 1
  for metadata in summary summary.sig summary.idx; do
    if [[ -f "$site/repo/$metadata" ]]; then
      touch "$site/repo/$metadata"
    fi
  done
}

# --no-deps scopes this to application origin/commit/data migration. The runtime
# and real installed app launch have already passed the release's Flatpak job.
# No --no-gpg-verify, --delete-data, system installation, or application execution.
client bundle-migration
timeout --kill-after=5s 300s flatpak install --user --noninteractive --no-deps "$old_bundle"
[[ $(flatpak info --user --show-commit "$ref") == "$old_commit" ]]
marker_create bundle
flatpak remote-add --user --gpg-import="$key" "$remote" "$url"
timeout --kill-after=5s 300s flatpak install --user --noninteractive --no-deps --reinstall "$remote" "$ref"
check_install "$new_commit"
marker_verify bundle
printf 'Standalone bundle migration: origin, new commit and private data verified.\n'

# Separate installation: first install the old signed commit from the named
# remote, replace only what the same HTTP URL serves, then use ordinary update.
switch_repo "$old_repo"
client remote-update
flatpak remote-add --user --gpg-import="$key" "$remote" "$url"
timeout --kill-after=5s 300s flatpak install --user --noninteractive --no-deps "$remote" "$ref"
check_install "$old_commit"
marker_create update
refresh_summary_timestamps
switch_repo "$site/repo"
timeout --kill-after=5s 300s flatpak update --user --noninteractive --no-deps "$ref"
check_install "$new_commit"
marker_verify update
printf 'Normal Flatpak update: same remote, advanced commit and private data verified.\n'
if [[ $# -ge 2 ]]; then
  mkdir -p -- "$2"
  python3 - "$2/update-smoke.json" "$old_commit" "$new_commit" <<'PY'
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps(dict(old_commit=sys.argv[2], new_commit=sys.argv[3],
    standalone_bundle_migration='passed', normal_remote_update='passed',
    private_data_preserved=True, runtime_execution='covered separately by Flatpak build job'), indent=2) + '\n')
PY
fi
