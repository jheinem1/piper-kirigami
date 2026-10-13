#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Capture and exercise the native Breeze settings pages using real QTest input.

PYTHONPATH=.deps:. python tools/verify-kde-settings.py --output evidence-kde/settings-refined

Mock devices only. Screenshots are actual QQuickWindow.grabWindow() captures.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import traceback

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "piper_kde", ROOT / "tools/verify-kde-ui.py"
)
kde = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(kde)
Qt = kde.Qt


def check_controls(h, names):
    for name in names:
        assert h.fully_visible(h.find(name)), f"{name} is clipped"


def capture_pages(h):
    for narrow in (False, True):
        h.window.resize(960 if narrow else 1280, 700 if narrow else 820)
        h.settle(150)
        for dark in (False, True):
            if h.window.property("darkMode") != dark:
                h.toggle_theme()
            mode = ("dark" if dark else "light") + ("-narrow" if narrow else "")
            for device in ("G600", "Capability"):
                h.select_device(device)
                for name, tab, controls in [
                    (
                        "sensitivity",
                        "sensitivityTab",
                        ["dpiX0", "dpiX3", "reportRate", "advancedSettingsLink"],
                    ),
                    ("profiles", "profileTab", ["profileName", "profileEnabled"]),
                    (
                        "advanced",
                        "advancedTab",
                        ["angleSnapping", "debounce", "advancedReportRate"],
                    ),
                    ("lighting", "lightingTab", ["ledAssignment0", "diagramTarget0"]),
                ]:
                    h.click(tab)
                    check_controls(h, controls)
                    h.capture(mode + "-" + device.lower() + "-" + name)
                h.click_target("leds", 0)
                check_controls(
                    h,
                    [
                        "ledMode",
                        "ledColor",
                        "ledBrightness",
                        "ledDuration",
                        "ledCancel",
                        "ledSave",
                    ],
                )
                h.capture(mode + "-" + device.lower() + "-lighting-editor")
                h.click("ledCancel")
    assert not h.backend.dirty


def sensitivity(h):
    h.select_device("Capability")
    h.window.resize(960, 700)
    h.settle(200)
    h.click("sensitivityTab")
    original = deepcopy(h.backend.selectedProfile)
    h.combo("dpiX0", 5)
    h.combo("dpiY0", 6)
    assert h.backend.selectedProfile["resolutions"][0]["x"] == 600
    assert h.backend.selectedProfile["resolutions"][0]["y"] == 700
    h.click("resolutionActive0")
    h.click("resolutionDefault2")
    assert h.backend.selectedProfile["resolutions"][0]["active"]
    assert h.backend.selectedProfile["resolutions"][2]["default"]
    assert h.find("resolutionActive0").property("checked")
    assert h.find("resolutionDefault2").property("checked")
    h.click("resolutionEnabled3")
    assert not h.backend.selectedProfile["resolutions"][3]["enabled"]
    h.combo("reportRate", 1)
    assert h.backend.selectedProfile["reportRate"] == 250
    h.focus_with_tab("advancedSettingsLink")
    assert h.fully_visible(
        h.find("advancedSettingsLink")
    ), "Focused settings action is clipped"
    h.capture("narrow-sensitivity-pending")
    h.click("resetButton")
    assert h.backend.selectedProfile == original
    assert not h.backend.dirty
    h.combo("dpiX0", 5)
    h.click("applyButton")
    h.idle()
    assert not h.backend.dirty and not h.backend.error
    assert h.backend.selectedProfile["resolutions"][0]["x"] == 600
    h.select_device("G600")
    for index in range(4):
        assert not h.find("dpiY" + str(index)).isVisible()
        assert not h.find("resolutionEnabled" + str(index)).isEnabled()
    assert h.find("reportRate").isEnabled()


def advanced(h):
    h.select_device("Capability")
    h.click("advancedTab")
    original = deepcopy(h.backend.selectedProfile)
    h.click("angleSnapping")
    h.combo("debounce", 2)
    h.combo("advancedReportRate", 2)
    assert h.backend.selectedProfile["angleSnapping"] == 1
    assert h.backend.selectedProfile["debounce"] == 8
    assert h.backend.selectedProfile["reportRate"] == 500
    h.click("resetButton")
    assert h.backend.selectedProfile == original
    h.click("angleSnapping")
    h.click("applyButton")
    h.idle()
    assert not h.backend.dirty and not h.backend.error
    assert h.backend.selectedProfile["angleSnapping"] == 1
    h.select_device("G600")
    assert not h.find("angleSnapping").isEnabled()
    assert not h.find("debounce").isEnabled()
    assert h.find("advancedReportRate").isEnabled()


def profiles(h):
    h.select_device("Capability")
    h.click("profileTab")
    h.combo("profileSelect", 1)
    original = deepcopy(h.backend.selectedProfile)
    h.text("profileName", "work")
    h.key(Qt.Key.Key_Tab)
    assert h.backend.selectedProfile["name"] == "work"
    h.click("profileEnabled")
    assert not h.backend.selectedProfile["enabled"]
    h.click("profileEnabled")
    h.click("activateProfile")
    assert h.backend.selectedProfile["active"]
    assert not h.find("activateProfile").isVisible()
    h.click("resetButton")
    h.combo("profileSelect", 1)
    assert h.backend.selectedProfile == original
    h.text("profileName", "work")
    h.key(Qt.Key.Key_Tab)
    h.click("applyButton")
    h.idle()
    assert not h.backend.dirty and not h.backend.error
    assert h.backend.selectedProfile["name"] == "work"
    h.select_device("G600")
    assert not h.find("profileName").isEnabled()
    assert not h.find("profileEnabled").isEnabled()


