// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Controls as QQC2

QQC2.ComboBox {
    id: control
    // KDE's Menu-backed popup can first open with focus on its outer popup
    // item, leaving the ListView unable to receive keyboard navigation.
    // Keep the native menu, delegates and selection behavior; focus its real
    // keyboard receiver when the opening transition completes.
    Connections {
        target: control.popup
        function onOpened() {
            const content = control.popup.contentItem;
            if (content) content.forceActiveFocus(Qt.PopupFocusReason);
        }
    }
}
