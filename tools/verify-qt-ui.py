#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Drive the real Kirigami UI with QTest and save native window evidence.

Run from the repository root:
    PYTHONPATH=.deps:. python tools/verify-qt-ui.py --output evidence

Hardware is never accessed: every scenario uses Backend(mock=True). Screenshots
are QQuickWindow.grabWindow() output, not mocked artwork or browser renderings.
"""

from __future__ import annotations

import argparse
import hashlib
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import traceback
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp/piper-qt-cache")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import (  # noqa: E402
    QCoreApplication,
    QEvent,
    QObject,
    QPointF,
    Qt,
    QUrl,
)
from PySide6.QtGui import QFont, QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression  # noqa: E402
from PySide6.QtQuick import QQuickItem  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from qt_piper.backend import Backend, MockTransport  # noqa: E402
from qt_piper.diagrams import DiagramCatalog, DiagramImageProvider  # noqa: E402
from qt_piper.recorder import MacroRecorder  # noqa: E402

_APP = None


def application():
    global _APP
    _APP = QGuiApplication.instance() or QGuiApplication(["piper-qt-ui-tests"])
    _APP.setApplicationName("Piper Kirigami QA")
    _APP.setOrganizationName("libratbag")
    _APP.setFont(QFont("Noto Sans", 11))
    return _APP


class ArtworkPreviewTransport(MockTransport):
    """Synthetic capability fixtures for checking real SVGs inside QML.

    This intentionally makes no claim about any named device's hardware
    capabilities. Each screenshot is labeled as an artwork QA preview.
    """

    ARTWORK = [
        "logitech-g502.svg",
        "roccat-kone-pure.svg",
        "logitech-g-pro-keyboard.svg",
        "steelseries-senseiraw.svg",
    ]

    def __init__(self, catalog):
        super().__init__("generic")
        self.catalog = catalog

    async def snapshot(self):
        base = (await super().snapshot())[0]
        result = []
        for index, filename in enumerate(self.ARTWORK):
            device = deepcopy(base)
            device["path"] = device["id"] = f"/artwork_preview/device{index}"
            device["svg"] = filename
            device["name"] = "Artwork QA: " + filename.removesuffix(".svg")
            document = self.catalog.document(filename)
            for pi, profile in enumerate(device["profiles"]):
                profile["path"] = f"{device['path']}/p{pi}"
                profile["name"] = "Preview profile " + str(pi + 1)
                original_button = profile["buttons"][0]
                original_led = profile["leds"][0]
                profile["buttons"] = []
                for hotspot in document.hotspots("buttons"):
                    button = deepcopy(original_button)
                    bi = hotspot["index"]
                    button.update(
                        index=bi,
                        physicalIndex=bi,
                        displayIndex=bi,
                        label=f"Button {bi+1}",
                        path=f"{profile['path']}/b{bi}",
                    )
                    profile["buttons"].append(button)
                profile["leds"] = []
                for hotspot in document.hotspots("leds"):
                    led = deepcopy(original_led)
                    li = hotspot["index"]
                    led.update(index=li, path=f"{profile['path']}/l{li}")
                    profile["leds"].append(led)
            result.append(device)
        return result


class UIHarness:
    def __init__(self, output: Path, artwork_preview=False, qml_path=None):
        self.app = application()
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.catalog = DiagramCatalog()
        self.backend = Backend(
            mock=True,
            fixture="all",
            transport=(
                ArtworkPreviewTransport(self.catalog) if artwork_preview else None
            ),
        )
        self.recorder = MacroRecorder()
        self.engine = QQmlApplicationEngine()
        self.qml_warnings = []
        self.screenshots = []
        self.interactions = []
        self.engine.warnings.connect(
            lambda errors: self.qml_warnings.extend(str(e.toString()) for e in errors)
        )
        for path in [
            os.environ.get("PIPER_KIRIGAMI_QML_PATH", ""),
            "/usr/lib/x86_64-linux-gnu/qt6/qml",
            "/usr/lib/qt6/qml",
            "/usr/lib64/qt6/qml",
        ]:
            if path and Path(path).exists():
                self.engine.addImportPath(path)
        self.engine.rootContext().setContextProperty("macroRecorder", self.recorder)
        self.engine.rootContext().setContextProperty("backend", self.backend)
        self.engine.rootContext().setContextProperty("diagrams", self.catalog)
        self.engine.addImageProvider(
            "piper-diagrams", DiagramImageProvider(self.catalog)
        )
        self.engine.load(
            QUrl.fromLocalFile(
                str(qml_path or ROOT / "qt_piper_baseline_v1/qml/Main.qml")
            )
        )
        assert self.engine.rootObjects(), "Main.qml failed to load: " + "\n".join(
            self.qml_warnings
        )
        self.window = self.engine.rootObjects()[0]
        self.window.requestActivate()
        self.settle(500)
        assert self.window.isVisible()
        self.idle()
        assert self.backend.connected, (
            "Mock backend must begin connected: " + self.backend.error
        )

    def close(self):
        self.window.close()
        self.engine.deleteLater()
        self.backend.close()
        self.backend.deleteLater()
        self.recorder.deleteLater()
        self.catalog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def settle(self, milliseconds=100):
        deadline = time.monotonic() + milliseconds / 1000
        while time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()

    def find(self, name):
        obj = self.window.findChild(QObject, name)
        if obj is None:
            # Repeater delegates belong to the visual tree, not necessarily the
            # QObject owner tree. Walk inside QML to avoid materializing opaque
            # Kirigami plugin classes as Python wrappers.
            expression = QQmlExpression(
                self.engine.rootContext(),
                self.window,
                "(function walk(item) { if (item.objectName === "
                + json.dumps(name)
                + ") return item; let children = item.children || []; for (let child of children) { let found = walk(child); if (found) return found; } return null; })(contentItem)",
            )
            result = expression.evaluate()
            obj = result[0] if isinstance(result, tuple) else result
            if hasattr(obj, "toQObject"):
                obj = obj.toQObject()
        assert obj is not None, f"Missing QML objectName={name}"
        return obj

    def click(self, name, x=None, y=None):
        item = self.find(name)
        assert isinstance(item, QQuickItem), f"{name} is not a visual QQuickItem"
        assert item.isVisible(), f"{name} is hidden"
        assert item.isEnabled(), f"{name} is disabled"
        point = item.mapToScene(
            QPointF(
                item.width() / 2 if x is None else x,
                item.height() / 2 if y is None else y,
            )
        )
        assert (
            0 <= point.x() < self.window.width()
            and 0 <= point.y() < self.window.height()
        ), f"{name} is outside window: {point}"
        QTest.mouseMove(self.window, point.toPoint())
        QTest.mouseClick(
            self.window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            point.toPoint(),
        )
        self.interactions.append(
            {"action": "mouse_click", "object": name, "x": point.x(), "y": point.y()}
        )
        self.settle()
        return item

    def key(self, key, modifiers=Qt.KeyboardModifier.NoModifier):
        QTest.keyClick(self.window, key, modifiers)
        self.settle(15)

    def combo(self, name, index):
        self.click(name)
        self.key(Qt.Key.Key_Home)
        for _ in range(index):
            self.key(Qt.Key.Key_Down)
        self.key(Qt.Key.Key_Return)
        self.settle()
        assert (
            self.find(name).property("currentIndex") == index
        ), f"{name} did not select item {index}"
        self.interactions.append(
            {"action": "keyboard_combo_select", "object": name, "index": index}
        )

    def mapping_type(self, action_type):
        types = self.find("mappingDialog").property("types")
        if hasattr(types, "toVariant"):
            types = types.toVariant()
        self.combo("mappingType", types.index(action_type))

    def idle(self):
        for _ in range(100):
            if not self.backend.busy:
                self.settle(50)
                return
            self.settle(20)
        raise AssertionError("Mock backend did not finish its asynchronous operation")

    def text(self, name, value):
        self.click(name)
        self.key(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        for char in str(value):
            if char == "#":
                self.key(Qt.Key.Key_NumberSign)
            elif char.isalpha():
                self.key(
                    getattr(Qt.Key, "Key_" + char.upper()),
                    (
                        Qt.KeyboardModifier.ShiftModifier
                        if char.isupper()
                        else Qt.KeyboardModifier.NoModifier
                    ),
                )
            else:
                keys = {
                    "[": Qt.Key.Key_BracketLeft,
                    "]": Qt.Key.Key_BracketRight,
                    ",": Qt.Key.Key_Comma,
                    " ": Qt.Key.Key_Space,
                    "-": Qt.Key.Key_Minus,
                }
                self.key(
                    keys.get(char, getattr(Qt.Key, "Key_" + char, Qt.Key.Key_unknown))
                )
        self.interactions.append(
            {"action": "keyboard_replace", "object": name, "value": str(value)}
        )
        self.settle()

    def spin(self, name, value):
        self.text(name, value)
        self.key(Qt.Key.Key_Return)
        assert (
            self.find(name).property("value") == value
        ), f"{name} did not accept {value}"

    def capture(self, name):
        self.settle(200)
        image = self.window.grabWindow()
        assert (
            not image.isNull() and image.width() >= 1024 and image.height() >= 680
        ), "Native Qt screenshot is empty or undersized"
        path = self.output / (name + ".png")
        assert image.save(str(path)), f"Could not save {path}"
        record = {
            "file": str(path),
            "width": image.width(),
            "height": image.height(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        self.screenshots.append(record)
        return record

    def select_device(self, fragment):
        names = [d["name"] for d in self.backend.devices]
        index = next(
            (i for i, name in enumerate(names) if fragment.lower() in name.lower()),
            None,
        )
        assert index is not None, f"Missing mock device {fragment!r}: {names}"
        self.combo("deviceSelect", index)
        assert self.backend.selectedDeviceIndex == index
        self.settle(150)

    def button(self, index):
        return next(
            b for b in self.backend.selectedProfile["buttons"] if b["index"] == index
        )

    def target_point(self, layer, index):
        model = self.backend.selectedDevice["svg"]
        count = len(self.backend.selectedProfile["buttons"])
        shifted = self.window.property("shifted")
        doc = self.catalog.document(model)
        hotspot = next(
            h for h in doc.hotspots(layer, count, shifted) if h["index"] == index
        )
        mask = doc.mask(hotspot["id"])
        item = self.find("mouseDiagram")
        scale = item.width() / doc.width
        candidates = [mask.interior_point()]
        # Sample near the middle first and insist that the rounded window pixel
        # still selects this ID, including at fractional image scaling.
        for gy in range(1, 30):
            for gx in range(1, 30):
                candidates.append(
                    (
                        hotspot["x"] + hotspot["width"] * gx / 30,
                        hotspot["y"] + hotspot["height"] * gy / 30,
                    )
                )
        for point in candidates:
            if point is None:
                continue
            x, y = point
            scene = item.mapToScene(QPointF(x * scale, y * scale)).toPoint()
            actual = item.mapFromScene(QPointF(scene))
            if (
                self.catalog.hitTest(
                    model, layer, actual.x() / scale, actual.y() / scale, count, shifted
                )
                == index
            ):
                return scene
        raise AssertionError(f"No window-pixel click can reach {model}:{hotspot['id']}")

    def click_target(self, layer, index):
        point = self.target_point(layer, index)
        QTest.mouseMove(self.window, point)
        self.settle(50)
        QTest.mouseClick(
            self.window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            point,
        )
        self.settle(120)
        name, field = (
            ("ledDialog", "ledIndex")
            if layer == "leds"
            else ("mappingDialog", "buttonIndex")
        )
        dialog = self.find(name)
        assert dialog.property(
            "visible"
        ), f"Clicking {layer}:{index} did not open its editor"
        assert (
            dialog.property(field) == index
        ), f"Clicking {layer}:{index} opened wrong editor index {dialog.property(field)}"
        self.interactions.append(
            {
                "action": "svg_pixel_click",
                "layer": layer,
                "index": index,
                "x": point.x(),
                "y": point.y(),
            }
        )

    def clean_qml(self):
        errors = [
            w
            for w in self.qml_warnings
            if any(
                s in w
                for s in [
                    "TypeError",
                    "ReferenceError",
                    "Cannot assign",
                    "Unable to assign",
                    "is not a function",
                    "Binding loop",
                ]
            )
        ]
        assert not errors, "QML runtime errors: " + "\n".join(errors)


def scenario_mapping(h):
    h.select_device("Capability")
    h.click("buttonsTab")
    h.capture("qt-buttons-before")
    original = dict(h.button(0))
    h.click_target("buttons", 0)
    h.capture("qt-button-target-selected")
    h.mapping_type("key")
    h.spin("keyCode", 46)
    h.capture("qt-button-key-mapping-editor")
    h.click("mappingCancel")
    assert h.button(0) == original and not h.backend.dirty, "Cancel changed the mapping"
    h.click_target("buttons", 0)
    h.mapping_type("key")
    h.spin("keyCode", 46)
    h.click("mappingSave")
    assert h.button(0)["actionType"] == "key" and h.button(0)["actionValue"] == 46
    assert h.backend.dirty
    h.capture("qt-buttons-key-mapping-saved")
    h.click("applyButton")
    h.idle()
    h.settle(200)
    assert not h.backend.dirty and not h.backend.error
    h.capture("qt-buttons-applied")
    h.click_target("buttons", 0)
    assert h.find("keyCode").property("value") == 46
    h.click("mappingCancel")


def scenario_gshift(h):
    h.select_device("G600")
    h.click("buttonsTab")
    h.capture("qt-g600-normal-before")
    normal = dict(h.button(0))
    h.click_target("buttons", 0)
    h.click("mappingCancel")
    h.click("gshiftLayer")
    assert h.window.property("shifted")
    h.capture("qt-g600-gshift-before")
    h.click_target("buttons", 21)
    h.capture("qt-g600-gshift-target-selected")
    h.mapping_type("button")
    h.spin("mouseButtonNumber", 5)
    h.click("mappingSave")
    assert h.button(21)["actionType"] == "button" and h.button(21)["actionValue"] == 5
    assert h.button(0) == normal, "G-Shift edit contaminated the normal layer"
    h.capture("qt-g600-gshift-mapping-saved")
    h.click("normalLayer")
    h.click_target("buttons", 0)
    assert h.find("mappingDialog").property("buttonIndex") == 0
    h.click("mappingCancel")
    h.click("applyButton")
    h.idle()
    assert not h.backend.dirty


def scenario_led(h):
    h.click("lightingTab")
    h.capture("qt-leds-before")
    assert h.backend.selectedProfile["leds"], "Fixture has no LEDs"
    h.click_target("leds", 0)
    h.capture("qt-led-target-selected")
    h.text("ledColor", "badcolor")
    h.click("ledSave")
    assert (
        h.find("ledDialog").property("visible") and not h.backend.dirty
    ), "Invalid color must retain editor without staging changes"
    h.combo("ledMode", 3)
    h.text("ledColor", "#33aaff")
    brightness = h.find("ledBrightness")
    assert not brightness.isEnabled(), "G600 driver does not support brightness"
    h.capture("qt-led-editor-configured")
    h.click("ledSave")
    led = h.backend.selectedProfile["leds"][0]
    assert led["mode"] == 3 and led["color"].lower() == "#33aaff", led
    assert led["brightness"] == 255
    assert h.backend.dirty
    h.capture("qt-leds-saved")
    h.click("applyButton")
    h.idle()
    assert not h.backend.dirty
    h.click_target("leds", 0)
    assert h.find("ledMode").property("currentIndex") == 3
    assert h.find("ledColor").property("text").lower() == "#33aaff"
    h.click("ledCancel")
    h.select_device("Capability")
    h.click_target("leds", 0)
    brightness = h.find("ledBrightness")
    h.click("ledBrightness", brightness.width() * 0.6, brightness.height() / 2)
    h.click("ledSave")
    assert 0 < h.backend.selectedProfile["leds"][0]["brightness"] < 255
    h.capture("qt-generic-led-brightness-saved")
    h.click("applyButton")
    h.idle()
    assert not h.backend.dirty


def scenario_dpi_profiles(h):
    h.capture("qt-sensitivity-before")
    original = h.backend.selectedProfile["resolutions"][0]["x"]
    target = original + 100
    values = h.backend.selectedProfile["resolutions"][0]["values"]
    h.combo("dpiX0", values.index(target))
    assert h.backend.selectedProfile["resolutions"][0]["x"] == target
    assert h.backend.dirty
    h.capture("qt-sensitivity-edited")
    h.click("profile1")
    assert h.backend.selectedProfileIndex == 1
    h.capture("qt-profile2-selected")
    h.click("profile0")
    assert (
        h.backend.selectedProfile["resolutions"][0]["x"] == target
    ), "Switching profile lost staged DPI"
    h.click("resetButton")
    assert (
        not h.backend.dirty
        and h.backend.selectedProfile["resolutions"][0]["x"] == original
    )
    h.capture("qt-sensitivity-reset")


def scenario_failure_disconnect(h):
    h.select_device("Capability")
    h.click("buttonsTab")
    original = dict(h.button(0))
    h.click_target("buttons", 0)
    h.mapping_type("key")
    h.spin("keyCode", 57)
    h.click("mappingSave")
    h.click("failCommitButton")
    h.click("applyButton")
    h.idle()
    h.settle(200)
    assert (
        h.backend.error and h.backend.dirty
    ), "Failed commit must retain pending changes and explain the failure"
    h.capture("qt-apply-failed")
    h.click("resetButton")
    assert not h.backend.dirty and h.button(0) == original
    h.click("simulateDisconnect")
    assert not h.backend.connected
    assert not h.find("applyButton").isEnabled()
    h.capture("qt-device-disconnected")
    h.click("simulateDisconnect")
    h.idle()
    assert h.backend.connected
    h.capture("qt-device-reconnected")


def scenario_all_targets(h):
    checked = []
    for device_index in range(len(h.backend.devices)):
        h.combo("deviceSelect", device_index)
        device = h.backend.selectedDevice
        layers = [False, True] if "g600" in device["svg"] else [False]
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
                h.click_target("buttons", hotspot["index"])
                h.click("mappingCancel")
                checked.append(f"{device['name']}:button:{hotspot['index']}")
        h.click("lightingTab")
        hotspots = h.catalog.describe(
            device["svg"], "leds", len(h.backend.selectedProfile["buttons"]), False
        )["hotspots"]
        for hotspot in hotspots:
            if any(
                led["index"] == hotspot["index"]
                for led in h.backend.selectedProfile["leds"]
            ):
                h.click_target("leds", hotspot["index"])
                h.click("ledCancel")
                checked.append(f"{device['name']}:led:{hotspot['index']}")
    assert len(checked) >= 45, f"Too little diagram click coverage: {len(checked)}"
    return {"targets_clicked": len(checked), "targets": checked}


def scenario_macro_recording(h):
    h.select_device("G600")
    h.click("buttonsTab")
    h.click_target("buttons", 8)
    original = h.button(8)["actionValue"]
    assert (
        json.loads(h.find("macroJson").property("text")) == original
    ), "Existing macro must load into the editor"
    h.mapping_type("macro")
    h.text("macroJson", "[]")
    h.click("mappingSave")
    assert h.find("mappingDialog").property("visible")
    assert h.find("mappingDialog").property("validation")
    assert h.button(8)["actionValue"] == original and not h.backend.dirty
    h.click("recordMacro")
    assert h.recorder.active
    QTest.keyClick(h.window, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    h.settle()
    h.click("recordMacro")
    assert not h.recorder.active
    expected = [[1, 29], [1, 46], [2, 46], [2, 29]]
    assert h.recorder.events == expected, h.recorder.events
    assert json.loads(h.find("macroJson").property("text")) == expected
    h.capture("qt-g600-macro-recorded")
    h.click("mappingSave")
    assert (
        h.button(8)["actionType"] == "macro" and h.button(8)["actionValue"] == expected
    )
    h.capture("qt-g600-macro-saved")
    h.click("applyButton")
    h.idle()
    assert not h.backend.dirty
    h.click_target("buttons", 8)
    assert json.loads(h.find("macroJson").property("text")) == expected
    h.click("recordMacro")
    QTest.keyPress(h.window, Qt.Key.Key_Shift)
    h.click("mappingCancel")
    assert (
        not h.recorder.active
    ), "Closing recorder must remove application event filter"
    assert h.button(8)["actionValue"] == expected and not h.backend.dirty
    QTest.keyRelease(h.window, Qt.Key.Key_Shift)


def scenario_advanced(h):
    h.select_device("Capability")
    h.click("advancedTab")
    assert h.find("angleSnapping").isEnabled()
    h.click("angleSnapping")
    h.combo("debounce", 2)
    assert h.backend.selectedProfile["angleSnapping"] == 1
    assert h.backend.selectedProfile["debounce"] == 8
    h.capture("qt-advanced-edited")
    h.click("applyButton")
    h.idle()
    assert not h.backend.dirty
    h.select_device("G600")
    assert not h.find("angleSnapping").isEnabled()
    assert not h.find("debounce").isEnabled()
    h.capture("qt-advanced-unsupported")


def scenario_profile_capabilities(h):
    h.select_device("Capability")
    values = h.backend.selectedProfile["resolutions"][0]["values"]
    h.combo("dpiY0", values.index(1200))
    assert h.backend.selectedProfile["resolutions"][0]["x"] == 400
    assert h.backend.selectedProfile["resolutions"][0]["y"] == 1200
    h.click("resolutionActive0")
    assert h.backend.selectedProfile["resolutions"][0]["active"]
    h.click("resolutionDefault0")
    assert h.backend.selectedProfile["resolutions"][0]["default"]
    h.click("resolutionEnabled2")
    assert not h.backend.selectedProfile["resolutions"][2]["enabled"]
    h.capture("qt-separate-axis-stages-edited")
    h.click("profile1")
    h.click("activateProfile")
    assert h.backend.selectedProfile["active"]
    h.text("profileName", "work")
    h.key(Qt.Key.Key_Return)
    assert h.backend.selectedProfile["name"] == "work"
    h.click("profile0")
    h.click("profileEnabled")
    assert not h.backend.selectedProfile["enabled"]
    h.capture("qt-profiles-configured")
    h.click("applyButton")
    h.idle()
    assert not h.backend.dirty
    assert h.backend.profiles[1]["name"] == "work" and h.backend.profiles[1]["active"]
    assert not h.backend.profiles[0]["enabled"]


def scenario_diagram_gallery(h):
    coverage = []
    for i in range(len(h.backend.devices)):
        h.combo("deviceSelect", i)
        filename = h.backend.selectedDevice["svg"]
        stem = filename.removesuffix(".svg")
        h.click("buttonsTab")
        h.capture("qt-artwork-" + stem + "-buttons")
        hotspots = h.catalog.describe(
            filename, "buttons", len(h.backend.selectedProfile["buttons"]), False
        )["hotspots"]
        if hotspots:
            h.click_target("buttons", hotspots[0]["index"])
            h.click("mappingCancel")
        h.click("lightingTab")
        h.capture("qt-artwork-" + stem + "-leds")
        hotspots = h.catalog.describe(
            filename, "leds", len(h.backend.selectedProfile["buttons"]), False
        )["hotspots"]
        if hotspots:
            h.click_target("leds", hotspots[0]["index"])
            h.click("ledCancel")
        coverage.append(filename)
    return {
        "artwork_ui_previews": coverage,
        "fixture_note": "Synthetic capabilities used only to verify actual SVG rendering inside QML; no device support or hardware-write claim.",
    }


def scenario_close_warning(h):
    values = h.backend.selectedProfile["resolutions"][0]["values"]
    h.combo("dpiX0", values.index(500))
    assert h.backend.dirty
    h.window.close()
    h.interactions.append({"action": "window_close_request", "dirty": True})
    h.settle()
    assert h.window.isVisible() and h.find("closeDialog").property("visible")
    h.capture("qt-close-unsaved-warning")
    h.click("keepEditingButton")
    assert h.window.isVisible() and not h.find("closeDialog").property("visible")
    assert h.backend.dirty and h.backend.selectedProfile["resolutions"][0]["x"] == 500
    h.window.close()
    h.interactions.append({"action": "window_close_request", "dirty": True})
    h.settle()
    h.click("discardCloseButton")
    assert not h.window.isVisible()
    assert (
        h.backend._transport.calls == []
    ), "Discard and close must never apply changes"


def scenario_theme(h):
    assert not h.window.property("darkMode")
    h.click("themeToggle")
    assert h.window.property("darkMode")
    h.click("buttonsTab")
    h.capture("qt-dark-buttons")
    original = h.button(0)
    h.click_target("buttons", 0)
    h.capture("qt-dark-button-editor")
    h.click("mappingCancel")
    assert h.button(0) == original and not h.backend.dirty
    h.click("lightingTab")
    h.click_target("leds", 0)
    h.capture("qt-dark-led-editor")
    h.click("ledCancel")
    assert not h.backend.dirty
    h.click("themeToggle")
    assert not h.window.property("darkMode")
    h.capture("qt-light-theme-restored")


SCENARIOS = {
    "mapping": scenario_mapping,
    "gshift": scenario_gshift,
    "led": scenario_led,
    "dpi_profiles": scenario_dpi_profiles,
    "failure_disconnect": scenario_failure_disconnect,
    "all_targets": scenario_all_targets,
    "macro_recording": scenario_macro_recording,
    "advanced": scenario_advanced,
    "profile_capabilities": scenario_profile_capabilities,
    "diagram_gallery": scenario_diagram_gallery,
    "close_warning": scenario_close_warning,
    "theme": scenario_theme,
}


def run_scenario(name, output):
    h = UIHarness(output, artwork_preview=name == "diagram_gallery")
    result = {"scenario": name, "passed": False}
    try:
        result.update(SCENARIOS[name](h) or {})
        h.clean_qml()
        result["passed"] = True
    except Exception:
        result["error"] = traceback.format_exc()
        h.capture("FAILED-" + name)
    finally:
        result["screenshots"] = h.screenshots
        result["interactions"] = h.interactions
        result["qml_warnings"] = h.qml_warnings
        h.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "evidence")
    parser.add_argument("--scenario", action="append", choices=SCENARIOS)
    args = parser.parse_args()
    report = {
        "renderer": "QQuickWindow.grabWindow; offscreen Qt Quick software; real Kirigami QML",
        "backend": "deterministic mock; no hardware writes",
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
    (args.output / "qt-ui-verification.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
