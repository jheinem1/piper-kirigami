# KDE HIG review

This is a focused review of the prototype, not certification of complete HIG or accessibility compliance. It uses the official [KDE HIG](https://develop.kde.org/hig/) and the public components used by System Settings. The executable-local System Settings shell is not embedded.

## Corrections included

- Header device/profile ComboBoxes use the native flat property, matching the public KWin decoration settings selector. No custom border or hardcoded background is applied.
- Navigation delegates use native implicit sizing instead of fixed pixel/grid-unit heights. Indented search results use the same native row height and remain single-line.
- Normal production startup preserves the platform font, style and palette. Explicit preview overrides remain available. An isolated test verifies preservation of a 14-point font and a changing system palette.
- Mapping inputs, stage controls and diagram targets have descriptive accessible names. Keyboard activation includes Return and keypad Enter. Diagram actions use the normal pointer cursor.
- Macro events use a bounded full-width view beneath the compact form, with a native InlineViewHeader and Add… action. Value selection uses a searchable native dialog; cancellation leaves drafts unchanged.
- Assignment editing uses an in-window child page with native Kirigami.FormLayout label/control columns, content-sized assignment selectors, scrollable content and fixed scoped actions. Quick shortcut recording remains in the main assignment row.
- A reopened named-key picker stays synchronized with its Linux keycode.
- Dismissing an error clears its state without breaking the binding that shows later errors. LED validation messages reset correctly after previous failures.
- Settings are staged until Apply; Reset discards drafts. Footer Help opens the working offline handbook. Closing during Apply is blocked. Unsupported factory restoration is not invented: Defaults is visibly disabled with an explanation until safe restoration is implemented.
- Offline help is available from the menu and F1, with contents, search and standard Close behavior. It documents the distinction between local drafts, daemon writes and unverified physical persistence.

## Guidance and interpretation

[Accessibility](https://develop.kde.org/hig/accessibility/) calls for keyboard access, intelligible accessible labels and testing larger text. [Error guidance](https://develop.kde.org/hig/status_changes/#errors-and-failures) requires failures to remain visible and understandable. [Customization guidance](https://develop.kde.org/hig/powerful_when_needed/#customization-increases-reach) supports respecting platform choices. [Spacing](https://develop.kde.org/hig/layout_and_nav/#spacings-and-sizes), [text](https://develop.kde.org/hig/text_and_labels/) and [interaction cues](https://develop.kde.org/hig/getting_input/#signaling-interactivity) inform the metric/cursor corrections.

The Normal/G-Shift control selects an editing view, not the physical mouse's active mode. [Tabbed views](https://develop.kde.org/hig/displaying_content/#tabbed-views) are a natural pattern for related same-level views. The [Switch/CheckBox distinction](https://develop.kde.org/hig/getting_input/) concerns two-state settings; immediate effect alone does not establish that a view selector must be a Switch. The application uses Normal/G-Shift tabs above both affected panes. The choice follows the view-selection semantics; it does not toggle the physical mouse mode.

The split System Settings-like navigation/content structure is deliberate. HIG guidance should inform an application-specific design rather than trigger a new layout solely to resemble an example.

## Remaining boundaries

- Real desktop platform/portal theme behavior, RTL, tablet mode and Orca have not been fully verified.
- Validation occurs on Apply in some editors; continuous validation and broader dialog/page polish remain future work.
- Frontend Apply scopes are explicit: one child assignment, selected-profile assignment drafts, or the current settings page. ratbagd Commit remains device-wide, so concurrent external-client races cannot be eliminated by frontend scoping.
- Existing GTK translations have not been migrated. The prototype is English-only.
- Host KHelpCenter registration, saved-profile library/import/export, physical mouse behavior and firmware persistence are not established by this review.

## Child-page reference patterns

The public [Keyboard Layouts page](https://github.com/KDE/plasma-desktop/blob/master/kcms/keyboard/ui/main.qml#L249-L258) separates its compact form from a full-width list and InlineViewHeader. Its [LayoutDelegate](https://github.com/KDE/plasma-desktop/blob/master/kcms/keyboard/ui/LayoutDelegate.qml) provides the native row/action reference. [Lists and grids](https://develop.kde.org/hig/displaying_content/#lists-and-grids) specifies placing creation actions in an InlineViewHeader; it does not prescribe whether new-item values must be entered before or after opening an add flow. The chosen Add… picker avoids empty placeholder events. The [ellipsis guidance](https://develop.kde.org/hig/text_and_labels/#ellipses) applies because the action needs another choice.

The focused audit found and corrected keyboard focus loss after event reordering, including repeated movement and boundary behavior, and added focus-driven scrolling for delay controls. Real Qt event tests, responsive screenshots and accessible names provide evidence for these behaviors; they are not substitutes for full screen-reader, RTL or touch testing.

## Ordered-list and picker checks

The order-sensitive [KWin Window Rules editor](https://github.com/KDE/kwin/blob/master/src/kcms/rules/ui/main.qml#L134-L235) is another native reference. Visible move actions with disabled boundaries are retained for keyboard access; drag handles and overflow menus are optional application conventions, not HIG mandates. Event rows have plain names at the left and move/remove controls at the right, with semantic alternating View backgrounds.

The final searchable picker reserves one native large-spacing content inset and a separate scrollbar gutter below its fixed search/type controls. Geometry was checked at 11pt and actual 14pt in a 960×700 window, including initially revealing distant current values. This corrects a real overlap observed in an earlier preview; those superseded screenshots are not verification of the final popup. Selected values receive native selection styling and bold text.

The final event rows are intentionally immutable: their plain left labels retain type and value, while only move/remove actions remain at the right. Add… opens an outlined list picker with explicit OK/Cancel; selection is local until OK. This is the chosen interaction model, not an assertion that HIG requires immutable events.

A focused review of Sensitivity, Lighting, Profiles and Advanced retained their current designs. A small Lighting defect was corrected: malformed color/duration input now produces reactive feedback and disables Save before staging. Four settings groups then passed 251 real inputs with zero QML warnings on the updated LED dialog. Wider page redesign remains separate work.
