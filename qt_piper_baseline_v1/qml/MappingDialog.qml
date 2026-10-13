// SPDX-License-Identifier: GPL-2.0-or-later
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
Dialog {
    id: dialog
    objectName: "mappingDialog"
    property var backendObject
    onClosed: if (macroRecorder.active) macroRecorder.stop()
    Connections { target: macroRecorder; function onChanged() { if (!macroRecorder.active && macroRecorder.events.length) macroJson.text=JSON.stringify(macroRecorder.events) } }
    property int buttonIndex: -1
    property var mapping: ({})
    property string validation: ""
    property var types: ["none", "button", "key", "special", "macro"]
    property var typeLabels: ["Disabled", "Mouse button", "Keyboard key", "Special action", "Macro"]
    property var macroEvents: []
    function load(button) {
        mapping=button; buttonIndex=button.index; validation="";
        types=["none","button","key","special","macro"].filter(function(t) { return (button.actionTypes || []).indexOf(t) >= 0 });
        let labels={none:"Disabled",button:"Mouse button",key:"Keyboard key",special:"Special action",macro:"Macro / key combination"};
        typeLabels=types.map(function(t) { return labels[t] });
        let t=types.indexOf(button.actionType); actionType.currentIndex=Math.max(0,t);
        mouseButton.value=button.actionType === "button" ? Number(button.actionValue) : 1;
        keyCode.value=button.actionType === "key" ? Number(button.actionValue) : 30;
        let ss=backendObject.specialActions || []; specialAction.currentIndex=0;
        for (let i=0;i<ss.length;i++) if (ss[i].value === button.actionValue) specialAction.currentIndex=i;
        macroEvents=button.actionType === "macro" ? JSON.parse(JSON.stringify(button.actionValue || [])) : [];
        macroJson.text=JSON.stringify(macroEvents);
    }
    function save() {
        let type=types[actionType.currentIndex]; let value=0;
        if(type === "button") value=mouseButton.value;
        else if(type === "key") value=keyCode.value;
        else if(type === "special") value=specialAction.currentValue;
        else if(type === "macro") {
            try { value=JSON.parse(macroJson.text); if(!Array.isArray(value)) throw "Expected an event list"; for(let e of value) if(!Array.isArray(e)||e.length!==2||![1,2,3].includes(e[0])||!Number.isInteger(e[1])||e[1]<0) throw "Each event must be [type, non-negative integer]"; }
            catch(e) { validation="Invalid macro: " + e; return }
        }
        if(backendObject.setButtonMapping(buttonIndex,type,value)) dialog.close();
        else validation=backendObject.error;
    }
    title: "Configure " + (mapping.label || "button " + (buttonIndex+1))
    modal: true; anchors.centerIn: parent; width: 590
    standardButtons: Dialog.NoButton
    contentItem: ColumnLayout {
        spacing: 14
        Label { text: "Assignment"; font.bold: true }
        ComboBox { id: actionType; objectName: "mappingType"; model: dialog.typeLabels; Layout.fillWidth: true }
        RowLayout {
            visible: dialog.types[actionType.currentIndex] === "button"
            Label { text: "Mouse button number" }
            SpinBox { id: mouseButton; objectName: "mouseButtonNumber"; from: 1; to: 32; editable: true }
        }
        ColumnLayout {
            visible: dialog.types[actionType.currentIndex] === "key"; Layout.fillWidth: true
            ComboBox { id: keyPicker; model: backendObject.keyChoices || []; textRole: "label"; valueRole: "value"; Layout.fillWidth: true; onActivated: keyCode.value=currentValue }
            RowLayout { Label { text: "Linux keycode" } SpinBox { id: keyCode; objectName: "keyCode"; from: 1; to: 767; editable: true } }
            Label { text: "For chords, choose Macro and add key press/release events."; opacity: 0.65; wrapMode: Text.WordWrap; Layout.fillWidth: true }
        }
        ComboBox { id: specialAction; objectName: "specialAction"; visible: dialog.types[actionType.currentIndex] === "special"; model: backendObject.specialActions || []; textRole: "label"; valueRole: "value"; Layout.fillWidth: true }
        ColumnLayout {
            visible: dialog.types[actionType.currentIndex] === "macro"; Layout.fillWidth: true; spacing: 10
            Label { text: "Macro sequence"; font.bold: true }
            RowLayout {
                ComboBox { id: eventType; model: ["Key press", "Key release", "Wait (ms)"]; Layout.fillWidth: true }
                SpinBox { id: eventValue; from: 0; to: 65535; value: 30; editable: true }
                Button { text: "Add"; onClicked: { try { let ev=JSON.parse(macroJson.text); ev.push([eventType.currentIndex+1,eventValue.value]); macroJson.text=JSON.stringify(ev) } catch(e) { dialog.validation="Correct the JSON before adding an event." } } }
            }
            ScrollView { Layout.fillWidth: true; Layout.preferredHeight: 140
                TextArea { id: macroJson; objectName: "macroJson"; text: "[]"; wrapMode: TextEdit.Wrap; font.family: "monospace" }
            }
            Label { text: "Each event is [type, value]. Types: 1 = press, 2 = release, 3 = delay in milliseconds. Keys use Linux evdev codes. Example Ctrl+C: [[1,29],[1,46],[2,46],[2,29]]."; wrapMode: Text.WordWrap; Layout.fillWidth: true; opacity: 0.65; font.pixelSize: 12 }
            RowLayout { Button { text: macroRecorder.active ? "Stop recording" : "Record keys"; objectName: "recordMacro"; onClicked: macroRecorder.active ? macroRecorder.stop() : macroRecorder.start(timedRecording.checked) } CheckBox { id: timedRecording; text: "Timing" } }
            Label { visible: macroRecorder.active; text: "Recording… Press your shortcut, then click Stop recording."; color: Kirigami.Theme.linkColor }
            RowLayout { Button { text: "Clear"; onClicked: macroJson.text="[]" } Button { text: "Insert Ctrl+C"; onClicked: macroJson.text="[[1,29],[1,46],[2,46],[2,29]]" } }
        }
        Kirigami.InlineMessage { text: dialog.validation; visible: dialog.validation !== ""; type: Kirigami.MessageType.Error; Layout.fillWidth: true }
        RowLayout { Item { Layout.fillWidth: true } Button { text: "Cancel"; objectName: "mappingCancel"; onClicked: dialog.close() } Button { text: "Save assignment"; objectName: "mappingSave"; highlighted: true; onClicked: dialog.save() } }
    }
}
