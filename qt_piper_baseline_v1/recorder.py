# SPDX-License-Identifier: GPL-2.0-or-later
"""Portable keyboard macro recorder using Qt keys and Linux evdev values."""

import time
from PySide6.QtCore import QObject, Signal, Property, Slot, QEvent, Qt
from PySide6.QtGui import QGuiApplication

_KEYS = {
    "Escape": 1,
    "Backspace": 14,
    "Tab": 15,
    "Return": 28,
    "Enter": 28,
    "Control": 29,
    "Shift": 42,
    "Alt": 56,
    "Space": 57,
    "CapsLock": 58,
    "Meta": 125,
    "Up": 103,
    "Down": 108,
    "Left": 105,
    "Right": 106,
    "Home": 102,
    "End": 107,
    "PageUp": 104,
    "PageDown": 109,
    "Insert": 110,
    "Delete": 111,
    "Minus": 12,
    "Equal": 13,
    "BracketLeft": 26,
    "BracketRight": 27,
    "Semicolon": 39,
    "Apostrophe": 40,
    "QuoteLeft": 41,
    "Backslash": 43,
    "Comma": 51,
    "Period": 52,
    "Slash": 53,
}
_KEYS.update(dict(zip("1234567890", range(2, 12), strict=True)))
_KEYS.update(dict(zip("QWERTYUIOP", range(16, 26), strict=True)))
_KEYS.update(dict(zip("ASDFGHJKL", range(30, 39), strict=True)))
_KEYS.update(dict(zip("ZXCVBNM", range(44, 51), strict=True)))
_KEYS.update({f"F{i}": 59 + i - 1 for i in range(1, 11)})
_KEYS.update({"F11": 87, "F12": 88})
QT_TO_EVDEV = {
    int(getattr(Qt.Key, "Key_" + k)): v
    for k, v in _KEYS.items()
    if hasattr(Qt.Key, "Key_" + k)
}


class MacroRecorder(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = False
        self._events = []
        self._pressed = set()
        self._last = None
        self._timed = False

    @Property(bool, notify=changed)
    def active(self):
        return self._active

    @Property("QVariantList", notify=changed)
    def events(self):
        return self._events

    @Slot(bool)
    def start(self, timed=False):
        self._events = []
        self._pressed = set()
        self._last = None
        self._timed = timed
        self._active = True
        QGuiApplication.instance().installEventFilter(self)
        self.changed.emit()

    @Slot()
    def stop(self):
        if not self._active:
            return
        QGuiApplication.instance().removeEventFilter(self)
        for key in sorted(self._pressed):
            self._events.append([2, key])
        self._pressed.clear()
        self._active = False
        self.changed.emit()

    def eventFilter(self, watched, event):
        if not self._active or event.type() not in (QEvent.KeyPress, QEvent.KeyRelease):
            return False
        if event.isAutoRepeat():
            return True
        code = QT_TO_EVDEV.get(event.key())
        if code is None:
            return True
        now = time.monotonic()
        if self._timed and self._last is not None:
            delay = min(65535, round((now - self._last) * 1000))
            if delay:
                self._events.append([3, delay])
        pressed = event.type() == QEvent.KeyPress
        if pressed:
            self._pressed.add(code)
        else:
            self._pressed.discard(code)
        self._events.append([1 if pressed else 2, code])
        self._last = now
        self.changed.emit()
        return True
