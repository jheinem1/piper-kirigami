# Development builds for JamesOS

The primary deliverable is an **x86_64 Flatpak bundle** for the Fedora 44/Bazzite-based JamesOS desktop. It uses the existing KDE 6.11 runtime family and the host's ratbagd 0.18/API 2 service. An optional native Fedora 44 **noarch RPM** is also built for later image-level integration.

These are unsigned, experimental CI artifacts, not stable releases or a Flathub submission. This repository does not install anything on JamesOS, publish a release, or modify its image configuration. Python and QML are packaged as an application; this is not a claim of a separately compiled native frontend.

## Flatpak contract

- App ID: `io.github.jheinem1.PiperKirigami`
- Branch and architecture: `development`, `x86_64`
- Command: `piper-kirigami`
- Runtime: `org.kde.Platform//6.11`; build SDK: `org.kde.Sdk//6.11`
- Python bindings: Flathub's `io.qt.PySide.BaseApp//6.11`
- Host service: `org.freedesktop.ratbag1`, API version 2

The exported desktop file, icon and AppStream component use the new application ID. GTK Piper's files and identity are not replaced.

The app requests Wayland, fallback X11, shared IPC, DRI graphics and permission to talk to **only `org.freedesktop.ratbag1` on the system bus**. It requests no network, home/host filesystem, raw input/HID access, or unrestricted system-bus socket. ratbagd remains a host service, with host policy controlling access. Existing runtime-defined KDE integration permissions may appear in installed metadata; CI records the final permission set for review.

### Dependencies and ABI

