// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import org.kde.kirigami as Kirigami

Kirigami.ContextualHelpButton {
    property alias helpText: control.toolTipText
    id: control
    text: "Show information"
    Accessible.name: text
    Keys.onEscapePressed: toolTipVisible = false
    onVisibleChanged: if (!visible) toolTipVisible = false
}
