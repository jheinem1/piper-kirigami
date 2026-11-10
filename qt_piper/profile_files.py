# SPDX-License-Identifier: GPL-2.0-or-later
"""Versioned profile files. Validation is pure; I/O never talks to ratbagd.

Paths, slot names, slot enablement and slot activation are deliberately absent.
A file describes the portable settings of one slot, not the device's identity
or which slot should be active. Unknown fields are rejected, never ignored.
"""

from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import tempfile

from PySide6.QtCore import QUrl

FORMAT = "org.freedesktop.piper.profile"
VERSION = 1
MAX_FILE_BYTES = 1024 * 1024


def _object(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"{label} must contain exactly: {', '.join(sorted(keys))}.")
    return value


def _integer(value, label, minimum=0, maximum=0xFFFFFFFF):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer from {minimum} to {maximum}.")
    return value


def _boolean(value, label):
    if type(value) is not bool:
        raise ValueError(f"{label} must be true or false.")
    return value


def _name(value, label):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.encode("utf-8")) > 255
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError(
            f"{label} must be a name of 1–255 UTF-8 bytes without control characters."
        )
    return value.strip()


def _indexed(values, expected, label):
    if not isinstance(values, list) or len(values) != len(expected):
        raise ValueError(f"{label} count does not match this profile slot.")
    result = {}
    for value in values:
        if not isinstance(value, dict) or "index" not in value:
            raise ValueError(f"Each {label} entry needs an index.")
        index = _integer(value["index"], f"{label} index")
        if index in result:
            raise ValueError(f"Duplicate {label} index {index}.")
        result[index] = value
    if set(result) != {item["index"] for item in expected}:
        raise ValueError(f"{label} indices do not match this profile slot.")
    return result


def settings_keys(profile):
    keys = set()
    if profile["reportRates"]:
        keys.add("reportRate")
    if profile["angleSnapping"] >= 0:
        keys.add("angleSnapping")
    if profile["debounces"]:
        keys.add("debounce")
    return keys


def resolution_keys(item):
    return {"index", "x", "y", "active", "default"} | (
        {"enabled"} if item["canDisable"] else set()
    )


def led_keys(item):
    return (
        {"index", "mode", "effectDuration"}
        | ({"color"} if item["colorDepth"] in (1, 2) else set())
        | ({"brightness"} if item.get("canBrightness", True) else set())
    )


def export_document(device, profile, name, mapping_validator):
    """Export the effective draft, then validate it with the import contract.

    Refuse an unrepresentable daemon value rather than silently changing it
    during a later import (notably unsupported G600 macros and LED timing).
    """
    document = {
        "format": FORMAT,
        "version": VERSION,
        "name": _name(name, "File profile name"),
        "device": {"model": device["model"]},
        "profile": {
            "settings": {key: profile[key] for key in sorted(settings_keys(profile))},
            "resolutions": [
                {key: item[key] for key in sorted(resolution_keys(item))}
                for item in profile["resolutions"]
            ],
            "buttons": [
                {
                    "index": item["index"],
                    "layer": item["layer"],
                    "physicalIndex": item["physicalIndex"],
                    "action": {
                        "type": item["actionType"],
                        "value": deepcopy(item["actionValue"]),
                    },
                }
                for item in profile["buttons"]
            ],
            "leds": [
                {
                    key: deepcopy(item["colorRgb"] if key == "color" else item[key])
                    for key in sorted(led_keys(item))
                }
                for item in profile["leds"]
            ],
        },
    }
    validate_document(document, device, profile, mapping_validator)
    return document


