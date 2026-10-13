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
app.setPalette(palette)
configure_application(app, force_breeze=False)
controller = DesktopStyle()
assert app.style().objectName() == style
assert app.font().pointSize() == 14
assert QIcon.themeName() == "test-system-icons"
assert app.palette().color(QPalette.Window).name() == "#181818"
assert controller.dark
palette.setColor(QPalette.Window, QColor("#fafafa"))
app.setPalette(palette)
app.processEvents()
assert not controller.dark
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
