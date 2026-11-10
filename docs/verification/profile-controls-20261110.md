# Profile slots and inline help refinement

Verified on 2026-11-10. These changes refine the locally installed 0.1.3 source;
they do not change the profile-file format, backend writes or release channel.

## Controls

The on-device slots selector is a native Qt Quick Controls `ItemDelegate` list,
using KDE's desktop delegate background, hover and selected state. It replaces
radio delegates: selecting a slot chooses the editor target, not the active
hardware profile. Active and disabled state appear separately at the row's end.
The list exposes list/list-item accessibility roles and selected state, supports
Up/Down/Home/End, and shares the page's scrolling. Existing Make active, Apply,
Reset and draft guards are unchanged.

Advanced uses Kirigami's `ContextualHelpButton` beside each related field. The
native help control is reused on the other settings pages. Unsupported fields
retain enabled explanatory help. Escape, repeated click, focus dismissal and
navigation dismissal are covered.

## Verification

- Slots tests exercise actual Qt mouse/keyboard input, selected versus active
  state, accessibility, blocked busy input, disabled slots, preserved drafts,
  header selection synchronization, and 960/1280-pixel windows with 11/14-point
  fonts in light and dark themes.
- Inline help tests cover both device fixtures, both themes, both widths and both
  fonts. Private KWin Wayland verification drove 91 Qt inputs and 16 geometry
  cases at 14 points, with zero QML warnings and zero transport writes.
- A second private Wayland run used the actual G600 through a D-Bus guard that
  accepts only GetAll and AddMatch. All 3 slots were visible, selecting a
  non-active slot left activation and every draft unchanged, and both Advanced
  info controls were vertically aligned within 0.5 pixels. There were 146
  read/match calls and zero hardware writes. The production palette retained
  the user's KDE window color and accent. Captures were visually inspected.
- Both new test modules are explicitly required by Flatpak and Fedora package
  checks. Full package results are recorded with the resulting local bundle;
  this source report does not claim publication or an installation.

Evidence is retained locally with the profile-refinement and Advanced-verification
artifacts. Real-device screenshots are private verification evidence, not release
artwork. No public push or release is part of this refinement.
