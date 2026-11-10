# ratbagd idle reconnection

## Reproduced before implementation

The pre-fix installed Flatpak and source checkout had the same backend SHA-256:
`ab95cfc1c4acd70b7490f4c4c316fa0ee7b78908ecb016374641541fb3babd61`.

The real Fedora ratbagd 0.18-5.fc44 was observed without stopping or restarting it manually and without sending any device writes. The installed Piper backend ran in a QCoreApplication event loop; this was a model-level observation, not a visible-window test. A guard allowed only D-Bus `AddMatch` and property `GetAll` calls.

On 2026-11-10, all times UTC:

- 03:11:05: installed backend connected successfully.
- 03:13:16: last property snapshot completed after an external property change.
- 03:33:44: ratbagd logged `Exiting after idle` and systemd recorded a clean deactivation. D-Bus emitted `NameOwnerChanged` with an empty new owner.
- 03:33:44: Piper changed to `connected=false`, status `Disconnected`, while its D-Bus connection remained connected.
- 03:34:14: it was still disconnected after 30 seconds with no automatic read attempt.
- 03:34:14: a manual Refresh immediately activated a new ratbagd process and restored the connection.

This agrees with [libratbag v0.18's exit-on-idle implementation](https://github.com/libratbag/libratbag/blob/v0.18/ratbagd/ratbagd.c#L467-L526): ratbagd intentionally exits after 20 idle minutes and expects the next client request to activate it. The daemon's timer has one-minute accuracy. Piper listened for a returning owner, but never issued the read that would cause it to return.

A separate private-D-Bus reproducer used synthetic devices and a shortened idle deadline. It reproduced the same stuck state and proved that a manual read restored the connection while retaining a local polling-rate draft. No physical devices or system bus were used by that reproducer.

The regression was added before the production fix in commit `622abdb`. Its automatic reactivation assertion failed on the unchanged backend with the observed `Disconnected` state. All 98 pre-existing backend tests passed on that same implementation.

## Fix and safety boundaries

- On disconnection or a failed refresh, retry only a read-only snapshot. The next read allows D-Bus activation to restart ratbagd.
- Retry delays are 1, 2, 4, 8, 16, then at most 30 seconds while unavailable. Stop retrying after a successful snapshot or when the backend closes.
- Keep local drafts and partial-Apply safeguards. Never replay Apply, Set, or Commit automatically.
- Clear stale Disconnected status after recovery, including when a draft remains dirty.
- Tag asynchronous operations with a disconnect generation. A stale successful read or Apply result cannot cancel recovery from a newer loss; uncertain writes remain guarded and are not replayed.
- Mock disconnects remain under explicit test/demo control.

## Verification

- 104 backend and reconnect tests passed, including two consecutive private-service idle exits and automatic reactivations, zero Set/Commit calls, draft retention, capped backoff, shutdown cleanup, and preservation of partial-write guards, and loss-before-result ordering for reads and Apply.
- Another 17 diagram, handbook, recorder, and desktop-style tests passed, plus 1,434 SVG subtests.
- Black and Ruff passed for the changed Python files; `git diff --check` passed.
- The Flatpak build test list includes the new reconnect regression.
- The current Kirigami footer and error-recovery QML scenarios passed with synthetic devices and no QML warnings.
- Independent safety review reproduced the stale-result race before the generation guard and verified recovery afterward, with no remaining actionable findings.

## Natural post-fix verification

The fixed source backend (SHA-256 `55ef6ac7ff078c54cf2ed5943db3bae9d88d8ac0803cb05c200930c70ddaa933`) was then observed against the same real system ratbagd, again with a QCoreApplication event loop and a guard permitting only AddMatch/GetAll:

- 03:40:00 UTC: connected and completed the initial read-only snapshot.
- 04:00:44 UTC: after 20 minutes 44 seconds without client reads, the real daemon exited cleanly and relinquished its D-Bus name. The bus connection itself remained alive.
- 04:00:45 UTC: Piper's automatic retry activated ratbagd and restored connected status with no error. Recovery took **1.146 seconds**, without a manual Refresh.
- The whole run issued 286 GetAll calls and three AddMatch calls, with **zero device writes**. The observer exited successfully after recovery.

The pre-fix natural failure used installed Flatpak code; the post-fix natural success used the corrected source backend on the host. Both were model/event-loop observations rather than visible-window idle tests. The current QML recovery/footer checks used synthetic devices. These results do not themselves establish a rebuilt or installed package. No mouse settings were changed during either real-daemon observation.
