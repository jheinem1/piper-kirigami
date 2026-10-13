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
    title: led.name || "Lighting zone " + (ledIndex+1)
    modal: true; anchors.centerIn: parent
    width: Kirigami.Units.gridUnit*29
    padding: Kirigami.Units.largeSpacing*2
    standardButtons: Dialog.NoButton
    contentItem: ColumnLayout {
        spacing: Kirigami.Units.largeSpacing*2
        Kirigami.FormLayout {
            ComboBox {
                id: mode; objectName: "ledMode"
                Kirigami.FormData.label: "Effect:"
                Accessible.name: "Lighting effect"
                model: dialog.modeLabels
                onActivated: dialog.backendValidation=""
                Layout.preferredWidth: Kirigami.Units.gridUnit*14
            }
            RowLayout {
                Kirigami.FormData.label: "Color:"
                spacing: Kirigami.Units.largeSpacing
                Rectangle {
                    implicitWidth: Kirigami.Units.iconSizes.smallMedium; implicitHeight: implicitWidth
                    color: /^#[0-9a-fA-F]{6}$/.test(colorField.text) ? colorField.text : "transparent"
                    border.color: Kirigami.Theme.disabledTextColor
                    enabled: colorField.enabled
                    opacity: enabled ? 1 : 0.5
                }
                TextField {
                    id: colorField; objectName: "ledColor"
                    Accessible.name: "Lighting color"
                    enabled: dialog.led.colorDepth > 0
                    onTextChanged: dialog.backendValidation=""
                    Layout.fillWidth: true; placeholderText: "#RRGGBB"
                }
            }
            Label { visible: !(dialog.led.colorDepth > 0); text: "Color adjustment is not supported."; color: Kirigami.Theme.disabledTextColor }
            RowLayout {
                Kirigami.FormData.label: "Brightness:"
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
                SpinBox { id: duration; objectName: "ledDuration"; Accessible.name: "Effect duration in milliseconds"; from: dialog.led.effectDurationMinimum===undefined ? 0 : dialog.led.effectDurationMinimum; to: dialog.led.effectDurationMaximum===undefined ? 10000 : dialog.led.effectDurationMaximum; stepSize: dialog.led.effectDurationStep || 1; editable: true }
                Label { text: "ms" }
            }
        }
        Kirigami.InlineMessage { id: validation; objectName: "ledValidation"; Layout.fillWidth: true; text: dialog.inputValidation || dialog.backendValidation || dialog.colorValidationMessage; visible: dialog.visible && (dialog.inputValidation !== "" || dialog.backendValidation !== ""); type: Kirigami.MessageType.Error }
    }
    footer: DialogButtonBox {
        Button { objectName: "ledCancel"; text: "Cancel"; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole }
        Button { objectName: "ledSave"; text: "Save lighting"; enabled: dialog.inputValidation === ""; DialogButtonBox.buttonRole: DialogButtonBox.ApplyRole; onClicked: dialog.save() }
        onRejected: dialog.close()
    }
}