def lighting(h):
    h.select_device("Capability")
    h.click("lightingTab")
    original = deepcopy(h.backend.selectedProfile["leds"][0])
    h.click("ledAssignment0")
    h.text("ledColor", "badcolor")
    assert not h.find("ledSave").isEnabled()
    assert h.find("ledValidation").property("visible")
    h.text("ledColor", "#00aaff")
    assert h.find("ledSave").isEnabled()
    assert not h.find("ledValidation").property("visible")
    h.text("ledColor", "badcolor")
    assert not h.find("ledSave").isEnabled()
    assert h.find("ledDialog").property("visible")
    assert h.backend.selectedProfile["leds"][0] == original
    h.click("ledCancel")
    h.click("ledAssignment0")
    h.combo("ledMode", 3)
    h.text("ledColor", "#33aaff")
    h.spin("ledDuration", 2000)
    h.click("ledBrightness")
    h.key(Qt.Key.Key_Left)
    h.click("ledCancel")
    assert h.backend.selectedProfile["leds"][0] == original and not h.backend.dirty
    h.click_target("leds", 0)
    h.combo("ledMode", 3)
    h.text("ledColor", "#33aaff")
    h.spin("ledDuration", 2000)
    h.click("ledSave")
    assert not h.find("ledDialog").property("visible")
    led = h.backend.selectedProfile["leds"][0]
    assert led["mode"] == 3 and led["color"].lower() == "#33aaff"
    assert led["effectDuration"] == 2000
    h.click("resetButton")
    assert h.backend.selectedProfile["leds"][0] == original
    h.click("ledAssignment0")
    h.text("ledColor", "#33aaff")
    h.click("ledSave")
    h.click("applyButton")
    h.idle()
    assert not h.backend.dirty and not h.backend.error
    assert h.backend.selectedProfile["leds"][0]["color"].lower() == "#33aaff"
    h.select_device("G600")
    h.click_target("leds", 0)
    assert not h.find("ledBrightness").isEnabled()
    assert h.find("ledDuration").property("from") == 0
    assert h.find("ledDuration").property("to") == 15000
    assert h.find("ledDuration").property("stepSize") == 1000
    original_g600 = deepcopy(h.backend.selectedProfile["leds"][0])
    h.combo("ledMode", 3)
    h.text("ledColor", "#334455")
    h.spin("ledDuration", 1500)
    assert not h.find("ledSave").isEnabled()
    assert h.find("ledValidation").property("visible")
    assert h.find("ledDialog").property("visible")
    assert h.backend.selectedProfile["leds"][0] == original_g600
    assert not h.backend.dirty
    assert "1000" in h.find("ledValidation").property("text")
    h.spin("ledDuration", 15000)
    assert h.find("ledSave").isEnabled()
    assert not h.find("ledValidation").property("visible")
    h.click("ledSave")
    assert not h.find("ledDialog").property("visible")
    assert h.backend.selectedProfile["leds"][0]["effectDuration"] == 15000
    h.click("resetButton")
    h.click("ledAssignment0")
    h.spin("ledDuration", 0)
    h.click("ledSave")
    assert h.backend.selectedProfile["leds"][0]["effectDuration"] == 0
    h.click("ledAssignment0")
    assert h.find("ledDuration").property("value") == 0
    h.key(Qt.Key.Key_Escape)
    assert not h.find("ledDialog").property("visible")
    h.click("resetButton")
    assert h.backend.selectedProfile["leds"][0] == original_g600
    assert not h.backend.dirty


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "evidence-kde/settings-refined"
    )
    parser.add_argument("--skip-captures", action="store_true")
    args = parser.parse_args()
    h = kde.KDEHarness(args.output)
    report = {
        "backend": "Deterministic mock fixtures; no hardware accessed",
        "renderer": "QApplication; org.kde.desktop; native Breeze; QQuickWindow.grabWindow",
        "source_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [
                ROOT / "qt_piper/qml/Main.qml",
                ROOT / "qt_piper/qml/LedDialog.qml",
            ]
        },
        "checks": [],
    }
    try:
        checks = ([] if args.skip_captures else [capture_pages]) + [
            sensitivity,
            advanced,
            profiles,
            lighting,
        ]
        for check in checks:
            check(h)
            h.clean_qml()
            report["checks"].append({"name": check.__name__, "passed": True})
            print(check.__name__ + ": PASS", flush=True)
        report["passed"] = True
    except Exception:
        report["passed"] = False
        report["error"] = traceback.format_exc()
        print(report["error"], flush=True)
        h.capture("FAILED-settings")
    finally:
        report["screenshots"] = h.screenshots
        report["interactions"] = h.interactions
        report["qml_warnings"] = h.qml_warnings
        (args.output / "settings-verification.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        h.close()
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
