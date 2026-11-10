# KDE interface and profile files verification

Verified on 2026-11-10 (UTC), before building the combined 0.1.3 release.
The changes sit on top of the Qt runtime alignment, KDE palette, and ratbagd
idle-reconnect fixes. The original width-fix worktree was preserved.

## Implemented

- Production colors and accent follow KDE; the application theme toggle is gone.
- The device chooser uses its natural text width with a responsive cap. Settings
  and assignment fields have a centered 18-grid-unit width; macros retain their
  full-width editor.
- The menu opens below its trigger and a second press closes it. About has About,
  Components and Authors tabs, the package version, retained license and credits.
- Removed duplicate pending-change text, the sensitivity subtitle, the Advanced
  shortcut and duplicate polling-rate control. Capability explanations use compact
  information buttons. Apply/Reset now follow the visible page's settled scope.
- Lighting has the Qt color chooser and optional hex input. Accepting the chooser
  updates only the open lighting editor; canceling that editor stages nothing.
- Profiles exposes every actual slot plus named JSON save/load. A validated,
  reviewed import is a pending draft, never a device write. See
  [the format and safety contract](../PROFILE-FILES.md).

## Automated checks

Host tests used Python 3.14 and Qt/PySide6 6.11.2, with mock devices or a private
D-Bus daemon. They did not write to physical hardware.

- **170 tests and 1,434 diagram subtests passed**: backend, reconnect, profile-file
  validation/I/O and diagrams.
- **23 native QML UI scenarios passed**, including every existing assignment,
  keyboard, target, navigation, macro, focus, recovery and layout scenario plus
  menu/About, device chooser and footer checks. Each ran in its own pytest process.
- **2 native forms tests passed**, covering 242 real Qt inputs, centered widths at
  960×700 and 1280×820 with 11/14-point fonts, and chooser accept/cancel/Escape.
- **1 profile-file UI test passed**, including warning-free empty startup, all
  three mock slots, file/review cancellation, staging, reset and stale-target
  rejection. The complete profile-specific suite was **56 tests**; its backend
  cases overlap the 170-test count above.
- **7 handbook/desktop-style tests passed** and **15 source-packaging tests passed**.
- The integrated settings verifier passed Sensitivity, Advanced, Profiles and
  Lighting; its page-scope check caught and verified the settled-scope fix.
- Ruff, Black and `git diff --check` passed. QML regression checks reported no QML
  warnings. Host pytest emitted existing anyio/PyGObject deprecation warnings.

## Native and real-service checks

An isolated KWin Wayland session launched the source application with mock
devices and an isolated home. The menu opened beneath its trigger and toggled
closed; the lighting chooser opened as a separate Qt window. Color acceptance
returned to the lighting editor, whose cancellation left Apply disabled. This
used an isolated compositor, not the user's live application window. The source
launch emitted a missing desktop-registration portal diagnostic and Qt AT-SPI
adapter diagnostics; it did not emit QML load errors. The chooser is selected by
Qt's platform-dialog API and can use Qt's fallback when a platform-specific
implementation is unavailable.

The real Logitech G600 was read once through a guard allowing only GetAll and
AddMatch. All **3 actual slots** exported and validated losslessly: each had
**40 assignments (including 20 G-Shift), 4 DPI stages and 1 LED**. There were
**146 permitted read/match calls and zero writes**. Actual mappings stayed in
memory and were neither printed nor saved.

Atomic overwrite and readback of a synthetic JSON file succeeded through a
single-file read/write document-portal grant inside the installed Flatpak runtime.
The temporary grant was revoked afterward. This verified the new writer in the
existing sandbox; it was not a claim that the new release had been installed.
No broad filesystem permission was added.

The natural ratbagd idle regression and recovery evidence is recorded separately
in [ratbagd-idle-reconnect.md](ratbagd-idle-reconnect.md).

## Packaging boundary

Both Flatpak and Fedora package checks include the reconnect, profile-file and
native-form tests. Installed runtime alignment and launch smoke checks remain
required in CI. Source verification alone does not establish a successful package
build, published release, desktop installation or JamesOS image build.
