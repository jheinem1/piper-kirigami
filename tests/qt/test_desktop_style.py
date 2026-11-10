# SPDX-License-Identifier: GPL-2.0-or-later
"""Production styling keeps the platform's font, style and palette."""

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_system_style_and_palette_are_preserved():
    script = """
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QPalette, QColor, QIcon
from qt_piper.desktop_style import configure_application, DesktopStyle
app = QApplication([])
app.setFont(QFont("Sans Serif", 14))
QIcon.setThemeName("test-system-icons")
style = app.style().objectName()
palette = app.palette()
palette.setColor(QPalette.Window, QColor("#181818"))
palette.setColor(QPalette.Highlight, QColor("#6c53a6"))
palette.setColor(QPalette.Accent, QColor("#926ee4"))
app.setPalette(palette)
configure_application(app, force_breeze=False)
controller = DesktopStyle()
assert app.style().objectName() == style
assert app.font().pointSize() == 14
assert QIcon.themeName() == "test-system-icons"
assert app.palette().color(QPalette.Window).name() == "#181818"
assert controller.dark
assert not controller.previewMode
assert app.palette().color(QPalette.Highlight).name() == "#6c53a6"
assert app.palette().color(QPalette.Accent).name() == "#926ee4"
# A production controller must not load a stock scheme or drop custom accents.
controller.setDark(False)
assert controller.dark
assert not app.property("KDE_COLOR_SCHEME_PATH")
assert app.palette().color(QPalette.Highlight).name() == "#6c53a6"
assert app.palette().color(QPalette.Accent).name() == "#926ee4"
palette.setColor(QPalette.Window, QColor("#fafafa"))
app.setPalette(palette)
app.processEvents()
assert not controller.dark
assert app.palette().color(QPalette.Highlight).name() == "#6c53a6"
assert app.palette().color(QPalette.Accent).name() == "#926ee4"
assert app.font().pointSize() == 14
"""
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_production_kirigami_colors_ignore_preview_requests():
    script = '''
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from qt_piper.desktop_style import prepare_desktop, configure_application, DesktopStyle
prepare_desktop()
app = QApplication([])
configure_application(app, force_breeze=False)
controller = DesktopStyle()
engine = QQmlApplicationEngine()
engine.loadData(b"""import QtQuick
import QtQuick.Controls
import org.kde.kirigami as K
K.ApplicationWindow {
    visible: false
    property color nativeHighlight: K.Theme.highlightColor
    property color nativeFocus: K.Theme.focusColor
    property color nativeBackground: K.Theme.backgroundColor
    Button { highlighted: true; text: "Probe" }
}""", QUrl())
assert engine.rootObjects(), "Hidden Kirigami window failed to load"
window = engine.rootObjects()[0]
def snapshot():
    return tuple(window.property(name).name() for name in
                 ("nativeHighlight", "nativeFocus", "nativeBackground"))
def check():
    try:
        before = snapshot()
        assert before[0] != before[2], before  # Reject uninitialized all-black colors.
        assert not controller.previewMode
        assert not app.property("KDE_COLOR_SCHEME_PATH")
        for dark in (False, True):
            controller.setDark(dark)
            app.processEvents()
            assert snapshot() == before, (before, snapshot())
            assert not app.property("KDE_COLOR_SCHEME_PATH")
        assert not window.isVisible() and not window.isActive()
        app.exit(0)
    except Exception:
        import traceback
        traceback.print_exc()
        app.exit(1)
QTimer.singleShot(150, check)
raise SystemExit(app.exec())
'''
    env = os.environ.copy()
    if not env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY"):
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
