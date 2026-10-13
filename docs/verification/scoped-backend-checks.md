# Scoped backend and packaging checks

Cloud run, 2026-10-13, Qt/PySide6 6.8.2.

Command:

```sh
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software python -m pytest -q tests/qt/test_backend.py tests/test_qt_diagrams.py tests/qt/test_handbook.py tests/qt/test_desktop_style.py packaging/tests/test_packaging.py
```

Result: **126 passed, 1,434 subtests passed in 47.19 seconds**. This includes 98 scoped backend tests and isolated D-Bus service traffic. No physical mouse writes occur in these tests.

Backend SHA256: `ab95cfc1c4acd70b7490f4c4c316fa0ee7b78908ecb016374641541fb3babd61`.

Target SDK Qt/PySide6 6.11.2 icon lookup and 32-pixel pixmap checks passed independently. The previous prototype also passed real Wayland/KWin device/profile/LED selector interaction with mouse and arrows+Return. Offscreen routing and Home-key assumptions differ; the test harness now uses observed indices and relative arrows. Latest-source target validation still remains necessary.
