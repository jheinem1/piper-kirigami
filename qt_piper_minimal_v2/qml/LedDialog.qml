// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
Dialog {
    id: dialog
    objectName: "ledDialog"
    property var backendObject
    property int ledIndex: -1
    property var led: ({})
    property var modes: [0,1,2,3]
    property var modeLabels: ["Off","Solid","Cycle","Breathing"]
    function load(value) { led=value; ledIndex=value.index; validation.visible=false; modes=value.modes || [0,1,2,3]; modeLabels=modes.map(function(m) { return ["Off","Solid","Cycle","Breathing"][m] || String(m) }); mode.currentIndex=Math.max(0,modes.indexOf(value.mode)); colorField.text=value.color || "#00aaff"; brightness.value=value.brightness === undefined ? 255 : value.brightness; duration.value=value.effectDuration || value.duration || 1000 }
    function save() { if(!/^#[0-9a-fA-F]{6}$/.test(colorField.text)) { validation.visible=true; return } let ok=backendObject.setLed(ledIndex,"mode",modes[mode.currentIndex]); if (led.colorDepth > 0) ok=backendObject.setLed(ledIndex,"color",colorField.text) && ok; if (led.canBrightness !== false) ok=backendObject.setLed(ledIndex,"brightness",brightness.value) && ok; ok=backendObject.setLed(ledIndex,"effectDuration",duration.value) && ok; if(ok) close(); else { validation.text=backendObject.error; validation.visible=true } }
    title: "Configure " + (led.name || "LED " + (ledIndex+1)); modal: true; anchors.centerIn: parent; width: 470; padding: 24; standardButtons: Dialog.NoButton
    contentItem: ColumnLayout {
        spacing: 14
        Label { text: "Lighting effect"; font.bold: true }
        ComboBox { id: mode; objectName: "ledMode"; model: dialog.modeLabels; Layout.fillWidth: true }
        RowLayout {
            Label { text: "Color" }
            Rectangle { width: 32; height: 32; radius: 6; color: /^#[0-9a-fA-F]{6}$/.test(colorField.text) ? colorField.text : "transparent"; border.color: Kirigami.Theme.textColor }
            TextField { id: colorField; objectName: "ledColor"; enabled: dialog.led.colorDepth > 0; Layout.fillWidth: true; placeholderText: "#RRGGBB" }
        }
        Label { text: "Brightness" }
        Slider { id: brightness; objectName: "ledBrightness"; enabled: dialog.led.canBrightness !== false; from: 0; to: 255; stepSize: 1; Layout.fillWidth: true }
        RowLayout { Label { text: "Effect duration (ms)" } SpinBox { id: duration; from: 0; to: 10000; stepSize: 100; editable: true } }
        Label { id: validation; text: "Enter a six-digit hex color, such as #00aaff."; visible: false; color: Kirigami.Theme.negativeTextColor }
        RowLayout { Item { Layout.fillWidth: true } Button { objectName: "ledCancel"; text: "Cancel"; onClicked: dialog.close() } Button { text: "Save lighting"; objectName: "ledSave"; highlighted: true; onClicked: dialog.save() } }
    }
}
