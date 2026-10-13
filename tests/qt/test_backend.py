# SPDX-License-Identifier: GPL-2.0-or-later
"""Hardware-free model, fixture and real private-D-Bus protocol tests."""

import asyncio
import os
from copy import deepcopy
import shutil
import subprocess
import time

import pytest
from PySide6.QtGui import QGuiApplication

from qt_piper.backend import (
    Backend,
    DBusTransport,
    MockTransport,
    RatbagError,
    button_layer,
    build_operations,
    svg_for_model,
    unwrap,
    validate_macro,
)
from qt_piper.fixtures import fixture_objects


@pytest.fixture(scope="session")
def app():
    return QGuiApplication.instance() or QGuiApplication([])


def wait_for(app, condition, timeout=3):
    until = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < until, "Qt operation timed out"
        app.processEvents()
        time.sleep(0.002)
    app.processEvents()


@pytest.fixture
def backend(app):
    b = Backend(mock=True, fixture="all")
    wait_for(app, lambda: b.connected and not b.busy)
    yield b
    b.close()


def test_g600_indices_and_capabilities(backend):
    buttons = backend.selectedProfile["buttons"]
    assert len(buttons) == 40
    assert [b["index"] for b in buttons if b["layer"] == "normal"] == list(range(20))
    assert [b["index"] for b in buttons if b["layer"] == "gshift"] == list(
        range(21, 41)
    )
    assert [b["physicalIndex"] for b in buttons if b["layer"] == "gshift"] == list(
        range(20)
    )
    assert len(backend.profiles) == 3
    assert not backend.selectedProfile["canRename"]
    assert backend.selectedProfile["reportRates"] == [
        125,
        142,
        166,
        200,
        250,
        333,
        500,
        1000,
    ]
    assert backend.selectedDevice["svg"] == "logitech-g600.svg"
    assert "key" not in buttons[0]["actionTypes"]


def test_reserved_index_cannot_be_written(backend):
    assert not backend.setButtonMapping(20, "button", 1)
    assert not backend.dirty
    assert "index 20" in backend.error
    assert button_layer("usb:046d:c24a:0", 20) is None


def test_stage_apply_and_reset(backend, app):
    assert backend.setDpi(1, 1200, 1200)
    assert backend.dirty
    assert backend._transport.calls == []
    backend.reset()
    assert backend.selectedProfile["resolutions"][1]["x"] == 800
    assert not backend.dirty
    backend.setDpi(1, 1200, 1200)
    backend.apply()
    wait_for(app, lambda: not backend.busy)
    assert not backend.dirty
    assert backend.commitState == "applied"
    assert backend.selectedProfile["resolutions"][1]["x"] == 1200
    backend.setDpi(1, 1600, 1600)
    backend.reset()
    assert backend.selectedProfile["resolutions"][1]["x"] == 1200


def test_change_back_is_not_dirty(backend):
    backend.setReportRate(500)
    assert backend.dirty
    backend.setReportRate(1000)
    assert not backend.dirty


def test_noop_apply_does_not_write(backend):
    backend.apply()
    assert not backend.busy
    assert not backend._transport.calls


def test_capability_validation(backend):
    assert not backend.setProfileName("Work")
    assert not backend.setProfileEnabled(False)
    assert not backend.setResolutionEnabled(0, False)
    assert not backend.setDpi(0, 800, 1600)
    assert not backend.setDpi(0, 813, 813)
    assert not backend.setReportRate(700)
    assert not backend.setButtonMapping(0, "key", 30)
    assert not backend.setButtonMapping(0, "special", (1 << 30) + 18)
    assert not backend.dirty


def test_full_capability_device(backend, app):
    backend.selectDevice(1)
    assert backend.setProfileName("Desk")
    assert backend.setDpi(0, 800, 1600)
    assert backend.setResolutionDefault(0)
    assert backend.setResolutionActive(0)
    assert backend.setResolutionEnabled(2, False)
    assert backend.setAngleSnapping(1)
    assert backend.setDebounce(8)
    assert backend.setButtonMapping(1, "key", 30)
    assert backend.setButtonMapping(
        2, "macro", [[1, 30], [2, 30], [3, 40], [1, 48], [2, 48]]
    )
    assert backend.setLed(0, "color", "#ff8040")
    assert backend.setLed(0, "mode", 3)
    assert backend.setLed(0, "effectDuration", 4200)
    backend.selectProfile(1)
    assert backend.setProfileEnabled(False)
    backend.apply()
    wait_for(app, lambda: not backend.busy)
    assert not backend.dirty
    assert backend.profiles[0]["name"] == "Desk"
    assert backend.profiles[0]["resolutions"][0]["y"] == 1600
    assert backend.profiles[0]["leds"][0]["color"] == "#ff8040"
    assert not backend.profiles[1]["enabled"]


def test_activation_is_exclusive(backend, app):
    backend.selectProfile(2)
    backend.setProfileActive()
    backend.apply()
    wait_for(app, lambda: not backend.busy)
    assert [p["index"] for p in backend.profiles if p["active"]] == [2]


def test_shift_mapping_writes_exact_raw_index(backend, app):
    assert backend.setButtonMapping(21, "button", 5)
    backend.apply()
    wait_for(app, lambda: not backend.busy)
    assert [op.path for op in backend._transport.calls] == [
        backend.selectedProfile["buttons"][20]["path"]
    ]
    assert backend._transport.calls[0].path.endswith("b21")
    assert backend.selectedProfile["buttons"][0]["actionValue"] == 1


def test_commit_failure_retains_edits_for_retry(backend, app):
    backend.setReportRate(500)
    backend.simulateCommitFailure()
    backend.apply()
    wait_for(app, lambda: not backend.busy)
    assert backend.dirty
    assert backend.commitState == "failed"
    assert "failure" in backend.error
    backend.apply()
    wait_for(app, lambda: not backend.busy)
    assert not backend.dirty
    assert not backend.error


def test_disconnect_prevents_write_and_reconnects(backend, app):
    backend.setReportRate(500)
    backend.simulateDisconnect()
    assert not backend.connected
    assert not backend.setReportRate(125)
    backend.apply()
    assert not backend._transport.calls
    backend.simulateReconnect()
    wait_for(app, lambda: backend.connected and not backend.busy)
    assert backend.dirty
    assert backend.selectedProfile["reportRate"] == 500


def test_empty_device_list_is_not_connection_failure(app):
    b = Backend(mock=True, fixture="empty")
    try:
        wait_for(app, lambda: b.connected and not b.busy)
        assert b.devices == []
        assert b.selectedProfile == {}
        assert not b.error
    finally:
        b.close()


def test_external_refresh_keeps_local_edit(backend, app):
    backend.setReportRate(500)
    backend.refresh()
    wait_for(app, lambda: not backend.busy)
    assert backend.selectedProfile["reportRate"] == 500
    assert backend.dirty


def test_resync_reports_delayed_hardware_failure(backend, app):
    backend.setReportRate(500)
    backend._on_event("resync")
    wait_for(app, lambda: backend.commitState == "failed")
    assert not backend.dirty
    assert backend.selectedProfile["reportRate"] == 1000
    assert "write failure" in backend.error


def test_maps_are_not_mutable_backdoors(backend):
    profile = backend.selectedProfile
    profile["reportRate"] = 99999
    assert backend.selectedProfile["reportRate"] == 1000


