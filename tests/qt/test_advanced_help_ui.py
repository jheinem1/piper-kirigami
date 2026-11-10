# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify inline native help with mock devices and actual Qt input/screenshots.

Run directly with --output to retain the geometry, input and screenshot report.
No real device or desktop input is used. The same runner supports an isolated
KWin Wayland session as well as pytest's offscreen software-rendered platform.
"""

import argparse
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
def test_advanced_inline_help(font_points, tmp_path):
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
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "advanced-help.json").read_text())
    assert report["passed"]
    assert report["qml_warnings"] == []
    assert report["transport_writes"] == 0
    assert report["source_unchanged"]
    assert len(report["geometry"]) == 16


def verify(h, kde):
    from PySide6.QtQml import QQmlEngine

    Qt = kde.Qt
    QPointF = kde.QPointF
    points = int(os.environ.get("PIPER_TEST_FONT_POINTS", "11"))
    geometry = []
    fixed_width = None

    def rect(item):
        pos = item.mapToScene(QPointF())
        return [pos.x(), pos.y(), item.width(), item.height()]

    def expression(obj, source):
        expr = kde.original_ui.QQmlExpression(
            QQmlEngine.contextForObject(obj), obj, source
        )
        result = expr.evaluate()
        assert not expr.hasError(), expr.error().toString()
        result = result[0] if isinstance(result, tuple) else result
        return result.toVariant() if hasattr(result, "toVariant") else result

    for dark in (False, True):
        if h.window.property("darkMode") != dark:
            h.toggle_theme()
        for width, height in [(1280, 820), (960, 700)]:
            h.window.resize(width, height)
            h.settle(150)
            for device in ("G600", "Capability"):
                h.select_device(device)
                h.click("advancedTab")
                form = h.find("advancedForm")
                grid = form.childItems()[0]
                grid_center = grid.mapToScene(QPointF(grid.width() / 2, 0)).x()
                form_center = form.mapToScene(QPointF(form.width() / 2, 0)).x()
                assert abs(grid_center - form_center) <= 1
                for control_name, help_name in [
                    ("angleSnapping", "angleSnappingInfo"),
                    ("debounce", "debounceInfo"),
                ]:
                    field = h.find(control_name)
                    help_button = h.find(help_name)
                    assert field.isEnabled() == (device == "Capability")
                    assert (
                        help_button.isEnabled()
                    ), "Unsupported controls still need help"
                    assert h.fully_visible(field) and h.fully_visible(help_button)
                    field_rect, help_rect = rect(field), rect(help_button)
                    error = (help_rect[1] + help_rect[3] / 2) - (
                        field_rect[1] + field_rect[3] / 2
                    )
                    assert abs(error) <= 1, (control_name, field_rect, help_rect)
                    assert help_rect[0] >= field_rect[0] + field_rect[2]
                    assert help_button.parentItem() == field.parentItem()
                    spacing = field.parentItem().property("spacing")
                    if control_name == "debounce" or device == "Capability":
                        assert (
                            abs(help_rect[0] - field_rect[0] - field_rect[2] - spacing)
                            <= 1
                        )
                    assert (
                        expression(help_button, "icon.name")
                        == "help-contextual-symbolic"
                    )
                    assert help_button.property("helpText")
                    geometry.append(
                        dict(
                            font_points=points,
                            theme="dark" if dark else "light",
                            window=[width, height],
                            device=device,
                            field=control_name,
                            field_rect=field_rect,
                            help_rect=help_rect,
                            center_error=error,
                        )
                    )
                debounce = h.find("debounce")
                if fixed_width is None:
                    fixed_width = debounce.width()
                assert abs(debounce.width() - fixed_width) <= 1
                assert abs(rect(debounce)[0] - rect(h.find("angleSnapping"))[0]) <= 1
                h.capture(
                    f"advanced-{'dark' if dark else 'light'}-{device.lower()}-{width}-{points}pt"
                )

    # Check both explanations with the actual native click/keyboard handlers.
    for device in ("Capability", "G600"):
        h.select_device(device)
        for name in ("angleSnappingInfo", "debounceInfo"):
            help_button = h.find(name)
            h.click(name)
            assert help_button.property("toolTipVisible")
            h.capture(f"{device.lower()}-{name}-tooltip-{points}pt")
            h.click(name)
            assert not help_button.property("toolTipVisible")
            # Native help intentionally stays visible while the pointer is on
            # the icon or tooltip. Move away before testing keyboard dismissal.
            kde.QTest.mouseMove(h.window, QPointF(h.window.width() - 30, 400).toPoint())
            h.interactions.append({"action": "mouse_move", "target": "blank_content"})
            h.settle(250)
            tooltips = [
                obj
                for obj in help_button.findChildren(kde.original_ui.QObject)
                if obj.inherits("QQuickToolTip")
            ]
            assert len(tooltips) == 1
            tooltip = tooltips[0]
            assert not tooltip.property("visible")
            h.focus_with_tab(name)
            h.key(Qt.Key.Key_Space)
            assert help_button.property("toolTipVisible")
            assert tooltip.property("visible")
            h.key(Qt.Key.Key_Escape)
            assert not help_button.property("toolTipVisible")
            assert not tooltip.property("visible")
            h.key(Qt.Key.Key_Space)
            assert help_button.property("toolTipVisible")
            h.key(Qt.Key.Key_Tab)
            assert not help_button.property("toolTipVisible")
            h.settle(250)  # Let the native tooltip's exit transition complete.
            assert not tooltip.property("visible")
        h.click("debounceInfo")
        assert h.find("debounceInfo").property("toolTipVisible")
        h.click("sensitivityTab")
        assert not h.find("debounceInfo").property("toolTipVisible")
        h.click("advancedTab")
        assert not h.find("debounceInfo").property("toolTipVisible")
    assert not h.backend.dirty
    assert h.backend._transport.calls == []
    h.clean_qml()
    return dict(geometry=geometry, transport_writes=0, native_help_interactions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location(
        "advanced_help_harness", ROOT / "tools/verify-kde-ui.py"
    )
    kde = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kde)
    hashes = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in ("qt_piper/qml/Main.qml", "qt_piper/qml/ContextHelpButton.qml")
    }
    report = dict(passed=False, source_sha256=hashes)
    h = None
    try:
        h = kde.KDEHarness(args.output)
        report.update(verify(h, kde))
        report["passed"] = True
    except Exception:
        report["error"] = traceback.format_exc()
        print(report["error"], flush=True)
        if h:
            h.capture("FAILED-advanced-help")
    finally:
        if h:
            report.update(
                qml_warnings=h.qml_warnings,
                screenshots=h.screenshots,
                interactions=h.interactions,
            )
            h.close()
    report["source_unchanged"] = all(
        hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == value
        for name, value in hashes.items()
    )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "advanced-help.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
