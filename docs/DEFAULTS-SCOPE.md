<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

# G600 assignment Defaults: supported scope

This is a feasibility assessment, not an implemented factory-reset feature.
A documented binding can become a **local assignment draft** through the
existing captured-context API. Only a later, explicit Apply may submit it.
This is separate from restoring an entire device or profile to factory state.

## Required enablement behavior

Defaults is enabled only when authoritative, supported defaults exist for the
**entire current scope** and the current draft differs semantically from them.
Equivalent normalized assignments keep it disabled. A profile name, slot number,
or dirty flag is not evidence of either a default value or a difference.
Defaults stages only the current scope; Revert restores that scope's observed
baseline, preserving unrelated drafts. Apply remains explicit.

Whole-profile Defaults additionally requires a complete known restoration for
all fields in that scope. The preset constants and this behavior are **not
implemented**: unavailable Defaults controls must remain disabled. The feasible
subset below is not permission to enable them wholesale.

## Identify the intended factory mode first

Require explicit selection of the intended factory preset, or independently
verified provenance. Current assignments, LED color, or ratbag slots 0/1/2 do
not establish original factory-mode identity: the three modes are editable.
[Logitech guide, p. 5][guide]

The destination must separately be a valid captured device/profile/button
context. Mode selection identifies the source preset, not a different write
destination.

## Documented assignment subset

These facts come from the official guide, English pp. 5–7. “Encodable” means
supported by the backend and referenced driver, not verified hardware state.
[Source][guide]

| Factory mode / layer | Physical controls and documented bindings | Assessment |
| --- | --- | --- |
| All modes, normal | Left/right click, wheel click, wheel left/right → mouse buttons 1/2/3/4/5; G8 → cycle mode | Encodable |
| Modes 1–2, normal | Ring button → G-Shift; G7 → Shift+B | Encodable |
| Mode 1, normal | G9–G20 → 1,2,3,4,5,6,7,8,9,0,-,= | Encodable |
| Mode 1, shifted | G9–G20 → Ctrl plus the preceding keys | Encodable |
| Mode 2, normal | G9–G20 → keypad 1,2,3,4,5,6,7,8,9,0,-,+ | Encodable |
| Mode 2, shifted | G9–G20 → Ctrl plus the preceding keypad keys | Encodable |
| Mode 3, normal | G7 → DPI cycle; G9–G14 → 1–6; G15 → DPI up; G17 → mouse button 5; G18 → DPI down; G19 → E; G20 → mouse button 4 | Encodable |
| Mode 3, normal | Ring button → DPI shift, documented target 400 DPI | Function encodable; target cannot be restored by this assignment API |
| Mode 3, normal | G16 → Default DPI | Unsupported by the referenced driver mapping |
| Modes 1–2, shifted top controls; Mode 3, shifted bank | Factory bindings not specified in these guide pages | No preset; do not infer |

Modes 1/2 each provide 20 normal and 12 shifted encodable assignments. Mode 3
provides 18 normal assignments, one function-only binding, and one unsupported
binding. These are not complete profile-restoration recipes.

## Encoding and target boundaries

- Editable raw indices are normal **0–19** and G-Shift **21–40**. Raw **20** is
  a color buffer and must never be an assignment target. Shifted physical index
  is `raw index - 21`; physical thumb controls G9–G20 occupy indices 8–19
  (shifted raw 29–40). Keep raw indices distinct from printed G-button names.
  [Driver layout][layout], [Piper diagram](../data/svgs/logitech-g600.svg)
- G600 action types are `none`, `button`, `special`, and `macro`. Mouse-button
  assignments support values 1–5. Keyboard presets use balanced one-key macros
  with optional modifiers, not the direct `key` action or timed sequences.
  [Driver action support][actions], [keyboard encoding][encoding]
- Supported special values are `(1 << 30)` plus 7 (DPI cycle), 9 (DPI up),
  10 (DPI down), 11 (DPI shift), 13 (profile cycle), or 17 (G-Shift).
  Default DPI, offset 12, is not a substitute for DPI shift or DPI cycle.
  [Driver mapping][mapping], [backend constants](../qt_piper/backend.py)
- `validateMapping(context, type, value)` checks without mutation.
  `stageMapping` changes only that assignment's local draft; child
  `applyMapping` submits only its Mapping operation. Assignment Defaults must
  not stage sensitivity, LED, profile activation, or other assignments.

No complete factory image is available. Unknown shifted bindings, the separate
shift-DPI target, independent shifted LED settings, and unexposed fields must
not be invented. DPI and lighting controls belong to separate scopes.

## Commit is broader than an assignment setter

The adapter can send one Mapping setter followed by one target-device Commit.
It preflights known-clean daemon profiles and the expected target value, keeps
unrelated local drafts, and reports submission rather than verified hardware
success. Another client can still race between preflight and Commit; ratbagd
provides no transaction lock for this operation.

Upstream G600 Commit writes each dirty profile as a complete report. Its writer
also replaces the separate shifted LED color with the main LED color on every
profile write. Therefore a scoped assignment Apply cannot promise a byte-level
single-field hardware change or preservation of an independent shifted color.
[Profile serialization and shifted-color copy][writer], [Commit loop][commit]

## Evidence and limits

The keyboard forms above passed the G600 macro validator. The backend passes
98 hardware-free tests, including private-D-Bus tests. No hardware restoration
or distribution-specific patched driver was tested.

Driver references are pinned to libratbag **v0.18**, commit
`9f4789f8746188a75cd3090e94adf984f0ac4cc6`. The existing backend retains the
upstream license notice for its derived HID key-code table. This document
summarizes factual behavior and does not copy driver implementation code.

[guide]: https://www.logitech.com/assets/44964/g600-mmo-gaming-mouse-quickstart-guide.pdf#page=5
[layout]: https://github.com/libratbag/libratbag/blob/9f4789f8746188a75cd3090e94adf984f0ac4cc6/src/driver-logitech-g600.c#L36-L78
[actions]: https://github.com/libratbag/libratbag/blob/9f4789f8746188a75cd3090e94adf984f0ac4cc6/src/driver-logitech-g600.c#L296-L314
[mapping]: https://github.com/libratbag/libratbag/blob/9f4789f8746188a75cd3090e94adf984f0ac4cc6/src/driver-logitech-g600.c#L105-L118
[encoding]: https://github.com/libratbag/libratbag/blob/9f4789f8746188a75cd3090e94adf984f0ac4cc6/src/driver-logitech-g600.c#L516-L530
[writer]: https://github.com/libratbag/libratbag/blob/9f4789f8746188a75cd3090e94adf984f0ac4cc6/src/driver-logitech-g600.c#L475-L575
[commit]: https://github.com/libratbag/libratbag/blob/9f4789f8746188a75cd3090e94adf984f0ac4cc6/src/driver-logitech-g600.c#L593-L612