KDE's [6.11 runtime manifest](https://github.com/KDE/flatpak-kde-runtime/blob/qt6.11/org.kde.Sdk.json.in) includes Kirigami, QQC2 Desktop Style, Breeze widget style, icon theme and color schemes. The SDK itself does not supply the application's PySide6 bindings. The maintained [PySide BaseApp](https://github.com/flathub/io.qt.PySide.BaseApp) builds them against the matching KDE Qt runtime.

Only `dbus-next` is added as a runtime Python dependency. Its pure-Python wheel is pinned to version 0.2.3 by full HTTPS URL and SHA-256 in `packaging/flatpak/python-dbus-next.json`. PySide/Qt wheels from PyPI are never used. pytest and its pinned closure are installed into `/app/test-tools` for the build tests, then removed before export. The BaseApp's recommended cleanup removes unused WebEngine/NumPy components.

Runtime and BaseApp branches receive updates. Every build records the exact installed Platform, SDK and BaseApp OSTree commits in `build-info.json`; these refs are not bundled as separate runtime payloads. The application bundle includes the required BaseApp binding files. For strict rebuilds, use a dedicated builder with the recorded commits, rather than assuming today's branch heads match an older artifact. Archived refs may eventually become unavailable.

The build imports the required PySide modules, checks the Qt/PySide major/minor versions, checks Breeze style/icons/schemes, and runs the actual QML app. Full versions and import paths are saved after the installed-bundle smoke test. A runtime/BaseApp update that breaks private Qt symbols or QML imports is a failed build requiring a matched rebuild, not a reason to install arbitrary pip wheels or disable checks.

## Build locally, without installing the app

Use a disposable development account or VM with Flatpak, flatpak-builder, Git, Python 3 and a working user session bus. The commands below add Flathub and install **build prerequisites into that account**; they do not install Piper Kirigami:

```sh
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user flathub \
  org.kde.Platform/x86_64/6.11 org.kde.Sdk/x86_64/6.11 io.qt.PySide.BaseApp/x86_64/6.11
python3 -m unittest discover -s packaging/tests -v
xvfb-run -a -s "-screen 0 1600x1100x24" dbus-run-session -- bash packaging/flatpak/build.sh ../piper-artifacts HEAD
```

The script packages the **selected Git commit**, ignoring uncommitted edits. Commit intended source changes first. It builds in a temporary directory, runs the active backend/SVG/KDE UI tests without real hardware, exports the bundle and removes its temporary build tree. It does not add remotes, install prerequisites, install the resulting app, or publish anything. Install Xvfb and xauth on the builder. Native popup keyboard checks use the real X11 display created by `xvfb-run`; offscreen rendering is reserved for icon and installed-startup smoke checks. The build-only X11 socket is not an additional installed-app permission.

The source snapshot, including upstream SVG symlinks, is made with `git archive`. Its project version comes only from `qt-build/meson.build`. The archive has stable Git timestamps, fixed archive permissions and deterministic gzip headers. `source-info.json` records its commit and SHA-256. Source archive reproducibility is tested; full Flatpak/RPM bit-for-bit reproducibility across changing runtimes, package repositories or builder versions is not promised.

### Reviewing a built bundle

Download the artifact for the intended successful commit. Verify `SHA256SUMS`, `build-info.json`, `runtime-check.json`, the installed mock screenshot and `installed-permissions.ini`. Checksums detect corruption; they are not a publisher signature. Do not deploy artifacts from untrusted pull requests.

When choosing to test it in a disposable account, install the downloaded bundle and launch its mock mode:

```sh
sha256sum -c SHA256SUMS
flatpak install --user ./io.github.jheinem1.PiperKirigami-x86_64-development.flatpak
flatpak run io.github.jheinem1.PiperKirigami/x86_64/development --mock
```

The bundle references Flathub for its runtime, which must be available or downloadable; this is not an offline runtime installer. It has no update repository and does not automatically enroll JamesOS into a new application feed. A deliberate later image integration should select a tested commit and establish signing/update policy first.

Real-device readiness additionally requires JamesOS tests for host ratbagd access, permissions, reconnect/hotplug, Wayland/X11, on-device writes and firmware persistence. Mock CI cannot establish these. Running without `--mock` uses the host daemon; pressing Apply may alter device settings.

## CI artifacts

`.github/workflows/build-artifacts.yml` runs on pull requests, pushes to `main` and manual dispatch. Actions are pinned by commit, credentials are not persisted and repository token permission is read-only. There is no release, tag, image-build or deployment job.

The primary Flatpak job:

1. Checks source reproducibility, archive symlinks/modes, dependency hashes, identity and permission rules.
2. Installs matching Flathub dependencies into a disposable GitHub runner.
3. Builds with network-free, hash-pinned Python dependency installation and runs active model, SVG and native KDE interaction tests.
4. Exports the development bundle, installs it **only in that disposable runner**, then launches its actual installed command with `--mock --headless` and validates the PNG output. This second launch runs on the Platform runtime, after test dependencies are removed, rather than on the SDK.
5. Uploads the tested `.flatpak`, source archive, source/build/runtime metadata, final permissions, screenshot and `SHA256SUMS` for 30 days.

A failed build or installed-runtime test does not publish a purportedly tested bundle artifact. Build logs remain in the workflow run. Historical upstream workflows are preserved under `upstream-reference/workflows/` and are not enabled as current CI.

## Optional Fedora 44 RPM

`packaging/fedora/piper-kirigami.spec.in` installs only the active frontend, artwork, launcher and separate native desktop/icon identity. It declares Fedora's system packages: `python3-pyside6`, `python3-shiboken6`, `python3-dbus-next`, Qt 6 QML/SVG/Wayland, `kf6-kirigami`, `kf6-qqc2-desktop-style`, `plasma-breeze-qt6`, `plasma-breeze-common`, `breeze-icon-theme`, Noto Sans and `libratbag-ratbagd`. There is no bundled daemon, privileged setup script, or `Obsoletes/Conflicts` against GTK Piper.

The generated snapshot release is `0.<UTC commit timestamp>.git<12-character SHA>.fc44`, so it sorts below a future `1.fc44` stable release at the same project version. It does not depend on a local wall clock or shallow-clone commit count. RPM and Flatpak share the same source-version authority.

In a **Fedora 44 build container**, after installing the usual RPM build tools:

```sh
python3 packaging/prepare-source.py --output /tmp/piper-rpmbuild
sudo dnf install rpm-build dnf5-plugins
sudo dnf builddep /tmp/piper-rpmbuild/SPECS/piper-kirigami.spec
rpmbuild -ba --define '_topdir /tmp/piper-rpmbuild' /tmp/piper-rpmbuild/SPECS/piper-kirigami.spec
```

CI runs `%check`, then installs the RPM in a second clean Fedora 44 container and runs the installed launcher offscreen from outside the source tree. It uploads the `.noarch.rpm`, `.src.rpm`, source tarball, generated spec, dependency/package manifests, screenshot and checksums. Keep the CI Fedora matrix aligned with the downstream image base. A noarch payload still requires a compatible target distribution and Qt/KDE package set.

For JamesOS's immutable host, prefer the primary Flatpak route. The RPM is a future image-build input; do not run a mutable-host `dnf install` recipe on the live Bazzite desktop. No JamesOS configuration change is made here.

## Validation boundary

Packaging unit tests, JSON/XML/YAML parsing, shell syntax and staged Meson installation can be checked independently of Flatpak/RPM availability. A successful CI run is required before claiming that the actual bundle or RPM built and passed its installed-runtime checks. Hardware validation remains separate even after those jobs pass.
