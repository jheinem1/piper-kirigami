"""Native KDE desktop controls and distribution-provided Breeze color schemes."""

import configparser
import os
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QObject,
    Property,
    QStandardPaths,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication, QStyleFactory


def prepare_desktop():
    """Call before creating the application or loading any QML."""
    for path in [
        "/usr/lib/x86_64-linux-gnu/qt6/plugins",
        "/usr/lib64/qt6/plugins",
        "/usr/lib/qt6/plugins",
    ]:
        if Path(path).exists():
            QCoreApplication.addLibraryPath(path)
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "org.kde.desktop")
    QQuickStyle.setStyle("org.kde.desktop")


def configure_icon_search_paths():
    """Keep platform/resource paths and discover installed XDG icon themes.

    Qt's offscreen platform may expose only :/icons. QWidget icons, including
    the handbook toolbar, still need the runtime's installed icon directories.
    This does not select a theme or replace the user's configured fallback.
    """
    paths = list(QIcon.themeSearchPaths())
    for root in QStandardPaths.standardLocations(QStandardPaths.GenericDataLocation):
        directory = Path(root) / "icons"
        path = str(directory)
        if directory.is_dir() and path not in paths:
            paths.append(path)
    QIcon.setThemeSearchPaths(paths)


def configure_application(app, force_breeze=True):
    configure_icon_search_paths()
    if not force_breeze:
        if not QIcon.themeName():
            QIcon.setThemeName("breeze")
        return
    if "Breeze" not in QStyleFactory.keys():
        raise RuntimeError(
            "The native KDE Breeze style is required for this design preview."
        )
    app.setStyle("Breeze")
    QIcon.setThemeName("breeze")


class DesktopStyle(QObject):
    changed = Signal()

    def __init__(self, dark=None, parent=None):
        super().__init__(parent)
        self._dark = None
        if dark is None:
            self._follow_system_palette(QApplication.instance().palette())
            QApplication.instance().paletteChanged.connect(self._follow_system_palette)
        else:
            self.setDark(dark)

    def _follow_system_palette(self, palette):
        dark = palette.color(QPalette.Window).lightness() < 128
        if dark != self._dark:
            self._dark = dark
            self.changed.emit()

    @Property(bool, notify=changed)
    def dark(self):
        return bool(self._dark)

    @Property(str, constant=True)
    def name(self):
        return "KDE QQC2 Desktop + Breeze"

    @Slot(bool)
    def setDark(self, dark):
        if self._dark is dark:
            return
        name = "BreezeDark.colors" if dark else "BreezeLight.colors"
        paths = [
            Path(root) / "color-schemes" / name
            for root in os.environ.get(
                "XDG_DATA_DIRS", "/usr/local/share:/usr/share"
            ).split(":")
        ]
        path = next((p for p in paths if p.exists()), None)
        if path is None:
            raise RuntimeError(f"The installed KDE color scheme {name} is missing.")
        config = configparser.ConfigParser()
        config.read(path)
        app = QApplication.instance()
        palette = app.style().standardPalette()
        roles = {
            QPalette.Window: ("Window", "BackgroundNormal"),
            QPalette.WindowText: ("Window", "ForegroundNormal"),
            QPalette.Base: ("View", "BackgroundNormal"),
            QPalette.AlternateBase: ("View", "BackgroundAlternate"),
            QPalette.Text: ("View", "ForegroundNormal"),
            QPalette.Button: ("Button", "BackgroundNormal"),
            QPalette.ButtonText: ("Button", "ForegroundNormal"),
            QPalette.Highlight: ("Selection", "BackgroundNormal"),
            QPalette.HighlightedText: ("Selection", "ForegroundNormal"),
            QPalette.Link: ("View", "ForegroundLink"),
            QPalette.LinkVisited: ("View", "ForegroundVisited"),
            QPalette.ToolTipBase: ("Tooltip", "BackgroundNormal"),
            QPalette.ToolTipText: ("Tooltip", "ForegroundNormal"),
        }
        for role, (section, key) in roles.items():
            value = config.get("Colors:" + section, key, fallback="")
            if value:
                palette.setColor(role, QColor(*map(int, value.split(","))))
        for role in [QPalette.WindowText, QPalette.Text, QPalette.ButtonText]:
            palette.setColor(
                QPalette.Disabled,
                role,
                QColor(
                    *map(int, config["Colors:Window"]["ForegroundInactive"].split(","))
                ),
            )
        app.setProperty("KDE_COLOR_SCHEME_PATH", str(path))
        app.setPalette(palette)
        self._dark = dark
        self.changed.emit()
