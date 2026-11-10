# SPDX-License-Identifier: GPL-2.0-or-later
"""Isolated, mock-only QTest coverage for fixed forms and the Qt color chooser.

Run directly with --output to preserve screenshots and a verification report.
The offscreen platform exercises Qt's color-dialog fallback. Production leaves
native-dialog selection to Qt/KDE; no desktop windows or mouse devices are used.
"""

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("font_points", [11, 14])
def test_native_forms_and_color_picker(font_points, tmp_path):
    env = os.environ.copy()
    env.update(
        QT_QPA_PLATFORM="offscreen",
        QT_QUICK_BACKEND="software",
        PIPER_TEST_FONT_POINTS=str(font_points),
    )
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), env.get("PYTHONPATH", "")])
    result = subprocess.run(
        [sys.executable, __file__, "--output", str(tmp_path)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "native-forms.json").read_text())
    assert report["passed"]
    assert report["qml_warnings"] == []
    assert report["transport_writes"] == 0
    assert report["source_unchanged"]


def verify(h, kde):
    Qt = kde.Qt
    QPointF = kde.QPointF
    QTest = kde.QTest
    report = {"assignment_geometry": []}
    points = int(os.environ.get("PIPER_TEST_FONT_POINTS", "11"))
    if points == 14:
        h.toggle_theme()
    h.select_device("Capability")
    h.edit_target(0)
    fixed_width = None
    for width, height in [(1280, 820), (960, 700)]:
        h.window.resize(width, height)
        h.settle(150)
        for action, field in [
            ("button", "mouseButtonPicker"),
            ("key", "keyPicker"),
            ("special", "specialAction"),
            ("none", None),
            ("macro", None),
        ]:
            h.mapping_type(action)
            form = h.find("assignmentForm")
            grid = form.childItems()[0]
            page = h.find("assignmentPage")
            center = grid.mapToScene(QPointF(grid.width() / 2, 0)).x()
            page_center = page.mapToScene(QPointF(page.width() / 2, 0)).x()
            assert abs(center - page_center) <= 1, (center, page_center, action)
            controls = ["mappingType"] + ([field] if field else [])
            for name in controls:
                item = h.find(name)
                assert h.fully_visible(item), f"{name} clipped at {width}, {points} pt"
                assert abs(item.width() - form.property("controlWidth")) <= 1
                if fixed_width is None:
                    fixed_width = item.width()
                assert abs(item.width() - fixed_width) <= 1, "Field stretches on resize"
            if field:
                assert (
                    abs(
                        h.find(field).mapToScene(QPointF()).x()
                        - h.find("mappingType").mapToScene(QPointF()).x()
                    )
                    <= 1
                )
            if action == "macro":
                panel = h.find("macroEventPanel")
                scroll = h.find("mappingScroll")
                assert panel.width() >= scroll.width() - 2
                assert panel.width() > fixed_width
                assert h.fully_visible(panel)
                h.capture(f"assignment-macro-{width}-{points}pt")
            elif action == "button":
                h.capture(f"assignment-button-{width}-{points}pt")
            report["assignment_geometry"].append(
                {
                    "window": [width, height],
                    "action": action,
                    "field_width": fixed_width,
                    "center_error": round(center - page_center, 3),
                }
            )
    h.back(discard=True)

    def popup_window():
        matches = [
            w
            for w in h.app.topLevelWindows()
            if w.isVisible() and w.title() == "Choose lighting color"
        ]
        assert len(matches) == 1, "Qt color chooser did not open"
        return matches[0]

    def descendants(item):
        yield item
        for child in item.childItems():
            yield from descendants(child)

    def popup_item(window, name=None, text=None):
        matches = [
            item
            for item in descendants(window.contentItem())
            if (name and item.objectName() == name)
            or (
                text
                and item.property("text") == text
                and item.inherits("QQuickAbstractButton")
            )
        ]
        assert len(matches) == 1, (name, text, len(matches))
        return matches[0]

    def popup_click(window, item):
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        QTest.mouseClick(
            window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point
        )
        h.interactions.append(
            {
                "action": "color_dialog_click",
                "object": item.objectName() or item.property("text"),
            }
        )
        h.settle(120)

    def choose_color(value, accept):
        before = h.find("ledColor").property("text")
        h.click("ledColorButton")
        window = popup_window()
        field = popup_item(window, name="hex")
        assert field.property("text").lower() == before.lower()
        popup_click(window, field)
        h.key(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier, window)
        for char in value:
            key = (
                Qt.Key.Key_NumberSign
                if char == "#"
                else getattr(Qt.Key, "Key_" + char.upper())
            )
            h.key(key, window=window)
        h.key(Qt.Key.Key_Tab, window=window)
        assert (
            h.find("ledColor").property("text") == before
        ), "Preview changed the outer draft"
        if accept:
            popup_click(window, popup_item(window, text="OK"))
            assert h.find("ledColor").property("text").lower() == value.lower()
        else:
            path = h.output / f"qt-color-chooser-{points}pt.png"
            assert window.grabWindow().save(str(path))
            h.screenshots.append(
                {
                    "file": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
            popup_click(window, popup_item(window, text="Cancel"))
            assert h.find("ledColor").property("text") == before
        h.settle(120)
        assert not h.find("ledColorDialog").property("visible")
        # Offscreen Qt has no window manager to reactivate the parent after a
        # separate Popup.Window. Emulate that platform step, not a control click.
        assert h.find("ledColorButton").hasFocus()
        h.window.requestActivate()
        h.settle(100)
        assert h.find("ledColorButton").hasActiveFocus()

    h.click("lightingTab")
    original = deepcopy(h.backend.selectedProfile["leds"][0])
    h.click("ledAssignment0")
    for name in [
        "ledMode",
        "ledColorButton",
        "ledColor",
        "ledBrightness",
        "ledDuration",
        "ledCancel",
        "ledSave",
    ]:
        assert h.fully_visible(h.find(name)), f"{name} clipped at 960×700, {points} pt"
    assert h.find("ledBrightness").isEnabled()
    h.capture(f"lighting-editor-960-{points}pt")
    choose_color("#ee8833", accept=False)
    assert not h.backend.dirty
    choose_color("#33aaff", accept=True)
    assert h.backend.selectedProfile["leds"][0] == original
    h.click("ledCancel")
    assert not h.backend.dirty
    h.click("ledAssignment0")
    assert h.find("ledColor").property("text").lower() == original["color"].lower()
    choose_color("#33aaff", accept=True)
    h.click("ledSave")
    assert h.backend.selectedProfile["leds"][0]["color"].lower() == "#33aaff"
    assert h.backend._transport.calls == [], "Color chooser sent a device write"
    h.click("resetButton")
    assert h.backend.selectedProfile["leds"][0] == original

    h.select_device("G600")
    h.click("ledAssignment0")
    assert not h.find("ledBrightness").isEnabled()
    assert h.find("ledDuration").property("stepSize") == 1000
    assert h.find("ledDuration").property("to") == 15000
    h.click("ledColorButton")
    window = popup_window()
    h.key(Qt.Key.Key_Escape, window=window)
    assert h.find("ledDialog").property("visible"), "Escape closed the parent editor"
    assert not h.find("ledColorDialog").property("visible")
    h.window.requestActivate()
    h.settle(100)
    assert not h.backend.dirty
    h.click("ledCancel")

    # Inject an unsupported capability into this local editor, not the backend.
    led = deepcopy(h.backend.selectedProfile["leds"][0])
    led["colorDepth"] = 0
    expression = kde.original_ui.QQmlExpression(
        h.engine.rootContext(),
        h.find("ledDialog"),
        "load(" + json.dumps(led) + "); open();",
    )
    expression.evaluate()
    assert not expression.hasError(), expression.error().toString()
    h.settle(150)
    assert not h.find("ledColorButton").isEnabled()
    assert not h.find("ledColor").isEnabled()
    assert h.find("ledSave").isEnabled()
    h.capture(f"lighting-unsupported-color-{points}pt")
    h.click("ledCancel")
    assert not h.backend.dirty
    assert h.backend._transport.calls == []
    h.clean_qml()
    report.update(
        font_points=points,
        native_dialog_options="Qt platform default, no forced non-native option",
        isolated_dialog_renderer="Qt Quick offscreen fallback",
        cancel_preview_and_escape_preserve_draft=True,
        accepted_color_remains_local_until_editor_ok=True,
        editor_cancel_and_reopen_restore_color=True,
        capability_controls_preserved=True,
        transport_writes=0,
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location(
        "native_forms_harness", ROOT / "tools/verify-kde-ui.py"
    )
    kde = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kde)
    sources = [
        ROOT / "qt_piper/qml" / name
        for name in [
            "AssignmentPage.qml",
            "LedDialog.qml",
            "Main.qml",
            "ValuePicker.qml",
        ]
    ]
    hashes = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sources
    }
    result = {"passed": False, "source_sha256": hashes}
    h = None
    try:
        h = kde.KDEHarness(args.output)
        result.update(verify(h, kde))
        result["passed"] = True
    except Exception:
        result["error"] = traceback.format_exc()
        print(result["error"], flush=True)
        if h:
            h.capture("FAILED-native-forms")
    finally:
        if h:
            result.update(
                qml_warnings=h.qml_warnings,
                screenshots=h.screenshots,
                interactions=h.interactions,
            )
            h.close()
    result["source_unchanged"] = all(
        hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == value
        for p, value in hashes.items()
    )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "native-forms.json").write_text(json.dumps(result, indent=2) + "\n")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
