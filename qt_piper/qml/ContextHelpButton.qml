// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Controls
import org.kde.kirigami as Kirigami

ToolButton {
    id: control
    property string helpText: ""
    icon.name: "help-contextual"
    text: "Show information"
    display: AbstractButton.IconOnly
    Accessible.name: text
    Accessible.description: helpText
    checkable: true
    onClicked: if (!checked) hideTimer.stop()
    ToolTip.text: helpText
    ToolTip.visible: hovered || activeFocus || checked
    ToolTip.delay: checked || activeFocus ? 0 : Kirigami.Units.toolTipDelay
    ToolTip.timeout: -1
    onActiveFocusChanged: if (!activeFocus) checked = false
    onCheckedChanged: if (checked) hideTimer.restart()
    Keys.onEscapePressed: { checked = false; focus = false; }
    Timer { id: hideTimer; interval: 15000; onTriggered: control.checked = false }
}
