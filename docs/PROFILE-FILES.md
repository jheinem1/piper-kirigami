# Named JSON profiles

The Profiles page lists every on-device slot reported by ratbagd. Selecting a
slot does not activate it or write to the mouse. “Make active” is a separate
pending change that requires Apply.

## Save and load

- **Save to File** exports the selected slot's effective settings, including
  pending local edits. The file's name is independent of the on-device name.
- **Load from File** validates the entire file against the selected device and
  slot, then shows a review. Cancel and Escape do not change settings.
- **Load as pending changes** replaces the target slot's editable content in
  the local draft. Its on-device name, enabled state and active state stay as
  they were. Other slots and devices are unchanged.
- **Apply** on Profiles writes the imported changes and pending slot-management
  changes through the existing guarded scoped Apply. Unrelated pending changes
  remain pending. **Reset** discards the same scope without writing.
- Loading replaces any earlier draft changes to settings carried in the file.
  Review the load dialog before accepting. The file's active/default *DPI stage*
  is part of its content; that is distinct from activating a *profile slot*.
- Saving and loading files never issue ratbagd writes. On real hardware, Apply
  reports a submission to ratbagd, not a claim of hardware verification.

## Version 1 contract

The root has exactly `format`, `version`, `name`, `device`, and `profile`.
`format` is `org.freedesktop.piper.profile`; `version` is integer `1`.
`name` is a nonempty label of at most 255 UTF-8 bytes without control characters.
`device` contains only `model`, which must match the target's ratbagd model ID.

`profile` has exactly these collections:

- `settings`: supported `reportRate`, `angleSnapping`, and `debounce` fields.
  Unsupported fields must be absent, not zeroed or silently ignored.
- `resolutions`: one record per reported DPI stage with `index`, `x`, `y`,
  `active`, and `default`; `enabled` is present only when stage disabling is
  supported. Exactly one enabled active and one enabled default stage is needed.
- `buttons`: one record per exposed button with `index`, `physicalIndex`,
  `layer`, and `action`. The action contains `type` and `value` in Piper's
  ratbagd representation. Both G600 layers are included: normal raw indices
  0–19, G-Shift raw indices 21–40. Reserved index 20 is never exported or loaded.
- `leds`: one record per zone with `index`, `mode`, and `effectDuration`;
  `color` is three integer RGB channels when editable color is supported;
  `brightness` is included only when writable. In particular G600 brightness is
  absent and its duration is constrained to whole seconds from 0–15000 ms.

Array ordering does not determine destination: each index and button-layer
identity is checked against the current slot. All counts must match. Supported
DPI/rate/debounce lists and assignment/LED capabilities are checked against the
live model. G600 keyboard shortcuts must be exactly representable, including
modifier-only shortcuts' reserved zero key pair. Timed/multi-key sequences,
unknown actions, coerced numeric types, and lossy LED colors are rejected.

Unknown fields, wrong versions/models, duplicate JSON keys or indices,
non-finite numbers, malformed UTF-8, excessive file size (>1 MiB), remote URLs,
and nonregular input files are rejected. A rejected file leaves the draft
unchanged. Export also validates, so unsupported daemon values cannot become
misleading files that change semantics when loaded later.

## Safety and compatibility

Validation builds an isolated candidate, never mutating the live draft. The
review freezes that candidate in memory. A changed selection, connection or
slot draft invalidates the review; the file is not re-read after approval.

Saving uses a same-directory temporary file and atomic publication. Replacement
requires Save dialog confirmation. If a selected location (including a restricted
document-portal grant) does not permit atomic saving, Piper reports an error and
leaves an existing file untouched. It does not fall back to truncating the target
or request broad filesystem access. Atomic overwrite and readback through a
read/write-only document-portal grant were verified in the installed Flatpak runtime using a synthetic JSON file. The
grant covered that test file only; no broad filesystem permission was added.

The hardware-free tests cover schema validation, safe I/O, exact roundtrips,
preview cancellation/staleness, G600 restrictions, scoped Apply/Reset, and the
real D-Bus adapter against an isolated fake daemon. The standalone native UI test
covers all slots, file-dialog cancel, review cancel, staging and reset.