@pytest.mark.parametrize(
    "events",
    [
        [],
        [[2, 30]],
        [[1, 30]],
        [[1, 30], [1, 30], [2, 30]],
        [[3, -1]],
        [[3, 100000]],
        [[9, 1]],
    ],
)
def test_invalid_macros(events):
    with pytest.raises(ValueError):
        validate_macro(events)


def test_g600_rejects_unsupported_macros():
    assert validate_macro([[1, 42], [1, 30], [2, 30], [2, 42]], g600=True)
    with pytest.raises(ValueError, match="one key"):
        validate_macro([[1, 30], [2, 30], [1, 48], [2, 48]], g600=True)
    with pytest.raises(ValueError, match="one key"):
        validate_macro([[1, 30], [3, 100], [2, 30]], g600=True)


def test_unknown_device_uses_existing_fallback():
    assert svg_for_model("unknown") == "fallback.svg"


def test_fixture_reads_are_deterministic():
    a = asyncio.run(MockTransport("g600").snapshot())
    b = asyncio.run(MockTransport("g600").snapshot())
    assert a == b
    assert not build_operations(a, deepcopy(a))


# These tests speak actual D-Bus to an isolated daemon, not a patched transport.
# They never open the user's system bus or a physical device.
@pytest.fixture
def private_bus(tmp_path):
    if not shutil.which("dbus-daemon"):
        pytest.skip("dbus-daemon unavailable")
    # Cloud sandboxes can require TCP; offline Flatpak builders require a Unix
    # socket. Both carry the same synthetic protocol tests on a private daemon.
    transport = os.environ.get("PIPER_TEST_BUS_TRANSPORT", "tcp")
    assert transport in ("tcp", "unix")
    listen = (
        "unix:tmpdir=/tmp"
        if transport == "unix"
        else "tcp:host=127.0.0.1,port=0,family=ipv4"
    )
    config = tmp_path / "bus.conf"
    config.write_text(f"""<busconfig><type>session</type>
      <listen>{listen}</listen>
      <auth>ANONYMOUS</auth><allow_anonymous/>
      <policy context="default"><allow send_destination="*"/>
      <allow receive_sender="*"/><allow own="*"/></policy></busconfig>""")
    process = subprocess.Popen(
        [
            "dbus-daemon",
            "--config-file=" + str(config),
            "--nofork",
            "--print-address=1",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    address = process.stdout.readline().strip()
    assert address, "Private D-Bus daemon failed to start"
    try:
        yield address
    finally:
        process.terminate()
        process.wait(timeout=5)
        process.stdout.close()


def variant_properties(props):
    from dbus_next import Variant

    signatures = {
        "APIVersion": "i",
        "Devices": "ao",
        "Name": "s",
        "Model": "s",
        "DeviceType": "u",
        "FirmwareVersion": "s",
        "Profiles": "ao",
        "Index": "u",
        "Capabilities": "au",
        "Disabled": "b",
        "IsActive": "b",
        "IsDirty": "b",
        "ReportRate": "u",
        "ReportRates": "au",
        "AngleSnapping": "i",
        "Debounce": "i",
        "Debounces": "au",
        "Resolutions": "ao",
        "Buttons": "ao",
        "Leds": "ao",
        "IsDefault": "b",
        "IsDisabled": "b",
        "Resolution": "v",
        "Mapping": "(uv)",
        "ActionTypes": "au",
        "Mode": "u",
        "Modes": "au",
        "Color": "(uuu)",
        "ColorDepth": "u",
        "Brightness": "u",
        "EffectDuration": "u",
    }
    result = {}
    for key, value in props.items():
        signature = signatures[key]
        if key == "IsDirty" and not isinstance(value, bool):
            signature = "s" if isinstance(value, str) else "u"
        if key == "Resolutions" and (not value or isinstance(value[0], int)):
            signature = "au"
        if key == "Resolution":
            value = Variant("(uu)" if isinstance(value, list) else "u", value)
        if key == "Mapping":
            value = [value[0], Variant("a(uu)" if value[0] == 4 else "u", value[1])]
        result[key] = Variant(signature, value)
    return result


async def start_fake_daemon(
    address,
    version=2,
    reject_writes=False,
    ignore_writes=False,
    resync_on_write=False,
    reject_commit=False,
):
    from dbus_next import Message, MessageType
    from dbus_next.aio import MessageBus
    from dbus_next.auth import AuthAnnonymous

    bus = await MessageBus(bus_address=address, auth=AuthAnnonymous()).connect()
    service = "org.freedesktop.ratbag1"
    await bus.request_name(service)
    objects, paths = fixture_objects("all")
    calls = []

    def handler(message):
        if (
            message.message_type != MessageType.METHOD_CALL
            or message.destination != service
        ):
            return None
        calls.append(message)
        if message.member == "GetAll":
            props = (
                {"APIVersion": version, "Devices": paths}
                if message.path == "/org/freedesktop/ratbag1"
                else objects[message.path][1]
            )
            return Message.new_method_return(
                message, "a{sv}", [variant_properties(props)]
            )
        if message.member == "Set":
            if reject_writes:
                return Message.new_error(
                    message,
                    "org.freedesktop.DBus.Error.AccessDenied",
                    "Test daemon rejected this write",
                )
            props = objects[message.path][1]
            if not ignore_writes:
                props[message.body[1]] = unwrap(message.body[2])
            if reject_commit:
                objects[message.path.rsplit("/", 1)[0]][1]["IsDirty"] = True
            if resync_on_write:
                bus.send(Message.new_signal(paths[0], service + ".Device", "Resync"))
            return Message.new_method_return(message)
        if message.member == "Commit":
            if reject_commit:
                return Message.new_error(
                    message,
                    "org.freedesktop.DBus.Error.Failed",
                    "Synthetic Commit failure",
                )
            return Message.new_method_return(message)
        if message.member in ("SetActive", "SetDefault"):
            interface = objects[message.path][0]
            prefix = message.path.rsplit("/", 1)[0]
            field = "IsActive" if message.member == "SetActive" else "IsDefault"
            for path, (kind, props) in objects.items():
                if kind == interface and path.rsplit("/", 1)[0] == prefix:
                    props[field] = path == message.path
            return Message.new_method_return(message, "u", [0])
        return Message.new_error(
            message, "org.freedesktop.DBus.Error.UnknownMethod", "No such method"
        )

    bus.add_message_handler(handler)
    return bus, objects, paths, calls


def test_real_dbus_roundtrip_variants_and_commit(private_bus):
    async def scenario():
        server, objects, paths, calls = await start_fake_daemon(private_bus)
        from dbus_next.auth import AuthAnnonymous

        transport = DBusTransport(bus_address=private_bus, auth=AuthAnnonymous())
        try:
            initial = await transport.snapshot()
            assert len(initial) == 2
            assert len(initial[0]["profiles"][0]["buttons"]) == 40
            draft = deepcopy(initial)
            draft[0]["profiles"][0]["resolutions"][1]["x"] = 1200
            draft[0]["profiles"][0]["resolutions"][1]["y"] = 1200
            button = draft[0]["profiles"][0]["buttons"][20]
            button["actionType"] = "macro"
            button["actionValue"] = [[1, 42], [1, 30], [2, 30], [2, 42]]
            draft[1]["profiles"][0]["resolutions"][0].update(x=800, y=1600)
            updated = await transport.apply(build_operations(initial, draft))
            assert updated[0]["profiles"][0]["resolutions"][1]["x"] == 1200
            assert updated[1]["profiles"][0]["resolutions"][0]["y"] == 1600
            writes = [c for c in calls if c.member == "Set"]
            assert len(writes) == 3
            resolution_writes = [c for c in writes if c.body[1] == "Resolution"]
            assert resolution_writes[0].body[2].signature == "v"
            assert resolution_writes[0].body[2].value.signature == "u"
            assert resolution_writes[1].body[2].value.signature == "(uu)"
            macro_write = [c for c in writes if c.body[1] == "Mapping"][0]
            assert macro_write.path.endswith("b21")
            assert macro_write.body[2].value[1].signature == "a(uu)"
            assert len([c for c in calls if c.member == "Commit"]) == 2
        finally:
            await transport.close()
            server.disconnect()

    asyncio.run(scenario())


def test_real_dbus_version_mismatch_blocks_read(private_bus):
    async def scenario():
        server, *_ = await start_fake_daemon(private_bus, version=999)
        from dbus_next.auth import AuthAnnonymous

        transport = DBusTransport(bus_address=private_bus, auth=AuthAnnonymous())
        try:
            with pytest.raises(RatbagError, match="requires API 2"):
                await transport.snapshot()
        finally:
            await transport.close()
            server.disconnect()

    asyncio.run(scenario())


def test_real_dbus_resync_and_service_disappearance(private_bus):
    async def scenario():
        from dbus_next import Message

        server, _, paths, _ = await start_fake_daemon(private_bus)
        from dbus_next.auth import AuthAnnonymous

        transport = DBusTransport(bus_address=private_bus, auth=AuthAnnonymous())
        events = []
        transport.on_event = events.append
        try:
            await transport.snapshot()
            server.send(
                Message.new_signal(paths[0], "org.freedesktop.ratbag1.Device", "Resync")
            )
            await asyncio.sleep(0.05)
            assert "resync" in events
            await server.release_name("org.freedesktop.ratbag1")
            await asyncio.sleep(0.05)
            assert "disconnected" in events
        finally:
            await transport.close()
            server.disconnect()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "reject,ignore,expected",
    [(True, False, "AccessDenied"), (False, True, "did not accept")],
)
def test_real_dbus_error_and_ignored_setter_do_not_commit(
    private_bus, reject, ignore, expected
):
    async def scenario():
        from dbus_next.auth import AuthAnnonymous

        server, _, paths, calls = await start_fake_daemon(
            private_bus, reject_writes=reject, ignore_writes=ignore
        )
        transport = DBusTransport(bus_address=private_bus, auth=AuthAnnonymous())
        try:
            before = await transport.snapshot()
            draft = deepcopy(before)
            draft[0]["profiles"][0]["reportRate"] = 500
            with pytest.raises(RatbagError, match=expected):
                await transport.apply(build_operations(before, draft))
            assert not any(c.member == "Commit" for c in calls)
        finally:
            await transport.close()
            server.disconnect()

    asyncio.run(scenario())


def test_real_dbus_activation_methods(private_bus):
    async def scenario():
        from dbus_next.auth import AuthAnnonymous

        server, _, _, calls = await start_fake_daemon(private_bus)
        transport = DBusTransport(bus_address=private_bus, auth=AuthAnnonymous())
        try:
            before = await transport.snapshot()
            draft = deepcopy(before)
            profiles = draft[0]["profiles"]
            for p in profiles:
                p["active"] = p["index"] == 2
            for r in profiles[2]["resolutions"]:
                r["active"] = r["default"] = r["index"] == 0
            after = await transport.apply(build_operations(before, draft))
            assert after[0]["profiles"][2]["active"]
            assert after[0]["profiles"][2]["resolutions"][0]["default"]
            methods = [m for m in calls if m.member in ("SetActive", "SetDefault")]
            assert len(methods) == 3
            assert all(m.signature == "" for m in methods)
        finally:
            await transport.close()
            server.disconnect()

    asyncio.run(scenario())


def test_real_dbus_properties_changed_notification(private_bus):
    async def scenario():
        from dbus_next import Message, Variant
        from dbus_next.auth import AuthAnnonymous

        server, _, paths, _ = await start_fake_daemon(private_bus)
        transport = DBusTransport(bus_address=private_bus, auth=AuthAnnonymous())
        event = asyncio.Event()
        transport.on_event = lambda kind: event.set() if kind == "changed" else None
        try:
            await transport.snapshot()
            server.send(
                Message.new_signal(
                    "/org/freedesktop/ratbag1",
                    "org.freedesktop.DBus.Properties",
                    "PropertiesChanged",
                    "sa{sv}as",
                    [
                        "org.freedesktop.ratbag1.Manager",
                        {"Devices": Variant("ao", paths[:1])},
                        [],
                    ],
                )
            )
            await asyncio.wait_for(event.wait(), 1)
        finally:
            await transport.close()
            server.disconnect()

    asyncio.run(scenario())


def test_g600_modifier_only_and_early_modifier_release_rejected():
    assert validate_macro([[1, 29], [2, 29]], g600=True) == [
        [1, 29],
        [1, 0],
        [2, 0],
        [2, 29],
    ]
    with pytest.raises(ValueError, match="main key before"):
        validate_macro([[1, 29], [1, 30], [2, 29], [2, 30]], g600=True)


def test_macro_daemon_event_limit():
    with pytest.raises(ValueError, match="256"):
        validate_macro([[1, 30], [2, 30]] * 129)


def test_real_dbus_resync_mid_apply_aborts_commit(private_bus):
    async def scenario():
        from dbus_next.auth import AuthAnnonymous

        server, _, _, calls = await start_fake_daemon(private_bus, resync_on_write=True)
        transport = DBusTransport(bus_address=private_bus, auth=AuthAnnonymous())
        try:
            before = await transport.snapshot()
            draft = deepcopy(before)
            draft[0]["profiles"][0]["reportRate"] = 500
            with pytest.raises(RatbagError, match="resynchronization during Apply"):
                await transport.apply(build_operations(before, draft))
            assert not any(c.member == "Commit" for c in calls)
        finally:
            await transport.close()
            server.disconnect()

    asyncio.run(scenario())


def test_scoped_assignment_keeps_other_page_profile_and_device_drafts(backend, app):
    backend.setDpi(0, 800, 800)
    backend.setLed(0, "color", "#123456")
    backend.setButtonMapping(0, "button", 5)
    backend.selectProfile(1)
    backend.setReportRate(500)
    backend.setButtonMapping(1, "button", 4)
    backend.selectDevice(1)
    backend.setDebounce(8)
    backend.setProfileName("Pending name")
    backend.selectDevice(0)
    backend.selectProfile(0)
    before = deepcopy(backend._draft)
    context = backend.captureMappingContext(21)
    outcomes = []
    backend.mappingApplyFinished.connect(lambda *args: outcomes.append(args))
    assert backend.applyMapping(context, "button", 5)
    wait_for(app, lambda: not backend.busy)
    assert backend.mappingForContext(context)["actionValue"] == 5
    assert not backend.mappingDirty(context)
    assert backend.dirty
    assert len(backend._transport.calls) == 1
    assert backend._transport.calls[0].path == context["buttonPath"]
    assert backend._transport.calls[0].device == context["devicePath"]
    assert outcomes[-1][0] == context["token"] and outcomes[-1][1]
    assert (
        backend._draft[0]["profiles"][0]["resolutions"]
        == before[0]["profiles"][0]["resolutions"]
    )
    assert backend._draft[0]["profiles"][0]["leds"] == before[0]["profiles"][0]["leds"]
    assert backend._draft[0]["profiles"][1] == before[0]["profiles"][1]
    assert backend._draft[1] == before[1]
    assert (
        backend._draft[0]["profiles"][0]["buttons"][0]
        == before[0]["profiles"][0]["buttons"][0]
    )
    assert backend._base[0]["profiles"][0]["resolutions"][0]["x"] == 400
    assert backend._base[1]["profiles"][0]["name"] == "Desktop"


def test_reset_assignment_restores_only_captured_mapping(backend):
    context = backend.captureMappingContext(21)
    initial = backend.mappingForContext(context)
    backend.setButtonMapping(21, "button", 5)
    backend.setButtonMapping(0, "button", 4)
    backend.setReportRate(500)
    reset = backend.resetMapping(context)
    assert reset == initial
    assert backend.mappingForContext(context) == initial
    assert not backend.mappingDirty(context)
    assert backend.dirty
    assert backend.selectedProfile["reportRate"] == 500
    assert backend.selectedProfile["buttons"][0]["actionValue"] == 4
    assert not backend._transport.calls


def test_scoped_failure_keeps_assignment_and_unrelated_edits(backend, app):
    context = backend.captureMappingContext(21)
    backend.setReportRate(500)
    backend.simulateCommitFailure()
    outcomes = []
    backend.mappingApplyFinished.connect(lambda *args: outcomes.append(args))
    assert backend.applyMapping(context, "button", 5)
    wait_for(app, lambda: not backend.busy)
    assert backend.mappingDirty(context)
    assert backend.mappingForContext(context)["actionValue"] == 5
    assert backend.selectedProfile["reportRate"] == 500
    assert not outcomes[-1][1]
    assert backend.applyMapping(context, "button", 5)
    wait_for(app, lambda: not backend.busy)
    assert outcomes[-1][1]
    assert not backend.mappingDirty(context)
    assert backend.dirty
    assert backend.selectedProfile["reportRate"] == 500


def test_scoped_noop_never_commits_other_drafts(backend):
    backend.setReportRate(500)
    context = backend.captureMappingContext(21)
    button = backend.mappingForContext(context)
    assert backend.applyMapping(context, button["actionType"], button["actionValue"])
    assert not backend.busy
    assert backend.dirty
    assert not backend._transport.calls


def test_scoped_busy_and_context_guards(backend, app):
    context = backend.captureMappingContext(21)
    assert backend.captureMappingContext(20) == {}
    forged = dict(context, index=20)
    assert not backend.applyMapping(forged, "button", 5)
    assert backend.applyMapping(context, "button", 5)
    assert backend.busy
    assert not backend.applyMapping(context, "button", 4)
    assert backend.resetMapping(context) == {}
    assert backend.captureMappingContext(0) == {}
    backend.selectDevice(1)
    backend.selectProfile(1)
    assert backend.selectedDeviceIndex == 0
    assert backend.selectedProfileIndex == 0
    wait_for(app, lambda: not backend.busy)
    assert len(backend._transport.calls) == 1
    assert backend.mappingForContext(context)["actionValue"] == 5
    backend.selectProfile(1)
    assert not backend.mappingContextValid(context)
    assert not backend.applyMapping(context, "button", 4)
    backend.selectProfile(0)
    assert not backend.mappingContextValid(context)


def test_scoped_context_disconnect_and_external_refresh(backend, app):
    context = backend.captureMappingContext(21)
    backend.refresh()
    wait_for(app, lambda: not backend.busy)
    assert backend.mappingContextValid(context)
    backend._transport.objects[context["buttonPath"]][1]["Mapping"] = [1, 5]
    backend.refresh()
    wait_for(app, lambda: not backend.busy)
    assert not backend.mappingContextValid(context)
    context = backend.captureMappingContext(21)
    backend.simulateDisconnect()
    assert not backend.mappingContextValid(context)
    backend.simulateReconnect()
    wait_for(app, lambda: not backend.busy)
    assert not backend.mappingContextValid(context)


def test_scoped_daemon_dirty_preflight_preserves_drafts_without_writing(backend, app):
    context = backend.captureMappingContext(21)
    backend.setReportRate(500)
    other_profile = backend.profiles[1]["path"]
    backend._transport.objects[other_profile][1]["IsDirty"] = True
    assert backend.applyMapping(context, "button", 5)
    wait_for(app, lambda: not backend.busy)
    assert backend.mappingDirty(context)
    assert backend.selectedProfile["reportRate"] == 500
    assert not backend._transport.calls
    assert "pending changes" in backend.error


def test_scoped_delayed_resync_retains_all_drafts_for_retry(backend, app):
    context = backend.captureMappingContext(21)
    backend.setReportRate(500)
    assert backend.applyMapping(context, "button", 5)
    wait_for(app, lambda: not backend.busy)
    backend._transport.objects[context["buttonPath"]][1]["Mapping"] = [1, 1]
    backend._on_event("resync")
    wait_for(app, lambda: backend.commitState == "failed")
    assert backend.selectedProfile["reportRate"] == 500
    assert backend.selectedProfile["buttons"][20]["actionValue"] == 5
    assert backend.dirty


def test_private_dbus_scoped_mapping_writes_one_mapping_and_one_device_commit(
    private_bus,
):
    async def scenario():
        from dbus_next.auth import AuthAnnonymous
        from qt_piper.backend import Operation

        server, objects, paths, calls = await start_fake_daemon(private_bus)
        transport = DBusTransport(bus_address=private_bus, auth=AuthAnnonymous())
        try:
            data = await transport.snapshot()
            target = data[0]["profiles"][1]["buttons"][20]
            op = Operation(
                paths[0], target["path"], "Button", "Mapping", [1, 5], "(uv)"
            )
            result = await transport.apply_mapping(op)
            writes = [c for c in calls if c.member == "Set"]
            commits = [c for c in calls if c.member == "Commit"]
            assert len(writes) == len(commits) == 1
            assert writes[0].path == target["path"]
            assert writes[0].body[1] == "Mapping"
            assert writes[0].body[2].signature == "(uv)"
            assert commits[0].path == paths[0]
            assert result[0]["profiles"][1]["buttons"][20]["actionValue"] == 5
            assert objects[data[0]["profiles"][0]["path"]][1]["ReportRate"] == 1000
            assert objects[data[1]["profiles"][0]["path"]][1]["Debounce"] == 4
        finally:
            await transport.close()
            server.disconnect()

    asyncio.run(scenario())


def test_private_dbus_scoped_dirty_profile_blocks_all_writes(private_bus):
    async def scenario():
        from dbus_next.auth import AuthAnnonymous
        from qt_piper.backend import Operation, ScopedApplyError

        server, objects, paths, calls = await start_fake_daemon(private_bus)
        transport = DBusTransport(bus_address=private_bus, auth=AuthAnnonymous())
        try:
            data = await transport.snapshot()
            target = data[0]["profiles"][1]["buttons"][20]
            objects[data[0]["profiles"][0]["path"]][1]["IsDirty"] = True
            op = Operation(
                paths[0], target["path"], "Button", "Mapping", [1, 5], "(uv)"
            )
            with pytest.raises(ScopedApplyError, match="pending changes") as error:
                await transport.apply_mapping(op)
            assert not error.value.partial
            assert not any(c.member in ("Set", "Commit") for c in calls)
        finally:
            await transport.close()
            server.disconnect()

    asyncio.run(scenario())


@pytest.mark.parametrize("state", [None, "false", 0])
def test_private_dbus_scoped_unknown_or_malformed_dirty_state_blocks_writes(
    private_bus, state
):
    async def scenario():
        from dbus_next.auth import AuthAnnonymous
        from qt_piper.backend import Operation, ScopedApplyError

        server, objects, paths, calls = await start_fake_daemon(private_bus)
        transport = DBusTransport(bus_address=private_bus, auth=AuthAnnonymous())
        try:
            data = await transport.snapshot()
            target = data[0]["profiles"][1]["buttons"][20]
            props = objects[data[0]["profiles"][0]["path"]][1]
            if state is None:
                del props["IsDirty"]
            else:
                props["IsDirty"] = state
            op = Operation(
                paths[0], target["path"], "Button", "Mapping", [1, 5], "(uv)"
            )
            with pytest.raises(ScopedApplyError, match="valid IsDirty"):
                await transport.apply_mapping(op)
            assert not any(c.member in ("Set", "Commit") for c in calls)
        finally:
            await transport.close()
            server.disconnect()

    asyncio.run(scenario())


def test_backend_scoped_apply_over_private_dbus_preserves_all_other_drafts(
    private_bus, app
):
    async def scenario():
        from dbus_next.auth import AuthAnnonymous

        server, _, paths, calls = await start_fake_daemon(private_bus)
        transport = DBusTransport(bus_address=private_bus, auth=AuthAnnonymous())
        backend = Backend(transport=transport)

        async def idle():
            until = time.monotonic() + 5
            while True:
                app.processEvents()
                if backend.connected and not backend.busy:
                    return
                assert time.monotonic() < until, backend.error
                await asyncio.sleep(0.002)

        try:
            await idle()
            backend.selectDevice(1)
            backend.setDebounce(8)
            backend.setProfileName("Local other-device name")
            backend.selectDevice(0)
            backend.selectProfile(1)
            backend.setReportRate(500)
            backend.selectProfile(0)
            backend.setDpi(0, 800, 800)
            backend.setLed(0, "color", "#123456")
            backend.setButtonMapping(0, "button", 4)
            pending = deepcopy(backend._draft)
            context = backend.captureMappingContext(21)
            outcomes = []
            backend.mappingApplyFinished.connect(lambda *args: outcomes.append(args))
            assert backend.applyMapping(context, "button", 5)
            await idle()
            writes = [c for c in calls if c.member == "Set"]
            commits = [c for c in calls if c.member == "Commit"]
            assert len(writes) == len(commits) == 1
            assert (
                writes[0].path == context["buttonPath"]
                and writes[0].body[1] == "Mapping"
            )
            assert commits[0].path == paths[0]
            assert outcomes[-1][0] == context["token"] and outcomes[-1][1]
            assert backend.commitState == "submitted"
            assert backend.dirty and not backend.mappingDirty(context)
            assert backend._draft[1] == pending[1]
            assert backend._draft[0]["profiles"][1] == pending[0]["profiles"][1]
            for field in ("resolutions", "leds"):
                assert (
                    backend._draft[0]["profiles"][0][field]
                    == pending[0]["profiles"][0][field]
                )
            assert (
                backend._draft[0]["profiles"][0]["buttons"][0]
                == pending[0]["profiles"][0]["buttons"][0]
            )
        finally:
            backend.close()
            server.disconnect()

    asyncio.run(scenario())


def test_backend_scoped_private_dbus_failure_retains_drafts(private_bus, app):
    async def scenario():
        from dbus_next.auth import AuthAnnonymous

        server, _, _, calls = await start_fake_daemon(private_bus, reject_writes=True)
        backend = Backend(
            transport=DBusTransport(bus_address=private_bus, auth=AuthAnnonymous())
        )

        async def idle():
            until = time.monotonic() + 5
            while True:
                app.processEvents()
                if backend.connected and not backend.busy:
                    return
                assert time.monotonic() < until, backend.error
                await asyncio.sleep(0.002)

        try:
            await idle()
            backend.setReportRate(500)
            context = backend.captureMappingContext(21)
            outcomes = []
            backend.mappingApplyFinished.connect(lambda *args: outcomes.append(args))
            assert backend.applyMapping(context, "button", 5)
            await idle()
            assert backend.mappingDirty(context)
            assert backend.mappingForContext(context)["actionValue"] == 5
            assert backend.selectedProfile["reportRate"] == 500
            assert not outcomes[-1][1]
            assert backend.commitState == "failed"
            assert len([c for c in calls if c.member == "Set"]) == 1
            assert not any(c.member == "Commit" for c in calls)
            assert (
                backend.resetMapping(context) == {}
            )  # Potential partial write remains protected.
        finally:
            backend.close()
            server.disconnect()

    asyncio.run(scenario())


def test_backend_scoped_preflight_retry_does_not_clear_partial_write_guard(
    private_bus, app
):
    async def scenario():
        from dbus_next.auth import AuthAnnonymous

        server, _, _, calls = await start_fake_daemon(private_bus, reject_commit=True)
        backend = Backend(
            transport=DBusTransport(bus_address=private_bus, auth=AuthAnnonymous())
        )

        async def idle():
            until = time.monotonic() + 5
            while True:
                app.processEvents()
                if backend.connected and not backend.busy:
                    return
                assert time.monotonic() < until, backend.error
                await asyncio.sleep(0.002)

        try:
            await idle()
            backend.setReportRate(500)
            context = backend.captureMappingContext(21)
            assert backend.applyMapping(context, "button", 5)
            await idle()
            assert backend._partial_apply
            assert backend.applyMapping(context, "button", 5)
            await idle()
            assert "pending changes" in backend.error
            assert backend._partial_apply
            assert backend.resetMapping(context) == {}
            assert backend.mappingDirty(context)
            assert backend.selectedProfile["reportRate"] == 500
            assert len([c for c in calls if c.member == "Set"]) == 1
            assert len([c for c in calls if c.member == "Commit"]) == 1
        finally:
            backend.close()
            server.disconnect()

    asyncio.run(scenario())


def test_child_then_main_assignment_batch_isolation(backend, app):
    backend.setDpi(0, 800, 800)
    backend.setLed(0, "color", "#123456")
    backend.selectProfile(1)
    backend.setButtonMapping(1, "button", 4)
    backend.selectDevice(1)
    backend.setProfileName("Other device draft")
    backend.selectDevice(0)
    backend.selectProfile(0)
    a = backend.captureMappingContext(0)
    b = backend.captureMappingContext(21)
    assert backend.stageMapping(a, "button", 4)
    assert backend.stageMapping(b, "macro", [[1, 29], [1, 46], [2, 46], [2, 29]])
    assert not backend._transport.calls
    assert backend.profileMappingsDirty
    assert backend.applyMapping(a, "button", 4)
    wait_for(app, lambda: not backend.busy)
    assert not backend.mappingDirty(a) and backend.mappingDirty(b)
    contexts = backend.captureMappingContexts()
    outcomes = []
    backend.mappingsApplyFinished.connect(lambda *args: outcomes.append(args))
    assert backend.applyMappings(contexts)
    wait_for(app, lambda: not backend.busy)
    assert len(backend._transport.calls) == 2
    assert [op.path for op in backend._transport.calls] == [
        a["buttonPath"],
        b["buttonPath"],
    ]
    assert not backend.profileMappingsDirty
    assert backend.dirty
    assert backend.selectedProfile["resolutions"][0]["x"] == 800
    assert backend.selectedProfile["leds"][0]["color"] == "#123456"
    assert backend._draft[0]["profiles"][1]["buttons"][1]["actionValue"] == 4
    assert backend._draft[1]["profiles"][0]["name"] == "Other device draft"
    assert outcomes[-1][:3] == (a["devicePath"], a["profilePath"], True)


def test_main_assignment_revert_leaves_every_other_scope(backend):
    backend.setDpi(0, 800, 800)
    backend.setButtonMapping(0, "button", 4)
    backend.setButtonMapping(21, "button", 5)
    backend.selectProfile(1)
    backend.setButtonMapping(1, "button", 4)
    backend.selectProfile(0)
    contexts = backend.captureMappingContexts()
    assert backend.resetMappings(contexts)
    assert not backend.profileMappingsDirty
    assert backend.dirty
    assert backend.selectedProfile["resolutions"][0]["x"] == 800
    assert backend._draft[0]["profiles"][1]["buttons"][1]["actionValue"] == 4
    assert not backend._transport.calls


@pytest.mark.parametrize(
    "scope,expected_members",
    [
        ("sensitivity", {"Resolution", "ReportRate"}),
        ("lighting", {"Color"}),
        ("advanced", {"AngleSnapping", "Debounce", "ReportRate"}),
        ("profiles", {"Name"}),
    ],
)
def test_page_apply_isolation(backend, app, scope, expected_members):
    backend.selectDevice(1)
    backend.setDpi(0, 800, 1600)
    backend.setReportRate(500)
    backend.setLed(0, "color", "#123456")
    backend.setAngleSnapping(1)
    backend.setDebounce(8)
    backend.setProfileName("Local profile name")
    backend.setButtonMapping(1, "key", 30)
    backend.selectProfile(1)
    backend.setButtonMapping(0, "key", 31)
    backend.selectProfile(0)
    context = backend.capturePageContext(scope)
    assert backend.pageDirty(context)
    outcome = []
    backend.pageApplyFinished.connect(lambda *args: outcome.append(args))
    assert backend.applyPage(context)
    wait_for(app, lambda: not backend.busy)
    assert {op.member for op in backend._transport.calls} == expected_members
    assert not backend.pageDirty(context)
    assert backend.profileMappingsDirty and backend.dirty
    assert backend.selectedProfile["buttons"][1]["actionValue"] == 30
    assert backend.profiles[1]["buttons"][0]["actionValue"] == 31
    assert outcome[-1][0] == context["token"] and outcome[-1][1]
    # In particular, applying a profile name must not clear its child fields.
    if scope == "profiles":
        assert backend.selectedProfile["resolutions"][0]["y"] == 1600
        assert backend.selectedProfile["leds"][0]["color"] == "#123456"
        assert backend.selectedProfile["debounce"] == 8


@pytest.mark.parametrize("scope", ["sensitivity", "lighting", "advanced", "profiles"])
def test_page_reset_isolation(backend, scope):
    backend.selectDevice(1)
    backend.setDpi(0, 800, 1600)
    backend.setReportRate(500)
    backend.setLed(0, "color", "#123456")
    backend.setAngleSnapping(1)
    backend.setDebounce(8)
    backend.setProfileName("Local profile name")
    backend.setButtonMapping(1, "key", 30)
    context = backend.capturePageContext(scope)
    assert backend.resetPage(context)
    assert not backend.pageDirty(context)
    assert backend.profileMappingsDirty and backend.dirty
    assert backend.selectedProfile["buttons"][1]["actionValue"] == 30
    assert not backend._transport.calls


def test_private_dbus_stale_child_mapping_rejected_before_write(private_bus, app):
    async def scenario():
        from dbus_next.auth import AuthAnnonymous

        server, objects, _, calls = await start_fake_daemon(private_bus)
        backend = Backend(
            transport=DBusTransport(bus_address=private_bus, auth=AuthAnnonymous())
        )

        async def idle():
            until = time.monotonic() + 5
            while True:
                app.processEvents()
                if backend.connected and not backend.busy:
                    return
                assert time.monotonic() < until, backend.error
                await asyncio.sleep(0.002)

        try:
            await idle()
            context = backend.captureMappingContext(21)
            objects[context["buttonPath"]][1]["Mapping"] = [1, 4]
            assert backend.applyMapping(context, "button", 5)
            await idle()
            assert "changed in ratbagd" in backend.error
            assert backend.mappingDirty(context)
            assert not any(c.member in ("Set", "Commit") for c in calls)
        finally:
            backend.close()
            server.disconnect()

    asyncio.run(scenario())


def test_backend_batch_and_page_apply_over_private_dbus_never_mix_scopes(
    private_bus, app
):
    async def scenario():
        from dbus_next.auth import AuthAnnonymous

        server, _, paths, calls = await start_fake_daemon(private_bus)
        backend = Backend(
            transport=DBusTransport(bus_address=private_bus, auth=AuthAnnonymous())
        )

        async def idle():
            until = time.monotonic() + 5
            while True:
                app.processEvents()
                if backend.connected and not backend.busy:
                    return
                assert time.monotonic() < until, backend.error
                await asyncio.sleep(0.002)

        try:
            await idle()
            backend.selectDevice(1)
            backend.setDebounce(8)
            backend.setDpi(0, 800, 1600)
            backend.setReportRate(500)
            backend.setLed(0, "color", "#123456")
            backend.setButtonMapping(0, "key", 30)
            backend.setButtonMapping(1, "key", 31)
            backend.selectProfile(1)
            backend.setButtonMapping(0, "key", 32)
            backend.selectProfile(0)
            context = backend.capturePageContext("sensitivity")
            assert backend.applyPage(context)
            await idle()
            assert {c.body[1] for c in calls if c.member == "Set"} == {
                "Resolution",
                "ReportRate",
            }
            assert backend.profileMappingsDirty
            offset = len(calls)
            contexts = backend.captureMappingContexts()
            assert backend.applyMappings(contexts)
            await idle()
            writes = [c for c in calls[offset:] if c.member == "Set"]
            commits = [c for c in calls[offset:] if c.member == "Commit"]
            assert len(writes) == 2 and all(c.body[1] == "Mapping" for c in writes)
            assert len(commits) == 1 and commits[0].path == paths[1]
            assert not backend.profileMappingsDirty
            assert backend.selectedProfile["leds"][0]["color"] == "#123456"
            assert backend.selectedProfile["debounce"] == 8
            assert backend.profiles[1]["buttons"][0]["actionValue"] == 32
            assert backend.dirty
        finally:
            backend.close()
            server.disconnect()

    asyncio.run(scenario())


def test_g600_modifier_only_reserved_key_roundtrip(backend, app):
    # Synthetic Linux modifier chord: no user's device profile is copied.
    macro = [[1, 29], [1, 42], [1, 0], [2, 0], [2, 42], [2, 29]]
    assert validate_macro(macro, g600=True) == macro
    context = backend.captureMappingContext(5)
    assert backend.applyMapping(context, "macro", macro)
    wait_for(app, lambda: not backend.busy)
    assert backend.mappingForContext(context)["actionValue"] == macro
    assert "Key 0" not in backend.mappingForContext(context)["actionLabel"]


@pytest.mark.parametrize("key", [84, 164, 165, 767])
def test_g600_rejects_unencodable_keys(backend, key):
    assert not backend.setButtonMapping(0, "macro", [[1, key], [2, key]])
    assert "cannot be encoded" in backend.error
    assert not backend.dirty


def test_g600_placeholder_requires_modifiers():
    with pytest.raises(ValueError, match="at least one modifier"):
        validate_macro([[1, 0], [2, 0]], g600=True)
    with pytest.raises(ValueError):
        validate_macro([[1, 0], [2, 0]], g600=False)


@pytest.mark.parametrize(
    "duration,accepted",
    [
        (0, True),
        (1000, True),
        (15000, True),
        (15001, False),
        (16000, False),
        (2500, False),
    ],
)
def test_g600_led_duration_matches_hardware_encoding(backend, duration, accepted):
    assert backend.setLed(0, "effectDuration", duration) is accepted
    assert backend.selectedProfile["leds"][0]["effectDurationMaximum"] == 15000
    assert backend.selectedProfile["leds"][0]["effectDurationStep"] == 1000


def test_batch_context_guard_is_atomic(backend):
    contexts = backend.captureMappingContexts()
    backend.setButtonMapping(0, "button", 4)
    backend.setButtonMapping(21, "button", 5)
    forged = deepcopy(contexts)
    forged[-1]["index"] = 20
    assert not backend.resetMappings(forged)
    assert backend.mappingDirty(contexts[0]) and backend.mappingDirty(contexts[20])
    assert not backend.applyMappings(forged)
    assert not backend._transport.calls
    backend.selectProfile(1)
    assert not backend.applyMappings(contexts)
    assert not backend.resetMappings(contexts)


def test_page_profile_activation_preserves_all_other_fields(backend, app):
    backend.selectDevice(1)
    backend.setProfileName("Other profile pending")
    backend.selectProfile(1)
    backend.setProfileActive()
    backend.setProfileName("New active name")
    backend.setDpi(0, 800, 1600)
    backend.setButtonMapping(0, "key", 30)
    context = backend.capturePageContext("profiles")
    assert backend.applyPage(context)
    wait_for(app, lambda: not backend.busy)
    assert {op.member for op in backend._transport.calls} == {"Name", "SetActive"}
    assert [p["index"] for p in backend.profiles if p["active"]] == [1]
    assert not backend.pageDirty(context)
    assert backend.selectedProfile["resolutions"][0]["y"] == 1600
    assert backend.selectedProfile["buttons"][0]["actionValue"] == 30
    assert backend.profiles[0]["name"] == "Other profile pending"
    assert backend.dirty


def test_page_reset_activation_only_resets_active_fields(backend):
    backend.selectDevice(1)
    backend.selectProfile(1)
    backend.setProfileActive()
    backend.setButtonMapping(0, "key", 30)
    context = backend.capturePageContext("profiles")
    assert backend.resetPage(context)
    assert [p["index"] for p in backend.profiles if p["active"]] == [0]
    assert backend.selectedProfile["buttons"][0]["actionValue"] == 30


def test_delayed_resync_never_overwrites_newer_assignment_input(backend, app):
    context = backend.captureMappingContext(21)
    assert backend.applyMapping(context, "button", 5)
    wait_for(app, lambda: not backend.busy)
    assert backend.stageMapping(context, "button", 4)
    backend._transport.objects[context["buttonPath"]][1]["Mapping"] = [1, 1]
    backend._on_event("resync")
    wait_for(app, lambda: backend.commitState == "failed")
    assert backend.selectedProfile["buttons"][20]["actionValue"] == 4
    assert backend.dirty


def test_delayed_resync_never_overwrites_newer_page_input(backend, app):
    context = backend.capturePageContext("sensitivity")
    backend.setDpi(0, 800, 800)
    assert backend.applyPage(context)
    wait_for(app, lambda: not backend.busy)
    backend.setDpi(0, 1600, 1600)
    path = backend.selectedProfile["resolutions"][0]["path"]
    backend._transport.objects[path][1]["Resolution"] = 400
    backend._on_event("resync")
    wait_for(app, lambda: backend.commitState == "failed")
    assert backend.selectedProfile["resolutions"][0]["x"] == 1600
    assert backend.dirty


def test_page_noop_never_applies_pending_assignment(backend):
    backend.setButtonMapping(0, "button", 5)
    context = backend.capturePageContext("lighting")
    assert not backend.pageDirty(context)
    assert backend.applyPage(context)
    assert not backend._transport.calls
    assert backend.profileMappingsDirty


def test_private_dbus_stale_batch_and_page_values_rejected(private_bus):
    async def scenario():
        from dbus_next.auth import AuthAnnonymous
        from qt_piper.backend import Operation, ScopedApplyError

        server, objects, paths, calls = await start_fake_daemon(private_bus)
        transport = DBusTransport(bus_address=private_bus, auth=AuthAnnonymous())
        try:
            before = await transport.snapshot()
            profile = before[1]["profiles"][0]
            button = profile["buttons"][0]
            objects[button["path"]][1]["Mapping"] = [3, 31]
            with pytest.raises(ScopedApplyError, match="assignment changed"):
                await transport.apply_mappings(
                    [
                        Operation(
                            paths[1],
                            button["path"],
                            "Button",
                            "Mapping",
                            [3, 30],
                            "(uv)",
                        )
                    ],
                    {button["path"]: [button["actionId"], button["actionValue"]]},
                )
            objects[profile["path"]][1]["Debounce"] = 12
            with pytest.raises(ScopedApplyError, match="settings changed"):
                await transport.apply_page(
                    [
                        Operation(
                            paths[1], profile["path"], "Profile", "Debounce", 8, "i"
                        )
                    ],
                    {
                        "devicePath": paths[1],
                        "profilePath": profile["path"],
                        "scope": "advanced",
                    },
                    before,
                )
            assert not any(c.member in ("Set", "Commit") for c in calls)
        finally:
            await transport.close()
            server.disconnect()

    asyncio.run(scenario())


def test_background_refresh_cannot_hide_stale_main_assignment_draft(backend, app):
    backend.setButtonMapping(21, "button", 5)
    path = backend.selectedProfile["buttons"][20]["path"]
    backend._transport.objects[path][1]["Mapping"] = [1, 4]
    backend.refresh()
    wait_for(app, lambda: not backend.busy)
    assert backend.selectedProfile["buttons"][20]["actionValue"] == 5
    assert not backend.applyMappings(backend.captureMappingContexts())
    assert "changed outside" in backend.error
    assert not backend._transport.calls
    # Revert uses the newly observed baseline, not the stale one from entry.
    assert backend.resetMappings(backend.captureMappingContexts())
    assert backend.selectedProfile["buttons"][20]["actionValue"] == 4


def test_background_refresh_cannot_hide_stale_page_draft(backend, app):
    backend.setReportRate(500)
    path = backend.selectedProfile["path"]
    backend._transport.objects[path][1]["ReportRate"] = 250
    backend.refresh()
    wait_for(app, lambda: not backend.busy)
    context = backend.capturePageContext("sensitivity")
    assert not backend.applyPage(context)
    assert "changed outside" in backend.error
    assert not backend._transport.calls
    assert backend.resetPage(context)
    assert backend.selectedProfile["reportRate"] == 250
    assert not backend.pageDirty(context)


def test_explicit_new_recording_after_conflict_resolves_only_that_assignment(
    backend, app
):
    backend.setButtonMapping(21, "button", 5)
    backend.setReportRate(500)
    button_path = backend.selectedProfile["buttons"][20]["path"]
    profile_path = backend.selectedProfile["path"]
    backend._transport.objects[button_path][1]["Mapping"] = [1, 4]
    backend._transport.objects[profile_path][1]["ReportRate"] = 250
    backend.refresh()
    wait_for(app, lambda: not backend.busy)
    context = backend.captureMappingContext(21)
    assert backend.stageMapping(context, "button", 5)
    assert backend.applyMappings(backend.captureMappingContexts())
    wait_for(app, lambda: not backend.busy)
    assert len(backend._transport.calls) == 1
    assert not backend.applyPage(backend.capturePageContext("sensitivity"))
    assert "changed outside" in backend.error


def test_validate_mapping_is_read_only_even_when_normalizing_modifiers(backend):
    backend.setReportRate(500)
    context = backend.captureMappingContext(21)
    original_events = [[1, 29], [2, 29]]
    events = deepcopy(original_events)
    before = (
        deepcopy(backend._base),
        deepcopy(backend._draft),
        deepcopy(backend._latest),
        deepcopy(backend._mapping_contexts),
        deepcopy(backend._external_conflicts),
        backend.error,
        backend.status,
        backend.commitState,
        backend.dirty,
        deepcopy(backend._transport.objects),
        deepcopy(backend._transport.calls),
    )
    notifications = []
    backend.changed.connect(lambda: notifications.append("changed"))
    backend.mappingApplyFinished.connect(lambda *args: notifications.append(args))
    assert backend.validateMapping(context, "macro", events) == ""
    after = (
        backend._base,
        backend._draft,
        backend._latest,
        backend._mapping_contexts,
        backend._external_conflicts,
        backend.error,
        backend.status,
        backend.commitState,
        backend.dirty,
        backend._transport.objects,
        backend._transport.calls,
    )
    assert before == after
    assert events == original_events
    assert not notifications


@pytest.mark.parametrize(
    "events,message",
    [
        ([[1, 30], [3, 100], [2, 30]], "one key"),
        ([[1, 164], [2, 164]], "cannot be encoded"),
        ([[1, 30], [2, 30], [1, 48], [2, 48]], "one key"),
        ([[1, 30]], "matching release"),
        ([[1, 29], [1, 30], [2, 29], [2, 30]], "main key before"),
    ],
)
def test_validate_mapping_reports_g600_constraints_without_mutation(
    backend, events, message
):
    context = backend.captureMappingContext(21)
    before = deepcopy(backend._draft)
    original_error = backend.error
    assert message in backend.validateMapping(context, "macro", events)
    assert backend._draft == before
    assert backend.error == original_error
    assert not backend._transport.calls
    assert not backend.dirty


def test_validate_mapping_accepts_generic_timed_sequence_without_staging(backend):
    backend.selectDevice(1)
    context = backend.captureMappingContext(0)
    before = deepcopy(backend._draft)
    assert (
        backend.validateMapping(
            context, "macro", [[1, 30], [2, 30], [3, 100], [1, 48], [2, 48]]
        )
        == ""
    )
    assert backend._draft == before
    assert not backend.dirty
    assert not backend._transport.calls


def test_validate_mapping_accepts_reserved_zero_chord_without_mutation(backend):
    context = backend.captureMappingContext(5)
    events = [[1, 29], [1, 42], [1, 0], [2, 0], [2, 42], [2, 29]]
    before = deepcopy(backend._draft)
    assert backend.validateMapping(context, "macro", events) == ""
    assert backend._draft == before
    assert not backend.dirty


def test_validate_mapping_handles_invalid_and_stale_contexts_without_error_signals(
    backend,
):
    context = backend.captureMappingContext(21)
    notifications = []
    backend.changed.connect(lambda: notifications.append("changed"))
    assert "stale" in backend.validateMapping({}, "macro", [[1, 30], [2, 30]])
    assert "stale" in backend.validateMapping(None, "macro", [[1, 30], [2, 30]])
    assert "stale" in backend.validateMapping(dict(context, index=20), "button", 1)
    assert not notifications
    backend.selectProfile(1)
    notifications.clear()
    assert "stale" in backend.validateMapping(context, "button", 1)
    assert not notifications
    assert not backend._transport.calls


def test_mapping_key_choices_cover_all_g600_encodable_keys(backend):
    from qt_piper.backend import G600_KEYBOARD_CODES

    context = backend.captureMappingContext(21)
    choices = backend.mappingKeyChoices(context)
    assert len(choices) == 135
    assert [choice["value"] for choice in choices] == sorted(G600_KEYBOARD_CODES)
    assert {choice["value"]: choice["label"] for choice in choices}[355] == "Key 355"
    assert not {0, 164, 165, 767}.intersection(c["value"] for c in choices)
    for choice in choices:
        key = choice["value"]
        assert backend.validateMapping(context, "macro", [[1, key], [2, key]]) == ""


def test_mapping_key_choices_cover_generic_range_and_preserve_values(backend):
    backend.selectDevice(1)
    context = backend.captureMappingContext(0)
    assert backend.stageMapping(context, "key", 767)
    choices = backend.mappingKeyChoices(context)
    assert [choice["value"] for choice in choices] == list(range(1, 768))
    assert choices[-1] == {"value": 767, "label": "Key 767"}
    assert backend.mappingForContext(context)["actionValue"] == 767
    assert not backend._transport.calls


def test_mapping_key_choices_show_zero_only_for_valid_existing_g600_chord(backend):
    context = backend.captureMappingContext(21)
    assert 0 not in {choice["value"] for choice in backend.mappingKeyChoices(context)}
    assert backend.stageMapping(context, "macro", [[1, 29], [2, 29]])
    choices = backend.mappingKeyChoices(context)
    assert len(choices) == 136
    assert choices[0] == {
        "value": 0,
        "label": "Reserved 0 (modifier-chord placeholder)",
        "placeholder": True,
        "selectable": False,
    }
    assert backend.validateMapping(context, "macro", [[1, 0], [2, 0]])
    # Invalid daemon data must not make reserved zero an ordinary key choice.
    backend._item("buttons", 21)["actionValue"] = [[1, 0], [2, 0]]
    assert len(backend.mappingKeyChoices(context)) == 135


def test_mapping_key_choices_are_read_only_and_reject_stale_contexts(backend):
    context = backend.captureMappingContext(21)
    backend.setReportRate(500)
    notifications = []
    backend.changed.connect(lambda: notifications.append("changed"))
    before = deepcopy(
        (
            backend._base,
            backend._draft,
            backend._latest,
            backend._mapping_contexts,
            backend._external_conflicts,
            backend.error,
            backend.status,
            backend.commitState,
            backend._transport.objects,
            backend._transport.calls,
        )
    )
    assert backend.mappingKeyChoices(context)
    assert not backend.mappingKeyChoices(None)
    assert not backend.mappingKeyChoices({})
    assert not backend.mappingKeyChoices(dict(context, index=20))
    assert before == (
        backend._base,
        backend._draft,
        backend._latest,
        backend._mapping_contexts,
        backend._external_conflicts,
        backend.error,
        backend.status,
        backend.commitState,
        backend._transport.objects,
        backend._transport.calls,
    )
    assert not notifications
    backend.selectProfile(1)
    notifications.clear()
    assert not backend.mappingKeyChoices(context)
    assert not notifications
    assert not backend._transport.calls
