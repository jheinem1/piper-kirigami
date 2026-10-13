#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify the native Breeze/Kirigami iteration with actual QTest input.

PYTHONPATH=.deps:. python tools/verify-kde-ui.py --output evidence-kde/pane-layout

A QApplication and org.kde.desktop must be initialized before any controls are
created. Run this verifier in a separate process from the saved v1/v2 verifiers.
All backend writes use deterministic mock fixtures; hardware is never accessed.
Screenshots are real QQuickWindow.grabWindow() captures, not rendered mockups.
"""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
import traceback
from threading import Event

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "piper_kde_shared_ui_harness", ROOT / "tools/verify-qt-ui.py"
)
original_ui = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(original_ui)
Qt = original_ui.Qt
QTest = original_ui.QTest
QPointF = original_ui.QPointF

from PySide6.QtGui import QAccessible  # noqa: E402
from PySide6.QtQml import QQmlProperty  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from qt_piper.desktop_style import (  # noqa: E402
    DesktopStyle,
    configure_application,
    prepare_desktop,
)
from qt_piper.help import Handbook  # noqa: E402

_APP = None


def desktop_application():
    global _APP
    existing = QApplication.instance()
    assert existing is None or isinstance(
        existing, QApplication
    ), "KDE verification needs its own process; a QGuiApplication already exists"
    if existing is None:
        prepare_desktop()
        _APP = QApplication(["piper-kde-ui-tests"])
        configure_application(_APP)
    else:
        _APP = existing
    _APP.setApplicationName("Piper KDE QA")
    _APP.setOrganizationName("libratbag")
    _APP.setFont(
        original_ui.QFont(
            "Noto Sans", int(os.environ.get("PIPER_TEST_FONT_POINTS", "11"))
        )
    )
    assert QQuickStyle.name() == "org.kde.desktop", QQuickStyle.name()
    assert _APP.style().objectName().lower() == "breeze", (
        "Native Breeze widget style was not loaded: " + _APP.style().objectName()
    )
    return _APP


original_ui.application = desktop_application


class KDEHarness(original_ui.UIHarness):
    def __init__(self, output):
        self.app = desktop_application()
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.catalog = original_ui.DiagramCatalog()
        self.backend = original_ui.Backend(mock=True, fixture="all")
        self.recorder = original_ui.MacroRecorder()
        self.desktop_style = DesktopStyle(dark=False)
        self.handbook = Handbook()
        self.engine = original_ui.QQmlApplicationEngine()
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
        for name, obj in [
            ("macroRecorder", self.recorder),
            ("backend", self.backend),
            ("diagrams", self.catalog),
            ("desktopStyle", self.desktop_style),
            ("handbook", self.handbook),
        ]:
            self.engine.rootContext().setContextProperty(name, obj)
        self.engine.addImageProvider(
            "piper-diagrams", original_ui.DiagramImageProvider(self.catalog)
        )
        self.engine.load(
            original_ui.QUrl.fromLocalFile(str(ROOT / "qt_piper/qml/Main.qml"))
        )
        assert self.engine.rootObjects(), "Main.qml failed to load: " + "\n".join(
            self.qml_warnings
        )
        self.window = self.engine.rootObjects()[0]
        self.window.requestActivate()
        self.settle(500)
        assert self.window.isVisible()
        self.idle()
        assert self.backend.connected, self.backend.error

    def clean_qml(self):
        super().clean_qml()
        assert not self.qml_warnings, "Native QML warnings: " + "\n".join(
            self.qml_warnings
        )

    def capture(self, name):
        self.settle(200)
        image = self.window.grabWindow()
        assert not image.isNull()
        assert image.width() == self.window.width()
        assert image.height() == self.window.height()
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

    def find(self, name):
        try:
            obj = super().find(name)
        except AssertionError:
            # Reparented native dialogs own virtual ListView delegates outside
            # the main contentItem tree. Inspect their real visual content too.
            obj = None
            for popup in self.window.findChildren(original_ui.QObject):
                if not popup.inherits("QQuickPopup"):
                    continue
                expression = original_ui.QQmlExpression(
                    self.engine.rootContext(),
                    popup,
                    "(function walk(item) { if (!item) return null; if (item.objectName === "
                    + json.dumps(name)
                    + ") return item; for (let child of (item.children || [])) { let found=walk(child); if(found) return found; } return null; })(contentItem)",
                )
                result = expression.evaluate()
                candidate = result[0] if isinstance(result, tuple) else result
                if hasattr(candidate, "toQObject"):
                    candidate = candidate.toQObject()
                if candidate is not None:
                    obj = candidate
                    break
            assert obj is not None, f"Missing QML objectName={name}"
        if isinstance(obj, original_ui.QQuickItem) or not (
            name.endswith("Tab") or obj.inherits("QQuickAction")
        ):
            return obj
        # InlineMessage and navigation actions own actual visual buttons. Drive
        # that button with QTest rather than invoking the Action programmatically.
        expression = original_ui.QQmlExpression(
            self.engine.rootContext(),
            self.window,
            "(function walk(item) { if (item.objectName === "
            + json.dumps(name)
            + " || (item.action && item.action.objectName === "
            + json.dumps(name)
            + ")) return item; let children = item.children || []; for (let child of children) { let found = walk(child); if (found) return found; } return null; })(contentItem)",
        )
        result = expression.evaluate()
        obj = result[0] if isinstance(result, tuple) else result
        if hasattr(obj, "toQObject"):
            obj = obj.toQObject()
        assert isinstance(
            obj, original_ui.QQuickItem
        ), f"Missing visual control for {name}"
        return obj

    def click(self, name, x=None, y=None):
        item = super().click(name, x, y)
        # Native desktop controls animate popup entry/exit. Wait for the real
        # control to settle before the next input, rather than disabling it.
        self.settle(300)
        return item

    def key(self, key, modifiers=Qt.KeyboardModifier.NoModifier, window=None):
        QTest.keyClick(window or self.window, key, modifiers)
        self.interactions.append(
            {"action": "key_click", "key": key.name, "modifiers": modifiers.value}
        )
        self.settle(
            350
            if key
            in [
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
                Qt.Key.Key_Space,
                Qt.Key.Key_Escape,
            ]
            else 30
        )

    def combo(self, name, index, verify=True):
        item = self.click(name)

        def evaluate(code):
            prop = QQmlProperty(item, code, self.engine.rootContext())
            assert prop.isValid(), f"Missing native ComboBox property: {code}"
            return prop.read()

        def popup_window():
            content = evaluate("popup.contentItem")
            # Keep the PySide wrapper alive while the native popup is in use;
            # otherwise its temporary wrapper can invalidate the owning window.
            if not hasattr(self, "_combo_popup_contents"):
                self._combo_popup_contents = {}
            self._combo_popup_contents[name] = content
            window = content.window() if content is not None else None
            if window is not None and window.isVisible():
                return window
            focus = self.app.focusWindow()
            return focus if focus is not None and focus.isVisible() else self.window

        # Qt 6.11 can use a separate native popup window. Send the real keys
        # to the window containing the popup, rather than always to Main.qml.
        popup_open = bool(evaluate("popup.visible"))
        if popup_open:
            target = popup_window()
            route = "popup-item" if target == self.window else "popup-window"
            QTest.mouseMove(self.window, QPointF(2, 2).toPoint())
            self.settle(60)

            def highlighted_index():
                # Native KDE Menu popups and list-backed Qt ComboBoxes expose
                # different selection properties. Observe them; Home is not a
                # supported menu-selection shortcut on all KDE/Qt versions.
                for path in [
                    "popup.currentIndex",
                    "highlightedIndex",
                    "popup.contentItem.currentIndex",
                ]:
                    prop = QQmlProperty(item, path, self.engine.rootContext())
                    if prop.isValid():
                        value = prop.read()
                        if isinstance(value, int):
                            return value
                return -1

            for _ in range(item.property("count") + 2):
                current = highlighted_index()
                if current == index:
                    break
                self.key(
                    Qt.Key.Key_Up if current > index else Qt.Key.Key_Down,
                    window=popup_window(),
                )
                observed = highlighted_index()
                assert observed != current, (
                    f"{name}: native popup arrows did not advance from {current} "
                    f"toward {index}; route={route}, platform={self.app.platformName()}, "
                    f"focusWindow={self.app.focusWindow()}. This is a popup input-routing "
                    "failure, not a successful selection."
                )
            assert (
                highlighted_index() == index
            ), f"{name}: popup did not highlight {index}"
            self.key(Qt.Key.Key_Return, window=popup_window())
        else:
            # The offscreen platform cannot grab a Popup.Window keyboard and
            # may dismiss it immediately. Exercise the control's native closed
            # keyboard path instead; never assign currentIndex or fake signals.
            assert self.app.platformName() in ["offscreen", "minimal"], (
                f"{name}: native popup did not stay open on " + self.app.platformName()
            )
            route = "closed-keyboard-offscreen"
            self.window.requestActivate()
            self.settle(100)
            self.focus_with_tab(name)
            for _ in range(item.property("count") + 1):
                current = item.property("currentIndex")
                if current == index:
                    break
                self.key(Qt.Key.Key_Down if current < index else Qt.Key.Key_Up)
                item = self.find(name)
                if not verify and item.property("currentIndex") == current:
                    break
                assert item.property("currentIndex") != current, (
                    f"{name}: focused native keyboard selection did not advance "
                    f"from {current} toward {index}"
                )
        self.settle(100)
        active = self.window.activeFocusItem()
        # A native activation can rebuild a model-backed delegate (e.g. DPI).
        item = self.find(name)
        actual = item.property("currentIndex")
        assert not verify or actual == index, (
            f"{name} did not select item {index}: actual={actual}, route={route}, "
            f"popupVisible={evaluate('popup.visible')}, "
            f"focus={active.objectName() if active else None}, "
            f"focusWindow={self.app.focusWindow()}"
        )
        self.interactions.append(
            {
                "action": "keyboard_combo_select",
                "object": name,
                "index": index,
                "route": route,
            }
        )

    def toggle_theme(self):
        self.click("appMenuButton")
        self.click("themeToggle")

    def focus_with_tab(self, name):
        try:
            target = self.find(name)
        except AssertionError:
            # Virtual ListView rows are instantiated as native Tab focus scrolls
            # toward them. Do not create delegates or move focus programmatically.
            target = None
        for count in range(300):
            active = self.window.activeFocusItem()
            if (target is not None and target.hasActiveFocus()) or (
                active is not None and active.objectName() == name
            ):
                self.interactions.append(
                    {"action": "keyboard_tab_focus", "object": name, "tabs": count}
                )
                return
            active = self.window.activeFocusItem()
            # Native multiline editors reserve Tab for text indentation;
            # Ctrl+Tab is the standard keyboard path back to dialog controls.
            modifiers = (
                Qt.KeyboardModifier.ControlModifier
                if active and active.objectName() == "macroJson"
                else Qt.KeyboardModifier.NoModifier
            )
            self.key(Qt.Key.Key_Tab, modifiers)
        active = self.window.activeFocusItem()
        raise AssertionError(
            f"{name} not reachable by Tab; last focus={active.objectName() if active else None}"
        )

    def fully_visible(self, item):
        """Check the whole row, including clipping ancestors, in window pixels."""
        if not item.isVisible() or item.width() <= 0 or item.height() <= 0:
            return False
        top_left = item.mapToScene(QPointF(0, 0))
        bottom_right = item.mapToScene(QPointF(item.width(), item.height()))
        if not (
            top_left.x() >= -0.5
            and top_left.y() >= -0.5
            and bottom_right.x() <= self.window.width() + 0.5
            and bottom_right.y() <= self.window.height() + 0.5
        ):
            return False
        ancestor = item.parentItem()
        while ancestor is not None:
            if ancestor.clip():
                start = ancestor.mapFromScene(top_left)
                end = ancestor.mapFromScene(bottom_right)
                if not (
                    start.x() >= -0.5
                    and start.y() >= -0.5
                    and end.x() <= ancestor.width() + 0.5
                    and end.y() <= ancestor.height() + 0.5
                ):
                    return False
            ancestor = ancestor.parentItem()
        return True

    def layer_state(self, shifted):
        bar = self.find("contentLayerTabs")
        header = self.find("contentLayerHeader")
        separator = self.find("contentLayerSeparator")
        assert "TabBar" in bar.metaObject().className()
        assert self.window.property("shifted") == shifted
        assert bar.property("currentIndex") == int(shifted)
        expected_visible = (
            self.window.property("page") == 1
            and bool(self.backend.selectedDevice.get("hasGShift"))
            and self.backend.connected
            and not self.window.property("assignmentEditing")
        )
        for name, text, checked in [
            ("normalLayer", "Normal", not shifted),
            ("gshiftLayer", "G-Shift", shifted),
        ]:
            tab = self.find(name)
            assert "TabButton" in tab.metaObject().className()
            assert tab.property("text") == text
            assert tab.property("checked") == checked
            assert tab.isVisible() == expected_visible
            interface = QAccessible.queryAccessibleInterface(tab)
            assert (
                interface is not None and interface.role() == QAccessible.Role.PageTab
            )
            if expected_visible:
                assert self.fully_visible(tab), f"Layer tab {name} is clipped"
        assert header.isVisible() == expected_visible
        if expected_visible:
            pane = self.find("contentPane")
            for item in [header, bar, separator]:
                assert self.fully_visible(
                    item
                ), f"Layer header {item.objectName()} is clipped"
                ancestor = item.parentItem()
                while ancestor is not None and ancestor != pane:
                    ancestor = ancestor.parentItem()
                assert ancestor == pane, "Tabs must belong to the right content pane"
                origin = item.mapToItem(pane, QPointF(0, 0))
                assert abs(origin.x()) <= 0.5
                assert (
                    abs(item.width() - pane.width()) <= 0.5
                ), "Layer tabs and separator must span both the diagram and assignment panes"
            tab_bottom = bar.mapToScene(QPointF(0, bar.height())).y()
            separator_top = separator.mapToScene(QPointF(0, 0)).y()
            separator_bottom = separator_top + separator.height()
            assert abs(tab_bottom - separator_top) <= 1
            for name in ["diagramPane", "assignmentsScroll"]:
                assert (
                    self.find(name).mapToScene(QPointF(0, 0)).y()
                    >= separator_bottom - 0.5
                )

    def view_snapshot(self):
        return (
            deepcopy(self.backend._draft),
            self.backend.dirty,
            deepcopy(self.backend._transport.calls),
        )

    def assert_view_unchanged(self, before):
        assert (
            self.view_snapshot() == before
        ), "View-only navigation changed drafts, dirty state, or transport writes"

    def set_layer(self, shifted):
        before = self.view_snapshot()
        target = "gshiftLayer" if shifted else "normalLayer"
        control = self.find(target)
        assert (
            control.isVisible()
        ), "Cannot change the layer without visible native tabs"
        if not control.property("checked"):
            self.click(target)
            assert self.window.property("selectedButton") == -1
        self.layer_state(shifted)
        self.assert_view_unchanged(before)

    def visible_assignments(self, shifted, require_all_in_view=False):
        self.layer_state(shifted)
        expected = list(range(21, 41) if shifted else range(20))
        other = list(range(20) if shifted else range(21, 41))
        rows = [self.find("buttonAssignment" + str(index)) for index in expected]
        assert len(rows) == 20
        for index, row in zip(expected, rows):
            assert row.isVisible(), f"Assignment {index} is hidden"
            assert row.isEnabled(), f"Assignment {index} is disabled"
            if require_all_in_view:
                assert self.fully_visible(row), f"Assignment {index} is clipped"
        # The other layer may be filtered out completely or exist as hidden rows.
        for index in other:
            try:
                row = self.find("buttonAssignment" + str(index))
            except AssertionError:
                continue
            assert (
                not row.isVisible()
            ), f"Other-layer assignment {index} leaked into overview"
        return expected

    def pane_geometry(self):
        panes = {
            name: self.find(name)
            for name in [
                "navigationSidebar",
                "navigationHeader",
                "modulePane",
                "sectionHeader",
                "contentPane",
                "paneDivider",
            ]
        }

        def rectangle(item):
            origin = item.mapToScene(QPointF(0, 0))
            return (
                origin.x(),
                origin.y(),
                origin.x() + item.width(),
                origin.y() + item.height(),
            )

        def contained(item, container):
            ancestor = item
            while ancestor is not None and ancestor != container:
                ancestor = ancestor.parentItem()
            assert (
                ancestor == container
            ), f"{item.objectName()} must structurally belong to {container.objectName()}"
            x1, y1, x2, y2 = rectangle(item)
            cx1, cy1, cx2, cy2 = rectangle(container)
            assert cx1 - 0.5 <= x1 <= x2 <= cx2 + 0.5
            assert cy1 - 0.5 <= y1 <= y2 <= cy2 + 0.5

        for name, item in panes.items():
            assert self.fully_visible(item), f"Pane element {name} is clipped"
        left = rectangle(panes["navigationSidebar"])
        right = rectangle(panes["modulePane"])
        divider = rectangle(panes["paneDivider"])
        left_header = rectangle(panes["navigationHeader"])
        right_header = rectangle(panes["sectionHeader"])
        body = rectangle(panes["contentPane"])
        assert abs(left[2] - divider[0]) <= 1
        assert abs(divider[2] - right[0]) <= 1
        assert abs(left[1] - right[1]) <= 1
        assert abs(left[3] - right[3]) <= 1
        assert divider[1] <= min(left[1], right[1]) + 1
        assert divider[3] >= max(left[3], right[3]) - 1
        assert abs(left_header[2] - left[2]) <= 1
        assert abs(right_header[0] - right[0]) <= 1
        assert abs(right_header[2] - right[2]) <= 1
        assert abs(left_header[3] - right_header[3]) <= 1
        assert body[1] >= right_header[3] - 1
        assert abs(body[0] - right[0]) <= 1
        contained(panes["navigationHeader"], panes["navigationSidebar"])
        contained(panes["sectionHeader"], panes["modulePane"])
        contained(panes["contentPane"], panes["modulePane"])
        for name in ["appMenuButton", "settingsSearch"]:
            contained(self.find(name), panes["navigationHeader"])
        for name in ["sectionTitle", "deviceSelect", "profileSelect"]:
            contained(self.find(name), panes["sectionHeader"])
        previous_bottom = left_header[3]
        section_heights = {}
        for name in [
            "buttonsTab",
            "sensitivityTab",
            "lightingTab",
            "profileTab",
            "advancedTab",
        ]:
            item = self.find(name)
            contained(item, panes["navigationSidebar"])
            bounds = rectangle(item)
            assert bounds[1] >= previous_bottom - 0.5
            assert abs(item.height() - item.implicitHeight()) <= 0.5, (
                f"Section {name} must use its native implicit height: "
                f"{item.height()} != {item.implicitHeight()}"
            )
            section_heights[name] = item.height()
            previous_bottom = bounds[3]
        return {
            "left_pane_width": left[2] - left[0],
            "divider_x": divider[0],
            "native_section_row_heights": section_heights,
        }

    def single_column_assignments(self, shifted):
        assert self.find("assignmentGrid").property("columns") == 1
        indices = self.visible_assignments(shifted, require_all_in_view=False)
        previous_bottom = None
        column_x = None
        column_width = None
        maximum_height = self.find("profileSelect").height() + 2
        heights = []
        for index in indices:
            row = self.find("buttonAssignment" + str(index))
            origin = row.mapToScene(QPointF(0, 0))
            if column_x is None:
                column_x, column_width = origin.x(), row.width()
            assert (
                abs(origin.x() - column_x) <= 0.5
            ), "Assignments must use exactly one column"
            assert (
                abs(row.width() - column_width) <= 0.5
            ), "Assignment rows must have a consistent width"
            if previous_bottom is not None:
                assert (
                    origin.y() >= previous_bottom - 0.5
                ), "Assignment rows overlap or form multiple columns"
            assert (
                0 < row.height() <= maximum_height
            ), f"Assignment {index} is not compact: {row.height()} > {maximum_height}"
            for label in ["assignmentLabel", "assignmentValue"]:
                assert self.find(label + str(index)).property("lineCount") == 1
            previous_bottom = origin.y() + row.height()
            heights.append(row.height())
        return {"column_count": 1, "row_count": len(indices), "row_heights": heights}

    def assert_selected(self, index):
        self.layer_state(self.button(index).get("layer") == "gshift")
        assert (
            self.window.property("selectedButton") == index
        ), f"Expected selected button {index}, got {self.window.property('selectedButton')}"
        assert not self.find("assignmentPage").property(
            "visible"
        ), "Selecting a button must reveal its assignment without opening an editor"
        row = self.find("buttonAssignment" + str(index))
        assert row.property("highlighted"), f"Assignment {index} is not highlighted"
        assert self.fully_visible(row), f"Selected assignment {index} is clipped"
        assert self.fully_visible(
            self.find("buttonEdit" + str(index))
        ), f"Selected assignment {index} edit control is clipped"

    def select_target(self, index):
        """Click an exact SVG pixel, checking selection and natural auto-scroll."""
        before = deepcopy(self.backend.selectedProfile)
        was_dirty = self.backend.dirty
        point = self.target_point("buttons", index)
        QTest.mouseMove(self.window, point)
        self.settle(50)
        assert (
            self.window.cursor().shape() == Qt.CursorShape.ArrowCursor
        ), "Device controls must keep the native arrow cursor"
        QTest.mouseClick(
            self.window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            point,
        )
        self.settle(350)
        self.assert_selected(index)
        assert (
            self.backend.selectedProfile == before and self.backend.dirty == was_dirty
        )
        self.interactions.append(
            {
                "action": "svg_select_and_reveal",
                "index": index,
                "x": point.x(),
                "y": point.y(),
            }
        )

    def edit_row(self, index):
        self.click("buttonEdit" + str(index))
        dialog = self.find("assignmentPage")
        assert dialog.property(
            "visible"
        ), "The explicit edit button must open its editor"
        assert dialog.property("buttonIndex") == index

    def payload(self):
        value = self.find("assignmentPage").property("payload")
        return deepcopy(value.toVariant() if hasattr(value, "toVariant") else value)

    def choose_value(self, name, value):
        previous = self.payload()
        self.click(name)
        assert self.find("valuePicker").property("visible")
        self.text("valuePickerSearch", str(value))
        option = self.find("valuePickerOption" + str(value))
        assert self.fully_visible(option)
        self.click("valuePickerOption" + str(value))
        assert self.find("valuePicker").property("visible")
        assert self.find("valuePicker").property("pendingValue") == value
        assert self.payload() == previous
        self.click("valuePickerOk")
        assert not self.find("valuePicker").property("visible")
        assert self.find(name).property("currentValue") == value
        assert self.find(name).hasActiveFocus()

    def add_event(self, kind, value):
        before = deepcopy(self.payload()["value"])
        self.click("macroAddEvent")
        assert self.find("valuePicker").property("eventMode")
        assert not self.find("valuePickerOk").isEnabled()
        self.combo("valuePickerEventType", kind - 1)
        assert self.payload()["value"] == before
        if kind == 3:
            self.spin("valuePickerDelay", value)
        else:
            self.text("valuePickerSearch", str(value))
            self.click("valuePickerOption" + str(value))
        assert self.find("valuePicker").property("visible")
        assert self.payload()["value"] == before
        self.click("valuePickerOk")
        assert not self.find("valuePicker").property("visible")
        assert self.payload()["value"] == before + [[kind, value]]
        assert self.find("macroAddEvent").hasActiveFocus()

    def spin(self, name, value):
        # These values are now chosen in a real searchable native list. The
        # hidden numeric properties are read-only serialization oracles here.
        picker = {"mouseButtonNumber": "mouseButtonPicker", "keyCode": "keyPicker"}.get(
            name
        )
        if picker and not self.find(name).isVisible():
            self.choose_value(picker, value)
            assert self.find(name).property("value") == value
        else:
            super().spin(name, value)

    def click_text_button(self, text, scope=None):
        parent = self.find(scope) if scope else self.window
        matches = [
            item
            for item in parent.findChildren(original_ui.QObject)
            if isinstance(item, original_ui.QQuickItem)
            and item.inherits("QQuickAbstractButton")
            and item.isVisible()
            and item.isEnabled()
            and item.property("text") == text
        ]
        assert (
            len(matches) == 1
        ), f"Expected one visible {text!r} button in {scope}: {len(matches)}"
        item = matches[0]
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        QTest.mouseClick(
            self.window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            point,
        )
        self.interactions.append(
            {
                "action": "mouse_click",
                "object": item.objectName(),
                "text": text,
                "scope": scope,
            }
        )
        self.settle(350)

    def mapping_type(self, action_type):
        types = self.find("assignmentPage").property("types")
        if hasattr(types, "toVariant"):
            types = types.toVariant()
        self.combo("mappingType", types.index(action_type))

    def back(self, discard=False):
        assert self.window.property("assignmentEditing")
        self.click("assignmentBack")
        prompt = self.find("assignmentNavigationDialog")
        if prompt.property("visible"):
            assert discard, "Clean Back unexpectedly prompted for unsaved changes"
            self.click("assignmentDiscardChanges")
        assert not self.window.property("assignmentEditing")
        assert not self.find("assignmentPage").isVisible()

    def apply_assignment(self):
        assert self.window.property("assignmentEditing")
        assert self.find("applyButton").isEnabled()
        self.click("applyButton")
        self.idle()
        assert not self.backend.error, self.backend.error
        assert self.find("assignmentPage").isVisible()
        assert not self.find("assignmentPage").property("edited")

    def quick_record(self, index, keys=(Qt.Key.Key_F6,)):
        before = deepcopy(self.backend._transport.calls)
        self.select_target(index)
        self.click("buttonQuickMacro" + str(index))
        assert not self.window.property("assignmentEditing")
        assert self.window.property("quickMacroIndex") == index and self.recorder.active
        assert self.fully_visible(self.find("quickMacroPanel" + str(index)))
        for key in keys:
            self.key(key)
        self.click("quickMacroStop" + str(index))
        assert not self.recorder.active
        assert self.window.property("quickMacroIndex") == -1
        assert self.button(index)["actionType"] == "macro"
        assert self.backend.profileMappingsDirty
        assert (
            self.backend._transport.calls == before
        ), "Recording must only stage a draft"

    def edit_target(self, index):
        self.select_target(index)
        self.edit_row(index)

    def assignment_geometry(self, index):
        row = self.find("buttonAssignment" + str(index))
        name = self.find("assignmentLabel" + str(index))
        value = self.find("assignmentValue" + str(index))
        edit = self.find("buttonEdit" + str(index))
        quick = self.find("buttonQuickMacro" + str(index))
        for item in [row, name, value, quick, edit]:
            assert self.fully_visible(item), f"{item.objectName()} is clipped"
        name_start = name.mapToScene(QPointF(0, 0)).x()
        name_end = name.mapToScene(QPointF(name.width(), 0)).x()
        value_start = value.mapToScene(QPointF(0, 0)).x()
        value_end = value.mapToScene(QPointF(value.width(), 0)).x()
        quick_start = quick.mapToScene(QPointF(0, 0)).x()
        quick_end = quick.mapToScene(QPointF(quick.width(), 0)).x()
        edit_start = edit.mapToScene(QPointF(0, 0)).x()
        assert (
            name_start
            < name_end
            <= value_start
            <= value_end
            <= quick_start
            < quick_end
            <= edit_start
        ), f"Assignment {index} must place its name left, assignment right, edit at far right"
        alignment = original_ui.QQmlExpression(
            self.engine.rootContext(), value, "horizontalAlignment === 2"
        ).evaluate()
        assert alignment[0] if isinstance(alignment, tuple) else alignment
        assert name.property("text") and value.property("text")


def scenario_overview(h):
    assert h.window.property("page") == 1, "Buttons must be the default page"
    assert not h.window.property("shifted")
    assert not h.find("assignmentPage").property("visible")
    assert h.find("deviceSelect").isVisible()
    assert h.find("profileSelect").isVisible()
    h.window.resize(1200, 820)
    h.settle(150)
    assert h.window.width() == 1200 and h.window.height() == 820
    assert "leaders=0" in h.find("mouseDiagram").property("source").toString()
    h.select_device("G600")
    sidebar = h.find("navigationSidebar")
    assert h.fully_visible(sidebar)
    panes = h.pane_geometry()
    previous_y = -1
    for name in [
        "buttonsTab",
        "sensitivityTab",
        "lightingTab",
        "profileTab",
        "advancedTab",
    ]:
        item = h.find(name)
        point = item.mapToScene(QPointF(0, 0))
        assert h.fully_visible(item) and point.x() < sidebar.width()
        assert point.y() > previous_y, "Navigation must be a vertical left sidebar"
        previous_y = point.y()
    for width, height in [(1400, 820), (1200, 820), (960, 700)]:
        h.window.resize(width, height)
        h.settle(150)
        h.layer_state(False)
        h.set_layer(True)
        h.visible_assignments(True)
        h.set_layer(False)
        h.visible_assignments(False)
    h.window.resize(1200, 820)
    h.settle(150)
    normal = h.visible_assignments(False)
    normal_layout = h.single_column_assignments(False)
    for index in normal:
        if h.fully_visible(h.find("buttonAssignment" + str(index))):
            h.assignment_geometry(index)
    assert not h.window.property("darkMode")
    h.capture("kde-sidebar-light-overview")
    h.set_layer(True)
    shifted = h.visible_assignments(True)
    shifted_layout = h.single_column_assignments(True)
    h.set_layer(False)
    h.visible_assignments(False)
    return {
        "native_controls_style": QQuickStyle.name(),
        "native_widget_style": h.app.style().objectName(),
        "application_type": type(h.app).__name__,
        "pane_layout": panes,
        "layer_control": "TabBar: Normal / G-Shift",
        "layer_control_sizes_checked": [[1400, 820], [1200, 820], [960, 700]],
        "normal_assignment_indices": normal,
        "gshift_assignment_indices": shifted,
        "normal_layout": normal_layout,
        "gshift_layout": shifted_layout,
    }


def scenario_mapping(h):
    h.select_device("Capability")
    original = deepcopy(h.button(0))
    h.edit_target(0)
    before = h.view_snapshot()
    h.mapping_type("key")
    h.spin("keyCode", 46)
    assert h.find("assignmentPage").property("localDirty")
    h.assert_view_unchanged(before)
    h.back(discard=True)
    assert h.button(0) == original and not h.backend.dirty
    h.edit_row(0)
    h.mapping_type("key")
    h.spin("keyCode", 46)
    h.click("resetButton")
    assert not h.find("assignmentPage").property("edited")
    assert h.button(0) == original and not h.backend.dirty
    h.mapping_type("key")
    h.spin("keyCode", 46)
    h.apply_assignment()
    assert h.button(0)["actionType"] == "key" and h.button(0)["actionValue"] == 46
    assert len(h.backend._transport.calls) == 1
    h.back()
    h.edit_target(0)
    assert h.find("keyCode").property("value") == 46
    assert h.find("keyPicker").property("currentValue") == 46
    h.spin("keyCode", 30)
    assert h.find("keyPicker").property("currentValue") == 30
    h.choose_value("keyPicker", 48)
    assert h.find("keyCode").property("value") == 48
    h.spin("keyCode", 700)
    assert h.find("keyPicker").property("currentValue") == 700
    assert "700" in h.find("keyPicker").property("text")
    h.back(discard=True)
    # Apply every supported assignment kind through the visible child page.
    applied = ["key"]
    for action in ["button", "special", "macro", "none"]:
        h.edit_target(0)
        h.mapping_type(action)
        if action == "button":
            h.spin("mouseButtonNumber", 5)
        elif action == "special":
            h.combo("specialAction", 1)
        elif action == "macro":
            h.add_event(1, 30)
            h.add_event(2, 30)
        h.apply_assignment()
        assert h.button(0)["actionType"] == action
        h.back()
        applied.append(action)
    return {"assignment_types_applied": applied, "local_edits_no_writes": True}


def scenario_gshift(h):
    h.select_device("G600")
    normal = deepcopy(h.button(0))
    h.set_layer(True)
    h.visible_assignments(True)
    for profile in [1, 0]:
        h.combo("profileSelect", profile)
        h.layer_state(True)
        assert h.window.property("selectedButton") == -1
    h.edit_target(21)
    h.mapping_type("button")
    h.spin("mouseButtonNumber", 5)
    h.apply_assignment()
    assert h.button(21)["actionType"] == "button" and h.button(21)["actionValue"] == 5
    assert h.button(0) == normal, "G-Shift edit contaminated the normal layer"
    h.back()
    h.visible_assignments(True)
    h.edit_row(21)
    assert h.find("mouseButtonNumber").property("value") == 5
    h.back()
    h.set_layer(False)
    h.edit_target(0)
    h.back()
    assert h.button(0) == normal
    h.set_layer(True)
    h.edit_target(29)
    h.capture("kde-assignment-child-gshift")
    assert h.find("macroEventPanel").isVisible()
    assert (
        json.loads(h.find("macroJson").property("text")) == h.button(29)["actionValue"]
    )
    h.back()
    h.toggle_theme()
    assert h.window.property("darkMode")
    h.visible_assignments(True)
    h.capture("kde-sidebar-dark-gshift-overview")
    h.edit_target(29)
    assert h.find("macroEventPanel").isVisible()
    h.back()
    h.toggle_theme()
    assert not h.window.property("darkMode")


def scenario_led(h):
    h.select_device("G600")
    h.click("lightingTab")
    assert h.window.property("page") == 2
    original = deepcopy(h.backend.selectedProfile["leds"][0])
    h.click_target("leds", 0)
    h.text("ledColor", "badcolor")
    assert not h.find("ledSave").isEnabled()
    assert h.find("ledValidation").property("visible")
    assert h.find("ledDialog").property("inputValidation")
    assert h.find("ledDialog").property("visible") and not h.backend.dirty
    h.click("ledCancel")
    assert h.backend.selectedProfile["leds"][0] == original
    h.click_target("leds", 0)
    h.combo("ledMode", 3)
    h.text("ledColor", "#33aaff")
    assert not h.find("ledBrightness").isEnabled()
    h.click("ledSave")
    led = h.backend.selectedProfile["leds"][0]
    assert led["mode"] == 3 and led["color"].lower() == "#33aaff"
    h.click("applyButton")
    h.idle()
    assert not h.backend.dirty and not h.backend.error
    h.click("buttonsTab")
    h.visible_assignments(False)


def scenario_profiles_and_sensitivity(h):
    h.select_device("Capability")
    h.click("sensitivityTab")
    assert h.window.property("page") == 0
    original = h.backend.selectedProfile["resolutions"][0]["x"]
    values = h.backend.selectedProfile["resolutions"][0]["values"]
    target = values[values.index(original) + 1]
    h.combo("dpiX0", values.index(target))
    assert h.backend.selectedProfile["resolutions"][0]["x"] == target
    h.combo("profileSelect", 1)
    assert h.backend.selectedProfileIndex == 1
    h.combo("profileSelect", 0)
    assert h.backend.selectedProfile["resolutions"][0]["x"] == target
    h.click("resetButton")
    assert h.backend.selectedProfile["resolutions"][0]["x"] == original
    assert not h.backend.dirty
    h.click("profileTab")
    assert h.window.property("page") == 4
    h.click("advancedTab")
    assert h.window.property("page") == 3


def scenario_all_assignments(h):
    h.select_device("G600")
    checked = []
    for shifted in [False, True]:
        h.set_layer(shifted)
        for index in h.visible_assignments(shifted):
            h.select_target(index)
            h.assignment_geometry(index)
            h.edit_row(index)
            h.back(discard=True)
            checked.append(index)
    assert len(checked) == 40 and not h.backend.dirty
    return {"assignment_rows_edited": checked}


def scenario_keyboard(h):
    h.select_device("G600")
    h.focus_with_tab("buttonsTab")
    for key, expected_page in [
        (Qt.Key.Key_Down, 0),
        (Qt.Key.Key_Down, 2),
        (Qt.Key.Key_End, 3),
        (Qt.Key.Key_Home, 1),
    ]:
        h.key(key)
        assert h.window.property("page") == expected_page
    h.focus_with_tab("diagramArea")
    h.key(Qt.Key.Key_Right)
    selected = h.window.property("selectedButton")
    assert selected >= 0
    h.assert_selected(selected)
    # Keyboard Enter on the diagram remains an intentional editing shortcut.
    h.key(Qt.Key.Key_Return)
    assert h.find("assignmentPage").property("visible")
    assert h.find("assignmentPage").property("buttonIndex") == selected
    h.focus_with_tab("assignmentBack")
    h.key(Qt.Key.Key_Space)
    assert not h.find("assignmentPage").property("visible")
    h.focus_with_tab("diagramArea")
    h.key(Qt.Key.Key_Enter)
    assert h.find("assignmentPage").property("visible")
    assert h.find("assignmentPage").property("buttonIndex") == selected
    h.key(Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
    assert not h.window.property(
        "assignmentEditing"
    ), "Alt+Left did not return from the child page"
    for index, activation_key in [
        (8, Qt.Key.Key_Space),
        (9, Qt.Key.Key_Return),
        (10, Qt.Key.Key_Enter),
    ]:
        h.focus_with_tab("buttonEdit" + str(index))
        h.key(activation_key)
        assert h.find("assignmentPage").property("visible")
        assert h.find("assignmentPage").property("buttonIndex") == index
        h.key(Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
        assert not h.find("assignmentPage").property("visible")
    h.focus_with_tab("normalLayer")
    for key, shifted in [
        (Qt.Key.Key_Right, True),
        (Qt.Key.Key_Left, False),
        (Qt.Key.Key_Right, True),
    ]:
        before = h.view_snapshot()
        h.key(key)
        h.layer_state(shifted)
        h.assert_view_unchanged(before)
        assert h.window.property("selectedButton") == -1
    before = h.view_snapshot()
    h.key(Qt.Key.Key_Space)
    h.layer_state(True)
    h.assert_view_unchanged(before)
    h.focus_with_tab("diagramArea")
    h.key(Qt.Key.Key_Right)
    selected = h.window.property("selectedButton")
    assert selected >= 21
    h.assert_selected(selected)
    h.focus_with_tab("buttonEdit" + str(selected))
    h.key(Qt.Key.Key_Return)
    assert h.find("assignmentPage").property("visible")
    assert h.find("assignmentPage").property("buttonIndex") == selected
    h.key(Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
    assert not h.find("assignmentPage").property("visible")
    assert not h.backend.dirty


def scenario_all_targets(h):
    checked_buttons = []
    checked_leds = []
    for device_index in range(len(h.backend.devices)):
        h.combo("deviceSelect", device_index)
        device = h.backend.selectedDevice
        layers = [False, True] if device.get("hasGShift") else [False]
        h.click("buttonsTab")
        for shifted in layers:
            if len(layers) > 1:
                h.set_layer(shifted)
            hotspots = h.catalog.describe(
                device["svg"],
                "buttons",
                len(h.backend.selectedProfile["buttons"]),
                shifted,
            )["hotspots"]
            for hotspot in hotspots:
                index = hotspot["index"]
                h.edit_target(index)
                h.back(discard=True)
                checked_buttons.append(f"{device['name']}:button:{index}")
        h.click("lightingTab")
        hotspots = h.catalog.describe(
            device["svg"], "leds", len(h.backend.selectedProfile["leds"]), False
        )["hotspots"]
        for hotspot in hotspots:
            index = hotspot["index"]
            if any(led["index"] == index for led in h.backend.selectedProfile["leds"]):
                # The latest selection-only change applies to mouse buttons.
                # LED zones intentionally retain one-click direct editing.
                h.click_target("leds", index)
                h.click("ledCancel")
                checked_leds.append(f"{device['name']}:led:{index}")
    assert len(checked_buttons) == 48 and len(checked_leds) == 2
    assert not h.backend.dirty
    return {
        "button_targets_selected_then_edited": checked_buttons,
        "led_targets_directly_edited": checked_leds,
        "targets_clicked": len(checked_buttons) + len(checked_leds),
    }


def scenario_selection_reveal(h):
    h.select_device("G600")
    checked = []
    for width, height in [(1200, 820), (960, 700)]:
        h.window.resize(width, height)
        h.settle(200)
        for shifted in [False, True]:
            h.set_layer(shifted)
            expected = h.visible_assignments(shifted, require_all_in_view=False)
            first, last = expected[0], expected[-1]
            h.single_column_assignments(shifted)
            if width == 960:
                # Use the actual pending-changes footer to exercise a constrained
                # supported viewport while verifying that selection keeps edits.
                h.quick_record(expected[len(expected) // 2])
                assert h.backend.dirty
                assert not h.fully_visible(
                    h.find("buttonAssignment" + str(last))
                ), "Narrow pending-changes fixture must have a genuinely offscreen last row"
            for index in [last, first, last, first, last, first]:
                h.select_target(index)
                h.assignment_geometry(index)
                h.edit_row(index)
                h.back(discard=True)
                checked.append(
                    {"size": [width, height], "shifted": shifted, "index": index}
                )
            if width == 960:
                assert not h.fully_visible(h.find("buttonAssignment" + str(last)))
                h.click("resetButton")
                assert not h.backend.dirty
        if width == 960:
            h.capture("kde-narrow-selection-reveal")
    assert not h.backend.dirty
    return {"selection_reveal_cycles": checked}


def scenario_narrow_targets(h):
    h.select_device("G600")
    h.window.resize(960, 700)
    h.settle(200)
    checked = []
    before = h.view_snapshot()
    for shifted in [False, True]:
        h.set_layer(shifted)
        indices = list(range(21, 41) if shifted else range(20))
        assert not any(
            item.objectName().startswith("diagramTarget")
            for item in h.window.findChildren(original_ui.QObject)
        ), "Diagram artwork must not have numbered button overlays"
        for index in indices:
            h.select_target(index)
            checked.append(index)
        for index in [indices[0], indices[-1]]:
            h.edit_target(index)
            h.back(discard=True)
        h.focus_with_tab("diagramArea")
        for index in indices:
            h.key(Qt.Key.Key_Right)
            h.assert_selected(index)
            assert h.window.property("diagramHighlight") == "button" + str(
                h.button(index)["physicalIndex"]
            )
        h.key(Qt.Key.Key_Return)
        assert h.find("assignmentPage").property("buttonIndex") == indices[-1]
        h.back(discard=True)
    h.assert_view_unchanged(before)
    return {
        "narrow_svg_targets": checked,
        "keyboard_targets": checked,
        "numbered_overlays": False,
    }


def scenario_hover_feedback(h):
    from PySide6.QtCore import QPoint
    from PySide6.QtQuick import QQuickWindow

    h.select_device("G600")
    before = h.view_snapshot()
    checked = []
    for dark in [False, True]:
        h.desktop_style.setDark(dark)
        h.window.resize(1200, 820)
        h.settle(150)
        for shifted in [False, True]:
            h.set_layer(shifted)
            first, last = (21, 40) if shifted else (0, 19)
            for index in [first, last]:
                h.select_target(index)
                target_id = "button" + str(h.button(index)["physicalIndex"])
                assert h.window.property("hoverTarget") == target_id
                assert h.window.property("diagramHighlight") == target_id
                area = h.find("diagramArea")
                diagram = h.find("mouseDiagram")
                doc = h.catalog.document(h.backend.selectedDevice["svg"])
                scale = diagram.width() / doc.width
                # A blank point inside the SVG's bounding box exercises hit-test
                # misses, independently of MouseArea exit events.
                blank = None
                for y in range(10, int(area.height()) - 10, 10):
                    for x in range(10, int(area.width()) - 10, 10):
                        scene = area.mapToScene(QPointF(x, y)).toPoint()
                        local = diagram.mapFromScene(QPointF(scene))
                        if not (
                            0 < local.x() < diagram.width()
                            and 0 < local.y() < diagram.height()
                        ):
                            continue
                        if (
                            h.catalog.hitTest(
                                h.backend.selectedDevice["svg"],
                                "buttons",
                                local.x() / scale,
                                local.y() / scale,
                                len(h.backend.selectedProfile["buttons"]),
                                shifted,
                            )
                            == -1
                        ):
                            blank = scene
                            break
                    if blank is not None:
                        break
                assert blank is not None
                for point in [blank, QPoint(1100, 40)]:
                    QTest.mouseMove(h.window, h.target_point("buttons", index))
                    h.settle(40)
                    QTest.mouseMove(h.window, point)
                    h.settle(80)
                    assert h.window.property("hoverTarget") == ""
                    assert h.window.property("diagramHighlight") == ""
                    assert h.window.property("selectedButton") == index
                    assert h.find("buttonAssignment" + str(index)).property(
                        "highlighted"
                    )
                    QTest.mouseClick(
                        h.window,
                        Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier,
                        blank,
                    )
                    h.settle(80)
                    assert h.window.property("selectedButton") == index
                    assert h.window.property("diagramHighlight") == ""
                checked.append({"dark": dark, "shifted": shifted, "index": index})
            # Tab does not invent a target. Arrow keys deliberately select one.
            h.set_layer(not shifted)
            h.set_layer(shifted)
            h.focus_with_tab("diagramArea")
            assert h.window.property("selectedButton") == -1
            assert h.window.property("diagramHighlight") == ""
            h.key(Qt.Key.Key_Left)
            h.assert_selected(last)
            assert h.window.property("diagramHighlight") == "button19"
            interface = QAccessible.queryAccessibleInterface(h.find("diagramArea"))
            assert interface.text(QAccessible.Text.Description) == h.window.property(
                "selectedTargetDescription"
            )
            row = h.find("buttonAssignment" + str(first))
            row_point = row.mapToScene(
                QPointF(row.width() / 2, row.height() / 2)
            ).toPoint()
            QTest.mouseMove(h.window, row_point)
            h.settle(80)
            assert h.window.property("diagramHighlight") == "button0"
            QTest.mouseMove(h.window, QPoint(1100, 40))
            h.settle(80)
            assert h.window.property("diagramHighlight") == ""
            assert h.window.property("selectedButton") == last
            h.key(Qt.Key.Key_Left)
            assert h.window.property("diagramHighlight") == "button18"
            h.key(Qt.Key.Key_Tab)
            assert not h.find("diagramArea").hasActiveFocus()
            assert h.window.property("diagramHighlight") == ""
            h.capture(
                "hover-none-"
                + ("dark" if dark else "light")
                + ("-gshift" if shifted else "-normal")
            )
        h.window.requestActivate()
        h.settle(150)
        assert h.window.isActive()
        h.capture(("dark" if dark else "light") + "-active-clean-header")
        other = QQuickWindow()
        try:
            other.resize(100, 100)
            other.show()
            other.requestActivate()
            h.settle(200)
            assert not h.window.isActive()
            h.capture(("dark" if dark else "light") + "-inactive-clean-header")
        finally:
            other.close()
        h.window.requestActivate()
        h.settle(100)
    h.assert_view_unchanged(before)
    h.interactions.append(
        {"action": "verify_native_hover_and_window_activation", "cases": checked}
    )
    return {
        "hover_miss_and_exit_cases": checked,
        "keyboard_none_and_reverse_selection": True,
        "view_only": True,
    }


def scenario_minimum_size(h):
    h.select_device("G600")
    h.window.resize(h.window.minimumWidth(), h.window.minimumHeight())
    h.settle(150)
    h.pane_geometry()
    for name, page in [("lightingTab", 2), ("profileTab", 4), ("buttonsTab", 1)]:
        h.focus_with_tab(name)
        h.key(Qt.Key.Key_Return)
        assert h.window.property("page") == page
    for shifted in [False, True]:
        h.set_layer(shifted)
        expected = h.visible_assignments(shifted, require_all_in_view=False)
        # Real Tab navigation must reveal the explicit edit control and row.
        # No forced focus or programmatic contentY adjustment hides UI defects.
        for index in expected:
            name = "buttonEdit" + str(index)
            h.focus_with_tab(name)
            assert h.fully_visible(
                h.find(name)
            ), f"Focused edit control {index} is clipped"
            assert h.fully_visible(
                h.find("buttonAssignment" + str(index))
            ), f"Assignment {index} is clipped while its edit control is focused"
            activation_key = [Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter][
                index % 3
            ]
            h.key(activation_key)
            assert h.find("assignmentPage").property("visible")
            assert h.find("assignmentPage").property("buttonIndex") == index
            h.focus_with_tab("assignmentBack")
            h.key(Qt.Key.Key_Space)
            assert not h.window.property("assignmentEditing")
        h.edit_target(21 if shifted else 0)
        h.back(discard=True)
    h.click("lightingTab")
    h.click_target("leds", 0)
    h.click("ledCancel")
    h.click("profileTab")
    assert h.fully_visible(h.find("profileName"))
    return {
        "minimum_size": [h.window.width(), h.window.height()],
        "reachable_edit_controls": 40,
    }


def scenario_search(h):
    def results():
        value = h.window.property("searchResults")
        return value.toVariant() if hasattr(value, "toVariant") else value

    def inline_geometry():
        found = results()
        assignments = [
            (i, item) for i, item in enumerate(found) if item["kind"] == "assignment"
        ]
        pane = h.find("navigationSidebar")
        container = h.find("searchResults")
        assert container.isVisible() == bool(assignments)
        assert (
            h.window.findChild(original_ui.QObject, "searchPopup") is None
        ), "Search results must be persistent sidebar content, not a popup"
        buttons = h.find("buttonsTab")
        previous_bottom = buttons.mapToScene(QPointF(0, buttons.height())).y()
        left = pane.mapToScene(QPointF(0, 0)).x()
        right = left + pane.width()
        for position, result in assignments:
            row = h.find("searchResult" + str(position))
            label = h.find("searchResultLabel" + str(position))
            ancestor = row.parentItem()
            while ancestor is not None and ancestor != pane:
                ancestor = ancestor.parentItem()
            assert ancestor == pane, "Search result must belong to the left pane"
            top_left = row.mapToScene(QPointF(0, 0))
            assert left - 0.5 <= top_left.x()
            assert top_left.x() + row.width() <= right + 0.5
            assert top_left.y() >= previous_bottom - 0.5
            native_height = max(row.implicitHeight(), buttons.implicitHeight())
            assert abs(row.height() - native_height) <= 0.5, (
                f"Search result {position} must use native row sizing: "
                f"{row.height()} != {native_height}"
            )
            assert label.property("lineCount") == 1
            assert label.x() >= buttons.property("leftPadding") + 12
            expected = result["title"]
            if h.backend.selectedDevice.get("hasGShift"):
                expected += " · " + ("G-Shift" if result["shifted"] else "Normal")
            assert (
                label.property("text") == expected
            ), "Inline search must show only a button name and minimal layer context"
            interface = QAccessible.queryAccessibleInterface(row)
            assert interface is not None, "Search result lacks an accessible interface"
            accessible = interface.text(QAccessible.Text.Name)
            assert result["title"] in accessible and result["detail"] in accessible
            previous_bottom = top_left.y() + row.height()
        assert (
            h.find("sensitivityTab").mapToScene(QPointF(0, 0)).y()
            >= previous_bottom - 0.5
        )
        return assignments

    def retained(text, expected):
        assert h.find("settingsSearch").property("text") == text
        assert results() == expected, "Search results changed on simple activation"
        inline_geometry()

    def query(text):
        h.text("settingsSearch", text)
        QTest.mouseMove(
            h.window, QPointF(h.window.width() - 2, h.window.height() - 2).toPoint()
        )
        h.settle(200)
        assert h.find("settingsSearch").property("text") == text
        inline_geometry()
        return results()

    def clear():
        h.key(Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
        h.key(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        h.key(Qt.Key.Key_Backspace)
        h.settle(250)
        assert h.find("settingsSearch").property("text") == ""
        assert results() == [] and not h.find("searchResults").isVisible()
        assert not h.find("searchNoResults").isVisible()

    def activate_assignment(text, index, shifted):
        before = h.view_snapshot()
        found = query(text)
        assert len(found) == 1 and found[0]["kind"] == "assignment", found
        assert found[0]["index"] == index and found[0]["shifted"] == shifted
        h.key(Qt.Key.Key_Return)
        retained(text, found)
        assert h.window.property("page") == 1
        assert h.window.property("shifted") == shifted
        h.assert_selected(index)
        assert h.find("sectionTitle").property("text") == "Buttons"
        assert h.find("searchResult0").property("highlighted")
        h.assert_view_unchanged(before)
        return found[0]

    def header_geometry():
        h.pane_geometry()
        for ordered_names in [
            ["settingsSearch", "appMenuButton"],
            ["sectionTitle", "deviceSelect", "profileSelect"],
        ]:
            previous_right = -1
            for name in ordered_names:
                item = h.find(name)
                assert h.fully_visible(item), f"Header control {name} is clipped"
                start = item.mapToScene(QPointF(0, 0)).x()
                end = item.mapToScene(QPointF(item.width(), 0)).x()
                assert (
                    start >= previous_right - 0.5
                ), f"Header control {name} overlaps the preceding control"
                previous_right = end
        assert (
            h.find("settingsSearch").mapToScene(QPointF(0, 0)).x()
            < h.find("paneDivider").mapToScene(QPointF(0, 0)).x()
        )
        assert (
            h.find("profileSelect").mapToScene(QPointF(0, 0)).x() > h.window.width() / 2
        )
        assert h.window.title() == "Piper"
        visible_piper_labels = original_ui.QQmlExpression(
            h.engine.rootContext(),
            h.window,
            '(function walk(item) { let count=(item.visible && item.text==="Piper") ? 1 : 0; for(let child of (item.children || []))count+=walk(child); return count; })(contentItem)',
        ).evaluate()
        count = (
            visible_piper_labels[0]
            if isinstance(visible_piper_labels, tuple)
            else visible_piper_labels
        )
        assert count == 0, "Piper should appear only in the native window title"

    h.select_device("G600")
    assert results() == []
    h.key(Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert h.find("settingsSearch").hasActiveFocus(), "Native Ctrl+F must focus search"
    sections = []
    for text, page, title in [
        ("sensitivity", 0, "Sensitivity"),
        ("lighting", 2, "Lighting"),
        ("profiles", 4, "Profiles"),
        ("advanced", 3, "Advanced"),
    ]:
        found = query(text)
        assert found[0]["kind"] == "section" and found[0]["page"] == page, found
        h.key(Qt.Key.Key_Return)
        assert h.window.property("page") == page
        assert h.find("sectionTitle").property("text") == title
        retained(text, found)
        sections.append(title)
    # Assignment search switches the section and correct mapping layer while
    # preserving the selection-only contract, including offscreen targets.
    activate_assignment("normal g9", 8, False)
    h.edit_row(8)
    h.back(discard=True)
    activate_assignment("g-shift g9", 29, True)
    found = query("g9")
    assert [(x["index"], x["shifted"]) for x in found] == [
        (8, False),
        (29, True),
    ], found
    h.key(Qt.Key.Key_Down)
    assert h.window.property("searchResultIndex") == 1
    h.key(Qt.Key.Key_Up)
    assert h.window.property("searchResultIndex") == 0
    h.key(Qt.Key.Key_Down)
    h.key(Qt.Key.Key_Enter)
    assert h.window.property("shifted")
    h.assert_selected(29)
    retained("g9", found)
    # Both matches remain clickable after selection; no retyping/reopening is
    # allowed to hide a disappearing-result or stale-layer bug.
    for position, index, shifted in [
        (1, 29, True),
        (0, 8, False),
        (0, 8, False),
        (1, 29, True),
    ]:
        before = h.view_snapshot()
        h.click("searchResult" + str(position))
        h.assert_selected(index)
        h.assert_view_unchanged(before)
        assert h.window.property("shifted") == shifted
        retained("g9", found)
    for shifted in [False, True]:
        h.set_layer(shifted)
        retained("g9", found)
    h.focus_with_tab("searchResult0")
    h.key(Qt.Key.Key_Return)
    h.assert_selected(8)
    retained("g9", found)
    h.focus_with_tab("searchResult1")
    h.key(Qt.Key.Key_Enter)
    h.assert_selected(29)
    retained("g9", found)
    h.capture("kde-inline-search-g9")
    # Broad queries render all 40 assignments as one compact sidebar list.
    # Search Up/Down must scroll the actual result into view in both directions.
    long_results = query("button")
    assert len([x for x in long_results if x["kind"] == "assignment"]) == 40
    h.key(Qt.Key.Key_Up)
    last_position = len(long_results) - 1
    assert h.window.property("searchResultIndex") == last_position
    assert h.fully_visible(h.find("searchResult" + str(last_position)))
    h.key(Qt.Key.Key_Return)
    h.assert_selected(40)
    retained("button", long_results)
    h.key(Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    h.key(Qt.Key.Key_Down)
    assert h.window.property("searchResultIndex") == 0
    assert h.fully_visible(h.find("buttonsTab"))
    h.key(Qt.Key.Key_Down)
    assert h.fully_visible(h.find("searchResult1"))
    h.key(Qt.Key.Key_Return)
    h.assert_selected(0)
    retained("button", long_results)
    found = query("zzznomatchingassignment")
    assert found == [] and h.find("searchNoResults").isVisible()
    previous = (h.window.property("page"), h.window.property("selectedButton"))
    h.key(Qt.Key.Key_Return)
    assert (h.window.property("page"), h.window.property("selectedButton")) == previous
    search = h.find("settingsSearch")
    h.click("settingsSearch", search.width() - 16, search.height() / 2)
    assert h.find("settingsSearch").property("text") == ""
    assert results() == [] and not h.find("searchResults").isVisible()
    assert not h.find("searchNoResults").isVisible()
    found = query("normal g9")
    h.key(Qt.Key.Key_Escape)
    retained("normal g9", found)
    assert not h.find("settingsSearch").hasActiveFocus()
    h.click("buttonsTab")
    h.key(Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    h.settle(200)
    retained("normal g9", found)
    h.key(Qt.Key.Key_Return)
    h.assert_selected(8)
    # Stage a distinct mapping in profile 1, then ensure retained search text
    # recomputes against profile 2, profile 1, and Discard without stale data.
    h.quick_record(8)
    assert h.backend.dirty
    found = query("normal g9")
    assert len(found) == 1 and "F6" in found[0]["detail"]
    found = query("normal g9 f6")
    assert len(found) == 1 and found[0]["index"] == 8
    query("normal g9")
    h.key(Qt.Key.Key_Escape)
    h.combo("profileSelect", 1)
    assert h.find("settingsSearch").property("text") == "normal g9"
    assert "F6" not in results()[0]["detail"], results()
    activate_assignment("normal g9", 8, False)
    h.edit_row(8)
    assert h.find("assignmentPage").property("buttonIndex") == 8
    h.back(discard=True)
    h.combo("profileSelect", 0)
    assert "F6" in results()[0]["detail"]
    h.click("resetButton")
    assert not h.backend.dirty and "F6" not in results()[0]["detail"]
    query("g20")
    assert len(results()) == 2
    h.key(Qt.Key.Key_Escape)
    h.set_layer(True)
    h.select_device("Capability")
    h.layer_state(False)
    assert h.find("settingsSearch").property("text") == "g20"
    assert results() == [], "Search retained stale G600 assignments after device change"
    activate_assignment("button 1", 0, False)
    h.edit_row(0)
    h.back(discard=True)
    clear()
    h.select_device("G600")
    h.layer_state(False)
    for width, height in [(1400, 820), (1200, 820), (960, 700)]:
        h.window.resize(width, height)
        h.settle(200)
        for name, page in [
            ("buttonsTab", 1),
            ("sensitivityTab", 0),
            ("lightingTab", 2),
            ("profileTab", 4),
            ("advancedTab", 3),
        ]:
            h.click(name)
            assert h.window.property("page") == page
            header_geometry()
        activate_assignment("gshift g20", 40, True)
        assert h.fully_visible(h.find("buttonAssignment40"))
        assert h.fully_visible(h.find("buttonEdit40"))
        h.edit_row(40)
        h.back(discard=True)
        clear()
    assert not h.backend.dirty
    assert h.backend._transport.calls == [], "Search must never write to the device"
    return {
        "search_sections_activated": sections,
        "search_assignment_indices": [8, 29, 40],
        "search_profile_and_device_refresh": True,
        "persistent_inline_results": True,
        "inline_assignment_count": 40,
        "native_inline_row_sizing": True,
        "repeat_activation_and_layer_refresh": True,
        "tab_search_state_sync": True,
        "view_only_transport_writes": 0,
        "header_sizes_checked": [[1400, 820], [1200, 820], [960, 700]],
    }


def scenario_footer(h):
    h.select_device("G600")
    initial_draft = deepcopy(h.backend._draft)

    def state():
        bar = h.find("pendingChangesBar")
        assert bar.isVisible() and h.fully_visible(bar)
        assert "ToolBar" in bar.metaObject().className()
        pane = h.find("modulePane")
        origin = bar.mapToItem(pane, QPointF(0, 0))
        assert origin.x() >= -0.5 and origin.x() + bar.width() <= pane.width() + 0.5
        assert origin.y() + bar.height() <= pane.height() + 0.5
        last_right = -1
        for name, label in [
            ("helpButton", "Help"),
            ("resetButton", "Revert"),
            ("defaultsButton", "Defaults"),
            ("applyButton", "Apply"),
        ]:
            item = h.find(name)
            assert item.property("text") == label and h.fully_visible(item)
            start = item.mapToScene(QPointF(0, 0)).x()
            assert start >= last_right - 0.5
            last_right = start + item.width()
        assert h.find("helpButton").isEnabled()
        assert not h.find("defaultsButton").isEnabled()
        assert h.find("defaultsButton").isVisible()
        assert not h.find("defaultsUnavailable").isVisible()
        apply = h.find("applyButton")
        apply_right = apply.mapToItem(bar, QPointF(apply.width(), 0)).x()
        assert abs(bar.width() - apply_right - bar.property("rightPadding")) <= 1
        assert h.find("resetButton").isEnabled() == (
            h.backend.profileMappingsDirty and not h.backend.busy
        )
        assert h.find("applyButton").isEnabled() == (
            h.backend.profileMappingsDirty
            and not h.backend.busy
            and h.backend.connected
        )

    def stage(value):
        h.set_layer(False)
        h.quick_record(0, (Qt.Key.Key_F6 if value == 5 else Qt.Key.Key_F7,))
        assert h.backend.dirty
        state()

    for width, height in [(1400, 820), (1200, 820), (960, 700)]:
        h.window.resize(width, height)
        h.settle(150)
        state()
        h.capture(f"kde-footer-help-reset-apply-{width}")
    before = h.view_snapshot()
    h.click("helpButton")
    handbook = h.handbook._dialog
    assert handbook is not None and handbook.isVisible()
    assert handbook.objectName() == "handbookDialog"
    assert "Piper" in handbook.browser.toPlainText()
    QTest.keyClick(handbook, Qt.Key.Key_Escape)
    h.interactions.append(
        {"action": "key_click", "object": "handbookDialog", "key": "Key_Escape"}
    )
    h.settle(150)
    assert not handbook.isVisible()
    h.window.requestActivate()
    h.settle(100)
    h.assert_view_unchanged(before)
    h.key(Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    h.assert_view_unchanged(before)
    stage(5)
    assert h.backend._transport.calls == []
    h.focus_with_tab("helpButton")
    h.key(Qt.Key.Key_Tab)
    assert h.find(
        "resetButton"
    ).hasActiveFocus(), "Reset must follow Help in the footer Tab order"
    h.key(Qt.Key.Key_Tab)
    assert h.find(
        "applyButton"
    ).hasActiveFocus(), "Apply must follow Reset; hidden Defaults must not take focus"
    h.key(Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
    assert h.find("resetButton").hasActiveFocus()
    h.key(Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
    assert h.find("helpButton").hasActiveFocus()
    before = h.view_snapshot()
    h.key(Qt.Key.Key_Space)
    assert h.handbook._dialog is handbook and handbook.isVisible()
    QTest.keyClick(handbook, Qt.Key.Key_Escape)
    h.interactions.append(
        {"action": "key_click", "object": "handbookDialog", "key": "Key_Escape"}
    )
    h.settle(150)
    assert not handbook.isVisible()
    h.window.requestActivate()
    h.settle(100)
    h.assert_view_unchanged(before)
    h.capture("kde-footer-dirty-keyboard-order")
    draft = deepcopy(h.backend._draft)
    for shifted in [True, False, True, False]:
        h.set_layer(shifted)
        state()
    for profile in [1, 0]:
        h.combo("profileSelect", profile)
        assert h.backend._draft == draft and h.backend.dirty
        state()
    for device in ["Capability", "G600"]:
        h.select_device(device)
        assert h.backend._draft == draft and h.backend.dirty
        state()
    assert h.backend._transport.calls == []
    h.window.close()
    h.interactions.append({"action": "window_close_request", "dirty": True})
    h.settle(200)
    assert h.window.isVisible() and h.find("closeDialog").property("visible")
    h.click("keepEditingButton")
    assert h.window.isVisible() and h.backend._draft == draft
    h.click("resetButton")
    assert not h.backend.dirty and h.backend._draft == initial_draft
    assert h.backend._transport.calls == []
    state()

    stage(5)
    h.backend.simulateDisconnect()
    h.settle(150)
    state()
    before = h.view_snapshot()
    h.key(Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    h.assert_view_unchanged(before)
    h.backend.simulateReconnect()
    h.idle()
    assert h.backend.dirty and h.button(0)["actionValue"] == [[1, 64], [2, 64]]
    state()
    h.backend.simulateCommitFailure()
    h.click("applyButton")
    h.idle()
    assert h.backend.dirty and h.backend.error and h.backend._transport.calls == []
    state()

    # Hold only the mock transport so the real busy-state controls and close
    # guard can be exercised deterministically, without timing races/hardware.
    release = Event()
    real_apply = h.backend._transport.apply
    apply_attempts = []

    async def held_apply(operations):
        apply_attempts.append(list(operations))
        while not release.is_set():
            await asyncio.sleep(0.02)
        return await real_apply(operations)

    h.backend._transport.apply = held_apply
    try:
        h.click("applyButton")
        assert h.backend.busy
        state()
        h.key(Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        assert len(apply_attempts) == 1 and h.backend._transport.calls == []
        h.window.close()
        h.interactions.append({"action": "window_close_request", "busy": True})
        h.settle(150)
        assert h.window.isVisible(), "An in-flight Apply must not be abandoned"
        assert not h.find("closeDialog").property("visible")
        assert not h.find("contentLayerTabs").isEnabled()
        assert not h.window.property("shifted")
        h.click("buttonQuickMacro0")
        assert h.window.property("quickMacroIndex") == -1 and not h.recorder.active
        state()
    finally:
        release.set()
        h.idle()
        h.backend._transport.apply = real_apply
    assert not h.backend.dirty and not h.backend.error
    assert h.backend._transport.calls == apply_attempts[0]
    state()
    h.capture("kde-footer-after-apply")
    committed = deepcopy(h.backend._transport.calls)
    stage(2)
    h.window.close()
    h.interactions.append({"action": "window_close_request", "dirty": True})
    h.settle(150)
    assert h.find("closeDialog").property("visible")
    h.click("discardCloseButton")
    assert not h.window.isVisible()
    assert h.backend._transport.calls == committed, "Discard and close must not Apply"
    return {
        "native_footer_sizes": [[1400, 820], [1200, 820], [960, 700]],
        "defaults_supported": False,
        "unsupported_defaults_disabled_without_placeholder": True,
        "handbook_opened_by_footer_mouse_and_keyboard": True,
        "footer_keyboard_order": ["helpButton", "resetButton", "applyButton"],
        "reset_transport_writes": 0,
        "apply_attempts_while_busy": len(apply_attempts),
        "pending_profile_device_close_preserved": True,
        "mock_failure_disconnect_busy_guards": True,
    }


def scenario_hig_accessibility(h):
    checked = []

    def accessible(name, expected):
        item = h.find(name)
        interface = QAccessible.queryAccessibleInterface(item)
        assert interface is not None, f"Missing accessible interface: {name}"
        actual = interface.text(QAccessible.Text.Name)
        assert actual == expected, f"{name}: accessible name {actual!r} != {expected!r}"
        checked.append({"object": name, "name": actual})

    def visible_controls(names):
        for name in names:
            h.focus_with_tab(name)
            assert h.fully_visible(
                h.find(name)
            ), f"Focused mapping control {name} is clipped"
            for action in ["applyButton", "resetButton", "helpButton"]:
                assert h.fully_visible(
                    h.find(action)
                ), f"Mapping action {action} is clipped"

    h.select_device("Capability")
    points = h.app.font().pointSize()
    sizes = [(960, 700)] if points == 14 else [(1400, 820), (960, 700)]
    for width, height in sizes:
        h.window.resize(width, height)
        h.settle(150)
        h.edit_target(0)
        accessible("mappingType", "Assignment type")
        assert abs(h.find("mappingType").property("font").pointSizeF() - points) < 0.1
        for action in ["none", "button", "key", "special", "macro"]:
            h.mapping_type(action)
            names = ["mappingType"]
            if action == "button":
                accessible(
                    "mouseButtonPicker",
                    "Choose mouse button. Current: "
                    + h.find("mouseButtonPicker").property("text"),
                )
                names.append("mouseButtonPicker")
            elif action == "key":
                accessible(
                    "keyPicker",
                    "Choose keyboard key. Current: "
                    + h.find("keyPicker").property("text"),
                )
                names.append("keyPicker")
                h.focus_with_tab("keyPicker")
                assert h.find("keyPicker").hasActiveFocus()
            elif action == "special":
                accessible("specialAction", "Special action")
                names.append("specialAction")
            elif action == "macro":
                h.add_event(1, 64)
                h.add_event(2, 64)
                assert not h.find(
                    "macroJson"
                ).isVisible(), "Raw JSON must not be the primary editor"
                accessible("macroAddEvent", "Add macro event")
                assert h.window.findChild(original_ui.QObject, "recordMacro") is None
                last = h.find("macroEventName0")
                for name in [
                    "macroEventUp0",
                    "macroEventDown0",
                    "macroEventRemove0",
                ]:
                    item = h.find(name)
                    assert (
                        item.mapToScene(QPointF(0, 0)).x()
                        >= last.mapToScene(QPointF(last.width(), 0)).x() - 1
                    )
                    last = item
                assert (
                    h.window.findChild(original_ui.QObject, "macroEventKind0") is None
                )
                for removed in ["macroEventKey0", "macroEventDelay0"]:
                    assert h.window.findChild(original_ui.QObject, removed) is None
                accessible("macroEventRow0", "Event 1, key down, F6")
                accessible("macroEventRemove0", "Remove event 1")
                names.extend(
                    [
                        "macroEventRemove0",
                        "macroAddEvent",
                    ]
                )
                previous = h.payload()
                h.click("macroAddEvent")
                accessible("valuePickerEventType", "New event type")
                accessible("valuePickerSearch", "Search available values")
                for name in [
                    "valuePickerEventType",
                    "valuePickerSearch",
                    "valuePickerCancel",
                ]:
                    assert h.fully_visible(h.find(name)), name
                h.combo("valuePickerEventType", 2)
                accessible("valuePickerDelay", "Delay in milliseconds")
                for name in [
                    "valuePickerDelay",
                    "valuePickerOk",
                    "valuePickerCancel",
                ]:
                    h.focus_with_tab(name)
                    assert h.fully_visible(h.find(name)), name
                h.click("valuePickerCancel")
                assert h.payload() == previous
                assert h.find("macroAddEvent").hasActiveFocus()
            visible_controls(names)
        panel = h.find("macroEventPanel")
        footer = h.find("pendingChangesBar")
        panel_bottom = panel.mapToScene(QPointF(0, panel.height())).y()
        footer_top = footer.mapToScene(QPointF(0, 0)).y()
        assert abs(panel_bottom - footer_top) <= 2, (panel_bottom, footer_top)
        row = h.find("macroEventRow0")
        assert row.height() <= h.find("mappingType").height() * 1.6
        assert panel.height() > row.height() * 5
        h.capture(f"kde-hig-macro-{width}-{points}pt")
        if points == 14:
            before = h.view_snapshot()
            h.focus_with_tab("macroEventRemove1")
            h.key(Qt.Key.Key_Space)
            assert not h.find("applyButton").isEnabled()
            assert h.find("assignmentPage").property("visible")
            validation = h.find("mappingValidation")
            assert validation.isVisible() and h.fully_visible(validation)
            assert validation.property("text")
            for action in ["applyButton", "resetButton", "helpButton"]:
                assert h.fully_visible(h.find(action))
            h.assert_view_unchanged(before)
            h.capture("kde-hig-invalid-macro-14pt")
        h.click("resetButton")
        h.focus_with_tab("assignmentBack")
        h.key(Qt.Key.Key_Space)
        assert not h.find("assignmentPage").property("visible")
        assert not h.backend.dirty
    if points == 14:
        h.quick_record(0, tuple(getattr(Qt.Key, f"Key_F{i}") for i in range(1, 13)))
        h.edit_row(0)
        assert len(h.payload()["value"]) == 24
        form_top = h.find("assignmentForm").mapToScene(QPointF(0, 0)).y()
        h.focus_with_tab("macroEventRemove23")
        assert (
            abs(h.find("assignmentForm").mapToScene(QPointF(0, 0)).y() - form_top)
            <= 0.5
        ), "Event focus must scroll the inner list without moving the outer form"
        assert h.fully_visible(h.find("macroEventRemove23"))
        event_list = h.find("macroEventList")
        assert event_list.property("contentY") > 0
        assert event_list.property("contentHeight") > event_list.height()
        assert h.fully_visible(h.find("applyButton"))
        h.capture("kde-hig-long-events-960-14pt")
        h.click("resetButton")
        h.back()
    h.select_device("G600")
    h.window.resize(1400, 820)
    h.settle(150)
    for shifted in [False, True]:
        h.set_layer(shifted)
        for index in range(21, 29) if shifted else range(8):
            button = h.button(index)
            accessible(
                "buttonAssignment" + str(index),
                f"Button {button['physicalIndex'] + 1}, {button['actionLabel']}",
            )
    h.click("sensitivityTab")
    for resolution in h.backend.selectedProfile["resolutions"]:
        index = resolution["index"]
        for control, label in [
            ("Enabled", "enabled"),
            ("Active", "active"),
            ("Default", "default"),
        ]:
            accessible(f"resolution{control}{index}", f"Stage {index + 1} {label}")
    assert not h.backend.dirty and h.backend._transport.calls == []
    font_points = [points]
    if points != 14:
        # Kirigami caches theme metrics. Validate a real 14pt startup in a
        # fresh native process, not a mislabeled mid-engine font override.
        output = h.output / "native-14pt"
        env = os.environ.copy()
        env["PIPER_TEST_FONT_POINTS"] = "14"
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/verify-kde-ui.py"),
                "--scenario",
                "hig_accessibility",
                "--output",
                str(output),
            ],
            env=env,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        large = json.loads((output / "kde-ui-verification.json").read_text())[
            "results"
        ][0]
        assert large["passed"] and large["mapping_font_points_checked"] == [14]
        checked.extend(large["accessible_controls_checked"])
        h.interactions.extend(large["interactions"])
        h.screenshots.extend(large["screenshots"])
        h.qml_warnings.extend(large["qml_warnings"])
        font_points.append(14)
    return {
        "accessible_controls_checked": checked,
        "mapping_sizes_checked": [[1400, 820], [960, 700]],
        "mapping_font_points_checked": font_points,
        "native_visual_event_keyboard": True,
        "large_font_validation_revealed": True,
        "event_panel_fills_to_footer": True,
        "compact_rows_and_long_list_keyboard_scroll": True,
    }


def scenario_error_recovery(h):
    error = h.find("backendErrorMessage")
    assert not error.isVisible()
    h.backend.simulateDisconnect()
    h.settle(150)
    first = h.backend.error
    assert first and error.isVisible() and error.property("text") == first
    h.click("dismissErrorAction")
    assert not h.backend.error and not error.isVisible()
    h.backend.simulateReconnect()
    h.idle()
    h.select_device("G600")
    h.edit_target(0)
    h.mapping_type("button")
    h.spin("mouseButtonNumber", 5)
    h.backend.simulateCommitFailure()
    h.click("applyButton")
    h.idle()
    second = h.backend.error
    assert second and second != first
    assert (
        error.isVisible() and error.property("text") == second
    ), "Dismissing an earlier error broke visibility of the next backend error"
    h.capture("kde-second-error-after-dismiss")
    h.click("dismissErrorAction")
    assert not error.isVisible() and not h.backend.error and h.backend.dirty
    h.click("resetButton")
    assert not h.backend.dirty
    h.back()

    h.click("lightingTab")
    h.click_target("leds", 0)
    validation = h.find("ledValidation")
    color_message = h.find("ledDialog").property("colorValidationMessage")
    assert not validation.isVisible() and validation.property("text") == color_message
    h.backend.simulateDisconnect()
    h.settle(100)
    h.click("ledSave")
    assert validation.isVisible() and validation.property("text") == h.backend.error
    assert validation.property("text") != color_message
    h.click("ledCancel")
    h.backend.simulateReconnect()
    h.idle()
    h.click_target("leds", 0)
    assert not validation.isVisible() and validation.property("text") == color_message
    # Trigger a second backend error in this same dialog, then invalid color
    # input must replace it with the relevant color-validation explanation.
    h.backend.simulateDisconnect()
    h.settle(100)
    h.click("ledSave")
    assert validation.property("text") != color_message
    before = h.view_snapshot()
    h.text("ledColor", "badcolor")
    assert not h.find("ledSave").isEnabled()
    assert validation.isVisible() and validation.property("text") == color_message
    h.assert_view_unchanged(before)
    h.text("ledColor", "#33aaff")
    assert h.find("ledSave").isEnabled() and not validation.isVisible()
    h.assert_view_unchanged(before)
    h.text("ledColor", "badcolor")
    h.capture("kde-led-validation-reset")
    h.click("ledCancel")
    h.backend.simulateReconnect()
    h.idle()
    assert not h.backend.dirty and h.backend._transport.calls == []
    return {
        "new_error_after_dismiss_visible": True,
        "led_validation_reset_on_open_and_invalid_input": True,
        "transport_writes": 0,
    }


def scenario_assignment_navigation(h):
    h.select_device("G600")
    original = deepcopy(h.button(0))
    routes = []

    def edit(value=5):
        h.click("buttonsTab")
        h.set_layer(False)
        h.edit_target(0)
        h.mapping_type("button")
        h.spin("mouseButtonNumber", value)
        assert h.find("assignmentPage").property("edited")
        assert h.find("navigationSidebar").isVisible()
        assert h.find("assignmentSidebarEntry").isVisible()
        assert not h.find("buttonsTab").property("checked")

    def prompt():
        assert h.window.property("assignmentEditing")
        assert h.find("assignmentNavigationDialog").property("visible")
        for name in [
            "assignmentKeepEditing",
            "assignmentDiscardChanges",
            "assignmentApplyContinue",
        ]:
            assert h.fully_visible(h.find(name))

    edit()
    before = h.view_snapshot()
    h.click("assignmentBack")
    prompt()
    h.click("assignmentKeepEditing")
    assert h.find("mouseButtonNumber").property("value") == 5
    h.assert_view_unchanged(before)
    h.key(Qt.Key.Key_Escape)
    assert h.window.property(
        "assignmentEditing"
    ), "Escape must not discard a child draft"
    h.click("assignmentBack")
    prompt()
    h.click("assignmentDiscardChanges")
    assert not h.window.property("assignmentEditing") and h.button(0) == original
    routes.append("Back: Keep editing and Discard")

    edit()
    h.click("sensitivityTab")
    prompt()
    h.click("assignmentDiscardChanges")
    assert h.window.property("page") == 0 and not h.window.property("assignmentEditing")
    routes.append("sidebar")

    edit()
    h.combo("profileSelect", 1, verify=False)
    prompt()
    assert h.backend.selectedProfileIndex == 0
    h.click("assignmentKeepEditing")
    h.combo("profileSelect", 1, verify=False)
    prompt()
    h.click("assignmentDiscardChanges")
    assert h.backend.selectedProfileIndex == 1 and not h.window.property(
        "assignmentEditing"
    )
    h.combo("profileSelect", 0)
    routes.append("profile")

    edit()
    h.combo("deviceSelect", 1, verify=False)
    prompt()
    assert h.backend.selectedDeviceIndex == 0
    h.click("assignmentDiscardChanges")
    assert h.backend.selectedDeviceIndex == 1 and not h.window.property(
        "assignmentEditing"
    )
    h.select_device("G600")
    routes.append("device")

    edit()
    h.key(Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    h.text("settingsSearch", "gshift g20")
    h.key(Qt.Key.Key_Return)
    prompt()
    assert not h.window.property("shifted")
    h.click("assignmentDiscardChanges")
    h.assert_selected(40)
    assert h.window.property("shifted")
    h.text("settingsSearch", "")
    routes.append("search across layers")

    edit()
    h.click("assignmentBack")
    prompt()
    h.click("assignmentApplyContinue")
    h.idle()
    assert not h.window.property("assignmentEditing")
    assert h.button(0)["actionValue"] == 5
    assert len(h.backend._transport.calls) == 1
    h.edit_target(0)
    assert h.find("mouseButtonNumber").property("value") == 5
    h.back()
    routes.append("Apply and continue/reopen")

    edit(2)
    h.backend.simulateCommitFailure()
    h.click("assignmentBack")
    h.click("assignmentApplyContinue")
    h.idle()
    prompt()
    assert h.find("assignmentPage").property("edited") and h.backend.error
    h.click("assignmentKeepEditing")
    h.click("resetButton")
    h.back()
    assert h.button(0)["actionValue"] == 5
    assert len(h.backend._transport.calls) == 1
    routes.append("failed Apply keeps editor")

    h.edit_target(0)
    h.mapping_type("macro")
    h.add_event(1, 30)
    assert not h.find("applyButton").isEnabled()
    assert h.fully_visible(h.find("mappingValidation"))
    h.click("assignmentBack")
    prompt()
    assert not h.find("assignmentApplyContinue").isEnabled()
    h.click("assignmentKeepEditing")
    h.click("resetButton")
    h.back()
    routes.append("invalid input blocks Apply and continue")

    edit(2)
    h.backend.simulateDisconnect()
    h.settle(150)
    assert not h.find("assignmentPage").property("contextValid")
    assert not h.find("applyButton").isEnabled()
    h.backend.simulateReconnect()
    h.idle()
    assert not h.find("assignmentPage").property("contextValid")
    h.back(discard=True)
    assert len(h.backend._transport.calls) == 1
    routes.append("disconnect invalidates captured context")

    edit(2)
    h.window.close()
    h.interactions.append(
        {"action": "window_close_request", "local_assignment_dirty": True}
    )
    prompt()
    h.click("assignmentKeepEditing")
    assert h.window.isVisible()
    h.window.close()
    prompt()
    h.click("assignmentDiscardChanges")
    assert not h.window.isVisible()
    assert len(h.backend._transport.calls) == 1
    routes.append("window close")
    return {"guarded_navigation_routes": routes, "explicit_scoped_writes": 1}


def scenario_scoped_assignments(h):
    h.select_device("G600")
    h.quick_record(0, (Qt.Key.Key_F6,))
    h.quick_record(1, (Qt.Key.Key_F7,))
    h.set_layer(True)
    h.quick_record(21, (Qt.Key.Key_F8,))
    h.set_layer(False)
    h.click("sensitivityTab")
    resolution = h.backend.selectedProfile["resolutions"][0]
    values = resolution["values"]
    h.combo("dpiX0", (values.index(resolution["x"]) + 1) % len(values))
    h.click("lightingTab")
    h.click_target("leds", 0)
    h.text("ledColor", "#33aaff")
    h.click("ledSave")
    h.combo("profileSelect", 1)
    h.click("buttonsTab")
    h.quick_record(8, (Qt.Key.Key_F9,))
    h.combo("profileSelect", 0)
    profiles = h.backend._draft[h.backend.selectedDeviceIndex]["profiles"]
    unrelated = deepcopy((profiles[1], profiles[0]["resolutions"], profiles[0]["leds"]))
    paths = {index: h.button(index)["path"] for index in [0, 1, 21]}
    assert h.backend._transport.calls == []

    def preserved():
        profiles = h.backend._draft[h.backend.selectedDeviceIndex]["profiles"]
        assert (
            profiles[1],
            profiles[0]["resolutions"],
            profiles[0]["leds"],
        ) == unrelated
        assert h.backend.dirty

    h.edit_target(0)
    h.mapping_type("button")
    h.spin("mouseButtonNumber", 5)
    h.apply_assignment()
    assert [(op.path, op.member) for op in h.backend._transport.calls] == [
        (paths[0], "Mapping")
    ]
    preserved()
    h.back()
    assert h.backend.profileMappingsDirty
    h.click("applyButton")
    h.idle()
    assert not h.backend.error, h.backend.error
    assert {op.path for op in h.backend._transport.calls} == set(paths.values())
    assert len(h.backend._transport.calls) == 3
    assert all(op.member == "Mapping" for op in h.backend._transport.calls)
    assert not h.backend.profileMappingsDirty
    preserved()
    committed = deepcopy(h.backend.selectedProfile["buttons"])
    h.quick_record(0, (Qt.Key.Key_F10,))
    h.set_layer(True)
    h.quick_record(21, (Qt.Key.Key_F11,))
    h.click("resetButton")
    assert h.backend.selectedProfile["buttons"] == committed
    assert not h.backend.profileMappingsDirty
    assert (
        not h.find("applyButton").isEnabled() and not h.find("resetButton").isEnabled()
    )
    preserved()

    # The editor must not accept unseen new local input during an in-flight Apply.
    h.set_layer(False)
    h.edit_target(0)
    h.mapping_type("button")
    h.spin("mouseButtonNumber", 2)
    release = Event()
    real_apply = h.backend._transport.apply
    attempts = []

    async def held_apply(operations):
        attempts.append(list(operations))
        while not release.is_set():
            await asyncio.sleep(0.02)
        return await real_apply(operations)

    h.backend._transport.apply = held_apply
    try:
        h.click("applyButton")
        assert h.backend.busy and h.find("assignmentPage").property("applying")
        assert (
            not h.find("mappingType").isEnabled()
            and not h.find("mouseButtonNumber").isEnabled()
        )
        assert (
            not h.find("resetButton").isEnabled()
            and not h.find("applyButton").isEnabled()
        )
        h.key(Qt.Key.Key_9)
        assert h.find("mouseButtonNumber").property("value") == 2
        h.click("sensitivityTab")
        h.click("assignmentBack")
        h.combo("profileSelect", 1, verify=False)
        h.combo("deviceSelect", 1, verify=False)
        assert h.window.property("assignmentEditing") and h.window.property("page") == 1
        assert (
            h.backend.selectedProfileIndex == 0 and h.backend.selectedDeviceIndex == 0
        )
        h.key(Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        h.window.close()
        assert h.window.isVisible() and len(attempts) == 1
    finally:
        release.set()
        h.idle()
        h.backend._transport.apply = real_apply
    assert h.button(0)["actionValue"] == 2
    assert not h.find("assignmentPage").property("edited")
    assert len(h.backend._transport.calls) == 4
    preserved()
    h.capture("kde-scoped-assignment-child")
    h.back()
    return {
        "child_mapping_writes": 1,
        "main_profile_mapping_writes": 2,
        "unrelated_drafts_preserved": True,
        "main_revert_scope_preserved": True,
        "busy_editor_and_navigation_guarded": True,
        "busy_apply_attempts": len(attempts),
    }


def scenario_quick_macro(h):
    h.select_device("G600")
    original = deepcopy(h.backend.selectedProfile)
    h.select_target(0)
    collapsed_height = h.find("buttonAssignment0").height()
    h.click("buttonQuickMacro0")
    assert h.recorder.active and not h.window.property("assignmentEditing")
    h.click("quickMacroStop0")
    assert "No shortcut" in h.find("quickMacroStatus0").property("text")
    assert h.backend.selectedProfile == original and h.backend._transport.calls == []
    h.click("quickMacroCancel0")

    h.click("buttonQuickMacro0")
    QTest.keyPress(h.window, Qt.Key.Key_Control)
    h.key(Qt.Key.Key_VolumeUp)
    QTest.keyRelease(h.window, Qt.Key.Key_Control)
    h.interactions.append(
        {"action": "record_unsupported_chord", "keys": ["Control", "VolumeUp"]}
    )
    h.click("quickMacroStop0")
    assert h.recorder.error
    assert h.find("quickMacroStatus0").property("text") == h.recorder.error
    assert h.backend.selectedProfile == original
    assert not h.find("applyButton").isEnabled()
    h.click("quickMacroCancel0")

    h.quick_record(0)
    assert abs(h.find("buttonAssignment0").height() - collapsed_height) <= 0.5
    assert h.find("buttonQuickMacro0").hasActiveFocus()
    assert "F6" in h.find("assignmentValue0").property("text")
    staged = deepcopy(h.backend.selectedProfile)
    h.select_target(1)
    h.click("buttonQuickMacro1")
    h.key(Qt.Key.Key_F1)
    h.key(Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert h.handbook._dialog is None
    assert not h.find("settingsSearch").hasActiveFocus()
    h.click("sensitivityTab")
    assert h.window.property("page") == 1 and h.window.property("quickMacroIndex") == 1
    h.click("gshiftLayer")
    assert not h.window.property("shifted")
    assert not h.find("applyButton").isEnabled()
    h.click("quickMacroCancel1")
    assert h.backend.selectedProfile == staged
    assert h.find("buttonQuickMacro1").hasActiveFocus()
    h.capture("kde-quick-shortcut-staged")
    h.click("buttonQuickMacro1")
    h.key(Qt.Key.Key_F7)
    h.click("resetButton")
    assert not h.recorder.active and h.window.property("quickMacroIndex") == -1
    assert h.backend.selectedProfile == original and not h.backend.dirty
    assert h.backend._transport.calls == []
    return {
        "direct_inline_recording": True,
        "empty_and_unknown_chords_rejected": True,
        "recording_blocks_navigation_and_shortcuts": True,
        "cancel_and_revert_no_writes": True,
        "transport_writes": 0,
    }


def scenario_value_picker(h):
    h.select_device("Capability")
    h.edit_target(0)
    h.mapping_type("key")
    baseline = h.view_snapshot()
    previous = h.payload()

    def choices(filtered=False):
        value = h.find("valuePicker").property(
            "filteredChoices" if filtered else "choices"
        )
        return value.toVariant() if hasattr(value, "toVariant") else value

    def cancelled():
        assert not h.find("valuePicker").property("visible")
        assert h.find("keyPicker").hasActiveFocus()
        assert h.payload() == previous
        h.assert_view_unchanged(baseline)

    h.click("keyPicker")
    assert h.find("valuePicker").property("visible")
    assert h.find("valuePickerSearch").hasActiveFocus()
    full = choices()
    assert [entry["value"] for entry in full] == list(range(1, 768))
    assert h.find("valuePickerList").property("count") == 767
    current = h.find("keyPicker").property("currentValue")
    current_row = h.find("valuePickerOption" + str(current))
    assert current_row.property("highlighted") and h.fully_visible(current_row)
    h.text("valuePickerSearch", "zzznomatchingvalue")
    assert not choices(True) and h.find("valuePickerEmpty").isVisible()
    assert not h.find("valuePickerOk").isEnabled()
    h.key(Qt.Key.Key_Return)
    assert h.find("valuePicker").property("visible") and h.payload() == previous
    h.key(Qt.Key.Key_Escape)
    cancelled()

    h.click("keyPicker")
    assert (
        h.find("valuePickerSearch").property("text") == "" and len(choices(True)) == 767
    )
    h.text("valuePickerSearch", "46")
    filtered = choices(True)
    assert filtered[0]["value"] == 46 and len(filtered) > 1
    assert not h.find("valuePickerOk").isEnabled()
    h.key(Qt.Key.Key_Down)
    assert h.find("valuePickerList").hasActiveFocus()
    h.key(Qt.Key.Key_Down)
    assert h.find("valuePickerList").property("currentIndex") == 1
    h.key(Qt.Key.Key_Up)
    assert h.find("valuePickerList").property("currentIndex") == 0
    assert (
        h.payload() == previous
    ), "Searching and arrow navigation must not mutate the draft"
    h.capture("kde-searchable-value-picker")
    h.key(Qt.Key.Key_Enter)
    assert not h.find("valuePicker").property("visible")
    assert h.find("keyPicker").property("currentValue") == 46
    assert h.find("keyPicker").hasActiveFocus()
    previous = h.payload()
    h.assert_view_unchanged(baseline)

    h.click("keyPicker")
    label = next(choice["label"] for choice in full if choice["value"] == 1)
    h.text("valuePickerSearch", label)
    assert any(choice["value"] == 1 for choice in choices(True))
    h.click("valuePickerOption1")
    assert h.find("valuePicker").property("pendingValue") == 1
    assert h.payload() == previous
    h.click("valuePickerCancel")
    cancelled()
    h.click("keyPicker")
    h.text("valuePickerSearch", "48")
    h.click("valuePickerOption48")
    assert h.payload() == previous
    QTest.mouseClick(
        h.window,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPointF(5, 5).toPoint(),
    )
    h.interactions.append({"action": "picker_click_outside", "x": 5, "y": 5})
    h.settle(350)
    cancelled()
    h.choose_value("keyPicker", 700)
    assert h.payload()["value"] == 700 and "700" in h.find("keyPicker").property("text")
    h.mapping_type("button")
    h.click("mouseButtonPicker")
    assert [entry["value"] for entry in choices()] == list(range(1, 33))
    h.key(Qt.Key.Key_Escape)
    assert h.find("mouseButtonPicker").hasActiveFocus()
    h.choose_value("mouseButtonPicker", 32)
    assert h.payload()["value"] == 32
    h.assert_view_unchanged(baseline)
    h.mapping_type("key")
    previous = h.payload()
    h.click("keyPicker")
    h.text("valuePickerSearch", "48")
    h.click("valuePickerOption48")
    assert h.payload() == previous
    h.backend.simulateDisconnect()
    h.settle(400)
    assert not h.find("assignmentPage").property("contextValid")
    assert not h.find("valuePicker").property(
        "visible"
    ), "Stale context must close the picker"
    assert (
        h.payload() == previous
    ), "A picker opened for a stale context must not assign a value"
    assert h.backend._transport.calls == []
    h.backend.simulateReconnect()
    h.idle()
    h.back(discard=True)
    assert not h.backend.dirty and h.backend._transport.calls == []
    return {
        "full_key_choice_count": 767,
        "full_mouse_choice_count": 32,
        "search_arrows_enter_escape_cancel": True,
        "focus_returns_to_opener": True,
        "selection_only_mutates_local_draft": True,
        "explicit_ok_required_and_cancel_preserves_pending_choice": True,
        "stale_context_rejected": True,
        "transport_writes": 0,
    }


def scenario_visual_events(h):
    h.select_device("Capability")
    h.edit_target(0)
    h.mapping_type("macro")
    baseline = h.view_snapshot()
    assert h.window.findChild(original_ui.QObject, "recordMacro") is None
    h.add_event(1, 64)
    h.add_event(2, 64)
    assert h.payload()["value"] == [[1, 64], [2, 64]]
    assert not h.find("macroJson").isVisible()
    panel = h.find("macroEventPanel")
    assert panel.width() > h.find("assignmentPage").width() * 0.9
    assert h.find("macroEventHeader").isVisible()

    def add(kind, value):
        h.add_event(kind, value)
        h.assert_view_unchanged(baseline)

    before = h.payload()
    h.click("macroAddEvent")
    h.combo("valuePickerEventType", 1)
    h.text("valuePickerSearch", "48")
    h.click("valuePickerOption48")
    assert h.payload() == before
    h.click("valuePickerCancel")
    assert h.payload() == before and h.find("macroAddEvent").hasActiveFocus()
    add(1, 30)
    assert not h.find("applyButton").isEnabled()
    assert h.find("mappingValidation").isVisible()
    add(2, 30)
    assert h.find("applyButton").isEnabled()
    add(3, 200)
    assert h.payload()["value"][-1] == [3, 200]
    for removed in ["macroEventKind0", "macroEventKey0", "macroEventDelay4"]:
        assert h.window.findChild(original_ui.QObject, removed) is None
    h.focus_with_tab("macroEventUp4")
    h.key(Qt.Key.Key_Return)
    assert h.payload()["value"][3] == [3, 200]
    assert h.find("macroEventUp3").hasActiveFocus()
    h.key(Qt.Key.Key_Return)
    assert h.payload()["value"][2] == [3, 200]
    assert h.find("macroEventUp2").hasActiveFocus()
    h.key(Qt.Key.Key_Return)
    h.key(Qt.Key.Key_Return)
    assert h.payload()["value"][0] == [3, 200]
    assert h.find("macroEventRow0").hasActiveFocus()
    edge = h.payload()
    h.key(Qt.Key.Key_Return)
    assert (
        h.payload() == edge
    ), "Repeated Return at the edge must not delete or reverse the event"
    h.click("macroEventDown0")
    h.key(Qt.Key.Key_Return)
    assert h.payload()["value"][2] == [3, 200]
    h.click("macroEventRemove2")
    assert h.find("macroAddEvent").hasActiveFocus()
    # Immutable rows are replaced by removing and adding configured events.
    h.click("macroEventRemove3")
    assert not h.find("applyButton").isEnabled()
    h.click("macroEventRemove2")
    add(1, 48)
    add(2, 48)
    h.click("macroEventDown0")
    assert not h.find("applyButton").isEnabled()
    assert h.find("mappingValidation").isVisible()
    h.click("macroEventUp1")
    assert h.find("applyButton").isEnabled()
    h.click("macroEventRemove3")
    assert not h.find("applyButton").isEnabled()
    add(2, 48)
    h.capture("kde-visual-event-editor")
    assert h.payload()["value"] == [[1, 64], [2, 64], [1, 48], [2, 48]]
    h.apply_assignment()
    assert len(h.backend._transport.calls) == 1
    h.back()
    h.edit_target(0)
    assert h.payload()["value"] == [[1, 64], [2, 64], [1, 48], [2, 48]]
    h.click("macroEventRemove3")
    h.click("resetButton")
    assert h.payload()["value"] == [[1, 64], [2, 64], [1, 48], [2, 48]]
    h.back()

    h.select_device("G600")
    h.quick_record(0, (Qt.Key.Key_Control,))
    h.edit_row(0)
    events = h.payload()["value"]
    assert [1, 0] in events and [2, 0] in events
    index = events.index([1, 0])
    assert "Reserved" in h.find("macroEventName" + str(index)).property("text")
    h.click("macroAddEvent")
    choices = h.find("valuePicker").property("choices").toVariant()
    from qt_piper.backend import G600_KEYBOARD_CODES

    assert [entry["value"] for entry in choices] == sorted(G600_KEYBOARD_CODES)
    assert len(choices) == 135 and all(entry["value"] != 0 for entry in choices)
    h.click("valuePickerCancel")
    assert h.payload()["value"] == events
    h.click("macroAddEvent")
    assert h.find("valuePickerEventType").property("count") == 2
    assert not h.find("valuePickerDelay").isVisible()
    h.click("valuePickerCancel")
    assert h.payload()["value"] == events
    h.click("resetButton")
    h.back()
    assert not h.backend.dirty
    return {
        "visual_add_cancel_replace_remove_reorder": True,
        "incomplete_sequence_blocks_apply": True,
        "generic_delay_supported": True,
        "repeated_keyboard_move_tracks_event": True,
        "reorder_edge_focus_is_safe": True,
        "g600_complete_key_choice_count": 135,
        "reserved_zero_not_selectable": True,
        "explicit_scoped_writes": 1,
    }


SCENARIOS = {
    "overview": scenario_overview,
    "mapping": scenario_mapping,
    "gshift": scenario_gshift,
    "led": scenario_led,
    "profiles_and_sensitivity": scenario_profiles_and_sensitivity,
    "all_assignments": scenario_all_assignments,
    "keyboard": scenario_keyboard,
    "all_targets": scenario_all_targets,
    "selection_reveal": scenario_selection_reveal,
    "narrow_targets": scenario_narrow_targets,
    "hover_feedback": scenario_hover_feedback,
    "minimum_size": scenario_minimum_size,
    "search": scenario_search,
    "footer": scenario_footer,
    "hig_accessibility": scenario_hig_accessibility,
    "error_recovery": scenario_error_recovery,
    "assignment_navigation": scenario_assignment_navigation,
    "scoped_assignments": scenario_scoped_assignments,
    "quick_macro": scenario_quick_macro,
    "value_picker": scenario_value_picker,
    "visual_events": scenario_visual_events,
}


def run_scenario(name, output):
    h = None
    sources = [
        "qt_piper/qml/Main.qml",
        "qt_piper/qml/AssignmentPage.qml",
        "qt_piper/qml/ValuePicker.qml",
        "qt_piper/qml/LedDialog.qml",
        "qt_piper/backend.py",
        "qt_piper/recorder.py",
    ]
    hashes = {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in sources
    }
    result = {"scenario": name, "passed": False, "source_sha256": hashes}
    try:
        h = KDEHarness(output)
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
    result["source_unchanged"] = all(
        hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
        for path, digest in hashes.items()
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "evidence-kde/pane-layout"
    )
    parser.add_argument("--scenario", action="append", choices=SCENARIOS)
    args = parser.parse_args()
    report = {
        "renderer": "QApplication; org.kde.desktop Qt Quick Controls; native Breeze; QQuickWindow.grabWindow; real Kirigami QML",
        "backend": "Deterministic mock fixtures; no hardware accessed",
        "interaction_contract": "Button diagram selects/reveals; row shortcut records locally; row chevron opens assignment child; child Apply writes one mapping; main Apply writes selected-profile mappings; other pages apply their own scope",
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
    (args.output / "kde-ui-verification.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
