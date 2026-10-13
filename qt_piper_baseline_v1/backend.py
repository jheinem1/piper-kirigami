# SPDX-License-Identifier: GPL-2.0-or-later
"""Qt/QML model and asynchronous ratbagd API-v2 client.

No Gio, GTK, root access or input-device file access is involved. dbus-next
runs on a private asyncio thread; Qt model changes only happen on the GUI
thread. Edits are staged locally until Apply. D-Bus property changes are not
transactions: a failed Apply can leave partial settings in the daemon cache.
The UI preserves edits for retry and explicitly reports that possibility.

Commit is asynchronous in ratbagd. A successful method reply means submitted,
not hardware verified. A later Device.Resync signal is always surfaced as an
error and the model is reloaded from ratbagd.
"""

from __future__ import annotations

import asyncio
import configparser
from copy import deepcopy
from dataclasses import dataclass
from functools import wraps
import os
from pathlib import Path
import threading
from typing import Any

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot
from PySide6.QtGui import QColor

from .fixtures import fixture_objects

API_VERSION = 2
SPECIAL_BASE = 1 << 30
ACTION_IDS = {"none": 0, "button": 1, "special": 2, "key": 3, "macro": 4}
ACTION_NAMES = {v: k for k, v in ACTION_IDS.items()}
SPECIAL_LABELS = {
    SPECIAL_BASE + i: label
    for i, label in enumerate(
        [
            "Unknown",
            "Double click",
            "Wheel left",
            "Wheel right",
            "Wheel up",
            "Wheel down",
            "Ratchet mode",
            "Cycle DPI up",
            "Cycle DPI down",
            "DPI up",
            "DPI down",
            "DPI shift",
            "Default DPI",
            "Cycle profile up",
            "Cycle profile down",
            "Profile up",
            "Profile down",
            "G-Shift / second mode",
            "Battery level",
        ]
    )
}
KEY_LABELS = {
    1: "Esc",
    2: "1",
    3: "2",
    4: "3",
    5: "4",
    6: "5",
    7: "6",
    8: "7",
    9: "8",
    10: "9",
    11: "0",
    12: "-",
    13: "=",
    14: "Backspace",
    15: "Tab",
    16: "Q",
    17: "W",
    18: "E",
    19: "R",
    20: "T",
    21: "Y",
    22: "U",
    23: "I",
    24: "O",
    25: "P",
    28: "Enter",
    29: "Left Ctrl",
    30: "A",
    31: "S",
    32: "D",
    33: "F",
    34: "G",
    35: "H",
    36: "J",
    37: "K",
    38: "L",
    42: "Left Shift",
    44: "Z",
    45: "X",
    46: "C",
    47: "V",
    48: "B",
    49: "N",
    50: "M",
    54: "Right Shift",
    56: "Left Alt",
    57: "Space",
    97: "Right Ctrl",
    100: "Right Alt",
    103: "Up",
    105: "Left",
    106: "Right",
    108: "Down",
    111: "Delete",
    113: "Mute",
    114: "Volume down",
    115: "Volume up",
    125: "Left Meta",
    126: "Right Meta",
    163: "Next track",
    164: "Play/pause",
    165: "Previous track",
    **{59 + i: f"F{i + 1}" for i in range(10)},
    87: "F11",
    88: "F12",
}
MODIFIER_KEYS = {29, 42, 54, 56, 97, 100, 125, 126}
MOUSE_LABELS = {
    1: "Left click",
    2: "Right click",
    3: "Middle click",
    4: "Back",
    5: "Forward",
}


class RatbagError(RuntimeError):
    """A daemon, capability, value or transport error suitable for display."""


