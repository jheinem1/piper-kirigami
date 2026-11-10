# SPDX-License-Identifier: GPL-2.0-or-later
"""Hardware-free file, atomic import and scoped apply/reset coverage."""

from copy import deepcopy
import json
import os
import time

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication

from qt_piper.backend import Backend, build_operations
from qt_piper import profile_files


@pytest.fixture(scope="module")
def app():
    return QGuiApplication.instance() or QGuiApplication([])


def wait_for(app, condition):
    end = time.monotonic() + 4
    while not condition():
        assert time.monotonic() < end
        app.processEvents()
        time.sleep(0.002)
    app.processEvents()


@pytest.fixture
def backend(app):
    backend = Backend(mock=True, fixture="all")
    wait_for(app, lambda: backend.connected and not backend.busy)
    yield backend
    backend.close()


def document(backend, name="Named file, not a slot"):
    return profile_files.export_document(
        backend._device(), backend._profile(), name, backend._set_mapping
    )


def save(tmp_path, value):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return str(path)


def inspect(backend, path):
    return backend.inspectProfileFile(path, backend.capturePageContext("profiles"))


def stage(backend, path):
    preview = inspect(backend, path)
    assert preview, backend.error
    assert backend.importProfileFile(preview["token"]), backend.error
    return preview


@pytest.mark.parametrize("device_index", [0, 1])
def test_roundtrip_effective_draft_without_transport_writes(
    backend, tmp_path, device_index
):
    backend.selectDevice(device_index)
    backend.setReportRate(500)
    backend.setDpi(0, 1200, 1200)
    backend.setLed(0, "color", "#123456")
    backend.setButtonMapping(0, "button", 5)
    if device_index == 0:
        backend.setButtonMapping(21, "macro", [[1, 29], [1, 30], [2, 30], [2, 29]])
    else:
        backend.setAngleSnapping(1)
        backend.setDebounce(8)
        backend.setResolutionActive(0)
        backend.setResolutionDefault(0)
        backend.setResolutionEnabled(3, False)
    expected = document(backend)
    path = tmp_path / "A profile #with spaces.json"
    before = deepcopy(backend._draft)
    context = backend.capturePageContext("profiles")
    assert backend.exportProfileFile(
        QUrl.fromLocalFile(str(path)).toString(), expected["name"], context, False
    )
    assert json.loads(path.read_text()) == expected
    assert backend._draft == before
    assert not backend._transport.calls
    assert not backend.exportProfileFile(str(path), "Overwrite denied", context, False)
    assert json.loads(path.read_text()) == expected
    backend.selectProfile(1)
    original_slot = deepcopy(backend.selectedProfile)
    before = deepcopy(backend._draft)
    preview = inspect(backend, str(path))
    assert backend._draft == before and not backend.profileImportPending
    assert preview["gshiftButtons"] == (20 if device_index == 0 else 0)
    assert backend.importProfileFile(preview["token"])
    assert document(backend) == expected
    for key in ("rawName", "name", "active", "isActive", "enabled", "disabled"):
        assert backend.selectedProfile[key] == original_slot[key]
    assert (
        backend._draft[device_index]["profiles"][0]
        == before[device_index]["profiles"][0]
    )
    assert not backend._transport.calls
    assert backend.profileFileName == expected["name"]
    assert backend.profileImportPending


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda d: d.update(version=2), "version"),
        (lambda d: d.update(version=True), "version"),
        (lambda d: d.update(format="unknown"), "Piper"),
        (lambda d: d.update(unknown=True), "exactly"),
        (lambda d: d.update(name=""), "name"),
        (lambda d: d.update(name="line\nbreak"), "name"),
        (lambda d: d["device"].update(model="usb:other"), "model"),
        (lambda d: d["profile"].update(name="unsafe slot name"), "exactly"),
        (lambda d: d["profile"].update(active=True), "exactly"),
        (lambda d: d["profile"]["settings"].update(reportRate=700), "reportRate"),
        (lambda d: d["profile"]["settings"].update(reportRate=True), "integer"),
        (lambda d: d["profile"]["settings"].update(angleSnapping=1), "exactly"),
        (lambda d: d["profile"]["resolutions"][0].update(x=813), "DPI"),
        (lambda d: d["profile"]["resolutions"][0].update(x=800), "axes"),
        (lambda d: d["profile"]["resolutions"][0].update(active=True), "exactly one"),
        (lambda d: d["profile"]["resolutions"][1].update(default=False), "exactly one"),
        (lambda d: d["profile"]["resolutions"][0].update(enabled=False), "exactly"),
        (lambda d: d["profile"]["buttons"].pop(), "count"),
        (lambda d: d["profile"]["buttons"][1].update(index=0), "Duplicate"),
        (lambda d: d["profile"]["buttons"][0].update(index=20), "indices"),
        (lambda d: d["profile"]["buttons"][20].update(layer="normal"), "layer"),
        (lambda d: d["profile"]["buttons"][20].update(physicalIndex=1), "physical"),
        (
            lambda d: d["profile"]["buttons"][0]["action"].update(type="key", value=30),
            "unsupported",
        ),
        (lambda d: d["profile"]["buttons"][0]["action"].update(value=6), "1–5"),
        (lambda d: d["profile"]["buttons"][0]["action"].update(value=1.0), "integer"),
        (
            lambda d: d["profile"]["buttons"][0]["action"].update(type="none", value=1),
            "value 0",
        ),
        (
            lambda d: d["profile"]["buttons"][0]["action"].update(
                type="special", value=(1 << 30) + 18
            ),
            "special",
        ),
        (
            lambda d: d["profile"]["buttons"][0]["action"].update(
                type="macro", value=[[1, 30], [3, 10], [2, 30]]
            ),
            "G600",
        ),
        (
            lambda d: d["profile"]["buttons"][0]["action"].update(
                type="macro", value=[[1, 29], [2, 29]]
            ),
            "exactly",
        ),
        (
            lambda d: d["profile"]["buttons"][0]["action"].update(
                type="macro", value=[[True, 30], [2, 30]]
            ),
            "integer",
        ),
        (lambda d: d["profile"]["leds"][0].update(mode=40), "mode"),
        (lambda d: d["profile"]["leds"][0].update(color=[-1, 0, 0]), "RGB"),
        (lambda d: d["profile"]["leds"][0].update(brightness=125), "exactly"),
        (lambda d: d["profile"]["leds"][0].update(effectDuration=1234), "exactly"),
        (lambda d: d["profile"]["leds"][0].update(effectDuration=16000), "duration"),
    ],
)
def test_malformed_or_unsupported_import_is_atomic(backend, tmp_path, mutate, match):
    content = document(backend)
    # A valid early change must never partially stage if a later field is wrong.
    content["profile"]["settings"]["reportRate"] = 500
    mutate(content)
    before = deepcopy(backend._draft)
    assert not inspect(backend, save(tmp_path, content))
    assert match in backend.error
    assert backend._draft == before
    assert not backend.dirty and not backend.profileImportPending
    assert not backend._transport.calls


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"\xff",
        b'{"version":1,"version":1}',
        b'{"version":NaN}',
        b"[" * 2000 + b"]" * 2000,
        b" " * (profile_files.MAX_FILE_BYTES + 1),
    ],
)
def test_invalid_file_bytes(backend, tmp_path, body):
    path = tmp_path / "bad.json"
    path.write_bytes(body)
    assert not inspect(backend, str(path))
    assert not backend.dirty and not backend._transport.calls


