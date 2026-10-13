#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Fail early if the Flatpak Qt, PySide and native Breeze payload disagree."""

import json
import os
from pathlib import Path
import sys

import PySide6
from PySide6 import (  # noqa: F401 - runtime module availability probe
    QtCore,
    QtGui,
    QtQml,
    QtQuick,
    QtQuickControls2,
    QtSvg,
    QtWidgets,
)
import dbus_next
import shiboken6

# Check the installed application's initialization, not a test-only substitute.
sys.path.insert(0, "/app/share/piper-kirigami")
from qt_piper.desktop_style import configure_icon_search_paths

assert (
    PySide6.__version__.split(".")[:2] == QtCore.qVersion().split(".")[:2]
), f"PySide {PySide6.__version__} != Qt {QtCore.qVersion()}; rebuild with matching KDE/PySide refs"
assert PySide6.__version__.startswith("6.11."), PySide6.__version__
app = QtWidgets.QApplication([])
assert "Breeze" in QtWidgets.QStyleFactory.keys(), "Breeze QWidget style is missing"
roots = os.environ.get("XDG_DATA_DIRS", "/app/share:/usr/share").split(":")
schemes = {}
for name in ("BreezeLight.colors", "BreezeDark.colors"):
    matches = [
        str(Path(root) / "color-schemes" / name)
        for root in roots
        if (Path(root) / "color-schemes" / name).is_file()
    ]
    assert matches, f"Required color scheme {name} is missing"
    schemes[name] = matches[0]
configure_icon_search_paths()
QtGui.QIcon.setThemeName("breeze")
mouse_icon = QtGui.QIcon.fromTheme("input-mouse")
icon_context = {
    "theme": QtGui.QIcon.themeName(),
    "theme_search_paths": QtGui.QIcon.themeSearchPaths(),
    "fallback_theme": QtGui.QIcon.fallbackThemeName(),
    "fallback_search_paths": QtGui.QIcon.fallbackSearchPaths(),
    "platform": app.platformName(),
}
assert not mouse_icon.isNull(), f"Breeze input-mouse lookup failed: {icon_context}"
assert not mouse_icon.pixmap(
    32, 32
).isNull(), f"Breeze input-mouse was found but could not render: {icon_context}"
handbook_path = Path("/app/share/piper-kirigami/qt_piper/help/handbook.html")
assert handbook_path.is_file(), "The installed offline handbook is missing"
assert "Piper Kirigami Handbook" in handbook_path.read_text(encoding="utf-8")
print(
    json.dumps(
        {
            "python": sys.version,
            "handbook": str(handbook_path),
            "pyside": PySide6.__version__,
            "qt": QtCore.qVersion(),
            "shiboken": shiboken6.__version__,
            "qt_prefix": QtCore.QLibraryInfo.path(QtCore.QLibraryInfo.PrefixPath),
            "qml_imports": QtCore.QLibraryInfo.path(QtCore.QLibraryInfo.QmlImportsPath),
            "styles": QtWidgets.QStyleFactory.keys(),
            "icons": icon_context,
            "color_schemes": schemes,
            "dbus_next": str(Path(dbus_next.__file__)),
        },
        indent=2,
    )
)
