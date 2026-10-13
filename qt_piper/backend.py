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
from uuid import uuid4
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
# The key-code data below is derived from libratbag's MIT-licensed HID table.
# Copyright © 2015 Red Hat, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice (including the next
# paragraph) shall be included in all copies or substantial portions of the
# Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.
#
# Linux evdev codes present in libratbag v0.18's hid_keyboard_mapping.
# https://github.com/libratbag/libratbag/blob/v0.18/src/libratbag-hidraw.c
# G600 stores one keyboard-page HID usage; consumer-only/unknown codes become
# zero in that driver. KEY_RESERVED=0 is separately allowed for modifier chords.
G600_KEYBOARD_CODES = frozenset(
    [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        24,
        25,
        26,
        27,
        28,
        29,
        30,
        31,
        32,
        33,
        34,
        35,
        36,
        37,
        38,
        39,
        40,
        41,
        42,
        43,
        44,
        45,
        46,
        47,
        48,
        49,
        50,
        51,
        52,
        53,
        54,
        55,
        56,
        57,
        58,
        59,
        60,
        61,
        62,
        63,
        64,
        65,
        66,
        67,
        68,
        69,
        70,
        71,
        72,
        73,
        74,
        75,
        76,
        77,
        78,
        79,
        80,
        81,
        82,
        83,
        86,
        87,
        88,
        96,
        97,
        98,
        99,
        100,
        102,
        103,
        104,
        105,
        106,
        107,
        108,
        109,
        110,
        111,
        113,
        114,
        115,
        116,
        117,
        119,
        121,
        125,
        126,
        127,
        128,
        129,
        131,
        133,
        135,
        136,
        137,
        138,
        139,
        183,
        184,
        185,
        186,
        187,
        188,
        189,
        190,
        191,
        192,
        193,
        194,
        223,
        353,
        355,
    ]
)
MOUSE_LABELS = {
    1: "Left click",
    2: "Right click",
    3: "Middle click",
    4: "Back",
    5: "Forward",
}


class RatbagError(RuntimeError):
    """A daemon, capability, value or transport error suitable for display."""


class ScopedApplyError(RatbagError):
    """A scoped failure records whether a write may have reached the daemon."""

    def __init__(self, message, partial=False):
        super().__init__(message)
        self.partial = partial


def rebase_drafts(original, edited, fresh, exclude_paths=(), exclude_fields=None):
    """Keep only local differences, rebased onto live objects by opaque paths.

    Scoped success excludes the submitted button. No pending setting from a
    different page/profile/device is promoted into the committed baseline.
    Removed objects cannot accidentally be replayed onto their replacements.
    """
    exclude_fields = exclude_fields or {}
    if isinstance(fresh, dict):
        if fresh.get("path") in exclude_paths:
            return deepcopy(fresh)
        result = deepcopy(fresh)
        for key in fresh:
            if (
                key in original
                and key in edited
                and key not in exclude_fields.get(fresh.get("path"), ())
            ):
                result[key] = rebase_drafts(
                    original[key],
                    edited[key],
                    fresh[key],
                    exclude_paths,
                    exclude_fields,
                )
        return result
    if isinstance(fresh, list) and any(
        isinstance(items, list)
        and items
        and all(isinstance(item, dict) and "path" in item for item in items)
        for items in (original, edited, fresh)
    ):
        old = {item["path"]: item for item in original}
        draft = {item["path"]: item for item in edited}
        return [
            (
                rebase_drafts(
                    old[item["path"]],
                    draft[item["path"]],
                    item,
                    exclude_paths,
                    exclude_fields,
                )
                if item["path"] in old and item["path"] in draft
                else deepcopy(item)
            )
            for item in fresh
        ]
    return deepcopy(edited if edited != original else fresh)


def validate_mapping_scope(devices, operation):
    """Refuse device-wide Commit when unrelated daemon edits are already pending."""
    if (
        operation.interface != "Button"
        or operation.member != "Mapping"
        or operation.method
    ):
        raise ScopedApplyError("Assignment Apply accepts exactly one button Mapping.")
    device = next((d for d in devices if d["path"] == operation.device), None)
    if not device or not any(
        b["path"] == operation.path for p in device["profiles"] for b in p["buttons"]
    ):
        raise ScopedApplyError(
            "The captured button is no longer available. Reopen its settings."
        )
    if any(not p.get("daemonDirtyKnown", False) for p in device["profiles"]):
        raise ScopedApplyError(
            "ratbagd did not provide a valid IsDirty state for every profile. Cannot safely apply one assignment."
        )
    if any(p["daemonDirty"] for p in device["profiles"]):
        raise ScopedApplyError(
            "ratbagd already has pending changes for this device. Finish those changes or reconnect the device before applying one assignment."
        )


PAGE_SCOPES = {"sensitivity", "lighting", "advanced", "profiles"}


def indexed_objects(devices):
    result = {}
    for device in devices:
        result[device["path"]] = device
        for profile in device["profiles"]:
            result[profile["path"]] = profile
            for collection in ("buttons", "resolutions", "leds"):
                result.update({obj["path"]: obj for obj in profile[collection]})
    return result


