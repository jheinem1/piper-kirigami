# SPDX-License-Identifier: GPL-2.0-or-later
"""Packaged, offline handbook using Qt Widgets already required by the app."""

from pathlib import Path

from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtGui import (
    QDesktopServices,
    QIcon,
    QKeySequence,
    QShortcut,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

HANDBOOK_PATH = Path(__file__).with_name("help") / "handbook.html"
# QML supplies topic identifiers, never filenames or URLs.
HELP_TOPICS = frozenset(
    {
        "contents",
        "start",
        "drafts",
        "buttons",
        "gshift",
        "macros",
        "sensitivity",
        "lighting",
        "profiles",
        "advanced",
        "search",
        "troubleshooting",
        "flatpak",
        "limits",
        "assignment-write-scope",
        "assignment-button",
        "assignment-key",
        "assignment-special",
        "assignment-macro",
        "assignment-none",
    }
)


class HandbookDialog(QDialog):
    """A searchable local document, with no browser engine or network dependency."""

    def __init__(self):
        super().__init__()
        self.setObjectName("handbookDialog")
        self.setProperty("helpTopic", "contents")
        self.setWindowTitle("Piper Kirigami Handbook")
        self.setWindowIcon(QIcon.fromTheme("help-contents"))
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.resize(850, 680)
        self.setMinimumSize(560, 400)
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        contents = QPushButton(QIcon.fromTheme("go-home"), "Contents")
        contents.setObjectName("handbookContents")
        toolbar.addWidget(contents)
        self.search = QLineEdit()
        self.search.setObjectName("handbookSearch")
        self.search.setPlaceholderText("Find in handbook…")
        self.search.setAccessibleName("Find in handbook")
        self.search.setClearButtonEnabled(True)
        toolbar.addWidget(self.search, 1)
        self.previous = QPushButton(QIcon.fromTheme("go-up"), "Previous")
        self.previous.setObjectName("handbookPrevious")
        self.previous.setToolTip("Find previous (Shift+F3)")
        self.next = QPushButton(QIcon.fromTheme("go-down"), "Next")
        self.next.setObjectName("handbookNext")
        self.next.setToolTip("Find next (F3)")
        toolbar.addWidget(self.previous)
        toolbar.addWidget(self.next)
        layout.addLayout(toolbar)
        self.status = QLabel()
        self.status.setObjectName("handbookSearchStatus")
        self.status.setAccessibleName("Handbook search result")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.browser = QTextBrowser()
        self.browser.setObjectName("handbookText")
        self.browser.setAccessibleName("Piper Kirigami Handbook")
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.document().setDocumentMargin(18)
        try:
            self.browser.setHtml(HANDBOOK_PATH.read_text(encoding="utf-8"))
        except OSError:
            self.browser.setPlainText(
                "The packaged Piper Kirigami handbook could not be read. "
                "Please reinstall the application package."
            )
        self.browser.anchorClicked.connect(self._open_link)
        layout.addWidget(self.browser, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.setObjectName("handbookButtons")
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
        # An Enter in Find should find the next match, not close the window.
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        contents.clicked.connect(self._contents)
        self.search.textChanged.connect(self._search_changed)
        self.search.returnPressed.connect(lambda: self.find_text())
        self.previous.clicked.connect(lambda: self.find_text(backward=True))
        self.next.clicked.connect(lambda: self.find_text())
        QShortcut(QKeySequence.StandardKey.Find, self, activated=self.focus_search)
        QShortcut(QKeySequence("F3"), self, activated=lambda: self.find_text())
        QShortcut(
            QKeySequence("Shift+F3"),
            self,
            activated=lambda: self.find_text(backward=True),
        )
        self._search_changed("")

    def focus_search(self):
        self.search.setFocus(Qt.ShortcutFocusReason)
        self.search.selectAll()

    def show_topic(self, topic):
        """Navigate only within the installed handbook, clearing a previous search."""
        if topic not in HELP_TOPICS:
            return False
        self.search.clear()
        cursor = self.browser.textCursor()
        cursor.clearSelection()
        self.browser.setTextCursor(cursor)
        self.browser.scrollToAnchor(topic)
        self.browser.setFocus(Qt.OtherFocusReason)
        self.setProperty("helpTopic", topic)
        return True

    def _contents(self):
        self.show_topic("contents")

    def _open_link(self, url):
        if (
            url.isRelative()
            and not url.path()
            and not url.query()
            and url.fragment() in HELP_TOPICS
        ):
            self.show_topic(url.fragment())
        # Public support links use the desktop's normal URL handler/portal.
        elif url.scheme() == "https" and not QDesktopServices.openUrl(url):
            self.status.setText("Could not open the link in your browser.")

    def _search_changed(self, text):
        self.previous.setEnabled(bool(text))
        self.next.setEnabled(bool(text))
        if not text:
            cursor = self.browser.textCursor()
            cursor.clearSelection()
            self.browser.setTextCursor(cursor)
            self.status.setText("Offline help · Ctrl+F to find · Esc to close")
            return
        self.browser.moveCursor(QTextCursor.Start)
        self.find_text()

    def find_text(self, backward=False):
        text = self.search.text()
        if not text:
            return
        flags = QTextDocument.FindBackward if backward else QTextDocument.FindFlags()
        found = self.browser.find(text, flags)
        wrapped = False
        if not found:
            self.browser.moveCursor(QTextCursor.End if backward else QTextCursor.Start)
            found = self.browser.find(text, flags)
            wrapped = found
        if not found:
            self.status.setText("No matches")
        elif wrapped:
            self.status.setText(
                "Search wrapped to the end"
                if backward
                else "Search wrapped to the beginning"
            )
        else:
            self.status.setText("Match found · F3 for next · Shift+F3 for previous")


class Handbook(QObject):
    """QML-facing controller; keep one window and preserve its reading position."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dialog = None
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.close)

    @Slot()
    def showHelp(self):
        if self._dialog is None:
            self._dialog = HandbookDialog()
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()

    @Slot(str, result=bool)
    def hasTopic(self, topic):
        """Whether matching authored help exists for this exact local topic."""
        return isinstance(topic, str) and topic in HELP_TOPICS

    @Slot(str, result=bool)
    def showTopic(self, topic):
        """Open matching contextual help only; missing topics do not open a window."""
        if not self.hasTopic(topic):
            return False
        self.showHelp()
        return self._dialog.show_topic(topic)

    @Slot()
    def close(self):
        if self._dialog is not None:
            self._dialog.close()
