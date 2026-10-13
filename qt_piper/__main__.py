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
    from PySide6.QtWidgets import QApplication
    from .desktop_style import prepare_desktop, configure_application, DesktopStyle
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import (
        QQuickWindow,  # noqa: F401 - registers native window wrapper
    )
    from .backend import Backend
    from .help import Handbook
    from .recorder import MacroRecorder
    from .diagrams import DiagramCatalog, DiagramImageProvider

    prepare_desktop()
    app = QApplication(sys.argv[:1])
    app.setDesktopFileName(
        os.environ.get("FLATPAK_ID", "org.freedesktop.Piper.Kirigami")
    )
    configure_application(app, force_breeze=args.mock or args.dark)
    desktop_style = DesktopStyle(True if args.dark else None)
    app.setApplicationName("Piper Kirigami")
    app.setOrganizationName("libratbag")
    backend = Backend(mock=args.mock, fixture="all")
    recorder = MacroRecorder()
    handbook = Handbook()
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
    engine.rootContext().setContextProperty("desktopStyle", desktop_style)
    engine.rootContext().setContextProperty("startDark", args.dark)
    engine.rootContext().setContextProperty("backend", backend)
    engine.rootContext().setContextProperty("macroRecorder", recorder)
    engine.rootContext().setContextProperty("handbook", handbook)
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