def operation_fields(operations, devices):
    """The exact normalized fields affected by each daemon operation."""
    fields = {}
    aliases = {
        "Name": {"rawName", "name"},
        "Disabled": {"disabled", "enabled"},
        "ReportRate": {"reportRate"},
        "AngleSnapping": {"angleSnapping"},
        "Debounce": {"debounce"},
        "Resolution": {"x", "y", "dpi"},
        "IsDisabled": {"disabled", "enabled"},
        "Mapping": {"actionType", "actionId", "actionValue", "actionLabel", "macro"},
        "Mode": {"mode"},
        "Color": {"color", "colorRgb"},
        "Brightness": {"brightness"},
        "EffectDuration": {"effectDuration"},
    }
    for op in operations:
        if not op.method:
            fields.setdefault(op.path, set()).update(aliases[op.member])
            continue
        changed = (
            {"active", "isActive"}
            if op.member == "SetActive"
            else {"default", "isDefault"}
        )
        for device in devices:
            if device["path"] != op.device:
                continue
            for profile in device["profiles"]:
                siblings = (
                    device["profiles"]
                    if op.interface == "Profile"
                    else profile["resolutions"]
                )
                if any(item["path"] == op.path for item in siblings):
                    for item in siblings:
                        fields.setdefault(item["path"], set()).update(changed)
    return fields


def copy_model_fields(source, destination, fields):
    source_objects, destination_objects = indexed_objects(source), indexed_objects(
        destination
    )
    for path, names in fields.items():
        if path in source_objects and path in destination_objects:
            for name in names:
                destination_objects[path][name] = deepcopy(source_objects[path][name])


def validate_page_scope(devices, operations, context):
    device = next((d for d in devices if d["path"] == context["devicePath"]), None)
    profile = (
        next(
            (p for p in device["profiles"] if p["path"] == context["profilePath"]), None
        )
        if device
        else None
    )
    if not profile:
        raise ScopedApplyError("The captured profile is no longer available.")
    if any(not p.get("daemonDirtyKnown", False) for p in device["profiles"]):
        raise ScopedApplyError(
            "ratbagd did not provide a valid IsDirty state for every profile. Cannot safely apply this page."
        )
    if any(p["daemonDirty"] for p in device["profiles"]):
        raise ScopedApplyError(
            "ratbagd already has pending changes for this device. Finish those changes or reconnect it before applying this page."
        )
    if any(not page_operation_matches(op, context, profile) for op in operations):
        raise ScopedApplyError("Apply contains settings outside the captured page.")


def page_operation_matches(operation, context, profile):
    if operation.device != context["devicePath"]:
        return False
    scope = context["scope"]
    if operation.interface == "Profile" and operation.path == context["profilePath"]:
        return (
            operation.member
            in {
                "sensitivity": {"ReportRate"},
                "advanced": {"ReportRate", "AngleSnapping", "Debounce"},
                "profiles": {"Name", "Disabled", "SetActive"},
                "lighting": set(),
            }[scope]
        )
    collection = {"sensitivity": "resolutions", "lighting": "leds"}.get(scope)
    interface = {"sensitivity": "Resolution", "lighting": "Led"}.get(scope)
    return bool(
        collection
        and operation.interface == interface
        and any(item["path"] == operation.path for item in profile[collection])
    )


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
        presses = [KEY_LABELS.get(v, f"Key {v}") for t, v in value if t == 1 and v != 0]
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
                "daemonDirtyKnown": isinstance(props.get("IsDirty"), bool),
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
                        "effectDurationMinimum": 0,
                        "effectDurationMaximum": (
                            15000 if device["hasGShift"] else 10000
                        ),
                        "effectDurationStep": 1000 if device["hasGShift"] else 1,
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


class ScopedTransport:
    """Scope guards shared by the real adapter and deterministic fixtures."""

    async def apply_mapping(self, operation, expected=None):
        return await self.apply_mappings([operation], expected)

    async def apply_mappings(self, operations, expected=None):
        try:
            devices = await self.snapshot()
            if not operations:
                return devices
            scopes = set()
            for operation in operations:
                validate_mapping_scope(devices, operation)
                if expected is not None:
                    observed = indexed_objects(devices)[operation.path]
                    if [observed["actionId"], observed["actionValue"]] != expected.get(
                        operation.path
                    ):
                        raise ScopedApplyError(
                            "This assignment changed in ratbagd after the editor was opened. Refresh and review it before applying."
                        )
                for device in devices:
                    for profile in device["profiles"]:
                        if any(
                            button["path"] == operation.path
                            for button in profile["buttons"]
                        ):
                            scopes.add((device["path"], profile["path"]))
            if len(scopes) != 1 or len({op.path for op in operations}) != len(
                operations
            ):
                raise ScopedApplyError(
                    "Assignment Apply must contain unique buttons from one device and profile."
                )
        except Exception as exc:
            raise ScopedApplyError(str(exc), partial=False) from exc
        try:
            return await self.apply(operations)
        except Exception as exc:
            raise ScopedApplyError(str(exc), partial=True) from exc

    async def apply_page(self, operations, context, expected=None):
        try:
            devices = await self.snapshot()
            validate_page_scope(devices, operations, context)
            if expected is not None:
                old_objects, live_objects = indexed_objects(expected), indexed_objects(
                    devices
                )
                for path, names in operation_fields(operations, expected).items():
                    if path not in live_objects or any(
                        live_objects[path].get(name) != old_objects[path].get(name)
                        for name in names
                    ):
                        raise ScopedApplyError(
                            "These settings changed in ratbagd after editing began. Refresh and review this page before applying."
                        )
            if not operations:
                return devices
        except Exception as exc:
            raise ScopedApplyError(str(exc), partial=False) from exc
        try:
            return await self.apply(operations)
        except Exception as exc:
            raise ScopedApplyError(str(exc), partial=True) from exc


