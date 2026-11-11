#!/usr/bin/env bash
# Build a signed HTTP repository from the exact already-tested bundle.
set -euo pipefail
artifacts=$(realpath "${1:?Usage: build-repository.sh ARTIFACTS OUTPUT}")
output=${2:?}
root=$(cd "$(dirname "$0")" && pwd)
: "${GNUPGHOME:?Use an isolated CI signing keyring}"
mapfile -t config < <(python3 - "$root/config.json" <<'PY'
import json, re, sys
c = json.load(open(sys.argv[1]))
assert re.fullmatch(r'[A-F0-9]{40}', c.get('gpg_fingerprint') or ''), 'Provision and commit the repository public key/fingerprint first'
for key in ('gpg_fingerprint', 'url', 'collection_id', 'public_key'):
    print(c[key])
PY
)
[[ ${#config[@]} == 4 ]] || exit 1
fingerprint=${config[0]}
key="$root/${config[3]}"
actual=$(gpg --batch --show-keys --with-colons "$key" | awk -F: '$1 == "fpr" {print $10; exit}')
[[ "$actual" == "$fingerprint" ]] || { echo 'Public key fingerprint mismatch' >&2; exit 1; }
[[ ! -e "$output" ]] || { echo 'Output must be new; never modify a live repository' >&2; exit 1; }
(cd "$artifacts" && sha256sum --check SHA256SUMS)
mkdir -p "$output/repo"
output=$(realpath "$output")
repo="$output/repo"
ostree --repo="$repo" init --mode=archive-z2 --collection-id="${config[2]}"
flatpak build-import-bundle --gpg-sign="$fingerprint" --gpg-homedir="$GNUPGHOME" \
  "$repo" "$artifacts/io.github.jheinem1.PiperKirigami-x86_64-development.flatpak"
expected=$(cat "$artifacts/flatpak-app-commit.txt")
actual=$(ostree --repo="$repo" rev-parse app/io.github.jheinem1.PiperKirigami/x86_64/development)
[[ "$actual" == "$expected" ]] || { echo 'Imported commit differs from tested bundle' >&2; exit 1; }
flatpak build-update-repo --title='Piper Kirigami' --default-branch=development \
  --collection-id="${config[2]}" --deploy-collection-id \
  --gpg-sign="$fingerprint" --gpg-homedir="$GNUPGHOME" --gpg-import="$key" "$repo"
# Verify commit and summary from a fresh client repository, not the signing keyring.
verify=$(mktemp -d)
trap 'rm -rf "$verify"' EXIT
ostree --repo="$verify/client" init --mode=archive-z2
ostree --repo="$verify/client" remote add --set=gpg-verify-summary=true --gpg-import="$key" piper "file://$repo"
ostree --repo="$verify/client" pull piper app/io.github.jheinem1.PiperKirigami/x86_64/development
ostree --repo="$verify/untrusted" init --mode=archive-z2
ostree --repo="$verify/untrusted" remote add --set=gpg-verify=true --set=gpg-verify-summary=true piper "file://$repo"
mkdir -m 700 "$verify/empty-keyring"
if GNUPGHOME="$verify/empty-keyring" ostree --repo="$verify/untrusted" pull piper app/io.github.jheinem1.PiperKirigami/x86_64/development; then
  echo 'Untrusted client unexpectedly accepted the repository' >&2
  exit 1
fi
python3 "$root/write-descriptors.py" "$root/config.json" "$key" "$output"
cp "$artifacts/release.json" "$output/release.json"
touch "$output/.nojekyll"
# Keep below GitHub Pages' 1 GB published-site limit, with headroom.
test "$(du -sb "$output" | cut -f1)" -lt 900000000
