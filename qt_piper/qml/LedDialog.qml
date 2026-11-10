import QtQuick
import QtQuick.Dialogs as QtDialogs
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
    readonly property string colorValidationMessage: "Enter a six-digit hex color, such as #00aaff."
    property string backendValidation: ""
    readonly property bool durationTextAcceptable: duration.contentItem && duration.contentItem.acceptableInput !== false && duration.contentItem.text.trim() !== ""
    readonly property int enteredDuration: durationTextAcceptable ? duration.valueFromText(duration.contentItem.text, duration.locale) : duration.value
    readonly property string inputValidation: {
        if (led.colorDepth > 0 && !/^#[0-9a-fA-F]{6}$/.test(colorField.text)) return colorValidationMessage;
        if (!durationTextAcceptable || enteredDuration < duration.from || enteredDuration > duration.to || (enteredDuration-duration.from)%duration.stepSize !== 0)
            return "Enter an effect duration from "+duration.from+" to "+duration.to+" ms in steps of "+duration.stepSize+" ms.";
        return "";
    }
    function load(value) {
        colorDialog.close();
        led=value; ledIndex=value.index; backendValidation="";
        modes=value.modes || [0,1,2,3];
        modeLabels=modes.map(function(m) { return ["Off","Solid","Cycle","Breathing"][m] || String(m) });
        mode.currentIndex=Math.max(0,modes.indexOf(value.mode));
        colorField.text=value.color || "#00aaff";
        brightness.value=value.brightness === undefined ? 255 : value.brightness;
        duration.value=value.effectDuration!==undefined ? value.effectDuration : value.duration!==undefined ? value.duration : 1000;
    }
    function save() {
        if (inputValidation !== "") return;
        duration.value=enteredDuration;
        let ok=backendObject.setLed(ledIndex,"mode",modes[mode.currentIndex]);
        if (led.colorDepth > 0) ok=backendObject.setLed(ledIndex,"color",colorField.text) && ok;
        if (led.canBrightness !== false) ok=backendObject.setLed(ledIndex,"brightness",brightness.value) && ok;
        ok=backendObject.setLed(ledIndex,"effectDuration",duration.value) && ok;
        if(ok) close(); else backendValidation=backendObject.error;
    }
    Connections {
        target: duration.contentItem
        function onTextChanged() { dialog.backendValidation=""; }
    }
    // QtQuick.Dialogs uses the platform color chooser, as KDE's ColorButton
    // does. Only acceptance updates this dialog's draft; preview and Cancel
    // never stage a backend change.
    QtDialogs.ColorDialog {
        id: colorDialog
        objectName: "ledColorDialog"
        title: "Choose lighting color"
        parentWindow: dialog.parent ? dialog.parent.Window.window : null
        onAccepted: if (dialog.visible && dialog.led.colorDepth > 0) colorField.text=selectedColor.toString();
        onVisibleChanged: if (!visible) Qt.callLater(function() {
            if (dialog.visible) {
                colorButton.forceActiveFocus(Qt.PopupFocusReason);
            }
        });
    }
    onClosed: colorDialog.close()
    title: led.name || "Lighting zone " + (ledIndex+1)
    modal: true
    focus: true
    anchors.centerIn: parent
    width: Math.min(Kirigami.Units.gridUnit*34,parent ? parent.width-Kirigami.Units.largeSpacing*4 : Kirigami.Units.gridUnit*34)
    padding: Kirigami.Units.largeSpacing*2
    standardButtons: Dialog.NoButton
    contentItem: ColumnLayout {
        spacing: Kirigami.Units.largeSpacing*2
        Kirigami.FormLayout {
            id: lightingForm
            objectName: "ledForm"
            readonly property real controlWidth: Math.min(Kirigami.Units.gridUnit*18,Math.max(0,width))
            NativeComboBox {
                id: mode; objectName: "ledMode"
                Kirigami.FormData.label: "Effect:"
                Accessible.name: "Lighting effect"
                model: dialog.modeLabels
                onActivated: dialog.backendValidation=""
                Layout.fillWidth: true
                Layout.preferredWidth: lightingForm.controlWidth
                Layout.maximumWidth: lightingForm.controlWidth
            }
            RowLayout {
                Kirigami.FormData.label: "Color:"
                Kirigami.FormData.buddyFor: colorButton
                Layout.fillWidth: true
                Layout.preferredWidth: lightingForm.controlWidth
                Layout.maximumWidth: lightingForm.controlWidth
                spacing: Kirigami.Units.largeSpacing
                Button {
                    id: colorButton; objectName: "ledColorButton"
                    Layout.preferredWidth: Kirigami.Units.gridUnit*3
                    enabled: dialog.led.colorDepth > 0
                    Accessible.name: "Choose lighting color"
                    Accessible.description: "Open the system color chooser. Current color: "+colorField.text
                    ToolTip.visible: hovered
                    ToolTip.text: "Choose a color"
                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: Kirigami.Units.smallSpacing
                        radius: 1
                        color: /^#[0-9a-fA-F]{6}$/.test(colorField.text) ? colorField.text : "transparent"
                        border.color: Kirigami.Theme.disabledTextColor
                        opacity: colorButton.enabled ? 1 : 0.5
                    }
                    onClicked: {
                        colorDialog.selectedColor=/^#[0-9a-fA-F]{6}$/.test(colorField.text) ? colorField.text : (dialog.led.color || "#00aaff");
                        colorDialog.open();
                    }
                }
                TextField {
                    id: colorField; objectName: "ledColor"
                    Accessible.name: "Lighting color"
                    enabled: dialog.led.colorDepth > 0
                    onTextChanged: dialog.backendValidation=""
                    Layout.fillWidth: true; Layout.minimumWidth: 0; placeholderText: "#RRGGBB"
                    Accessible.description: "Color in hexadecimal. Use the color button to select a color visually."
                }
            }
            Label {
                visible: !(dialog.led.colorDepth > 0)
                text: "Color adjustment is not supported."
                color: Kirigami.Theme.disabledTextColor
                Layout.fillWidth: true
                Layout.preferredWidth: lightingForm.controlWidth
                Layout.maximumWidth: visible ? lightingForm.controlWidth : 0
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Kirigami.FormData.label: "Brightness:"
                Kirigami.FormData.buddyFor: brightness
                Layout.fillWidth: true
                Layout.preferredWidth: lightingForm.controlWidth
                Layout.maximumWidth: lightingForm.controlWidth
                Slider {
                    id: brightness; objectName: "ledBrightness"
                    Accessible.name: "Lighting brightness"
                    enabled: dialog.led.canBrightness !== false
                    from: 0; to: 255; stepSize: 1
                    onMoved: dialog.backendValidation=""
                    Layout.fillWidth: true
                }
                Label { text: dialog.led.canBrightness !== false ? Math.round(brightness.value/255*100) + "%" : "Not supported"; color: dialog.led.canBrightness !== false ? Kirigami.Theme.textColor : Kirigami.Theme.disabledTextColor }
            }
            RowLayout {
                Kirigami.FormData.label: "Effect duration:"
                Kirigami.FormData.buddyFor: duration
                Layout.fillWidth: true
                Layout.preferredWidth: lightingForm.controlWidth
                Layout.maximumWidth: lightingForm.controlWidth
                SpinBox { id: duration; Layout.fillWidth: true; objectName: "ledDuration"; Accessible.name: "Effect duration in milliseconds"; from: dialog.led.effectDurationMinimum===undefined ? 0 : dialog.led.effectDurationMinimum; to: dialog.led.effectDurationMaximum===undefined ? 10000 : dialog.led.effectDurationMaximum; stepSize: dialog.led.effectDurationStep || 1; editable: true }
                Label { text: "ms" }
            }
        }
        Kirigami.InlineMessage { id: validation; objectName: "ledValidation"; Layout.fillWidth: true; text: dialog.inputValidation || dialog.backendValidation || dialog.colorValidationMessage; visible: dialog.visible && (dialog.inputValidation !== "" || dialog.backendValidation !== ""); type: Kirigami.MessageType.Error }
    }
    footer: DialogButtonBox {
        Button { objectName: "ledCancel"; text: "Cancel"; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole }
        // Close only after save() accepts the draft, including backend validation.
        Button { objectName: "ledSave"; text: "OK"; Accessible.description: "Keep changes in the lighting draft and close. Apply on the Lighting page sends them to the mouse."; enabled: dialog.inputValidation === ""; DialogButtonBox.buttonRole: DialogButtonBox.ApplyRole; onClicked: dialog.save() }
        onRejected: dialog.close()
    }
}
