# Signed Flatpak update repository

The intended repository is `https://jheinem1.github.io/piper-kirigami/repo/`.
It is not live merely because these files exist. Configuration intentionally fails
closed until the owner provisions signing and GitHub Pages.

## One-time owner setup

1. Approve publishing these changes to the public Piper fork.
2. Create a dedicated OpenPGP signing key in an approved secure environment and
   keep an offline backup. Do not use a personal email-signing key. The CI key must
   work noninteractively; access to it permits publishing trusted Piper updates.
3. Export only its public key in binary format as
   `packaging/repository/piper-repository.gpg`. Set its full uppercase primary
   fingerprint in `config.json`. Supply the same public file and fingerprint to
   JamesOS's `system/piper-kirigami` trust configuration. Never commit a private key.
4. Store a base64-encoded export of the dedicated secret signing key as the
   GitHub environment secret `FLATPAK_SIGNING_KEY` in `github-pages`. Restrict that
   environment to approved release tags, preferably with owner approval. Set the
   repository's Pages build source to **GitHub Actions**. These are explicit
   owner-controlled setup steps, not performed by this change.
5. Push a new approved `vX.Y.Z` tag matching the project version, after the commit
   is on main. Do not reuse an existing release tag or overwrite its assets.

Use a stable signing key across releases. Key rotation requires a separately
planned, signed transition and client trust update; never generate a new key on
every build, disable GPG verification, or trust an arbitrary downloaded key.

## Release behavior

The existing CI builds/tests the Flatpak and RPM. The publishing job imports the
exact tested Flatpak into a new archive-mode OSTree repository, signs its app
commit and repository metadata, and confirms the imported commit matches the
installed-runtime-tested bundle. A clean temporary client verifies signatures
while pulling it. A bad key, missing secret, bad checksum or failed check stops
publication. Source builds and pull requests never get the signing secret.

The job creates a draft release with its exact tested artifacts, uploads the
repository to Pages, deploys it, then exposes the release. Publishing is serialized,
and a lower version cannot replace a higher published version. The repository
contains the latest release, not every main-branch commit. The existing
`io.github.jheinem1.PiperKirigami/x86_64/development` identity is retained to preserve
installed app data and upgrade continuity.

Each deployment replaces the whole Pages site atomically with a self-contained
repository. Only the current app commit is needed for a full client update; this
avoids unbounded Git history/repository growth. It sacrifices previous-version
server rollback and incremental deltas. Existing installations remain usable when
hosting is unavailable, and local pre-migration backups provide rollback. GitHub
Pages is appropriate for this small personal repository, not an unlimited download
service; keep the site under 1 GB (CI enforces a 900 MB safety ceiling), monitor
bandwidth, and plan another host if it grows.

A failed deployment leaves the prior live Pages repository intact and may leave a
draft release. A failed final release exposure can leave the new signed repository
live with its release still draft. Inspect the deployment and exact asset hashes
before recovering either case; blindly retrying or deleting/replacing assets is
not supported. The workflow intentionally refuses an existing release.

## Client enrollment and migration

The site exposes `piper-kirigami.flatpakrepo` and `piper-kirigami.flatpakref`, each
embedding the public key. The proposed JamesOS installer additionally ships the
public key/fingerprint, validates an existing remote's URL and trust, backs up the
old app and launchers, and reinstalls from the named signed remote. No uninstall
or deletion of `~/.var/app/io.github.jheinem1.PiperKirigami` is needed. GTK Piper and
its profile library remain available. Verify the installed origin is the named
remote and the mock runtime test passes before switching launchers.

Once enrolled, Discover/`flatpak update --user` receives newly published releases.
There is no application-version pin or required JamesOS rebuild per Piper release.
Flatpak still verifies signed commits. Ordinary Flatpak updates do not execute the
JamesOS installer runtime gate, so release CI's installed-runtime test remains
essential; shared KDE runtime changes can still require a matched Piper rebuild.

## Required final validation before claiming live service

Run the real release CI, verify the public `.flatpakrepo` and signed summary from
a fresh disposable Flatpak installation, install from the HTTP remote, then publish
a second tested version and prove a normal `flatpak update` advances its commit.
Also migrate an existing bundle install, confirm its origin changes, preserve its
private data, and test an invalid signing key is rejected. Local unit tests alone
do not establish any of these network/runtime outcomes.
