# SPDX-License-Identifier: GPL-2.0-or-later
"""Offline handbook checks; native widgets run in isolated QApplication processes."""

from html.parser import HTMLParser
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


class DocumentLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.anchors = set()
        self.links = []
        self.scripts = 0
        self.resources = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.anchors.update(
            value for key, value in attrs.items() if key in ("id", "name")
        )
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])
        if tag == "script":
            self.scripts += 1
        if "src" in attrs:
            self.resources.append(attrs["src"])


def test_handbook_is_standalone_and_has_valid_contents():
    html = (ROOT / "qt_piper/help/handbook.html").read_text(encoding="utf-8")
    parser = DocumentLinks()
    parser.feed(html)
    assert not parser.scripts
    assert not parser.resources
    local_links = [link[1:] for link in parser.links if link.startswith("#")]
    assert len(set(local_links)) == 20
    assert set(local_links) <= parser.anchors
    assert all(link.startswith(("#", "https://")) for link in parser.links)
    for phrase in (
        "The layer selector is view-only.",
        "No saved-profile library:",
        "only the current assignment draft",
        "child settings page inside the main window",
        "only the selected profile",
        "Recording stages a pending assignment; it never writes automatically.",
        "visual <b>Events</b> panel",
        "Selection remains local to the popup until you choose <b>OK</b>",
        "Selecting a key alone inserts nothing.",
        "Apply stays disabled while a sequence is incomplete",
        "does not restore factory settings",
        "this release does not register a DocBook handbook",
        "GPL-2.0-or-later",
    ):
        assert phrase in html
    assert "shortcut button" not in html
    assert "child-page capture" not in html
    assert "Save assignment" not in html
    assert "Check JSON syntax" not in html
    assert "sequence numerically" not in html
    assert {
        "assignment-" + action
        for action in ("button", "key", "special", "macro", "none")
    } <= parser.anchors