def test_safe_local_paths_and_atomic_write(tmp_path):
    for path in (
        "https://example.com/p.json",
        "file://other-host/a.json",
        "relative.json",
        "file:///tmp/a.json?x=1",
    ):
        with pytest.raises(ValueError):
            profile_files.local_path(path)
    target = tmp_path / "profile.json"
    profile_files.write_document(str(target), {"one": 1})
    before = target.read_bytes()
    with pytest.raises(ValueError):
        profile_files.write_document(str(target), {"two": 2})
    assert target.read_bytes() == before
    profile_files.write_document(str(target), {"two": 2}, True)
    assert profile_files.read_document(str(target)) == {"two": 2}
    assert not list(tmp_path.glob(".piper-profile-*"))
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(OSError):
        profile_files.read_document(str(link))
    with pytest.raises(ValueError):
        profile_files.write_document(str(link), {}, True)
    pipe = tmp_path / "pipe.json"
    os.mkfifo(pipe)
    with pytest.raises(ValueError):
        profile_files.read_document(str(pipe))


def test_preview_cancel_stale_target_and_stale_draft(backend, tmp_path):
    content = document(backend)
    content["profile"]["settings"]["reportRate"] = 500
    path = save(tmp_path, content)
    preview = inspect(backend, path)
    backend.cancelProfileImport(preview["token"])
    assert not backend.importProfileFile(preview["token"])
    preview = inspect(backend, path)
    backend.selectProfile(1)
    assert not backend.importProfileFile(preview["token"])
    assert not backend.dirty
    preview = inspect(backend, path)
    backend.setDpi(0, 800, 800)
    before = deepcopy(backend._draft)
    assert not backend.importProfileFile(preview["token"])
    assert backend._draft == before
    preview = inspect(backend, path)
    backend._on_event("disconnected")
    assert not backend.importProfileFile(preview["token"])
    assert backend._draft == before
    assert not backend._transport.calls


