# Offline handbook and KDE help integration

The application provides **Piper Kirigami Handbook** in its application menu and the standard **F1** shortcut. The reader is a native Qt Widgets `QTextBrowser` window using the existing Breeze application style and palette. It includes local contents links, text search, next/previous matches, and keyboard controls. No WebEngine, network service or added sandbox permission is required. The packaged HTML is also a standalone document.

`qt_piper/help.py` loads `qt_piper/help/handbook.html` relative to its own installed location. Meson's existing `install_subdir('../qt_piper', ...)` includes both files automatically. Flatpak and RPM use that same Meson install tree. The Flatpak BaseApp cleanup may continue removing WebEngine. `Handbook` is exposed as the `handbook` QML context property; the explicitly named general Handbook entry calls `handbook.showHelp()`. Contextual page help calls `handbook.showTopic(topic)` only when `handbook.hasTopic(topic)` is true. On an individual assignment child page, its footer Help and F1 call `handbook.showTopic("assignment-" + actionType)`.

## Contextual assignment help

Authored page-topic mapping: Buttons → `buttons`; Sensitivity → `sensitivity`; Lighting → `lighting`; Profiles → `profiles`; Advanced → `advanced`. The footer Help and F1 use the same matching topic and availability. A page without an authored match must not display contextual Help or substitute the general handbook. This contract does not imply new or unfinished pages have documentation.

`Handbook.showTopic(str)` accepts only identifiers in `HELP_TOPICS`. The assignment topics are `assignment-button`, `assignment-key`, `assignment-special`, `assignment-macro`, and `assignment-none`; `assignment-write-scope` explains the child page's Help, Reset, Defaults and Apply actions. Existing chapter identifiers, including `buttons`, remain valid. `hasTopic(str)` reports whether that exact authored topic exists. Contextual Help and F1 must use this availability check and the matching topic. Invalid identifiers, filenames and URLs return false without changing or opening the reader; there is no unrelated contents fallback. The API never launches an external browser. Public HTTPS links are a separate explicit click action.

The child's Assignment row selects the action type. For macros, its visual Events panel remains visible, with numbered rows showing each event's fixed type and value together. Each row offers move and delete actions; changing an event requires removing it and adding a replacement. The header Add… popup configures the type and key or delay, then inserts one event only after explicit OK confirmation; selection stays local until then. Direct mouse-button and keyboard-key assignment values use complete per-context searchable native list popups with the same pending-selection and OK contract. OK is disabled without a valid selection; Enter confirms a valid selection. Mouse clicks and arrow keys only select. Cancel, Escape or closing either picker preserves the assignment draft and inserts nothing. G600 offers chord-only Key down/up; supported generic devices also offer Delay. The previous raw-JSON editor is not exposed. Invalid or incomplete sequences keep scoped Apply disabled. The overview recorder retains explicit Stop/Use shortcut/Cancel behavior.

Topic navigation reuses the existing reader window, clears a prior search/selection and scrolls to the chosen local anchor. General `showHelp()` preserves the reading position. Both routes use the same native reader and need no additional dependency or sandbox permission.

The handbook distinguishes the individual assignment transaction from other settings drafts: child Apply submits only that assignment and child Reset discards only its draft. Buttons overview Apply/Revert covers only the selected profile's pending button assignments in both layers, excluding DPI, lighting and other profiles. Quick recording in an overview row stages a draft without writing it. Other page actions are scoped to the selected device/profile: Sensitivity covers DPI stages and polling rate; Lighting covers LEDs; Advanced covers angle snapping, debounce and polling rate; Profiles covers supported name/enabled fields and active-profile selection. None submits pending button drafts. Polling rate is intentionally shared between Sensitivity and Advanced. Full-width Normal/G-Shift tabs only change the view. Navigation with an unsaved child draft requires a decision rather than silently writing it.

## Why this is not KHelpCenter integration

KDE documents F1 and an application Handbook menu entry as the normal way to open offline documentation. `KHelpClient::invokeHelp()` goes further: it starts KHelpCenter and locates documentation via the desktop file's `X-DocPath`. Native KDE handbook distribution conventionally uses DocBook/KDocTools and the documentation install hierarchy.

A Flatpak owns a separate `/app` filesystem. Its exported desktop/icon metadata does not automatically export a private handbook directory into the host's KDE documentation search path. A host KHelpCenter cannot be assumed to resolve this app's sandbox-local handbook. The OpenURI portal is an external-application launch mechanism; using it alone does not establish that the handbook is installed in the receiving application's filesystem.

This release therefore does **not** add an unverified `X-DocPath`, launch `khelpcenter`, rely on host-spawn permissions, or claim host Help Center registration. Its supported help route is the bundled native reader. Actual Flatpak installed-runtime testing remains part of the packaging CI, distinct from source/staged native tests.

## A future native KHelpCenter route

For native distribution packaging, add an authored DocBook handbook and validate it with KDocTools. Install it into the KDE HTML documentation hierarchy under a stable application documentation name, set the native desktop file's matching `X-DocPath`, and test the exact Help/F1 lookup with KHelpCenter installed. Retain the in-app reader as the Flatpak route until a supported, tested document-delivery and viewer-discovery flow exists. Do not add broad host/filesystem/session-bus access just to open help.

The standalone HTML in this release is not presented as a compiled DocBook bundle or an automatically published docs.kde.org handbook. This independent project does not imply KDE project membership or endorsement.

## Official references

- [KDE user documentation convention](https://kde.org/support/)
- [KHelpClient API and X-DocPath lookup](https://api-staging.kde.org/khelpclient.html)
- [KDEInstallDirs6 documentation install directory](https://api.kde.org/ecm/kde-module/KDEInstallDirs6.html)
- [Flatpak desktop integration and portals](https://docs.flatpak.org/en/latest/desktop-integration.html)
- [Flatpak filesystem/export conventions](https://docs.flatpak.org/en/latest/conventions.html)
- [Qt QTextBrowser API](https://doc.qt.io/qt-6/qtextbrowser.html)

Sources checked on 2026-10-12. This page records the implementation boundary; it is not a claim that host KHelpCenter has been tested from this Flatpak.
