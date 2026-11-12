# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise the native slots list without writing to physical devices."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_profile_slots_native_ui(tmp_path):
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software")
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), env.get("PYTHONPATH", "")])
    result = subprocess.run(
        [sys.executable, str(Path(__file__)), str(tmp_path)],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def run_ui(output):
    from copy import deepcopy

    from PySide6.QtGui import QAccessible, QFont

    spec = importlib.util.spec_from_file_location(
        "piper_slots_kde", ROOT / "tools/verify-kde-ui.py"
    )
    kde = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kde)
    h = kde.KDEHarness(output)
    Qt = kde.Qt
    report = {"backend": "mock devices only", "screenshots": []}
    try:
        h.select_device("G600")
        h.click("profileTab")
        before = deepcopy(h.backend._draft)
        active = [p["index"] for p in h.backend.profiles if p["active"]]
        assert active == [0]
        slots = h.find("profileSlotList")
        assert slots.property("count") == 3
        assert QAccessible.queryAccessibleInterface(slots).role() == QAccessible.List

        def selected(index):
            assert h.backend.selectedProfileIndex == index
            assert h.find("profileSelect").property("currentIndex") == index
            assert slots.property("currentIndex") == index
            for i in range(3):
                row = h.find("profileSlot" + str(i))
                accessible = QAccessible.queryAccessibleInterface(row)
                assert accessible.role() == QAccessible.ListItem
                assert accessible.state().selected == (i == index)
                assert not accessible.state().checkable
                assert row.property("highlighted") == (i == index)
                assert not row.property("checkable")
            assert [p["index"] for p in h.backend.profiles if p["active"]] == active
            assert not h.backend._transport.calls

        h.click("profileSlot1")
        selected(1)
        assert h.find("profileSlotStatus0").property("text") == "Active"
        assert not h.find("profileSlotStatus1").isVisible()
        # A selected editor target is not the mouse's active slot.
        h.capture("profiles-inactive-slot-selected")
        for key, index in (
            (Qt.Key_Down, 2),
            (Qt.Key_Down, 2),
            (Qt.Key_Up, 1),
            (Qt.Key_Home, 0),
            (Qt.Key_End, 2),
            (Qt.Key_Return, 2),
            (Qt.Key_Space, 2),
        ):
            h.key(key)
            selected(index)
        h.combo("profileSelect", 0)
        selected(0)
        h.focus_with_tab("profileSlotList")
        h.key(Qt.Key_Down)
        selected(1)
        assert h.backend._draft == before and not h.backend.dirty

        # Busy state blocks both row and keyboard changes, retaining selection.
        h.backend._busy = True
        h.backend.changed.emit()
        h.settle()
        assert not slots.isEnabled()
        row = h.find("profileSlot2")
        kde.QTest.mouseClick(
            h.window,
            Qt.LeftButton,
            Qt.NoModifier,
            row.mapToScene(kde.QPointF(row.width() / 2, row.height() / 2)).toPoint(),
        )
        h.settle()
        h.key(Qt.Key_Up)
        selected(1)
        h.backend._busy = False
        h.backend.changed.emit()
        h.settle()
        h.click("profileSlot2")
        selected(2)

        for points in (11, 14):
            h.app.setFont(QFont("Noto Sans", points))
            for width in (960, 1280):
                h.window.resize(width, 700 if width == 960 else 820)
                for dark in (False, True):
                    if h.window.property("darkMode") != dark:
                        h.toggle_theme()
                    h.settle(150)
                    for i in range(3):
                        row = h.find("profileSlot" + str(i))
                        assert h.fully_visible(row)
                        assert h.fully_visible(h.find("profileSlotLabel" + str(i)))
                        assert row.width() == slots.width()
                    assert h.fully_visible(h.find("exportProfileFile"))
                    h.capture(
                        f"profiles-{'dark' if dark else 'light'}-{width}-{points}pt"
                    )

        # Device capability flags do not disable selecting a disabled slot.
        h.select_device("Capability")
        h.click("profileSlot1")
        h.text("profileName", "named draft")
        h.key(Qt.Key_Tab)
        h.click("profileEnabled")
        assert not h.backend.selectedProfile["enabled"], h.backend.selectedProfile
        pending = deepcopy(h.backend._draft)
        h.click("profileSlot0")
        assert h.find("profileSlotStatus1").property("text") == "Disabled"
        h.click("profileSlot1")
        assert (
            h.backend.selectedProfile["name"] == "named draft"
        ), h.backend.selectedProfile["name"]
        assert not h.backend.selectedProfile["enabled"], h.backend.selectedProfile
        assert h.backend._draft == pending, "draft changed during slot selection"
        assert not h.backend._transport.calls
        h.capture("profiles-disabled-slot-draft")
        h.click("resetButton")
        assert not h.backend.dirty
        h.clean_qml()
        report.update(
            passed=True,
            mouse_and_keyboard_selection=True,
            active_slot_unchanged=True,
            disabled_slot_editable=True,
            pending_edits_preserved=True,
            busy_guard=True,
            transport_writes=0,
            screenshots=h.screenshots,
            qml_warnings=h.qml_warnings,
        )
        (output / "profile-slots.json").write_text(json.dumps(report, indent=2) + "\n")
        print(
            "Native slots list: selection, keyboard, accessibility, drafts, busy and geometry passed."
        )
    finally:
        h.close()


if __name__ == "__main__":
    run_ui(Path(sys.argv[1]))