def test_preview_is_immutable_and_busy_and_partial_are_guarded(backend, tmp_path):
    content = document(backend)
    content["profile"]["settings"]["reportRate"] = 500
    path = save(tmp_path, content)
    preview = inspect(backend, path)
    save(tmp_path, {"malicious": True})
    backend._busy = True
    assert not backend.importProfileFile(preview["token"])
    backend._busy = False
    assert backend.importProfileFile(preview["token"])
    assert backend.selectedProfile["reportRate"] == 500
    assert not backend.importProfileFile(preview["token"])
    backend._partial_apply = True
    assert not inspect(backend, path)
    assert "pending" in backend.error
    assert not backend._transport.calls


def test_import_apply_scope_preserves_other_drafts(backend, app, tmp_path):
    content = document(backend)
    content["profile"]["settings"]["reportRate"] = 500
    content["profile"]["buttons"][20]["action"]["value"] = 5
    content["profile"]["leds"][0]["color"] = [10, 20, 30]
    backend.selectProfile(1)
    backend.setDpi(0, 800, 800)
    backend.selectDevice(1)
    backend.setProfileName("Other device")
    backend.selectDevice(0)
    stage(backend, save(tmp_path, content))
    # A newer edit outside imported fields is not owned by Profiles Apply.
    backend.setDpi(0, 1200, 1200)
    context = backend.capturePageContext("profiles")
    assert backend.pageDirty(context)
    assert backend.applyPage(context)
    wait_for(app, lambda: not backend.busy)
    assert {op.member for op in backend._transport.calls} == {
        "ReportRate",
        "Mapping",
        "Color",
    }
    assert {op.path for op in backend._transport.calls} <= {
        backend.selectedProfile["path"],
        backend.selectedProfile["buttons"][20]["path"],
        backend.selectedProfile["leds"][0]["path"],
    }
    assert not backend.profileImportPending and not backend.pageDirty(context)
    assert backend.selectedProfile["resolutions"][0]["x"] == 1200
    assert backend.profiles[1]["resolutions"][0]["x"] == 800
    assert backend.devices[1]["profiles"][0]["name"] == "Other device"
    assert backend.dirty
    backend.setReportRate(125)
    assert not backend.pageDirty(context), "Applied import must not claim future edits"


def test_import_reset_scope_and_child_reset(backend, tmp_path):
    content = document(backend)
    content["profile"]["settings"]["reportRate"] = 500
    content["profile"]["buttons"][20]["action"]["value"] = 5
    stage(backend, save(tmp_path, content))
    backend.setLed(0, "color", "#112233")
    context = backend.capturePageContext("profiles")
    assert backend.resetPage(context)
    assert backend.selectedProfile["reportRate"] == 1000
    assert backend.selectedProfile["buttons"][20]["actionValue"] == 1
    assert backend.selectedProfile["leds"][0]["color"] == "#112233"
    assert not backend.profileImportPending
    backend.reset()
    stage(backend, save(tmp_path, content))
    assert backend.resetPage(backend.capturePageContext("sensitivity"))
    assert backend.profileImportPending
    assert backend.resetMappings(backend.captureMappingContexts())
    # Resetting the last imported field via another page also clears ownership.
    assert not backend.pageDirty(context)
    assert not backend.profileImportPending
    assert not backend._transport.calls


def test_import_capabilities_rechecked_and_export_rejects_unrepresentable(
    backend, tmp_path
):
    content = document(backend)
    backend._profile()["reportRates"] = [125]
    assert not inspect(backend, save(tmp_path, content))
    assert not backend.dirty
    backend._profile()["reportRates"] = [125, 1000]
    backend._profile()["leds"][0]["effectDuration"] = 1234
    path = tmp_path / "export.json"
    assert not backend.exportProfileFile(
        str(path), "Unsafe", backend.capturePageContext("profiles"), False
    )
    assert not path.exists()
    assert not backend._transport.calls


def test_scoped_apply_dirty_daemon_conflict_and_retry(backend, app, tmp_path):
    content = document(backend)
    content["profile"]["settings"]["reportRate"] = 500
    stage(backend, save(tmp_path, content))
    context = backend.capturePageContext("profiles")
    props = backend._transport.objects[backend.profiles[1]["path"]][1]
    props["IsDirty"] = True
    assert backend.applyPage(context)
    wait_for(app, lambda: not backend.busy)
    assert backend.profileImportPending and backend.pageDirty(context)
    assert not backend._transport.calls
    props["IsDirty"] = False
    assert backend.applyPage(context)
    wait_for(app, lambda: not backend.busy)
    assert not backend.profileImportPending
    assert [op.member for op in backend._transport.calls] == ["ReportRate"]


