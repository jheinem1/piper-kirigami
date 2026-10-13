# SPDX-License-Identifier: GPL-2.0-or-later
"""Run with python -m qt_piper [--mock] [--screenshot path]."""

import argparse
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Piper Qt / Kirigami frontend")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use deterministic demo devices; never access hardware",
    )
    parser.add_argument(
        "--screenshot", type=Path, help="Save a native Qt rendered screenshot and exit"
    )
    parser.add_argument(
        "--headless", action="store_true", help="Use Qt offscreen software renderer"
    )
    parser.add_argument(
        "--dark", action="store_true", help="Start with the dark palette"
    )
    args = parser.parse_args()
    if args.headless:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.setdefault("QT_QUICK_BACKEND", "software")
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtGui import QGuiApplication, QFont, QIcon
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import (
        QQuickWindow,  # noqa: F401 - registers native window wrapper
    )
    from .backend import Backend
    from .recorder import MacroRecorder
    from .diagrams import DiagramCatalog, DiagramImageProvider

    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName("Piper Kirigami")
    app.setOrganizationName("libratbag")
    if not QIcon.themeName():
        QIcon.setThemeName("breeze")
    app.setFont(QFont("Noto Sans", 11))
    backend = Backend(mock=args.mock, fixture="all")
    recorder = MacroRecorder()
    app.aboutToQuit.connect(backend.close)
    diagrams = DiagramCatalog()
    engine = QQmlApplicationEngine()
    # System Kirigami imports must match the installed Qt major/minor ABI.
    for path in [
        os.environ.get("PIPER_KIRIGAMI_QML_PATH", ""),
        "/usr/lib/x86_64-linux-gnu/qt6/qml",
        "/usr/lib64/qt6/qml",
        "/usr/lib/qt6/qml",
    ]:
        if path and Path(path).exists():
            engine.addImportPath(path)
    engine.rootContext().setContextProperty("startDark", args.dark)
    engine.rootContext().setContextProperty("backend", backend)
    engine.rootContext().setContextProperty("macroRecorder", recorder)
    engine.rootContext().setContextProperty("diagrams", diagrams)
    engine.addImageProvider("piper-diagrams", DiagramImageProvider(diagrams))
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / "qml" / "Main.qml")))
    if not engine.rootObjects():
        return 2
    if args.screenshot:

        def capture():
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            ok = engine.rootObjects()[0].grabWindow().save(str(args.screenshot))
            app.exit(0 if ok else 3)

        QTimer.singleShot(1600, capture)
    result = app.exec()
    from shiboken6 import delete

    delete(engine)
    backend.close()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
