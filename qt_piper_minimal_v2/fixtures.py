# SPDX-License-Identifier: GPL-2.0-or-later
"""Deterministic demonstration devices, never hardware detection results.

G600 topology and capabilities follow libratbag's driver-logitech-g600.c.
The downstream G600 patch hides raw index 20 (the colour buffer) and maps the
shifted layer's indices 21..40 back to physical buttons 0..19. Sample settings
are illustrative, not a claim about factory defaults or the user's mouse.
"""

from copy import deepcopy

SPECIAL_BASE = 1 << 30


def _dpi_values():
    values, dpi = [], 200
    while dpi <= 8200:
        values.append(dpi)
        dpi += 50 if dpi < 1000 else 100 if dpi < 2600 else 200 if dpi < 5000 else 500
    return values


def fixture_objects(kind="g600"):
    """Return a raw ratbagd-like object graph of (interface, properties)."""
    if kind not in ("g600", "generic", "all", "multi", "empty"):
        raise ValueError(f"Unknown demonstration fixture: {kind}")
    objects = {}
    device_paths = []
    if kind == "empty":
        return objects, device_paths
    kinds = ["g600", "generic"] if kind in ("all", "multi") else [kind]
    for name in kinds:
        g600 = name == "g600"
        dpath = f"/org/freedesktop/ratbag1/device/mock_{name}"
        device_paths.append(dpath)
        profiles = []
        for pindex in range(3 if g600 else 2):
            ppath = f"{dpath}/p{pindex}"
            profiles.append(ppath)
            resolutions, buttons, leds = [], [], []
            for index, dpi in enumerate((400, 800, 1600, 3200)):
                path = f"{ppath}/r{index}"
                resolutions.append(path)
                objects[path] = (
                    "Resolution",
                    {
                        "Index": index,
                        "IsActive": index == 1,
                        "IsDefault": index == 1,
                        "IsDisabled": False,
                        "Resolution": dpi if g600 else [dpi, dpi],
                        "Capabilities": [] if g600 else [1, 2],
                        "Resolutions": (
                            _dpi_values() if g600 else list(range(100, 16001, 100))
                        ),
                    },
                )
            for index in range(41 if g600 else 8):
                path = f"{ppath}/b{index}"
                buttons.append(path)
                physical = index - 21 if g600 and index >= 21 else index
                if physical < 5:
                    mapping = [1, physical + 1]
                elif g600 and physical == 5:
                    mapping = [2, SPECIAL_BASE + 17]
                elif physical == 6:
                    mapping = [2, SPECIAL_BASE + 9]
                elif physical == 7:
                    mapping = [2, SPECIAL_BASE + 10]
                else:
                    key = 2 + (physical - 8) % 10
                    mapping = [4, [[1, key], [2, key]]]
                if g600 and index >= 21 and physical >= 8:
                    key = 2 + (physical - 8) % 10
                    mapping = [4, [[1, 42], [1, key], [2, key], [2, 42]]]
                if g600 and index == 20:
                    mapping = [0, 0]
                objects[path] = (
                    "Button",
                    {
                        "Index": index,
                        "Mapping": mapping,
                        "ActionTypes": [0, 1, 2, 4] if g600 else [0, 1, 2, 3, 4],
                    },
                )
            path = f"{ppath}/l0"
            leds.append(path)
            objects[path] = (
                "Led",
                {
                    "Index": 0,
                    "Mode": 1,
                    "Modes": [0, 1, 2, 3],
                    "Color": [[89, 172, 235], [238, 118, 171], [148, 207, 94]][
                        pindex % 3
                    ],
                    "ColorDepth": 1,
                    "Brightness": 255,
                    "EffectDuration": 3000,
                },
            )
            objects[ppath] = (
                "Profile",
                {
                    "Index": pindex,
                    "Name": "" if g600 else ["Desktop", "Gaming"][pindex],
                    "Capabilities": [] if g600 else [100, 101, 102],
                    "Disabled": False,
                    "IsActive": pindex == 0,
                    "IsDirty": False,
                    "ReportRate": 1000,
                    "ReportRates": (
                        [125, 142, 166, 200, 250, 333, 500, 1000]
                        if g600
                        else [125, 250, 500, 1000]
                    ),
                    "AngleSnapping": -1 if g600 else 0,
                    "Debounce": -1 if g600 else 4,
                    "Debounces": [] if g600 else [2, 4, 8, 12],
                    "Resolutions": resolutions,
                    "Buttons": buttons,
                    "Leds": leds,
                },
            )
        objects[dpath] = (
            "Device",
            {
                "Name": (
                    "Logitech G600 Gaming Mouse" if g600 else "Capability test mouse"
                ),
                "Model": "usb:046d:c24a:0" if g600 else "usb:0000:0001:0",
                "DeviceType": 2,
                "FirmwareVersion": "Demo fixture",
                "Profiles": profiles,
            },
        )
    return deepcopy(objects), device_paths