def unwrap(value):
    """Recursively unwrap dbus-next Variants without importing it in mock mode."""
    if hasattr(value, "signature") and hasattr(value, "value"):
        return unwrap(value.value)
    if isinstance(value, dict):
        return {k: unwrap(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [unwrap(v) for v in value]
    return value


def button_layer(model, index):
    if model.startswith("usb:046d:c24a"):
        if 0 <= index < 20:
            return "normal", index
        if 21 <= index < 41:
            return "gshift", index - 21
        return None  # Index 20 is a colour buffer, not a button.
    return "normal", index


def mapping_label(action_type, value):
    if action_type == "none":
        return "Disabled"
    if action_type == "button":
        return MOUSE_LABELS.get(value, f"Mouse button {value}")
    if action_type == "special":
        return SPECIAL_LABELS.get(value, f"Special action {value}")
    if action_type == "key":
        return KEY_LABELS.get(value, f"Key {value}")
    if action_type == "macro":
        presses = [KEY_LABELS.get(v, f"Key {v}") for t, v in value if t == 1]
        waits = any(t == 3 for t, _ in value)
        label = " + ".join(presses) or "Empty macro"
        return label + (" (timed)" if waits else "")
    return "Unknown mapping"


def svg_for_model(model, device_type=2):
    config = configparser.ConfigParser(interpolation=None)
    config.read(Path(__file__).resolve().parents[1] / "data/svgs/svg-lookup.ini")
    parts = model.split(":")
    match_model = ":".join(parts[:3]) if len(parts) == 4 and parts[3] == "0" else model
    for section in config.sections():
        matches = config.get(section, "DeviceMatch", fallback="").split(";")
        if match_model in matches:
            return config.get(section, "Svg")
    return "fallback.svg"


async def read_devices(get_properties, device_paths):
    """Normalize real daemon or fixture properties into the same QML model."""
    devices = []
    for dpath in device_paths:
        raw = unwrap(await get_properties(dpath, "Device"))
        model = raw.get("Model", "unknown")
        device = {
            "path": dpath,
            "id": dpath,
            "name": raw.get("Name", "Unknown device"),
            "model": model,
            "deviceType": raw.get("DeviceType", 2),
            "firmwareVersion": raw.get("FirmwareVersion", ""),
            "svg": svg_for_model(model, raw.get("DeviceType", 2)),
            "hasGShift": model.startswith("usb:046d:c24a"),
            "profiles": [],
        }
        device["diagram"] = device["svg"]
        for ppath in raw.get("Profiles", []):
            props = unwrap(await get_properties(ppath, "Profile"))
            caps = props.get("Capabilities", [])
            profile = {
                "path": ppath,
                "index": props.get("Index", 0),
                "name": props.get("Name") or f"Profile {props.get('Index', 0) + 1}",
                "rawName": props.get("Name", ""),
                "capabilities": caps,
                "canRename": 100 in caps,
                "canDisable": 102 in caps,
                "active": props.get("IsActive", False),
                "isActive": props.get("IsActive", False),
                "enabled": not props.get("Disabled", False),
                "disabled": props.get("Disabled", False),
                "daemonDirty": props.get("IsDirty", False),
                "reportRate": props.get("ReportRate", 0),
                "reportRates": props.get("ReportRates", []),
                "angleSnapping": props.get("AngleSnapping", -1),
                "debounce": props.get("Debounce", -1),
                "debounces": props.get("Debounces", []),
                "resolutions": [],
                "buttons": [],
                "leds": [],
            }
            for rpath in props.get("Resolutions", []):
                r = unwrap(await get_properties(rpath, "Resolution"))
                value = r.get("Resolution", 0)
                separate = isinstance(value, list)
                values = r.get("Resolutions", [])
                profile["resolutions"].append(
                    {
                        "path": rpath,
                        "index": r["Index"],
                        "x": value[0] if separate else value,
                        "y": value[1] if separate else value,
                        "dpi": value[0] if separate else value,
                        "separateXY": separate,
                        "capabilities": r.get("Capabilities", []),
                        "values": values,
                        "minimum": min(values) if values else 0,
                        "maximum": max(values) if values else 0,
                        "active": r.get("IsActive", False),
                        "isActive": r.get("IsActive", False),
                        "default": r.get("IsDefault", False),
                        "isDefault": r.get("IsDefault", False),
                        "enabled": not r.get("IsDisabled", False),
                        "disabled": r.get("IsDisabled", False),
                        "canDisable": 2 in r.get("Capabilities", []),
                    }
                )
            for bpath in props.get("Buttons", []):
                b = unwrap(await get_properties(bpath, "Button"))
                layer = button_layer(model, b["Index"])
                if layer is None:
                    continue
                action_id, value = b.get("Mapping", [0, 0])
                action_type = ACTION_NAMES.get(action_id, "unknown")
                profile["buttons"].append(
                    {
                        "path": bpath,
                        "index": b["Index"],
                        "physicalIndex": layer[1],
                        "displayIndex": layer[1],
                        "layer": layer[0],
                        "label": f"Button {layer[1] + 1}",
                        "actionType": action_type,
                        "actionId": action_id,
                        "actionValue": value,
                        "actionLabel": mapping_label(action_type, value),
                        "actionTypes": [
                            ACTION_NAMES[i]
                            for i in b.get("ActionTypes", [])
                            if i in ACTION_NAMES
                        ],
                        "actionTypeIds": b.get("ActionTypes", []),
                        "macro": value if action_type == "macro" else [],
                    }
                )
            for lpath in props.get("Leds", []):
                led = unwrap(await get_properties(lpath, "Led"))
                rgb = led.get("Color", [0, 0, 0])
                profile["leds"].append(
                    {
                        "path": lpath,
                        "index": led["Index"],
                        "mode": led.get("Mode", 0),
                        "modes": led.get("Modes", []),
                        "color": f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}",
                        "colorRgb": rgb,
                        "colorDepth": led.get("ColorDepth", 0),
                        "brightness": led.get("Brightness", 0),
                        "effectDuration": led.get("EffectDuration", 0),
                        "canBrightness": not device["hasGShift"],
                    }
                )
            device["profiles"].append(profile)
        devices.append(device)
    return devices


@dataclass(frozen=True)
class Operation:
    device: str
    path: str
    interface: str
    member: str
    value: Any = None
    signature: str = ""
    method: bool = False


def build_operations(original, edited):
    """Only emit intended differences; untouched settings never get rewritten."""
    operations = []
    old_devices = {d["path"]: d for d in original}
    for device in edited:
        old_device = old_devices.get(device["path"])
        if not old_device:
            continue
        old_profiles = {p["path"]: p for p in old_device["profiles"]}
        for profile in device["profiles"]:
            old = old_profiles.get(profile["path"])
            if not old:
                continue

            def add(
                path,
                interface,
                member,
                value=None,
                signature="",
                method=False,
                device_path=device["path"],
            ):
                operations.append(
                    Operation(
                        device_path,
                        path,
                        interface,
                        member,
                        value,
                        signature,
                        method,
                    )
                )

            for field, member, signature in [
                ("rawName", "Name", "s"),
                ("disabled", "Disabled", "b"),
                ("reportRate", "ReportRate", "u"),
                ("angleSnapping", "AngleSnapping", "i"),
                ("debounce", "Debounce", "i"),
            ]:
                if profile[field] != old[field]:
                    add(profile["path"], "Profile", member, profile[field], signature)
            if profile["active"] and not old["active"]:
                add(profile["path"], "Profile", "SetActive", method=True)
            for collection, interface in [
                ("resolutions", "Resolution"),
                ("buttons", "Button"),
                ("leds", "Led"),
            ]:
                previous = {o["path"]: o for o in old[collection]}
                for obj in profile[collection]:
                    before = previous.get(obj["path"])
                    if not before:
                        continue
                    if interface == "Resolution":
                        if (obj["x"], obj["y"]) != (before["x"], before["y"]):
                            value = (
                                [obj["x"], obj["y"]] if obj["separateXY"] else obj["x"]
                            )
                            add(obj["path"], interface, "Resolution", value, "v")
                        for field, member in [
                            ("active", "SetActive"),
                            ("default", "SetDefault"),
                        ]:
                            if obj[field] and not before[field]:
                                add(obj["path"], interface, member, method=True)
                        if obj["disabled"] != before["disabled"]:
                            add(
                                obj["path"],
                                interface,
                                "IsDisabled",
                                obj["disabled"],
                                "b",
                            )
                    elif interface == "Button":
                        if (obj["actionType"], obj["actionValue"]) != (
                            before["actionType"],
                            before["actionValue"],
                        ):
                            add(
                                obj["path"],
                                interface,
                                "Mapping",
                                [ACTION_IDS[obj["actionType"]], obj["actionValue"]],
                                "(uv)",
                            )
                    else:
                        for field, member, signature in [
                            ("mode", "Mode", "u"),
                            ("colorRgb", "Color", "(uuu)"),
                            ("brightness", "Brightness", "u"),
                            ("effectDuration", "EffectDuration", "u"),
                        ]:
                            if obj[field] != before[field]:
                                add(
                                    obj["path"],
                                    interface,
                                    member,
                                    obj[field],
                                    signature,
                                )
    # Enable before activation, disable after activation. Property writes precede methods.
    return sorted(
        operations,
        key=lambda o: (
            2
            if o.member in ("Disabled", "IsDisabled") and o.value
            else 1 if o.method else 0
        ),
    )


class MockTransport:
    """Stateful fixture transport using precisely the production read path."""

    def __init__(self, fixture="g600"):
        self.objects, self.device_paths = fixture_objects(fixture)
        self.connected = True
        self.fail_next_commit = False
        self.calls = []
        self.on_event = None

    async def snapshot(self):
        if not self.connected:
            raise RatbagError("Demo device disconnected.")

        async def get(path, interface):
            return deepcopy(self.objects[path][1])

        return await read_devices(get, self.device_paths)

    async def apply(self, operations):
        if not self.connected:
            raise RatbagError("Demo device disconnected.")
        if self.fail_next_commit:
            self.fail_next_commit = False
            raise RatbagError(
                "Simulated device write failure. Your edits are kept for retry."
            )
        for op in operations:
            self.calls.append(op)
            props = self.objects[op.path][1]
            if op.method:
                field = "IsActive" if op.member == "SetActive" else "IsDefault"
                prefix = op.path.rsplit("/", 1)[0]
                for path, (interface, sibling) in self.objects.items():
                    if interface == op.interface and path.rsplit("/", 1)[0] == prefix:
                        sibling[field] = path == op.path
            else:
                props[op.member] = deepcopy(op.value)
        return await self.snapshot()

    async def close(self):
        pass


class DBusTransport:
    """Real system-bus ratbagd client. Optional bus_address is for integration tests."""

    def __init__(self, service=None, bus_address=None, timeout=5.0, auth=None):
        self.service = service or (
            "org.freedesktop.ratbag_devel1"
            if os.getenv("RATBAG_TEST")
            else "org.freedesktop.ratbag1"
        )
        self.root = "/" + self.service.replace(".", "/")
        self.bus_address = bus_address
        self.auth = auth
        self.timeout = timeout
        self.bus = None
        self.on_event = None
        self._watch_task = None
        self._resync_count = 0

    async def _connect(self):
        if self.bus is not None and self.bus.connected:
            return
        try:
            from dbus_next.aio import MessageBus
            from dbus_next import BusType
        except ImportError as exc:
            raise RatbagError(
                "Install dbus-next to connect to ratbagd. Demo mode remains available."
            ) from exc
        bus = (
            MessageBus(bus_address=self.bus_address, auth=self.auth)
            if self.bus_address
            else MessageBus(bus_type=BusType.SYSTEM)
        )
        self.bus = await asyncio.wait_for(bus.connect(), self.timeout)
        self.bus.add_message_handler(self._message)
        for rule in [
            f"type='signal',sender='{self.service}',interface='org.freedesktop.DBus.Properties'",
            f"type='signal',sender='{self.service}',interface='{self.service}.Device',member='Resync'",
            f"type='signal',sender='org.freedesktop.DBus',interface='org.freedesktop.DBus',member='NameOwnerChanged',arg0='{self.service}'",
        ]:
            await self._call(
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "AddMatch",
                "s",
                [rule],
                destination="org.freedesktop.DBus",
            )
        self._watch_task = asyncio.create_task(self._watch_disconnect())

    async def _watch_disconnect(self):
        try:
            await self.bus.wait_for_disconnect()
        except Exception:
            pass
        if self.on_event:
            self.on_event("disconnected")

    def _message(self, msg):
        from dbus_next import MessageType

        if msg.message_type != MessageType.SIGNAL:
            return False
        if (
            msg.interface == "org.freedesktop.DBus"
            and msg.member == "NameOwnerChanged"
            and len(msg.body) == 3
            and msg.body[0] == self.service
        ):
            if self.on_event:
                self.on_event("changed" if msg.body[2] else "disconnected")
        elif msg.member == "Resync" and msg.interface == self.service + ".Device":
            self._resync_count += 1
            if self.on_event:
                self.on_event("resync")
        elif (
            msg.interface == "org.freedesktop.DBus.Properties"
            and msg.member == "PropertiesChanged"
            and msg.body
            and str(msg.body[0]).startswith(self.service + ".")
            and self.on_event
        ):
            self.on_event("changed")
        return False

    async def _call(
        self, path, interface, member, signature="", body=None, destination=None
    ):
        from dbus_next import Message, MessageType

        reply = await asyncio.wait_for(
            self.bus.call(
                Message(
                    destination=destination or self.service,
                    path=path,
                    interface=interface,
                    member=member,
                    signature=signature,
                    body=body or [],
                )
            ),
            self.timeout,
        )
        if reply.message_type == MessageType.ERROR:
            raise RatbagError(
                f"{reply.error_name}: {' '.join(str(v) for v in reply.body)}"
            )
        return reply.body

    async def _get(self, path, interface):
        result = await self._call(
            path,
            "org.freedesktop.DBus.Properties",
            "GetAll",
            "s",
            [self.service + "." + interface],
        )
        return unwrap(result[0])

    async def snapshot(self):
        await self._connect()
        manager = await self._get(self.root, "Manager")
        if manager.get("APIVersion") != API_VERSION:
            raise RatbagError(
                f"Incompatible ratbagd API {manager.get('APIVersion', 'unknown')}; this client requires API {API_VERSION}."
            )
        return await read_devices(self._get, manager.get("Devices", []))

    async def apply(self, operations):
        from dbus_next import Variant

        await self._connect()
        resync_count = self._resync_count
        devices = []
        for op in operations:
            if op.method:
                result = await self._call(
                    op.path, self.service + "." + op.interface, op.member
                )
                if result and isinstance(result[0], int) and result[0] != 0:
                    raise RatbagError(
                        f"ratbagd rejected {op.member} (code {result[0]})."
                    )
            else:
                value = op.value
                if op.member == "Resolution":
                    value = Variant("(uu)" if isinstance(value, list) else "u", value)
                elif op.member == "Mapping":
                    action_id, payload = value
                    value = [
                        action_id,
                        Variant("a(uu)" if action_id == 4 else "u", payload),
                    ]
                await self._call(
                    op.path,
                    "org.freedesktop.DBus.Properties",
                    "Set",
                    "ssv",
                    [
                        self.service + "." + op.interface,
                        op.member,
                        Variant(op.signature, value),
                    ],
                )
            # Some daemon setters historically returned success even when a
            # capability/value was rejected. Confirm its cache before Commit.
            observed = await self._get(op.path, op.interface)
            if self._resync_count != resync_count:
                raise RatbagError(
                    "ratbagd reported a device resynchronization during Apply; the remaining writes and Commit were aborted."
                )
            member = (
                ("IsActive" if op.member == "SetActive" else "IsDefault")
                if op.method
                else op.member
            )
            expected = True if op.method else op.value
            if observed.get(member) != expected:
                raise RatbagError(
                    f"ratbagd did not accept {op.interface}.{op.member}; no Commit was sent."
                )
            if op.device not in devices:
                devices.append(op.device)
        for device in devices:
            await self._call(device, self.service + ".Device", "Commit")
        return await self.snapshot()

    async def close(self):
        self.on_event = None
        if self._watch_task:
            self._watch_task.cancel()
        if self.bus:
            self.bus.disconnect()


class AsyncRunner:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self._run, daemon=True, name="piper-ratbag-dbus"
        )
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
        pending = asyncio.all_tasks(self.loop)
        for task in pending:
            task.cancel()
        if pending:
            self.loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True)
            )
        self.loop.close()

    def submit(self, coroutine, callback):
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)

        def finished(result):
            try:
                callback(True, result.result())
            except Exception as exc:
                callback(False, str(exc) or type(exc).__name__)

        future.add_done_callback(finished)

    def close(self, transport):
        future = asyncio.run_coroutine_threadsafe(transport.close(), self.loop)
        try:
            future.result(timeout=2)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=2)


