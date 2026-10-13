#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify the minimal Kirigami iteration with real Qt mouse/keyboard events.

PYTHONPATH=.deps:. python tools/verify-minimal-ui.py --output evidence-minimal

Screenshots are native QQuickWindow captures. All writes use mock fixtures;
these checks do not access hardware. The original full-layout harness is kept
unchanged and supplies only shared QTest helpers.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import importlib.util
import hashlib
import json
from pathlib import Path
import traceback

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "piper_original_ui_harness", ROOT / "tools/verify-qt-ui.py"
)
original_ui = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(original_ui)
Qt = original_ui.Qt
QTest = original_ui.QTest


class MinimalHarness(original_ui.UIHarness):
    def __init__(self, output):
        super().__init__(output, qml_path=ROOT / "qt_piper_minimal_v2/qml/Main.qml")

    def capture(self, name):
        self.settle(200)
        image = self.window.grabWindow()
        assert not image.isNull()
        assert image.width() >= self.window.minimumWidth()
        assert image.height() >= self.window.minimumHeight()
        path = self.output / (name + ".png")
        assert image.save(str(path))
        record = {
            "file": str(path),
            "width": image.width(),
            "height": image.height(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        self.screenshots.append(record)
        return record

    def toggle_theme(self):
        self.click("appMenuButton")
        self.click("themeToggle")

    def edit_led(self, index):
        self.click("chooseMapping")
        assert self.find("ledDialog").property("visible")
        assert self.find("ledDialog").property("ledIndex") == index

    def select_target(self, layer, index):
        """Click a real rounded window pixel inside an SVG's exact region."""
        point = self.target_point(layer, index)
        QTest.mouseMove(self.window, point)
        self.settle(40)
        QTest.mouseClick(
            self.window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            point,
        )
        self.settle(120)
        self.interactions.append(
            {
                "action": "svg_pixel_click",
                "layer": layer,
                "index": index,
                "x": point.x(),
                "y": point.y(),
            }
        )
        if layer == "buttons":
            assert self.window.property("selectedButton") == index
            assert not self.find("mappingDialog").property(
                "visible"
            ), "Diagram selection should show an inspector, not open the editor"
            assert self.find("chooseMapping").isVisible()
            assert self.find("chooseMapping").isEnabled()
        else:
            assert self.window.property("selectedLed") == index
            assert not self.find("ledDialog").property("visible")
            assert self.find("chooseMapping").isVisible()
        assert (
            self.find("diagramArea").width() >= self.window.width() * 0.4
        ), "Inspector must not squeeze the device diagram into a narrow strip"

    def edit_selected(self, index):
        self.click("chooseMapping")
        dialog = self.find("mappingDialog")
        assert dialog.property("visible")
        assert dialog.property("buttonIndex") == index

    def focus_with_tab(self, name):
        """Navigate focus through actual Tab events, without forceActiveFocus."""
        target = self.find(name)
        for count in range(100):
            if target.hasActiveFocus():
                self.interactions.append(
                    {"action": "keyboard_tab_focus", "object": name, "tabs": count}
                )
                return
            self.key(Qt.Key.Key_Tab)
        active = self.window.activeFocusItem()
        raise AssertionError(
            f"{name} not reachable by Tab; last focus={active.objectName() if active else None}"
        )


def scenario_overview(h):
    assert h.window.property("page") == 1, "Buttons must be the default page"
    assert not h.window.property("shifted")
    assert not h.find("mappingDialog").property("visible")
    assert h.find("deviceSelect").isVisible()
    assert h.find("profileSelect").isVisible()
    assert "leaders=0" in h.find("mouseDiagram").property("source").toString()
    assert not h.window.property("allAssignments")
    h.select_device("G600")
    h.capture("minimal-light-overview")
    h.toggle_theme()
    assert h.window.property("darkMode")
    h.capture("minimal-dark-overview")
    h.toggle_theme()
    assert not h.window.property("darkMode")


def scenario_mapping(h):
    h.select_device("Capability")
    original = deepcopy(h.button(0))
    h.select_target("buttons", 0)
    h.capture("minimal-button-inspector")
    h.edit_selected(0)
    h.mapping_type("key")
    h.spin("keyCode", 46)
    h.capture("minimal-key-mapping-editor")
    h.click("mappingCancel")
    assert h.button(0) == original and not h.backend.dirty
    h.edit_selected(0)
    h.mapping_type("key")
    h.spin("keyCode", 46)
    h.click("mappingSave")
    assert h.button(0)["actionType"] == "key"
    assert h.button(0)["actionValue"] == 46
    assert h.backend.dirty
    h.capture("minimal-mapping-staged")
    h.click("resetButton")
    assert h.button(0) == original and not h.backend.dirty
    h.edit_selected(0)
    h.mapping_type("key")
    h.spin("keyCode", 46)
    h.click("mappingSave")
    h.click("applyButton")
    h.idle()
    assert not h.backend.dirty and not h.backend.error
    h.edit_selected(0)
    assert h.find("keyCode").property("value") == 46
    h.click("mappingCancel")
    h.capture("minimal-mapping-applied")


def scenario_gshift(h):
    h.select_device("G600")
    normal = deepcopy(h.button(0))
    h.click("gshiftLayer")
    assert h.window.property("shifted")
    h.select_target("buttons", 21)
    h.capture("minimal-gshift-button1-inspector")
    h.edit_selected(21)
    h.mapping_type("button")
    h.spin("mouseButtonNumber", 5)
    h.click("mappingSave")
    assert h.button(21)["actionType"] == "button"
    assert h.button(21)["actionValue"] == 5
    assert h.button(0) == normal, "Shift edit contaminated the normal layer"
    assert h.backend.dirty
    h.edit_selected(21)
    assert h.find("mouseButtonNumber").property("value") == 5
    h.click("mappingCancel")
    h.click("normalLayer")
    assert not h.window.property("shifted")
    h.select_target("buttons", 0)
    assert h.button(0) == normal
    h.click("applyButton")
    h.idle()
    assert not h.backend.dirty and not h.backend.error
    # G9 demonstrates the MMO side-pad assignment in the review screenshots.
    h.click("gshiftLayer")
    h.select_target("buttons", 29)
    h.capture("minimal-light-gshift-inspector")
    h.edit_selected(29)
    h.capture("minimal-light-gshift-editor")
    assert not h.find("macroJson").isVisible(), "Raw sequence must be opt-in"
    h.click("advancedMacroToggle")
    assert h.find("macroJson").isVisible()
    assert (
        json.loads(h.find("macroJson").property("text")) == h.button(29)["actionValue"]
    )
    h.capture("minimal-advanced-macro-sequence")
    h.click("advancedMacroToggle")
    assert not h.find("macroJson").isVisible()
    h.click("mappingCancel")
    h.toggle_theme()
    h.capture("minimal-dark-gshift-inspector")
    h.edit_selected(29)
    assert not h.find("macroJson").isVisible()
    h.capture("minimal-dark-gshift-editor")
    h.click("mappingCancel")
    assert not h.backend.dirty


def scenario_led(h):
    h.select_device("G600")
    h.click("lightingTab")
    assert h.window.property("page") == 2
    h.capture("minimal-lighting")
    original = deepcopy(h.backend.selectedProfile["leds"][0])
    h.select_target("leds", 0)
    h.edit_led(0)
    h.text("ledColor", "badcolor")
    h.click("ledSave")
    assert h.find("ledDialog").property("visible")
    assert not h.backend.dirty
    h.click("ledCancel")
    assert h.backend.selectedProfile["leds"][0] == original
    h.select_target("leds", 0)
    h.edit_led(0)
    h.combo("ledMode", 3)
    h.text("ledColor", "#33aaff")
    assert not h.find("ledBrightness").isEnabled()
    h.capture("minimal-led-editor")
    h.click("ledSave")
    led = h.backend.selectedProfile["leds"][0]
    assert led["mode"] == 3 and led["color"].lower() == "#33aaff"
    assert h.backend.dirty
    h.click("applyButton")
    h.idle()
    assert not h.backend.dirty
    h.click("buttonsTab")
    assert h.window.property("page") == 1
    h.select_target("buttons", 0)


def scenario_profiles_and_sensitivity(h):
    h.select_device("Capability")
    h.click("sensitivityTab")
    assert h.window.property("page") == 0
    original = h.backend.selectedProfile["resolutions"][0]["x"]
    values = h.backend.selectedProfile["resolutions"][0]["values"]
    target = values[values.index(original) + 1]
    h.combo("dpiX0", values.index(target))
    assert h.backend.selectedProfile["resolutions"][0]["x"] == target
    assert h.backend.dirty
    h.combo("profileSelect", 1)
    assert h.backend.selectedProfileIndex == 1
    h.combo("profileSelect", 0)
    assert h.backend.selectedProfile["resolutions"][0]["x"] == target
    h.click("resetButton")
    assert h.backend.selectedProfile["resolutions"][0]["x"] == original
    assert not h.backend.dirty
    h.capture("minimal-sensitivity")
    h.click("profileTab")
    h.capture("minimal-profile-settings")
    h.click("appMenuButton")
    h.click("advancedMenuItem")
    assert h.window.property("page") == 3
    h.capture("minimal-advanced-settings")


def scenario_all_assignments(h):
    h.select_device("G600")
    assert not h.window.property("allAssignments")
    h.click("allAssignments")
    assert h.window.property("allAssignments")
    h.capture("minimal-all-assignments")
    h.click("buttonAssignment0")
    assert h.window.property("selectedButton") == 0
    assert not h.find("mappingDialog").property("visible")
    h.edit_selected(0)
    h.click("mappingCancel")
    assert not h.window.property("allAssignments")
    h.click("closeInspector")
    h.capture("minimal-assignments-collapsed")


def scenario_keyboard(h):
    h.select_device("G600")
    h.focus_with_tab("diagramArea")
    h.key(Qt.Key.Key_Right)
    selected = h.window.property("selectedButton")
    assert selected >= 0
    h.focus_with_tab("chooseMapping")
    h.key(Qt.Key.Key_Space)
    assert h.find("mappingDialog").property("visible")
    assert h.find("mappingDialog").property("buttonIndex") == selected
    h.focus_with_tab("mappingCancel")
    h.key(Qt.Key.Key_Space)
    assert not h.find("mappingDialog").property("visible")
    assert not h.backend.dirty
    h.focus_with_tab("gshiftLayer")
    h.key(Qt.Key.Key_Space)
    assert h.window.property("shifted")
    h.focus_with_tab("diagramArea")
    h.key(Qt.Key.Key_Right)
    assert h.window.property("selectedButton") >= 21
    h.focus_with_tab("chooseMapping")
    h.key(Qt.Key.Key_Space)
    assert h.find("mappingDialog").property("visible")
    assert h.find("mappingDialog").property("buttonIndex") >= 21
    h.key(Qt.Key.Key_Escape)
    assert not h.find("mappingDialog").property("visible")
    h.capture("minimal-keyboard-selected")


def scenario_all_targets(h):
    checked = []
    for device_index in range(len(h.backend.devices)):
        h.combo("deviceSelect", device_index)
        device = h.backend.selectedDevice
        layers = [False, True] if device.get("hasGShift") else [False]
        h.click("buttonsTab")
        for shifted in layers:
            if len(layers) > 1:
                h.click("gshiftLayer" if shifted else "normalLayer")
            hotspots = h.catalog.describe(
                device["svg"],
                "buttons",
                len(h.backend.selectedProfile["buttons"]),
                shifted,
            )["hotspots"]
            for hotspot in hotspots:
                index = hotspot["index"]
                h.select_target("buttons", index)
                h.edit_selected(index)
                h.click("mappingCancel")
                checked.append(f"{device['name']}:button:{index}")
        h.click("lightingTab")
        hotspots = h.catalog.describe(
            device["svg"], "leds", len(h.backend.selectedProfile["leds"]), False
        )["hotspots"]
        for hotspot in hotspots:
            index = hotspot["index"]
            if any(led["index"] == index for led in h.backend.selectedProfile["leds"]):
                h.select_target("leds", index)
                h.edit_led(index)
                h.click("ledCancel")
                checked.append(f"{device['name']}:led:{index}")
    assert len(checked) >= 45, f"Too little region coverage: {len(checked)}"
    assert not h.backend.dirty
    return {"targets_clicked": len(checked), "targets": checked}


def scenario_minimum_size(h):
    h.select_device("G600")
    h.window.resize(h.window.minimumWidth(), h.window.minimumHeight())
    h.settle(150)
    h.select_target("buttons", 0)
    h.edit_selected(0)
    h.capture("minimal-minimum-window-editor")
    h.click("mappingCancel")
    h.click("gshiftLayer")
    h.select_target("buttons", 21)
    h.capture("minimal-minimum-window-inspector")
    h.click("lightingTab")
    h.select_target("leds", 0)
    h.edit_led(0)
    h.click("ledCancel")
    h.click("profileTab")
    h.capture("minimal-minimum-window-profile")


SCENARIOS = {
    "overview": scenario_overview,
    "mapping": scenario_mapping,
    "gshift": scenario_gshift,
    "led": scenario_led,
    "profiles_and_sensitivity": scenario_profiles_and_sensitivity,
    "all_assignments": scenario_all_assignments,
    "keyboard": scenario_keyboard,
    "all_targets": scenario_all_targets,
    "minimum_size": scenario_minimum_size,
}


def run_scenario(name, output):
    h = None
    result = {"scenario": name, "passed": False}
    try:
        h = MinimalHarness(output)
        result.update(SCENARIOS[name](h) or {})
        h.clean_qml()
        result["passed"] = True
    except Exception:
        result["error"] = traceback.format_exc()
        if h is not None:
            h.capture("FAILED-" + name)
    finally:
        if h is not None:
            result["screenshots"] = h.screenshots
            result["interactions"] = h.interactions
            result["qml_warnings"] = h.qml_warnings
            h.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "evidence-minimal")
    parser.add_argument("--scenario", action="append", choices=SCENARIOS)
    args = parser.parse_args()
    report = {
        "renderer": "Native QQuickWindow.grabWindow; Qt Quick software; real Kirigami QML",
        "backend": "Deterministic mock fixtures; no hardware accessed",
        "results": [],
    }
    for name in args.scenario or SCENARIOS:
        result = run_scenario(name, args.output)
        report["results"].append(result)
        print(f"{name}: {'PASS' if result['passed'] else 'FAIL'}", flush=True)
        if not result["passed"]:
            print(result["error"], flush=True)
    report["passed"] = all(result["passed"] for result in report["results"])
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "minimal-ui-verification.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
