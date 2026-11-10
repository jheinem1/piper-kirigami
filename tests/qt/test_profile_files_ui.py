# SPDX-License-Identifier: GPL-2.0-or-later
"""Run ProfilePage's native QML interactions in a separate QApplication."""

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_profile_file_native_ui(tmp_path):
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software")
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), env.get("PYTHONPATH", "")])
    result = subprocess.run(
        [sys.executable, str(Path(__file__)), str(tmp_path)],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def run_ui(output):
    import json
    import time
    from copy import deepcopy

    from PySide6.QtCore import QObject, QPointF, Qt, QUrl
    from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, QQmlEngine
    from PySide6.QtQuick import (
        QQuickItem,  # noqa: F401
        QQuickWindow,  # noqa: F401
    )  # noqa: F401 - register window/item wrappers
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from shiboken6 import delete

    from qt_piper.backend import Backend
    from qt_piper.desktop_style import (
        prepare_desktop,
        configure_application,
        DesktopStyle,
    )
    from qt_piper.profile_files import export_document

    prepare_desktop()
    app = QApplication(["Piper profile file QA"])
    configure_application(app)
    style = DesktopStyle(dark=False)
    backend = Backend(mock=True, fixture="all", autostart=False)
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(
        lambda errors: warnings.extend(error.toString() for error in errors)
    )
    for path in (
        "/usr/lib64/qt6/qml",
        "/usr/lib/qt6/qml",
        "/usr/lib/x86_64-linux-gnu/qt6/qml",
    ):
        if Path(path).exists():
            engine.addImportPath(path)
    engine.rootContext().setContextProperty("backend", backend)
    engine.rootContext().setContextProperty("desktopStyle", style)

    def settle(milliseconds=250):
        end = time.monotonic() + milliseconds / 1000
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.002)

    settle()
    assert not backend.connected
    output.mkdir(parents=True, exist_ok=True)
    wrapper = output / "ProfileTest.qml"
    wrapper.write_text(
        '''import QtQuick
import QtQuick.Controls
import org.kde.kirigami as Kirigami
import "'''
        + QUrl.fromLocalFile(str(ROOT / "qt_piper/qml")).toString()
        + """"
ApplicationWindow {
    visible: true; width: 900; height: 700
    color: Kirigami.Theme.backgroundColor
    ProfilePage { anchors.fill: parent; backendObject: backend; onSelectSlot: function(index) { backend.selectProfile(index); } }
}"""
    )
    # loadData can hold the Python GIL while QML resolves Python properties.
    engine.load(QUrl.fromLocalFile(str(wrapper)))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    window.requestActivate()
    settle(250)
    assert not warnings, warnings
    backend.refresh()
    settle(250)
    assert backend.connected

    def find(name):
        def visit(item):
            if item.objectName() == name:
                return item
            for child in item.childItems() if hasattr(item, "childItems") else []:
                result = visit(child)
                if result is not None:
                    return result
            return None

        obj = window.findChild(QObject, name)
        if obj is None:
            obj = visit(window.contentItem())
        assert obj is not None, name
        return obj

    def expression(obj, source):
        expr = QQmlExpression(QQmlEngine.contextForObject(obj), obj, source)
        result = expr.evaluate()
        assert not expr.hasError(), expr.error().toString()
        result = result[0] if isinstance(result, tuple) else result
        return result.toVariant() if hasattr(result, "toVariant") else result

    def click(item):
        position = item.mapToScene(
            QPointF(item.width() / 2, item.height() / 2)
        ).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, position)
        settle()

    try:
        page = find("profilesScroll")
        assert all(
            find("profileSlot" + str(index)).property("visible") for index in range(3)
        )
        click(find("profileSlot1"))
        assert backend.selectedProfileIndex == 1
        assert not backend.dirty and not backend._transport.calls
        assert not find("profileName").property("enabled")
        assert find("profileNameInfo").property("visible")
        assert (
            find("profileFileName").width()
            <= 18 * expression(page, "Kirigami.Units.gridUnit") + 1
        )
        # The real Save/Open dialog can be opened and canceled without edits.
        for control, dialog_name in (
            ("exportProfileFile", "saveProfileFileDialog"),
            ("importProfileFile", "loadProfileFileDialog"),
        ):
            click(find(control))
            dialog = find(dialog_name)
            assert dialog.property("visible")
            expression(dialog, "reject()")
            window.requestActivate()
            settle()
            assert not dialog.property("visible")
            assert not backend.dirty and not backend._transport.calls

        content = export_document(
            backend._device(),
            backend._profile(),
            "My G600 shortcuts",
            backend._set_mapping,
        )
        content["profile"]["settings"]["reportRate"] = 500
        content["profile"]["buttons"][20]["action"]["value"] = 5
        path = output / "profile.json"
        path.write_text(json.dumps(content))
        before = deepcopy(backend._draft)
        page.setProperty("loadContext", backend.capturePageContext("profiles"))
        assert expression(page, "previewFile(" + json.dumps(str(path)) + ")")
        settle()
        review = find("profileImportReview")
        assert review.property("visible")
        assert backend._draft == before
        QTest.keyClick(window, Qt.Key_Escape)
        settle()
        assert not review.property("visible")
        assert backend._draft == before and not backend._transport.calls
        assert expression(page, "previewFile(" + json.dumps(str(path)) + ")")
        settle()
        button = expression(review, "standardButton(Dialog.Ok)")
        click(button)
        assert not review.property("visible")
        assert backend.selectedProfile["reportRate"] == 500
        assert backend.selectedProfile["buttons"][20]["actionValue"] == 5
        assert not backend.selectedProfile["active"]
        assert backend.profileImportPending and not backend._transport.calls
        assert backend.resetPage(backend.capturePageContext("profiles"))
        assert not backend.profileImportPending and not backend.dirty
        # Repeated review closes safely when the selected target changes.
        assert expression(page, "previewFile(" + json.dumps(str(path)) + ")")
        settle()
        backend.selectProfile(0)
        settle()
        assert not review.property("visible")
        assert not backend.dirty and not backend._transport.calls
        window.grabWindow().save(str(output / "profile-page.png"))
        assert not warnings, warnings
        print(
            "Profile page: all slots, native dialogs, cancel, review, stage, reset and stale target passed; no transport writes."
        )
    finally:
        delete(engine)
        backend.close()


if __name__ == "__main__":
    run_ui(Path(sys.argv[1]))