def edit_action(function):
    @wraps(function)
    def guarded(self, *args):
        if not self._connected or self._busy:
            self._set_error(
                "Connect a device and wait for the current operation to finish."
            )
            return False
        try:
            function(self, *args)
        except (ValueError, TypeError, KeyError, IndexError, RatbagError) as exc:
            self._set_error(str(exc))
            return False
        self._error = ""
        self._commit_state = "staged" if self.dirty else "idle"
        self._status = "Unapplied changes" if self.dirty else "No pending changes"
        self.changed.emit()
        return True

    return guarded


class Backend(QObject):
    """QML-facing device model. All exposed maps are immutable snapshots."""

    changed = Signal()
    _result = Signal(str, bool, object)
    _transport_event = Signal(str)

    def __init__(
        self, mock=False, fixture="g600", parent=None, transport=None, autostart=True
    ):
        super().__init__(parent)
        self._mock = bool(mock or isinstance(transport, MockTransport))
        self._transport = transport or (
            MockTransport(fixture) if mock else DBusTransport()
        )
        self._runner = AsyncRunner()
        self._base = []
        self._draft = []
        self._latest = []
        self._device_index = -1
        self._profile_index = -1
        self._connected = False
        self._busy = False
        self._error = ""
        self._status = "Starting demo" if self._mock else "Connecting to ratbagd"
        self._commit_state = "idle"
        self._closed = False
        self._resync_pending = False
        self._partial_apply = False
        self._partial_devices = set()
        self._refresh_queued = False
        self._result.connect(self._on_result)
        self._transport_event.connect(self._on_event)
        self._transport.on_event = self._transport_event.emit
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(150)
        self._refresh_timer.timeout.connect(self.refresh)
        if autostart:
            QTimer.singleShot(0, self.refresh)

    @Property("QVariantList", notify=changed)
    def devices(self):
        return deepcopy(self._draft)

    @Property("QVariantMap", notify=changed)
    def selectedDevice(self):
        return deepcopy(self._device())

    @Property("QVariantList", notify=changed)
    def profiles(self):
        return deepcopy(self._device().get("profiles", []))

    @Property("QVariantMap", notify=changed)
    def selectedProfile(self):
        return deepcopy(self._profile())

    @Property(int, notify=changed)
    def selectedDeviceIndex(self):
        return self._device_index

    @Property(int, notify=changed)
    def selectedProfileIndex(self):
        return self._profile_index

    @Property(bool, notify=changed)
    def connected(self):
        return self._connected

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy

    @Property(bool, notify=changed)
    def dirty(self):
        return bool(build_operations(self._base, self._draft))

    @Property(str, notify=changed)
    def error(self):
        return self._error

    @Property(str, notify=changed)
    def status(self):
        return self._status

    @Property(str, notify=changed)
    def commitState(self):
        return self._commit_state

    @Property(bool, constant=True)
    def mock(self):
        return self._mock

    @Property("QVariantList", constant=True)
    def actionChoices(self):
        return [
            {"value": value, "label": label}
            for value, label in [
                ("button", "Mouse button"),
                ("key", "Keyboard key"),
                ("special", "Special action"),
                ("macro", "Macro / key combination"),
                ("none", "Disabled"),
            ]
        ]

    @Property("QVariantList", notify=changed)
    def specialActions(self):
        g600 = self._device().get("hasGShift", False)
        return [
            {"value": k, "label": v}
            for k, v in SPECIAL_LABELS.items()
            if k != SPECIAL_BASE
            and (not g600 or k - SPECIAL_BASE in (7, 9, 10, 11, 13, 17))
        ]

    @Property("QVariantList", constant=True)
    def keyChoices(self):
        return [{"value": k, "label": v} for k, v in sorted(KEY_LABELS.items())]

    def _device(self):
        return (
            self._draft[self._device_index]
            if 0 <= self._device_index < len(self._draft)
            else {}
        )

    def _profile(self):
        profiles = self._device().get("profiles", [])
        return (
            profiles[self._profile_index]
            if 0 <= self._profile_index < len(profiles)
            else {}
        )

    def _item(self, collection, index):
        for item in self._profile().get(collection, []):
            if item["index"] == index:
                return item
        raise ValueError(f"No {collection} entry with index {index}.")

    def _set_error(self, message):
        self._error = message
        self.changed.emit()

    @Slot(int)
    def selectDevice(self, index):
        if 0 <= index < len(self._draft):
            self._device_index = index
            self._profile_index = next(
                (i for i, p in enumerate(self._device()["profiles"]) if p["active"]), 0
            )
            self.changed.emit()

    @Slot(int)
    def selectProfile(self, index):
        if 0 <= index < len(self._device().get("profiles", [])):
            self._profile_index = index
            self.changed.emit()

    @Slot(result=bool)
    @edit_action
    def setProfileActive(self):
        profile = self._profile()
        if not profile or profile["disabled"]:
            raise ValueError("Enable this profile before activating it.")
        for candidate in self._device()["profiles"]:
            candidate["active"] = candidate["isActive"] = candidate is profile

    @Slot(str, result=bool)
    @edit_action
    def setProfileName(self, name):
        profile = self._profile()
        if not profile.get("canRename"):
            raise ValueError("This device does not support profile names.")
        if not name.strip() or len(name.encode("utf-8")) > 255:
            raise ValueError("Use a nonempty profile name of at most 255 UTF-8 bytes.")
        profile["name"] = profile["rawName"] = name.strip()

    @Slot(bool, result=bool)
    @edit_action
    def setProfileEnabled(self, enabled):
        profile = self._profile()
        if not profile.get("canDisable"):
            raise ValueError("This device does not support disabling profiles.")
        if not enabled and profile["active"]:
            raise ValueError("The active profile cannot be disabled.")
        profile["enabled"], profile["disabled"] = enabled, not enabled

    @Slot(int, result=bool)
    @edit_action
    def setReportRate(self, rate):
        profile = self._profile()
        if rate not in profile.get("reportRates", []):
            raise ValueError("Choose a report rate supported by this profile.")
        profile["reportRate"] = rate

    @Slot(int, result=bool)
    @edit_action
    def setAngleSnapping(self, value):
        profile = self._profile()
        if profile.get("angleSnapping", -1) < 0 or value not in (0, 1):
            raise ValueError("Angle snapping is not supported or the value is invalid.")
        profile["angleSnapping"] = value

    @Slot(int, result=bool)
    @edit_action
    def setDebounce(self, value):
        profile = self._profile()
        if value not in profile.get("debounces", []):
            raise ValueError("Choose a supported debounce value.")
        profile["debounce"] = value

    @Slot(int, int, int, result=bool)
    @edit_action
    def setDpi(self, index, x, y):
        item = self._item("resolutions", index)
        if x not in item["values"] or y not in item["values"]:
            raise ValueError("Choose DPI values reported as supported by this device.")
        if not item["separateXY"] and x != y:
            raise ValueError("This device uses the same DPI for both axes.")
        item["x"], item["y"], item["dpi"] = x, y, x

    @Slot(int, result=bool)
    @edit_action
    def setResolutionActive(self, index):
        item = self._item("resolutions", index)
        if item["disabled"]:
            raise ValueError("Enable this DPI stage before activating it.")
        for candidate in self._profile()["resolutions"]:
            candidate["active"] = candidate["isActive"] = candidate is item

    @Slot(int, result=bool)
    @edit_action
    def setResolutionDefault(self, index):
        item = self._item("resolutions", index)
        if item["disabled"]:
            raise ValueError("Enable this DPI stage before making it the default.")
        for candidate in self._profile()["resolutions"]:
            candidate["default"] = candidate["isDefault"] = candidate is item

    @Slot(int, bool, result=bool)
    @edit_action
    def setResolutionEnabled(self, index, enabled):
        item = self._item("resolutions", index)
        if not item["canDisable"]:
            raise ValueError("This device does not support disabling DPI stages.")
        if not enabled and (item["active"] or item["default"]):
            raise ValueError("The active or default DPI stage cannot be disabled.")
        item["enabled"], item["disabled"] = enabled, not enabled

    @Slot(int, str, "QVariant", result=bool)
    @edit_action
    def setButtonMapping(self, index, action_type, value):
        item = self._item("buttons", index)
        if hasattr(value, "toVariant"):
            value = value.toVariant()
        if action_type not in item["actionTypes"]:
            raise ValueError("This button does not support that action type.")
        if action_type == "none":
            value = 0
        elif action_type == "macro":
            value = validate_macro(value, g600=self._device()["hasGShift"])
        else:
            value = int(value)
            if action_type == "button" and not 1 <= value <= 32:
                raise ValueError("Mouse button must be between 1 and 32.")
            if action_type == "button" and self._device()["hasGShift"] and value > 5:
                raise ValueError(
                    "The G600 driver supports mouse button assignments 1–5."
                )
            if action_type == "key" and not 1 <= value <= 0x2FF:
                raise ValueError("Use a valid Linux input key code (1–767).")
            if action_type == "special" and value not in SPECIAL_LABELS:
                raise ValueError("Unknown special action.")
            if (
                action_type == "special"
                and self._device()["hasGShift"]
                and value - SPECIAL_BASE not in (7, 9, 10, 11, 13, 17)
            ):
                raise ValueError(
                    "The G600 driver does not support that special action."
                )
        item["actionType"], item["actionId"], item["actionValue"] = (
            action_type,
            ACTION_IDS[action_type],
            value,
        )
        item["actionLabel"] = mapping_label(action_type, value)
        item["macro"] = deepcopy(value) if action_type == "macro" else []

    @Slot(int, str, "QVariant", result=bool)
    @edit_action
    def setLed(self, index, field, value):
        item = self._item("leds", index)
        if hasattr(value, "toVariant"):
            value = value.toVariant()
        if field == "color":
            if item["colorDepth"] not in (1, 2):
                raise ValueError("This LED does not support editable RGB colour.")
            color = (
                QColor(value) if isinstance(value, (str, QColor)) else QColor(*value)
            )
            if not color.isValid():
                raise ValueError("Use a valid RGB colour.")
            rgb = [color.red(), color.green(), color.blue()]
            if item["colorDepth"] == 2:
                rgb = [255 if channel >= 128 else 0 for channel in rgb]
            item["colorRgb"] = rgb
            item["color"] = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
        elif field == "mode":
            value = int(value)
            if value not in item["modes"]:
                raise ValueError("Choose an LED mode supported by the device.")
            item[field] = value
        elif field in ("brightness", "effectDuration"):
            if field == "brightness" and not item.get("canBrightness", True):
                raise ValueError(
                    "The G600 driver does not support LED brightness; change the RGB colour instead."
                )
            value = int(value)
            maximum = 255 if field == "brightness" else 10000
            if not 0 <= value <= maximum:
                raise ValueError(f"{field} must be between 0 and {maximum}.")
            item[field] = value
        else:
            raise ValueError("Unknown LED setting.")

    def _start(self, name, coroutine):
        self._busy = True
        self.changed.emit()
        self._runner.submit(
            coroutine, lambda ok, result: self._result.emit(name, ok, result)
        )

    @Slot()
    def refresh(self):
        if self._closed:
            return
        if self._busy:
            self._refresh_queued = True
            return
        self._start("refresh", self._transport.snapshot())

    @Slot()
    def apply(self):
        if self._busy or not self._connected or not self.dirty:
            return
        self._commit_state = "applying"
        self._status = (
            "Applying demo changes" if self._mock else "Sending changes to ratbagd"
        )
        self._error = ""
        operations = build_operations(self._base, self._draft)
        self._partial_devices = {op.device for op in operations}
        self._start("apply", self._transport.apply(operations))

    @Slot()
    def reset(self):
        if self._busy:
            return
        if self._partial_apply and not self._mock:
            self._set_error(
                "Apply partly failed. Retry Apply, or unplug and reconnect the device before discarding edits; ratbagd may hold partial changes."
            )
            return
        self._base = deepcopy(self._latest)
        self._draft = deepcopy(self._latest)
        self._commit_state = "idle"
        self._status = "Pending edits discarded"
        self._error = ""
        self._fix_selection()
        self.changed.emit()

    @Slot()
    def clearError(self):
        self._error = ""
        self.changed.emit()

    def _fix_selection(self, device_path=None, profile_path=None):
        self._device_index = next(
            (i for i, d in enumerate(self._draft) if d["path"] == device_path),
            min(max(self._device_index, 0), len(self._draft) - 1),
        )
        profiles = self._device().get("profiles", [])
        self._profile_index = next(
            (i for i, p in enumerate(profiles) if p["path"] == profile_path),
            next(
                (i for i, p in enumerate(profiles) if p["active"]),
                0 if profiles else -1,
            ),
        )

    @Slot(str, bool, object)
    def _on_result(self, operation, success, result):
        if self._closed:
            return
        self._busy = False
        if not success:
            if operation == "apply":
                self._partial_apply = not self._mock
                self._commit_state = "failed"
                self._error = str(result)
                if not self._mock:
                    self._error += " Some settings may be staged in ratbagd. Retry Apply or reconnect the device before discarding edits."
                self._status = "Apply failed; edits retained"
            else:
                self._connected = False
                self._error = (
                    f"Cannot connect to ratbagd: {result}"
                    if not self._mock
                    else str(result)
                )
                self._status = "Disconnected"
        else:
            device_path, profile_path = self._device().get("path"), self._profile().get(
                "path"
            )
            self._latest = deepcopy(result)
            was_dirty = self.dirty
            self._connected = True
            if operation == "apply" or not was_dirty or self._resync_pending:
                self._base = deepcopy(result)
                self._draft = deepcopy(result)
            else:
                live_paths = {d["path"] for d in result}
                removed = any(d["path"] not in live_paths for d in self._draft)
                self._base = [d for d in self._base if d["path"] in live_paths]
                self._draft = [d for d in self._draft if d["path"] in live_paths]
                for device in result:
                    if not any(d["path"] == device["path"] for d in self._draft):
                        self._base.append(deepcopy(device))
                        self._draft.append(deepcopy(device))
                if removed:
                    self._partial_devices.intersection_update(live_paths)
                    self._partial_apply = self._partial_apply and bool(
                        self._partial_devices
                    )
                    self._error = (
                        "A device was removed. Its unapplied edits were discarded."
                    )
            self._fix_selection(device_path, profile_path)
            if self._resync_pending:
                self._partial_apply = False
                self._resync_pending = False
                self._commit_state = "failed"
                self._error = "ratbagd reported a device write failure. Settings were reloaded from the device."
                self._status = "Device settings resynchronized after an error"
            elif operation == "apply":
                self._partial_devices.clear()
                self._partial_apply = False
                self._commit_state = "applied" if self._mock else "submitted"
                self._status = (
                    "Demo changes applied"
                    if self._mock
                    else "Changes submitted to ratbagd"
                )
                self._error = ""
            elif not self.dirty and self._commit_state not in ("failed", "submitted"):
                self._status = (
                    "Demo device ready" if self._mock else "Connected to ratbagd"
                )
                self._error = ""
            if not result:
                self._status = "No supported devices found"
        self.changed.emit()
        if self._refresh_queued:
            self._refresh_queued = False
            self._refresh_timer.start()

    @Slot(str)
    def _on_event(self, event):
        if self._closed:
            return
        if event == "disconnected":
            self._connected = False
            self._error = "ratbagd disconnected. Unapplied changes are retained until you reconnect or discard them."
            self._status = "Disconnected"
            self.changed.emit()
        else:
            if event == "resync":
                self._resync_pending = True
                self._error = "ratbagd reported a device write failure. Reloading device settings."
                self.changed.emit()
            self._refresh_timer.start()

    @Slot()
    def simulateDisconnect(self):
        if self._mock and not self._busy:
            self._transport.connected = False
            self._on_event("disconnected")

    @Slot()
    def simulateReconnect(self):
        if self._mock and not self._busy:
            self._transport.connected = True
            self._error = ""
            self.refresh()

    @Slot()
    def simulateCommitFailure(self):
        if self._mock:
            self._transport.fail_next_commit = True
            self._status = "The next demo Apply will simulate a device failure"
            self.changed.emit()

    @Slot()
    def close(self):
        if not self._closed:
            self._closed = True
            self._refresh_timer.stop()
            self._runner.close(self._transport)