def test_forged_scope_cannot_include_other_fields(backend):
    backend.setReportRate(500)
    context = backend.capturePageContext("profiles")
    operation = build_operations(backend._base, backend._draft)[0]
    context["importedOperations"] = [
        [operation.path, operation.interface, operation.member]
    ]
    assert not backend.pageDirty(context)
    assert backend.resetPage(context)
    assert backend.selectedProfile["reportRate"] == 500
    assert not backend._transport.calls


def test_atomic_save_failure_preserves_existing_file(tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    path.write_text("original")

    def deny_sibling(*args, **kwargs):
        raise PermissionError("document portal denies sibling creation")

    monkeypatch.setattr(profile_files.tempfile, "mkstemp", deny_sibling)
    with pytest.raises(ValueError, match="safe atomic save"):
        profile_files.write_document(str(path), {"new": True}, True)
    assert path.read_text() == "original"


def test_generic_capability_restrictions_are_atomic(backend, tmp_path):
    backend.selectDevice(1)
    content = document(backend)
    content["profile"]["settings"]["debounce"] = 3
    assert not inspect(backend, save(tmp_path, content))
    content = document(backend)
    content["profile"]["resolutions"][1]["enabled"] = False
    assert not inspect(backend, save(tmp_path, content))
    content = document(backend)
    backend._profile()["leds"][0]["colorDepth"] = 2
    assert not inspect(backend, save(tmp_path, content))
    assert "on/off" in backend.error
    assert not backend.dirty and not backend._transport.calls


# Reuse the existing isolated loopback bus, never the system mouse service.
from test_backend import private_bus  # noqa: E402,F401


def test_import_over_private_dbus_never_writes_before_apply(request, app, tmp_path):
    import asyncio
    from dbus_next.auth import AuthAnnonymous
    from qt_piper.backend import DBusTransport
    from test_backend import start_fake_daemon

    bus_address = request.getfixturevalue("private_bus")

    async def scenario():
        server, _objects, paths, calls = await start_fake_daemon(bus_address)
        backend = Backend(
            transport=DBusTransport(bus_address=bus_address, auth=AuthAnnonymous())
        )

        async def idle():
            end = time.monotonic() + 5
            while True:
                app.processEvents()
                if backend.connected and not backend.busy:
                    return
                assert time.monotonic() < end, backend.error
                await asyncio.sleep(0.002)

        try:
            await idle()
            content = document(backend)
            content["profile"]["settings"]["reportRate"] = 500
            content["profile"]["buttons"][20]["action"]["value"] = 5
            backend.selectProfile(2)
            stage(backend, save(tmp_path, content))
            assert not any(
                call.member in ("Set", "Commit", "SetActive", "SetDefault")
                for call in calls
            )
            context = backend.capturePageContext("profiles")
            assert backend.applyPage(context)
            await idle()
            writes = [call for call in calls if call.member == "Set"]
            assert {call.body[1] for call in writes} == {
                "ReportRate",
                "Mapping",
                "Color",
            }
            # Color differs between the source and target slot in the fixture.
            assert all(
                call.path.startswith(backend.selectedProfile["path"] + "/")
                or call.path == backend.selectedProfile["path"]
                for call in writes
            )
            commits = [call for call in calls if call.member == "Commit"]
            assert len(commits) == 1 and commits[0].path == paths[0]
            assert not any(call.member == "SetActive" for call in calls)
            assert not backend.dirty and not backend.profileImportPending
        finally:
            backend.close()
            server.disconnect()

    asyncio.run(scenario())


def test_import_apply_failure_and_delayed_resync_keep_retry_scope(
    backend, app, tmp_path
):
    content = document(backend)
    content["profile"]["settings"]["reportRate"] = 500
    stage(backend, save(tmp_path, content))
    context = backend.capturePageContext("profiles")
    backend.simulateCommitFailure()
    assert backend.applyPage(context)
    wait_for(app, lambda: not backend.busy)
    assert backend.commitState == "failed"
    assert backend.profileImportPending and backend.pageDirty(context)
    assert backend.applyPage(context)
    wait_for(app, lambda: not backend.busy)
    assert not backend.profileImportPending
    backend._transport.objects[backend.selectedProfile["path"]][1]["ReportRate"] = 1000
    backend._on_event("resync")
    wait_for(app, lambda: backend.commitState == "failed")
    assert backend.selectedProfile["reportRate"] == 500
    assert backend.profileImportPending and backend.pageDirty(context)
    assert backend.resetPage(context)
    assert backend.selectedProfile["reportRate"] == 1000
    assert not backend.profileImportPending