@pytest.mark.parametrize("scenario", ["reader", "topics", "recorder", "application"])
def test_native_handbook(scenario, tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / ".deps"), str(ROOT), env.get("PYTHONPATH", "")]
    )
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QT_QUICK_BACKEND"] = "software"
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    result = subprocess.run(
        [sys.executable, str(Path(__file__)), scenario, str(tmp_path)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"PASS {scenario}" in result.stdout


def check_reader(output):
    from PySide6.QtCore import QPoint, Qt, QUrl
    from PySide6.QtGui import QFont, QPalette, QTextCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialogButtonBox, QPushButton
    from qt_piper.desktop_style import (
        DesktopStyle,
        configure_application,
        prepare_desktop,
    )
    from qt_piper.help import Handbook

    prepare_desktop()
    app = QApplication([])
    app.setFont(QFont("Noto Sans", 11))
    configure_application(app)
    style = DesktopStyle(False)
    controller = Handbook()
    controller.showHelp()
    dialog = controller._dialog
    QTest.qWait(80)
    assert dialog.isVisible()
    assert len(dialog.browser.toPlainText()) > 10000
    assert dialog.browser.isReadOnly()
    assert not dialog.browser.openLinks()
    assert not dialog.browser.openExternalLinks()
    assert not dialog.testAttribute(Qt.WA_QuitOnClose)
    assert dialog.grab().save(str(output / "handbook-light.png"))
    style.setDark(True)
    QTest.qWait(30)
    assert dialog.grab().save(str(output / "handbook-dark-contents.png"))
    style.setDark(False)

    QTest.keyClick(dialog, Qt.Key_F, Qt.ControlModifier)
    QTest.qWait(20)
    assert dialog.search.hasFocus()
    QTest.keyClicks(dialog.search, "ratbagd")
    first = dialog.browser.textCursor().selectionStart()
    assert dialog.browser.textCursor().selectedText().lower() == "ratbagd"
    QTest.keyClick(dialog.search, Qt.Key_Return)
    second = dialog.browser.textCursor().selectionStart()
    assert second > first
    assert dialog.isVisible(), "Enter in search must not close the dialog"
    QTest.keyClick(dialog.search, Qt.Key_F3, Qt.ShiftModifier)
    assert dialog.browser.textCursor().selectionStart() == first
    # Previous at the first match wraps to the last occurrence.
    QTest.keyClick(dialog.search, Qt.Key_F3, Qt.ShiftModifier)
    assert dialog.browser.textCursor().selectionStart() > second
    assert "wrapped" in dialog.status.text()
    QTest.keyClick(dialog.search, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClicks(dialog.search, "no-such-handbook-phrase")
    assert dialog.status.text() == "No matches"
    QTest.mouseClick(dialog.findChild(QPushButton, "handbookContents"), Qt.LeftButton)
    assert dialog.search.text() == ""
    assert not dialog.next.isEnabled()
    assert not dialog.previous.isEnabled()
    assert dialog.browser.verticalScrollBar().value() < 50

    # Click a real contents hyperlink, rather than invoking the reader slot.
    dialog.browser.moveCursor(QTextCursor.Start)
    assert dialog.browser.find("On-device profiles")
    cursor = dialog.browser.textCursor()
    rect = dialog.browser.cursorRect(cursor)
    QTest.mouseClick(
        dialog.browser.viewport(), Qt.LeftButton, pos=rect.center() - QPoint(3, 0)
    )
    QTest.qWait(30)
    assert dialog.browser.verticalScrollBar().value() > 1000
    before = dialog.browser.toPlainText()
    dialog._open_link(QUrl("file:///not-a-handbook-file"))
    dialog._open_link(QUrl("javascript:invalid"))
    assert dialog.browser.toPlainText() == before

    style.setDark(True)
    QTest.qWait(30)
    assert dialog.browser.palette().color(QPalette.Base) == app.palette().color(
        QPalette.Base
    )
    assert dialog.grab().save(str(output / "handbook-dark.png"))
    dialog.resize(560, 400)
    QTest.qWait(20)
    for widget in (dialog.search, dialog.previous, dialog.next, dialog.browser):
        assert widget.width() > 0
        point = widget.mapTo(dialog, widget.rect().bottomRight())
        assert point.x() < dialog.width() and point.y() < dialog.height()
    assert dialog.grab().save(str(output / "handbook-minimum.png"))
    position = dialog.browser.verticalScrollBar().value()
    QTest.keyClick(dialog, Qt.Key_Escape)
    assert not dialog.isVisible()
    controller.showHelp()
    QTest.qWait(30)
    assert controller._dialog is dialog
    assert dialog.browser.verticalScrollBar().value() == position
    button_box = dialog.findChild(QDialogButtonBox, "handbookButtons")
    QTest.mouseClick(button_box.button(QDialogButtonBox.Close), Qt.LeftButton)
    assert not dialog.isVisible()
    controller.close()


def check_topics(output):
    from unittest.mock import patch
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from qt_piper.help import HANDBOOK_PATH, HELP_TOPICS, Handbook

    app = QApplication([])
    controller = Handbook()
    parser = DocumentLinks()
    parser.feed(HANDBOOK_PATH.read_text(encoding="utf-8"))
    assert parser.anchors >= HELP_TOPICS
    headings = {
        "assignment-button": "Mouse-button assignment",
        "assignment-key": "Keyboard-key assignment",
        "assignment-special": "Special-action assignment",
        "assignment-macro": "Macro assignment",
        "assignment-none": "Disabled assignment",
        "assignment-write-scope": "Assignment page: Help, Reset, Defaults and Apply",
    }
    for topic, heading in headings.items():
        assert controller.hasTopic(topic)
        assert controller.showTopic(topic)
        QTest.qWait(20)
        dialog = controller._dialog
        assert dialog.isVisible()
        assert dialog.property("helpTopic") == topic
        assert dialog.browser.verticalScrollBar().value() > 100
        top_line = dialog.browser.cursorForPosition(QPoint(30, 10)).block().text()
        assert top_line == heading, (topic, top_line)
        # A contextual jump must clear both an old query and its selection.
        dialog.search.setText("ratbagd")
        assert dialog.browser.textCursor().hasSelection()
    controller.showTopic("assignment-macro")
    assert dialog.search.text() == ""
    assert not dialog.browser.textCursor().hasSelection()
    position = dialog.browser.verticalScrollBar().value()
    controller.close()
    controller.showHelp()
    assert controller._dialog is dialog
    assert dialog.property("helpTopic") == "assignment-macro"
    assert dialog.browser.verticalScrollBar().value() == position
    # The QML API accepts local identifiers, never an arbitrary external URL/path.
    with patch("qt_piper.help.QDesktopServices.openUrl") as open_url:
        for invalid in (
            "https://example.invalid",
            "file:///etc/passwd",
            "../handbook",
            "#macros",
            "unknown",
            "",
        ):
            assert not controller.hasTopic(invalid)
            assert not controller.showTopic(invalid)
            assert dialog.property("helpTopic") == "assignment-macro"
            assert dialog.browser.verticalScrollBar().value() == position
        open_url.assert_not_called()
    controller.close()
    assert not controller.showTopic("missing-page")
    assert not dialog.isVisible()
    unopened = Handbook()
    assert not unopened.showTopic("missing-page")
    assert unopened._dialog is None
    for topic in ("buttons", "sensitivity", "lighting", "profiles", "advanced"):
        assert controller.hasTopic(topic)
    controller.showTopic("assignment-macro")
    assert dialog.grab().save(str(output / "handbook-topic-validation.png"))
    controller.close()
    app.processEvents()


def check_recorder(_output):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget
    from qt_piper.recorder import MacroRecorder

    app = QApplication([])
    target = QWidget()
    target.show()
    target.activateWindow()
    QTest.qWait(20)
    recorder = MacroRecorder()
    recorder.start(False)
    QTest.keyPress(target, Qt.Key_Control)
    QTest.keyClick(target, Qt.Key_F13)  # Unmapped; must not become Ctrl alone.
    QTest.keyRelease(target, Qt.Key_Control)
    assert recorder.error
    assert "cannot be recorded" in recorder.error
    recorder.stop()
    assert recorder.error, "Stopping must not hide the unsupported-key error"
    assert recorder.events == [[1, 29], [2, 29]]
    recorder.start(False)
    assert recorder.error == ""
    assert recorder.events == []
    QTest.keyClick(target, Qt.Key_F1)
    recorder.stop()
    assert recorder.error == ""
    assert recorder.events == [[1, 59], [2, 59]]

    accepted = []

    def accept_completed_chord():
        if not recorder.active and not recorder.error and recorder.events:
            accepted.append(list(recorder.events))

    recorder.changed.connect(accept_completed_chord)
    recorder.startChord()
    QTest.keyPress(target, Qt.Key_Control)
    QTest.keyPress(target, Qt.Key_C)
    QTest.keyRelease(target, Qt.Key_C)
    assert recorder.active, "Capture waits until all chord keys are released"
    QTest.keyRelease(target, Qt.Key_Control)
    assert not recorder.active
    assert recorder.events == [[1, 29], [1, 46], [2, 46], [2, 29]]
    assert accepted == [recorder.events]
    previous = list(accepted)

    recorder.startChord()
    QTest.keyPress(target, Qt.Key_Control)
    QTest.keyClick(target, Qt.Key_Escape)
    QTest.keyRelease(target, Qt.Key_Control)
    assert not recorder.active
    assert recorder.events == []
    assert recorder.error == ""
    assert accepted == previous, "Escape cannot replace the previous editor draft"

    recorder.startChord()
    QTest.keyPress(target, Qt.Key_C)
    recorder.cancel()
    QTest.keyRelease(target, Qt.Key_C)
    assert not recorder.active
    assert recorder.events == []
    assert recorder.error == ""
    assert accepted == previous

    recorder.startChord()
    QTest.keyPress(target, Qt.Key_Control)
    QTest.keyClick(target, Qt.Key_F13)
    QTest.keyRelease(target, Qt.Key_Control)
    assert not recorder.active
    assert recorder.error
    assert accepted == previous, "An unsupported key must not accept Ctrl alone"
    recorder.cancel()
    assert recorder.events == [] and recorder.error == ""
    target.close()
    app.processEvents()


def check_application(output):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest

    spec = importlib.util.spec_from_file_location(
        "handbook_kde_harness", ROOT / "tools/verify-kde-ui.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    harness = module.KDEHarness(output)
    try:
        assert not harness.backend.dirty
        harness.key(Qt.Key_F1)
        harness.settle(80)
        dialog = harness.handbook._dialog
        assert dialog is not None and dialog.isVisible()
        assert not harness.backend.dirty
        QTest.keyClick(dialog, Qt.Key_Escape)
        assert not dialog.isVisible()
        harness.window.requestActivate()
        harness.settle(50)
        harness.click("appMenuButton")
        harness.click("handbookMenuItem")
        assert dialog.isVisible()
        assert harness.handbook._dialog is dialog
        assert not harness.backend.dirty
        harness.clean_qml()
        QTest.keyClick(dialog, Qt.Key_Escape)
        harness.window.requestActivate()
        harness.settle(30)
        # Child Help and F1 follow every current action type without writing.
        harness.combo("deviceSelect", 1)
        harness.click("buttonEdit0")
        child = harness.find("assignmentPage")
        assert harness.window.property("assignmentEditing")
        types = child.property("types")
        if hasattr(types, "toVariant"):
            types = types.toVariant()
        assert {"none", "button", "key", "special", "macro"} <= set(types), types
        for action_type in ("button", "key", "special", "macro", "none"):
            harness.combo("mappingType", types.index(action_type))
            expected_topic = "assignment-" + action_type
            assert child.property("helpTopic") == expected_topic
            harness.key(Qt.Key_F1)
            harness.settle(30)
            assert dialog.isVisible()
            assert dialog.property("helpTopic") == expected_topic
            assert dialog.search.text() == ""
            assert not harness.backend.dirty
            QTest.keyClick(dialog, Qt.Key_Escape)
            harness.window.requestActivate()
            harness.settle(30)
            harness.click("helpButton")
            assert dialog.isVisible()
            assert dialog.property("helpTopic") == expected_topic
            assert not harness.backend.dirty
            QTest.keyClick(dialog, Qt.Key_Escape)
            harness.window.requestActivate()
            harness.settle(30)
        # Direct key assignments use the same pending-selection and Cancel contract.
        harness.combo("mappingType", types.index("key"))
        previous_key = harness.payload()["value"]
        harness.click("keyPicker")
        harness.text("valuePickerSearch", "47")
        harness.click("valuePickerOption47")
        assert harness.find("valuePicker").property("visible")
        assert harness.find("valuePickerOk").isEnabled()
        assert harness.payload()["value"] == previous_key
        harness.click("valuePickerCancel")
        assert harness.payload()["value"] == previous_key
        assert not harness.backend.dirty
        # The child edits events visually; Add cancellation and Help keep its draft.
        harness.combo("mappingType", types.index("macro"))
        assert harness.find("macroEventPanel").isVisible()
        assert not harness.find("macroJson").isVisible()
        assert child.findChild(module.original_ui.QObject, "recordMacro") is None
        previous_events = harness.payload()["value"]
        harness.click("macroAddEvent")
        assert harness.find("valuePicker").property("visible")
        assert harness.find("valuePicker").property("eventMode")
        assert not harness.find("valuePickerOk").isEnabled()
        harness.text("valuePickerSearch", "46")
        harness.click("valuePickerOption46")
        assert harness.find("valuePicker").property("visible")
        assert harness.find("valuePickerOk").isEnabled()
        assert harness.payload()["value"] == previous_events
        harness.click("valuePickerCancel")
        assert not harness.find("valuePicker").property("visible")
        assert harness.payload()["value"] == previous_events
        harness.add_event(1, 46)
        harness.add_event(2, 46)
        assert harness.payload()["value"] == previous_events + [[1, 46], [2, 46]]
        previous_shortcut = harness.find("macroJson").property("text")
        assert not harness.backend.dirty
        assert not harness.recorder.active
        harness.click("helpButton")
        assert dialog.isVisible()
        assert dialog.property("helpTopic") == "assignment-macro"
        assert harness.find("macroJson").property("text") == previous_shortcut
        QTest.keyClick(dialog, Qt.Key_F, Qt.ControlModifier)
        QTest.keyClicks(dialog.search, "DPI")
        assert dialog.search.text() == "DPI"
        assert not harness.recorder.active
        assert harness.find("macroJson").property("text") == previous_shortcut
        assert not harness.backend.dirty
        QTest.keyClick(dialog, Qt.Key_Escape)
        harness.window.requestActivate()
        harness.settle(30)
        harness.click("resetButton")
        assert not child.property("edited")
        harness.click("assignmentBack")
        assert not harness.window.property("assignmentEditing")
        harness.clean_qml()
        # Application shortcuts are captured only by the overview quick recorder.
        harness.click("buttonQuickMacro0")
        harness.key(Qt.Key_F1)
        assert harness.recorder.active
        assert not dialog.isVisible()
        assert harness.recorder.events == [[1, 59], [2, 59]]
        harness.key(Qt.Key_F, Qt.ControlModifier)
        assert harness.recorder.active
        assert not harness.find("settingsSearch").hasActiveFocus()
        assert not harness.backend.dirty
        harness.click("quickMacroCancel0")
        assert not harness.recorder.active
        assert not harness.backend.dirty
        # Overview Help pauses quick recording without staging or applying it.
        harness.click("buttonQuickMacro0")
        harness.key(Qt.Key_C)
        harness.click("helpButton")
        assert dialog.isVisible()
        assert dialog.property("helpTopic") == "buttons"
        assert not harness.recorder.active
        assert harness.window.property("quickMacroIndex") == 0
        assert not harness.backend.dirty
        QTest.keyClick(dialog, Qt.Key_Escape)
        harness.window.requestActivate()
        harness.settle(30)
        assert harness.find("quickMacroStop0").property("text") == "Use shortcut"
        harness.click("quickMacroStop0")
        assert harness.backend.profileMappingsDirty
        assert harness.window.property("quickMacroIndex") == -1
        assert harness.find("resetButton").property("text") == "Revert"
        harness.click("resetButton")
        assert not harness.backend.dirty
        harness.clean_qml()
        # Every current page has matching contextual Help; F1 uses the same topic.
        for control, page, topic in (
            ("buttonsTab", 1, "buttons"),
            ("sensitivityTab", 0, "sensitivity"),
            ("lightingTab", 2, "lighting"),
            ("profileTab", 4, "profiles"),
            ("advancedTab", 3, "advanced"),
        ):
            harness.click(control)
            assert harness.window.property("page") == page
            assert harness.window.property("contextHelpTopic") == topic
            assert harness.window.property("contextHelpAvailable")
            assert harness.find("helpButton").isVisible()
            assert harness.find("helpButton").isEnabled()
            harness.click("helpButton")
            assert dialog.isVisible()
            assert dialog.property("helpTopic") == topic
            QTest.keyClick(dialog, Qt.Key_Escape)
            harness.window.requestActivate()
            harness.settle(30)
            harness.key(Qt.Key_F1)
            assert dialog.isVisible()
            assert dialog.property("helpTopic") == topic
            QTest.keyClick(dialog, Qt.Key_Escape)
            harness.window.requestActivate()
            harness.settle(30)
        harness.clean_qml()
        harness.key(Qt.Key_F1)
        assert dialog.isVisible()
        # A modeless help window must not keep the app alive after main closes.
        QTimer.singleShot(0, harness.window.close)
        QTimer.singleShot(1500, lambda: harness.app.exit(23))
        assert harness.app.exec() == 0
        assert not dialog.isVisible()
    finally:
        harness.handbook.close()
        harness.close()


if __name__ == "__main__":
    output_path = Path(sys.argv[2])
    output_path.mkdir(parents=True, exist_ok=True)
    {
        "reader": check_reader,
        "topics": check_topics,
        "recorder": check_recorder,
        "application": check_application,
    }[sys.argv[1]](output_path)
    print("PASS " + sys.argv[1])
