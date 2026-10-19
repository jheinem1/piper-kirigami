# Bounded KDE design workshop proposal

This local proposal builds on `51b0b89` and retains the approved Buttons sidebar,
indented persistent search, single-column assignment rows, full-width Normal /
G-Shift tabs, toolbar divider and 1050 × 700 opening size. The installed desktop
application is unchanged. Help Center integration remains a separate proposal.

## Assignment editor

Keep the existing child page: the event editor needs the available window space,
and its Help, Reset and Apply already have an explicit single-assignment scope.
Keep the native searchable value picker, pending selection and OK / Cancel flow.
These existing choices follow KDE's guidance on child pages, standard controls,
large choice lists and inline validation.

For G600, name the restricted macro type **Keyboard shortcut** and show a live
readable summary, such as **Left Shift + 1**, above the detailed events. A short
hint explains the one-key-with-modifiers restriction. Other devices retain
**Macro** and show the event count. Validation and the event payload are unchanged.

Packaged-runtime review also caught stale pale alternating-row fills after a
light-to-dark transition, despite correct palette values. Keep the native row
hover and focus painting without alternate fills. Verify actual background
pixels against text colors after palette transitions, rather than checking only
palette properties.

## Remaining settings pages

Use the toolbar page title once. Remove the repeated Lighting zones, DPI stages,
Device settings and On-device profiles headings from the content area. Keep
Stage 1–4, field labels, zone counts and the assignment Events header because
they identify distinct groups. The DPI group retains its accessible name, and
the Profiles form retains its on-device scope in accessible and visible text.

- **Sensitivity:** retain the native DPI-stage controls and polling-rate selector.
  A next proposal should improve precise entry through long supported-value
  menus while preserving the device's allowed DPI values and steps.
- **Lighting:** retain the native outlined editor, **OK** confirmation and
  validation. The popup has no explanatory paragraph. OK still keeps a draft;
  the page's **Apply** submits it. Color-picker, keyboard-confirmation and
  effect-relevance gaps remain separate review items.
- **Profiles:** retain the compact native form and capability-filtered controls.
  Review pending-activation wording: Make active currently changes the displayed
  status before Apply submits it. Selected-for-editing and active-on-device
  states should be distinguishable.
- **Advanced:** retain the native form and unsupported-feature explanation.
  Review contextual help for technical settings, make generic unsupported hints
  conditional, and clarify that polling rate is shared with Sensitivity.

These remaining-page recommendations are review directions, not implemented
redesigns. The current change removes repeated headings and preserves controls.

No backend, device protocol, profile persistence or device-write scope changes.
Native preview screenshots use deterministic demo devices, with no hardware
access. Review both the editor and Lighting confirmation before approving an
installation; the preview package is a local review artifact, not a release.

## References

- [KDE: getting input](https://develop.kde.org/hig/getting_input/)
- [KDE: displaying content](https://develop.kde.org/hig/displaying_content/)
- [KDE: layout and navigation](https://develop.kde.org/hig/layout_and_nav/)
- [KDE: text and labels](https://develop.kde.org/hig/text_and_labels/)
- [Plasma Mouse settings: native numeric-entry and contextual-help patterns](https://raw.githubusercontent.com/KDE/plasma-desktop/master/kcms/mouse/ui/main.qml)

Guidance and native previews reviewed on 2026-10-19. Detailed capture and test
results accompany the local workshop artifact, outside the source repository.