def validate_document(document, device, profile, mapping_validator):
    """Return a fully validated replacement copy; never alter arguments.

    ``mapping_validator`` is Backend's existing device-specific assignment
    validator, used only against isolated candidate objects.
    """
    _object(
        document, {"format", "version", "name", "device", "profile"}, "Profile file"
    )
    if document["format"] != FORMAT:
        raise ValueError("This is not a Piper profile file.")
    if type(document["version"]) is not int or document["version"] != VERSION:
        raise ValueError(
            f"Unsupported profile file version. Expected version {VERSION}."
        )
    _name(document["name"], "File profile name")
    _object(document["device"], {"model"}, "Device")
    if (
        not isinstance(document["device"]["model"], str)
        or document["device"]["model"] != device["model"]
    ):
        raise ValueError("The profile file is for a different device model.")
    content = _object(
        document["profile"], {"settings", "resolutions", "buttons", "leds"}, "Profile"
    )
    settings = _object(
        content["settings"], settings_keys(profile), "Supported profile settings"
    )
    candidate = deepcopy(profile)
    for key, value in settings.items():
        _integer(value, key)
        supported = (
            profile["reportRates"]
            if key == "reportRate"
            else profile["debounces"] if key == "debounce" else (0, 1)
        )
        if value not in supported:
            raise ValueError(f"{key} is not supported by this profile slot.")
        candidate[key] = value

    resolutions = _indexed(content["resolutions"], profile["resolutions"], "DPI stage")
    for item in candidate["resolutions"]:
        value = _object(
            resolutions[item["index"]],
            resolution_keys(item),
            "Supported DPI stage settings",
        )
        for axis in ("x", "y"):
            _integer(value[axis], f"DPI {axis}")
            if value[axis] not in item["values"]:
                raise ValueError(
                    "The file contains a DPI value unsupported by this profile slot."
                )
        if not item["separateXY"] and value["x"] != value["y"]:
            raise ValueError("This device uses the same DPI for both axes.")
        enabled = (
            _boolean(value["enabled"], "DPI enabled")
            if item["canDisable"]
            else item["enabled"]
        )
        active = _boolean(value["active"], "Active DPI stage")
        default = _boolean(value["default"], "Default DPI stage")
        if not enabled and (active or default):
            raise ValueError("The active or default DPI stage cannot be disabled.")
        item.update(
            x=value["x"],
            y=value["y"],
            dpi=value["x"],
            enabled=enabled,
            disabled=not enabled,
            active=active,
            isActive=active,
            default=default,
            isDefault=default,
        )
    if candidate["resolutions"] and (
        sum(item["active"] for item in candidate["resolutions"]) != 1
        or sum(item["default"] for item in candidate["resolutions"]) != 1
    ):
        raise ValueError(
            "A profile must have exactly one active and one default DPI stage."
        )

    buttons = _indexed(content["buttons"], profile["buttons"], "Button")
    for item in candidate["buttons"]:
        value = _object(
            buttons[item["index"]],
            {"index", "layer", "physicalIndex", "action"},
            "Button",
        )
        _integer(value["physicalIndex"], "Physical button index")
        if (
            value["layer"] != item["layer"]
            or value["physicalIndex"] != item["physicalIndex"]
        ):
            raise ValueError(
                "The file's button layer or physical index does not match this slot."
            )
        action = _object(value["action"], {"type", "value"}, "Button action")
        if (
            not isinstance(action["type"], str)
            or action["type"] not in item["actionTypes"]
        ):
            raise ValueError("The file contains an unsupported button action type.")
        if action["type"] == "macro":
            events = action["value"]
            if not isinstance(events, list) or not 1 <= len(events) <= 256:
                raise ValueError("A macro must contain 1–256 events.")
            for event in events:
                if not isinstance(event, list) or len(event) != 2:
                    raise ValueError("Each macro event must be [type, value].")
                _integer(event[0], "Macro event type", 1, 3)
                _integer(event[1], "Macro event value", 0, 60000)
        else:
            _integer(action["value"], "Button action value")
            if action["type"] == "none" and action["value"] != 0:
                raise ValueError("A disabled button must have action value 0.")
        mapping_validator(item, device, action["type"], deepcopy(action["value"]))
        if item["actionValue"] != action["value"]:
            raise ValueError(
                "The file contains a button action that cannot be represented exactly."
            )

    leds = _indexed(content["leds"], profile["leds"], "LED")
    for item in candidate["leds"]:
        value = _object(leds[item["index"]], led_keys(item), "Supported LED settings")
        mode = _integer(value["mode"], "LED mode")
        if mode not in item["modes"]:
            raise ValueError("The LED mode is not supported by this profile slot.")
        item["mode"] = mode
        if "color" in value:
            rgb = value["color"]
            if not isinstance(rgb, list) or len(rgb) != 3:
                raise ValueError("LED color must contain three RGB channels.")
            for channel in rgb:
                _integer(channel, "RGB channel", 0, 255)
                if item["colorDepth"] == 2 and channel not in (0, 255):
                    raise ValueError("This LED supports only on/off RGB channels.")
            item["colorRgb"] = deepcopy(rgb)
            item["color"] = "#{:02x}{:02x}{:02x}".format(*rgb)
        if "brightness" in value:
            item["brightness"] = _integer(value["brightness"], "LED brightness", 0, 255)
        duration = _integer(
            value["effectDuration"],
            "LED effect duration",
            item.get("effectDurationMinimum", 0),
            item.get("effectDurationMaximum", 10000),
        )
        if duration % item.get("effectDurationStep", 1):
            raise ValueError(
                "LED effect duration cannot be represented exactly by this device."
            )
        item["effectDuration"] = duration
    return candidate


def local_path(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Choose a local JSON file.")
    url = QUrl(value)
    if url.scheme():
        if (
            not url.isLocalFile()
            or url.host() not in ("", "localhost")
            or url.hasQuery()
            or url.hasFragment()
        ):
            raise ValueError(
                "Profile files must use a local file path, not a remote URL."
            )
        value = url.toLocalFile()
    path = Path(value)
    if not path.is_absolute() or "\x00" in str(path):
        raise ValueError("Choose an absolute local file path.")
    return path


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON field: {key}.")
        value[key] = item
    return value


def _reject_constant(value):
    raise ValueError(f"Invalid JSON number: {value}.")


def read_document(value):
    path = local_path(value)
    # Nonblocking prevents a named pipe from hanging the UI before fstat.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("Choose a regular local file.")
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Profile files must be no larger than 1 MiB.")
    try:
        return json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"Invalid UTF-8 JSON profile file: {exc}") from exc


def write_document(value, document, overwrite=False):
    """Atomically save, with no partial files and no implicit overwrite."""
    path = local_path(value)
    data = (
        json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Profile files must be no larger than 1 MiB.")
    if path.is_symlink():
        raise ValueError("Choose a file that is not a symbolic link.")
    if path.exists() and (not path.is_file() or not overwrite):
        raise ValueError(
            "The destination exists. Confirm replacement in the Save dialog or choose another name."
        )
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=".piper-profile-", suffix=".tmp", dir=path.parent
        )
    except PermissionError as exc:
        raise ValueError(
            "This location does not allow a safe atomic save. Choose another writable folder; the existing file has not been changed."
        ) from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            # link is atomic and fails if another writer created the target.
            os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