# Alias retained for callers that prefer a domain-specific class name.
RatbagBackend = Backend


def validate_macro(events, g600=False):
    if not isinstance(events, (list, tuple)) or not events or len(events) > 256:
        raise ValueError("A macro must contain 1–256 press, release or wait events.")
    result, held, presses = [], set(), []
    for event in events:
        if not isinstance(event, (list, tuple)) or len(event) != 2:
            raise ValueError("Each macro event must be [type, value].")
        kind, value = int(event[0]), int(event[1])
        if kind not in (1, 2, 3) or value < 0:
            raise ValueError("Macro event types are 1=press, 2=release and 3=wait.")
        if kind == 3:
            if not 1 <= value <= 60000:
                raise ValueError(
                    "Macro waits must be between 1 and 60000 milliseconds."
                )
        else:
            if not 1 <= value <= 0x2FF:
                raise ValueError("Macro key codes must be between 1 and 767.")
            if kind == 1:
                if value in held:
                    raise ValueError("Release a key before pressing it again.")
                held.add(value)
                presses.append(value)
            else:
                if value not in held:
                    raise ValueError("A release event must follow a matching press.")
                held.remove(value)
        result.append([kind, value])
    if held:
        raise ValueError("Every pressed key needs a matching release event.")
    if g600:
        if (
            any(kind == 3 for kind, _ in result)
            or len([key for key in presses if key not in MODIFIER_KEYS]) != 1
            or len(set(presses)) != len(presses)
        ):
            raise ValueError(
                "G600 hardware supports one key with modifiers, not timed or multi-key sequences."
            )
        main_key = next(key for key in presses if key not in MODIFIER_KEYS)
        main_release = result.index([2, main_key])
        if any(
            kind == 2 and key in MODIFIER_KEYS for kind, key in result[:main_release]
        ):
            raise ValueError(
                "Release the main key before its modifiers so the G600 keeps the whole chord."
            )
        # A single chord: all press events must precede every release event.
        released = False
        for kind, _ in result:
            released |= kind == 2
            if released and kind == 1:
                raise ValueError(
                    "G600 combinations must press all keys before releasing them."
                )
    return result