class MockTransport(ScopedTransport):
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


class DBusTransport(ScopedTransport):
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
                callback(False, exc)

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
        before = deepcopy(self._draft)
        try:
            function(self, *args)
        except (ValueError, TypeError, KeyError, IndexError, RatbagError) as exc:
            self._set_error(str(exc))
            return False
        self._clear_conflicts(
            operation_fields(build_operations(before, self._draft), before)
        )
        self._error = ""
        self._commit_state = "staged" if self.dirty else "idle"
        self._status = "Unapplied changes" if self.dirty else "No pending changes"
        self.changed.emit()
        return True

    return guarded


class Backend(QObject):
    """QML-facing device model. All exposed maps are immutable snapshots."""

    changed = Signal()
    mappingApplyFinished = Signal(str, bool, str)
    mappingsApplyFinished = Signal(str, str, bool, str)
    pageApplyFinished = Signal(str, bool, str)
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
        self._partial_mapping_path = None
        self._partial_mapping_paths = set()
        self._mapping_contexts = {}
        self._mapping_apply_context = None
        self._mapping_batch_contexts = []
        self._page_contexts = {}
        self._page_apply_context = None
        self._page_apply_operations = []
        self._partial_page_scope = None
        self._last_page_submission = None
        self._scoped_recovery = False
        self._last_scoped_submission = None
        self._refresh_queued = False
        self._external_conflicts = set()
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

    @Property(bool, notify=changed)
    def profileMappingsDirty(self):
        device_path = self._device().get("path")
        button_paths = {b["path"] for b in self._profile().get("buttons", [])}
        return any(
            op.device == device_path
            and op.path in button_paths
            and op.member == "Mapping"
            for op in build_operations(self._base, self._draft)
        )

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

    def _clear_conflicts(self, fields):
        self._external_conflicts.difference_update(
            (path, name) for path, names in fields.items() for name in names
        )

    def _check_conflicts(self, operations):
        fields = operation_fields(operations, self._draft)
        if any(
            (path, name) in self._external_conflicts
            for path, names in fields.items()
            for name in names
        ):
            raise ValueError(
                "These draft settings also changed outside this application. Revert and review them, or edit them again, before applying."
            )

    def _remember_external_conflicts(self, fresh):
        before, draft, live = (
            indexed_objects(self._base),
            indexed_objects(self._draft),
            indexed_objects(fresh),
        )
        fields = operation_fields(
            build_operations(self._base, self._draft), self._draft
        )
        for path, names in fields.items():
            if path in before and path in draft and path in live:
                for name in names:
                    if live[path].get(name) != before[path].get(name) and live[
                        path
                    ].get(name) != draft[path].get(name):
                        self._external_conflicts.add((path, name))
        self._external_conflicts = {
            (path, name) for path, name in self._external_conflicts if path in live
        }

    def _set_error(self, message):
        self._error = message
        self.changed.emit()

    @Slot(int)
    def selectDevice(self, index):
        if self._busy:
            return
        if 0 <= index < len(self._draft):
            if index != self._device_index:
                self._mapping_contexts.clear()
                self._page_contexts.clear()
            self._device_index = index
            self._profile_index = next(
                (i for i, p in enumerate(self._device()["profiles"]) if p["active"]), 0
            )
            self.changed.emit()

    @Slot(int)
    def selectProfile(self, index):
        if self._busy:
            return
        if 0 <= index < len(self._device().get("profiles", [])):
            if index != self._profile_index:
                self._mapping_contexts.clear()
                self._page_contexts.clear()
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
        self._set_mapping(
            self._item("buttons", index), self._device(), action_type, value
        )

    def _set_mapping(self, item, device, action_type, value):
        if hasattr(value, "toVariant"):
            value = value.toVariant()
        if action_type not in item["actionTypes"]:
            raise ValueError("This button does not support that action type.")
        if action_type == "none":
            value = 0
        elif action_type == "macro":
            value = validate_macro(value, g600=device["hasGShift"])
        else:
            value = int(value)
            if action_type == "button" and not 1 <= value <= 32:
                raise ValueError("Mouse button must be between 1 and 32.")
            if action_type == "button" and device["hasGShift"] and value > 5:
                raise ValueError(
                    "The G600 driver supports mouse button assignments 1–5."
                )
            if action_type == "key" and not 1 <= value <= 0x2FF:
                raise ValueError("Use a valid Linux input key code (1–767).")
            if action_type == "special" and value not in SPECIAL_LABELS:
                raise ValueError("Unknown special action.")
            if (
                action_type == "special"
                and device["hasGShift"]
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

    @staticmethod
    def _mapping_identity(context):
        return tuple(
            context.get(key)
            for key in ("devicePath", "profilePath", "buttonPath", "index")
        )

    @staticmethod
    def _find_context_button(devices, context):
        device = next(
            (d for d in devices if d["path"] == context.get("devicePath")), None
        )
        profile = (
            next(
                (
                    p
                    for p in device["profiles"]
                    if p["path"] == context.get("profilePath")
                ),
                None,
            )
            if device
            else None
        )
        button = (
            next(
                (
                    b
                    for b in profile["buttons"]
                    if b["path"] == context.get("buttonPath")
                    and b["index"] == context.get("index")
                ),
                None,
            )
            if profile
            else None
        )
        if not button:
            raise ValueError(
                "This assignment is no longer available. Reopen its settings."
            )
        return device, profile, button

    def _context_button(self, context):
        if hasattr(context, "toVariant"):
            context = context.toVariant()
        record = self._mapping_contexts.get(context.get("token"))
        if not record or record["identity"] != self._mapping_identity(context):
            raise ValueError("This assignment context is stale. Reopen its settings.")
        if (
            not self._connected
            or self._device().get("path") != context.get("devicePath")
            or self._profile().get("path") != context.get("profilePath")
        ):
            raise ValueError(
                "The selected device or profile changed. Reopen the assignment settings."
            )
        return self._find_context_button(self._draft, context)

    @Slot(int, result="QVariantMap")
    def captureMappingContext(self, index):
        if self._busy or not self._connected:
            self._set_error("Wait until the device is connected and ready.")
            return {}
        try:
            item = self._item("buttons", index)
            context = {
                "devicePath": self._device()["path"],
                "profilePath": self._profile()["path"],
                "buttonPath": item["path"],
                "index": index,
                "token": uuid4().hex,
            }
            baseline = self._find_context_button(self._base, context)[2]
            self._mapping_contexts[context["token"]] = {
                "identity": self._mapping_identity(context),
                "baseline": [baseline["actionType"], deepcopy(baseline["actionValue"])],
            }
            return context
        except (ValueError, KeyError) as exc:
            self._set_error(str(exc))
            return {}

    @Slot(result="QVariantList")
    def captureMappingContexts(self):
        if self._busy or not self._connected:
            self._set_error("Wait until the device is connected and ready.")
            return []
        return [
            self.captureMappingContext(button["index"])
            for button in self._profile().get("buttons", [])
        ]

    @Slot("QVariantMap", str, "QVariant", result=bool)
    @edit_action
    def stageMapping(self, context, action_type, value):
        device, profile, button = self._context_button(context)
        self._set_mapping(button, device, action_type, value)
        self._external_conflicts = {
            (path, name)
            for path, name in self._external_conflicts
            if path != button["path"]
        }

    def _mapping_context_batch(self, contexts):
        if not isinstance(contexts, list) or not contexts:
            raise ValueError(
                "Capture the current profile's assignments before applying or reverting them."
            )
        resolved = [self._context_button(context) for context in contexts]
        scopes = {
            (device["path"], profile["path"]) for device, profile, button in resolved
        }
        paths = {button["path"] for device, profile, button in resolved}
        if len(scopes) != 1 or len(paths) != len(contexts):
            raise ValueError(
                "Assignment scope must contain unique buttons from the current profile."
            )
        return resolved, paths

    @Slot("QVariantList", result=bool)
    def resetMappings(self, contexts):
        try:
            if self._busy:
                raise ValueError(
                    "Wait for the current operation before reverting these assignments."
                )
            resolved, paths = self._mapping_context_batch(contexts)
            if (
                self._partial_apply
                and not self._mock
                and resolved[0][0]["path"] in self._partial_devices
            ):
                raise ValueError(
                    "A write may be pending in ratbagd. Retry Apply or reconnect the device before reverting assignments."
                )
            originals = [
                deepcopy(self._find_context_button(self._base, context)[2])
                for context in contexts
            ]
            self._external_conflicts = {
                (path, name)
                for path, name in self._external_conflicts
                if path not in paths
            }
            for (_, _, button), original in zip(resolved, originals, strict=True):
                button.clear()
                button.update(original)
            self._error = ""
            self._status = "Current profile assignment edits discarded"
            self._commit_state = "staged" if self.dirty else "idle"
            self.changed.emit()
            return True
        except (ValueError, TypeError, KeyError) as exc:
            self._set_error(str(exc))
            return False

    @Slot("QVariantList", result=bool)
    def applyMappings(self, contexts):
        device_path = contexts[0].get("devicePath", "") if contexts else ""
        profile_path = contexts[0].get("profilePath", "") if contexts else ""
        try:
            if self._busy:
                raise ValueError(
                    "Wait for the current operation before applying these assignments."
                )
            resolved, paths = self._mapping_context_batch(contexts)
            if (
                self._partial_apply
                and not self._mock
                and (
                    not self._partial_mapping_paths
                    or not self._partial_mapping_paths.issubset(paths)
                )
            ):
                raise ValueError(
                    "Another Apply partly failed. Resolve its pending daemon changes before applying these assignments."
                )
            operations = [
                op
                for op in build_operations(self._base, self._draft)
                if op.device == device_path
                and op.path in paths
                and op.member == "Mapping"
            ]
            self._check_conflicts(operations)
            self._error = ""
            if not operations:
                if self._partial_apply:
                    raise ValueError(
                        "A previous write may still be pending in ratbagd. Reconnect the device before discarding these assignments."
                    )
                self._status = "This profile has no pending assignment changes"
                self.changed.emit()
                self.mappingsApplyFinished.emit(
                    device_path, profile_path, True, self._status
                )
                return True
            changed_paths = {op.path for op in operations}
            self._mapping_batch_contexts = deepcopy(
                [
                    context
                    for context in contexts
                    if context["buttonPath"] in changed_paths
                ]
            )
            self._scoped_recovery = True
            self._last_page_submission = None
            self._partial_devices = {device_path}
            self._commit_state = "applying"
            self._status = (
                "Applying this profile's assignments"
                if self._mock
                else "Sending this profile's assignments to ratbagd"
            )
            baseline = indexed_objects(self._base)
            expected = {
                op.path: [
                    baseline[op.path]["actionId"],
                    deepcopy(baseline[op.path]["actionValue"]),
                ]
                for op in operations
            }
            self._start(
                "apply-mappings", self._transport.apply_mappings(operations, expected)
            )
            return True
        except (ValueError, TypeError, KeyError) as exc:
            self._set_error(str(exc))
            self.mappingsApplyFinished.emit(device_path, profile_path, False, str(exc))
            return False

    @Slot("QVariantMap", str, "QVariant", result=str)
    def validateMapping(self, context, action_type, value):
        """Validate editor input without staging, notifying, or writing anything.

        Validation intentionally uses the same normalizer as Apply on a copy.
        For example, a valid G600 modifier-only chord may acquire a reserved
        key-zero pair when it is later staged, but validation never changes the
        caller's event list or any application state.
        """
        try:
            if hasattr(context, "toVariant"):
                context = context.toVariant()
            if not isinstance(context, dict):
                raise ValueError(
                    "This assignment context is stale. Reopen its settings."
                )
            device, _profile, button = self._context_button(context)
            self._set_mapping(deepcopy(button), device, action_type, value)
        except (
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            OverflowError,
            RatbagError,
        ) as exc:
            return str(exc)
        return ""

    @Slot("QVariantMap", result="QVariantList")
    def mappingKeyChoices(self, context):
        """Return device-encodable key choices without changing editor state.

        Key zero is not a normal key choice. Preserve it for inspection only
        when the captured assignment already contains a valid modifier-only
        G600 chord; the shared normalizer adds it to new modifier chords.
        """
        try:
            if hasattr(context, "toVariant"):
                context = context.toVariant()
            if not isinstance(context, dict):
                return []
            device, _profile, button = self._context_button(context)
        except (ValueError, TypeError, KeyError):
            return []
        g600 = device["hasGShift"]
        codes = sorted(G600_KEYBOARD_CODES) if g600 else range(1, 0x300)
        choices = [
            {"value": code, "label": KEY_LABELS.get(code, f"Key {code}")}
            for code in codes
        ]
        if (
            g600
            and button["actionType"] == "macro"
            and [1, 0] in button["actionValue"]
            and not self.validateMapping(context, "macro", button["actionValue"])
        ):
            choices.insert(
                0,
                {
                    "value": 0,
                    "label": "Reserved 0 (modifier-chord placeholder)",
                    "placeholder": True,
                    "selectable": False,
                },
            )
        return choices

    @Slot("QVariantMap", result=bool)
    def mappingContextValid(self, context):
        try:
            self._context_button(context)
            return True
        except (ValueError, TypeError, KeyError):
            return False

    @Slot("QVariantMap", result="QVariantMap")
    def mappingForContext(self, context):
        try:
            return deepcopy(self._context_button(context)[2])
        except (ValueError, TypeError, KeyError):
            return {}

    @Slot("QVariantMap", result=bool)
    def mappingDirty(self, context):
        try:
            button = self._context_button(context)[2]
            before = self._find_context_button(self._base, context)[2]
            return (button["actionType"], button["actionValue"]) != (
                before["actionType"],
                before["actionValue"],
            )
        except (ValueError, TypeError, KeyError):
            return False

    @Slot("QVariantMap", result="QVariantMap")
    def resetMapping(self, context):
        try:
            if self._busy:
                raise ValueError(
                    "Wait for the current operation to finish before resetting this assignment."
                )
            device, profile, item = self._context_button(context)
            if (
                self._partial_apply
                and not self._mock
                and context.get("devicePath") in self._partial_devices
            ):
                raise ValueError(
                    "A write may be pending in ratbagd. Retry this assignment or reconnect the device before resetting it."
                )
            before = self._find_context_button(self._base, context)[2]
            item.clear()
            item.update(deepcopy(before))
            self._external_conflicts = {
                (path, name)
                for path, name in self._external_conflicts
                if path != item["path"]
            }
            self._error = ""
            self._status = "Assignment edits discarded"
            self._commit_state = "staged" if self.dirty else "idle"
            self.changed.emit()
            return deepcopy(item)
        except (ValueError, TypeError, KeyError) as exc:
            self._set_error(str(exc))
            return {}

    @Slot("QVariantMap", str, "QVariant", result=bool)
    def applyMapping(self, context, action_type, value):
        token = context.get("token", "")
        try:
            if self._busy:
                raise ValueError(
                    "Wait for the current operation to finish before applying this assignment."
                )
            device, profile, item = self._context_button(context)
            if (
                self._partial_apply
                and not self._mock
                and self._partial_mapping_paths != {item["path"]}
            ):
                raise ValueError(
                    "Another Apply partly failed. Resolve its pending daemon changes before applying this assignment."
                )
            self._set_mapping(item, device, action_type, value)
            self._external_conflicts = {
                (path, name)
                for path, name in self._external_conflicts
                if path != item["path"]
            }
            operations = [
                op
                for op in build_operations(self._base, self._draft)
                if op.device == context["devicePath"]
                and op.path == context["buttonPath"]
                and op.member == "Mapping"
            ]
            self._check_conflicts(operations)
            self._error = ""
            if not operations:
                if self._partial_apply:
                    raise ValueError(
                        "A previous write may still be pending in ratbagd. Reconnect the device before discarding or reapplying this assignment."
                    )
                self._status = "This assignment has no pending changes"
                self.changed.emit()
                self.mappingApplyFinished.emit(token, True, self._status)
                return True
            if len(operations) != 1:
                raise ValueError(
                    "The assignment scope is ambiguous; reopen its settings."
                )
            self._mapping_apply_context = deepcopy(context)
            self._scoped_recovery = True
            self._last_page_submission = None
            self._partial_devices = {context["devicePath"]}
            self._commit_state = "applying"
            self._status = (
                "Applying this assignment"
                if self._mock
                else "Sending this assignment to ratbagd"
            )
            baseline = self._find_context_button(self._base, context)[2]
            expected = {
                item["path"]: [baseline["actionId"], deepcopy(baseline["actionValue"])]
            }
            self._start(
                "apply-mapping", self._transport.apply_mapping(operations[0], expected)
            )
            return True
        except (ValueError, TypeError, KeyError) as exc:
            self._set_error(str(exc))
            self.mappingApplyFinished.emit(token, False, str(exc))
            return False

    def _reconcile_mapping_contexts(self, fresh, updated_contexts=None):
        updated_paths = {context["buttonPath"] for context in updated_contexts or []}
        for token, record in list(self._mapping_contexts.items()):
            identity = record["identity"]
            context = dict(
                zip(
                    ("devicePath", "profilePath", "buttonPath", "index"),
                    identity,
                    strict=True,
                )
            )
            try:
                button = self._find_context_button(fresh, context)[2]
            except ValueError:
                self._mapping_contexts.pop(token, None)
                continue
            baseline = [button["actionType"], button["actionValue"]]
            if context["buttonPath"] in updated_paths:
                record["baseline"] = deepcopy(baseline)
            elif baseline != record["baseline"]:
                self._mapping_contexts.pop(token, None)

    @staticmethod
    def _page_identity(context):
        return tuple(context.get(key) for key in ("devicePath", "profilePath", "scope"))

    def _page_profile(self, context):
        if self._page_contexts.get(context.get("token")) != self._page_identity(
            context
        ):
            raise ValueError("This page context is stale. Reopen the page.")
        if (
            not self._connected
            or self._device().get("path") != context.get("devicePath")
            or self._profile().get("path") != context.get("profilePath")
        ):
            raise ValueError("The selected device or profile changed. Reopen the page.")
        return self._profile()

    @Slot(str, result="QVariantMap")
    def capturePageContext(self, scope):
        if (
            self._busy
            or not self._connected
            or not self._profile()
            or scope not in PAGE_SCOPES
        ):
            self._set_error(
                "Select a connected profile and valid settings page before continuing."
            )
            return {}
        context = {
            "devicePath": self._device()["path"],
            "profilePath": self._profile()["path"],
            "scope": scope,
            "token": uuid4().hex,
        }
        self._page_contexts[context["token"]] = self._page_identity(context)
        return context

    @Slot("QVariantMap", result=bool)
    def pageDirty(self, context):
        try:
            profile = self._page_profile(context)
            return any(
                page_operation_matches(op, context, profile)
                for op in build_operations(self._base, self._draft)
            )
        except (ValueError, TypeError, KeyError):
            return False

    @Slot("QVariantMap", result=bool)
    def resetPage(self, context):
        try:
            if self._busy:
                raise ValueError(
                    "Wait for the current operation before reverting this page."
                )
            profile = self._page_profile(context)
            if (
                self._partial_apply
                and not self._mock
                and context["devicePath"] in self._partial_devices
            ):
                raise ValueError(
                    "A write may be pending in ratbagd. Retry Apply or reconnect the device before reverting this page."
                )
            operations = [
                op
                for op in build_operations(self._base, self._draft)
                if page_operation_matches(op, context, profile)
            ]
            fields = operation_fields(operations, self._draft)
            copy_model_fields(self._base, self._draft, fields)
            self._clear_conflicts(fields)
            self._error = ""
            self._status = "This page's edits discarded"
            self._commit_state = "staged" if self.dirty else "idle"
            self.changed.emit()
            return True
        except (ValueError, TypeError, KeyError) as exc:
            self._set_error(str(exc))
            return False

    @Slot("QVariantMap", result=bool)
    def applyPage(self, context):
        token = context.get("token", "")
        try:
            if self._busy:
                raise ValueError(
                    "Wait for the current operation before applying this page."
                )
            profile = self._page_profile(context)
            if (
                self._partial_apply
                and not self._mock
                and self._partial_page_scope != self._page_identity(context)
            ):
                raise ValueError(
                    "Another Apply partly failed. Resolve its pending daemon changes before applying this page."
                )
            operations = [
                op
                for op in build_operations(self._base, self._draft)
                if page_operation_matches(op, context, profile)
            ]
            self._check_conflicts(operations)
            self._error = ""
            if not operations:
                if self._partial_apply:
                    raise ValueError(
                        "A previous write may still be pending in ratbagd. Reconnect the device before discarding these settings."
                    )
                self._status = "This page has no pending changes"
                self.changed.emit()
                self.pageApplyFinished.emit(token, True, self._status)
                return True
            self._page_apply_context = deepcopy(context)
            self._page_apply_operations = operations
            self._last_scoped_submission = None
            self._scoped_recovery = True
            self._last_page_submission = None
            self._partial_devices = {context["devicePath"]}
            self._commit_state = "applying"
            self._status = (
                "Applying this page"
                if self._mock
                else "Sending this page's changes to ratbagd"
            )
            self._start(
                "apply-page",
                self._transport.apply_page(operations, context, deepcopy(self._base)),
            )
            return True
        except (ValueError, TypeError, KeyError) as exc:
            self._set_error(str(exc))
            self.pageApplyFinished.emit(token, False, str(exc))
            return False

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
            maximum = (
                255
                if field == "brightness"
                else item.get("effectDurationMaximum", 10000)
            )
            if field == "effectDuration" and value % item.get("effectDurationStep", 1):
                raise ValueError(
                    "The G600 stores LED duration in whole seconds. Choose a multiple of 1000 milliseconds."
                )
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
        self._scoped_recovery = False
        self._last_scoped_submission = None
        self._last_page_submission = None
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
        self._scoped_recovery = False
        self._last_scoped_submission = None
        self._last_page_submission = None
        self._external_conflicts.clear()
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
        mapping_context = (
            self._mapping_apply_context if operation == "apply-mapping" else None
        )
        mapping_contexts = (
            [mapping_context]
            if mapping_context
            else self._mapping_batch_contexts if operation == "apply-mappings" else []
        )
        page_context = self._page_apply_context if operation == "apply-page" else None
        had_resync = self._resync_pending
        if not success:
            if operation in ("apply", "apply-mapping", "apply-mappings", "apply-page"):
                self._partial_apply = not self._mock and (
                    self._partial_apply or getattr(result, "partial", True)
                )
                self._partial_mapping_paths = (
                    {context["buttonPath"] for context in mapping_contexts}
                    if self._partial_apply
                    else set()
                )
                self._partial_mapping_path = (
                    next(iter(self._partial_mapping_paths))
                    if len(self._partial_mapping_paths) == 1
                    else None
                )
                self._partial_page_scope = (
                    self._page_identity(page_context)
                    if page_context and self._partial_apply
                    else None
                )
                self._commit_state = "failed"
                self._error = str(result)
                if self._partial_apply:
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
            if (
                operation == "refresh"
                and not self._partial_apply
                and not self._resync_pending
            ):
                self._remember_external_conflicts(result)
            self._latest = deepcopy(result)
            was_dirty = self.dirty
            self._connected = True
            if page_context:
                field_scope = operation_fields(self._page_apply_operations, self._draft)
                desired = deepcopy(self._draft)
                self._draft = rebase_drafts(
                    self._base,
                    self._draft,
                    result,
                    exclude_fields={} if self._resync_pending else field_scope,
                )
                self._base = deepcopy(result)
                self._last_page_submission = (
                    deepcopy(page_context),
                    desired,
                    field_scope,
                )
            elif mapping_contexts:
                desired = [
                    (
                        deepcopy(context),
                        deepcopy(self._find_context_button(self._draft, context)[2]),
                    )
                    for context in mapping_contexts
                ]
                self._draft = rebase_drafts(
                    self._base,
                    self._draft,
                    result,
                    (
                        ()
                        if self._resync_pending
                        else {context["buttonPath"] for context in mapping_contexts}
                    ),
                )
                self._base = deepcopy(result)
                self._last_scoped_submission = desired
            elif self._resync_pending and self._scoped_recovery:
                previous_base = indexed_objects(self._base)
                previous_draft = indexed_objects(self._draft)
                self._draft = rebase_drafts(self._base, self._draft, result)
                self._base = deepcopy(result)
                if self._last_page_submission:
                    page, desired, field_scope = self._last_page_submission
                    unchanged = {
                        path: {
                            name
                            for name in names
                            if previous_base.get(path, {}).get(name)
                            == previous_draft.get(path, {}).get(name)
                        }
                        for path, names in field_scope.items()
                    }
                    copy_model_fields(desired, self._draft, unchanged)
                for context, desired in self._last_scoped_submission or []:
                    try:
                        path = context["buttonPath"]
                        if any(
                            previous_base.get(path, {}).get(name)
                            != previous_draft.get(path, {}).get(name)
                            for name in ("actionType", "actionValue")
                        ):
                            continue  # Newer local input supersedes the last submitted value.
                        button = self._find_context_button(self._draft, context)[2]
                        button.update(deepcopy(desired))
                    except ValueError:
                        pass
            elif operation == "apply" or not was_dirty or self._resync_pending:
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
                if not self._partial_apply:
                    self._draft = rebase_drafts(self._base, self._draft, result)
                    self._base = deepcopy(result)
                if removed:
                    self._partial_devices.intersection_update(live_paths)
                    self._partial_apply = self._partial_apply and bool(
                        self._partial_devices
                    )
                    self._error = (
                        "A device was removed. Its unapplied edits were discarded."
                    )
            self._fix_selection(device_path, profile_path)
            self._reconcile_mapping_contexts(
                result, mapping_contexts if not self._resync_pending else None
            )
            if self._resync_pending:
                self._partial_apply = False
                self._resync_pending = False
                self._commit_state = "failed"
                self._error = "ratbagd reported a device write failure. Settings were reloaded from the device."
                self._status = "Device settings resynchronized after an error"
            elif operation in (
                "apply",
                "apply-mapping",
                "apply-mappings",
                "apply-page",
            ):
                self._partial_mapping_path = None
                self._partial_mapping_paths.clear()
                self._partial_page_scope = None
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
        if page_context:
            self._page_apply_context = None
            self._page_apply_operations = []
            self.pageApplyFinished.emit(
                page_context["token"],
                success and self._commit_state != "failed",
                self._error or self._status,
            )
        elif mapping_context:
            self._mapping_apply_context = None
            self.mappingApplyFinished.emit(
                mapping_context["token"],
                success and self._commit_state != "failed",
                self._error or self._status,
            )
        elif operation == "apply-mappings" and mapping_contexts:
            self._mapping_batch_contexts = []
            context = mapping_contexts[0]
            self.mappingsApplyFinished.emit(
                context["devicePath"],
                context["profilePath"],
                success and self._commit_state != "failed",
                self._error or self._status,
            )
        elif had_resync and success and self._last_page_submission:
            self.pageApplyFinished.emit(
                self._last_page_submission[0]["token"], False, self._error
            )
        elif had_resync and success and self._last_scoped_submission:
            for context, _desired in self._last_scoped_submission:
                self.mappingApplyFinished.emit(context["token"], False, self._error)
            context = self._last_scoped_submission[0][0]
            self.mappingsApplyFinished.emit(
                context["devicePath"], context["profilePath"], False, self._error
            )
        if self._refresh_queued:
            self._refresh_queued = False
            self._refresh_timer.start()

    @Slot(str)
    def _on_event(self, event):
        if self._closed:
            return
        if event == "disconnected":
            self._mapping_contexts.clear()
            self._page_contexts.clear()
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
        if kind != event[0] or value != event[1]:
            raise ValueError("Macro event types and values must be integers.")
        if kind not in (1, 2, 3) or value < 0:
            raise ValueError("Macro event types are 1=press, 2=release and 3=wait.")
        if kind == 3:
            if not 1 <= value <= 60000:
                raise ValueError(
                    "Macro waits must be between 1 and 60000 milliseconds."
                )
        else:
            if not (1 <= value <= 0x2FF or g600 and value == 0):
                raise ValueError(
                    "Macro key codes must be between 1 and 767; G600 modifier chords may use the reserved 0 placeholder."
                )
            if g600 and value != 0 and value not in G600_KEYBOARD_CODES:
                raise ValueError(
                    f"Key code {value} cannot be encoded by the G600 keyboard HID mapping."
                )
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
        # The daemon represents modifier-only bindings with a reserved key pair.
        # Normalize a recorded balanced modifier chord to that documented shape.
        if (
            presses
            and all(key in MODIFIER_KEYS for key in presses)
            and not any(kind == 3 for kind, _ in result)
        ):
            first_release = next(i for i, (kind, _) in enumerate(result) if kind == 2)
            result[first_release:first_release] = [[1, 0], [2, 0]]
            presses.append(0)
        if (
            any(kind == 3 for kind, _ in result)
            or len([key for key in presses if key not in MODIFIER_KEYS]) != 1
            or len(set(presses)) != len(presses)
        ):
            raise ValueError(
                "G600 hardware supports one key with modifiers, not timed or multi-key sequences."
            )
        main_key = next(key for key in presses if key not in MODIFIER_KEYS)
        if main_key == 0 and not any(key in MODIFIER_KEYS for key in presses):
            raise ValueError(
                "The G600 reserved key 0 placeholder requires at least one modifier."
            )
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
